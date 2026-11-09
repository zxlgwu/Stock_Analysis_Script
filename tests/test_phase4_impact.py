import json
from dataclasses import replace
from pathlib import Path

from stock_agent.analysis.golden import apply_model, direction_accuracy, load_golden
from stock_agent.analysis.plausibility import supported_impacts
from stock_agent.analysis.guardrails import apply_guardrails
from stock_agent.analysis.materiality import classify_materiality, prompt_version
from stock_agent.analysis.schemas import EventAnalysis, Impact, MaterialityBatch
from stock_agent.core.config import RoleConfig, Settings
from stock_agent.db.repository import Database
from stock_agent.llm.base import LLMResult, Message
from stock_agent.llm.prompts import FILTER_PROMPT_VERSION
from stock_agent.llm.router import Router

_GOLDEN = Path(__file__).parent / "fixtures" / "golden_events.json"


def _impact(**kwargs) -> Impact:
    payload = {
        "ticker": "AAPL",
        "relation": "direct",
        "direction": "positive",
        "affected_revenue_line": "Services",
        "est_revenue_impact_pct": 4,
        "horizon": "long",
        "confidence": 0.8,
        "already_priced_in": "partially",
        "reasoning": "Services guidance moved up.",
        "key_uncertainties": ["renewal rates"],
    }
    payload.update(kwargs)
    return Impact(**payload)


def _analysis(impacts) -> EventAnalysis:
    return EventAnalysis(
        cluster_id="c1",
        event_summary="Guidance",
        event_type="guidance",
        impacts=impacts,
    )


def test_guardrails_clip_magnitude_and_drop_unknown_tickers():
    analysis = _analysis(
        [
            _impact(est_revenue_impact_pct=25, confidence=0.4),
            _impact(ticker="MSFT", est_revenue_impact_pct=25, confidence=0.9),
            _impact(ticker="ZZZZ", est_revenue_impact_pct=2, confidence=0.9),
        ]
    )
    guarded = apply_guardrails(analysis, universe={"AAPL", "MSFT"}, context={"AAPL"})
    assert [item.ticker for item in guarded.impacts] == ["AAPL"]
    assert guarded.impacts[0].est_revenue_impact_pct == 10
    assert guarded.impacts[0].reasoning.startswith("[clipped]")


def test_high_confidence_large_impact_is_kept():
    guarded = apply_guardrails(
        _analysis([_impact(est_revenue_impact_pct=12, confidence=0.8)]),
        universe={"AAPL"},
        context={"AAPL"},
    )
    assert guarded.impacts[0].est_revenue_impact_pct == 12
    assert not guarded.impacts[0].reasoning.startswith("[clipped]")


def test_supplier_in_context_is_kept():
    guarded = apply_guardrails(
        _analysis([_impact(ticker="AVGO", relation="supplier", direction="positive")]),
        universe={"NVDA", "AVGO"},
        context={"NVDA", "AVGO"},
    )
    assert guarded.impacts[0].ticker == "AVGO"


def test_propagation_reaches_industries_and_named_companies():
    from stock_agent.analysis.propagation import resolve_channels
    from stock_agent.analysis.schemas import Channel
    from stock_agent.core.models import Security

    securities = [
        Security("XOM", "NYSE", "ExxonMobil", sector="Energy", industry="Integrated Oil & Gas"),
        Security("CVX", "NYSE", "Chevron Corporation", sector="Energy", industry="Integrated Oil & Gas"),
        Security("DAL", "NYSE", "Delta Air Lines", sector="Industrials", industry="Passenger Airlines"),
        Security("UAL", "NASDAQ", "United Airlines Holdings", sector="Industrials", industry="Passenger Airlines"),
        Security("LUV", "NYSE", "Southwest Airlines", sector="Industrials", industry="Passenger Airlines"),
        Security("KO", "NYSE", "Coca-Cola Company", sector="Consumer Staples", industry="Soft Drinks"),
    ]
    channels = [
        Channel(
            target="ExxonMobil",
            kind="company",
            order=1,
            relation="direct",
            direction="positive",
            mechanism="Higher crude prices lift upstream revenue.",
        ),
        Channel(
            target="Passenger Airlines",
            kind="industry",
            order=3,
            relation="customer",
            direction="negative",
            mechanism="Jet fuel costs rise.",
        ),
        Channel(
            target="integrated oil and gas",
            kind="industry",
            order=2,
            relation="competitor",
            direction="positive",
            mechanism="Peers sell the same crude.",
        ),
        Channel(
            target="Space tourism",
            kind="industry",
            order=3,
            relation="macro_exposure",
            direction="mixed",
            mechanism="No tracked industry.",
        ),
    ]
    liquidity = {"DAL": 3.0, "UAL": 2.0, "LUV": 1.0, "XOM": 5.0, "CVX": 4.0}
    resolved = resolve_channels(channels, securities, liquidity, per_industry=2)
    assert [item.channel.order for item in resolved] == [1, 2, 3]
    assert resolved[0].tickers == ("XOM",)
    assert resolved[1].tickers == ("XOM", "CVX")
    assert resolved[2].tickers == ("DAL", "UAL")


def test_related_industries_keeps_named_and_similar_industries():
    from stock_agent.analysis.propagation import prune_channels, related_industries
    from stock_agent.analysis.schemas import Channel

    industries = [
        "Soft Drinks & Non-alcoholic Beverages",
        "Passenger Airlines",
        "Regional Banks",
        "Food Retail",
        "Aerospace & Defense",
        "Steel",
        "Automobile Manufacturers",
        "Consumer Staples Merchandise Retail",
    ]

    def embed(texts):
        vectors = []
        for text in texts:
            lowered = text.lower()
            if "drink" in lowered or "beverage" in lowered or "gatorade" in lowered:
                vectors.append([1.0] * 120)
            elif "airline" in lowered:
                vectors.append([0.0, 1.0] + [0.0] * 118)
            else:
                vectors.append([0.2] * 120)
        return vectors

    ranked = related_industries(
        "Jetty takes on Gatorade",
        "A new sports drink will be sold in grocery stores.",
        industries,
        embed,
        named_industries=["Soft Drinks & Non-alcoholic Beverages"],
    )
    assert ranked[0] == "Soft Drinks & Non-alcoholic Beverages"
    assert "Passenger Airlines" not in ranked
    kept = prune_channels(
        [
            Channel(
                target="PepsiCo",
                kind="industry",
                order=1,
                relation="direct",
                direction="negative",
                mechanism="Gatorade loses share.",
            ),
            Channel(
                target="Passenger Airlines",
                kind="industry",
                order=2,
                relation="customer",
                direction="negative",
                mechanism="Copied from the old prompt.",
            ),
            Channel(
                target="Boeing",
                kind="company",
                order=1,
                relation="direct",
                direction="negative",
                mechanism="Prompt example.",
            ),
        ],
        "Jetty takes on Gatorade. A new sports drink.",
        ["Soft Drinks & Non-alcoholic Beverages", "Food Retail"],
    )
    assert [item.target for item in kept] == ["PepsiCo"]
    tariff = related_industries(
        "How Democrats will try to end Trump's tariffs",
        "Democrats plan to unwind the tariff regime.",
        industries,
        lambda texts: [[0.0] * 120 for _ in texts],
    )
    assert "Passenger Airlines" not in tariff
    assert "Steel" in tariff
    assert "Automobile Manufacturers" in tariff


def test_implausible_reasoning_is_dropped():
    names = {
        "CRWD": "CrowdStrike",
        "PANW": "Palo Alto Networks",
        "FTNT": "Fortinet",
        "DHI": "D.R. Horton",
        "TMO": "Thermo Fisher Scientific",
        "IBM": "IBM",
        "T": "AT&T",
        "NEE": "NextEra Energy",
        "XOM": "Exxon Mobil",
        "CVX": "Chevron",
    }
    copied = "As a customer of cybersecurity solutions, revenue could fall if protection fails."
    impacts = [
        _impact(ticker="CRWD", direction="negative", est_revenue_impact_pct=-0.2, reasoning=copied),
        _impact(ticker="PANW", direction="negative", est_revenue_impact_pct=-0.2, reasoning=copied),
        _impact(ticker="FTNT", direction="negative", est_revenue_impact_pct=-0.2, reasoning=copied),
        _impact(
            ticker="TMO",
            direction="negative",
            reasoning="The rebrand may shift share towards Thermo Fisher, and revenue for Siemens falls.",
        ),
        _impact(ticker="IBM", direction="negative", reasoning="This is a negative impact on Wipro's revenue."),
        _impact(ticker="T", direction="negative", reasoning="A lower stock price reduces AT&T revenue."),
        _impact(
            ticker="DHI",
            direction="negative",
            reasoning="More house buying increases mortgage demand and will decrease home sales.",
        ),
        _impact(
            ticker="NEE",
            direction="positive",
            reasoning="The climate agenda will increase demand for renewable electricity.",
        ),
        _impact(
            ticker="XOM",
            direction="negative",
            reasoning="The climate agenda will reduce Exxon Mobil revenue from oil sales.",
        ),
        _impact(
            ticker="CVX",
            direction="negative",
            reasoning="Increased scrutiny of fossil fuels is reducing their revenue from oil sales.",
        ),
    ]
    kept = supported_impacts(impacts, "Climate finance is on the COP31 agenda.", names)
    assert [item.ticker for item in kept] == ["NEE", "XOM", "CVX"]
    filing = "8-K - DTE ENERGY CO. Item 7.01: Regulation FD Disclosure. Item 9.01: Financial Statements and Exhibits"
    assert supported_impacts([_impact(reasoning="DTE reported strong revenue growth.")], filing, {"AAPL": "Apple"}) == []


def test_materiality_coerces_unknown_categories_and_records_prompt_version(tmp_path):
    loaded = Settings.load()
    roles = {
        name: RoleConfig("litellm" if role.provider == "cursor" else role.provider, role.model)
        for name, role in loaded.llm_roles.items()
    }
    settings = replace(loaded, root=tmp_path, database_path=tmp_path / "test.db", llm_roles=roles)
    db = Database(settings.database_path)

    class _Model:
        name = "litellm"

        def complete(self, messages, *, model, temperature=0.0, max_tokens=None):
            payload = json.loads(messages[-1].content.split("\n", 1)[1])
            items = [
                {
                    "cluster_id": payload[0]["cluster_id"],
                    "material": True,
                    "category": "not-a-real-category",
                    "reason": "Demand change.",
                }
            ]
            return LLMResult(json.dumps({"items": items}), None, 1, 1, 0.0, model, self.name)

        def embed(self, texts, *, model):
            return []

    router = Router(settings, db, {"litellm": _Model(), "local": _Model()})
    decided = classify_materiality(
        router,
        [
            {"cluster_id": "c1", "title": "Apple guidance", "body": "Services outlook raised."},
            {"cluster_id": "c2", "title": "Ignored", "body": "No output."},
        ],
    )
    by_id = {item.cluster_id: item for item in decided}
    assert by_id["c1"].category == "other"
    assert by_id["c1"].material is True
    assert by_id["c2"].material is False
    assert prompt_version() == FILTER_PROMPT_VERSION
    parsed = MaterialityBatch(items=decided)
    assert parsed.items[0].cluster_id == "c1"
    db.close()


def test_golden_set_direction_accuracy():
    cases = load_golden(_GOLDEN)
    assert len(cases) >= 8

    def oracle(case):
        return case["expected_ticker"], case["expected_direction"]

    def reversed_model(case):
        flipped = {"positive": "negative", "negative": "positive"}
        return case["expected_ticker"], flipped[case["expected_direction"]]

    assert direction_accuracy(apply_model(cases, oracle)) == 1
    assert direction_accuracy(apply_model(cases, reversed_model)) == 0
