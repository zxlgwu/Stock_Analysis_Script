from datetime import date
from pathlib import Path

import pandas as pd
import pytest

from stock_agent.analysis.price_stats import (
    cagr,
    compute_price_stats,
    drawdown,
    friday_on_or_before,
    ma_convergence,
    period_return,
)

FIXTURES = Path(__file__).parent / "fixtures"


def _series(values: list[float], start: str = "2020-01-02") -> pd.Series:
    index = pd.bdate_range(start, periods=len(values))
    return pd.Series(values, index=index, dtype=float)


def test_one_year_return_uses_calendar_lookback():
    index = pd.bdate_range("2023-01-02", "2024-12-31")
    series = pd.Series(100.0, index=index)
    series.iloc[-1] = 180.0
    result = period_return(series, series.index[-1], years=1)
    assert result == pytest.approx(0.80)


def test_max_drawdown_peak_and_trough():
    series = _series([100, 150, 120, 75, 90, 90])
    depth, peak, trough, current = drawdown(series, series.index[-1], years=5)
    assert depth == pytest.approx(75 / 150 - 1)
    assert peak == series.index[1].date()
    assert trough == series.index[3].date()
    assert current == pytest.approx(90 / 150 - 1)


def test_flat_prices_have_zero_convergence_and_drawdown():
    series = _series([50.0] * 300)
    assert ma_convergence(series) == pytest.approx(0.0, abs=1e-12)
    depth, _, _, current = drawdown(series, series.index[-1], years=5)
    assert depth == pytest.approx(0.0)
    assert current == pytest.approx(0.0)


def test_cagr_doubles_over_about_four_years():
    index = pd.bdate_range("2020-01-02", "2024-01-02")
    series = pd.Series(100.0, index=index)
    series.iloc[0] = 100.0
    series.iloc[-1] = 200.0
    result = cagr(series, series.index[-1], years=5)
    elapsed = (series.index[-1] - series.index[0]).days
    expected = 2 ** (365.25 / elapsed) - 1
    assert result == pytest.approx(expected)


def test_relative_return_against_spy():
    index = pd.bdate_range("2022-01-03", "2024-12-31")
    stock = pd.Series(100.0, index=index)
    stock.iloc[-1] = 150.0
    spy = pd.Series(100.0, index=index)
    spy.iloc[-1] = 120.0
    frame = pd.DataFrame({"date": stock.index, "adj_close": stock.values})
    stats = compute_price_stats(frame, ticker="AAA", spy=spy, as_of=index[-1].date(), lookback_years=5)
    assert stats is not None
    assert stats.ret_1y == pytest.approx(0.50)
    assert stats.rel_spy_1y == pytest.approx(0.30)
    assert stats.week_ending == friday_on_or_before(index[-1].date())


def test_friday_on_or_before():
    assert friday_on_or_before(date(2024, 12, 6)) == date(2024, 12, 6)
    assert friday_on_or_before(date(2024, 12, 8)) == date(2024, 12, 6)
