"""
Service module for text chunking.

Provides sentence-aware sliding window text chunking logic.
"""


def chunk_text(text: str, chunk_window_size: int, chunk_overlap_size: int) -> list[str]:
    """
    Split text into chunks using sliding window size and overlap with sentence boundary awareness.

    Parameters
    ----------
    text : str
        Input string to split into chunks.
    chunk_window_size : int
        Maximum size of each chunk.
    chunk_overlap_size : int
        Overlap character length between consecutive chunks.

    Returns
    -------
    list[str]
        List of text chunks.
    """
    if not text:
        return []
    if chunk_window_size <= 0:
        raise ValueError("chunk_window_size must be greater than 0")
    if chunk_overlap_size < 0:
        raise ValueError("chunk_overlap_size must be non-negative")
    if chunk_overlap_size >= chunk_window_size:
        raise ValueError("chunk_overlap_size must be smaller than chunk_window_size")

    chunks: list[str] = []
    start = 0
    text_length = len(text)

    while start < text_length:
        end = min(start + chunk_window_size, text_length)
        if end < text_length:
            boundary = max(
                text.rfind(".", start, end),
                text.rfind("!", start, end),
                text.rfind("?", start, end),
            )
            if boundary > start:
                end = boundary + 1

        chunk = text[start:end].strip()
        if chunk:
            chunks.append(chunk)

        if end >= text_length:
            break

        # Ensure start advances monotonically to prevent infinite loops
        next_start = max(start + 1, end - chunk_overlap_size)
        while next_start < text_length and text[next_start].isspace():
            next_start += 1
        start = next_start

    return chunks
