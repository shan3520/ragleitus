'''Token count estimation utility.'''
def estimate_token_count(text: str) -> int:
    if not text:
        return 0
    words = text.split()
    return max(1, int(len(words) * 1.3))
