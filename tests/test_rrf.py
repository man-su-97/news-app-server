"""Pure unit tests for Reciprocal Rank Fusion — no DB, no fakes needed.

RRF fuses two ranked id-lists (rank 1 = best) into one ranking:
    score(id) = sum over each list containing id of  1 / (k + rank_in_list)
Higher score = better. Ties break by id ascending for determinism.
"""

from app.repositories.chunk_repo import _compute_rrf


def test_empty_lists_return_empty():
    assert _compute_rrf([], [], k=60) == []


def test_single_list_ranks_by_position():
    result = _compute_rrf([10, 20, 30], [], k=60)
    # order preserved (rank 1, 2, 3) and scores are 1/(k+rank)
    assert [id_ for id_, _ in result] == [10, 20, 30]
    assert result[0][1] == 1 / 61
    assert result[1][1] == 1 / 62
    assert result[2][1] == 1 / 63


def test_one_empty_list_returns_the_other():
    assert [id_ for id_, _ in _compute_rrf([], [7, 8], k=60)] == [7, 8]


def test_non_overlapping_items_all_included():
    result = _compute_rrf([1, 2], [3, 4], k=60)
    assert {id_ for id_, _ in result} == {1, 2, 3, 4}


def test_item_in_both_lists_gets_summed_score():
    # list_a=[10,20,30], list_b=[20,40]
    #   10: 1/61              20: 1/62 + 1/61      30: 1/63      40: 1/62
    result = _compute_rrf([10, 20, 30], [20, 40], k=60)
    scores = dict(result)
    assert scores[20] == 1 / 62 + 1 / 61
    assert scores[10] == 1 / 61
    assert scores[40] == 1 / 62
    assert scores[30] == 1 / 63
    # 20 appears in both so it outranks everything else
    assert [id_ for id_, _ in result] == [20, 10, 40, 30]


def test_k_constant_changes_scores():
    # Larger k flattens the contribution of rank.
    small_k = dict(_compute_rrf([1], [], k=1))
    large_k = dict(_compute_rrf([1], [], k=1000))
    assert small_k[1] == 1 / 2
    assert large_k[1] == 1 / 1001
    assert small_k[1] > large_k[1]


def test_ties_break_by_id_ascending():
    # Same structure -> same score for 5 and 9; deterministic tie-break by id.
    result = _compute_rrf([9], [5], k=60)
    assert dict(result)[9] == dict(result)[5]
    assert [id_ for id_, _ in result] == [5, 9]
