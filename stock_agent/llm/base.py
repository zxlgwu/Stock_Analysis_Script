"""Provider protocol and the result every vendor returns."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from pydantic import BaseModel


@dataclass(frozen=True)
class Message:
    role: str
    content: str

    def as_dict(self) -> dict[str, str]:
        return {"role": self.role, "content": self.content}


@dataclass
class LLMResult:
    text: str
    parsed: BaseModel | None
    input_tokens: int
    output_tokens: int
    cost_usd: float
    model: str
    provider: str


class LLMProvider(Protocol):
    name: str

    def complete(
        self,
        messages: list[Message],
        *,
        model: str,
        temperature: float = 0.0,
        max_tokens: int | None = None,
    ) -> LLMResult: ...

    def embed(self, texts: list[str], *, model: str) -> list[list[float]]: ...


class BudgetExceeded(RuntimeError):
    """Raised when the weekly or monthly cap has already been spent."""


class LLMResponseError(RuntimeError):
    """Raised when a provider never returns JSON matching the schema."""
