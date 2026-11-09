"""Build a company profile from XBRL facts and an optional 10-K extraction."""

from __future__ import annotations

from datetime import date

from stock_agent.core.models import CompanyProfile, Fundamental, Relation
from stock_agent.knowledge.taxonomy import TAXONOMY


def build_profile(
    ticker: str,
    fundamentals: list[Fundamental],
    segments: dict[str, float],
    regions: dict[str, float],
    extraction: dict | None = None,
    *,
    as_of: date | None = None,
    known_tickers: set[str] | None = None,
) -> tuple[CompanyProfile, list[Relation]]:
    extraction = extraction or {}
    sensitivities = [
        factor for factor in extraction.get("sensitivities") or [] if factor in TAXONOMY
    ]
    profile = CompanyProfile(
        ticker=ticker,
        segments=dict(segments),
        regions=dict(regions),
        sensitivities=sensitivities,
        summary=str(extraction.get("summary") or ""),
        as_of=as_of or (fundamentals[-1].period_end if fundamentals else None),
    )
    relations: list[Relation] = []
    known = known_tickers or set()
    for item in extraction.get("relations") or []:
        kind = str(item.get("relation") or "")
        if kind not in {"competitor", "supplier_of", "customer_of", "partner"}:
            continue
        name = str(item.get("name") or item.get("ticker") or "").strip()
        if not name:
            continue
        dst_ticker = str(item["ticker"]).upper() if item.get("ticker") else None
        if dst_ticker and known and dst_ticker not in known:
            dst_ticker = None
        dst_key = dst_ticker or name.lower()
        relations.append(
            Relation(
                src_ticker=ticker,
                dst_key=dst_key,
                dst_ticker=dst_ticker,
                relation=kind,
                evidence=str(item.get("evidence") or ""),
                confidence=float(item.get("confidence") or 0.5),
            )
        )
    return profile, relations
