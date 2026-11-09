"""Cursor membership models. Each call is one agent run that only returns text."""

from __future__ import annotations

import os
import tempfile
from collections.abc import Callable

from stock_agent.llm.base import LLMResult, Message

Prompt = Callable[[str, str, str], object]


class CursorProvider:
    name = "cursor"

    def __init__(self, prompt: Prompt | None = None, api_key: str | None = None):
        self._prompt = prompt or default_cursor_prompt
        self._api_key = api_key

    def complete(
        self,
        messages: list[Message],
        *,
        model: str,
        temperature: float = 0.0,
        max_tokens: int | None = None,
    ) -> LLMResult:
        del temperature, max_tokens
        key = (self._api_key if self._api_key is not None else os.environ.get("CURSOR_API_KEY", "")).strip()
        if not key:
            raise CursorAuthError("Add CURSOR_API_KEY to .env to use a Cursor model.")
        model_id = model.removeprefix("cursor/").strip()
        if not model_id:
            raise CursorAuthError("Choose a Cursor model.")
        outcome = self._prompt(_prompt_text(messages), model_id, key)
        status = str(getattr(outcome, "status", "") or "")
        if status != "finished":
            detail = getattr(outcome, "error_message", None) or status or "the run did not finish"
            raise RuntimeError(f"Cursor model run failed: {detail}")
        usage = getattr(outcome, "usage", None)
        return LLMResult(
            text=str(getattr(outcome, "result", "") or ""),
            parsed=None,
            input_tokens=int(getattr(usage, "input_tokens", 0) or 0),
            output_tokens=int(getattr(usage, "output_tokens", 0) or 0),
            cost_usd=0.0,
            model=model_id,
            provider=self.name,
        )

    def embed(self, texts: list[str], *, model: str) -> list[list[float]]:
        raise NotImplementedError("Cursor models answer analysis prompts. Embeddings stay local.")


class CursorAuthError(RuntimeError):
    is_retryable = False


def default_cursor_prompt(prompt: str, model: str, api_key: str):
    from cursor_sdk import Agent, AgentOptions, LocalAgentOptions, SandboxOptions

    with tempfile.TemporaryDirectory(prefix="stock-agent-cursor-") as cwd:
        return Agent.prompt(
            prompt,
            AgentOptions(
                api_key=api_key,
                model=model,
                local=LocalAgentOptions(cwd=cwd, sandbox_options=SandboxOptions(enabled=True)),
            ),
        )


def cursor_model_choices(models: list | None = None, *, error: str = "") -> list[dict]:
    """Turn the account's Cursor model list into settings rows."""
    if error:
        return [_cursor_row("Cursor", "cursor/auto", False, error)]
    choices = []
    for model in models or []:
        model_id = str(getattr(model, "id", "") or (model.get("id") if isinstance(model, dict) else "")).strip()
        if not model_id:
            continue
        display = str(
            getattr(model, "display_name", "")
            or (model.get("display_name") if isinstance(model, dict) else "")
            or model_id
        )
        description = str(
            getattr(model, "description", "")
            or (model.get("description") if isinstance(model, dict) else "")
            or "Uses your Cursor membership."
        )
        choices.append(_cursor_row(display, f"cursor/{model_id}", True, description))
    return choices


def list_cursor_models() -> list[dict]:
    key = os.environ.get("CURSOR_API_KEY", "").strip()
    if not key:
        return [
            _cursor_row(
                "Cursor",
                "cursor/auto",
                False,
                "Add CURSOR_API_KEY to .env. Create it under Cursor Dashboard, Integrations.",
            )
        ]
    try:
        from cursor_sdk import Cursor

        return cursor_model_choices(Cursor.models.list(api_key=key))
    except Exception as exc:
        message = str(exc).strip() or "Cursor models could not be loaded."
        if key and key in message:
            message = "Cursor models could not be loaded."
        return [_cursor_row("Cursor", "cursor/auto", False, message[:180])]


def _cursor_row(name: str, model: str, selectable: bool, note: str) -> dict:
    return {
        "name": name,
        "model": model,
        "selectable": selectable,
        "kind": "cursor",
        "group": "Cursor",
        "size": "",
        "note": note,
    }


def _prompt_text(messages: list[Message]) -> str:
    parts = [
        "Answer the stock-analysis request below. Return only the text or JSON it asks for. "
        "Do not edit files, run commands, or use tools.",
        "",
    ]
    for message in messages:
        parts.append(f"{message.role.upper()}:")
        parts.append(message.content)
        parts.append("")
    return "\n".join(parts).strip()
