"""Daily collection: refresh universes, store prices, compute price statistics."""

from __future__ import annotations

from datetime import date, timedelta

import pandas as pd

from stock_agent.analysis.benchmarks import SECTOR_ETF
from stock_agent.analysis.price_stats import close_series, compute_price_stats
from stock_agent.analysis.technical import compute_technical
from stock_agent.core.config import Settings
from stock_agent.core.models import Security
from stock_agent.db.repository import Database
from stock_agent.ingest.prices.yfinance_source import YFinancePriceSource
from stock_agent.universe import load_universe


def run_collection(
    settings: Settings,
    *,
    as_of: date | None = None,
    limit: int | None = None,
    tickers: list[str] | None = None,
    compute_stats: bool = True,
) -> dict[str, int]:
    as_of = as_of or date.today()
    summary = {"members": 0, "priced": 0, "rows": 0, "stats": 0}
    with Database(settings.database_path) as db:
        members = _refresh_universes(db, settings, as_of)
        summary["members"] = len(members)
        selected = _select(members, limit=limit, tickers=tickers)
        benchmarks = [
            Security(ticker=ticker, exchange="ETF", name=ticker) for ticker in settings.benchmarks
        ]
        db.upsert_companies(benchmarks, as_of)
        targets = _dedupe(selected + benchmarks)
        summary["rows"] = _update_prices(db, settings, targets, as_of)
        summary["priced"] = len(selected)
        if compute_stats:
            summary["stats"] = _update_stats(db, settings, selected, as_of)
    return summary


def _refresh_universes(db: Database, settings: Settings, as_of: date) -> list[Security]:
    cache_dir = settings.root / "data" / "cache"
    collected: list[Security] = []
    for spec in settings.universes:
        universe = load_universe(spec, cache_dir=cache_dir)
        members = universe.list_members()
        print(f"{universe.name}: {len(members)} members")
        db.sync_universe(universe.name, members, as_of)
        collected.extend(members)
    return _dedupe(collected)


def _select(members: list[Security], *, limit: int | None, tickers: list[str] | None) -> list[Security]:
    if tickers:
        wanted = {ticker.strip().upper() for ticker in tickers}
        return [sec for sec in members if sec.ticker.upper() in wanted]
    if limit is not None:
        return members[:limit]
    return members


def _update_prices(db: Database, settings: Settings, targets: list[Security], as_of: date) -> int:
    if settings.price_source != "yfinance":
        raise ValueError(
            f"Price source {settings.price_source!r} is not implemented. Use 'yfinance'."
        )
    source = YFinancePriceSource(batch_size=settings.batch_size)
    latest = db.latest_price_dates([sec.ticker for sec in targets])
    default_start = as_of - timedelta(days=round(365.25 * settings.history_years))
    groups: dict[date, list[Security]] = {}
    for sec in targets:
        last = latest.get(sec.ticker)
        start = default_start if last is None else last + timedelta(days=1)
        if start <= as_of:
            groups.setdefault(start, []).append(sec)
    if not groups:
        print("Prices already current.")
        return 0
    written = 0
    for start, group in sorted(groups.items()):
        print(f"Downloading {len(group)} tickers from {start.isoformat()} to {as_of.isoformat()}...")
        frame = source.history(group, start, as_of)
        missing = sorted({sec.ticker for sec in group} - set(frame["ticker"].unique() if not frame.empty else []))
        if missing:
            print(f"  No prices returned for {len(missing)} tickers: {', '.join(missing[:12])}")
        written += db.upsert_prices(frame)
    print(f"Stored {written} price rows.")
    return written


def _update_stats(db: Database, settings: Settings, selected: list[Security], as_of: date) -> int:
    needed = {sec.ticker for sec in selected}
    needed.update(settings.benchmarks)
    for sec in selected:
        etf = SECTOR_ETF.get(sec.sector or "")
        if etf:
            needed.add(etf)
    prices = db.load_prices(sorted(needed))
    if prices.empty:
        print("No prices stored, so no statistics were computed.")
        return 0
    by_ticker = {ticker: frame for ticker, frame in prices.groupby("ticker")}
    spy = close_series(by_ticker["SPY"]) if "SPY" in by_ticker else None
    sector_series = {
        etf: close_series(by_ticker[etf]) for etf in set(SECTOR_ETF.values()) if etf in by_ticker
    }
    stats = []
    for sec in selected:
        frame = by_ticker.get(sec.ticker)
        if frame is None or frame.empty:
            continue
        etf = SECTOR_ETF.get(sec.sector or "")
        item = compute_price_stats(
            frame,
            ticker=sec.ticker,
            spy=spy,
            sector_benchmark=sector_series.get(etf) if etf else None,
            as_of=as_of,
            lookback_years=settings.history_years,
        )
        if item is not None:
            stats.append(item)
            signals = compute_technical(close_series(frame))
            print(
                f"  {sec.ticker}: 1y { _pct(item.ret_1y) }, "
                f"max DD { _pct(item.max_drawdown) }, "
                f"above 200d MA {signals.above_ma200}"
            )
    db.upsert_price_stats(stats)
    print(f"Computed statistics for {len(stats)} tickers.")
    return len(stats)


def _dedupe(securities: list[Security]) -> list[Security]:
    seen: set[str] = set()
    unique: list[Security] = []
    for sec in securities:
        if sec.ticker in seen:
            continue
        seen.add(sec.ticker)
        unique.append(sec)
    return unique


def _pct(value: float | None) -> str:
    if value is None or pd.isna(value):
        return "n/a"
    return f"{value:+.1%}"
