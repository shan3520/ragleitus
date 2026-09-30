"""Named saved-search configurations, always scoped to their owner."""

from sqlalchemy.orm import Session

from app.models.document import SavedSearch


def list_saved_searches(session: Session, user_id: int) -> list[SavedSearch]:
    return session.query(SavedSearch).filter(SavedSearch.user_id == user_id).all()


def get_saved_search(session: Session, user_id: int, search_id: int) -> SavedSearch | None:
    return (
        session.query(SavedSearch)
        .filter(SavedSearch.id == search_id, SavedSearch.user_id == user_id)
        .first()
    )


def delete_saved_search(session: Session, user_id: int, search_id: int) -> bool:
    saved_search = get_saved_search(session, user_id, search_id)
    if saved_search is None:
        return False
    session.delete(saved_search)
    session.flush()
    return True


def upsert_saved_search(
    session: Session,
    user_id: int,
    search_name: str,
    query_text: str,
    applied_filters: dict | None,
) -> SavedSearch:
    saved_search = (
        session.query(SavedSearch)
        .filter(SavedSearch.user_id == user_id, SavedSearch.search_name == search_name)
        .first()
    )
    if saved_search is None:
        saved_search = SavedSearch(user_id=user_id, search_name=search_name)
        session.add(saved_search)
    saved_search.query_text = query_text
    saved_search.applied_filters = applied_filters
    session.flush()
    return saved_search
