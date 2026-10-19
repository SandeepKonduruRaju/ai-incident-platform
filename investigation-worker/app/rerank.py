"""Second-stage ranking with a cross-encoder.

Bi-encoder (our embedding model): query and chunk are embedded SEPARATELY, so all chunks can be
embedded once at ingest and searched with an index. Fast, but the two texts never "see" each other.
Cross-encoder (this module): reads query and chunk TOGETHER and outputs one relevance score. Much more
accurate, but needs one model run per (query, chunk) pair at query time, so it only re-orders the
few dozen candidates the cheap retrievers found ("retrieve wide, rerank narrow").
"""

import asyncio
import re
from typing import Protocol

DEFAULT_RERANKER_MODEL = "Xenova/ms-marco-MiniLM-L-6-v2"

_WORD = re.compile(r"[a-z0-9]+")


class Reranker(Protocol):
    def rerank(self, query: str, documents: list[str]) -> list[float]: ...


class FastEmbedReranker:
    """ms-marco-MiniLM-L-6-v2: 6 layers, ~80MB ONNX, fast on CPU. Scores are logits (higher = more
    relevant, not bounded to 0..1); only their order matters to us."""

    def __init__(self, model_name: str = DEFAULT_RERANKER_MODEL, cache_dir: str | None = None) -> None:
        from fastembed.rerank.cross_encoder import TextCrossEncoder

        self._model = TextCrossEncoder(model_name=model_name, cache_dir=cache_dir)
        self.model_name = model_name

    def rerank(self, query: str, documents: list[str]) -> list[float]:
        return [float(score) for score in self._model.rerank(query, documents)]


class FakeReranker:
    """Deterministic stand-in for tests: score = share of the query's words that appear in the document."""

    def rerank(self, query: str, documents: list[str]) -> list[float]:
        query_words = set(_WORD.findall(query.lower()))
        if not query_words:
            return [0.0 for _ in documents]
        return [len(query_words & set(_WORD.findall(doc.lower()))) / len(query_words) for doc in documents]


async def rerank_async(reranker: Reranker, query: str, documents: list[str]) -> list[float]:
    """CPU-bound model run in a worker thread, so the event loop is never blocked."""
    if not documents:
        return []
    return await asyncio.to_thread(reranker.rerank, query, documents)
