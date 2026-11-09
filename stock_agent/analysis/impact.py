"""One structured impact call per material cluster."""

from __future__ import annotations

import json

from stock_agent.analysis.guardrails import apply_guardrails
from stock_agent.analysis.schemas import EventAnalysis
from stock_agent.llm.base import BudgetExceeded, Message
from stock_agent.llm.prompts import IMPACT_INSTRUCTIONS, IMPACT_PROMPT_VERSION
from stock_agent.llm.router import Router


def analyze_cluster(
    router: Router,
    cluster: dict,
    *,
    universe: set[str],
    context: set[str],
) -> EventAnalysis | None:
    messages = [
        Message("system", IMPACT_INSTRUCTIONS),
        Message("user", json.dumps(cluster, default=str)),
    ]
    try:
        result = router.complete("analysis", messages, response_schema=EventAnalysis)
    except BudgetExceeded:
        return None
    parsed: EventAnalysis = result.parsed  # type: ignore[assignment]
    parsed = parsed.model_copy(update={"cluster_id": cluster["cluster_id"]})
    return apply_guardrails(parsed, universe, context)


def prompt_version() -> str:
    return IMPACT_PROMPT_VERSION
