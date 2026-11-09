"""Map a story to every company it can reach: direct, second-order, and ripple effects."""

from __future__ import annotations

import difflib
import json
import math
import re
from dataclasses import dataclass

from stock_agent.analysis.schemas import Channel, ImpactMap
from stock_agent.core.models import Security
from stock_agent.llm.base import BudgetExceeded, Message
from stock_agent.llm.prompts import PROPAGATION_INSTRUCTIONS, PROPAGATION_PROMPT_VERSION
from stock_agent.llm.router import Router
from stock_agent.knowledge.exposure import FACTOR_INDUSTRY_HINTS
from stock_agent.knowledge.taxonomy import tag_factors
from stock_agent.processing.entity_linking import mentioned_tickers

PER_INDUSTRY = 4
MAX_CHANNELS = 6
MAX_INDUSTRIES = 10
INDUSTRY_EMBED_MODEL = "ollama/nomic-embed-text"
_TOKEN = re.compile(r"[a-z0-9]+")
_STOP = {"and", "or", "of", "the", "a", "an", "services", "products", "other", "multi"}
_EXAMPLE_TARGETS = {"boeing", "united airlines", "aerospace & defense"}
_INDUSTRY_WORDS = (
    "airlines",
    "retail",
    "banks",
    "reits",
    "utilities",
    "services",
    "equipment",
    "manufacturers",
    "insurance",
    "software",
    "semiconductors",
)


@dataclass(frozen=True)
class ResolvedChannel:
    channel: Channel
    tickers: tuple[str, ...]


def map_propagation(
    router: Router,
    cluster_id: str,
    title: str,
    text: str,
    industries: list[str],
    named_companies: list[str] | None = None,
) -> ImpactMap | None:
    named = named_companies or []
    content = (
        f"Story id: {cluster_id}\n"
        f"Headline: {title}\n"
        f"Article:\n{text[:2500]}\n\n"
        f"Companies named in the story: {json.dumps(named) if named else 'none detected'}\n"
        f"Industry targets must be copied from this list: {json.dumps(industries)}"
    )
    messages = [
        Message("system", PROPAGATION_INSTRUCTIONS),
        Message("user", content),
    ]
    try:
        result = router.complete("analysis", messages, response_schema=ImpactMap, max_tokens=900)
    except BudgetExceeded:
        return None
    parsed: ImpactMap = result.parsed  # type: ignore[assignment]
    article = f"{title}\n{text}"
    parsed.channels = prune_channels(parsed.channels, article, industries)
    if parsed.channels:
        parsed.relevant = True
    return parsed


def related_industries(
    title: str,
    text: str,
    industries: list[str],
    embed_fn=None,
    *,
    named_industries: list[str] | None = None,
    k: int = MAX_INDUSTRIES,
    cache: dict | None = None,
) -> list[str]:
    """Shortlist GICS industries this story can reach, so the model cannot dump the whole list."""
    query = f"{title}\n{text[:400]}"
    embedded = _embed_industries(query, industries, embed_fn, cache)
    keyword = _keyword_industries(query, industries)
    factor = _factor_industries(query, industries)
    related = embedded + [name for name in keyword + factor if name not in embedded]
    related_set = set(related)
    ranked: list[str] = []
    for name in named_industries or []:
        if name in industries and name not in ranked and (not related_set or name in related_set):
            ranked.append(name)
    for name in related:
        if name not in ranked:
            ranked.append(name)
    return ranked[:k]


def prune_channels(channels: list[Channel], article: str, industries: list[str]) -> list[Channel]:
    lowered = article.lower()
    names = [name.lower() for name in industries]
    kept: list[Channel] = []
    seen: set[tuple[str, int]] = set()
    for channel in sorted(channels, key=lambda item: item.order):
        target = channel.target.strip()
        if not target:
            continue
        if target.lower() in _EXAMPLE_TARGETS and target.lower() not in lowered:
            continue
        if channel.kind == "industry" and _match_industry(target, names) is None:
            lowered_target = target.lower()
            if "&" in target or any(word in lowered_target for word in _INDUSTRY_WORDS):
                continue
            channel = channel.model_copy(update={"kind": "company"})
        key = (target.lower(), channel.order)
        if key in seen:
            continue
        seen.add(key)
        kept.append(channel)
        if len(kept) >= MAX_CHANNELS:
            break
    return kept


def resolve_channels(
    channels: list[Channel],
    securities: list[Security],
    liquidity: dict[str, float],
    *,
    per_industry: int = PER_INDUSTRY,
) -> list[ResolvedChannel]:
    by_industry: dict[str, list[Security]] = {}
    for security in securities:
        if security.industry:
            by_industry.setdefault(security.industry.lower(), []).append(security)
    names = list(by_industry)
    resolved: list[ResolvedChannel] = []
    for channel in sorted(channels, key=lambda item: item.order):
        tickers: list[str] = []
        if channel.kind == "company":
            tickers = mentioned_tickers(channel.target, securities)[:2]
        if not tickers:
            industry = _match_industry(channel.target, names)
            if industry is not None:
                pool = sorted(
                    by_industry[industry],
                    key=lambda security: liquidity.get(security.ticker, 0.0),
                    reverse=True,
                )
                tickers = [security.ticker for security in pool[:per_industry]]
        if tickers:
            resolved.append(ResolvedChannel(channel, tuple(tickers)))
    return resolved


def fallback_channels(industries: list[str], title: str) -> list[Channel]:
    """If the small model returns nothing, still send the ranked industries to impact."""
    return [
        Channel(
            target=name,
            kind="industry",
            order=2 if index < 2 else 3,
            relation="macro_exposure",
            direction="mixed",
            mechanism=f"Exposed to the industry force in this story: {title[:120]}",
        )
        for index, name in enumerate(industries[:4])
    ]


def industry_embedder(router: Router):
    """Prefer the local nomic model; fall back to the configured embed role."""

    def embed(texts: list[str]) -> list[list[float]]:
        provider = router.providers.get("litellm")
        if provider is not None:
            try:
                return provider.embed(texts, model=INDUSTRY_EMBED_MODEL)
            except Exception as exc:
                print(f"  industry embed fallback: {exc}"[:200])
        return router.embed(texts)

    return embed


def _embed_industries(query: str, industries: list[str], embed_fn, cache: dict | None) -> list[str]:
    if embed_fn is None or not industries:
        return []
    labels = [f"GICS industry: {name}" for name in industries]
    try:
        if cache is not None and cache.get("labels") == industries and cache.get("vectors"):
            industry_vecs = cache["vectors"]
            query_vec = embed_fn([f"Story: {query}"])[0]
        else:
            vectors = embed_fn([f"Story: {query}"] + labels)
            query_vec, industry_vecs = vectors[0], vectors[1:]
            if cache is not None:
                cache["labels"] = industries
                cache["vectors"] = industry_vecs
    except Exception as exc:
        print(f"  industry embed failed: {exc}"[:200])
        return []
    if not query_vec or len(query_vec) < 100:
        return []
    scored = [(_cosine(query_vec, vector), name) for name, vector in zip(industries, industry_vecs)]
    scored.sort(reverse=True)
    if not scored or scored[0][0] < 0.50:
        return []
    return [name for score, name in scored[:4] if score >= 0.48]


def _factor_industries(query: str, industries: list[str]) -> list[str]:
    hints: list[str] = []
    for factor in tag_factors(query):
        hints.extend(FACTOR_INDUSTRY_HINTS.get(factor, ()))
    found: list[str] = []
    for hint in hints:
        needle = hint.lower()
        for name in industries:
            if needle in name.lower() and name not in found:
                found.append(name)
    return found


def _keyword_industries(query: str, industries: list[str]) -> list[str]:
    words = set(_TOKEN.findall(query.lower())) - _STOP
    scored: list[tuple[float, str]] = []
    for name in industries:
        tokens = set(_TOKEN.findall(name.lower())) - _STOP
        if not tokens:
            continue
        overlap = len(words & tokens) / len(tokens)
        if overlap >= 0.34:
            scored.append((overlap, name))
    scored.sort(reverse=True)
    return [name for _, name in scored]


def _match_industry(target: str, names: list[str]) -> str | None:
    wanted = target.strip().lower()
    if wanted in names:
        return wanted
    close = difflib.get_close_matches(wanted, names, n=1, cutoff=0.8)
    if close:
        return close[0]
    words = set(wanted.replace("&", " ").split()) - _STOP
    best, best_score = None, 0.0
    for name in names:
        other = set(name.replace("&", " ").split()) - _STOP
        if not other:
            continue
        score = len(words & other) / len(other)
        if score > best_score:
            best, best_score = name, score
    return best if best_score >= 0.67 else None


def _cosine(left: list[float], right: list[float]) -> float:
    if not left or not right:
        return 0.0
    size = min(len(left), len(right))
    dot = sum(left[i] * right[i] for i in range(size))
    norm_left = math.sqrt(sum(left[i] * left[i] for i in range(size))) or 1.0
    norm_right = math.sqrt(sum(right[i] * right[i] for i in range(size))) or 1.0
    return dot / (norm_left * norm_right)


def prompt_version() -> str:
    return PROPAGATION_PROMPT_VERSION
