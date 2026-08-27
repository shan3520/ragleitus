from app.db.database import SessionLocal
from app.models.audit_log import AuditLog


def log_audit_event(action: str, document_id: int = None):
    session = SessionLocal()
    try:
        audit_log = AuditLog(action=action, document_id=document_id)
        session.add(audit_log)
        session.commit()
    except Exception:
        pass
    finally:
        session.close()


def get_audit_logs(db, entity_id: str | None = None, entity_type: str | None = None, action_type: str | None = None, limit: int = 20, offset: int = 0):
    query = db.query(AuditLog)

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