"""Weekly HTML report with a plain-text fallback and inline chart ids."""

from __future__ import annotations

import html
import os
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

DISCLAIMER = (
    "This report is a research aid, not financial advice. "
    "Review every idea before making an investment decision."
)


RELATION_LABEL = {
    "direct": "the story is about this company",
    "competitor": "a rival of the company in the story",
    "supplier": "a supplier to the company in the story",
    "customer": "a customer of the company in the story",
    "macro_exposure": "exposed to the same industry force",
}
HORIZON_LABEL = {"mid": "6–18 months", "long": "2–5 years"}
LINK_LABEL = {
    "mentioned": "named in the story",
    "expanded": "known supplier, customer, or competitor",
    "exposure": "same industry or the same macro force",
    "order1": "directly affected",
    "order2": "competitor, supplier, customer, or substitute",
    "order3": "wider ripple through prices, costs, rates, or demand",
}
ORDER_LABEL = {1: "Direct", 2: "Second order", 3: "Ripple"}


@dataclass
class SpreadStep:
    order: int
    target: str
    relation: str
    direction: str
    mechanism: str
    tickers: list[str] = field(default_factory=list)


@dataclass
class CompanyEffect:
    ticker: str
    name: str
    relation: str
    direction: str
    horizon: str
    revenue_line: str
    est_pct: float
    confidence: float
    priced_in: str
    reasoning: str


@dataclass
class AnalyzedStory:
    title: str
    url: str
    summary: str
    effects: list[CompanyEffect] = field(default_factory=list)
    considered: list[tuple[str, str, str]] = field(default_factory=list)
    steps: list[SpreadStep] = field(default_factory=list)


@dataclass
class Highlight:
    ticker: str
    name: str
    list_name: str
    rank: int
    composite: float
    net_revenue: float | None
    thesis: str
    risks: str
    links: list[tuple[str, str]] = field(default_factory=list)
    chart_cid: str | None = None
    price_lines: list[str] = field(default_factory=list)


@dataclass
class EmailReport:
    week_ending: date
    new_idea_count: int
    risk_count: int
    week_in_review: list[str]
    long_ideas: list[Highlight]
    mid_ideas: list[Highlight]
    changes: list[str]
    risks: list[Highlight]
    track_record: list[str]
    health: list[str]
    recipients: list[str]
    stories: list[AnalyzedStory] = field(default_factory=list)
    other_story_count: int = 0
    pdf_path: Path | None = None
    chart_files: dict[str, Path] = field(default_factory=dict)


def subject_line(report: EmailReport) -> str:
    return (
        f"Stock Agent — week ending {report.week_ending.isoformat()} — "
        f"{report.new_idea_count} new ideas, {report.risk_count} risk alerts"
    )


def render_html(report: EmailReport, *, html_path: Path | None = None) -> str:
    parts = [
        "<html><body>",
        f"<h1>{html.escape(subject_line(report))}</h1>",
        _stories(report.stories, report.other_story_count),
        _section("Week in review", report.week_in_review),
        _ideas("Top long-term ideas", report.long_ideas),
        _ideas("Top mid-term ideas", report.mid_ideas),
        _section("What changed this week", report.changes),
        _ideas("Risk alerts", report.risks),
        _details(report.long_ideas + report.mid_ideas + report.risks, report, html_path),
        _section("Track record", report.track_record),
        _section("Agent health", report.health),
        f"<p><em>{html.escape(DISCLAIMER)}</em></p>",
        "</body></html>",
    ]
    return "\n".join(parts)


def render_text(report: EmailReport) -> str:
    lines = [subject_line(report), ""]
    lines.append("News analyzed")
    if not report.stories:
        lines.append("- No news was analyzed this week.")
    for story in report.stories:
        lines.append(f"- {story.title}")
        for step in story.steps:
            label = ORDER_LABEL.get(step.order, f"Order {step.order}")
            lines.append(f"  {label}: {step.target} ({step.direction}) {step.mechanism}")
        for effect in story.effects:
            lines.append(
                f"  {effect.ticker} {effect.direction} via {effect.relation}: {effect.reasoning}"
            )
        if not story.effects:
            lines.append("  No concrete effect on a public company.")
    lines.append("")
    lines.append("Week in review")
    lines.extend(f"- {item}" for item in report.week_in_review)
    lines.append("")
    lines.append(DISCLAIMER)
    return "\n".join(lines)


def _stories(stories: list[AnalyzedStory], other_story_count: int = 0) -> str:
    blocks = ["<h2>News analyzed</h2>"]
    detailed = [story for story in stories if story.effects]
    quiet = [story for story in stories if not story.effects]
    if not stories:
        blocks.append("<p>No news was analyzed this week.</p>")
        return "\n".join(blocks)
    if not detailed:
        blocks.append("<p>No analyzed story produced a concrete revenue effect on a public company.</p>")
    for story in detailed:
        headline = html.escape(story.title)
        if story.url:
            headline = f'<a href="{html.escape(story.url)}">{headline}</a>'
        considered = "".join(
            f"<li>{html.escape(name)} ({html.escape(ticker)}) — {html.escape(LINK_LABEL.get(link, link))}</li>"
            for ticker, name, link in story.considered
        )
        effects = "".join(_effect(effect) for effect in story.effects)
        spread = ""
        if story.steps:
            steps = "".join(_step(step) for step in story.steps)
            spread = f"<p><strong>How the effect spreads</strong></p><ul>{steps}</ul>"
        blocks.append(
            f"<h3>{headline}</h3>"
            f"<p>{html.escape(story.summary)}</p>"
            f"{spread}"
            f"<p><strong>Companies considered</strong></p><ul>{considered or '<li>None.</li>'}</ul>"
            f"<p><strong>How the news affects them</strong></p><ul>{effects}</ul>"
        )
    if quiet:
        items = "".join(
            f"<li>{html.escape(story.title)}</li>" for story in quiet
        )
        blocks.append(
            "<h3>Reviewed, with no concrete effect on a public company</h3>"
            f"<ul>{items}</ul>"
        )
    if other_story_count:
        blocks.append(
            f"<p>{other_story_count} other stories were screened out before analysis "
            "(lower priority this week).</p>"
        )
    return "\n".join(blocks)


def _step(step: SpreadStep) -> str:
    label = ORDER_LABEL.get(step.order, f"Order {step.order}")
    reached = ", ".join(step.tickers)
    return (
        "<li>"
        f"<strong>{html.escape(label)}</strong> — {html.escape(step.target)} "
        f"({html.escape(step.relation)}, {html.escape(step.direction)}): "
        f"{html.escape(step.mechanism)}"
        f"{f' Tracked companies: {html.escape(reached)}.' if reached else ''}"
        "</li>"
    )


def _effect(effect: CompanyEffect) -> str:
    relation = RELATION_LABEL.get(effect.relation, effect.relation)
    horizon = HORIZON_LABEL.get(effect.horizon, effect.horizon)
    return (
        "<li>"
        f"<strong>{html.escape(effect.name)} ({html.escape(effect.ticker)})</strong> — "
        f"{html.escape(effect.direction)}, {html.escape(horizon)}, {html.escape(relation)}. "
        f"Revenue line: {html.escape(effect.revenue_line)}. "
        f"Estimated impact: {effect.est_pct:+.1f}%. "
        f"Confidence: {effect.confidence:.2f}. "
        f"Already in the price: {html.escape(effect.priced_in)}. "
        f"<br>Logic: {html.escape(effect.reasoning)}"
        "</li>"
    )


def _chart_src(cid: str, report: EmailReport, html_path: Path | None) -> str:
    """Email uses a cid: attachment. A saved HTML file points at the PNG on disk."""
    path = report.chart_files.get(cid)
    if html_path is None or path is None:
        return f"cid:{cid}"
    return Path(os.path.relpath(path, html_path.parent)).as_posix()


def _section(title: str, bullets: list[str]) -> str:
    items = "".join(f"<li>{html.escape(item)}</li>" for item in bullets) or "<li>None this week.</li>"
    return f"<h2>{html.escape(title)}</h2><ul>{items}</ul>"


def _ideas(title: str, rows: list[Highlight]) -> str:
    if not rows:
        return f"<h2>{html.escape(title)}</h2><p>None this week.</p>"
    body = "".join(
        "<tr>"
        f"<td>{html.escape(row.ticker)}</td>"
        f"<td>{html.escape(row.name)}</td>"
        f"<td>{row.composite:.2f}</td>"
        f"<td>{'' if row.net_revenue is None else f'{row.net_revenue:.1f}%'}</td>"
        f"<td>{html.escape(row.thesis)}</td>"
        "</tr>"
        for row in rows
    )
    return (
        f"<h2>{html.escape(title)}</h2>"
        "<table><tr><th>Ticker</th><th>Company</th><th>Score</th>"
        "<th>Net revenue impact</th><th>Why the news matters</th></tr>"
        f"{body}</table>"
    )


def _details(rows: list[Highlight], report: EmailReport, html_path: Path | None) -> str:
    blocks = ["<h2>Idea details</h2>"]
    seen: set[str] = set()
    for row in rows:
        if row.ticker in seen:
            continue
        seen.add(row.ticker)
        image = ""
        if row.chart_cid:
            image = (
                f'<img src="{html.escape(_chart_src(row.chart_cid, report, html_path))}" '
                f'alt="{html.escape(row.ticker)} chart" style="max-width:720px"/>'
            )
        history = "".join(f"<li>{html.escape(line)}</li>" for line in row.price_lines)
        links = "".join(
            f'<li><a href="{html.escape(url)}">{html.escape(title)}</a></li>' for title, url in row.links
        )
        blocks.append(
            f"<h3>{html.escape(row.name)} ({html.escape(row.ticker)})</h3>{image}"
            f"<ul>{history}</ul><p>{html.escape(row.thesis)}</p>"
            f"<p>{html.escape(row.risks)}</p><ul>{links}</ul>"
        )
    return "\n".join(blocks)
