from repodoctor.search import reciprocal_rank_fusion


def test_reciprocal_rank_fusion_prefers_overlap() -> None:
    fused = reciprocal_rank_fusion([[1, 2, 3], [2, 4, 1]])
    assert fused[0] == 2
    assert 1 in fused[:3]
