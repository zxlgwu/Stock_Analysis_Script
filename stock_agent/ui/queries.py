"""Read-only views over the stock-agent database and chart files."""

from __future__ import annotations

import re
from datetime import date
from pathlib import Path

from stock_agent.db.repository import Database
from stock_agent.report.email_report import HORIZON_LABEL, ORDER_LABEL, RELATION_LABEL

_WEEK = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_PNG = re.compile(r"^[A-Za-z0-9_\-]+\.png$")
_CLUSTER = re.compile(r"^[a-fA-F0-9]{8,64}$")


def week_payload(db: Database) -> dict:
    impacts = db.load_impacts()
    by_cluster: dict[str, list[dict]] = {}
    for impact in impacts:
        by_cluster.setdefault(impact["cluster_id"], []).append(impact)
    stories = []
    for row in db.analyzed_stories():
        cluster_impacts = by_cluster.get(row["cluster_id"], [])
        effects = [item for item in cluster_impacts if item.get("direction") != "neutral"]
        published = [item.get("published_at") for item in cluster_impacts if item.get("published_at")]
        stories.append(
            {
                "cluster_id": row["cluster_id"],
                "title": row["title"] or row["summary"] or "Untitled",
                "summary": row["summary"] or "",
                "url": row["url"] or "",
                "effect_count": len(effects),
                "published_at": max(published) if published else None,
            }
        )
    stories.sort(key=lambda story: (story["effect_count"] == 0, story["title"]))
    return {"week_ending": latest_week(db), "stories": stories}


def story_payload(db: Database, cluster_id: str) -> dict | None:
    if not _CLUSTER.match(cluster_id or ""):
        return None
    row = next((item for item in db.analyzed_stories() if item["cluster_id"] == cluster_id), None)
    if row is None:
        return None
    impacts = [item for item in db.load_impacts() if item["cluster_id"] == cluster_id]
    tickers = sorted({item["ticker"] for item in impacts})
    names = _names(db, tickers)
    effects = [_effect(item, names) for item in impacts if item.get("direction") != "neutral"]
    return {
        "cluster_id": cluster_id,
        "title": row["title"] or row["summary"] or "Untitled",
        "summary": row["summary"] or "",
        "url": row["url"] or "",
        "steps": _steps(db.channels_for(cluster_id)),
        "effects": effects,
    }


def ideas_payload(db: Database, charts_dir: Path) -> dict:
    week = latest_week(db)
    grouped = {"long": [], "mid": [], "risk": []}
    if week is None:
        return {"week_ending": None, "long": [], "mid": [], "risk": []}
    day = date.fromisoformat(week)
    recommendations = db.recommendations_for(day)
    scores = {item.ticker: item for item in db.scores_for(day)}
    names = _names(db, [row["ticker"] for row in recommendations])
    for row in recommendations:
        list_name = row["list_name"]
        if list_name not in grouped:
            continue
        score = scores.get(row["ticker"])
        composite = None if score is None else score.composite
        net = None
        if score is not None:
            net = score.net_revenue_mid if list_name == "mid" else score.net_revenue_long
        grouped[list_name].append(
            {
                "ticker": row["ticker"],
                "name": names.get(row["ticker"], row["ticker"]),
                "rank": row["rank"],
                "thesis": row["thesis"] or "",
                "risks": row["risks"] or "",
                "composite": composite,
                "net_revenue": net,
                "composite_display": "n/a" if composite is None else f"{composite:.2f}",
                "net_revenue_display": "n/a" if net is None else f"{net:+.1f}%",
                "chart_url": chart_url(charts_dir, row["ticker"], week),
            }
        )
    return {"week_ending": week, **grouped}


def search_companies(db: Database, query: str, limit: int = 15) -> list[dict]:
    text = (query or "").strip()
    if not text:
        return []
    escaped = text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    like = f"%{escaped}%"
    prefix = f"{escaped}%"
    rows = db.conn.execute(
        """
        SELECT ticker, name, sector, industry
        FROM companies
        WHERE ticker LIKE ? ESCAPE '\\' OR name LIKE ? ESCAPE '\\'
        ORDER BY
            CASE
                WHEN ticker = ? COLLATE NOCASE THEN 0
                WHEN ticker LIKE ? ESCAPE '\\' THEN 1
                ELSE 2
            END,
            ticker
        LIMIT ?
        """,
        (like, like, text, prefix, limit),
    ).fetchall()
    return [
        {
            "ticker": row["ticker"],
            "name": row["name"] or row["ticker"],
            "sector": row["sector"] or "",
            "industry": row["industry"] or "",
        }
        for row in rows
    ]


def company_payload(db: Database, charts_dir: Path, ticker: str) -> dict | None:
    security = _security(db, ticker)
    if security is None:
        return None
    impacts = [item for item in db.load_impacts() if item["ticker"] == security.ticker]
    impacts.sort(key=lambda item: item.get("published_at") or "", reverse=True)
    effects = [_effect(item, {security.ticker: security.name}) for item in impacts if item.get("direction") != "neutral"]
    week = latest_week(db)
    stats = _price_stats(db, security.ticker)
    return {
        "ticker": security.ticker,
        "name": security.name,
        "exchange": security.exchange,
        "sector": security.sector or "",
        "industry": security.industry or "",
        "impacts": effects[:40],
        "price_stats": stats,
        "price_lines": _price_lines(stats),
        "chart_url": chart_url(charts_dir, security.ticker, week),
        "week_ending": week,
    }


def chart_file(charts_dir: Path, week: str, filename: str) -> Path | None:
    if not _WEEK.match(week or "") or not _PNG.match(filename or ""):
        return None
    root = charts_dir.resolve()
    path = (charts_dir / week / filename).resolve()
    if not path.is_relative_to(root) or not path.is_file():
        return None
    return path


def chart_url(charts_dir: Path, ticker: str, preferred_week: str | None) -> str | None:
    filename = f"{ticker.replace('.', '_')}.png"
    if not _PNG.match(filename):
        return None
    if preferred_week and chart_file(charts_dir, preferred_week, filename) is not None:
        return f"/charts/{preferred_week}/{filename}"
    if not charts_dir.is_dir():
        return None
    weeks = sorted((path.name for path in charts_dir.iterdir() if path.is_dir()), reverse=True)
    for week in weeks:
        if chart_file(charts_dir, week, filename) is not None:
            return f"/charts/{week}/{filename}"
    return None


def latest_week(db: Database) -> str | None:
    for table in ("recommendations", "scores_weekly"):
        row = db.conn.execute(f"SELECT MAX(week_ending) AS week FROM {table}").fetchone()
        if row and row["week"]:
            return row["week"]
    return None


def _security(db: Database, ticker: str):
    text = (ticker or "").strip()
    if not text:
        return None
    direct = db.get_companies([text.upper()])
    if text.upper() in direct:
        return direct[text.upper()]
    row = db.conn.execute(
        "SELECT ticker FROM companies WHERE ticker = ? COLLATE NOCASE",
        (text,),
    ).fetchone()
    if row is None:
        return None
    found = db.get_companies([row["ticker"]])
    return found.get(row["ticker"])


def _names(db: Database, tickers: list[str]) -> dict[str, str]:
    if not tickers:
        return {}
    return {ticker: security.name for ticker, security in db.get_companies(tickers).items()}


def _effect(impact: dict, names: dict[str, str]) -> dict:
    est = float(impact["est_pct"] or 0.0)
    confidence = float(impact["confidence"] or 0.0)
    relation = impact.get("relation") or ""
    horizon = impact.get("horizon") or ""
    return {
        "ticker": impact["ticker"],
        "name": names.get(impact["ticker"], impact["ticker"]),
        "relation": relation,
        "relation_label": RELATION_LABEL.get(relation, relation),
        "direction": impact.get("direction") or "",
        "horizon": horizon,
        "horizon_label": HORIZON_LABEL.get(horizon, horizon),
        "revenue_line": impact.get("revenue_line") or "",
        "est_pct": est,
        "estimated_impact": f"{est:+.1f}%",
        "confidence": confidence,
        "priced_in": impact.get("priced_in") or "",
        "reasoning": impact.get("reasoning") or "",
        "source_url": impact.get("url") or "",
        "source_title": impact.get("title") or "Source",
    }


def _steps(channels: list[dict]) -> list[dict]:
    steps = []
    for channel in channels:
        order = int(channel["ord"])
        tickers = [part for part in str(channel.get("tickers") or "").split(",") if part]
        steps.append(
            {
                "order": order,
                "label": ORDER_LABEL.get(order, f"Order {order}"),
                "target": channel.get("target") or "",
                "relation": channel.get("relation") or "",
                "direction": channel.get("direction") or "",
                "mechanism": channel.get("mechanism") or "",
                "tickers": tickers,
            }
        )
    return steps


def _price_stats(db: Database, ticker: str) -> dict | None:
    row = db.conn.execute(
        """
        SELECT week_ending, ret_1y, ret_3y, ret_5y, cagr,
               rel_spy_1y, rel_spy_3y, rel_spy_5y,
               rel_sector_1y, max_drawdown, current_drawdown,
               vol_1y, vol_full
        FROM price_stats_weekly
        WHERE ticker = ?
        ORDER BY week_ending DESC
        LIMIT 1
        """,
        (ticker,),
    ).fetchone()
    if row is None:
        return None
    return {key: row[key] for key in row.keys()}


def _price_lines(stats: dict | None) -> list[dict]:
    if not stats:
        return []
    labels = (
        ("ret_1y", "1-year return"),
        ("ret_3y", "3-year return"),
        ("ret_5y", "5-year return"),
        ("cagr", "CAGR"),
        ("rel_spy_1y", "Versus SPY, 1 year"),
        ("max_drawdown", "Max drawdown"),
        ("current_drawdown", "Current drawdown"),
        ("vol_1y", "1-year volatility"),
        ("vol_full", "Full-period volatility"),
    )
    return [{"label": label, "value": _fraction(stats.get(key))} for key, label in labels]


def _fraction(value: object) -> str:
    if value is None:
        return "n/a"
    pct = float(value) * 100.0
    sign = "+" if pct > 0 else ""
    return f"{sign}{pct:.1f}%"
