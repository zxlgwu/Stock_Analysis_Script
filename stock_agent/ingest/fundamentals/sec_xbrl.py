"""Parse SEC companyfacts JSON into annual fundamentals, segments, and regions."""

from __future__ import annotations

import os
from datetime import date

import requests

from stock_agent.core.models import Fundamental

_REVENUE = ("Revenues", "RevenueFromContractWithCustomerExcludingAssessedTax", "SalesRevenueNet")
_GROSS = ("GrossProfit",)
_OPERATING = ("OperatingIncomeLoss",)
_CASH = ("NetCashProvidedByUsedInOperatingActivities",)
_EPS = ("EarningsPerShareDiluted",)
_FORMS = {"10-K", "10-Q", "20-F", "40-F"}


def fetch_companyfacts(cik: str, session: requests.Session | None = None) -> dict:
    padded = str(cik).zfill(10)
    url = f"https://data.sec.gov/api/xbrl/companyfacts/CIK{padded}.json"
    client = session or requests
    response = client.get(
        url,
        headers={"User-Agent": os.environ.get("SEC_USER_AGENT") or "stock-agent/0.1 (research; local)"},
        timeout=30,
    )
    response.raise_for_status()
    return response.json()


def parse_companyfacts(payload: dict, ticker: str) -> tuple[list[Fundamental], dict[str, float], dict[str, float]]:
    facts = (payload.get("facts") or {}).get("us-gaap") or {}
    annual = _annual_points(facts, _REVENUE)
    gross = _annual_points(facts, _GROSS)
    operating = _annual_points(facts, _OPERATING)
    cash = _annual_points(facts, _CASH)
    eps = _annual_points(facts, _EPS, units=("USD/shares", "USD"))
    segments, regions = _segments_and_regions(facts)
    rows: list[Fundamental] = []
    for period_end, revenue in annual.items():
        gross_profit = gross.get(period_end)
        operating_income = operating.get(period_end)
        rows.append(
            Fundamental(
                ticker=ticker,
                period_end=date.fromisoformat(period_end),
                revenue=revenue,
                gross_margin=None if not revenue or gross_profit is None else gross_profit / revenue,
                op_margin=None if not revenue or operating_income is None else operating_income / revenue,
                fcf=cash.get(period_end),
                eps=eps.get(period_end),
                source="sec_xbrl",
                filed_at=None,
            )
        )
    rows.sort(key=lambda row: row.period_end)
    return rows, segments, regions


def _annual_points(facts: dict, names: tuple[str, ...], units: tuple[str, ...] = ("USD",)) -> dict[str, float]:
    points: dict[str, float] = {}
    for name in names:
        unit_map = (facts.get(name) or {}).get("units") or {}
        entries = []
        for unit in units:
            entries.extend(unit_map.get(unit) or [])
        for entry in entries:
            if entry.get("fp") != "FY" or entry.get("form") not in _FORMS:
                continue
            if entry.get("segment"):
                continue
            end = entry.get("end")
            if end and entry.get("val") is not None:
                points[end] = float(entry["val"])
        if points:
            break
    return points


def _segments_and_regions(facts: dict) -> tuple[dict[str, float], dict[str, float]]:
    segments: dict[str, float] = {}
    regions: dict[str, float] = {}
    for fact in facts.values():
        for entries in (fact.get("units") or {}).values():
            for entry in entries:
                segment = entry.get("segment") or {}
                if not segment or entry.get("fp") != "FY" or entry.get("val") is None:
                    continue
                label = str(segment.get("value") or "").split(":")[-1]
                label = label.replace("Member", "")
                dimension = str(segment.get("dimension") or "")
                target = regions if "Geograph" in dimension else segments
                target[label] = float(entry["val"])
    return segments, regions
