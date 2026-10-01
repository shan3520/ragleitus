import logging

from app.db.database import SessionLocal
from app.models.audit_log import AuditLog

logger = logging.getLogger(__name__)


def log_audit_event(action: str, user_id: int | None = None, document_id: int = None):
    """Record an audit event in its own session.

    Meant to run as a FastAPI background task after the response is sent, so
    a failure here must not surface to the caller; it is logged instead of
    being silently dropped.
    """
    session = SessionLocal()
    try:
        audit_log = AuditLog(action=action, user_id=user_id, document_id=document_id)
        session.add(audit_log)
        session.commit()
    except Exception:
        session.rollback()
        logger.exception("Failed to record audit event", extra={"action": action})
    finally:
        session.close()


def get_audit_logs(db, entity_id: str | None = None, entity_type: str | None = None, action_type: str | None = None, limit: int = 20, offset: int = 0, user_id: int | None = None):
    query = db.query(AuditLog)

    if user_id is not None:
        query = query.filter(AuditLog.user_id == user_id)

    if entity_id is not None:
        query = query.filter(AuditLog.document_id == entity_id)

    if action_type is not None:
        query = query.filter(AuditLog.action == action_type)

    total = query.count()

    logs = (
        query
        .order_by(AuditLog.timestamp.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )

    return logs, total
