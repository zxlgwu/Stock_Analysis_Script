"""Cluster near-duplicate articles by embedding cosine similarity."""

from __future__ import annotations

import math


def cosine(left: list[float], right: list[float]) -> float:
    dot = sum(a * b for a, b in zip(left, right))
    left_norm = math.sqrt(sum(a * a for a in left)) or 1.0
    right_norm = math.sqrt(sum(b * b for b in right)) or 1.0
    return dot / (left_norm * right_norm)


def cluster_vectors(
    ids: list[str], vectors: list[list[float]], *, threshold: float = 0.82
) -> list[list[str]]:
    """Greedy clusters. The first id in each group is the representative."""
    groups: list[dict] = []
    for article_id, vector in zip(ids, vectors):
        placed = False
        for group in groups:
            if cosine(vector, group["centroid"]) >= threshold:
                group["ids"].append(article_id)
                count = len(group["ids"])
                group["centroid"] = [
                    (previous * (count - 1) + value) / count
                    for previous, value in zip(group["centroid"], vector)
                ]
                placed = True
                break
        if not placed:
            groups.append({"ids": [article_id], "centroid": list(vector)})
    return [group["ids"] for group in groups]
