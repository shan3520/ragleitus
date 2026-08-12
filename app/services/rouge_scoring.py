'''ROUGE-L evaluation score calculation.'''
def score_rouge_l(candidate: str, reference: str) -> float:
    if not candidate or not reference:
        return 0.0
    cand_words = candidate.lower().split()
    ref_words = reference.lower().split()
    common = set(cand_words) & set(ref_words)
    if not common:
        return 0.0
    prec = len(common) / len(cand_words)
    rec = len(common) / len(ref_words)
    if prec + rec == 0:
        return 0.0
    return round(2 * prec * rec / (prec + rec), 4)
