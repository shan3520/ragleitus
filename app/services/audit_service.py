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