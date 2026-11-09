"""Short thesis for a highlighted company. Skipped when the budget is already spent."""

from __future__ import annotations

import json

from stock_agent.analysis.schemas import ThesisResult
from stock_agent.llm.base import BudgetExceeded, Message
from stock_agent.llm.prompts import THESIS_INSTRUCTIONS, THESIS_PROMPT_VERSION
from stock_agent.llm.router import Router


def write_thesis(router: Router, payload: dict) -> ThesisResult | None:
    messages = [
        Message("system", THESIS_INSTRUCTIONS),
        Message("user", json.dumps(payload, default=str)),
    ]
    try:
        result = router.complete("thesis", messages, response_schema=ThesisResult)
    except BudgetExceeded:
        return None
    return result.parsed  # type: ignore[return-value]


def prompt_version() -> str:
    return THESIS_PROMPT_VERSION
