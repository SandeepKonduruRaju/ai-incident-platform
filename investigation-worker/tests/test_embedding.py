import math
import threading

from app.embedding import FakeEmbedder, embed_async, embed_query


def test_fake_embedder_is_deterministic_unit_length_and_has_the_right_dim():
    embedder = FakeEmbedder()
    first, other = embedder.embed(["checkout 500 errors", "disk full"])
    assert embedder.dim == 384
    assert len(first) == 384
    assert embedder.embed(["checkout 500 errors"])[0] == first
    assert first != other
    assert math.isclose(math.sqrt(sum(v * v for v in first)), 1.0, rel_tol=1e-9)


async def test_embed_async_runs_the_embedder_off_the_event_loop_thread():
    seen = {}

    class RecordingEmbedder(FakeEmbedder):
        def embed(self, texts):
            seen["thread"] = threading.get_ident()
            return super().embed(texts)

    vectors = await embed_async(RecordingEmbedder(dim=8), ["a", "b"])
    assert len(vectors) == 2 and len(vectors[0]) == 8
    assert seen["thread"] != threading.get_ident()  # this test runs on the event loop thread


async def test_embed_query_prepends_the_instruction_to_the_query_only():
    embedder = FakeEmbedder()
    with_instruction = await embed_query(embedder, "pool exhausted", "Represent this: ")
    assert with_instruction == embedder.embed(["Represent this: pool exhausted"])[0]
    assert await embed_query(embedder, "pool exhausted") == embedder.embed(["pool exhausted"])[0]
