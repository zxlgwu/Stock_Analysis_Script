"""Thin LiteLLM adapter. Vendor choice lives in the model string, not in this class."""

from __future__ import annotations

from stock_agent.llm.base import LLMResult, Message

DEFAULT_MAX_TOKENS = 1500
REQUEST_TIMEOUT_SECONDS = 300


class LiteLLMProvider:
    name = "litellm"

    def complete(
        self,
        messages: list[Message],
        *,
        model: str,
        temperature: float = 0.0,
        max_tokens: int | None = None,
    ) -> LLMResult:
        import litellm

        # Local models can loop without an output cap, so every call is bounded.
        kwargs: dict = {
            "model": model,
            "messages": [message.as_dict() for message in messages],
            "temperature": temperature,
            "max_tokens": max_tokens or DEFAULT_MAX_TOKENS,
            "timeout": REQUEST_TIMEOUT_SECONDS,
        }
        response = litellm.completion(**kwargs)
        choice = response.choices[0].message.content or ""
        usage = getattr(response, "usage", None)
        hidden = getattr(response, "_hidden_params", {}) or {}
        cost = hidden.get("response_cost")
        return LLMResult(
            text=choice,
            parsed=None,
            input_tokens=int(getattr(usage, "prompt_tokens", 0) or 0),
            output_tokens=int(getattr(usage, "completion_tokens", 0) or 0),
            cost_usd=float(cost or 0.0),
            model=model,
            provider=self.name,
        )

    def embed(self, texts: list[str], *, model: str) -> list[list[float]]:
        import litellm

        response = litellm.embedding(model=model, input=list(texts), timeout=REQUEST_TIMEOUT_SECONDS)
        return [list(item["embedding"]) for item in response.data]
