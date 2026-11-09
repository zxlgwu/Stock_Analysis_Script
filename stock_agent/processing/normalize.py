"""URL cleanup, boilerplate hashing, and article ids."""

from __future__ import annotations

import hashlib
import re
from datetime import datetime
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

from stock_agent.core.models import RawArticle, StoredArticle

_SPACE = re.compile(r"\s+")


def canonicalize_url(url: str) -> str:
    parsed = urlparse(url.strip())
    kept = [
        (key, value)
        for key, value in parse_qsl(parsed.query, keep_blank_values=False)
        if not key.lower().startswith("utm_")
    ]
    path = parsed.path.rstrip("/") or parsed.path
    return urlunparse(
        (parsed.scheme.lower(), parsed.netloc.lower(), path, "", urlencode(kept), "")
    )


def content_hash(title: str, body: str) -> str:
    text = _SPACE.sub(" ", f"{title} {body}".lower()).strip()
    return hashlib.sha256(text.encode()).hexdigest()


def article_id(source: str, url: str, title: str) -> str:
    raw = f"{source}|{canonicalize_url(url)}|{title.strip().lower()}"
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


def to_stored(article: RawArticle, fetched_at: datetime) -> StoredArticle:
    url = canonicalize_url(article.url)
    return StoredArticle(
        id=article_id(article.source, url, article.title),
        source=article.source,
        url=url,
        title=article.title.strip(),
        body=article.body.strip(),
        published_at=article.published_at,
        fetched_at=fetched_at,
        content_hash=content_hash(article.title, article.body),
    )


def drop_exact_duplicates(
    articles: list[StoredArticle], known_hashes: set[str]
) -> list[StoredArticle]:
    seen = set(known_hashes)
    kept: list[StoredArticle] = []
    for article in articles:
        if article.content_hash in seen:
            continue
        seen.add(article.content_hash)
        kept.append(article)
    return kept
