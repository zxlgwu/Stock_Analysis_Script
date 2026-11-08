"""US listings from the Nasdaq Trader symbol directory, excluding ETFs and test issues."""

from __future__ import annotations

from pathlib import Path

import requests

from stock_agent.core.models import Security

DIRECTORY_URL = "https://www.nasdaqtrader.com/dynamic/SymDir/nasdaqtraded.txt"
_HEADERS = {"User-Agent": "stock-agent/0.1 (research; educational)"}

_EXCHANGES = {
    "Q": "NASDAQ",
    "N": "NYSE",
    "A": "NYSE American",
    "P": "NYSE Arca",
    "Z": "Cboe",
    "V": "IEX",
}


def parse_nasdaq_directory(text: str) -> list[Security]:
    lines = [line for line in text.splitlines() if line.strip()]
    if not lines:
        raise ValueError("Nasdaq symbol directory is empty")
    header = lines[0].split("|")
    try:
        symbol_at = header.index("Symbol")
        name_at = header.index("Security Name")
        exchange_at = header.index("Listing Exchange")
        etf_at = header.index("ETF")
        test_at = header.index("Test Issue")
    except ValueError as exc:
        raise ValueError("Nasdaq symbol directory is missing expected columns") from exc

    securities: list[Security] = []
    for line in lines[1:]:
        if line.startswith("File Creation Time"):
            continue
        parts = line.split("|")
        if len(parts) <= max(symbol_at, name_at, exchange_at, etf_at, test_at):
            continue
        if parts[etf_at] != "N" or parts[test_at] != "N":
            continue
        ticker = parts[symbol_at].strip()
        if not ticker:
            continue
        securities.append(
            Security(
                ticker=ticker,
                exchange=_EXCHANGES.get(parts[exchange_at].strip(), parts[exchange_at].strip()),
                name=parts[name_at].strip() or ticker,
            )
        )
    if not securities:
        raise ValueError("Nasdaq symbol directory parsed to zero companies")
    return securities


class NasdaqUniverse:
    name = "nasdaq"

    def __init__(self, cache_dir: Path | None = None, session: requests.Session | None = None):
        self.cache_dir = cache_dir
        self.session = session or requests.Session()

    def list_members(self) -> list[Security]:
        cache = None if self.cache_dir is None else self.cache_dir / "nasdaqtraded.txt"
        try:
            response = self.session.get(DIRECTORY_URL, headers=_HEADERS, timeout=60)
            response.raise_for_status()
            text = response.text
            if cache is not None:
                cache.parent.mkdir(parents=True, exist_ok=True)
                cache.write_text(text)
        except requests.RequestException:
            if cache is None or not cache.exists():
                raise
            text = cache.read_text()
        return parse_nasdaq_directory(text)
