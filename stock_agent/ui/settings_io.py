"""Read and save the settings the window is allowed to change.

The SMTP password stays in .env. The embed role stays on the hashed fallback.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Mapping

import yaml

from stock_agent.analysis.propagation import INDUSTRY_EMBED_MODEL
from stock_agent.ui.models import (
    DEFAULT_ANALYSIS_MODEL,
    describe_model,
    model_choice_error,
)

NEWS_SOURCES = (
    ("finnhub", "Finnhub"),
    ("sec_edgar_8k", "SEC 8-K"),
    ("gdelt", "GDELT"),
    ("rss", "RSS"),
)
_ANALYSIS_ROLES = ("filter", "analysis", "thesis")
_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_SECRET_KEYS = {"password", "smtp_password", "smtp_pass", "secret"}


class SettingsError(ValueError):
    """The settings body cannot be saved."""


def email_configured(env: Mapping[str, str] | None = None) -> bool:
    source = os.environ if env is None else env
    return bool(source.get("SMTP_HOST") and source.get("SMTP_USER") and source.get("SMTP_PASSWORD"))


def read_settings(path: Path) -> dict:
    raw = yaml.safe_load(path.read_text()) or {}
    roles = ((raw.get("llm") or {}).get("roles") or {})
    analysis = roles.get("analysis") or {}
    embed = roles.get("embed") or {}
    sources = raw.get("sources") or {}
    report = raw.get("report") or {}
    analysis_block = raw.get("analysis") or {}
    news = [str(name) for name in sources.get("news") or []]
    recipients = [str(item) for item in report.get("recipients") or []]
    model = str(analysis.get("model") or DEFAULT_ANALYSIS_MODEL)
    return {
        "analysis_model": model,
        "max_stories_per_week": int(analysis_block.get("max_stories_per_week", 40)),
        "fetch_article_text": bool(analysis_block.get("fetch_article_text", True)),
        "top_n": int(report.get("top_n", 10)),
        "news_sources": news,
        "recipients": recipients,
        "embed_model": str(embed.get("model") or "all-MiniLM-L6-v2"),
        "embed_provider": str(embed.get("provider") or "local"),
    }


def public_settings(path: Path, installed: list[dict], *, env: Mapping[str, str] | None = None) -> dict:
    current = read_settings(path)
    models = _with_current(installed, current["analysis_model"])
    return {
        "analysis_model": current["analysis_model"],
        "default_analysis_model": DEFAULT_ANALYSIS_MODEL,
        "models": models,
        "max_stories_per_week": current["max_stories_per_week"],
        "fetch_article_text": current["fetch_article_text"],
        "top_n": current["top_n"],
        "news_sources": current["news_sources"],
        "news_source_options": [{"id": key, "label": label} for key, label in NEWS_SOURCES],
        "recipients": current["recipients"],
        "email_configured": email_configured(env),
        "embed": {
            "industry_model": INDUSTRY_EMBED_MODEL,
            "settings_model": current["embed_model"],
            "settings_provider": current["embed_provider"],
            "note": (
                "Industry matching uses the local nomic model. "
                "The embed role stays all-MiniLM-L6-v2, the hashed fallback."
            ),
        },
    }


def save_settings(
    path: Path,
    updates: Mapping[str, object],
    installed: list[dict],
    *,
    env: Mapping[str, str] | None = None,
) -> dict:
    if any(str(key).lower() in _SECRET_KEYS for key in updates):
        raise SettingsError("The SMTP password stays in .env.")
    current = read_settings(path)
    text = path.read_text()
    embed_before = _embed_line(text)
    model = str(updates.get("analysis_model") or current["analysis_model"]).strip()
    reason = model_choice_error(model, installed, current["analysis_model"])
    if reason:
        raise SettingsError(reason)
    if not model.startswith("ollama/"):
        model = f"ollama/{model}"
    stories = _bounded_int(updates.get("max_stories_per_week", current["max_stories_per_week"]), "Stories per week", 1, 200)
    top_n = _bounded_int(updates.get("top_n", current["top_n"]), "Top N ideas", 1, 50)
    fetch_text = _as_bool(updates.get("fetch_article_text", current["fetch_article_text"]))
    news = _news_sources(updates.get("news_sources", current["news_sources"]))
    recipients = _recipients(updates.get("recipients", current["recipients"]))
    updated = update_settings_text(
        text,
        analysis_model=model,
        max_stories_per_week=stories,
        fetch_article_text=fetch_text,
        top_n=top_n,
        news_sources=news,
        recipients=recipients,
    )
    if _embed_line(updated) != embed_before:
        raise SettingsError("The embed role stays all-MiniLM-L6-v2.")
    temporary = path.with_suffix(".yaml.tmp")
    temporary.write_text(updated)
    temporary.replace(path)
    return public_settings(path, installed, env=env)


def update_settings_text(
    text: str,
    *,
    analysis_model: str,
    max_stories_per_week: int,
    fetch_article_text: bool,
    top_n: int,
    news_sources: list[str],
    recipients: list[str],
) -> str:
    embed_before = _embed_line(text)
    for role in _ANALYSIS_ROLES:
        text = _replace_role_model(text, role, analysis_model)
    text = _replace_scalar(text, "max_stories_per_week", str(max_stories_per_week))
    text = _replace_scalar(text, "fetch_article_text", "true" if fetch_article_text else "false")
    text = _replace_scalar(text, "top_n", str(top_n))
    news_value = "[" + ", ".join(news_sources) + "]"
    text = _replace_scalar(text, "news", news_value)
    quoted = ", ".join(json.dumps(item) for item in recipients)
    text = _replace_scalar(text, "recipients", f"[{quoted}]")
    if _embed_line(text) != embed_before:
        raise SettingsError("The embed role stays all-MiniLM-L6-v2.")
    return text


def _with_current(installed: list[dict], current: str) -> list[dict]:
    items = list(installed)
    known = {item["model"] for item in items} | {item["name"] for item in items}
    tag = current.removeprefix("ollama/")
    if current not in known and tag not in known:
        items.insert(0, describe_model(tag))
    return items


def _replace_role_model(text: str, role: str, model: str) -> str:
    pattern = rf'^(\s*{role}:\s*\{{[^\n]*\bmodel:\s*")[^"]*(")'

    def repl(match: re.Match[str]) -> str:
        return f"{match.group(1)}{model}{match.group(2)}"

    updated, count = re.subn(pattern, repl, text, count=1, flags=re.MULTILINE)
    if count != 1:
        raise SettingsError(f"Could not update the {role} model in settings.yaml.")
    return updated


def _replace_scalar(text: str, key: str, value: str) -> str:
    pattern = rf"^(\s*{re.escape(key)}:\s*)\S.*$"
    updated, count = re.subn(pattern, rf"\g<1>{value}", text, count=1, flags=re.MULTILINE)
    if count != 1:
        raise SettingsError(f"Could not update {key} in settings.yaml.")
    return updated


def _embed_line(text: str) -> str | None:
    for line in text.splitlines():
        if re.match(r"\s*embed:\s*", line):
            return line
    return None


def _bounded_int(value: object, label: str, low: int, high: int) -> int:
    try:
        number = int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError) as exc:
        raise SettingsError(f"{label} needs a whole number.") from exc
    if number < low or number > high:
        raise SettingsError(f"{label} stays between {low} and {high}.")
    return number


def _as_bool(value: object) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"true", "yes", "1"}:
            return True
        if lowered in {"false", "no", "0"}:
            return False
    raise SettingsError("Fetch full article text is on or off.")


def _news_sources(value: object) -> list[str]:
    if not isinstance(value, list):
        raise SettingsError("Choose the news sources to collect.")
    allowed = {key for key, _label in NEWS_SOURCES}
    chosen = []
    for item in value:
        name = str(item).strip()
        if name not in allowed:
            raise SettingsError("News sources are Finnhub, SEC 8-K, GDELT, and RSS.")
        if name not in chosen:
            chosen.append(name)
    return [key for key, _label in NEWS_SOURCES if key in chosen]


def _recipients(value: object) -> list[str]:
    if isinstance(value, str):
        parts = [part.strip() for part in value.split(",") if part.strip()]
    elif isinstance(value, list):
        parts = [str(part).strip() for part in value if str(part).strip()]
    else:
        raise SettingsError("Enter the report recipient.")
    if not parts:
        raise SettingsError("Enter the report recipient.")
    if len(parts) > 5:
        raise SettingsError("Save up to five report recipients.")
    for item in parts:
        if not _EMAIL.match(item):
            raise SettingsError("Enter an email address for the report recipient.")
    return parts
