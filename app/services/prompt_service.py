"""The prompt library: a user's own system prompts, versioned.

A prompt has a name and a list of versions; saving changes adds a version, so
earlier answers and experiments can always say which text they used. A
version's template is the system prompt for chat and experiments:
`{context}` is replaced by the numbered passages (required, or the model
would never see the documents) and `{question}`, optionally, by the question.
"""

from __future__ import annotations

from sqlalchemy import func
from sqlalchemy.orm import Session, selectinload

from app.models.prompt import Prompt, PromptVersion
from app.services.chat_service import ChatError, SYSTEM_PROMPT

MAX_TEMPLATE_LENGTH = 20_000


class PromptError(ChatError):
    status_code = 400


class PromptNotFoundError(PromptError):
    status_code = 404


def default_template() -> str:
    """The built-in system prompt, as a starting point for new prompts."""
    return SYSTEM_PROMPT


def validate_template(template: str) -> str:
    template = (template or "").strip()
    if not template:
        raise PromptError("The prompt is empty.")
    if len(template) > MAX_TEMPLATE_LENGTH:
        raise PromptError(f"The prompt is longer than {MAX_TEMPLATE_LENGTH} characters.")
    if "{context}" not in template:
        raise PromptError("The prompt must contain {context}, where the document passages go.")
    return template


def _clean_name(name: str) -> str:
    name = (name or "").strip()
    if not name:
        raise PromptError("Give the prompt a name.")
    return name[:255]


def list_prompts(session: Session, user_id: int) -> list[Prompt]:
    return (
        session.query(Prompt)
        .options(selectinload(Prompt.versions))
        .filter(Prompt.user_id == user_id)
        .order_by(Prompt.name, Prompt.id)
        .all()
    )


def get_prompt(session: Session, user_id: int, prompt_id: int) -> Prompt:
    prompt = (
        session.query(Prompt)
        .options(selectinload(Prompt.versions))
        .filter(Prompt.id == prompt_id, Prompt.user_id == user_id)
        .first()
    )
    if prompt is None:
        raise PromptNotFoundError("Prompt not found")
    return prompt


def get_version(session: Session, user_id: int, version_id: int) -> PromptVersion:
    """A prompt version the user owns."""
    version = (
        session.query(PromptVersion)
        .join(Prompt, PromptVersion.prompt_id == Prompt.id)
        .filter(PromptVersion.id == version_id, Prompt.user_id == user_id)
        .first()
    )
    if version is None:
        raise PromptNotFoundError("Prompt version not found")
    return version


def create_prompt(
    session: Session, user_id: int, name: str, template: str, description: str | None = None, note: str | None = None
) -> Prompt:
    prompt = Prompt(user_id=user_id, name=_clean_name(name), description=(description or "").strip() or None)
    prompt.versions.append(PromptVersion(version=1, template=validate_template(template), note=_note(note)))
    session.add(prompt)
    session.flush()
    return prompt


def update_prompt(session: Session, user_id: int, prompt_id: int, name: str | None = None, description: str | None = None) -> Prompt:
    prompt = get_prompt(session, user_id, prompt_id)
    if name is not None:
        prompt.name = _clean_name(name)
    if description is not None:
        prompt.description = description.strip() or None
    session.flush()
    return prompt


def add_version(session: Session, user_id: int, prompt_id: int, template: str, note: str | None = None) -> PromptVersion:
    prompt = get_prompt(session, user_id, prompt_id)
    latest = session.query(func.max(PromptVersion.version)).filter(PromptVersion.prompt_id == prompt.id).scalar() or 0
    version = PromptVersion(prompt_id=prompt.id, version=latest + 1, template=validate_template(template), note=_note(note))
    session.add(version)
    session.flush()
    return version


def clone_prompt(session: Session, user_id: int, prompt_id: int, name: str | None = None) -> Prompt:
    """A new prompt starting from the latest version of this one."""
    source = get_prompt(session, user_id, prompt_id)
    latest = source.versions[-1]
    return create_prompt(
        session, user_id, name or f"{source.name} (copy)", latest.template, source.description,
        note=f"Copied from {source.name} v{latest.version}",
    )


def delete_prompt(session: Session, user_id: int, prompt_id: int) -> None:
    """Delete a prompt and its versions; conversations and experiments using
    one fall back to the built-in prompt."""
    session.delete(get_prompt(session, user_id, prompt_id))
    session.flush()


def _note(note: str | None) -> str | None:
    return (note or "").strip()[:500] or None


def version_dict(version: PromptVersion) -> dict:
    return {
        "id": version.id,
        "version": version.version,
        "template": version.template,
        "note": version.note,
        "created_at": version.created_at,
    }


def prompt_dict(prompt: Prompt, with_versions: bool = False) -> dict:
    latest = prompt.versions[-1] if prompt.versions else None
    data = {
        "id": prompt.id,
        "name": prompt.name,
        "description": prompt.description,
        "created_at": prompt.created_at,
        "version_count": len(prompt.versions),
        "latest_version": version_dict(latest) if latest else None,
    }
    if with_versions:
        data["versions"] = [version_dict(v) for v in reversed(prompt.versions)]
    return data
