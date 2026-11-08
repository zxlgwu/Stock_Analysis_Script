"""Multi-year price charts with moving averages, as PNG files and one PDF."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.backends.backend_pdf import PdfPages
import pandas as pd

from stock_agent.analysis.price_stats import close_series

_MA_COLORS = {20: "green", 60: "orange", 120: "red", 200: "purple"}


@dataclass
class ChartSpec:
    ticker: str
    name: str
    prices: pd.DataFrame
    market_cap: float | None = None
    events: list[date] | None = None
    benchmark: pd.Series | None = None


def render_price_charts(
    charts: list[ChartSpec],
    *,
    dest_dir: Path,
    years: int = 5,
    moving_averages: list[int] | None = None,
    show_event_markers: bool = True,
    show_benchmark_panel: bool = False,
) -> tuple[list[Path], Path]:
    dest_dir.mkdir(parents=True, exist_ok=True)
    windows = moving_averages or [20, 60, 120]
    pngs: list[Path] = []
    pdf_path = dest_dir / "price_charts.pdf"
    with PdfPages(pdf_path) as pdf:
        for spec in charts:
            figure = _draw(spec, years=years, windows=windows, show_event_markers=show_event_markers, show_benchmark_panel=show_benchmark_panel)
            png = dest_dir / f"{spec.ticker.replace('.', '_')}.png"
            figure.savefig(png, dpi=110, bbox_inches="tight")
            pdf.savefig(figure, bbox_inches="tight")
            plt.close(figure)
            pngs.append(png)
    return pngs, pdf_path


def _draw(spec: ChartSpec, *, years: int, windows: list[int], show_event_markers: bool, show_benchmark_panel: bool):
    series = close_series(spec.prices)
    if series.empty:
        raise ValueError(f"No prices to chart for {spec.ticker}")
    averages = {window: series.rolling(window).mean() for window in windows}
    start = series.index[-1] - pd.DateOffset(years=years)
    view = series.loc[start:]
    averages = {window: values.loc[start:] for window, values in averages.items()}

    if show_benchmark_panel and spec.benchmark is not None:
        figure, (ax, bench_ax) = plt.subplots(
            2, 1, figsize=(10, 7.5), sharex=True, gridspec_kw={"height_ratios": [3, 1]}
        )
    else:
        figure, ax = plt.subplots(figsize=(10, 6))
        bench_ax = None

    ax.plot(view.index, view.values, label=f"{spec.ticker} Close", color="blue")
    for window, values in averages.items():
        color = _MA_COLORS.get(window, "gray")
        ax.plot(values.index, values.values, label=f"{window}-Day MA", color=color, linestyle="--")

    if show_event_markers and spec.events:
        labeled = False
        for event in spec.events:
            stamp = pd.Timestamp(event)
            if stamp < view.index[0] or stamp > view.index[-1]:
                continue
            ax.axvline(stamp, color="gray", alpha=0.45, linewidth=1, label=None if labeled else "News event")
            labeled = True

    year_label = f"{years} Year" if years == 1 else f"{years} Years"
    cap = ""
    if spec.market_cap:
        cap = f"\nMarket Cap: ${spec.market_cap / 1e9:,.0f}B"
    ax.set_title(f"{spec.name} ({spec.ticker}) Stock Price ({year_label}){cap}")
    ax.set_ylabel("Price (USD)")
    ax.grid(True)
    ax.legend()

    if bench_ax is not None and spec.benchmark is not None:
        bench = spec.benchmark.dropna().sort_index()
        bench.index = pd.DatetimeIndex(bench.index)
        if bench.index.tz is not None:
            bench.index = bench.index.tz_convert("America/New_York").tz_localize(None)
        aligned = pd.concat(
            [view.rename("stock"), bench.rename("benchmark")],
            axis=1,
        ).dropna()
        aligned = aligned.loc[start:]
        if not aligned.empty and float(aligned["stock"].iloc[0]) and float(aligned["benchmark"].iloc[0]):
            stock_rebased = aligned["stock"] / float(aligned["stock"].iloc[0]) * 100
            bench_rebased = aligned["benchmark"] / float(aligned["benchmark"].iloc[0]) * 100
            bench_ax.plot(stock_rebased.index, stock_rebased.values, label=spec.ticker, color="blue")
            bench_ax.plot(bench_rebased.index, bench_rebased.values, label="SPY", color="gray")
            bench_ax.set_ylabel("Rebased")
            bench_ax.grid(True)
            bench_ax.legend()
    ax.set_xlabel("Date")
    figure.tight_layout()
    return figure
