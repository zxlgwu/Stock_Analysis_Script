"""Drop impact lines whose reasoning does not support the company or the direction."""

from __future__ import annotations

import re

from stock_agent.analysis.schemas import Impact

_COVER_ITEMS = {"5.02", "7.01", "8.01", "9.01"}
_DIRECTION_UP = re.compile(
    r"increas\w*(?:\s+\w+){0,3}\s+(?:demand|revenue|sales|premiums|bookings|traffic)"
)
_DIRECTION_DOWN = re.compile(
    r"(?:decreas|reduc)\w*(?:\s+\w+){0,3}\s+(?:demand|revenue|sales|premiums|bookings|traffic)"
)


def supported_impacts(impacts: list[Impact], article: str, names: dict[str, str]) -> list[Impact]:
    if _cover_sheet(article):
        return []
    kept = [impact for impact in impacts if _reasoning_fits(impact, names, article)]
    return _drop_copied_reasoning(kept, names)


def _cover_sheet(article: str) -> bool:
    if "8-k" not in article.lower() or len(article) > 900:
        return False
    items = set(re.findall(r"Item (\d\.\d\d)", article))
    return bool(items) and items <= _COVER_ITEMS


def _reasoning_fits(impact: Impact, names: dict[str, str], article: str) -> bool:
    text = impact.reasoning or ""
    lowered = text.lower()
    source = article.lower()
    if any(phrase in lowered and phrase not in source for phrase in ("strong financial", "strong revenue", "revenue growth")):
        return False
    if "stock price" in lowered or "any changes" in lowered or "any shifts" in lowered:
        return False
    if _says_increase(lowered) and _says_decrease(lowered):
        return False
    name = names.get(impact.ticker, impact.ticker)
    own = {impact.ticker.lower(), name.lower(), name.split()[0].lower()}
    if _foreign_revenue_subject(text, own):
        return False
    if impact.direction == "negative" and re.search(
        rf"towards? (?:competitors like )?{re.escape(name.split()[0])}",
        text,
        flags=re.IGNORECASE,
    ):
        return False
    return True


def _says_increase(text: str) -> bool:
    return _DIRECTION_UP.search(text) is not None


def _says_decrease(text: str) -> bool:
    return _DIRECTION_DOWN.search(text) is not None


def _foreign_revenue_subject(text: str, own: set[str]) -> bool:
    patterns = (
        r"([A-Za-z][A-Za-z& .-]{1,40})'s revenue",
        r"revenue for ([A-Za-z][A-Za-z& .-]{1,40})",
        r"impact on ([A-Za-z][A-Za-z& .-]{1,40})'s revenue",
    )
    for pattern in patterns:
        for match in re.finditer(pattern, text):
            subject = match.group(1).strip().lower()
            first = subject.split()[0]
            if subject not in own and first not in own:
                return True
    return False


def _drop_copied_reasoning(impacts: list[Impact], names: dict[str, str]) -> list[Impact]:
    groups: dict[str, list[Impact]] = {}
    for impact in impacts:
        groups.setdefault(_normalize(impact.reasoning, impact.ticker, names), []).append(impact)
    copied = {
        key
        for key, group in groups.items()
        if len({item.ticker for item in group}) >= 3
    }
    return [impact for impact in impacts if _normalize(impact.reasoning, impact.ticker, names) not in copied]


def _normalize(reasoning: str, ticker: str, names: dict[str, str]) -> str:
    text = (reasoning or "").lower()
    for name in names.values():
        text = text.replace(name.lower(), " ")
        first = name.split()[0]
        if len(first) >= 4:
            text = text.replace(first.lower(), " ")
    text = text.replace(ticker.lower(), " ")
    text = re.sub(r"[^a-z ]", " ", text)
    return re.sub(r"\s+", " ", text).strip()
