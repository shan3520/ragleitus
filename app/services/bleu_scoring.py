'''BLEU precision evaluation score calculator.'''
def score_bleu(candidate: str, reference: str) -> float:
    if not candidate or not reference:
        return 0.0
    cand_words = candidate.lower().split()
    ref_words = reference.lower().split()
    matches = sum(1 for w in cand_words if w in ref_words)
    return round(matches / max(1, len(cand_words)), 4)
