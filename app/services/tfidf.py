'''
TF-IDF score computation service.
'''
import math
from collections import Counter

def compute_tf(tokens: list[str]) -> dict[str, float]:
    if not tokens:
        return {}
    counts = Counter(tokens)
    total = len(tokens)
    return {term: count / total for term, count in counts.items()}

def compute_idf(documents_tokens: list[list[str]]) -> dict[str, float]:
    if not documents_tokens:
        return {}
    n = len(documents_tokens)
    doc_freqs = Counter()
    for doc in documents_tokens:
        unique = set(doc)
        doc_freqs.update(unique)
    return {term: math.log((n + 1.0) / (df + 1.0)) + 1.0 for term, df in doc_freqs.items()}

def normalize_vector(weights: dict[str, float]) -> dict[str, float]:
    if not weights:
        return {}
    norm = math.sqrt(sum(v * v for v in weights.values()))
    if norm == 0.0:
        return {k: 0.0 for k in weights}
    return {k: round(v / norm, 4) for k, v in weights.items()}

