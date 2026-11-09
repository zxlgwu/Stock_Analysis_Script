"""Refresh stock-list membership and store daily prices.

Examples:
    python scripts/collect_daily.py --limit 20
    python scripts/collect_daily.py --tickers AAPL,MSFT,NVDA
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from stock_agent.core.config import Settings
from stock_agent.jobs.collect import run_collection


def main() -> None:
    parser = argparse.ArgumentParser(description="Collect universe membership and daily prices.")
    parser.add_argument("--limit", type=int, default=None, help="Download prices for the first N members only")
    parser.add_argument("--tickers", default=None, help="Comma-separated tickers to price instead")
    parser.add_argument("--skip-stats", action="store_true", help="Store prices without computing statistics")
    parser.add_argument("--skip-news", action="store_true", help="Skip news and filing collection")
    args = parser.parse_args()
    tickers = [part.strip() for part in args.tickers.split(",")] if args.tickers else None
    summary = run_collection(
        Settings.load(),
        limit=args.limit,
        tickers=tickers,
        compute_stats=not args.skip_stats,
        collect_news=not args.skip_news,
    )
    print(
        f"Done. Members {summary['members']}, priced {summary['priced']}, "
        f"rows {summary['rows']}, stats {summary['stats']}, articles {summary['articles']}."
    )


if __name__ == "__main__":
    main()
