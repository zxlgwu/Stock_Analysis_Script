"""Local embeddings. Uses sentence-transformers when installed, otherwise a stable hash."""

from __future__ import annotations

import hashlib
import math
import re

from stock_agent.llm.base import LLMResult, Message

_DIMS = 64
_TOKEN = re.compile(r"[a-z0-9]+")
_WARNED = False


def hashed_bow(text: str, dims: int = _DIMS) -> list[float]:
    """Bag-of-words embedding. The same text always maps to the same vector."""
    vector = [0.0] * dims
    for token in _TOKEN.findall(text.lower()):
        bucket = int(hashlib.md5(token.encode()).hexdigest(), 16) % dims
        vector[bucket] += 1.0
    norm = math.sqrt(sum(value * value for value in vector)) or 1.0
    return [value / norm for value in vector]


class LocalEmbedProvider:
    """Embedding role. Completion is intentionally unsupported."""

    name = "local"

    def complete(
        self,
        messages: list[Message],
        *,
        model: str,
        temperature: float = 0.0,
        max_tokens: int | None = None,
    ) -> LLMResult:
        raise NotImplementedError("The local provider only embeds text.")

    def embed(self, texts: list[str], *, model: str) -> list[list[float]]:
        encoder = _load_sentence_transformer(model)
        if encoder is not None:
            vectors = encoder.encode(list(texts), normalize_embeddings=True)
            return [list(map(float, row)) for row in vectors]
        global _WARNED
        if model not in {"hashed-bow", "hashed-bow-fallback"} and not _WARNED:
            print(
                f"sentence-transformers is not installed; using a hashed bag-of-words "
                f"embedder instead of {model}."
            )
            _WARNED = True
        return [hashed_bow(text) for text in texts]


def _load_sentence_transformer(model: str):
    if model in {"hashed-bow", "hashed-bow-fallback"}:
        return None
    try:
        from sentence_transformers import SentenceTransformer
    except ImportError:
        return None
    return SentenceTransformer(model)
