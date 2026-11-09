"""SQLite access for stock-agent tables."""

from __future__ import annotations

import json
import sqlite3
from datetime import date, datetime
from pathlib import Path

import pandas as pd

from stock_agent.core.models import (
    CompanyProfile,
    Fundamental,
    PriceStats,
    Relation,
    ScoreRecord,
    Security,
    StoredArticle,
)

_SCHEMA = Path(__file__).with_name("schema.sql").read_text()


def _iso(value: date | None) -> str | None:
    return value.isoformat() if value is not None else None


class Database:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        self.conn = sqlite3.connect(path)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON")
        self.conn.executescript(_SCHEMA)

    def close(self) -> None:
        self.conn.close()

    def __enter__(self) -> Database:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def upsert_companies(self, securities: list[Security], updated_at: date) -> None:
        rows = [
            (
                sec.ticker,
                sec.exchange,
                sec.name,
                sec.cik,
                sec.sector,
                sec.industry,
                updated_at.isoformat(),
            )
            for sec in securities
        ]
        self.conn.executemany(
            """
            INSERT INTO companies (ticker, exchange, name, cik, sector, industry, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(ticker) DO UPDATE SET
                exchange = COALESCE(excluded.exchange, companies.exchange),
                name = COALESCE(excluded.name, companies.name),
                cik = COALESCE(excluded.cik, companies.cik),
                sector = COALESCE(excluded.sector, companies.sector),
                industry = COALESCE(excluded.industry, companies.industry),
                updated_at = excluded.updated_at
            """,
            rows,
        )
        self.conn.commit()

    def sync_universe(self, universe: str, securities: list[Security], as_of: date) -> None:
        """Insert new members and mark departed members removed. Keeps history."""
        self.upsert_companies(securities, as_of)
        incoming = {sec.ticker for sec in securities}
        active = {
            row["ticker"]
            for row in self.conn.execute(
                """
                SELECT ticker FROM universe_members
                WHERE universe = ? AND removed_at IS NULL
                """,
                (universe,),
            )
        }
        stamp = as_of.isoformat()
        new_rows = [(universe, ticker, stamp) for ticker in sorted(incoming - active)]
        self.conn.executemany(
            """
            INSERT INTO universe_members (universe, ticker, added_at, removed_at)
            VALUES (?, ?, ?, NULL)
            """,
            new_rows,
        )
        departed = sorted(active - incoming)
        self.conn.executemany(
            """
            UPDATE universe_members
            SET removed_at = ?
            WHERE universe = ? AND ticker = ? AND removed_at IS NULL
            """,
            [(stamp, universe, ticker) for ticker in departed],
        )
        self.conn.commit()

    def active_members(self, universe: str) -> list[Security]:
        rows = self.conn.execute(
            """
            SELECT c.ticker, c.exchange, c.name, c.cik, c.sector, c.industry
            FROM universe_members m
            JOIN companies c ON c.ticker = m.ticker
            WHERE m.universe = ? AND m.removed_at IS NULL
            ORDER BY c.ticker
            """,
            (universe,),
        ).fetchall()
        return [
            Security(
                ticker=row["ticker"],
                exchange=row["exchange"] or "",
                name=row["name"] or row["ticker"],
                cik=row["cik"],
                sector=row["sector"],
                industry=row["industry"],
            )
            for row in rows
        ]

    def latest_price_dates(self, tickers: list[str]) -> dict[str, date]:
        if not tickers:
            return {}
        placeholders = ",".join("?" * len(tickers))
        rows = self.conn.execute(
            f"""
            SELECT ticker, MAX(date) AS max_date
            FROM prices
            WHERE ticker IN ({placeholders})
            GROUP BY ticker
            """,
            tickers,
        ).fetchall()
        return {row["ticker"]: date.fromisoformat(row["max_date"]) for row in rows}

    def upsert_prices(self, frame: pd.DataFrame) -> int:
        if frame.empty:
            return 0
        records = []
        for row in frame.itertuples(index=False):
            day = row.date
            if isinstance(day, datetime):
                day = day.date()
            elif hasattr(day, "date") and not isinstance(day, date):
                day = day.date()
            volume = None if pd.isna(row.volume) else int(row.volume)
            records.append(
                (
                    row.ticker,
                    day.isoformat(),
                    _num(row.open),
                    _num(row.high),
                    _num(row.low),
                    _num(row.close),
                    _num(row.adj_close),
                    volume,
                )
            )
        self.conn.executemany(
            """
            INSERT INTO prices (ticker, date, open, high, low, close, adj_close, volume)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(ticker, date) DO UPDATE SET
                open = excluded.open,
                high = excluded.high,
                low = excluded.low,
                close = excluded.close,
                adj_close = excluded.adj_close,
                volume = excluded.volume
            """,
            records,
        )
        self.conn.commit()
        return len(records)

    def get_companies(self, tickers: list[str]) -> dict[str, Security]:
        if not tickers:
            return {}
        placeholders = ",".join("?" * len(tickers))
        rows = self.conn.execute(
            f"""
            SELECT ticker, exchange, name, cik, sector, industry
            FROM companies
            WHERE ticker IN ({placeholders})
            """,
            tickers,
        ).fetchall()
        return {
            row["ticker"]: Security(
                ticker=row["ticker"],
                exchange=row["exchange"] or "",
                name=row["name"] or row["ticker"],
                cik=row["cik"],
                sector=row["sector"],
                industry=row["industry"],
            )
            for row in rows
        }

    def load_prices(self, tickers: list[str]) -> pd.DataFrame:
        if not tickers:
            return pd.DataFrame(
                columns=["ticker", "date", "open", "high", "low", "close", "adj_close", "volume"]
            )
        placeholders = ",".join("?" * len(tickers))
        frame = pd.read_sql_query(
            f"""
            SELECT ticker, date, open, high, low, close, adj_close, volume
            FROM prices
            WHERE ticker IN ({placeholders})
            ORDER BY ticker, date
            """,
            self.conn,
            params=tickers,
        )
        frame["date"] = pd.to_datetime(frame["date"])
        return frame

    def upsert_price_stats(self, stats: list[PriceStats]) -> None:
        rows = [
            (
                item.week_ending.isoformat(),
                item.ticker,
                item.ret_1y,
                item.ret_3y,
                item.ret_5y,
                item.cagr,
                item.rel_spy_1y,
                item.rel_spy_3y,
                item.rel_spy_5y,
                item.rel_sector_1y,
                item.rel_sector_3y,
                item.rel_sector_5y,
                item.max_drawdown,
                _iso(item.max_dd_start),
                _iso(item.max_dd_end),
                item.current_drawdown,
                item.vol_1y,
                item.vol_full,
                item.ma_convergence,
            )
            for item in stats
        ]
        self.conn.executemany(
            """
            INSERT INTO price_stats_weekly (
                week_ending, ticker, ret_1y, ret_3y, ret_5y, cagr,
                rel_spy_1y, rel_spy_3y, rel_spy_5y,
                rel_sector_1y, rel_sector_3y, rel_sector_5y,
                max_drawdown, max_dd_start, max_dd_end, current_drawdown,
                vol_1y, vol_full, ma_convergence
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(week_ending, ticker) DO UPDATE SET
                ret_1y = excluded.ret_1y,
                ret_3y = excluded.ret_3y,
                ret_5y = excluded.ret_5y,
                cagr = excluded.cagr,
                rel_spy_1y = excluded.rel_spy_1y,
                rel_spy_3y = excluded.rel_spy_3y,
                rel_spy_5y = excluded.rel_spy_5y,
                rel_sector_1y = excluded.rel_sector_1y,
                rel_sector_3y = excluded.rel_sector_3y,
                rel_sector_5y = excluded.rel_sector_5y,
                max_drawdown = excluded.max_drawdown,
                max_dd_start = excluded.max_dd_start,
                max_dd_end = excluded.max_dd_end,
                current_drawdown = excluded.current_drawdown,
                vol_1y = excluded.vol_1y,
                vol_full = excluded.vol_full,
                ma_convergence = excluded.ma_convergence
            """,
            rows,
        )
        self.conn.commit()

    def upsert_articles(self, articles: list[StoredArticle]) -> int:
        rows = [
            (
                article.id,
                article.source,
                article.url,
                article.title,
                article.body,
                article.published_at.isoformat(),
                article.fetched_at.isoformat(),
                article.content_hash,
                article.cluster_id,
            )
            for article in articles
        ]
        before = self.conn.total_changes
        self.conn.executemany(
            """
            INSERT INTO articles (
                id, source, url, title, body, published_at, fetched_at, content_hash, cluster_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO NOTHING
            """,
            rows,
        )
        self.conn.commit()
        return self.conn.total_changes - before

    def known_content_hashes(self) -> set[str]:
        rows = self.conn.execute(
            "SELECT content_hash FROM articles WHERE content_hash IS NOT NULL"
        ).fetchall()
        return {row["content_hash"] for row in rows}

    def unclustered_articles(self) -> list[StoredArticle]:
        rows = self.conn.execute(
            """
            SELECT id, source, url, title, body, published_at, fetched_at, content_hash, cluster_id
            FROM articles
            WHERE cluster_id IS NULL
            ORDER BY published_at, id
            """
        ).fetchall()
        return [_article(row) for row in rows]

    def articles_by_ids(self, ids: list[str]) -> list[StoredArticle]:
        if not ids:
            return []
        placeholders = ",".join("?" * len(ids))
        rows = self.conn.execute(
            f"""
            SELECT id, source, url, title, body, published_at, fetched_at, content_hash, cluster_id
            FROM articles WHERE id IN ({placeholders})
            """,
            ids,
        ).fetchall()
        return [_article(row) for row in rows]

    def assign_cluster(self, article_ids: list[str], cluster_id: str) -> None:
        self.conn.executemany(
            "UPDATE articles SET cluster_id = ? WHERE id = ?",
            [(cluster_id, article_id) for article_id in article_ids],
        )
        self.conn.commit()

    def upsert_cluster(
        self,
        cluster_id: str,
        representative_id: str,
        first_seen: datetime,
        size: int,
        *,
        dropped: bool = False,
        drop_reason: str | None = None,
        event_summary: str | None = None,
    ) -> None:
        self.conn.execute(
            """
            INSERT INTO article_clusters (
                cluster_id, representative_article_id, first_seen, size,
                event_summary, dropped, drop_reason
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(cluster_id) DO UPDATE SET
                representative_article_id = excluded.representative_article_id,
                first_seen = excluded.first_seen,
                size = excluded.size,
                event_summary = COALESCE(excluded.event_summary, article_clusters.event_summary),
                dropped = excluded.dropped,
                drop_reason = excluded.drop_reason
            """,
            (
                cluster_id,
                representative_id,
                first_seen.isoformat(),
                size,
                event_summary,
                int(dropped),
                drop_reason,
            ),
        )
        self.conn.commit()

    def replace_entities(self, cluster_id: str, links: list[tuple[str, str]]) -> None:
        self.conn.execute("DELETE FROM cluster_entities WHERE cluster_id = ?", (cluster_id,))
        self.conn.executemany(
            """
            INSERT INTO cluster_entities (cluster_id, ticker, link_type)
            VALUES (?, ?, ?)
            """,
            [(cluster_id, ticker, link_type) for ticker, link_type in links],
        )
        self.conn.commit()

    def pending_clusters(self) -> list[dict]:
        rows = self.conn.execute(
            """
            SELECT c.cluster_id, c.representative_article_id, c.dropped
            FROM article_clusters c
            LEFT JOIN materiality m ON m.cluster_id = c.cluster_id
            WHERE m.cluster_id IS NULL AND c.dropped = 0
            ORDER BY c.first_seen, c.cluster_id
            """
        ).fetchall()
        return [dict(row) for row in rows]

    def cluster_entities(self, cluster_id: str) -> list[tuple[str, str]]:
        rows = self.conn.execute(
            """
            SELECT ticker, link_type FROM cluster_entities
            WHERE cluster_id = ? ORDER BY link_type, ticker
            """,
            (cluster_id,),
        ).fetchall()
        return [(row["ticker"], row["link_type"]) for row in rows]

    def save_materiality(
        self,
        cluster_id: str,
        material: bool,
        category: str,
        reason: str,
        model: str,
        prompt_version: str,
    ) -> None:
        self.conn.execute(
            """
            INSERT INTO materiality (cluster_id, material, category, reason, model, prompt_version)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(cluster_id) DO UPDATE SET
                material = excluded.material,
                category = excluded.category,
                reason = excluded.reason,
                model = excluded.model,
                prompt_version = excluded.prompt_version
            """,
            (cluster_id, int(material), category, reason, model, prompt_version),
        )
        self.conn.commit()

    def material_clusters_without_impacts(self) -> list[str]:
        rows = self.conn.execute(
            """
            SELECT m.cluster_id
            FROM materiality m
            LEFT JOIN impacts i ON i.cluster_id = m.cluster_id
            WHERE m.material = 1 AND i.cluster_id IS NULL
            ORDER BY m.cluster_id
            """
        ).fetchall()
        return [row["cluster_id"] for row in rows]

    def save_impacts(self, rows: list[tuple]) -> None:
        self.conn.executemany(
            """
            INSERT INTO impacts (
                cluster_id, ticker, relation, direction, revenue_line, est_pct, horizon,
                confidence, priced_in, reasoning, model, prompt_version, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(cluster_id, ticker, horizon, relation) DO UPDATE SET
                direction = excluded.direction,
                revenue_line = excluded.revenue_line,
                est_pct = excluded.est_pct,
                confidence = excluded.confidence,
                priced_in = excluded.priced_in,
                reasoning = excluded.reasoning,
                model = excluded.model,
                prompt_version = excluded.prompt_version,
                created_at = excluded.created_at
            """,
            rows,
        )
        self.conn.commit()

    def load_impacts(self) -> list[dict]:
        rows = self.conn.execute(
            """
            SELECT i.cluster_id, i.ticker, i.relation, i.direction, i.revenue_line, i.est_pct,
                   i.horizon, i.confidence, i.priced_in, i.reasoning, i.model, i.prompt_version,
                   i.created_at, a.source, a.published_at, a.title, a.url, c.event_summary
            FROM impacts i
            JOIN article_clusters c ON c.cluster_id = i.cluster_id
            JOIN articles a ON a.id = c.representative_article_id
            """
        ).fetchall()
        return [dict(row) for row in rows]

    def material_titles(self, limit: int = 8) -> list[str]:
        rows = self.conn.execute(
            """
            SELECT COALESCE(c.event_summary, a.title) AS title
            FROM materiality m
            JOIN article_clusters c ON c.cluster_id = m.cluster_id
            JOIN articles a ON a.id = c.representative_article_id
            WHERE m.material = 1
            ORDER BY a.published_at DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
        return [row["title"] for row in rows if row["title"]]

    def analyzed_stories(self) -> list[dict]:
        rows = self.conn.execute(
            """
            SELECT m.cluster_id, m.material, m.reason,
                   COALESCE(c.event_summary, a.title) AS summary,
                   a.title, a.url
            FROM materiality m
            JOIN article_clusters c ON c.cluster_id = m.cluster_id
            JOIN articles a ON a.id = c.representative_article_id
            WHERE m.material = 1
               OR m.reason = 'No public company has a concrete revenue mechanism.'
               OR m.reason = 'No tracked company has a concrete revenue mechanism.'
            ORDER BY a.published_at DESC
            """
        ).fetchall()
        return [dict(row) for row in rows]

    def replace_channels(self, cluster_id: str, rows: list[tuple]) -> None:
        """rows: (target, kind, order, relation, direction, mechanism, tickers, model, prompt_version)."""
        self.conn.execute("DELETE FROM impact_channels WHERE cluster_id = ?", (cluster_id,))
        self.conn.executemany(
            """
            INSERT INTO impact_channels (
                cluster_id, position, target, kind, ord, relation, direction,
                mechanism, tickers, model, prompt_version
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [(cluster_id, position, *row) for position, row in enumerate(rows)],
        )
        self.conn.commit()

    def channels_for(self, cluster_id: str) -> list[dict]:
        rows = self.conn.execute(
            """
            SELECT target, kind, ord, relation, direction, mechanism, tickers
            FROM impact_channels WHERE cluster_id = ? ORDER BY ord, position
            """,
            (cluster_id,),
        ).fetchall()
        return [dict(row) for row in rows]

    def update_article_body(self, article_id: str, body: str) -> None:
        self.conn.execute("UPDATE articles SET body = ? WHERE id = ?", (body, article_id))
        self.conn.commit()

    def liquidity(self, days: int = 30) -> dict[str, float]:
        """Average daily dollar volume over the latest window, used to pick the largest names in an industry."""
        rows = self.conn.execute(
            """
            SELECT ticker, AVG(close * volume) AS dollars
            FROM prices
            WHERE date >= date((SELECT MAX(date) FROM prices), ?)
            GROUP BY ticker
            """,
            (f"-{int(days)} days",),
        ).fetchall()
        return {row["ticker"]: float(row["dollars"] or 0.0) for row in rows}

    def set_event_summary(self, cluster_id: str, summary: str) -> None:
        self.conn.execute(
            "UPDATE article_clusters SET event_summary = ? WHERE cluster_id = ?",
            (summary, cluster_id),
        )
        self.conn.commit()

    def upsert_profile(self, profile: CompanyProfile) -> None:
        self.conn.execute(
            """
            INSERT INTO company_profiles (
                ticker, segments_json, regions_json, sensitivities_json, summary, as_of
            ) VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(ticker) DO UPDATE SET
                segments_json = excluded.segments_json,
                regions_json = excluded.regions_json,
                sensitivities_json = excluded.sensitivities_json,
                summary = excluded.summary,
                as_of = excluded.as_of
            """,
            (
                profile.ticker,
                json.dumps(profile.segments),
                json.dumps(profile.regions),
                json.dumps(profile.sensitivities),
                profile.summary,
                _iso(profile.as_of),
            ),
        )
        self.conn.commit()

    def get_profile(self, ticker: str) -> CompanyProfile | None:
        row = self.conn.execute(
            "SELECT * FROM company_profiles WHERE ticker = ?", (ticker,)
        ).fetchone()
        if row is None:
            return None
        return CompanyProfile(
            ticker=row["ticker"],
            segments=json.loads(row["segments_json"] or "{}"),
            regions=json.loads(row["regions_json"] or "{}"),
            sensitivities=json.loads(row["sensitivities_json"] or "[]"),
            summary=row["summary"] or "",
            as_of=date.fromisoformat(row["as_of"]) if row["as_of"] else None,
        )

    def replace_relations(self, src_ticker: str, relations: list[Relation]) -> None:
        self.conn.execute("DELETE FROM company_relations WHERE src_ticker = ?", (src_ticker,))
        self.conn.executemany(
            """
            INSERT INTO company_relations (
                src_ticker, dst_key, dst_ticker, relation, evidence, confidence
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    item.src_ticker,
                    item.dst_key,
                    item.dst_ticker,
                    item.relation,
                    item.evidence,
                    item.confidence,
                )
                for item in relations
            ],
        )
        self.conn.commit()

    def all_relations(self) -> list[Relation]:
        rows = self.conn.execute(
            """
            SELECT src_ticker, dst_key, dst_ticker, relation, evidence, confidence
            FROM company_relations
            """
        ).fetchall()
        return [
            Relation(
                src_ticker=row["src_ticker"],
                dst_key=row["dst_key"],
                relation=row["relation"],
                evidence=row["evidence"] or "",
                confidence=row["confidence"] if row["confidence"] is not None else 0.5,
                dst_ticker=row["dst_ticker"],
            )
            for row in rows
        ]

    def upsert_fundamentals(self, rows: list[Fundamental]) -> None:
        self.conn.executemany(
            """
            INSERT INTO fundamentals (
                ticker, period_end, revenue, gross_margin, op_margin, fcf, eps, source, filed_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(ticker, period_end, source) DO UPDATE SET
                revenue = excluded.revenue,
                gross_margin = excluded.gross_margin,
                op_margin = excluded.op_margin,
                fcf = excluded.fcf,
                eps = excluded.eps,
                filed_at = excluded.filed_at
            """,
            [
                (
                    item.ticker,
                    item.period_end.isoformat(),
                    item.revenue,
                    item.gross_margin,
                    item.op_margin,
                    item.fcf,
                    item.eps,
                    item.source,
                    _iso(item.filed_at),
                )
                for item in rows
            ],
        )
        self.conn.commit()

    def fundamentals_for(self, ticker: str) -> list[Fundamental]:
        rows = self.conn.execute(
            """
            SELECT ticker, period_end, revenue, gross_margin, op_margin, fcf, eps, source, filed_at
            FROM fundamentals WHERE ticker = ? ORDER BY period_end
            """,
            (ticker,),
        ).fetchall()
        return [
            Fundamental(
                ticker=row["ticker"],
                period_end=date.fromisoformat(row["period_end"]),
                revenue=row["revenue"],
                gross_margin=row["gross_margin"],
                op_margin=row["op_margin"],
                fcf=row["fcf"],
                eps=row["eps"],
                source=row["source"],
                filed_at=date.fromisoformat(row["filed_at"]) if row["filed_at"] else None,
            )
            for row in rows
        ]

    def upsert_scores(self, scores: list[ScoreRecord]) -> None:
        self.conn.executemany(
            """
            INSERT INTO scores_weekly (
                week_ending, ticker, news_mid, news_long, net_revenue_mid, net_revenue_long,
                quality, value, technical, risk, composite
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(week_ending, ticker) DO UPDATE SET
                news_mid = excluded.news_mid,
                news_long = excluded.news_long,
                net_revenue_mid = excluded.net_revenue_mid,
                net_revenue_long = excluded.net_revenue_long,
                quality = excluded.quality,
                value = excluded.value,
                technical = excluded.technical,
                risk = excluded.risk,
                composite = excluded.composite
            """,
            [
                (
                    item.week_ending.isoformat(),
                    item.ticker,
                    item.news_mid,
                    item.news_long,
                    item.net_revenue_mid,
                    item.net_revenue_long,
                    item.quality,
                    item.value,
                    item.technical,
                    item.risk,
                    item.composite,
                )
                for item in scores
            ],
        )
        self.conn.commit()

    def scores_for(self, week_ending: date) -> list[ScoreRecord]:
        rows = self.conn.execute(
            "SELECT * FROM scores_weekly WHERE week_ending = ? ORDER BY ticker",
            (week_ending.isoformat(),),
        ).fetchall()
        return [_score(row) for row in rows]

    def replace_recommendations(self, week_ending: date, rows: list[tuple]) -> None:
        self.conn.execute(
            "DELETE FROM recommendations WHERE week_ending = ?", (week_ending.isoformat(),)
        )
        self.conn.executemany(
            """
            INSERT INTO recommendations (week_ending, ticker, list_name, rank, thesis, risks)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            rows,
        )
        self.conn.commit()

    def recommendations_for(self, week_ending: date) -> list[dict]:
        rows = self.conn.execute(
            """
            SELECT week_ending, ticker, list_name, rank, thesis, risks
            FROM recommendations WHERE week_ending = ?
            ORDER BY list_name, rank
            """,
            (week_ending.isoformat(),),
        ).fetchall()
        return [dict(row) for row in rows]

    def record_report(self, week_ending: date, recipients: list[str], status: str, message_id: str | None) -> None:
        self.conn.execute(
            """
            INSERT INTO reports_sent (week_ending, recipients, status, message_id)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(week_ending) DO UPDATE SET
                recipients = excluded.recipients,
                status = excluded.status,
                message_id = excluded.message_id
            """,
            (week_ending.isoformat(), ",".join(recipients), status, message_id),
        )
        self.conn.commit()

    def record_alert(self, day: date, ticker: str, filing_url: str, item_type: str) -> None:
        self.conn.execute(
            """
            INSERT INTO alerts_sent (date, ticker, filing_url, item_type)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(date, ticker, item_type) DO NOTHING
            """,
            (day.isoformat(), ticker, filing_url, item_type),
        )
        self.conn.commit()

    def record_metric(self, as_of: date, metric: str, horizon: str, value: float) -> None:
        self.conn.execute(
            """
            INSERT INTO evaluation_metrics (as_of, metric, horizon, value)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(as_of, metric, horizon) DO UPDATE SET value = excluded.value
            """,
            (as_of.isoformat(), metric, horizon, value),
        )
        self.conn.commit()

    def metrics_for(self, as_of: date) -> list[dict]:
        rows = self.conn.execute(
            "SELECT metric, horizon, value FROM evaluation_metrics WHERE as_of = ? ORDER BY metric",
            (as_of.isoformat(),),
        ).fetchall()
        return [dict(row) for row in rows]

    def mark_step(self, week_ending: date, step: str, status: str, updated_at: datetime) -> None:
        self.conn.execute(
            """
            INSERT INTO job_steps (week_ending, step, status, updated_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(week_ending, step) DO UPDATE SET
                status = excluded.status,
                updated_at = excluded.updated_at
            """,
            (week_ending.isoformat(), step, status, updated_at.isoformat()),
        )
        self.conn.commit()

    def log_llm_call(
        self,
        *,
        ts: datetime,
        role: str,
        provider: str,
        model: str,
        input_tokens: int,
        output_tokens: int,
        cost_usd: float,
        cache_hit: bool,
    ) -> None:
        self.conn.execute(
            """
            INSERT INTO llm_calls (
                ts, role, provider, model, input_tokens, output_tokens, cost_usd, cache_hit
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                ts.isoformat(),
                role,
                provider,
                model,
                input_tokens,
                output_tokens,
                cost_usd,
                int(cache_hit),
            ),
        )
        self.conn.commit()

    def llm_spend_since(self, start: datetime) -> float:
        row = self.conn.execute(
            """
            SELECT COALESCE(SUM(cost_usd), 0) AS spent
            FROM llm_calls
            WHERE cache_hit = 0 AND ts >= ?
            """,
            (start.isoformat(),),
        ).fetchone()
        return float(row["spent"])

    def llm_calls(self) -> list[dict]:
        rows = self.conn.execute(
            """
            SELECT ts, role, provider, model, input_tokens, output_tokens, cost_usd, cache_hit
            FROM llm_calls ORDER BY id
            """
        ).fetchall()
        return [dict(row) for row in rows]

    def get_llm_cache(self, model: str, prompt_hash: str) -> str | None:
        row = self.conn.execute(
            "SELECT response_json FROM llm_cache WHERE model = ? AND prompt_hash = ?",
            (model, prompt_hash),
        ).fetchone()
        return None if row is None else row["response_json"]

    def put_llm_cache(self, model: str, prompt_hash: str, payload: str, created_at: datetime) -> None:
        self.conn.execute(
            """
            INSERT INTO llm_cache (model, prompt_hash, response_json, created_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(model, prompt_hash) DO UPDATE SET
                response_json = excluded.response_json,
                created_at = excluded.created_at
            """,
            (model, prompt_hash, payload, created_at.isoformat()),
        )
        self.conn.commit()


def _article(row: sqlite3.Row) -> StoredArticle:
    return StoredArticle(
        id=row["id"],
        source=row["source"],
        url=row["url"] or "",
        title=row["title"] or "",
        body=row["body"] or "",
        published_at=datetime.fromisoformat(row["published_at"]),
        fetched_at=datetime.fromisoformat(row["fetched_at"]),
        content_hash=row["content_hash"] or "",
        cluster_id=row["cluster_id"],
    )


def _score(row: sqlite3.Row) -> ScoreRecord:
    return ScoreRecord(
        week_ending=date.fromisoformat(row["week_ending"]),
        ticker=row["ticker"],
        news_mid=row["news_mid"] or 0.0,
        news_long=row["news_long"] or 0.0,
        net_revenue_mid=row["net_revenue_mid"] or 0.0,
        net_revenue_long=row["net_revenue_long"] or 0.0,
        quality=row["quality"] or 0.0,
        value=row["value"] or 0.0,
        technical=row["technical"] or 0.0,
        risk=row["risk"] or 0.0,
        composite=row["composite"] or 0.0,
    )


def _num(value: object) -> float | None:
    if value is None or (isinstance(value, float) and pd.isna(value)) or pd.isna(value):
        return None
    return float(value)
