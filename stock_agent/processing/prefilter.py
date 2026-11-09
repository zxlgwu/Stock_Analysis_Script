"""Drop low-value market recaps before any LLM call. Filings are always kept."""

from __future__ import annotations

import re

_LOW_VALUE = (
    re.compile(r"stocks to watch"),
    re.compile(r"stock recap"),
    re.compile(r"market recap"),
    re.compile(r"what to watch"),
    re.compile(r"top \d+ stocks"),
    re.compile(r"\d+ stocks to (buy|watch|sell)"),
    re.compile(r"\bmovers\b"),
    re.compile(r"here are the stocks"),
)


def is_low_value(title: str, body: str, source: str) -> tuple[bool, str]:
    if source == "sec_edgar_8k":
        return False, ""
    text = f"{title} {body}".lower()
    for pattern in _LOW_VALUE:
        if pattern.search(text):
            return True, pattern.pattern
    return False, ""
