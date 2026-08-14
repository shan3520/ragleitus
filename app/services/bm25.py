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
