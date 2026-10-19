"""Turn text into vectors (embeddings) for semantic search over worker.chunks.

Embedder is a Protocol (structural typing, like a Java interface that classes satisfy without
"implements"): ingestion and search depend on it, so unit tests swap in FakeEmbedder and never load
the real model.
"""

import asyncio
import hashlib
import math
from typing import Protocol

DEFAULT_MODEL = "BAAI/bge-small-en-v1.5"
# From the bge-*-v1.5 model card: prepend to short search queries, never to stored passages.
BGE_QUERY_INSTRUCTION = "Represent this sentence for searching relevant passages: "


class Embedder(Protocol):
    @property
    def dim(self) -> int: ...

    def embed(self, texts: list[str]) -> list[list[float]]: ...


class FastEmbedEmbedder:
    """Local ONNX model through fastembed: no API key, no network at runtime, runs on CPU.

    bge-small-en-v1.5 returns 384-dimensional, L2-normalised vectors (length 1), so cosine distance
    (pgvector's <=> operator) is the natural metric.
    """

    def __init__(self, model_name: str = DEFAULT_MODEL, cache_dir: str | None = None) -> None:
        # Imported here so modules that only need the Protocol (and the unit tests) do not load onnxruntime.
        from fastembed import TextEmbedding

        # Loads the model files from cache_dir, downloading them first if they are missing.
        self._model = TextEmbedding(model_name=model_name, cache_dir=cache_dir)
        self.model_name = model_name
        self._dim = TextEmbedding.get_embedding_size(model_name)

    @property
    def dim(self) -> int:
        return self._dim

    def embed(self, texts: list[str]) -> list[list[float]]:
        # fastembed yields one numpy array per text; tolist() gives plain Python floats.
        return [vector.tolist() for vector in self._model.embed(texts)]


class FakeEmbedder:
    """Deterministic stand-in for tests: the same text always gives the same unit-length vector.

    Built from a SHA-256 hash of the text, so it carries no meaning (similar texts are NOT close);
    it only checks plumbing: shapes, storage, idempotency.
    """

    def __init__(self, dim: int = 384) -> None:
        self._dim = dim

    @property
    def dim(self) -> int:
        return self._dim

    def embed(self, texts: list[str]) -> list[list[float]]:
        return [self._vector(text) for text in texts]

    def _vector(self, text: str) -> list[float]:
        values: list[float] = []
        counter = 0
        while len(values) < self._dim:
            digest = hashlib.sha256(f"{counter}:{text}".encode()).digest()
            values.extend(byte / 255.0 - 0.5 for byte in digest)
            counter += 1
        values = values[: self._dim]
        norm = math.sqrt(sum(v * v for v in values)) or 1.0
        return [v / norm for v in values]


async def embed_async(embedder: Embedder, texts: list[str]) -> list[list[float]]:
    """Run the CPU-bound embedding in a worker thread so the event loop keeps serving
    (health checks, Kafka heartbeats) meanwhile. onnxruntime releases the GIL while it computes."""
    return await asyncio.to_thread(embedder.embed, texts)


async def embed_query(embedder: Embedder, query: str, instruction: str = "") -> list[float]:
    """Embed a search query. BGE models are trained with an instruction prefix on short QUERIES
    (never on the stored passages): asymmetric retrieval, short question vs long document."""
    [vector] = await embed_async(embedder, [instruction + query])
    return vector
