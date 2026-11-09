"""Store newly fetched articles. No LLM calls."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from stock_agent.core.config import Settings
from stock_agent.core.models import Security
from stock_agent.db.repository import Database
from stock_agent.ingest.news.sec_edgar import critical_item_types
from stock_agent.processing.normalize import drop_exact_duplicates, to_stored


def collect_articles(
    settings: Settings,
    db: Database,
    securities: list[Security],
    sources: list,
    *,
    since: datetime | None = None,
    now: datetime | None = None,
) -> dict:
    now = now or datetime.now(timezone.utc)
    known = db.known_content_hashes()
    stored = 0
    failures: list[str] = []
    alerts = 0
    for source in sources:
        window = since or _source_since(db, getattr(source, "name", ""), now)
        try:
            raws = list(source.fetch(window, securities))
        except Exception as exc:
            failures.append(f"{getattr(source, 'name', 'source')}: {exc}")
            continue
        failures.extend(getattr(source, "failures", None) or [])
        converted = []
        for raw in raws:
            if settings.critical_filings and raw.source == "sec_edgar_8k":
                for item_type in critical_item_types(raw.title, raw.body):
                    for ticker in raw.tickers or ("UNKNOWN",):
                        db.record_alert(now.date(), ticker, raw.url, item_type)
                        alerts += 1
            converted.append(to_stored(raw, now))
        fresh = drop_exact_duplicates(converted, known)
        known.update(article.content_hash for article in fresh)
        stored += db.upsert_articles(fresh)
    return {"stored": stored, "failures": failures, "alerts": alerts}


def _source_since(db: Database, source: str, now: datetime) -> datetime:
    """Each source keeps its own window, so a fast feed does not hide a slow one."""
    row = db.conn.execute(
        "SELECT MAX(published_at) AS ts FROM articles WHERE source = ?",
        (source,),
    ).fetchone()
    floor = now - timedelta(days=7)
    if not row or not row["ts"]:
        return floor
    latest = datetime.fromisoformat(row["ts"])
    if latest.tzinfo is None:
        latest = latest.replace(tzinfo=timezone.utc)
    return max(latest - timedelta(hours=6), floor)
