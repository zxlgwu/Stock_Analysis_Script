"""Rank the week's stories so the model reads the most market-relevant ones first."""

from __future__ import annotations

import re

from stock_agent.knowledge.exposure import sectors_for_text
from stock_agent.knowledge.taxonomy import tag_factors

_PERSONAL = re.compile(
    r"\b(my (husband|wife|son|daughter|mother|father|adviser)|should i|i'm \d+|i am \d+|"
    r"retire(ment)?\b.*\?|annuity|horoscope|recipe|obituary)",
    re.IGNORECASE,
)
_RESULTS_ITEMS = ("1.01", "2.01", "2.02", "2.05", "2.06", "8.01")
_COVER_ITEMS = ("5.02", "5.07", "7.01", "9.01")


def story_priority(
    title: str,
    body: str,
    source: str,
    links: list[tuple[str, str]],
    size: int = 1,
) -> float:
    text = f"{title}. {body}"
    score = 0.0
    kinds = {kind for _ticker, kind in links}
    if "mentioned" in kinds:
        score += 3
    if "expanded" in kinds or "exposure" in kinds:
        score += 1
    score += min(len(tag_factors(text[:1500])), 2)
    score += min(len(sectors_for_text(text[:1500])), 2) * 0.5
    score += min(max(size - 1, 0), 3)
    if source in {"rss", "finnhub"}:
        score += 1
    if source == "sec_edgar_8k":
        items = re.findall(r"Item (\d\.\d\d)", body)
        if any(item in _RESULTS_ITEMS for item in items):
            score += 2
        elif items and all(item in _COVER_ITEMS for item in items):
            score -= 3
    if _PERSONAL.search(text[:600]):
        score -= 4
    return score
