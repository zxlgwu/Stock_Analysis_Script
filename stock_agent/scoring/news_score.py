"""Time-decayed news impact from stored predictions."""

from __future__ import annotations

import math
from datetime import date, datetime

DIRECTION = {"positive": 1.0, "negative": -1.0, "neutral": 0.0}
PRICED_IN = {"likely": 0.3, "partially": 0.6, "unlikely": 1.0}
RELATION_WEIGHT = {
    "direct": 1.0,
    "competitor": 0.5,
    "supplier": 0.5,
    "customer": 0.5,
    "macro_exposure": 0.3,
}
SOURCE_WEIGHT = {"sec_edgar_8k": 1.0, "finnhub": 0.75, "rss": 0.6, "gdelt": 0.5}
MAGNITUDE_CAP = 10.0


def _age_days(published_at: str, as_of: date) -> float:
    published = datetime.fromisoformat(published_at)
    if published.tzinfo is not None:
        published = published.replace(tzinfo=None)
    return max((datetime.combine(as_of, datetime.min.time()) - published).total_seconds() / 86400, 0.0)


def contribution(impact: dict, as_of: date, tau_days: float) -> float:
    decay = math.exp(-_age_days(impact["published_at"], as_of) / tau_days)
    sign = DIRECTION.get(impact["direction"], 0.0)
    magnitude = min(abs(float(impact["est_pct"] or 0.0)), MAGNITUDE_CAP)
    return (
        sign
        * magnitude
        * float(impact["confidence"] or 0.0)
        * SOURCE_WEIGHT.get(impact.get("source") or "", 0.5)
        * RELATION_WEIGHT.get(impact["relation"], 0.5)
        * PRICED_IN.get(impact["priced_in"], 0.6)
        * decay
    )


def net_revenue_impact(impact: dict, as_of: date, tau_days: float) -> float:
    """Signed percent of revenue, decayed, before the cross-sectional z-score."""
    decay = math.exp(-_age_days(impact["published_at"], as_of) / tau_days)
    sign = DIRECTION.get(impact["direction"], 0.0)
    return sign * abs(float(impact["est_pct"] or 0.0)) * PRICED_IN.get(impact["priced_in"], 0.6) * decay


def aggregate(impacts: list[dict], ticker: str, horizon: str, as_of: date, tau_days: float) -> tuple[float, float]:
    score = 0.0
    revenue = 0.0
    for impact in impacts:
        if impact["ticker"] != ticker or impact["horizon"] != horizon:
            continue
        score += contribution(impact, as_of, tau_days)
        revenue += net_revenue_impact(impact, as_of, tau_days)
    return score, revenue
