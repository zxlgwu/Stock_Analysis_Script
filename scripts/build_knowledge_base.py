"""Refresh XBRL fundamentals and optional 10-K relationship notes.

Examples:
    python scripts/build_knowledge_base.py --tickers AAPL,MSFT
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from stock_agent.core.config import Settings
from stock_agent.db.repository import Database
from stock_agent.ingest.fundamentals.sec_xbrl import fetch_companyfacts, parse_companyfacts
from stock_agent.jobs.weekly import _members
from stock_agent.knowledge.profile_builder import build_profile


def main() -> None:
    parser = argparse.ArgumentParser(description="Build company profiles from SEC companyfacts.")
    parser.add_argument("--tickers", default=None, help="Comma-separated tickers. Default: every active member with a CIK.")
    args = parser.parse_args()
    wanted = {part.strip().upper() for part in args.tickers.split(",")} if args.tickers else None
    settings = Settings.load()
    stored = 0
    with Database(settings.database_path) as db:
        securities = _members(settings, db)
        known = {security.ticker for security in securities}
        for security in securities:
            if wanted is not None and security.ticker not in wanted:
                continue
            if not security.cik:
                print(f"{security.ticker}: no CIK, skipped")
                continue
            try:
                payload = fetch_companyfacts(security.cik)
            except Exception as exc:
                print(f"{security.ticker}: companyfacts failed: {exc}")
                continue
            rows, segments, regions = parse_companyfacts(payload, security.ticker)
            profile, relations = build_profile(
                security.ticker, rows, segments, regions, known_tickers=known
            )
            db.upsert_fundamentals(rows)
            db.upsert_profile(profile)
            db.replace_relations(security.ticker, relations)
            stored += 1
            print(f"{security.ticker}: {len(rows)} annual periods, {len(relations)} relations")
    print(f"Updated {stored} profiles.")


if __name__ == "__main__":
    main()
