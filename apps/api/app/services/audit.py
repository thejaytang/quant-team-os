from typing import Any

from sqlalchemy.orm import Session

from app.core.redaction import contains_secret, redact_secrets
from app.db.models import AuditLog, SystemEvent


def write_system_event(db: Session, event_type: str, payload: dict[str, Any], severity: str = "info") -> SystemEvent:
    event = SystemEvent(event_type=event_type, severity=severity, payload=redact_secrets(payload))
    db.add(event)
    db.flush()
    return event


def write_audit_log(
    db: Session,
    action: str,
    target_type: str,
    target_id: str | None = None,
    payload: dict[str, Any] | None = None,
    actor: str = "system",
) -> AuditLog:
    clean_payload = redact_secrets(payload or {})
    if contains_secret(clean_payload):
        # Redaction is idempotent, so re-running it cannot remove a secret that
        # survived the first pass. Fail closed by dropping the payload entirely
        # rather than persisting a leaking value into the audit trail.
        write_system_event(db, "security_violation", {"action": action, "target_type": target_type}, "critical")
        clean_payload = {"redaction_incomplete": True, "action": action}
    log = AuditLog(actor=actor, action=action, target_type=target_type, target_id=target_id, payload=clean_payload)
    db.add(log)
    db.flush()
    return log
