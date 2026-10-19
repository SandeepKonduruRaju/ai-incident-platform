"""Reciprocal Rank Fusion (RRF): combine several ranked result lists into one.

    rrf_score(doc) = sum over lists of 1 / (k_const + rank)      rank is 1-based; missing from a list -> 0

Why ranks and not scores? Cosine distance (0..2, lower is better) and ts_rank (0..~1, higher is better)
are on different, incomparable scales; normalising them is fragile. RRF only uses positions, so any
retrievers can be fused without tuning. k_const = 60 (from the original paper, Cormack et al. 2009)
damps the difference between rank 1 and rank 2, so a document found by BOTH retrievers tends to beat
one found high by only one of them.
"""

from collections.abc import Hashable, Iterable, Sequence

DEFAULT_K_CONST = 60


def rrf_fuse(
    ranked_lists: Iterable[Sequence[Hashable]], k_const: int = DEFAULT_K_CONST
) -> list[tuple[Hashable, float]]:
    """[(chunk_id, rrf_score)] sorted by score descending; ties broken by chunk_id (as text) ascending."""
    if k_const < 0:
        raise ValueError("k_const must be >= 0")
    scores: dict[Hashable, float] = {}
    for ranked in ranked_lists:
        seen: set[Hashable] = set()
        for rank, chunk_id in enumerate(ranked, start=1):
            if chunk_id in seen:  # a list should not vote twice for the same document
                continue
            seen.add(chunk_id)
            scores[chunk_id] = scores.get(chunk_id, 0.0) + 1.0 / (k_const + rank)
    return sorted(scores.items(), key=lambda item: (-item[1], str(item[0])))
