"""Rank information coefficient, quintile spread, and confidence calibration."""

from __future__ import annotations

import math


def _ranks(values: list[float]) -> list[float]:
    order = sorted(range(len(values)), key=lambda index: values[index])
    ranks = [0.0] * len(values)
    for rank, index in enumerate(order, start=1):
        ranks[index] = float(rank)
    return ranks


def _pearson(left: list[float], right: list[float]) -> float | None:
    mean_left = sum(left) / len(left)
    mean_right = sum(right) / len(right)
    numerator = sum((a - mean_left) * (b - mean_right) for a, b in zip(left, right))
    left_scale = math.sqrt(sum((a - mean_left) ** 2 for a in left))
    right_scale = math.sqrt(sum((b - mean_right) ** 2 for b in right))
    if left_scale == 0 or right_scale == 0:
        return None
    return numerator / (left_scale * right_scale)


def rank_ic(scores: dict[str, float], forward_returns: dict[str, float]) -> float | None:
    shared = [ticker for ticker in scores if ticker in forward_returns]
    if len(shared) < 3:
        return None
    return _pearson(
        _ranks([scores[ticker] for ticker in shared]),
        _ranks([forward_returns[ticker] for ticker in shared]),
    )


def quintile_spread(scores: dict[str, float], forward_returns: dict[str, float]) -> float | None:
    pairs = sorted(
        ((scores[ticker], forward_returns[ticker]) for ticker in scores if ticker in forward_returns),
        key=lambda item: item[0],
    )
    if len(pairs) < 5:
        return None
    bucket = max(1, len(pairs) // 5)
    bottom = sum(value for _, value in pairs[:bucket]) / bucket
    top = sum(value for _, value in pairs[-bucket:]) / bucket
    return top - bottom


def calibration(rows: list[tuple[float, bool]]) -> dict[str, float | None]:
    def rate(low: float, high: float) -> float | None:
        bucket = [hit for confidence, hit in rows if low <= confidence < high]
        if not bucket:
            return None
        return sum(bucket) / len(bucket)

    return {"0.5": rate(0.4, 0.7), "0.8": rate(0.7, 1.01)}
