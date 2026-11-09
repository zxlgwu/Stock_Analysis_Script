"""Shared data types for stock-agent."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime


@dataclass(frozen=True)
class Security:
    ticker: str
    exchange: str
    name: str
    cik: str | None = None
    sector: str | None = None
    industry: str | None = None


@dataclass(frozen=True)
class PriceStats:
    ticker: str
    week_ending: date
    ret_1y: float | None
    ret_3y: float | None
    ret_5y: float | None
    cagr: float | None
    rel_spy_1y: float | None
    rel_spy_3y: float | None
    rel_spy_5y: float | None
    rel_sector_1y: float | None
    rel_sector_3y: float | None
    rel_sector_5y: float | None
    max_drawdown: float | None
    max_dd_start: date | None
    max_dd_end: date | None
    current_drawdown: float | None
    vol_1y: float | None
    vol_full: float | None
    ma_convergence: float | None


@dataclass(frozen=True)
class TechnicalSignals:
    above_ma120: bool | None
    above_ma200: bool | None
    ma200_slope: float | None
    momentum_3m: float | None
    momentum_6m: float | None
    momentum_12m: float | None
    ma_convergence: float | None


@dataclass(frozen=True)
class RawArticle:
    source: str
    url: str
    title: str
    body: str
    published_at: datetime
    tickers: tuple[str, ...] = ()


@dataclass(frozen=True)
class StoredArticle:
    id: str
    source: str
    url: str
    title: str
    body: str
    published_at: datetime
    fetched_at: datetime
    content_hash: str
    cluster_id: str | None = None


@dataclass(frozen=True)
class Relation:
    src_ticker: str
    dst_key: str
    relation: str
    evidence: str = ""
    confidence: float = 0.5
    dst_ticker: str | None = None


@dataclass(frozen=True)
class Fundamental:
    ticker: str
    period_end: date
    revenue: float | None
    gross_margin: float | None
    op_margin: float | None
    fcf: float | None
    eps: float | None
    source: str
    filed_at: date | None = None


@dataclass(frozen=True)
class CompanyProfile:
    ticker: str
    segments: dict[str, float] = field(default_factory=dict)
    regions: dict[str, float] = field(default_factory=dict)
    sensitivities: list[str] = field(default_factory=list)
    summary: str = ""
    as_of: date | None = None


@dataclass(frozen=True)
class ScoreRecord:
    week_ending: date
    ticker: str
    news_mid: float
    news_long: float
    net_revenue_mid: float
    net_revenue_long: float
    quality: float
    value: float
    technical: float
    risk: float
    composite: float
