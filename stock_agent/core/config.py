"""Load config/settings.yaml and optional .env values."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

import yaml
from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[2]


@dataclass(frozen=True)
class RoleConfig:
    provider: str
    model: str


@dataclass(frozen=True)
class Settings:
    root: Path
    universes: list[str]
    price_source: str
    database_path: Path
    history_years: int
    benchmarks: list[str]
    batch_size: int
    chart_years: int
    moving_averages: list[int]
    show_event_markers: bool
    show_benchmark_panel: bool
    llm_roles: dict[str, RoleConfig]
    weekly_budget_usd: float
    monthly_budget_usd: float

    @classmethod
    def load(cls, path: Path | None = None) -> Settings:
        load_dotenv(PROJECT_ROOT / ".env")
        config_path = path or (PROJECT_ROOT / "config" / "settings.yaml")
        raw = yaml.safe_load(config_path.read_text()) or {}

        prices = raw.get("prices") or {}
        charts = (raw.get("report") or {}).get("charts") or {}
        llm = raw.get("llm") or {}
        roles = {
            name: RoleConfig(provider=str(cfg["provider"]), model=str(cfg["model"]))
            for name, cfg in (llm.get("roles") or {}).items()
        }
        db_value = os.environ.get("STOCK_AGENT_DB") or (raw.get("database") or {}).get(
            "path", "data/stock_agent.db"
        )
        database_path = Path(db_value)
        if not database_path.is_absolute():
            database_path = PROJECT_ROOT / database_path

        return cls(
            root=PROJECT_ROOT,
            universes=list(raw.get("universes") or ["sp500"]),
            price_source=str((raw.get("sources") or {}).get("prices") or "yfinance"),
            database_path=database_path,
            history_years=int(prices.get("history_years", 5)),
            benchmarks=list(prices.get("benchmarks") or ["SPY"]),
            batch_size=int(prices.get("batch_size", 25)),
            chart_years=int(charts.get("years", 5)),
            moving_averages=[int(w) for w in charts.get("moving_averages") or [20, 60, 120]],
            show_event_markers=bool(charts.get("show_event_markers", True)),
            show_benchmark_panel=bool(charts.get("show_benchmark_panel", False)),
            llm_roles=roles,
            weekly_budget_usd=float(llm.get("weekly_budget_usd", 10)),
            monthly_budget_usd=float(llm.get("monthly_budget_usd", 40)),
        )
