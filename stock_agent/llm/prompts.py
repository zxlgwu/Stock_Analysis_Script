"""Versioned prompt templates. Stored impacts record the version string."""

FILTER_PROMPT_VERSION = "filter-v2"
IMPACT_PROMPT_VERSION = "impact-v4"
THESIS_PROMPT_VERSION = "thesis-v2"
PROPAGATION_PROMPT_VERSION = "propagation-v7"
PROFILE_PROMPT_VERSION = "profile-v1"

MATERIAL_CATEGORIES = (
    "earnings",
    "guidance",
    "m_and_a",
    "regulation",
    "litigation",
    "product",
    "contract",
    "management",
    "macro",
    "supply_chain",
    "other",
)

FILTER_INSTRUCTIONS = (
    "TASK: materiality. Keep a story when it could change revenue over 6 months "
    "or more for a public company, its competitors, its suppliers, its customers, "
    "or an industry exposed to the same force. That includes macro news such as "
    "oil, rates, tariffs, regulation, and demand shifts. Drop price recaps, "
    "obituaries, crime, and stories about private or foreign firms with no path "
    "into a US-listed industry. "
    f"Category must be one of: {', '.join(MATERIAL_CATEGORIES)}."
)

PROPAGATION_INSTRUCTIONS = (
    "TASK: propagation. You are an equity analyst. Map how THIS article changes "
    "the revenue of US-listed companies. Do not stop at the company in the headline. "
    "First name the one thing that changed: a product, a capacity, a price, a customer, "
    "a rule, or a technology. Then cover both chains for that thing. Skip a role this "
    "article does not support. "
    "Supply chain: who supplies the input, who produces or operates the thing, who "
    "processes it, and who moves or sells it. "
    "Affected chain: who buys it, who buys from those buyers, who competes with the "
    "producer, and who gains or loses from the price or cost change. "
    "A foreign company still counts when its product, input, or customer reaches a "
    "US-listed industry. "
    "Rules: use as many channels as those roles require, up to 12. Industry targets "
    "must be copied exactly from the supplied industries list. If that list has no "
    "industry for a role, skip the role. Company targets must appear in the article "
    "or the named-companies list. Do not reuse a chain from another story. Skip guesses. "
    "Set relevant to true when a named company or listed industry has a revenue or cost "
    "link. Set relevant to false and return no channels only for personal finance, "
    "celebrity, or local news with no business effect. "
    "Each mechanism is one sentence that names a revenue or cost line and says whether "
    "that line rises or falls. "
    "Return only JSON with keys relevant, changed, event_summary, and channels. "
    "changed is a short phrase for the one thing that changed. "
    "Each channel has target, kind (company or industry), order (1 for the subject, "
    "2 for the supply chain and the direct customers or competitors, 3 for the next "
    "buyers and the price or cost change), relation (direct, competitor, supplier, "
    "customer, or macro_exposure), direction (positive, negative, or mixed), and mechanism."
)

IMPACT_INSTRUCTIONS = (
    "TASK: impact. Use only the supplied article and the supplied candidate list. "
    "Each candidate carries order (1 direct, 2 competitor/supplier/customer, 3 wider "
    "ripple), a suggested relation, and why_included, the step that links it to the "
    "story. Judge every candidate, including the second- and third-order ones. "
    "A candidate is not an impact by itself. Include a company only when you can "
    "explain a concrete revenue mechanism, including second-order effects: "
    "direct means the article is about that company; competitor means a rival's "
    "news shifts this company's share or pricing; supplier means this company "
    "sells into the affected business; customer means this company buys from it; "
    "macro_exposure means a rate, commodity, policy, or demand shift hits this "
    "company's revenue. Follow the chain in why_included. A company that sells the "
    "affected product can gain when supply tightens. A company that buys that "
    "product, or buys from those buyers, can lose when its cost rises. A foreign "
    "or sanctioned company still counts. Do not return an empty impacts list only "
    "because the company in the headline is not a US company. Skip a company "
    "when the link would be a guess. "
    "For each included company, reasoning must be two sentences: what happened, "
    "then how that changes the named revenue line, in which direction, and over "
    "which horizon. est_revenue_impact_pct is your percent change in that revenue "
    "line and must be above 0 for a positive direction and below 0 for a negative "
    "direction. horizon mid means 6–18 months and long means 2–5 years. "
    "Do not invent companies, tickers, or source URLs. Never use a ticker that "
    "is not in the supplied list. Use an empty impacts list when no candidate "
    "has a mechanism. "
    "Return only JSON: {\"cluster_id\": \"...\", \"event_summary\": \"...\", "
    "\"event_type\": \"earnings\", \"impacts\": [{\"ticker\": \"TICKER\", "
    "\"relation\": \"direct\", \"direction\": \"positive\", "
    "\"affected_revenue_line\": \"the revenue line\", \"est_revenue_impact_pct\": 1.0, "
    "\"horizon\": \"mid\", \"confidence\": 0.6, \"already_priced_in\": \"partially\", "
    "\"reasoning\": \"what happened. how the revenue line changes.\", "
    "\"key_uncertainties\": [\"what could make this wrong\"]}]}. "
    "relation is direct, competitor, supplier, customer, or macro_exposure. "
    "direction is positive, negative, or neutral. horizon is mid or long. "
    "already_priced_in is likely, partially, or unlikely."
)

THESIS_INSTRUCTIONS = (
    "TASK: thesis. The user message names one company and the news effects already "
    "estimated for it. Write only about that company. Do not name any other company. "
    "Base the thesis on those news effects. Then note the bear case, the risks, "
    "and what would invalidate the view. Mention the supplied price history only "
    "when a large past gain or a deep drawdown conflicts with the news. "
    "Return only JSON: {\"ticker\": \"TICKER\", \"thesis\": \"...\", "
    "\"bear_case\": \"...\", \"risks\": [\"...\"], \"invalidation\": \"...\"}."
)
