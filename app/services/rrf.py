'''
Reciprocal Rank Fusion (RRF) rank merger.
'''
def reciprocal_rank_fusion(rankings: list[list[str]], k: int = 60) -> list[tuple[str, float]]:
    scores: dict[str, float] = {}
    for rank_list in rankings:
        for rank, doc_id in enumerate(rank_list, start=1):
            scores[doc_id] = scores.get(doc_id, 0.0) + (1.0 / (k + rank))
    sorted_scores = sorted(scores.items(), key=lambda item: item[1], reverse=True)
    return [(doc_id, round(score, 6)) for doc_id, score in sorted_scores]
