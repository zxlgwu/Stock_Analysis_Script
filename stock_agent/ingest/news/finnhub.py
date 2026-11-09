"""Finnhub company-news source."""

from __future__ import annotations

from datetime import datetime, timezone

import requests

from stock_agent.core.models import RawArticle, Security


class FinnhubNews:
    name = "finnhub"

    def __init__(self, api_key: str, session: requests.Session | None = None):
        self.api_key = api_key
        self.session = session or requests

    def fetch(self, since: datetime, securities: list[Security]) -> list[RawArticle]:
        articles: list[RawArticle] = []
        start = since.date().isoformat()
        end = datetime.now(timezone.utc).date().isoformat()
        for security in securities:
            response = self.session.get(
                "https://finnhub.io/api/v1/company-news",
                params={"symbol": security.ticker, "from": start, "to": end, "token": self.api_key},
                timeout=30,
            )
            response.raise_for_status()
            articles.extend(self.parse(response.json(), fallback_ticker=security.ticker))
        return articles

    @staticmethod
    def parse(payload: list[dict], fallback_ticker: str | None = None) -> list[RawArticle]:
        articles: list[RawArticle] = []
        for item in payload:
            published = datetime.fromtimestamp(int(item.get("datetime") or 0), tz=timezone.utc)
            ticker = str(item.get("related") or fallback_ticker or "").upper()
            articles.append(
                RawArticle(
                    source="finnhub",
                    url=str(item.get("url") or ""),
                    title=str(item.get("headline") or ""),
                    body=str(item.get("summary") or ""),
                    published_at=published,
                    tickers=(ticker,) if ticker else (),
                )
            )
        return articles
