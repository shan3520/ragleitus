from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.core.config import settings
from app.services.chunking import chunk_text

router = APIRouter(tags=["chunking"])


class ChunkRequest(BaseModel):
    text: str
    chunk_window_size: int | None = Field(default=None, gt=0)
    chunk_overlap_size: int | None = Field(default=None, ge=0)


@router.post("/chunk")
def chunk(request: ChunkRequest):
    window = request.chunk_window_size if request.chunk_window_size is not None else settings.chunk_window_size
    overlap = request.chunk_overlap_size if request.chunk_overlap_size is not None else settings.chunk_overlap_size
    try:
        chunks = chunk_text(request.text, window, overlap)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"chunks": chunks}
