from datetime import date
from pathlib import Path

import pandas as pd

from stock_agent.core.models import Security
from stock_agent.db.repository import Database
from stock_agent.report.charts import ChartSpec, render_price_charts


def test_universe_sync_keeps_removed_members(tmp_path: Path):
    db = Database(tmp_path / "test.db")
    first = [Security("AAPL", "NASDAQ", "Apple"), Security("MSFT", "NASDAQ", "Microsoft")]
    db.sync_universe("sp500", first, date(2024, 1, 2))
    db.sync_universe("sp500", [first[0]], date(2024, 6, 3))
    active = [sec.ticker for sec in db.active_members("sp500")]
    assert active == ["AAPL"]
    removed = db.conn.execute(
        "SELECT removed_at FROM universe_members WHERE ticker = 'MSFT'"
    ).fetchone()["removed_at"]
    assert removed == "2024-06-03"
    db.close()


def test_chart_pdf_is_written(tmp_path: Path):
    index = pd.bdate_range("2023-01-02", periods=160)
    prices = pd.DataFrame({"date": index, "close": range(100, 260), "adj_close": range(100, 260)})
    pngs, pdf = render_price_charts(
        [ChartSpec(ticker="AAA", name="Acme", prices=prices, market_cap=2.5e9)],
        dest_dir=tmp_path,
        years=1,
        moving_averages=[20, 60],
    )
    assert pngs[0].exists() and pngs[0].stat().st_size > 0
    assert pdf.exists() and pdf.stat().st_size > 0
