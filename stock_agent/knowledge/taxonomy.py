"""Fixed macro factors. News tags and company profiles share this list."""

from __future__ import annotations

TAXONOMY: tuple[str, ...] = (
    "interest_rates",
    "usd_strength",
    "oil_price",
    "natural_gas",
    "china_exposure",
    "tariffs",
    "ai_capex",
    "consumer_discretionary_spend",
    "consumer_staples_demand",
    "healthcare_policy",
    "drug_pricing",
    "defense_budget",
    "housing",
    "labor_costs",
    "supply_chain",
    "semiconductor_cycle",
    "cloud_spend",
    "advertising_spend",
    "regulation",
    "antitrust",
    "cybersecurity",
    "climate_policy",
    "credit_conditions",
    "insurance_losses",
    "travel_demand",
    "auto_demand",
    "retail_traffic",
    "fx_emerging_markets",
    "commodity_input_costs",
    "power_demand",
)

KEYWORDS: dict[str, tuple[str, ...]] = {
    "interest_rates": ("interest rate", "rate hike", "rate cut", "fed funds"),
    "usd_strength": ("dollar strength", "strong dollar", "usd strength"),
    "oil_price": ("oil price", "crude oil", "brent"),
    "natural_gas": ("natural gas",),
    "china_exposure": ("china", "chinese"),
    "tariffs": ("tariff", "tariffs"),
    "ai_capex": ("ai capex", "ai spending", "gpu demand", "data center spend", " ai ", "ai adopter"),
    "consumer_discretionary_spend": ("consumer spending", "discretionary spend"),
    "consumer_staples_demand": ("grocery demand", "staples demand"),
    "healthcare_policy": ("medicare", "healthcare policy", "medicaid"),
    "drug_pricing": ("drug pricing", "drug price"),
    "defense_budget": ("defense budget", "pentagon budget"),
    "housing": ("housing market", "mortgage rate", "home sales", "buy a house", "homebuyer"),
    "labor_costs": ("wage inflation", "labor cost"),
    "supply_chain": ("supply chain", "supplier shortage"),
    "semiconductor_cycle": ("semiconductor", "chip shortage", "foundry"),
    "cloud_spend": ("cloud spend", "cloud growth"),
    "advertising_spend": ("ad spend", "advertising spend"),
    "regulation": ("regulation", "regulator"),
    "antitrust": ("antitrust", "monopoly case"),
    "cybersecurity": ("cybersecurity", "cyber", "data breach"),
    "climate_policy": ("climate rule", "climate finance", "emissions rule", "carbon tax", "cop31", "cop30"),
    "credit_conditions": ("credit conditions", "loan losses", "default rate"),
    "insurance_losses": ("catastrophe losses", "insured losses"),
    "travel_demand": ("travel demand", "airline traffic"),
    "auto_demand": ("auto demand", "vehicle sales"),
    "retail_traffic": ("retail traffic", "same-store sales"),
    "fx_emerging_markets": ("emerging market currency", "em fx"),
    "commodity_input_costs": ("input cost", "commodity cost"),
    "power_demand": ("power demand", "electricity demand", "grid capacity"),
}


def tag_factors(text: str) -> list[str]:
    lowered = text.lower()
    found = [factor for factor, words in KEYWORDS.items() if any(word in lowered for word in words)]
    return [factor for factor in TAXONOMY if factor in found]
