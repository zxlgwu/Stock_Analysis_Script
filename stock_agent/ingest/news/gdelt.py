"""GDELT document API for macro and industry news."""

from __future__ import annotations

from datetime import datetime, timezone

import requests

from stock_agent.core.models import RawArticle, Security


MARKET_QUERY = (
    "(earnings OR guidance OR acquisition OR merger OR tariff OR layoffs OR FDA OR "
    "lawsuit OR antitrust OR contract OR outlook OR \"supply chain\" OR \"interest rates\") "
    "sourcelang:eng (domainis:reuters.com OR domainis:cnbc.com OR domainis:apnews.com OR "
    "domainis:businesswire.com OR domainis:prnewswire.com OR domainis:globenewswire.com OR "
    "domainis:fool.com OR domainis:investopedia.com)"
)


class GdeltNews:
    name = "gdelt"

    def __init__(self, session: requests.Session | None = None, query: str = MARKET_QUERY):
        self.session = session or requests
        self.query = query

    def fetch(self, since: datetime, securities: list[Security]) -> list[RawArticle]:
        stamp = since.astimezone(timezone.utc).strftime("%Y%m%d%H%M%S")
        response = self.session.get(
            "https://api.gdeltproject.org/api/v2/doc/doc",
            params={
                "query": self.query,
                "mode": "artlist",
                "format": "json",
                "startdatetime": stamp,
                "maxrecords": 75,
            },
            timeout=30,
        )
        response.raise_for_status()
        return self.parse(response.json())

    @staticmethod
    def parse(payload: dict) -> list[RawArticle]:
        articles: list[RawArticle] = []
        for item in payload.get("articles") or []:
            articles.append(
                RawArticle(
                    source="gdelt",
                    url=str(item.get("url") or ""),
                    title=str(item.get("title") or ""),
                    body=str(item.get("title") or ""),
                    published_at=_parse_seen(str(item.get("seendate") or "")),
                )
            )
        return articles


def _parse_seen(value: str) -> datetime:
    if not value:
        return datetime.now(timezone.utc)
    return datetime.strptime(value, "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc)
