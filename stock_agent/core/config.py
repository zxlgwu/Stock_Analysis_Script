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
    llm_cache: bool
    news_sources: list[str]
    fundamentals_source: str
    rss_feeds: list[str]
    decay_days: dict[str, int]
    score_weights: dict[str, float]
    top_n: int
    recipients: list[str]
    critical_filings: bool
    max_stories_per_week: int = 40
    fetch_article_text: bool = True

    @classmethod
    def load(cls, path: Path | None = None) -> Settings:
        load_dotenv(PROJECT_ROOT / ".env")
        config_path = path or (PROJECT_ROOT / "config" / "settings.yaml")
        raw = yaml.safe_load(config_path.read_text()) or {}

        prices = raw.get("prices") or {}
        report = raw.get("report") or {}
        charts = report.get("charts") or {}
        llm = raw.get("llm") or {}
        sources = raw.get("sources") or {}
        scoring = raw.get("scoring") or {}
        alerts = raw.get("alerts") or {}
        analysis = raw.get("analysis") or {}
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
            llm_cache=bool(llm.get("cache", True)),
            news_sources=[str(name) for name in sources.get("news") or []],
            fundamentals_source=str(sources.get("fundamentals") or "sec_xbrl"),
            rss_feeds=[str(url) for url in sources.get("rss_feeds") or []],
            decay_days={
                "mid": int((scoring.get("decay_days") or {}).get("mid", 90)),
                "long": int((scoring.get("decay_days") or {}).get("long", 365)),
            },
            score_weights={
                key: float(value)
                for key, value in (
                    scoring.get("weights")
                    or {
                        "news_mid": 0.25,
                        "news_long": 0.25,
                        "quality": 0.20,
                        "value": 0.15,
                        "technical": 0.10,
                        "risk": 0.05,
                    }
                ).items()
            },
            top_n=int(report.get("top_n", 10)),
            recipients=[str(item) for item in report.get("recipients") or []],
            critical_filings=bool(alerts.get("critical_filings", False)),
            max_stories_per_week=int(analysis.get("max_stories_per_week", 40)),
            fetch_article_text=bool(analysis.get("fetch_article_text", True)),
        )
