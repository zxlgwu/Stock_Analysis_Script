"""Score a labeled set of events. Direction must match the expected ticker."""

from __future__ import annotations

import json
from pathlib import Path


def load_golden(path: Path) -> list[dict]:
    return json.loads(path.read_text())


def direction_accuracy(cases: list[dict]) -> float:
    if not cases:
        return 0.0
    hits = 0
    for case in cases:
        ticker_ok = case["predicted_ticker"].upper() == case["expected_ticker"].upper()
        direction_ok = case["predicted_direction"] == case["expected_direction"]
        hits += int(ticker_ok and direction_ok)
    return hits / len(cases)


def apply_model(cases: list[dict], model) -> list[dict]:
    scored = []
    for case in cases:
        ticker, direction = model(case)
        scored.append({**case, "predicted_ticker": ticker, "predicted_direction": direction})
    return scored
