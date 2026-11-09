"""Equal-weight top-N paper portfolio, after a flat estimated trading cost."""

from __future__ import annotations

COST_PER_REBALANCE = 0.001


def period_return(
    scores: dict[str, float],
    forward_returns: dict[str, float],
    *,
    top_n: int = 20,
    cost: float = COST_PER_REBALANCE,
) -> float | None:
    ranked = sorted(scores, key=lambda ticker: scores[ticker], reverse=True)[:top_n]
    usable = [forward_returns[ticker] for ticker in ranked if ticker in forward_returns]
    if not usable:
        return None
    return sum(usable) / len(usable) - cost
