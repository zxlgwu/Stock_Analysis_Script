"""Multi-year price statistics from stored daily prices. No network and no LLM."""

from __future__ import annotations

from datetime import date, timedelta

import pandas as pd

from stock_agent.core.models import PriceStats


def friday_on_or_before(day: date) -> date:
    return day - timedelta(days=(day.weekday() - 4) % 7)


def close_series(prices: pd.DataFrame) -> pd.Series:
    """Adjusted close indexed by date. Falls back to close."""
    frame = prices.copy()
    frame["date"] = pd.to_datetime(frame["date"])
    column = "adj_close" if "adj_close" in frame and frame["adj_close"].notna().any() else "close"
    frame = frame.dropna(subset=[column]).sort_values("date")
    frame = frame.drop_duplicates("date", keep="last")
    series = frame.set_index("date")[column].astype(float)
    index = pd.DatetimeIndex(series.index)
    if index.tz is not None:
        index = index.tz_convert("America/New_York").tz_localize(None)
    series.index = index
    return series


def period_return(series: pd.Series, as_of: pd.Timestamp, *, years: int = 0, months: int = 0) -> float | None:
    history = series.loc[:as_of]
    if history.empty:
        return None
    end = float(history.iloc[-1])
    target = as_of - pd.DateOffset(years=years, months=months)
    prior = history.loc[:target]
    if prior.empty or end <= 0:
        return None
    start = float(prior.iloc[-1])
    if start <= 0:
        return None
    return end / start - 1.0


def cagr(series: pd.Series, as_of: pd.Timestamp, years: int) -> float | None:
    history = series.loc[:as_of]
    window = history.loc[as_of - pd.DateOffset(years=years) :]
    if len(window) < 2:
        return None
    start_price = float(window.iloc[0])
    end_price = float(window.iloc[-1])
    elapsed = (window.index[-1] - window.index[0]).days
    if start_price <= 0 or end_price <= 0 or elapsed <= 0:
        return None
    return (end_price / start_price) ** (365.25 / elapsed) - 1.0


def drawdown(series: pd.Series, as_of: pd.Timestamp, years: int) -> tuple[float | None, date | None, date | None, float | None]:
    """Max drawdown (depth, peak date, trough date) and current drawdown over the lookback."""
    history = series.loc[:as_of]
    window = history.loc[as_of - pd.DateOffset(years=years) :]
    if window.empty:
        return None, None, None, None
    running_peak = window.cummax()
    depth = window / running_peak - 1.0
    trough_at = depth.idxmin()
    before = window.loc[:trough_at]
    peak_level = float(before.max())
    peak_at = before[before == peak_level].index[-1]
    current = float(window.iloc[-1]) / float(window.max()) - 1.0
    return float(depth.loc[trough_at]), peak_at.date(), trough_at.date(), current


def annualized_volatility(series: pd.Series) -> float | None:
    returns = series.pct_change().dropna()
    if len(returns) < 2:
        return None
    return float(returns.std() * (252 ** 0.5))


def ma_convergence(series: pd.Series, windows: tuple[int, ...] = (20, 60, 120), lookback: int = 100) -> float | None:
    """Average relative spread of moving averages. Low means the averages have converged."""
    if len(series) < max(windows):
        return None
    averages = pd.concat([series.rolling(window).mean() for window in windows], axis=1)
    tail = averages.dropna().iloc[-lookback:]
    if tail.empty:
        return None
    spread = tail.max(axis=1) - tail.min(axis=1)
    center = tail.mean(axis=1)
    relative = spread / center.replace(0, pd.NA)
    value = relative.dropna()
    if value.empty:
        return None
    return float(value.mean())


def _relative(stock: float | None, benchmark: float | None) -> float | None:
    if stock is None or benchmark is None:
        return None
    return stock - benchmark


def compute_price_stats(
    prices: pd.DataFrame,
    *,
    ticker: str,
    spy: pd.Series | None = None,
    sector_benchmark: pd.Series | None = None,
    as_of: date | None = None,
    lookback_years: int = 5,
) -> PriceStats | None:
    series = close_series(prices)
    if series.empty:
        return None
    as_of_ts = pd.Timestamp(as_of) if as_of else series.index[-1]
    series = series.loc[:as_of_ts]
    if series.empty:
        return None
    as_of_ts = series.index[-1]

    returns = {years: period_return(series, as_of_ts, years=years) for years in (1, 3, 5)}
    spy_returns = {
        years: None if spy is None else period_return(spy, as_of_ts, years=years) for years in (1, 3, 5)
    }
    sector_returns = {
        years: None if sector_benchmark is None else period_return(sector_benchmark, as_of_ts, years=years)
        for years in (1, 3, 5)
    }
    max_dd, peak_on, trough_on, current_dd = drawdown(series, as_of_ts, lookback_years)
    one_year = series.loc[as_of_ts - pd.DateOffset(years=1) :]
    full = series.loc[as_of_ts - pd.DateOffset(years=lookback_years) :]

    return PriceStats(
        ticker=ticker,
        week_ending=friday_on_or_before(as_of_ts.date()),
        ret_1y=returns[1],
        ret_3y=returns[3],
        ret_5y=returns[5],
        cagr=cagr(series, as_of_ts, lookback_years),
        rel_spy_1y=_relative(returns[1], spy_returns[1]),
        rel_spy_3y=_relative(returns[3], spy_returns[3]),
        rel_spy_5y=_relative(returns[5], spy_returns[5]),
        rel_sector_1y=_relative(returns[1], sector_returns[1]),
        rel_sector_3y=_relative(returns[3], sector_returns[3]),
        rel_sector_5y=_relative(returns[5], sector_returns[5]),
        max_drawdown=max_dd,
        max_dd_start=peak_on,
        max_dd_end=trough_on,
        current_drawdown=current_dd,
        vol_1y=annualized_volatility(one_year),
        vol_full=annualized_volatility(full),
        ma_convergence=ma_convergence(series),
    )
