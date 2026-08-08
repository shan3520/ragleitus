from fastapi import APIRouter
from pydantic import BaseModel, Field

from app.core.config import settings

router = APIRouter(tags=["chunking"])


class ChunkRequest(BaseModel):
    text: str
    chunk_window_size: int | None = Field(default=None, gt=0)
    chunk_overlap_size: int | None = Field(default=None, ge=0)


def chunk_text(text: str, chunk_window_size: int, chunk_overlap_size: int) -> list[str]:
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
        start = max(end - chunk_overlap_size, 0)
        while start < text_length and text[start].isspace():
            start += 1

    return chunks


@router.post("/chunk")
def chunk(request: ChunkRequest):
    window = request.chunk_window_size if request.chunk_window_size is not None else settings.chunk_window_size
    overlap = request.chunk_overlap_size if request.chunk_overlap_size is not None else settings.chunk_overlap_size
    return {"chunks": chunk_text(request.text, window, overlap)}
