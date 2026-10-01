from fastapi import APIRouter, Depends
from app.api.deps import get_current_user
from pydantic import BaseModel

from app.services.text_cleaning import clean_text_pages

router = APIRouter(tags=["cleaning"], dependencies=[Depends(get_current_user)])


class CleanRequest(BaseModel):
    pages: list[str]


@router.post("/clean")
def clean_text(request: CleanRequest):
    return {"pages": clean_text_pages(request.pages)}
