"""Trend and momentum signals computed from daily prices."""

from __future__ import annotations

import pandas as pd

from stock_agent.analysis.price_stats import ma_convergence, period_return
from stock_agent.core.models import TechnicalSignals


def compute_technical(prices: pd.Series) -> TechnicalSignals:
    """`prices` is an adjusted-close series indexed by date."""
    series = prices.dropna().sort_index().astype(float)
    if series.empty:
        return TechnicalSignals(None, None, None, None, None, None, None)
    as_of = series.index[-1]
    last = float(series.iloc[-1])

    def average(window: int) -> float | None:
        if len(series) < window:
            return None
        return float(series.rolling(window).mean().iloc[-1])

    ma120 = average(120)
    ma200 = average(200)
    slope = None
    if len(series) >= 221:
        long_average = series.rolling(200).mean().dropna()
        prior = float(long_average.iloc[-21])
        if prior:
            slope = float(long_average.iloc[-1]) / prior - 1.0

    return TechnicalSignals(
        above_ma120=None if ma120 is None else last > ma120,
        above_ma200=None if ma200 is None else last > ma200,
        ma200_slope=slope,
        momentum_3m=period_return(series, as_of, months=3),
        momentum_6m=period_return(series, as_of, months=6),
        momentum_12m=period_return(series, as_of, months=12),
        ma_convergence=ma_convergence(series),
    )
