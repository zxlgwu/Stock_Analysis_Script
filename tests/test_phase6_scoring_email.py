import json
from dataclasses import replace
from datetime import date, datetime, timezone
from stock_agent.core.config import RoleConfig, Settings
from stock_agent.core.models import Fundamental, ScoreRecord, Security
from stock_agent.db.repository import Database
from stock_agent.jobs.weekly import run_weekly
from stock_agent.llm.base import LLMResult
from stock_agent.llm.router import Router
from stock_agent.notify.email_smtp import EmailNotifier, build_message
from stock_agent.processing.normalize import to_stored
from stock_agent.report.email_report import (
    DISCLAIMER,
    AnalyzedStory,
    CompanyEffect,
    EmailReport,
    Highlight,
    render_html,
    subject_line,
)
from stock_agent.scoring.composite import build_scores, composite_score, rank_lists, zscore_within_sector
from stock_agent.scoring.factors import quality_raw, risk_raw, technical_raw, value_raw
from stock_agent.scoring.news_score import aggregate, contribution
from stock_agent.core.models import RawArticle, TechnicalSignals
import math


def _impact(ticker, est, published="2026-11-06T00:00:00"):
    return {
        "ticker": ticker,
        "horizon": "long",
        "direction": "positive",
        "est_pct": est,
        "confidence": 0.8,
        "source": "sec_edgar_8k",
        "relation": "direct",
        "priced_in": "unlikely",
        "published_at": published,
    }


def test_news_contribution_decay_and_sector_zscore():
    fresh = contribution(_impact("AAPL", 5), date(2026, 11, 6), 90)
    assert fresh == 4
    aged = contribution(_impact("AAPL", 5, "2026-08-08T00:00:00"), date(2026, 11, 6), 90)
    assert abs(aged - 4 * math.exp(-1)) < 1e-9
    score, revenue = aggregate([_impact("AAPL", 5), _impact("MSFT", 1)], "AAPL", "long", date(2026, 11, 6), 90)
    assert score == 4
    assert revenue == 5
    z = zscore_within_sector({"AAPL": 0.0, "MSFT": 4.0}, {"AAPL": "Tech", "MSFT": "Tech"})
    assert z["AAPL"] == -1
    assert z["MSFT"] == 1


def test_composite_lists_require_positive_news_and_quality():
    weights = {
        "news_mid": 0.25,
        "news_long": 0.25,
        "quality": 0.20,
        "value": 0.15,
        "technical": 0.10,
        "risk": 0.05,
    }
    assert math.isclose(composite_score(1, 1, 1, 1, 1, 1, weights), 0.9)
    assert quality_raw(
        [
            Fundamental("AAPL", date(2023, 9, 30), 100, 0.4, 0.3, 20, 5, "sec_xbrl"),
            Fundamental("AAPL", date(2024, 9, 28), 110, 0.4, 0.3, 22, 6, "sec_xbrl"),
        ]
    ) is not None
    assert value_raw(10, 20) == 1
    assert technical_raw(TechnicalSignals(True, True, 0.01, 0.1, 0.1, 0.1, 0.02)) == 1
    assert risk_raw(0.8, -1) == 1
    scores = [
        ScoreRecord(date(2026, 11, 6), "AAPL", 1, 1, 0, 4, 0.5, 0, 0, 0, 1.0),
        ScoreRecord(date(2026, 11, 6), "MSFT", 0, -0.2, 0, -1, 0.1, 0, 0, 0, 0.2),
    ]
    lists = rank_lists(
        scores,
        {"AAPL": 0.4, "MSFT": 0.1},
        {"AAPL": "Tech", "MSFT": "Tech"},
        {"AAPL": 2.0},
        weights,
        top_n=5,
    )
    assert [row.ticker for row in lists["long"]] == ["AAPL"]
    assert [row.ticker for row in lists["risk"]] == ["MSFT"]
    built = build_scores(
        ["AAPL", "MSFT"],
        {"AAPL": "Tech", "MSFT": "Tech"},
        [_impact("AAPL", 5), _impact("MSFT", 1)],
        {
            "AAPL": {"quality": 0.2, "value": 0.0, "technical": 1.0, "risk": 0.1},
            "MSFT": {"quality": 0.2, "value": 0.0, "technical": 0.0, "risk": 0.1},
        },
        weights,
        {"mid": 90, "long": 365},
        date(2026, 11, 6),
    )
    assert {row.ticker for row in built} == {"AAPL", "MSFT"}
    assert built[0].net_revenue_long == 5 or built[1].net_revenue_long == 5


def test_email_contains_the_required_sections_and_inline_chart(tmp_path):
    chart = tmp_path / "aapl.png"
    chart.write_bytes(
        b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x02\x00\x00\x00\x90wS\xde"
        b"\x00\x00\x00\x0cIDATx\x9cc\xf8\xcf\xc0\x00\x00\x00\x03\x00\x01\x00\x05\xfe\x02\x00\x00\x00\x00IEND\xaeB`\x82"
    )
    report = EmailReport(
        week_ending=date(2026, 11, 6),
        new_idea_count=1,
        risk_count=1,
        week_in_review=["Apple raised services guidance."],
        long_ideas=[
            Highlight(
                "AAPL",
                "Apple Inc.",
                "long",
                1,
                1.2,
                4.0,
                "Services can compound.",
                "Guidance could be cut.",
                links=[("8-K", "https://www.sec.gov/example")],
                chart_cid="chart-AAPL",
                price_lines=["1-year return +10.0%"],
            )
        ],
        mid_ideas=[],
        changes=["AAPL entered the lists."],
        risks=[],
        track_record=["No completed forward window yet."],
        health=["LLM spend this week $0.20 of $10.00."],
        recipients=["investor@example.com"],
        stories=[
            AnalyzedStory(
                title="Apple raised services guidance.",
                url="https://news.example.com/aapl",
                summary="Services outlook was raised for two years.",
                effects=[
                    CompanyEffect(
                        "AAPL",
                        "Apple Inc.",
                        "direct",
                        "positive",
                        "long",
                        "Services",
                        4.0,
                        0.8,
                        "unlikely",
                        "Higher services guidance raises services revenue over two to five years.",
                    )
                ],
                considered=[("AAPL", "Apple Inc.", "mentioned")],
            )
        ],
        chart_files={"chart-AAPL": chart},
    )
    html = render_html(report)
    assert subject_line(report).startswith("Stock Agent — week ending 2026-11-06")
    for heading in (
        "News analyzed",
        "Week in review",
        "Top long-term ideas",
        "Risk alerts",
        "Track record",
        "Agent health",
    ):
        assert heading in html
    assert "Higher services guidance raises services revenue" in html
    assert "cid:chart-AAPL" in html
    saved = tmp_path / "reports" / "2026-11-06.html"
    saved.parent.mkdir()
    page = render_html(report, html_path=saved)
    assert "cid:chart-AAPL" not in page
    assert 'src="../aapl.png"' in page
    assert DISCLAIMER in html
    assert "https://www.sec.gov/example" in html
    message = build_message(report)
    assert message["Subject"].startswith("Stock Agent")
    types = []
    for part in message.walk():
        types.append(part.get_content_type())
    assert "image/png" in types
    assert "text/html" in types


class _Scripted:
    name = "scripted"

    def complete(self, messages, *, model, temperature=0.0, max_tokens=None):
        task = messages[0].content
        user = messages[-1].content
        if "TASK: materiality" in task:
            payload = json.loads(user.split("\n", 1)[1])
            items = [
                {
                    "cluster_id": row["cluster_id"],
                    "material": True,
                    "category": "guidance",
                    "reason": "Multi-year guidance.",
                }
                for row in payload
            ]
            text = json.dumps({"items": items})
        elif "TASK: propagation" in task:
            headline = user.split("Headline: ", 1)[1].split("\n", 1)[0]
            company = headline.split()[0]
            text = json.dumps(
                {
                    "relevant": True,
                    "event_summary": headline,
                    "channels": [
                        {
                            "target": company,
                            "kind": "company",
                            "order": 1,
                            "relation": "direct",
                            "direction": "positive",
                            "mechanism": f"{company} revenue rises with the new business.",
                        }
                    ],
                }
            )
        elif "TASK: impact" in task:
            data = json.loads(user)
            ticker = data["tickers"][0]
            pct = 6 if ticker == "AAPL" else 1
            impacts = [
                {
                    "ticker": ticker,
                    "relation": "direct",
                    "direction": "positive",
                    "affected_revenue_line": "core",
                    "est_revenue_impact_pct": pct,
                    "horizon": horizon,
                    "confidence": 0.8,
                    "already_priced_in": "unlikely",
                    "reasoning": f"{ticker} demand improves.",
                    "key_uncertainties": ["adoption"],
                }
                for horizon in ("mid", "long")
            ]
            text = json.dumps(
                {
                    "cluster_id": data["cluster_id"],
                    "event_summary": data["title"],
                    "event_type": "guidance",
                    "impacts": impacts,
                }
            )
        elif "TASK: thesis" in task:
            data = json.loads(user)
            text = json.dumps(
                {
                    "ticker": data["ticker"],
                    "thesis": f"{data['ticker']} has a multi-year demand tailwind.",
                    "bear_case": "Growth could stall.",
                    "risks": ["competition"],
                    "invalidation": "Guidance is cut.",
                }
            )
        else:
            raise AssertionError(task)
        return LLMResult(text, None, 10, 20, 0.01, model, self.name)

    def embed(self, texts, *, model):
        vectors = []
        for index, _text in enumerate(texts):
            vector = [0.0, 0.0]
            vector[index % 2] = 1.0
            vectors.append(vector)
        return vectors


def _seed(db):
    day = date(2026, 11, 6)
    db.sync_universe(
        "sp500",
        [
            Security("AAPL", "NASDAQ", "Apple Inc.", sector="Information Technology"),
            Security("MSFT", "NASDAQ", "Microsoft Corporation", sector="Information Technology"),
        ],
        day,
    )
    now = datetime(2026, 11, 6, tzinfo=timezone.utc)
    articles = [
        to_stored(
            RawArticle("finnhub", "https://news.example.com/aapl", "Apple Inc. raises services guidance", "Outlook raised for two years.", now),
            now,
        ),
        to_stored(
            RawArticle("rss", "https://news.example.com/msft", "Microsoft Corporation wins a cloud contract", "A multi-year contract.", now),
            now,
        ),
    ]
    db.upsert_articles(articles)
    for ticker in ("AAPL", "MSFT"):
        db.upsert_fundamentals(
            [
                Fundamental(ticker, date(2023, 9, 30), 100, 0.4, 0.3, 20, 5, "sec_xbrl"),
                Fundamental(ticker, date(2024, 9, 28), 110, 0.4, 0.3, 22, 6, "sec_xbrl"),
            ]
        )


def test_weekly_dry_run_is_idempotent(tmp_path):
    loaded = Settings.load()
    roles = {
        name: RoleConfig("litellm" if role.provider == "cursor" else role.provider, role.model)
        for name, role in loaded.llm_roles.items()
    }
    settings = replace(
        loaded,
        root=tmp_path,
        database_path=tmp_path / "test.db",
        llm_roles=roles,
        recipients=["investor@example.com"],
        top_n=5,
    )
    db = Database(settings.database_path)
    _seed(db)
    db.close()
    scripted = _Scripted()
    sent = []

    class _Client:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def send_message(self, message):
            sent.append(message)

    def run_once():
        with Database(settings.database_path) as database:
            router = Router(settings, database, {"litellm": scripted, "local": scripted})
            return run_weekly(
                settings,
                as_of=date(2026, 11, 6),
                router=router,
                notifier=EmailNotifier(smtp_factory=lambda: _Client()),
                render_charts=False,
                text_fetcher=lambda url: "",
            )

    first = run_once()
    with Database(settings.database_path) as database:
        calls_after_first = len(database.llm_calls())
        assert database.conn.execute("SELECT COUNT(*) AS n FROM impacts").fetchone()["n"] == 4
        versions = {
            row["prompt_version"]
            for row in database.conn.execute("SELECT prompt_version FROM materiality")
        }
        assert versions == {"filter-v2"}
    second = run_once()
    with Database(settings.database_path) as database:
        assert len(database.llm_calls()) == calls_after_first
    assert first["impacts"] == 4
    assert first["email_status"] == "sent"
    assert second["impacts"] == 0
    assert sent
    html = (tmp_path / "output" / "reports" / "2026-11-06.html").read_text()
    assert "AAPL has a multi-year demand tailwind." in html
    assert "MSFT has a multi-year demand tailwind." in html
    assert "How the effect spreads" in html
    assert "Apple revenue rises with the new business." in html
    assert DISCLAIMER in html


def test_weekly_skips_thesis_when_budget_is_spent(tmp_path):
    loaded = Settings.load()
    roles = {
        name: RoleConfig("litellm" if role.provider == "cursor" else role.provider, "test-model")
        for name, role in loaded.llm_roles.items()
    }
    settings = replace(
        loaded,
        root=tmp_path,
        database_path=tmp_path / "test.db",
        weekly_budget_usd=0,
        monthly_budget_usd=0,
        llm_roles=roles,
        recipients=["you@example.com"],
        fetch_article_text=False,
    )
    with Database(settings.database_path) as db:
        db.sync_universe(
            "sp500",
            [Security("AAPL", "NASDAQ", "Apple Inc.", sector="Tech")],
            date(2026, 11, 6),
        )
        now = datetime(2026, 11, 6, tzinfo=timezone.utc)
        article = to_stored(
            RawArticle(
                "rss",
                "https://news.example.com/aapl",
                "Apple Inc. raises services guidance",
                "Services outlook was raised.",
                now,
            ),
            now,
        )
        db.upsert_articles([article])
        db.upsert_cluster("cluster-aapl", article.id, now, 1, dropped=False)
        db.assign_cluster([article.id], "cluster-aapl")
        db.save_materiality("cluster-aapl", True, "guidance", "Guidance can change revenue.", "test-model", "filter-v2")
        db.save_impacts(
            [
                (
                    "cluster-aapl",
                    "AAPL",
                    "direct",
                    "positive",
                    "Services",
                    2.0,
                    "mid",
                    0.8,
                    "unlikely",
                    "Apple services revenue rises because guidance was raised.",
                    "test-model",
                    "impact-v2",
                    now.isoformat(),
                )
            ]
        )
    summary = run_weekly(settings, as_of=date(2026, 11, 6), render_charts=False)
    html = (tmp_path / "output" / "reports" / "2026-11-06.html").read_text()
    assert "Thesis skipped: weekly LLM budget reached." in html
    assert summary["email_status"] == "not_configured"


def test_sp500_only_judgments_return_to_the_news_queue(tmp_path):
    from stock_agent.jobs.weekly import _reopen_narrow_company_pass

    db = Database(tmp_path / "test.db")
    old_reason = (
        "Screened out before analysis: no tracked company, industry, or macro force, "
        "or lower priority this week."
    )
    db.conn.execute(
        "INSERT INTO materiality VALUES ('old-screen', 0, 'other', ?, '', 'filter-v2')",
        (old_reason,),
    )
    db.conn.execute(
        """
        INSERT INTO impacts VALUES (
            'old-hit', 'AAPL', 'direct', 'positive', 'Sales', 1, 'long', 0.5, 'no',
            'because', 'ollama/qwen2.5:3b', 'impact-v3', '2026-11-09T03:00:00+00:00'
        )
        """
    )
    db.conn.execute(
        """
        INSERT INTO materiality VALUES (
            'old-hit', 1, 'other', 'Selected for news analysis.', '', 'filter-v2'
        )
        """
    )
    db.conn.execute(
        """
        INSERT INTO impacts VALUES (
            'kept', 'MSFT', 'direct', 'positive', 'Cloud', 1, 'long', 0.5, 'no',
            'because', 'grok-4.7', 'impact-v3', '2026-11-09T07:00:00+00:00'
        )
        """
    )
    db.conn.execute(
        "INSERT INTO recommendations VALUES ('2026-11-06', 'AAPL', 'long', 1, 'old thesis', '')"
    )
    db.conn.commit()
    _reopen_narrow_company_pass(db)
    _reopen_narrow_company_pass(db)
    materiality = {row["cluster_id"] for row in db.conn.execute("SELECT cluster_id FROM materiality")}
    impacts = {row["cluster_id"] for row in db.conn.execute("SELECT cluster_id FROM impacts")}
    assert materiality == set()
    assert impacts == {"kept"}
    assert db.conn.execute("SELECT COUNT(*) AS n FROM recommendations").fetchone()["n"] == 0
    db.close()
