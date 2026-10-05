"""The prompt library: your own versioned system prompts."""
from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.db.database import get_db
from app.models.user import User
from app.services import prompt_service

router = APIRouter(prefix="/api/prompts", tags=["prompts"])


class PromptCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=2000)
    template: str = Field(min_length=1, max_length=prompt_service.MAX_TEMPLATE_LENGTH)
    note: str | None = Field(default=None, max_length=500)


class PromptUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=2000)


class VersionCreate(BaseModel):
    template: str = Field(min_length=1, max_length=prompt_service.MAX_TEMPLATE_LENGTH)
    note: str | None = Field(default=None, max_length=500)


class PromptClone(BaseModel):
    name: str | None = Field(default=None, max_length=255)


def _raise(exc: prompt_service.PromptError):
    raise HTTPException(status_code=exc.status_code, detail=exc.message)


@router.get("")
def list_prompts(user: User = Depends(get_current_user), session: Session = Depends(get_db)):
    """Your prompts, each with its latest version."""
    return [prompt_service.prompt_dict(p) for p in prompt_service.list_prompts(session, user.id)]


@router.get("/default")
def default_prompt(user: User = Depends(get_current_user)):
    """The built-in system prompt, as a starting point."""
    return {"template": prompt_service.default_template()}


@router.post("", status_code=status.HTTP_201_CREATED)
def create_prompt(payload: PromptCreate, user: User = Depends(get_current_user), session: Session = Depends(get_db)):
    """Save a prompt. The template must contain {context}; {question} is optional."""
    try:
        prompt = prompt_service.create_prompt(session, user.id, payload.name, payload.template, payload.description, payload.note)
    except prompt_service.PromptError as exc:
        _raise(exc)
    session.commit()
    return prompt_service.prompt_dict(prompt, with_versions=True)


@router.get("/{prompt_id}")
def get_prompt(prompt_id: int, user: User = Depends(get_current_user), session: Session = Depends(get_db)):
    """A prompt with all its versions, newest first."""
    try:
        return prompt_service.prompt_dict(prompt_service.get_prompt(session, user.id, prompt_id), with_versions=True)
    except prompt_service.PromptError as exc:
        _raise(exc)


@router.patch("/{prompt_id}")
def update_prompt(prompt_id: int, payload: PromptUpdate, user: User = Depends(get_current_user), session: Session = Depends(get_db)):
    try:
        prompt = prompt_service.update_prompt(session, user.id, prompt_id, payload.name, payload.description)
    except prompt_service.PromptError as exc:
        _raise(exc)
    session.commit()
    return prompt_service.prompt_dict(prompt, with_versions=True)


@router.delete("/{prompt_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_prompt(prompt_id: int, user: User = Depends(get_current_user), session: Session = Depends(get_db)):
    """Delete a prompt; conversations using it go back to the built-in prompt."""
    try:
        prompt_service.delete_prompt(session, user.id, prompt_id)
    except prompt_service.PromptError as exc:
        _raise(exc)
    session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/{prompt_id}/versions", status_code=status.HTTP_201_CREATED)
def add_version(prompt_id: int, payload: VersionCreate, user: User = Depends(get_current_user), session: Session = Depends(get_db)):
    """Save a new version; earlier versions stay as they were."""
    try:
        version = prompt_service.add_version(session, user.id, prompt_id, payload.template, payload.note)
    except prompt_service.PromptError as exc:
        _raise(exc)
    session.commit()
    return prompt_service.version_dict(version)


@router.post("/{prompt_id}/clone", status_code=status.HTTP_201_CREATED)
def clone_prompt(prompt_id: int, payload: PromptClone | None = None, user: User = Depends(get_current_user), session: Session = Depends(get_db)):
    """A new prompt starting from this one's latest version."""
    try:
        prompt = prompt_service.clone_prompt(session, user.id, prompt_id, payload.name if payload else None)
    except prompt_service.PromptError as exc:
        _raise(exc)
    session.commit()
    return prompt_service.prompt_dict(prompt, with_versions=True)
