"""Build a price-chart PDF for tickers already stored in the database.

Example:
    python scripts/make_charts.py --tickers AAPL,MSFT,NVDA --open
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import yfinance as yf

from stock_agent.analysis.price_stats import close_series, friday_on_or_before
from stock_agent.core.config import Settings
from stock_agent.db.repository import Database
from stock_agent.ingest.prices.symbols import to_yfinance_symbol
from stock_agent.report.charts import ChartSpec, render_price_charts


def main() -> None:
    parser = argparse.ArgumentParser(description="Render multi-year price charts to PNG and PDF.")
    parser.add_argument("--tickers", required=True, help="Comma-separated tickers, in chart order")
    parser.add_argument("--years", type=int, default=None, help="Years of history to plot (default from settings)")
    parser.add_argument("--no-market-cap", action="store_true", help="Skip the market-cap lookup in the title")
    parser.add_argument("--benchmark-panel", action="store_true", help="Add a panel rebased against SPY")
    parser.add_argument("--open", action="store_true", help="Open the PDF when it is ready")
    args = parser.parse_args()

    settings = Settings.load()
    tickers = [part.strip().upper() for part in args.tickers.split(",") if part.strip()]
    week = friday_on_or_before(date.today())
    dest = settings.root / "output" / "charts" / week.isoformat()

    with Database(settings.database_path) as db:
        companies = db.get_companies(tickers)
        prices = db.load_prices(tickers + ["SPY"])
    if prices.empty:
        raise SystemExit("No prices in the database. Run scripts/collect_daily.py first.")

    by_ticker = {ticker: frame for ticker, frame in prices.groupby("ticker")}
    missing = [ticker for ticker in tickers if ticker not in by_ticker]
    if missing:
        raise SystemExit(f"No stored prices for: {', '.join(missing)}")

    caps = {} if args.no_market_cap else _market_caps(tickers)
    spy = close_series(by_ticker["SPY"]) if "SPY" in by_ticker else None
    charts = [
        ChartSpec(
            ticker=ticker,
            name=companies[ticker].name if ticker in companies else ticker,
            prices=by_ticker[ticker],
            market_cap=caps.get(ticker),
            benchmark=spy,
        )
        for ticker in tickers
    ]
    pngs, pdf = render_price_charts(
        charts,
        dest_dir=dest,
        years=args.years or settings.chart_years,
        moving_averages=settings.moving_averages,
        show_event_markers=settings.show_event_markers,
        show_benchmark_panel=args.benchmark_panel or settings.show_benchmark_panel,
    )
    print(f"Wrote {len(pngs)} charts")
    print(pdf)
    if args.open:
        subprocess.run(["open", str(pdf)], check=False)


def _market_caps(tickers: list[str]) -> dict[str, float]:
    caps: dict[str, float] = {}
    for ticker in tickers:
        try:
            info = yf.Ticker(to_yfinance_symbol(ticker)).fast_info
            value = _fast_info_value(info, "market_cap", "marketCap")
            if value:
                caps[ticker] = float(value)
        except Exception as exc:
            print(f"Market cap unavailable for {ticker}: {exc}")
    return caps


def _fast_info_value(info: object, *names: str) -> object:
    for name in names:
        try:
            value = info[name]
        except Exception:
            value = getattr(info, name, None)
        if value:
            return value
    return None


if __name__ == "__main__":
    main()
