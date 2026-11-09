"""Models already installed in local Ollama. Nothing here downloads a model."""

from __future__ import annotations

import re
import subprocess

from stock_agent.analysis.propagation import INDUSTRY_EMBED_MODEL

DEFAULT_ANALYSIS_MODEL = "ollama/qwen2.5:3b"
TOO_LARGE_TAGS = {"qwen2.5:latest", "qwen2.5vl:latest"}
_ROW = re.compile(r"^(\S+)\s+\S+\s+([0-9]+(?:\.[0-9]+)?)\s+(GB|MB|KB)\b")
_GB = {"KB": 1 / 1_000_000, "MB": 1 / 1024, "GB": 1.0}


def parse_ollama_list(text: str) -> list[dict]:
    """Turn `ollama list` output into display records."""
    found: list[dict] = []
    for line in text.splitlines():
        match = _ROW.match(line.strip())
        if not match:
            continue
        name, amount, unit = match.group(1), float(match.group(2)), match.group(3)
        found.append(describe_model(name, size_gb=amount * _GB[unit], size_label=f"{amount:g} {unit}"))
    return found


def describe_model(name: str, *, size_gb: float | None = None, size_label: str = "") -> dict:
    tag = name.removeprefix("ollama/")
    model = tag if tag.startswith("ollama/") else f"ollama/{tag}"
    if tag.startswith("nomic-embed"):
        return {
            "name": tag,
            "model": INDUSTRY_EMBED_MODEL,
            "selectable": False,
            "kind": "embed",
            "size": size_label,
            "note": "Installed for industry matching.",
        }
    too_large = tag in TOO_LARGE_TAGS or (size_gb is not None and size_gb >= 4.0)
    if too_large:
        return {
            "name": tag,
            "model": model,
            "selectable": False,
            "kind": "too_large",
            "size": size_label,
            "note": "Too large for this 8 GB Mac.",
        }
    if "vl" in tag.split(":", 1)[0]:
        return {
            "name": tag,
            "model": model,
            "selectable": False,
            "kind": "vision",
            "size": size_label,
            "note": "Vision model. Analysis uses a text model.",
        }
    note = "Default analysis model." if model == DEFAULT_ANALYSIS_MODEL or tag == "qwen2.5:3b" else ""
    return {
        "name": tag,
        "model": model,
        "selectable": True,
        "kind": "analysis",
        "size": size_label,
        "note": note,
    }


def installed_models() -> list[dict]:
    """Read the local Ollama catalog. A failure returns an empty list."""
    try:
        completed = subprocess.run(
            ["ollama", "list"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return []
    if completed.returncode != 0:
        return []
    return parse_ollama_list(completed.stdout)


def model_choice_error(model: str, installed: list[dict], current: str) -> str | None:
    """Return a user-facing reason the analysis model cannot be saved."""
    normalized = model if str(model).startswith("ollama/") else f"ollama/{model}"
    tag = normalized.removeprefix("ollama/")
    if tag.startswith("nomic-embed"):
        return "The nomic model is for industry matching, not the written analysis."
    if tag in TOO_LARGE_TAGS:
        return f"{tag} is too large for this 8 GB Mac."
    for item in installed:
        if item["model"] == normalized or item["name"] == tag:
            if item.get("selectable"):
                return None
            return item.get("note") or "That model cannot run the analysis on this Mac."
    if normalized == current or normalized == DEFAULT_ANALYSIS_MODEL:
        return None
    if not installed:
        return "That model is not in the installed Ollama list."
    return "Choose a model Ollama already has installed."
