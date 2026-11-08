"""Daily prices from Yahoo Finance via yfinance."""

from __future__ import annotations

from datetime import date, timedelta

import pandas as pd
import yfinance as yf

from stock_agent.core.models import Security
from stock_agent.ingest.prices.symbols import to_yfinance_symbol

_COLUMNS = {
    "Open": "open",
    "High": "high",
    "Low": "low",
    "Close": "close",
    "Adj Close": "adj_close",
    "Volume": "volume",
}


class YFinancePriceSource:
    name = "yfinance"

    def __init__(self, batch_size: int = 25):
        self.batch_size = batch_size

    def history(self, securities: list[Security], start: date, end: date) -> pd.DataFrame:
        """Return daily bars. `end` is inclusive."""
        if not securities or start > end:
            return _empty()
        by_symbol = {to_yfinance_symbol(sec.ticker): sec.ticker for sec in securities}
        frames: list[pd.DataFrame] = []
        symbols = list(by_symbol)
        # yfinance treats `end` as exclusive.
        exclusive_end = end + timedelta(days=1)
        for offset in range(0, len(symbols), self.batch_size):
            batch = symbols[offset : offset + self.batch_size]
            downloaded = yf.download(
                batch,
                start=start.isoformat(),
                end=exclusive_end.isoformat(),
                auto_adjust=False,
                group_by="ticker",
                threads=True,
                progress=False,
            )
            if downloaded is None or downloaded.empty:
                continue
            for symbol in batch:
                frame = _frame_for_symbol(downloaded, symbol, single=len(batch) == 1)
                if frame is None or frame.empty:
                    continue
                normalized = _normalize(frame)
                if normalized.empty:
                    continue
                normalized.insert(0, "ticker", by_symbol[symbol])
                frames.append(normalized)
        if not frames:
            return _empty()
        return pd.concat(frames, ignore_index=True)


def _empty() -> pd.DataFrame:
    return pd.DataFrame(
        columns=["ticker", "date", "open", "high", "low", "close", "adj_close", "volume"]
    )


def _frame_for_symbol(data: pd.DataFrame, symbol: str, *, single: bool) -> pd.DataFrame | None:
    if not isinstance(data.columns, pd.MultiIndex):
        return data
    for level in range(data.columns.nlevels):
        if symbol in set(data.columns.get_level_values(level)):
            return data.xs(symbol, axis=1, level=level)
    if single:
        return data
    return None


def _normalize(frame: pd.DataFrame) -> pd.DataFrame:
    frame = frame.rename(columns=_COLUMNS).copy()
    if "close" not in frame.columns:
        return _empty().drop(columns=["ticker"])
    frame = frame.reset_index()
    date_col = "Date" if "Date" in frame.columns else frame.columns[0]
    frame = frame.rename(columns={date_col: "date"})
    dates = pd.to_datetime(frame["date"])
    if getattr(dates.dt, "tz", None) is not None:
        dates = dates.dt.tz_convert("America/New_York").dt.tz_localize(None)
    frame["date"] = dates
    if "adj_close" not in frame.columns:
        frame["adj_close"] = frame["close"]
    for column in ("open", "high", "low", "close", "adj_close", "volume"):
        if column not in frame.columns:
            frame[column] = pd.NA
    frame = frame.dropna(subset=["close"])
    return frame[["date", "open", "high", "low", "close", "adj_close", "volume"]]
