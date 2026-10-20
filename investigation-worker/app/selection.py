"""Pick the final evidence: best reranker scores first, but with a cap per source type.

Without caps the top 6 is often 6 log windows (many, similar, keyword-rich), and the runbook that
explains the fix never reaches the LLM. Caps keep the evidence diverse; slots a type cannot fill
(e.g. no metric in the time window) go to the next best chunks of any type, so nothing is wasted.
"""

from collections import Counter
from collections.abc import Mapping, Sequence
from typing import Protocol

DEFAULT_SOURCE_CAPS: dict[str, int] = {"log": 3, "runbook": 2, "incident": 1, "metric": 2}
FINAL_K_RANGE = (1, 20)
RETRIEVE_K_RANGE = (1, 50)


class Scored(Protocol):
    @property
    def source_type(self) -> str: ...

    @property
    def rerank_score(self) -> float: ...



def validate_k(*, retrieve_k: int, final_k: int) -> None:
    for name, value, (low, high) in (
        ("retrieve_k", retrieve_k, RETRIEVE_K_RANGE),
        ("final_k", final_k, FINAL_K_RANGE),
    ):
        if not low <= value <= high:
            raise ValueError(f"{name} must be between {low} and {high}, got {value}")


def apply_source_caps[T: Scored](scored_chunks: Sequence[T], caps: Mapping[str, int], final_k: int) -> list[T]:
    """Up to final_k chunks, ordered by rerank_score descending (stable for equal scores).

    Pass 1 takes chunks in score order while their type is under its cap (types without a cap: 0).
    Pass 2 fills the remaining slots with the best chunks left over, regardless of type.
    """
    low, high = FINAL_K_RANGE
    if not low <= final_k <= high:
        raise ValueError(f"final_k must be between {low} and {high}, got {final_k}")
    if any(cap < 0 for cap in caps.values()):
        raise ValueError("caps must be >= 0")

    ranked = sorted(scored_chunks, key=lambda chunk: -chunk.rerank_score)  # sorted() is stable
    taken: Counter[str] = Counter()
    selected: list[int] = []
    for position, chunk in enumerate(ranked):
        if len(selected) == final_k:
            break
        if taken[chunk.source_type] < caps.get(chunk.source_type, 0):
            taken[chunk.source_type] += 1
            selected.append(position)

    chosen = set(selected)
    leftovers = [position for position in range(len(ranked)) if position not in chosen]
    selected.extend(leftovers[: final_k - len(selected)])
    return [ranked[position] for position in sorted(selected)]
