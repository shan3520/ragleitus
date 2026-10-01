"""
BM25 keyword scoring algorithm implementation.
"""

import math
from collections import Counter
from typing import Sequence

def tokenize(text: str) -> list[str]:
    """Tokenize input text into lowercase alpha-numeric terms."""
    if not text:
        return []
    import re
    return re.findall(r"\w+", text.lower())

def score_bm25(query_tokens: list[str], doc_tokens: list[str], avg_doc_len: float, k1: float = 1.5, b: float = 0.75) -> float:
    """Calculate BM25 relevance score for a document against query tokens."""
    if not query_tokens or not doc_tokens:
        return 0.0

    doc_len = len(doc_tokens)
    doc_freqs = Counter(doc_tokens)
    score = 0.0

    for token in query_tokens:
        if token in doc_freqs:
            freq = doc_freqs[token]
            num = freq * (k1 + 1.0)
            den = freq + k1 * (1.0 - b + b * (doc_len / (avg_doc_len or 1.0)))
            score += num / den

    return round(score, 4)


class BM25Index:
    """Okapi BM25 over a fixed set of documents, with inverse document frequency.

    `score_bm25` above scores term frequency only, so words that appear in
    every document count as much as rare ones; this index weights each query
    term by how rare it is across the collection.
    """

    def __init__(self, documents: Sequence[str], k1: float = 1.5, b: float = 0.75):
        self.k1 = k1
        self.b = b
        self._docs = [Counter(tokenize(d)) for d in documents]
        self._lengths = [sum(c.values()) for c in self._docs]
        self._avg_len = (sum(self._lengths) / len(self._lengths)) if self._lengths else 0.0
        doc_freq: Counter = Counter()
        for counts in self._docs:
            doc_freq.update(counts.keys())
        n = len(self._docs)
        self._idf = {term: math.log(1 + (n - df + 0.5) / (df + 0.5)) for term, df in doc_freq.items()}

    def scores(self, query: str) -> list[float]:
        terms = set(tokenize(query))
        results = []
        for counts, length in zip(self._docs, self._lengths):
            score = 0.0
            for term in terms:
                freq = counts.get(term)
                if not freq:
                    continue
                norm = freq + self.k1 * (1 - self.b + self.b * length / (self._avg_len or 1.0))
                score += self._idf[term] * freq * (self.k1 + 1) / norm
            results.append(score)
        return results

    def top(self, query: str, limit: int) -> list[tuple[int, float]]:
        """Indexes and scores of the best-matching documents with a non-zero score."""
        ranked = sorted(((i, s) for i, s in enumerate(self.scores(query)) if s > 0), key=lambda item: -item[1])
        return ranked[:limit]
