"""Cheap batched materiality filter."""

from __future__ import annotations

import json

from stock_agent.analysis.schemas import MaterialityBatch, MaterialityItem
from stock_agent.llm.base import BudgetExceeded, Message
from stock_agent.llm.prompts import FILTER_INSTRUCTIONS, FILTER_PROMPT_VERSION, MATERIAL_CATEGORIES
from stock_agent.llm.router import Router

_BATCH = 25


def classify_materiality(router: Router, clusters: list[dict]) -> list[MaterialityItem]:
    """Each cluster dict needs cluster_id, title, and body. Already-classified ids are skipped by the caller."""
    decided: list[MaterialityItem] = []
    allowed = set(MATERIAL_CATEGORIES)
    for start in range(0, len(clusters), _BATCH):
        batch = clusters[start : start + _BATCH]
        payload = [
            {
                "cluster_id": item["cluster_id"],
                "text": f"{item['title']}. {item['body'][:400]}",
            }
            for item in batch
        ]
        messages = [
            Message("system", FILTER_INSTRUCTIONS),
            Message(
                "user",
                "Return JSON {\"items\": [{\"cluster_id\", \"material\", \"category\", \"reason\"}]}\n"
                + json.dumps(payload),
            ),
        ]
        try:
            result = router.complete("filter", messages, response_schema=MaterialityBatch)
        except BudgetExceeded:
            break
        parsed: MaterialityBatch = result.parsed  # type: ignore[assignment]
        returned = {item.cluster_id: item for item in parsed.items}
        for item in batch:
            found = returned.get(item["cluster_id"])
            if found is None:
                decided.append(
                    MaterialityItem(
                        cluster_id=item["cluster_id"],
                        material=False,
                        category="other",
                        reason="Model omitted this cluster.",
                    )
                )
                continue
            category = found.category if found.category in allowed else "other"
            decided.append(found.model_copy(update={"category": category}))
    return decided


def prompt_version() -> str:
    return FILTER_PROMPT_VERSION
