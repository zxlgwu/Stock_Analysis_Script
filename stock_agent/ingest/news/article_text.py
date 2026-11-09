"""Fetch the readable text of a news article so analysis is not limited to the headline."""

from __future__ import annotations

import re
from typing import Callable

import requests
from bs4 import BeautifulSoup

from stock_agent.ingest.news.rss import HEADERS

MAX_CHARS = 6000
_SKIP_HOSTS = ("sec.gov",)
_BOILERPLATE = re.compile(
    r"(subscribe|sign up|newsletter|cookie|all rights reserved|advertisement|"
    r"click here|read more|follow us|got a confidential news tip)",
    re.IGNORECASE,
)

Fetcher = Callable[[str], str]


def extract_text(html: str) -> str:
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "nav", "footer", "header", "aside", "form"]):
        tag.decompose()
    container = soup.find("article") or soup
    paragraphs = []
    for node in container.find_all("p"):
        text = node.get_text(" ", strip=True)
        if len(text) < 40 or _BOILERPLATE.search(text):
            continue
        paragraphs.append(text)
    return "\n".join(paragraphs)[:MAX_CHARS]


def fetch_article_text(url: str, session: requests.Session | None = None) -> str:
    if not url.startswith("http") or any(host in url for host in _SKIP_HOSTS):
        return ""
    client = session or requests
    try:
        response = client.get(url, timeout=15, headers=HEADERS)
    except requests.RequestException:
        return ""
    if response.status_code != 200 or "html" not in response.headers.get("Content-Type", "html"):
        return ""
    return extract_text(response.text)
