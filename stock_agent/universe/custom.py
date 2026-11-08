"""A watchlist loaded from YAML or CSV."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import yaml

from stock_agent.core.config import PROJECT_ROOT
from stock_agent.core.models import Security


class CustomListUniverse:
    def __init__(self, name: str, directory: Path | None = None):
        self.list_name = name
        self.name = f"custom:{name}"
        self.directory = directory or (PROJECT_ROOT / "config" / "universes")

    def list_members(self) -> list[Security]:
        yaml_path = self.directory / f"{self.list_name}.yaml"
        csv_path = self.directory / f"{self.list_name}.csv"
        if yaml_path.exists():
            return _from_yaml(yaml_path)
        if csv_path.exists():
            return _from_csv(csv_path)
        raise FileNotFoundError(
            f"No watchlist named {self.list_name!r} in {self.directory} (.yaml or .csv)"
        )


def _from_yaml(path: Path) -> list[Security]:
    raw = yaml.safe_load(path.read_text()) or {}
    rows = raw.get("securities") or raw.get("tickers") or []
    securities = []
    for row in rows:
        if isinstance(row, str):
            securities.append(Security(ticker=row.strip(), exchange="", name=row.strip()))
            continue
        ticker = str(row["ticker"]).strip()
        securities.append(
            Security(
                ticker=ticker,
                exchange=str(row.get("exchange") or ""),
                name=str(row.get("name") or ticker),
                cik=row.get("cik"),
                sector=row.get("sector"),
                industry=row.get("industry"),
            )
        )
    return securities


def _from_csv(path: Path) -> list[Security]:
    frame = pd.read_csv(path, dtype=str).fillna("")
    if "ticker" not in frame.columns:
        raise ValueError(f"{path} must have a ticker column")
    securities = []
    for row in frame.to_dict(orient="records"):
        ticker = row["ticker"].strip()
        if not ticker:
            continue
        securities.append(
            Security(
                ticker=ticker,
                exchange=row.get("exchange", ""),
                name=row.get("name") or ticker,
                cik=row.get("cik") or None,
                sector=row.get("sector") or None,
                industry=row.get("industry") or None,
            )
        )
    return securities
