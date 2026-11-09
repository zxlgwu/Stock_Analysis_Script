"""Role routing, response cache, retries, schema repair, and the budget guard."""

from __future__ import annotations

import hashlib
import json
import time
from datetime import datetime, timedelta, timezone
from typing import Callable

from pydantic import BaseModel, ValidationError

from stock_agent.core.config import Settings
from stock_agent.db.repository import Database
from stock_agent.llm.base import BudgetExceeded, LLMProvider, LLMResponseError, LLMResult, Message
from stock_agent.llm.litellm_provider import LiteLLMProvider
from stock_agent.llm.local_embed import LocalEmbedProvider


def _extract_json(text: str) -> str:
    start = text.find("{")
    end = text.rfind("}")
    if start >= 0 and end > start:
        return _close_json(text[start : end + 1])
    start = text.find("[")
    end = text.rfind("]")
    if start >= 0 and end > start:
        return _close_json(text[start : end + 1])
    return _close_json(text)


def _close_json(text: str) -> str:
    """Local models often hit the token cap mid-object; close open brackets so parse can recover."""
    trimmed = text.strip()
    if trimmed.count("[") > trimmed.count("]"):
        trimmed += "]" * (trimmed.count("[") - trimmed.count("]"))
    if trimmed.count("{") > trimmed.count("}"):
        trimmed += "}" * (trimmed.count("{") - trimmed.count("}"))
    return trimmed


def parse_schema(text: str, schema: type[BaseModel]) -> BaseModel | None:
    blob = _extract_json(text)
    for candidate in (blob, _trim_to_last_complete_object(blob)):
        try:
            return schema.model_validate_json(candidate)
        except (ValidationError, ValueError):
            continue
    return None


def _trim_to_last_complete_object(text: str) -> str:
    idx = text.rfind("},")
    if idx < 0:
        return text
    return _close_json(text[: idx + 1] + "]}")


def _prompt_hash(model: str, messages: list[Message], schema: type[BaseModel] | None) -> str:
    payload = {
        "model": model,
        "messages": [message.as_dict() for message in messages],
        "schema": None if schema is None else schema.__name__,
    }
    encoded = json.dumps(payload, sort_keys=True).encode()
    return hashlib.sha256(encoded).hexdigest()


class Router:
    def __init__(
        self,
        settings: Settings,
        db: Database,
        providers: dict[str, LLMProvider] | None = None,
        *,
        clock: Callable[[], datetime] | None = None,
        sleep: Callable[[float], None] | None = None,
        max_attempts: int = 3,
    ):
        self.settings = settings
        self.db = db
        self.providers = providers or {
            "litellm": LiteLLMProvider(),
            "local": LocalEmbedProvider(),
        }
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self.sleep = sleep or time.sleep
        self.max_attempts = max_attempts

    def complete(
        self,
        role: str,
        messages: list[Message],
        *,
        response_schema: type[BaseModel] | None = None,
        temperature: float = 0.0,
        max_tokens: int | None = None,
    ) -> LLMResult:
        provider, model = self._resolve(role)
        cache_key = _prompt_hash(model, messages, response_schema)
        if self.settings.llm_cache:
            cached = self.db.get_llm_cache(model, cache_key)
            if cached is not None:
                result = _result_from_cache(cached, provider.name, model)
                if response_schema is not None:
                    result.parsed = parse_schema(result.text, response_schema)
                self._log(role, result, cache_hit=True)
                return result

        self._check_budget()
        result = self._call_with_retry(
            provider, model, messages, temperature=temperature, max_tokens=max_tokens
        )
        if response_schema is not None:
            parsed = parse_schema(result.text, response_schema)
            if parsed is None:
                repair = list(messages) + [
                    Message("assistant", result.text[:2000]),
                    Message(
                        "user",
                        "The previous reply was not valid JSON. Return only JSON matching this schema:\n"
                        + json.dumps(response_schema.model_json_schema()),
                    ),
                ]
                result = self._call_with_retry(
                    provider, model, repair, temperature=0.0, max_tokens=max_tokens
                )
                parsed = parse_schema(result.text, response_schema)
                if parsed is None:
                    raise LLMResponseError(result.text[:500])
            result.parsed = parsed
        self._log(role, result, cache_hit=False)
        if self.settings.llm_cache:
            self.db.put_llm_cache(model, cache_key, _cache_payload(result), self.clock())
        return result

    def embed(self, texts: list[str]) -> list[list[float]]:
        provider, model = self._resolve("embed")
        return provider.embed(texts, model=model)

    def _resolve(self, role: str) -> tuple[LLMProvider, str]:
        if role not in self.settings.llm_roles:
            raise KeyError(f"No LLM role named {role!r} in config.")
        config = self.settings.llm_roles[role]
        if config.provider not in self.providers:
            raise KeyError(f"No provider registered for {config.provider!r}.")
        return self.providers[config.provider], config.model

    def _call_with_retry(self, provider, model, messages, *, temperature, max_tokens) -> LLMResult:
        last_error: Exception | None = None
        for attempt in range(self.max_attempts):
            try:
                result = provider.complete(
                    messages, model=model, temperature=temperature, max_tokens=max_tokens
                )
                result.provider = provider.name
                result.model = model
                return result
            except Exception as exc:
                last_error = exc
                if attempt + 1 == self.max_attempts:
                    break
                self.sleep(0.5 * (2**attempt))
        raise RuntimeError(f"{provider.name} failed after {self.max_attempts} attempts") from last_error

    def _check_budget(self) -> None:
        now = self.clock()
        week = self.db.llm_spend_since(now - timedelta(days=7))
        month = self.db.llm_spend_since(now - timedelta(days=30))
        if week >= self.settings.weekly_budget_usd or month >= self.settings.monthly_budget_usd:
            raise BudgetExceeded(
                f"LLM budget reached (week ${week:.2f} / ${self.settings.weekly_budget_usd:.2f}, "
                f"month ${month:.2f} / ${self.settings.monthly_budget_usd:.2f})."
            )

    def _log(self, role: str, result: LLMResult, *, cache_hit: bool) -> None:
        self.db.log_llm_call(
            ts=self.clock(),
            role=role,
            provider=result.provider,
            model=result.model,
            input_tokens=0 if cache_hit else result.input_tokens,
            output_tokens=0 if cache_hit else result.output_tokens,
            cost_usd=0.0 if cache_hit else result.cost_usd,
            cache_hit=cache_hit,
        )


def _cache_payload(result: LLMResult) -> str:
    return json.dumps({"text": result.text, "input_tokens": result.input_tokens, "output_tokens": result.output_tokens, "cost_usd": result.cost_usd})


def _result_from_cache(payload: str, provider: str, model: str) -> LLMResult:
    raw = json.loads(payload)
    return LLMResult(
        text=raw["text"],
        parsed=None,
        input_tokens=int(raw.get("input_tokens") or 0),
        output_tokens=int(raw.get("output_tokens") or 0),
        cost_usd=float(raw.get("cost_usd") or 0.0),
        model=model,
        provider=provider,
    )
