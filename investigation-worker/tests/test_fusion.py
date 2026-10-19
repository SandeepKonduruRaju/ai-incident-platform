import pytest

from app.fusion import rrf_fuse


def test_worked_example_rank_5_in_both_beats_rank_1_in_only_one():
    # "both" is 5th in the vector list AND 5th in the keyword list; "a" is 1st, but only in the vector list.
    vector = ["a", "v2", "v3", "v4", "both"]
    keyword = ["k1", "k2", "k3", "k4", "both"]

    fused = rrf_fuse([vector, keyword], k_const=60)
    scores = dict(fused)

    assert scores["both"] == pytest.approx(1 / 65 + 1 / 65)  # 0.0308
    assert scores["a"] == pytest.approx(1 / 61)               # 0.0164
    assert fused[0][0] == "both"


def test_ranks_are_one_based():
    [(chunk_id, score)] = rrf_fuse([["a"]], k_const=60)
    assert (chunk_id, score) == ("a", pytest.approx(1 / 61))


def test_missing_from_a_list_contributes_zero():
    scores = dict(rrf_fuse([["a", "b"], ["b"]]))
    assert scores["a"] == pytest.approx(1 / 61)            # list 1 rank 1, absent from list 2 (+0)
    assert scores["b"] == pytest.approx(1 / 62 + 1 / 61)   # list 1 rank 2 + list 2 rank 1


def test_sorted_descending_with_deterministic_tie_break_by_id():
    # c and a both rank 1 in one list: equal scores -> ordered by id ascending.
    assert [chunk_id for chunk_id, _ in rrf_fuse([["c"], ["a"]])] == ["a", "c"]
    assert [chunk_id for chunk_id, _ in rrf_fuse([["a"], ["c"]])] == ["a", "c"]


def test_a_list_cannot_vote_twice_for_the_same_document():
    assert dict(rrf_fuse([["a", "a"]]))["a"] == pytest.approx(1 / 61)


def test_empty_input_and_bad_k_const():
    assert rrf_fuse([]) == []
    assert rrf_fuse([[], []]) == []
    with pytest.raises(ValueError):
        rrf_fuse([["a"]], k_const=-1)
