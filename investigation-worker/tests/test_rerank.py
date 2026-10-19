import threading

from app.rerank import FakeReranker, rerank_async


def test_fake_reranker_scores_by_shared_words():
    scores = FakeReranker().rerank(
        "connection pool exhausted",
        ["HikariPool connection pool exhausted", "pool is fine", "disk full"],
    )
    assert scores == [1.0, 1 / 3, 0.0]


def test_fake_reranker_is_deterministic_and_handles_empty_query():
    reranker = FakeReranker()
    assert reranker.rerank("a b", ["a"]) == reranker.rerank("a b", ["a"])
    assert reranker.rerank("", ["anything"]) == [0.0]


async def test_rerank_async_runs_off_the_event_loop_thread():
    seen = {}

    class RecordingReranker(FakeReranker):
        def rerank(self, query, documents):
            seen["thread"] = threading.get_ident()
            return super().rerank(query, documents)

    assert await rerank_async(RecordingReranker(), "pool", ["pool"]) == [1.0]
    assert seen["thread"] != threading.get_ident()


async def test_rerank_async_with_no_documents_does_not_call_the_model():
    class ExplodingReranker:
        def rerank(self, query, documents):
            raise AssertionError("must not be called")

    assert await rerank_async(ExplodingReranker(), "q", []) == []
