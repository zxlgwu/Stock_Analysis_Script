import pandas as pd

from stock_agent.analysis.technical import compute_technical


def test_rising_series_is_above_long_averages():
    index = pd.bdate_range("2022-01-03", periods=400)
    series = pd.Series(range(100, 500), index=index, dtype=float)
    signals = compute_technical(series)
    assert signals.above_ma120 is True
    assert signals.above_ma200 is True
    assert signals.ma200_slope is not None and signals.ma200_slope > 0
    assert signals.momentum_3m is not None and signals.momentum_3m > 0
    assert signals.momentum_12m is not None and signals.momentum_12m > 0


def test_falling_series_is_below_long_averages():
    index = pd.bdate_range("2022-01-03", periods=400)
    series = pd.Series(range(500, 100, -1), index=index, dtype=float)
    signals = compute_technical(series)
    assert signals.above_ma120 is False
    assert signals.above_ma200 is False
    assert signals.momentum_6m is not None and signals.momentum_6m < 0


def test_short_history_leaves_long_averages_blank():
    index = pd.bdate_range("2024-01-02", periods=30)
    series = pd.Series(range(30), index=index, dtype=float)
    signals = compute_technical(series)
    assert signals.above_ma120 is None
    assert signals.above_ma200 is None
    assert signals.ma_convergence is None
