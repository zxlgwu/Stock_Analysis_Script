import math
from datetime import date

from stock_agent.db.repository import Database
from stock_agent.evaluation.metrics import calibration, quintile_spread, rank_ic
from stock_agent.evaluation.outcomes import direction_hit
from stock_agent.evaluation.paper_portfolio import period_return


def test_direction_hit_compares_with_the_prior_trend():
    assert direction_hit("positive", 0.10, 0.20) is True
    assert direction_hit("positive", 0.10, 0.00) is False
    assert direction_hit("negative", 0.10, 0.00) is True
    assert direction_hit("neutral", 0.10, 0.20) is None


def test_rank_ic_quintile_spread_and_paper_portfolio():
    scores = {"A": 1, "B": 2, "C": 3, "D": 4, "E": 5}
    returns = {"A": 0.01, "B": 0.02, "C": 0.03, "D": 0.04, "E": 0.10}
    assert math.isclose(rank_ic(scores, returns), 1)
    assert rank_ic({"A": 1}, {"A": 0.1}) is None
    assert math.isclose(quintile_spread(scores, returns), 0.09)
    assert math.isclose(period_return(scores, returns, top_n=1, cost=0.001), 0.099)


def test_higher_confidence_bucket_is_measured_separately():
    rows = [(0.5, True), (0.5, False), (0.85, True), (0.9, True)]
    measured = calibration(rows)
    assert measured["0.5"] == 0.5
    assert measured["0.8"] == 1


def test_metrics_are_stored_for_the_week(tmp_path):
    db = Database(tmp_path / "test.db")
    db.record_metric(date(2026, 11, 6), "rank_ic", "forward", 0.2)
    db.record_metric(date(2026, 11, 6), "quintile_spread", "forward", 0.05)
    stored = {row["metric"]: row["value"] for row in db.metrics_for(date(2026, 11, 6))}
    assert stored == {"quintile_spread": 0.05, "rank_ic": 0.2}
    db.close()
