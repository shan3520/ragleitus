'''
Hybrid search score merger.
'''
def combine_scores(keyword_scores: dict[str, float], vector_scores: dict[str, float], alpha: float = 0.5) -> dict[str, float]:
    all_keys = set(keyword_scores.keys()) | set(vector_scores.keys())
    combined = {}
    for key in all_keys:
        kw = keyword_scores.get(key, 0.0)
        vec = vector_scores.get(key, 0.0)
        combined[key] = round(alpha * kw + (1.0 - alpha) * vec, 4)
    return combined
