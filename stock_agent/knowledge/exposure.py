"""Which sectors a story can reach when the company is not named."""

from __future__ import annotations

import re

from stock_agent.knowledge.taxonomy import tag_factors

# A macro tag pulls in a few large companies in the sectors that sell into that force.
FACTOR_SECTORS: dict[str, tuple[str, ...]] = {
    "interest_rates": ("Financials", "Real Estate"),
    "usd_strength": ("Information Technology", "Industrials", "Materials"),
    "oil_price": ("Energy",),
    "natural_gas": ("Energy", "Utilities"),
    "china_exposure": ("Information Technology", "Industrials", "Consumer Discretionary", "Materials"),
    "tariffs": ("Industrials", "Consumer Discretionary", "Information Technology", "Materials"),
    "ai_capex": ("Information Technology",),
    "consumer_discretionary_spend": ("Consumer Discretionary",),
    "consumer_staples_demand": ("Consumer Staples",),
    "healthcare_policy": ("Health Care",),
    "drug_pricing": ("Health Care",),
    "defense_budget": ("Industrials",),
    "housing": ("Consumer Discretionary", "Financials", "Real Estate"),
    "labor_costs": ("Consumer Discretionary", "Industrials"),
    "supply_chain": ("Industrials", "Information Technology", "Consumer Discretionary"),
    "semiconductor_cycle": ("Information Technology",),
    "cloud_spend": ("Information Technology",),
    "advertising_spend": ("Communication Services", "Consumer Discretionary"),
    "regulation": ("Financials", "Health Care", "Communication Services", "Energy"),
    "antitrust": ("Information Technology", "Communication Services"),
    "cybersecurity": ("Information Technology",),
    "climate_policy": ("Energy", "Utilities", "Industrials"),
    "credit_conditions": ("Financials",),
    "insurance_losses": ("Financials",),
    "travel_demand": ("Industrials", "Consumer Discretionary"),
    "auto_demand": ("Consumer Discretionary",),
    "retail_traffic": ("Consumer Discretionary", "Consumer Staples"),
    "fx_emerging_markets": ("Information Technology", "Consumer Staples", "Materials"),
    "commodity_input_costs": ("Materials", "Consumer Staples", "Industrials"),
    "power_demand": ("Utilities", "Information Technology", "Industrials"),
}

# Phrases that point at a sector even when the taxonomy wording is absent.
SECTOR_KEYWORDS: dict[str, tuple[str, ...]] = {
    "Energy": ("crude oil", "oil price", "brent", "wti", "opec", "refiner", "natural gas", "lng "),
    "Information Technology": (
        "semiconductor",
        "chipmaker",
        "data center",
        "cloud computing",
        "artificial intelligence",
        "gpu demand",
    ),
    "Financials": ("bank lending", "bank stock", "big bank", "net interest", "loan losses", "insurance premium"),
    "Health Care": ("drug pricing", "medicare", "medicaid", "fda approval"),
    "Consumer Discretionary": ("vehicle sales", "same-store sales", "consumer spending"),
    "Consumer Staples": ("grocery demand", "packaged food"),
    "Industrials": ("defense budget", "airline traffic", "freight volume"),
    "Communication Services": ("advertising spend", "ad spend", "streaming subscriber"),
    "Utilities": ("electricity demand", "grid capacity", "power demand"),
    "Real Estate": ("housing market", "mortgage rate", "home sales"),
    "Materials": ("copper price", "steel price", "commodity cost"),
}

# GICS industry names (or unambiguous prefixes) a macro factor can reach.
FACTOR_INDUSTRY_HINTS: dict[str, tuple[str, ...]] = {
    "tariffs": (
        "Steel",
        "Copper",
        "Automobile Manufacturers",
        "Automotive Parts",
        "Semiconductors",
        "Consumer Staples Merchandise Retail",
        "Construction Machinery",
        "Apparel Retail",
    ),
    "oil_price": ("Oil & Gas", "Integrated Oil", "Passenger Airlines"),
    "interest_rates": ("Diversified Banks", "Regional Banks", "Retail REITs", "Homebuilding"),
    "ai_capex": ("Semiconductors", "Technology Hardware", "Internet Services", "Data Center"),
    "semiconductor_cycle": ("Semiconductors", "Semiconductor Materials"),
    "housing": ("Homebuilding", "Building Products", "Home Improvement Retail"),
    "travel_demand": ("Passenger Airlines", "Hotels, Resorts", "Casinos & Gaming"),
    "auto_demand": ("Automobile Manufacturers", "Automotive Parts", "Automotive Retail"),
    "retail_traffic": ("Broadline Retail", "Consumer Staples Merchandise Retail", "Apparel Retail"),
}

# When a factor is explicit, start with the companies that sell into that force.
FACTOR_TICKERS: dict[str, tuple[str, ...]] = {
    "cybersecurity": ("CRWD", "PANW", "FTNT", "MSFT"),
    "ai_capex": ("NVDA", "MSFT", "AMZN", "GOOGL", "AVGO"),
    "oil_price": ("XOM", "CVX", "COP", "SLB"),
    "natural_gas": ("XOM", "CVX", "EQT"),
    "climate_policy": ("XOM", "CVX", "NEE", "DUK"),
    "interest_rates": ("JPM", "BAC", "GS"),
    "housing": ("DHI", "LEN", "PHM", "JPM"),
    "travel_demand": ("DAL", "UAL", "MAR", "BKNG"),
    "drug_pricing": ("LLY", "MRK", "PFE", "JNJ"),
    "defense_budget": ("LMT", "RTX", "NOC", "GD"),
    "advertising_spend": ("GOOGL", "META", "NFLX"),
    "credit_conditions": ("JPM", "BAC", "C"),
    "semiconductor_cycle": ("NVDA", "AVGO", "AMD", "AMAT", "LRCX"),
    "power_demand": ("NEE", "DUK", "VST", "CEG"),
}

# Large non-US firms whose news reliably reaches tracked companies. Story-specific
# links come from the propagation step, not from this table.
OUTSIDE_LINKS: tuple[tuple[str, tuple[tuple[str, str], ...]], ...] = (
    ("foxconn", (("AAPL", "customer"), ("HPQ", "customer"))),
    ("hon hai", (("AAPL", "customer"),)),
    ("taiwan semiconductor", (("NVDA", "customer"), ("AMD", "customer"), ("AVGO", "customer"), ("AAPL", "customer"))),
    ("tsmc", (("NVDA", "customer"), ("AMD", "customer"), ("AVGO", "customer"), ("AAPL", "customer"))),
    ("samsung electronics", (("AAPL", "competitor"), ("MU", "competitor"))),
    ("siemens healthineers", (("TMO", "competitor"), ("DHR", "competitor"), ("ABT", "competitor"))),
    ("wipro", (("ACN", "competitor"), ("CTSH", "competitor"), ("IBM", "competitor"))),
    ("infosys", (("ACN", "competitor"), ("CTSH", "competitor"), ("IBM", "competitor"))),
    ("asml", (("AMAT", "competitor"), ("LRCX", "competitor"), ("KLAC", "competitor"))),
    ("novo nordisk", (("LLY", "competitor"),)),
    ("toyota", (("GM", "competitor"), ("F", "competitor"), ("TSLA", "competitor"))),
    ("opec", (("XOM", "supplier"), ("CVX", "supplier"), ("COP", "supplier"))),
)

# Large, liquid names used as the second-order set. Names absent from the universe are skipped.
BELLWETHERS: dict[str, tuple[str, ...]] = {
    "Energy": ("XOM", "CVX", "COP", "SLB", "EOG"),
    "Information Technology": ("AAPL", "MSFT", "NVDA", "AVGO", "ORCL", "AMD"),
    "Financials": ("JPM", "BAC", "GS", "MS", "BLK"),
    "Health Care": ("UNH", "LLY", "JNJ", "MRK", "ABBV"),
    "Consumer Discretionary": ("AMZN", "TSLA", "HD", "MCD", "NKE"),
    "Consumer Staples": ("PG", "KO", "PEP", "WMT", "COST"),
    "Industrials": ("CAT", "HON", "UNP", "BA", "GE", "ETN"),
    "Communication Services": ("GOOGL", "META", "NFLX", "DIS", "TMUS"),
    "Utilities": ("NEE", "DUK", "SO"),
    "Real Estate": ("PLD", "AMT", "EQIX"),
    "Materials": ("LIN", "SHW", "FCX"),
}


def sectors_for_text(text: str) -> list[str]:
    found: set[str] = set()
    for factor in tag_factors(text):
        found.update(FACTOR_SECTORS.get(factor, ()))
    lowered = text.lower()
    for sector, phrases in SECTOR_KEYWORDS.items():
        if any(phrase in lowered for phrase in phrases):
            found.add(sector)
    return sorted(found)


def bellwethers_for(sectors: list[str]) -> list[str]:
    """Round-robin so one sector does not crowd out the others."""
    pools = [list(BELLWETHERS.get(sector, ())) for sector in sectors]
    ordered: list[str] = []
    while any(pools):
        for pool in pools:
            if not pool:
                continue
            ticker = pool.pop(0)
            if ticker not in ordered:
                ordered.append(ticker)
    return ordered


def factor_tickers(text: str) -> list[str]:
    ordered: list[str] = []
    for factor in tag_factors(text):
        for ticker in FACTOR_TICKERS.get(factor, ()):
            if ticker not in ordered:
                ordered.append(ticker)
    return ordered


def outside_tickers(text: str) -> list[str]:
    normalized = re.sub(r"\s+", " ", re.sub(r"[^a-z0-9 ]", " ", text.lower()))
    ordered: list[str] = []
    for phrase, links in OUTSIDE_LINKS:
        if phrase in normalized:
            for ticker, _relation in links:
                if ticker not in ordered:
                    ordered.append(ticker)
    return ordered
