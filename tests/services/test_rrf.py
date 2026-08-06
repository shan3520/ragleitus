from app.services.rrf import reciprocal_rank_fusion

def test_reciprocal_rank_fusion():
    r1 = ["docA", "docB", "docC"]
    r2 = ["docB", "docA"]
    fused = reciprocal_rank_fusion([r1, r2], k=60)
    assert len(fused) == 3
    assert fused[0][0] in ("docA", "docB")
