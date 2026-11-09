"""News sources. Parsers are pure; fetch methods are the only network calls."""

from __future__ import annotations

import os

from stock_agent.core.config import Settings
from stock_agent.ingest.news.finnhub import FinnhubNews
from stock_agent.ingest.news.gdelt import GdeltNews
from stock_agent.ingest.news.rss import DEFAULT_FEEDS, RssNews
from stock_agent.ingest.news.sec_edgar import Edgar8K


def default_sources(settings: Settings) -> list:
    sources = []
    for name in settings.news_sources:
        if name == "finnhub":
            key = os.environ.get("FINNHUB_API_KEY")
            if key:
                sources.append(FinnhubNews(key))
        elif name == "sec_edgar_8k":
            sources.append(Edgar8K())
        elif name == "gdelt":
            sources.append(GdeltNews())
        elif name == "rss":
            sources.append(RssNews(settings.rss_feeds or list(DEFAULT_FEEDS)))
    return sources
