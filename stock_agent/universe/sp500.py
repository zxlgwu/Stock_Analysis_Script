"""S&P 500 constituents from Wikipedia, with a cached copy as fallback."""

from __future__ import annotations

from pathlib import Path

import requests
from bs4 import BeautifulSoup

from stock_agent.core.models import Security

WIKI_URL = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"
_HEADERS = {
    "User-Agent": (
        "stock-agent/0.1 (research; educational) "
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)"
    )
}


def parse_sp500_html(html: str) -> list[Security]:
    soup = BeautifulSoup(html, "html.parser")
    table = soup.find("table", {"id": "constituents"})
    if table is None:
        raise ValueError("Could not find the S&P 500 constituents table")

    headers = [cell.get_text(strip=True) for cell in table.find("tr").find_all(["th", "td"])]
    index = {name: pos for pos, name in enumerate(headers)}

    def col(row: list[str], *names: str) -> str:
        for name in names:
            if name in index and index[name] < len(row):
                return row[index[name]]
        return ""

    securities: list[Security] = []
    for tr in table.find_all("tr")[1:]:
        cells = [cell.get_text(" ", strip=True) for cell in tr.find_all("td")]
        if not cells:
            continue
        ticker = col(cells, "Symbol").replace("\n", "").split("[")[0].strip()
        if not ticker:
            continue
        cik_raw = col(cells, "CIK").split("[")[0].strip()
        cik = cik_raw.zfill(10) if cik_raw.isdigit() else (cik_raw or None)
        securities.append(
            Security(
                ticker=ticker,
                exchange="",
                name=col(cells, "Security") or ticker,
                cik=cik,
                sector=col(cells, "GICS Sector") or None,
                industry=col(cells, "GICS Sub-Industry") or None,
            )
        )
    if not securities:
        raise ValueError("S&P 500 table parsed to zero companies")
    return securities


class SP500Universe:
    name = "sp500"

    def __init__(self, cache_dir: Path | None = None, session: requests.Session | None = None):
        self.cache_dir = cache_dir
        self.session = session or requests.Session()

    def list_members(self) -> list[Security]:
        cache = None if self.cache_dir is None else self.cache_dir / "sp500_constituents.html"
        try:
            response = self.session.get(WIKI_URL, headers=_HEADERS, timeout=30)
            response.raise_for_status()
            html = response.text
            if cache is not None:
                cache.parent.mkdir(parents=True, exist_ok=True)
                cache.write_text(html)
        except requests.RequestException:
            if cache is None or not cache.exists():
                raise
            html = cache.read_text()
        return parse_sp500_html(html)
