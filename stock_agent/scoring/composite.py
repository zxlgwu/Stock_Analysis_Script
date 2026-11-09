"""Cross-sectional scores and the three output lists."""

from __future__ import annotations

import math
from datetime import date

from stock_agent.core.models import ScoreRecord
from stock_agent.scoring.news_score import aggregate


def zscore_within_sector(values: dict[str, float], sectors: dict[str, str]) -> dict[str, float]:
    groups: dict[str, list[tuple[str, float]]] = {}
    for ticker, value in values.items():
        groups.setdefault(sectors.get(ticker) or "Unknown", []).append((ticker, value))
    scored: dict[str, float] = {}
    for members in groups.values():
        nums = [value for _, value in members]
        mean = sum(nums) / len(nums)
        variance = sum((value - mean) ** 2 for value in nums) / len(nums)
        std = math.sqrt(variance)
        for ticker, value in members:
            scored[ticker] = 0.0 if std == 0 else (value - mean) / std
    return scored


def composite_score(
    news_mid: float,
    news_long: float,
    quality: float,
    value: float,
    technical: float,
    risk: float,
    weights: dict[str, float],
) -> float:
    return (
        weights["news_mid"] * news_mid
        + weights["news_long"] * news_long
        + weights["quality"] * quality
        + weights["value"] * value
        + weights["technical"] * technical
        - weights["risk"] * risk
    )


def mid_term_weights(weights: dict[str, float]) -> dict[str, float]:
    bumped = dict(weights)
    bumped["news_mid"] = bumped["news_mid"] * 2
    bumped["technical"] = bumped["technical"] * 2
    total = sum(bumped.values()) or 1.0
    return {key: value / total for key, value in bumped.items()}


def build_scores(
    tickers: list[str],
    sectors: dict[str, str],
    impacts: list[dict],
    factors: dict[str, dict[str, float]],
    weights: dict[str, float],
    decay_days: dict[str, int],
    as_of: date,
) -> list[ScoreRecord]:
    raw_mid = {}
    raw_long = {}
    net_mid = {}
    net_long = {}
    for ticker in tickers:
        raw_mid[ticker], net_mid[ticker] = aggregate(impacts, ticker, "mid", as_of, decay_days["mid"])
        raw_long[ticker], net_long[ticker] = aggregate(impacts, ticker, "long", as_of, decay_days["long"])
    z_mid = zscore_within_sector(raw_mid, sectors)
    z_long = zscore_within_sector(raw_long, sectors)
    z_quality = zscore_within_sector({t: factors[t]["quality"] for t in tickers}, sectors)
    z_value = zscore_within_sector({t: factors[t]["value"] for t in tickers}, sectors)
    z_technical = zscore_within_sector({t: factors[t]["technical"] for t in tickers}, sectors)
    z_risk = zscore_within_sector({t: factors[t]["risk"] for t in tickers}, sectors)
    rows = []
    for ticker in tickers:
        rows.append(
            ScoreRecord(
                week_ending=as_of,
                ticker=ticker,
                news_mid=z_mid[ticker],
                news_long=z_long[ticker],
                net_revenue_mid=net_mid[ticker],
                net_revenue_long=net_long[ticker],
                quality=z_quality[ticker],
                value=z_value[ticker],
                technical=z_technical[ticker],
                risk=z_risk[ticker],
                composite=composite_score(
                    z_mid[ticker],
                    z_long[ticker],
                    z_quality[ticker],
                    z_value[ticker],
                    z_technical[ticker],
                    z_risk[ticker],
                    weights,
                ),
            )
        )
    return rows


def _median(values: list[float]) -> float:
    ordered = sorted(values)
    mid = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[mid]
    return (ordered[mid - 1] + ordered[mid]) / 2


def rank_lists(
    scores: list[ScoreRecord],
    raw_quality: dict[str, float | None],
    sectors: dict[str, str],
    previous: dict[str, float],
    weights: dict[str, float],
    top_n: int,
) -> dict[str, list[ScoreRecord]]:
    long_pool = []
    for row in scores:
        quality = raw_quality.get(row.ticker)
        if row.net_revenue_long <= 0 or quality is None:
            continue
        peers = [
            raw_quality[name]
            for name, sector in sectors.items()
            if sector == sectors.get(row.ticker) and raw_quality.get(name) is not None
        ]
        if quality >= _median([value for value in peers if value is not None]):
            long_pool.append(row)
    long_list = sorted(long_pool, key=lambda row: row.composite, reverse=True)[:top_n]
    mid_weights = mid_term_weights(weights)
    news_pool = [row for row in scores if row.net_revenue_mid != 0 or row.net_revenue_long != 0]
    mid_ranked = sorted(
        news_pool,
        key=lambda row: composite_score(
            row.news_mid, row.news_long, row.quality, row.value, row.technical, row.risk, mid_weights
        ),
        reverse=True,
    )[:top_n]
    risk_pool = [row for row in scores if row.net_revenue_mid < 0 or row.net_revenue_long < 0]
    risk_list = sorted(risk_pool, key=lambda row: min(row.net_revenue_mid, row.net_revenue_long))[:top_n]
    return {"long": long_list, "mid": mid_ranked, "risk": risk_list}
