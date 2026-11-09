"""US-listed public companies used to read the news.

The configured universe (the S&P 500) is still what gets scored and ranked.
News linking uses this wider list so a story can name a company outside that universe.
"""

from __future__ import annotations

import os

from stock_agent.core.config import Settings
from stock_agent.core.models import Security
from stock_agent.universe.nasdaq import NasdaqUniverse, parse_nasdaq_directory


def merge_companies(listings: list[Security], members: list[Security]) -> list[Security]:
    """Prefer universe sector, industry, and CIK when the same ticker appears in both lists."""
    merged = {security.ticker: security for security in listings}
    for member in members:
        current = merged.get(member.ticker)
        if current is None:
            merged[member.ticker] = member
            continue
        merged[member.ticker] = Security(
            ticker=member.ticker,
            exchange=member.exchange or current.exchange,
            name=member.name or current.name,
            cik=member.cik or current.cik,
            sector=member.sector or current.sector,
            industry=member.industry or current.industry,
        )
    return list(merged.values())


def load_public_companies(settings: Settings, members: list[Security]) -> list[Security]:
    """All US listings, with the configured universe's industry data laid on top.

    Tests stay offline. A normal run downloads the Nasdaq symbol directory once
    and reuses the cache.
    """
    cache_dir = settings.root / "data" / "cache"
    cache = cache_dir / "nasdaqtraded.txt"
    listings: list[Security] = []
    if cache.exists():
        listings = parse_nasdaq_directory(cache.read_text())
    elif not os.environ.get("PYTEST_CURRENT_TEST"):
        try:
            listings = NasdaqUniverse(cache_dir=cache_dir).list_members()
            print(f"Public companies: {len(listings)} US listings")
        except Exception as exc:
            print(f"Public company list unavailable, using the configured universe. {exc}"[:200])
    if not listings:
        return list(members)
    return merge_companies(listings, members)
