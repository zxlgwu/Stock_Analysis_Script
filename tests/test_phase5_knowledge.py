from datetime import date

from stock_agent.core.models import CompanyProfile, Security
from stock_agent.db.repository import Database
from stock_agent.ingest.fundamentals.sec_xbrl import parse_companyfacts
from stock_agent.knowledge.profile_builder import build_profile
from stock_agent.knowledge.taxonomy import TAXONOMY, tag_factors
from stock_agent.processing.entity_linking import link_entities

_FACTS = {
    "facts": {
        "us-gaap": {
            "Revenues": {
                "units": {
                    "USD": [
                        {"end": "2023-09-30", "val": 100, "fp": "FY", "form": "10-K"},
                        {"end": "2024-09-28", "val": 120, "fp": "FY", "form": "10-K"},
                    ]
                }
            },
            "GrossProfit": {"units": {"USD": [{"end": "2024-09-28", "val": 48, "fp": "FY", "form": "10-K"}]}},
            "OperatingIncomeLoss": {
                "units": {"USD": [{"end": "2024-09-28", "val": 30, "fp": "FY", "form": "10-K"}]}
            },
            "NetCashProvidedByUsedInOperatingActivities": {
                "units": {"USD": [{"end": "2024-09-28", "val": 25, "fp": "FY", "form": "10-K"}]}
            },
            "EarningsPerShareDiluted": {
                "units": {"USD/shares": [{"end": "2024-09-28", "val": 6.5, "fp": "FY", "form": "10-K"}]}
            },
            "RevenueFromContractWithCustomerExcludingAssessedTax": {
                "units": {
                    "USD": [
                        {
                            "end": "2024-09-28",
                            "val": 70,
                            "fp": "FY",
                            "form": "10-K",
                            "segment": {"dimension": "srt:ProductOrServiceAxis", "value": "us-gaap:ProductMember"},
                        },
                        {
                            "end": "2024-09-28",
                            "val": 40,
                            "fp": "FY",
                            "form": "10-K",
                            "segment": {
                                "dimension": "srt:StatementGeographicalAxis",
                                "value": "us-gaap:NonUsMember",
                            },
                        },
                    ]
                }
            },
        }
    }
}


def test_xbrl_parser_reads_growth_segments_and_regions():
    rows, segments, regions = parse_companyfacts(_FACTS, "AAPL")
    assert [row.period_end.isoformat() for row in rows] == ["2023-09-30", "2024-09-28"]
    assert rows[-1].revenue == 120
    assert rows[-1].gross_margin == 0.4
    assert rows[-1].op_margin == 0.25
    assert rows[-1].fcf == 25
    assert rows[-1].eps == 6.5
    assert segments["Product"] == 70
    assert regions["NonUs"] == 40


def test_profile_links_a_supplier_and_keeps_known_sensitivities(tmp_path):
    rows, segments, regions = parse_companyfacts(_FACTS, "NVDA")
    extraction = {
        "summary": "Designs accelerated computing chips.",
        "sensitivities": ["ai_capex", "not_a_factor"],
        "relations": [
            {
                "relation": "supplier_of",
                "ticker": "AVGO",
                "name": "Broadcom",
                "evidence": "10-K supplier list",
                "confidence": 0.6,
            }
        ],
    }
    profile, relations = build_profile(
        "NVDA",
        rows,
        segments,
        regions,
        extraction,
        as_of=date(2024, 11, 1),
        known_tickers={"NVDA", "AVGO"},
    )
    assert profile.sensitivities == ["ai_capex"]
    assert relations[0].dst_ticker == "AVGO"
    assert relations[0].relation == "supplier_of"
    assert len(TAXONOMY) >= 30

    db = Database(tmp_path / "test.db")
    db.sync_universe(
        "sp500",
        [Security("NVDA", "NASDAQ", "NVIDIA Corporation"), Security("AVGO", "NASDAQ", "Broadcom Inc.")],
        date(2024, 11, 1),
    )
    db.upsert_profile(profile)
    db.replace_relations("NVDA", relations)
    assert db.get_profile("NVDA").summary.startswith("Designs")
    links = link_entities(
        "NVIDIA Corporation raised its data-center outlook.",
        db.active_members("sp500"),
        db.all_relations(),
        [profile],
    )
    assert ("NVDA", "mentioned") in links
    assert ("AVGO", "expanded") in links
    db.close()


def test_macro_factor_routes_without_a_per_company_call():
    assert tag_factors("A new tariff on Chinese components") == ["china_exposure", "tariffs"]
    nvda = Security("NVDA", "NASDAQ", "NVIDIA Corporation")
    profile = CompanyProfile(ticker="NVDA", sensitivities=["tariffs"])
    links = link_entities("A new tariff was announced.", [nvda], [], [profile])
    assert links == [("NVDA", "expanded")]
