from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models.audit_log import AuditLog
from app.models.evaluation import Base
from app.services import audit_service


class _FailingSession:
    def add(self, audit_log):
        pass

    def commit(self):
        raise RuntimeError("database is down")

    def close(self):
        pass


def test_log_audit_event_swallows_database_errors():
    with patch.object(audit_service, "SessionLocal", lambda: _FailingSession()):
        audit_service.log_audit_event("document_deleted", document_id=42)


def test_log_audit_event_persists_audit_log():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()

    with patch.object(audit_service, "SessionLocal", sessionmaker(bind=engine)):
        audit_service.log_audit_event("document_deleted", document_id=42)

    rows = session.query(AuditLog).all()
    session.close()

    assert len(rows) == 1
    assert rows[0].action == "document_deleted"
    assert rows[0].document_id == 42
    assert rows[0].timestamp is not None


def test_audit_log_document_id_has_no_foreign_key():
    column = AuditLog.__table__.columns["document_id"]
    assert not column.foreign_keys