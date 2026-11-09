"""Did later reported growth move the way the impact predicted?"""

from __future__ import annotations


def direction_hit(predicted: str, prior_growth: float, realized_growth: float) -> bool | None:
    if predicted == "neutral":
        return None
    expected_up = predicted == "positive"
    return expected_up == (realized_growth > prior_growth)
