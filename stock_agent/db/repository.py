"""SQLite access for Phase 1 tables."""

from __future__ import annotations

import sqlite3
from datetime import date, datetime
from pathlib import Path

import pandas as pd

from stock_agent.core.models import PriceStats, Security

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


def _num(value: object) -> float | None:
    if value is None or (isinstance(value, float) and pd.isna(value)) or pd.isna(value):
        return None
    return float(value)
