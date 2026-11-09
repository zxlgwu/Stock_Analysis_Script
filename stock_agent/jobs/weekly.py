"""Weekly analysis: cluster, score, write theses, render the report."""

from __future__ import annotations

import hashlib
import re
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Callable

from stock_agent.analysis.impact import analyze_cluster
from stock_agent.analysis.plausibility import supported_impacts
from stock_agent.analysis.propagation import (
    fallback_channels,
    industry_embedder,
    map_propagation,
    related_industries,
    resolve_channels,
)
from stock_agent.analysis.propagation import prompt_version as propagation_version
from stock_agent.analysis.schemas import ImpactMap
from stock_agent.ingest.news.article_text import fetch_article_text
from stock_agent.processing.priority import story_priority
from stock_agent.analysis.impact import prompt_version as impact_version
from stock_agent.analysis.materiality import prompt_version as filter_version
from stock_agent.analysis.price_stats import friday_on_or_before
from stock_agent.analysis.technical import compute_technical
from stock_agent.analysis.thesis import write_thesis
from stock_agent.core.config import Settings
from stock_agent.core.models import ScoreRecord, Security, TechnicalSignals
from stock_agent.db.repository import Database
from stock_agent.evaluation.metrics import quintile_spread, rank_ic
from stock_agent.evaluation.paper_portfolio import period_return
from stock_agent.llm.base import LLMResponseError
from stock_agent.llm.router import Router
from stock_agent.notify.email_smtp import EmailNotifier, MissingSMTP
from stock_agent.processing.dedupe import cluster_vectors
from stock_agent.processing.entity_linking import link_entities, mentioned_tickers
from stock_agent.processing.prefilter import is_low_value
from stock_agent.report.charts import ChartSpec, render_price_charts
from stock_agent.report.email_report import (
    AnalyzedStory,
    CompanyEffect,
    EmailReport,
    Highlight,
    SpreadStep,
    render_html,
)
from stock_agent.scoring.composite import build_scores, rank_lists
from stock_agent.scoring.factors import quality_raw, risk_raw, technical_raw, value_raw
from stock_agent.universe import load_universe
from stock_agent.universe.listings import load_public_companies

_EMPTY_TECHNICAL = TechnicalSignals(None, None, None, None, None, None, None)


def run_weekly(
    settings: Settings,
    *,
    as_of: date | None = None,
    router: Router | None = None,
    notifier: EmailNotifier | None = None,
    render_charts: bool = True,
    text_fetcher: Callable[[str], str] | None = None,
) -> dict:
    as_of = friday_on_or_before(as_of or date.today())
    if text_fetcher is None and settings.fetch_article_text:
        text_fetcher = fetch_article_text
    now = datetime.now(timezone.utc)
    with Database(settings.database_path) as db:
        llm_enabled = router is not None or _llm_configured(settings)
        if router is None:
            router = Router(settings, db)
        members = _members(settings, db)
        companies = load_public_companies(settings, members)
        print(f"Week ending {as_of.isoformat()}.")
        summary = {
            "week_ending": as_of.isoformat(),
            "articles": 0,
            "clusters": 0,
            "impacts": 0,
            "scores": 0,
            "email_status": "skipped",
        }
        _step(db, as_of, "cluster", "running", now)
        summary["clusters"] = _cluster(db, router, companies)
        summary["articles"] = summary["clusters"]
        _step(db, as_of, "cluster", "done", now)

        _step(db, as_of, "materiality", "running", now)
        if llm_enabled:
            _select_stories(db, companies, settings.max_stories_per_week, text_fetcher)
        _step(db, as_of, "materiality", "done", now)

        _step(db, as_of, "impact", "running", now)
        summary["impacts"] = _analyze(db, router, companies, as_of) if llm_enabled else 0
        _step(db, as_of, "impact", "done", now)

        _step(db, as_of, "score", "running", now)
        scores = _score(db, settings, members, as_of)
        summary["scores"] = len(scores)
        _step(db, as_of, "score", "done", now)

        lists = _lists(db, settings, members, scores, as_of)
        _step(db, as_of, "thesis", "running", now)
        if llm_enabled:
            theses = _theses(db, router, lists, as_of, {security.ticker: security.name for security in companies})
        else:
            waiting = "News analysis is waiting on an LLM model in config/settings.yaml."
            theses = {
                row.ticker: (waiting, "")
                for name in ("long", "mid", "risk")
                for row in lists[name]
            }
        _step(db, as_of, "thesis", "done", now)
        _save_recommendations(db, as_of, lists, theses)

        for metric, value in _evaluate(db, as_of).items():
            horizon, name = metric.split(":", 1)
            db.record_metric(as_of, name, horizon, value)

        notes = []
        if not llm_enabled:
            notes.append("LLM models are still placeholders, so news impacts and written theses were skipped.")
        print(f"Writing the report for the week ending {as_of.isoformat()}.")
        report = _report(settings, db, companies, lists, theses, as_of, render_charts, notes)
        html_path = settings.root / "output" / "reports" / f"{as_of.isoformat()}.html"
        html_path.parent.mkdir(parents=True, exist_ok=True)
        html_path.write_text(render_html(report, html_path=html_path))
        summary["report_path"] = str(html_path)
        summary["email_status"] = _deliver(db, settings, report, notifier)
        _step(db, as_of, "email", summary["email_status"], now)
        return summary


def _members(settings: Settings, db: Database) -> list[Security]:
    cache = settings.root / "data" / "cache"
    found: list[Security] = []
    seen: set[str] = set()
    for spec in settings.universes:
        universe = load_universe(spec, cache_dir=cache)
        for security in db.active_members(universe.name):
            if security.ticker not in seen:
                seen.add(security.ticker)
                found.append(security)
    return found


def _profiles(db: Database):
    rows = db.conn.execute("SELECT ticker FROM company_profiles").fetchall()
    return [profile for row in rows if (profile := db.get_profile(row["ticker"]))]


def _cluster(db: Database, router: Router, securities: list[Security]) -> int:
    _isolate_filings(db)
    articles = db.unclustered_articles()
    if not articles:
        print("Clustering: no new articles.")
        return 0
    print(f"Clustering {len(articles)} articles.")
    filings = [article for article in articles if article.source == "sec_edgar_8k"]
    articles = [article for article in articles if article.source != "sec_edgar_8k"]
    relations = db.all_relations()
    profiles = _profiles(db)
    for article in filings:
        _store_single_cluster(db, article, securities, relations, profiles)
    if not articles:
        print(f"Clustered {len(filings)} filing stories.")
        return len(filings)
    vectors = router.embed([f"{article.title}. {article.body[:400]}" for article in articles])
    relations = db.all_relations()
    profiles = _profiles(db)
    groups = cluster_vectors([article.id for article in articles], vectors)
    by_id = {article.id: article for article in articles}
    for group in groups:
        members = [by_id[article_id] for article_id in group]
        representative = members[0]
        cluster_id = hashlib.sha256("".join(sorted(group)).encode()).hexdigest()[:16]
        low, reason = is_low_value(representative.title, representative.body, representative.source)
        db.upsert_cluster(
            cluster_id,
            representative.id,
            min(member.published_at for member in members),
            len(members),
            dropped=low,
            drop_reason=reason or None,
        )
        db.assign_cluster(group, cluster_id)
        if low:
            continue
        text = "\n".join(f"{member.title}. {member.body}" for member in members)
        db.replace_entities(cluster_id, link_entities(text, securities, relations, profiles))
    count = len(groups) + len(filings)
    print(f"Clustered {count} stories.")
    return count


def _isolate_filings(db: Database) -> None:
    """Each SEC filing is its own story. Boilerplate makes different 8-Ks look alike."""
    shared = db.conn.execute(
        """
        SELECT cluster_id FROM articles
        WHERE source = 'sec_edgar_8k' AND cluster_id IS NOT NULL
        GROUP BY cluster_id
        HAVING COUNT(*) > 1
        """
    ).fetchall()
    for row in shared:
        members = db.conn.execute(
            """
            SELECT id, published_at FROM articles
            WHERE cluster_id = ? AND source = 'sec_edgar_8k'
            """,
            (row["cluster_id"],),
        ).fetchall()
        for member in members:
            new_id = hashlib.sha256(member["id"].encode()).hexdigest()[:16]
            seen = member["published_at"]
            if not isinstance(seen, datetime):
                seen = datetime.fromisoformat(str(seen))
            db.upsert_cluster(new_id, member["id"], seen, 1, dropped=False)
            db.assign_cluster([member["id"]], new_id)
        left = db.conn.execute(
            "SELECT COUNT(*) AS n FROM articles WHERE cluster_id = ?",
            (row["cluster_id"],),
        ).fetchone()["n"]
        if left == 0:
            db.conn.execute("DELETE FROM cluster_entities WHERE cluster_id = ?", (row["cluster_id"],))
            db.conn.execute("DELETE FROM materiality WHERE cluster_id = ?", (row["cluster_id"],))
            db.conn.execute("DELETE FROM impacts WHERE cluster_id = ?", (row["cluster_id"],))
            db.conn.execute("DELETE FROM article_clusters WHERE cluster_id = ?", (row["cluster_id"],))
            db.conn.commit()


def _store_single_cluster(db, article, securities, relations, profiles) -> None:
    cluster_id = hashlib.sha256(article.id.encode()).hexdigest()[:16]
    low, reason = is_low_value(article.title, article.body, article.source)
    db.upsert_cluster(
        cluster_id,
        article.id,
        article.published_at,
        1,
        dropped=low,
        drop_reason=reason or None,
    )
    db.assign_cluster([article.id], cluster_id)
    if low:
        return
    db.replace_entities(
        cluster_id,
        link_entities(f"{article.title}. {article.body}", securities, relations, profiles),
    )


SCREENED_OUT = "Screened out before analysis: lower priority this week."
NO_MECHANISM = "No public company has a concrete revenue mechanism."
SELECTED = "Selected for news analysis."
MAX_CANDIDATES = 14
# Decisions from the pass that could name only S&P 500 companies.
_NARROW_REASONS = (
    "Screened out before analysis: no tracked company, industry, or macro force, or lower priority this week.",
    "No tracked company has a concrete revenue mechanism.",
)
_NARROW_MODEL = "ollama/qwen2.5:3b"
_NARROW_BEFORE = "2026-11-09T06:00:00"


def _select_stories(
    db: Database,
    securities: list[Security],
    limit: int,
    text_fetcher: Callable[[str], str] | None,
) -> None:
    """Rank pending stories and send the top ones to the model.

    Ranking is not a gate on its own: a story with no keyword hit can still be
    selected when there is room, and the model decides whether it reaches a company.
    """
    _isolate_filings(db)
    _reopen_narrow_company_pass(db)
    _refresh_links(db, securities, "Linking stories before choosing which ones to analyze.")
    ranked = []
    for row in db.pending_clusters():
        articles = db.articles_by_ids([row["representative_article_id"]])
        if not articles:
            continue
        article = articles[0]
        links = db.cluster_entities(row["cluster_id"])
        size = db.conn.execute(
            "SELECT COUNT(*) AS n FROM articles WHERE cluster_id = ?", (row["cluster_id"],)
        ).fetchone()["n"]
        score = story_priority(article.title, article.body, article.source, links, size)
        ranked.append((score, article.published_at, row["cluster_id"], article))
    ranked.sort(key=lambda item: (item[0], item[1]), reverse=True)
    print(f"Ranking {len(ranked)} stories. Up to {limit} will be analyzed.")
    selected = 0
    screened = 0
    for position, (score, _published, cluster_id, article) in enumerate(ranked):
        if position < limit and score > -2:
            if text_fetcher is not None and article.source != "sec_edgar_8k" and len(article.body) < 400:
                print(f"  reading article: {article.title[:90]}")
                text = text_fetcher(article.url)
                if len(text) > len(article.body):
                    db.update_article_body(article.id, text)
            db.save_materiality(cluster_id, True, "other", SELECTED, "", filter_version())
            print(f"Selected: {article.title[:90]}")
            selected += 1
        else:
            db.save_materiality(cluster_id, False, "other", SCREENED_OUT, "", filter_version())
            screened += 1
    print(f"Selected {selected} stories for analysis. Screened out {screened}.")


def _analyze(db: Database, router: Router, securities: list[Security], as_of: date) -> int:
    _refresh_links(db, securities, "Linking the selected stories before the model reads them.")
    universe = {security.ticker for security in securities}
    by_ticker = {security.ticker: security for security in securities}
    names = {security.ticker: security.name for security in securities}
    industries = sorted({security.industry for security in securities if security.industry})
    liquidity = db.liquidity()
    model = router.settings.llm_roles["analysis"].model
    embed_fn = industry_embedder(router)
    industry_cache: dict = {}
    written = 0
    cluster_ids = db.material_clusters_without_impacts()
    total = len(cluster_ids)
    print(f"Analyzing {total} stories with {model}.")
    for index, cluster_id in enumerate(cluster_ids, start=1):
        articles = _cluster_articles(db, cluster_id)
        if not articles:
            continue
        title = articles[0].title
        text = "\n".join(article.body for article in articles)
        named = mentioned_tickers(f"{title}. {text[:800]}", securities)
        named_names = [by_ticker[ticker].name for ticker in named if ticker in by_ticker]
        named_industries = [
            by_ticker[ticker].industry
            for ticker in named
            if ticker in by_ticker and by_ticker[ticker].industry
        ]
        shortlist = related_industries(
            title,
            text,
            industries,
            embed_fn,
            named_industries=named_industries,
            cache=industry_cache,
        )
        print(f"Mapping {index} of {total}: {title[:90]}")
        try:
            spread = map_propagation(
                router,
                cluster_id,
                title,
                text,
                industries,
                named_companies=named_names,
            )
        except (LLMResponseError, RuntimeError) as exc:
            print(f"  propagation skipped: {exc}"[:200])
            spread = ImpactMap(relevant=True, event_summary="", channels=[])
        if spread is None:
            print("  stopped: the model budget was reached.")
            break
        print(f"  spread: {len(spread.channels)} channels.")
        if spread.changed:
            print(f"  changed: {spread.changed}")
        resolved = resolve_channels(spread.channels, securities, liquidity) if spread.relevant else []
        if not resolved:
            resolved = resolve_channels(fallback_channels(shortlist[:2], title), securities, liquidity)
        if not spread.event_summary:
            spread.event_summary = title
        db.replace_channels(
            cluster_id,
            [
                (
                    item.channel.target,
                    item.channel.kind,
                    item.channel.order,
                    item.channel.relation,
                    item.channel.direction,
                    item.channel.mechanism,
                    ",".join(item.tickers),
                    model,
                    propagation_version(),
                )
                for item in resolved
            ],
        )
        if spread.event_summary:
            db.set_event_summary(cluster_id, spread.event_summary)

        candidates: dict[str, dict] = {}
        for ticker, link in db.cluster_entities(cluster_id):
            if ticker in universe and link == "mentioned":
                candidates[ticker] = {"order": 1, "relation": "direct", "why_included": "named in the article"}
        for item in resolved:
            for ticker in item.tickers:
                if ticker in universe and ticker not in candidates:
                    candidates[ticker] = {
                        "order": item.channel.order,
                        "relation": item.channel.relation,
                        "why_included": f"{item.channel.target}: {item.channel.mechanism}",
                    }
        for ticker, link in db.cluster_entities(cluster_id):
            if ticker in universe and ticker not in candidates:
                candidates[ticker] = {"order": 3, "relation": "macro_exposure", "why_included": link}
        ordered = _across_orders(candidates, MAX_CANDIDATES)
        if not ordered:
            print("  no company to score for this story.")
            db.save_materiality(cluster_id, False, "other", NO_MECHANISM, model, propagation_version())
            continue
        context = {ticker for ticker, _ in ordered}
        payload = {
            "cluster_id": cluster_id,
            "title": title,
            "body": text[:2500],
            "tickers": [ticker for ticker, _ in ordered],
            "candidates": [
                {
                    "ticker": ticker,
                    "name": by_ticker[ticker].name,
                    "industry": by_ticker[ticker].industry,
                    "order": info["order"],
                    "suggested_relation": info["relation"],
                    "why_included": info["why_included"],
                }
                for ticker, info in ordered
            ],
        }
        print(f"  impact on {len(ordered)} candidates: {', '.join(payload['tickers'])}")
        try:
            analysis = analyze_cluster(router, payload, universe=universe, context=context)
        except (LLMResponseError, RuntimeError) as exc:
            print(f"  impact skipped: {exc}"[:200])
            db.save_materiality(
                cluster_id,
                False,
                "other",
                f"Model response could not be parsed: {exc}"[:400],
                model,
                impact_version(),
            )
            continue
        if analysis is None:
            break
        if not spread.event_summary:
            db.set_event_summary(cluster_id, analysis.event_summary)
        directional = [impact for impact in analysis.impacts if impact.direction != "neutral"]
        kept = supported_impacts(directional, f"{title}. {text}", names)
        if not kept:
            print("  no concrete revenue mechanism.")
            db.save_materiality(cluster_id, False, "other", NO_MECHANISM, model, impact_version())
            continue
        print(f"  kept {len(kept)} impacts.")
        rows = [
            (
                cluster_id,
                impact.ticker,
                impact.relation,
                impact.direction,
                impact.affected_revenue_line,
                impact.est_revenue_impact_pct,
                impact.horizon,
                impact.confidence,
                impact.already_priced_in,
                _with_uncertainties(impact.reasoning, impact.key_uncertainties),
                router.settings.llm_roles["analysis"].model,
                impact_version(),
                datetime.now(timezone.utc).isoformat(),
            )
            for impact in kept
        ]
        db.save_impacts(rows)
        written += len(rows)
    return written


def _reopen_narrow_company_pass(db: Database) -> None:
    """Put stories judged only against S&P 500 companies back in the queue.

    Later runs match every story to the full US listing list. Ranked idea
    lists still use the S&P 500, because that is the universe with prices.
    """
    reason_ids = [
        row["cluster_id"]
        for row in db.conn.execute(
            f"SELECT cluster_id FROM materiality WHERE reason IN ({', '.join('?' for _ in _NARROW_REASONS)})",
            _NARROW_REASONS,
        )
    ]
    model_ids = [
        row["cluster_id"]
        for row in db.conn.execute(
            """
            SELECT DISTINCT cluster_id FROM impacts
            WHERE model = ? AND created_at < ?
            """,
            (_NARROW_MODEL, _NARROW_BEFORE),
        )
    ]
    cluster_ids = sorted(set(reason_ids) | set(model_ids))
    if not cluster_ids:
        return
    print(
        f"Returning {len(cluster_ids)} stories that were judged only against S&P 500 companies. "
        "This run matches them to all US-listed companies."
    )
    marks = [(cluster_id,) for cluster_id in cluster_ids]
    for table in ("impact_channels", "impacts", "materiality"):
        db.conn.executemany(f"DELETE FROM {table} WHERE cluster_id = ?", marks)
    db.conn.execute("DELETE FROM recommendations")
    db.conn.commit()


def _across_orders(candidates: dict[str, dict], limit: int) -> list[tuple[str, dict]]:
    """Keep a company from each step so the later affected chain is not cut off."""
    buckets: dict[int, list[tuple[str, dict]]] = {}
    for ticker, info in candidates.items():
        buckets.setdefault(int(info["order"]), []).append((ticker, info))
    ordered: list[tuple[str, dict]] = []
    while len(ordered) < limit and any(buckets.values()):
        for order in sorted(buckets):
            if not buckets[order]:
                continue
            ordered.append(buckets[order].pop(0))
            if len(ordered) >= limit:
                break
    return ordered


def _refresh_links(db: Database, securities: list[Security], reason: str) -> None:
    relations = db.all_relations()
    profiles = _profiles(db)
    rows = db.conn.execute("SELECT cluster_id FROM article_clusters WHERE dropped = 0").fetchall()
    total = len(rows)
    print(reason)
    if total == 0:
        print("  no stories to match.")
        return
    print(f"  {total} stories to match.")
    for index, row in enumerate(rows, start=1):
        articles = _cluster_articles(db, row["cluster_id"])
        text = "\n".join(f"{article.title}. {article.body}" for article in articles)
        db.replace_entities(row["cluster_id"], link_entities(text, securities, relations, profiles))
        if index == 1 or index % 25 == 0 or index == total:
            print(f"  linked {index} of {total} stories.")


def _score(db: Database, settings: Settings, securities: list[Security], as_of: date) -> list[ScoreRecord]:
    print(f"Scoring {len(securities)} S&P companies.")
    if not securities:
        return []
    sectors = {security.ticker: security.sector or "Unknown" for security in securities}
    pes = {security.ticker: _pe(db, security.ticker) for security in securities}
    medians: dict[str, float | None] = {}
    for sector in set(sectors.values()):
        peer = [pes[ticker] for ticker, name in sectors.items() if name == sector and pes[ticker] and pes[ticker] > 0]
        medians[sector] = None if not peer else sorted(peer)[len(peer) // 2]
    factors = {}
    for security in securities:
        quality = quality_raw(db.fundamentals_for(security.ticker))
        stats = _stats_row(db, security.ticker, as_of)
        frame = db.load_prices([security.ticker])
        technical = _EMPTY_TECHNICAL
        if not frame.empty:
            from stock_agent.analysis.price_stats import close_series

            technical = compute_technical(close_series(frame))
        valuation = value_raw(pes[security.ticker], medians.get(sectors[security.ticker]))
        factors[security.ticker] = {
            "quality": 0.0 if quality is None else quality,
            "value": 0.0 if valuation is None else valuation,
            "technical": technical_raw(technical),
            "risk": risk_raw(
                None if stats is None else stats["vol_full"],
                None if stats is None else stats["max_drawdown"],
            ),
        }
    scores = build_scores(
        [security.ticker for security in securities],
        sectors,
        db.load_impacts(),
        factors,
        settings.score_weights,
        settings.decay_days,
        as_of,
    )
    db.upsert_scores(scores)
    print(f"Scored {len(scores)} companies.")
    return scores


def _lists(db, settings, securities, scores, as_of):
    previous_week = as_of - timedelta(days=7)
    previous = {row.ticker: row.composite for row in db.scores_for(previous_week)}
    raw_quality = {security.ticker: quality_raw(db.fundamentals_for(security.ticker)) for security in securities}
    return rank_lists(
        scores,
        raw_quality,
        {security.ticker: security.sector or "Unknown" for security in securities},
        previous,
        settings.score_weights,
        settings.top_n,
    )


def _theses(db, router, lists, as_of, names: dict[str, str]) -> dict[str, tuple[str, str]]:
    if db.recommendations_for(as_of):
        print("Theses for this week are already written.")
        return {
            row["ticker"]: (row["thesis"] or "", row["risks"] or "")
            for row in db.recommendations_for(as_of)
        }
    impacts = db.load_impacts()
    written: dict[str, tuple[str, str]] = {}
    seen: set[str] = set()
    for name in ("long", "mid", "risk"):
        for row in lists[name]:
            if row.ticker in seen:
                continue
            seen.add(row.ticker)
            company = names.get(row.ticker, row.ticker)
            print(f"Thesis: {row.ticker} {company}")
            effects = [
                impact
                for impact in impacts
                if impact["ticker"] == row.ticker and impact["direction"] != "neutral"
            ]
            logic = " ".join(impact["reasoning"] for impact in effects if impact.get("reasoning"))
            result = write_thesis(
                router,
                {
                    "ticker": row.ticker,
                    "company_name": company,
                    "list": name,
                    "news_effects": [
                        {
                            "headline": impact.get("title"),
                            "relation": impact["relation"],
                            "direction": impact["direction"],
                            "horizon": impact["horizon"],
                            "revenue_line": impact["revenue_line"],
                            "est_pct": impact["est_pct"],
                            "reasoning": impact["reasoning"],
                        }
                        for impact in effects
                    ],
                    "price_history": _price_lines(db, row.ticker, as_of),
                    "week_ending": as_of.isoformat(),
                },
            )
            if result is None:
                note = "Thesis skipped: weekly LLM budget reached."
                written[row.ticker] = (f"{logic} {note}".strip(), "")
                return written
            assessment = result.thesis or ""
            if _about_this_company(assessment, row.ticker, company) and not _mentions_other_company(
                assessment, row.ticker, company, names
            ):
                thesis = f"{logic} Assessment: {assessment}".strip()
                risks = " ".join(result.risks + [result.bear_case, result.invalidation])
            else:
                thesis = logic
                risks = ""
            written[row.ticker] = (thesis, risks)
    return written


def _save_recommendations(db, as_of, lists, theses) -> None:
    rows = []
    for name in ("long", "mid", "risk"):
        for rank, row in enumerate(lists[name], start=1):
            thesis, risks = theses.get(row.ticker, ("", ""))
            rows.append((as_of.isoformat(), row.ticker, name, rank, thesis, risks))
    db.replace_recommendations(as_of, rows)


def _llm_configured(settings: Settings) -> bool:
    for name in ("filter", "analysis", "thesis"):
        role = settings.llm_roles.get(name)
        if role is None or "<" in role.model or not role.model.strip():
            return False
    return True


def _report(settings, db, securities, lists, theses, as_of, render_charts, notes: list[str] | None = None) -> EmailReport:
    names = {security.ticker: security.name for security in securities}
    impacts = db.load_impacts()
    highlighted = []
    for name in ("long", "mid", "risk"):
        highlighted.extend(lists[name])
    unique = []
    seen = set()
    for row in highlighted:
        if row.ticker not in seen:
            seen.add(row.ticker)
            unique.append(row)
    chart_files: dict[str, Path] = {}
    pdf_path = None
    if render_charts and unique:
        print(f"Drawing price charts for {len(unique)} companies.")
        chart_files, pdf_path = _charts(settings, db, unique, names, as_of)
    prior = _prior_tickers(db, as_of)
    current_ids = {row.ticker for row in lists["long"] + lists["mid"]}
    changes = [f"{ticker} entered the lists." for ticker in sorted(current_ids - prior)]
    changes.extend(f"{ticker} left the lists." for ticker in sorted(prior - current_ids))

    def highlights(rows, list_name):
        built = []
        for rank, row in enumerate(rows, start=1):
            thesis, risks = theses.get(row.ticker, ("", ""))
            net = row.net_revenue_long if list_name != "mid" else row.net_revenue_mid
            built.append(
                Highlight(
                    ticker=row.ticker,
                    name=names.get(row.ticker, row.ticker),
                    list_name=list_name,
                    rank=rank,
                    composite=row.composite,
                    net_revenue=net,
                    thesis=thesis,
                    risks=risks,
                    links=_links(impacts, row.ticker),
                    chart_cid=f"chart-{row.ticker}" if f"chart-{row.ticker}" in chart_files else None,
                    price_lines=_price_lines(db, row.ticker, as_of),
                )
            )
        return built

    spend_week = db.llm_spend_since(datetime.now(timezone.utc) - timedelta(days=7))
    spend_month = db.llm_spend_since(datetime.now(timezone.utc) - timedelta(days=30))
    metrics = db.metrics_for(as_of)
    stories = _stories(db, names)
    review = []
    for story in stories:
        if not story.effects:
            continue
        who = ", ".join(f"{effect.ticker} {effect.direction}" for effect in story.effects)
        review.append(f"{story.title} — {who}.")
    if not review:
        review = ["No story produced a concrete company effect."]
    return EmailReport(
        week_ending=as_of,
        new_idea_count=len(current_ids - prior),
        risk_count=len(lists["risk"]),
        week_in_review=review,
        stories=stories,
        long_ideas=highlights(lists["long"], "long"),
        mid_ideas=highlights(lists["mid"], "mid"),
        changes=changes,
        risks=highlights(lists["risk"], "risk"),
        track_record=[f"{row['metric']} ({row['horizon']}): {row['value']:.3f}" for row in metrics] or ["No completed forward window yet."],
        health=[
            *(notes or []),
            f"LLM spend this week ${spend_week:.2f} of ${settings.weekly_budget_usd:.2f}.",
            f"LLM spend month-to-date ${spend_month:.2f} of ${settings.monthly_budget_usd:.2f}.",
        ],
        recipients=settings.recipients,
        other_story_count=_unlinked_count(db),
        pdf_path=pdf_path,
        chart_files=chart_files,
    )


def _charts(settings, db, rows, names, as_of):
    specs = []
    for row in rows:
        frame = db.load_prices([row.ticker])
        if frame.empty:
            continue
        specs.append(ChartSpec(ticker=row.ticker, name=names.get(row.ticker, row.ticker), prices=frame))
    if not specs:
        return {}, None
    dest = settings.root / "output" / "charts" / as_of.isoformat()
    pngs, pdf = render_price_charts(
        specs,
        dest_dir=dest,
        years=settings.chart_years,
        moving_averages=settings.moving_averages,
        show_event_markers=settings.show_event_markers,
        show_benchmark_panel=settings.show_benchmark_panel,
    )
    files = {f"chart-{spec.ticker}": path for spec, path in zip(specs, pngs)}
    return files, pdf


def _deliver(db, settings, report, notifier) -> str:
    if notifier is None:
        notifier = EmailNotifier()
    if not report.recipients or report.recipients == ["you@example.com"]:
        db.record_report(report.week_ending, report.recipients, "not_configured", None)
        return "not_configured"
    try:
        message_id = notifier.send(report)
    except MissingSMTP:
        db.record_report(report.week_ending, report.recipients, "not_configured", None)
        return "not_configured"
    db.record_report(report.week_ending, report.recipients, "sent", message_id)
    return "sent"


def _evaluate(db: Database, as_of: date) -> dict[str, float]:
    row = db.conn.execute(
        """
        SELECT DISTINCT week_ending FROM scores_weekly
        WHERE week_ending < ? ORDER BY week_ending DESC LIMIT 1
        """,
        (as_of.isoformat(),),
    ).fetchone()
    if row is None:
        return {}
    start = date.fromisoformat(row["week_ending"])
    scores = {item.ticker: item.composite for item in db.scores_for(start)}
    returns = {}
    for ticker in scores:
        value = _price_return(db, ticker, start, as_of)
        if value is not None:
            returns[ticker] = value
    metrics = {}
    ic = rank_ic(scores, returns)
    spread = quintile_spread(scores, returns)
    paper = period_return(scores, returns)
    if ic is not None:
        metrics["forward:rank_ic"] = ic
    if spread is not None:
        metrics["forward:quintile_spread"] = spread
    if paper is not None:
        metrics["forward:paper_portfolio"] = paper
    return metrics


def _price_return(db, ticker, start, end) -> float | None:
    rows = db.conn.execute(
        """
        SELECT adj_close, close FROM prices
        WHERE ticker = ? AND date >= ? AND date <= ?
        ORDER BY date
        """,
        (ticker, start.isoformat(), end.isoformat()),
    ).fetchall()
    if len(rows) < 2:
        return None
    first = rows[0]["adj_close"] or rows[0]["close"]
    last = rows[-1]["adj_close"] or rows[-1]["close"]
    if not first:
        return None
    return float(last) / float(first) - 1.0


def _pe(db: Database, ticker: str) -> float | None:
    price = db.conn.execute(
        "SELECT close FROM prices WHERE ticker = ? ORDER BY date DESC LIMIT 1",
        (ticker,),
    ).fetchone()
    fundamentals = db.fundamentals_for(ticker)
    eps = fundamentals[-1].eps if fundamentals else None
    if price and price["close"] and eps and eps > 0:
        return float(price["close"]) / eps
    return None


def _stats_row(db, ticker, as_of):
    return db.conn.execute(
        "SELECT * FROM price_stats_weekly WHERE week_ending = ? AND ticker = ?",
        (as_of.isoformat(), ticker),
    ).fetchone()


def _stats_dict(db, tickers, as_of) -> dict:
    payload = {}
    for ticker in tickers:
        row = _stats_row(db, ticker, as_of)
        if row is not None:
            payload[ticker] = {
                "ret_1y": row["ret_1y"],
                "ret_3y": row["ret_3y"],
                "max_drawdown": row["max_drawdown"],
                "current_drawdown": row["current_drawdown"],
                "vol_full": row["vol_full"],
            }
    return payload


def _profile_dict(db, ticker) -> dict:
    profile = db.get_profile(ticker)
    if profile is None:
        return {"ticker": ticker}
    return {
        "ticker": ticker,
        "summary": profile.summary,
        "segments": profile.segments,
        "regions": profile.regions,
        "sensitivities": profile.sensitivities,
    }


def _cluster_articles(db, cluster_id):
    rows = db.conn.execute(
        "SELECT id FROM articles WHERE cluster_id = ? ORDER BY published_at",
        (cluster_id,),
    ).fetchall()
    return db.articles_by_ids([row["id"] for row in rows])


def _with_uncertainties(reasoning: str, uncertainties: list[str]) -> str:
    text = (reasoning or "").strip()
    extra = [item.strip() for item in uncertainties if item and item.strip()]
    if extra:
        text = f"{text} Uncertainties: {'; '.join(extra)}."
    return text


def _about_this_company(text: str, ticker: str, name: str) -> bool:
    if ticker in text:
        return True
    first = name.split()[0] if name else ""
    return len(first) >= 4 and first.lower() in text.lower()


def _mentions_other_company(text: str, ticker: str, name: str, names: dict[str, str]) -> bool:
    for other, other_name in names.items():
        if other == ticker:
            continue
        if re.search(rf"\b{re.escape(other)}\b", text):
            return True
        token = other_name.split()[0] if other_name else ""
        if len(token) >= 5 and token.lower() not in name.lower() and re.search(rf"\b{re.escape(token)}\b", text):
            return True
    return False


def _unlinked_count(db: Database) -> int:
    row = db.conn.execute(
        """
        SELECT COUNT(*) AS n FROM materiality
        WHERE reason = ?
        """,
        (SCREENED_OUT,),
    ).fetchone()
    return int(row["n"])


def _stories(db: Database, names: dict[str, str]) -> list[AnalyzedStory]:
    impacts = db.load_impacts()
    by_cluster: dict[str, list[dict]] = {}
    for impact in impacts:
        if impact["direction"] == "neutral":
            continue
        by_cluster.setdefault(impact["cluster_id"], []).append(impact)
    stories: list[AnalyzedStory] = []
    for row in db.analyzed_stories():
        effects = []
        for impact in by_cluster.get(row["cluster_id"], []):
            effects.append(
                CompanyEffect(
                    ticker=impact["ticker"],
                    name=names.get(impact["ticker"], impact["ticker"]),
                    relation=impact["relation"],
                    direction=impact["direction"],
                    horizon=impact["horizon"],
                    revenue_line=impact["revenue_line"] or "",
                    est_pct=float(impact["est_pct"] or 0.0),
                    confidence=float(impact["confidence"] or 0.0),
                    priced_in=impact["priced_in"] or "",
                    reasoning=impact["reasoning"] or "",
                )
            )
        channels = db.channels_for(row["cluster_id"])
        steps = [
            SpreadStep(
                order=int(channel["ord"]),
                target=channel["target"],
                relation=channel["relation"],
                direction=channel["direction"],
                mechanism=channel["mechanism"],
                tickers=[ticker for ticker in channel["tickers"].split(",") if ticker],
            )
            for channel in channels
        ]
        considered = [
            (ticker, names.get(ticker, ticker), link)
            for ticker, link in db.cluster_entities(row["cluster_id"])
            if link == "mentioned"
        ]
        seen = {ticker for ticker, _name, _link in considered}
        for step in steps:
            for ticker in step.tickers:
                if ticker not in seen:
                    seen.add(ticker)
                    considered.append((ticker, names.get(ticker, ticker), f"order{step.order}"))
        stories.append(
            AnalyzedStory(
                title=row["title"] or row["summary"] or "Untitled",
                url=row["url"] or "",
                summary=row["summary"] or row["title"] or "",
                effects=effects,
                considered=considered,
                steps=steps,
            )
        )
    stories.sort(key=lambda story: (not story.effects, story.title))
    return stories


def _links(impacts, ticker) -> list[tuple[str, str]]:
    found = []
    for impact in impacts:
        if impact["ticker"] == ticker and impact.get("url"):
            found.append((impact.get("title") or impact["url"], impact["url"]))
    return found[:5]


def _price_lines(db, ticker, as_of) -> list[str]:
    row = _stats_row(db, ticker, as_of)
    if row is None:
        return []
    def pct(value):
        return "n/a" if value is None else f"{value:+.1%}"
    return [
        f"1-year return {pct(row['ret_1y'])}",
        f"3-year return {pct(row['ret_3y'])}",
        f"Max drawdown {pct(row['max_drawdown'])}",
        f"Volatility {pct(row['vol_full'])}",
    ]


def _prior_tickers(db, as_of) -> set[str]:
    row = db.conn.execute(
        """
        SELECT DISTINCT week_ending FROM recommendations
        WHERE week_ending < ? ORDER BY week_ending DESC LIMIT 1
        """,
        (as_of.isoformat(),),
    ).fetchone()
    if row is None:
        return set()
    return {item["ticker"] for item in db.recommendations_for(date.fromisoformat(row["week_ending"]))}


def _step(db, as_of, step, status, now) -> None:
    db.mark_step(as_of, step, status, now)
