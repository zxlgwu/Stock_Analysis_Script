"""SEC EDGAR current 8-K filings."""

from __future__ import annotations

import os
import re
from datetime import datetime
from xml.etree import ElementTree

import requests

from stock_agent.core.models import RawArticle, Security

_ATOM = "{http://www.w3.org/2005/Atom}"
_CIK = re.compile(r"\((\d{6,10})\)")
_FEED = (
    "https://www.sec.gov/cgi-bin/browse-edgar"
    "?action=getcurrent&type=8-K&count=100&output=atom"
)


def critical_item_types(title: str, body: str) -> list[str]:
    """Rule-based scan for filings that should not wait for the weekly email."""
    text = f"{title} {body}".lower()
    found: list[str] = []
    checks = (
        ("1.03", "bankruptcy", "bankruptcy"),
        ("3.01", "delisting", "delisting"),
        ("4.01", "change in accountant", "auditor_change"),
        ("4.02", "non-reliance", "non_reliance"),
    )
    for code, phrase, label in checks:
        if code in text or phrase in text:
            found.append(label)
    return found


class Edgar8K:
    name = "sec_edgar_8k"

    def __init__(self, session: requests.Session | None = None):
        self.session = session or requests

    def fetch(self, since: datetime, securities: list[Security]) -> list[RawArticle]:
        response = self.session.get(
            _FEED,
            headers={"User-Agent": os.environ.get("SEC_USER_AGENT") or "stock-agent/0.1 (research; local)"},
            timeout=30,
        )
        response.raise_for_status()
        cik_to_ticker = {
            sec.cik.lstrip("0"): sec.ticker
            for sec in securities
            if sec.cik
        }
        articles = self.parse(response.text, cik_to_ticker)
        # Keep filings from any public company. A known CIK adds a ticker;
        # an unknown filer is still stored so the company name can be linked later.
        return [article for article in articles if article.published_at >= since]

    @staticmethod
    def parse(xml_text: str, cik_to_ticker: dict[str, str] | None = None) -> list[RawArticle]:
        cik_to_ticker = cik_to_ticker or {}
        root = ElementTree.fromstring(xml_text)
        articles: list[RawArticle] = []
        for entry in root.findall(f"{_ATOM}entry"):
            title = _text(entry.find(f"{_ATOM}title"))
            summary = _text(entry.find(f"{_ATOM}summary"))
            updated = _text(entry.find(f"{_ATOM}updated"))
            link = entry.find(f"{_ATOM}link")
            href = link.attrib.get("href", "") if link is not None else ""
            match = _CIK.search(title)
            cik = match.group(1).lstrip("0") if match else ""
            ticker = cik_to_ticker.get(cik, "")
            published = datetime.fromisoformat(updated) if updated else datetime.min
            articles.append(
                RawArticle(
                    source="sec_edgar_8k",
                    url=href,
                    title=title,
                    body=summary,
                    published_at=published,
                    tickers=(ticker,) if ticker else (),
                )
            )
        return articles


def _text(node) -> str:
    if node is None or node.text is None:
        return ""
    return node.text.strip()
