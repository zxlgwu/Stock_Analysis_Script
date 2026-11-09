"""Curated RSS feeds for company, industry, and macro news."""

from __future__ import annotations

from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from xml.etree import ElementTree

import requests

from stock_agent.core.models import RawArticle, Security

DEFAULT_FEEDS = (
    "https://www.cnbc.com/id/100003114/device/rss/rss.html",
    "https://www.cnbc.com/id/10001147/device/rss/rss.html",
    "https://www.cnbc.com/id/15839135/device/rss/rss.html",
    "https://www.cnbc.com/id/19854910/device/rss/rss.html",
    "https://www.cnbc.com/id/20910258/device/rss/rss.html",
    "https://www.cnbc.com/id/10000664/device/rss/rss.html",
    "https://www.federalreserve.gov/feeds/press_all.xml",
)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120 Safari/537.36"
    )
}


class RssNews:
    name = "rss"

    def __init__(self, feeds: list[str], session: requests.Session | None = None):
        self.feeds = feeds
        self.session = session or requests
        self.failures: list[str] = []

    def fetch(self, since: datetime, securities: list[Security]) -> list[RawArticle]:
        articles: list[RawArticle] = []
        self.failures = []
        for feed in self.feeds:
            try:
                response = self.session.get(feed, timeout=30, headers=HEADERS)
                response.raise_for_status()
                parsed = self.parse(response.content)
            except Exception as exc:
                self.failures.append(f"{feed}: {exc}")
                continue
            articles.extend(article for article in parsed if article.published_at >= since)
        if not articles and self.failures:
            raise RuntimeError("; ".join(self.failures))
        return articles

    @staticmethod
    def parse(xml: str | bytes) -> list[RawArticle]:
        if isinstance(xml, str):
            xml = xml.lstrip("\ufeff").encode("utf-8")
        root = ElementTree.fromstring(xml)
        articles: list[RawArticle] = []
        for item in root.iter("item"):
            title = _text(item.find("title"))
            link = _text(item.find("link"))
            description = _text(item.find("description"))
            pub = _text(item.find("pubDate"))
            published = parsedate_to_datetime(pub) if pub else datetime.now(timezone.utc)
            if published.tzinfo is None:
                published = published.replace(tzinfo=timezone.utc)
            articles.append(
                RawArticle(
                    source="rss",
                    url=link,
                    title=title,
                    body=description or title,
                    published_at=published,
                )
            )
        return articles


def _text(node) -> str:
    if node is None or node.text is None:
        return ""
    return node.text.strip()
