"""Shared data types for stock-agent."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date


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
