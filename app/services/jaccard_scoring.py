'''Jaccard similarity scoring.'''
def score_jaccard(text1: str, text2: str) -> float:
    s1 = set((text1 or "").lower().split())
    s2 = set((text2 or "").lower().split())
    union = s1 | s2
    if not union:
        return 0.0
    return round(len(s1 & s2) / len(union), 4)
