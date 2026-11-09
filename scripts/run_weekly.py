"""Run the weekly analysis and write the email report.

Examples:
    python scripts/run_weekly.py
    python scripts/run_weekly.py --no-email
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from stock_agent.core.config import Settings
from stock_agent.jobs.weekly import run_weekly
from stock_agent.notify.email_smtp import MissingSMTP


def main() -> None:
    parser = argparse.ArgumentParser(description="Cluster the week's news, score the universe, and build the report.")
    parser.add_argument("--no-email", action="store_true", help="Write the HTML report without sending it")
    args = parser.parse_args()
    summary = run_weekly(Settings.load(), notifier=_silent() if args.no_email else None)
    print(
        f"Week {summary['week_ending']}: clusters {summary['clusters']}, "
        f"impacts {summary['impacts']}, scores {summary['scores']}, email {summary['email_status']}."
    )
    print(summary["report_path"])


def _silent():
    class _NoSend:
        def send(self, report):
            raise MissingSMTP("Email sending is disabled for this run.")

    return _NoSend()


if __name__ == "__main__":
    main()
