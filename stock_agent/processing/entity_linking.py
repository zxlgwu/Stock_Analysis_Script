"""Map article text to tickers, then expand through the relationship graph."""

from __future__ import annotations

import re

from stock_agent.core.models import CompanyProfile, Relation, Security
from stock_agent.knowledge.exposure import bellwethers_for, factor_tickers, outside_tickers, sectors_for_text
from stock_agent.knowledge.taxonomy import tag_factors

# Single-word names that appear in ordinary headlines and are not a company mention.
_GENERIC_NAMES = {
    "news",
    "general",
    "national",
    "american",
    "united",
    "public",
    "service",
    "services",
    "group",
    "holdings",
    "international",
    "global",
    "capital",
    "energy",
    "health",
    "power",
    "data",
    "bank",
    "fund",
    "federal",
    "state",
    "southern",
    "western",
    "pacific",
    "trust",
    "dollar",
    "first",
    "real",
    "estate",
    "waste",
    "carrier",
    "extra",
    "fifth",
    "third",
    "digital",
    "realty",
}

# Leftover single tokens after stripping Inc/Corp, or first names that are also English words.
_WEAK_SINGLE = {
    "target",
    "block",
    "next",
    "best",
    "advance",
    "center",
    "pool",
    "match",
    "copy",
    "key",
    "field",
    "ball",
    "gap",
    "mosaic",
}
# A first name, or a common word that starts many company names. "under sanctions"
# is not Under Armour, and "European Union" is not the European Equity Fund.
_COMMON_FIRST = {
    "under",
    "union",
    "local",
    "european",
    "alexander",
    "northwestern",
    "american",
    "national",
    "general",
    "first",
    "public",
}
_WEAK_FIRST = {
    "johnson",
    "williams",
    "martin",
    "davis",
    "wilson",
    "anderson",
    "thomas",
    "jackson",
    "harris",
    "clark",
    "lewis",
    "young",
    "allen",
    "king",
    "wright",
    "scott",
    "green",
    "baker",
    "adams",
    "nelson",
    "carter",
    "mitchell",
    "roberts",
    "turner",
    "phillips",
    "campbell",
    "parker",
    "evans",
    "edwards",
    "collins",
    "stewart",
    "morris",
    "murphy",
    "cook",
    "rogers",
    "morgan",
    "peterson",
    "cooper",
    "reed",
    "bailey",
    "bell",
    "howard",
    "ward",
    "cox",
    "richardson",
    "wood",
    "watson",
    "brooks",
    "bennett",
    "gray",
    "james",
    "hunt",
    "kennedy",
}
_TICKER_WORDS = {
    "NOW",
    "ALL",
    "ARE",
    "NEW",
    "OUT",
    "LOW",
    "ONE",
    "BIG",
    "ANY",
    "SEE",
    "HAS",
    "WAS",
    "CAN",
    "ITS",
    "OWN",
    "FOR",
    "SO",
    "ON",
    "IT",
    "BE",
}

_SUFFIX = re.compile(
    r"\b(incorporated|inc|corp|corporation|company|co|ltd|plc|holdings|group|class [a-z]|the)\b\.?",
    re.IGNORECASE,
)


def _name_key(name: str) -> str:
    cleaned = _SUFFIX.sub(" ", name)
    cleaned = re.sub(r"[^a-z0-9 ]", " ", cleaned.lower())
    return re.sub(r"\s+", " ", cleaned).strip()


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9 ]", " ", text.lower())).strip()


def _ticker_in_text(text: str, ticker: str) -> bool:
    # One- and two-letter tickers match only as a parenthetical or a $ symbol.
    # Bare "NI" and "/DE" show up in other companies' names and SEC headers.
    # Common English words that are also tickers (NOW, ALL) need the same bar.
    if len(ticker) <= 2 or ticker in _TICKER_WORDS:
        return re.search(rf"\({re.escape(ticker)}\)|\$({re.escape(ticker)})\b", text) is not None
    # A hyphenated equipment code such as ELOU-AVT-2 is not the ticker AVT.
    for match in re.finditer(rf"(?<![A-Za-z0-9-]){re.escape(ticker)}(?![A-Za-z0-9-])", text):
        prefix = text[max(0, match.start() - 3) : match.start()]
        if re.search(r"[./]\s*$", prefix):
            continue
        return True
    return False


def _cik_tickers(text: str, securities: list[Security]) -> list[str]:
    by_cik: dict[str, list[Security]] = {}
    for security in securities:
        if not security.cik:
            continue
        by_cik.setdefault(security.cik.lstrip("0"), []).append(security)
    found: list[str] = []
    for match in re.finditer(r"\((\d{7,10})\)", text):
        choices = by_cik.get(match.group(1).lstrip("0"), [])
        if not choices:
            continue
        class_a = [security for security in choices if "class a" in security.name.lower()]
        pool = class_a or choices
        ticker = sorted(pool, key=lambda security: security.ticker)[0].ticker
        if ticker not in found:
            found.append(ticker)
    return found


def mentioned_tickers(text: str, securities: list[Security]) -> list[str]:
    found: list[str] = _cik_tickers(text, securities)
    normalized = _normalize(text)
    for security in securities:
        ticker = security.ticker.upper()
        if _ticker_in_text(text, ticker):
            found.append(ticker)
            continue
        original = _normalize(security.name)
        if original and re.search(rf"\b{re.escape(original)}\b", normalized):
            found.append(ticker)
            continue
        key = _name_key(security.name)
        if len(key) < 4 or key in _GENERIC_NAMES:
            continue
        tokens = key.split()
        if len(tokens) == 1 and (key in _WEAK_SINGLE or re.search(rf"\b{re.escape(key)}\s+of\b", normalized)):
            continue
        if re.search(rf"\b{re.escape(key)}\b", normalized):
            found.append(ticker)
            continue
        first = tokens[0]
        if (
            len(tokens) >= 2
            and len(first) >= 5
            and first not in _GENERIC_NAMES
            and first not in _WEAK_FIRST
            and first not in _COMMON_FIRST
            and not re.search(rf"\b{re.escape(first)}\s+of\b", normalized)
            and re.search(rf"\b{re.escape(first)}\b", normalized)
        ):
            found.append(ticker)
        elif (
            len(tokens) >= 2
            and first in _WEAK_FIRST | _COMMON_FIRST
            and re.search(rf"\b{re.escape(first)}\s+{re.escape(tokens[1])}\b", normalized)
        ):
            found.append(ticker)
    return list(dict.fromkeys(found))


def expand_related(mentioned: list[str], relations: list[Relation]) -> list[str]:
    """Peers, suppliers, and customers of a mentioned company."""
    extra: list[str] = []
    mentioned_set = set(mentioned)
    for ticker in mentioned:
        for relation in relations:
            other = _other_side(ticker, relation)
            if other and other not in mentioned_set and other not in extra:
                extra.append(other)
    return extra


def _other_side(ticker: str, relation: Relation) -> str | None:
    src = relation.src_ticker
    dst = relation.dst_ticker
    kind = relation.relation
    if kind in {"competitor", "partner"}:
        if src == ticker and dst:
            return dst
        if dst == ticker:
            return src
    elif kind == "supplier_of":
        if dst == ticker:
            return src
        if src == ticker and dst:
            return dst
    elif kind == "customer_of":
        if dst == ticker:
            return src
        if src == ticker and dst:
            return dst
    return None


def _industry_peers(mentioned: list[str], securities: list[Security], *, limit: int) -> list[str]:
    by_ticker = {security.ticker: security for security in securities}
    industries = {
        (by_ticker[ticker].industry or "").strip()
        for ticker in mentioned
        if ticker in by_ticker and len((by_ticker[ticker].industry or "").strip()) >= 4
    }
    peers: list[str] = []
    for security in sorted(securities, key=lambda item: item.ticker):
        if security.industry in industries and security.ticker not in mentioned:
            peers.append(security.ticker)
        if len(peers) >= limit:
            break
    return peers


def analysis_candidates(
    text: str,
    securities: list[Security],
    relations: list[Relation],
    profiles: list[CompanyProfile] | None = None,
    *,
    limit: int = 12,
) -> tuple[list[str], list[str], list[str]]:
    """Direct mentions, known counterparties, and industry or macro candidates.

    The third list is who the story might affect even though it never names them:
    same-industry peers of a named company, companies whose profile lists the
    story's macro factor, and a few large names in an exposed sector.
    """
    by_ticker = {security.ticker: security for security in securities}
    mentioned = [ticker for ticker in mentioned_tickers(text, securities) if ticker in by_ticker]
    related = [ticker for ticker in expand_related(mentioned, relations) if ticker in by_ticker]
    for ticker in outside_tickers(text):
        if ticker in by_ticker and ticker not in mentioned and ticker not in related:
            related.append(ticker)
    factors = set(tag_factors(text))
    if factors and profiles:
        for profile in profiles:
            if profile.ticker in by_ticker and profile.ticker not in mentioned and profile.ticker not in related:
                if factors.intersection(profile.sensitivities):
                    related.append(profile.ticker)
    exposure = _industry_peers(mentioned, securities, limit=4)
    seen = set(mentioned) | set(related) | set(exposure)
    # A named company is expanded through its peers and known counterparties.
    # Macro names are added only when the story names nobody, so a filing's
    # "Regulation FD" line or a single firm does not pull in every sector.
    if not mentioned and not related:
        lead = re.sub(r"regulation\s+fd", " ", text[:900], flags=re.IGNORECASE)
        focused = False
        for ticker in factor_tickers(lead):
            if ticker in by_ticker and ticker not in seen:
                exposure.append(ticker)
                seen.add(ticker)
                focused = True
        if not focused:
            for ticker in bellwethers_for(sectors_for_text(lead)):
                if ticker in by_ticker and ticker not in seen:
                    exposure.append(ticker)
                    seen.add(ticker)
    room = max(limit, len(mentioned))
    ordered = list(dict.fromkeys(mentioned + related + exposure))[:room]
    mentioned_set = set(mentioned)
    related_set = set(related)
    return (
        [ticker for ticker in ordered if ticker in mentioned_set],
        [ticker for ticker in ordered if ticker in related_set],
        [ticker for ticker in ordered if ticker not in mentioned_set and ticker not in related_set],
    )


def link_entities(
    text: str,
    securities: list[Security],
    relations: list[Relation],
    profiles: list[CompanyProfile] | None = None,
    *,
    limit: int = 12,
) -> list[tuple[str, str]]:
    mentioned, related, exposure = analysis_candidates(
        text, securities, relations, profiles, limit=limit
    )
    links = [(ticker, "mentioned") for ticker in mentioned]
    links.extend((ticker, "expanded") for ticker in related)
    links.extend((ticker, "exposure") for ticker in exposure)
    return links
