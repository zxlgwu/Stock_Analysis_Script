"""Magnitude checks and ticker checks applied after the model responds."""

from __future__ import annotations

from stock_agent.analysis.schemas import EventAnalysis, Impact

MAGNITUDE_LIMIT = 10.0
CONFIDENCE_FLOOR = 0.6


def apply_guardrails(
    analysis: EventAnalysis,
    universe: set[str],
    context: set[str],
) -> EventAnalysis:
    kept: list[Impact] = []
    for impact in analysis.impacts:
        ticker = impact.ticker.upper()
        if ticker not in universe or ticker not in context:
            continue
        reasoning = (impact.reasoning or "").strip()
        if len(reasoning) < 15:
            continue
        pct = impact.est_revenue_impact_pct
        if abs(pct) > MAGNITUDE_LIMIT and impact.confidence < CONFIDENCE_FLOOR:
            pct = MAGNITUDE_LIMIT if pct > 0 else -MAGNITUDE_LIMIT
            reasoning = f"[clipped] {reasoning}"
        kept.append(
            impact.model_copy(
                update={"ticker": ticker, "est_revenue_impact_pct": pct, "reasoning": reasoning}
            )
        )
    return analysis.model_copy(update={"impacts": kept})
