"""Fundamentals, valuation, technical timing, and risk. Each raw score is about -1 to 1 or 0 to 1."""

from __future__ import annotations

from stock_agent.core.models import Fundamental, TechnicalSignals


def _clip(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def quality_raw(rows: list[Fundamental]) -> float | None:
    usable = sorted((row for row in rows if row.revenue), key=lambda row: row.period_end)
    if len(usable) < 2:
        return None
    prior, latest = usable[-2], usable[-1]
    growth = latest.revenue / prior.revenue - 1.0
    operating = latest.op_margin or 0.0
    fcf_margin = 0.0 if not latest.revenue else (latest.fcf or 0.0) / latest.revenue
    return (
        _clip(growth, -1.0, 1.0) * 0.5
        + _clip(operating, -1.0, 1.0) * 0.3
        + _clip(fcf_margin, -1.0, 1.0) * 0.2
    )


def value_raw(pe: float | None, sector_median_pe: float | None) -> float | None:
    """Higher when the stock is cheaper than its sector median P/E."""
    if pe is None or pe <= 0 or sector_median_pe is None or sector_median_pe <= 0:
        return None
    return _clip(sector_median_pe / pe - 1.0, -1.0, 1.0)


def technical_raw(signals: TechnicalSignals) -> float:
    parts: list[float] = []
    if signals.above_ma120 is not None:
        parts.append(1.0 if signals.above_ma120 else 0.0)
    if signals.above_ma200 is not None:
        parts.append(1.0 if signals.above_ma200 else 0.0)
    if signals.momentum_6m is not None:
        parts.append(1.0 if signals.momentum_6m > 0 else 0.0)
    if signals.ma200_slope is not None:
        parts.append(1.0 if signals.ma200_slope > 0 else 0.0)
    if not parts:
        return 0.0
    return sum(parts) / len(parts)


def risk_raw(vol_full: float | None, max_drawdown: float | None) -> float:
    volatility = 0.0 if vol_full is None else min(abs(vol_full) / 0.8, 1.0)
    drawdown = 0.0 if max_drawdown is None else min(abs(max_drawdown), 1.0)
    return 0.5 * volatility + 0.5 * drawdown
