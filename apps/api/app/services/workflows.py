from __future__ import annotations

from typing import Any
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.redaction import redact_secrets
from app.db.models import AuditLog, WorkflowLink
from app.services.audit import write_audit_log
from app.services.temporal_client import cancel_temporal_workflow, start_temporal_workflow


def start_workflow(
    db: Session,
    workflow_type: str,
    owner_type: str,
    owner_id: str,
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    workflow_id = f"{workflow_type}-{owner_id}-{uuid4()}"
    link = WorkflowLink(
        workflow_id=workflow_id,
        workflow_type=workflow_type,
        owner_type=owner_type,
        owner_id=owner_id,
        status="started",
        meta={"input": redact_secrets(payload or {})},
    )
    db.add(link)
    write_audit_log(db, "workflow.started", owner_type, owner_id, {"workflow_id": workflow_id, "workflow_type": workflow_type})
    workflow_payload = {**(payload or {}), "workflow_id": workflow_id, "workflow_type": workflow_type, "owner_type": owner_type, "owner_id": owner_id}
    temporal_result = start_temporal_workflow(db, workflow_type, workflow_id, workflow_payload)
    link.meta = {**(link.meta or {}), "temporal": temporal_result}
    if temporal_result.get("mode") == "local_fallback":
        link.status = "temporal_unavailable"
    db.flush()
    return {
        "workflow_id": workflow_id,
        "workflow_type": workflow_type,
        "owner_type": owner_type,
        "owner_id": owner_id,
        "status": link.status,
    }


def cancel_workflow(db: Session, link: WorkflowLink, actor: str) -> dict[str, Any]:
    temporal_result = cancel_temporal_workflow(db, link.workflow_id, actor)
    link.status = "cancel_requested"
    link.meta = {**(link.meta or {}), "last_temporal_event": temporal_result}
    db.flush()
    return {
        "workflow_id": link.workflow_id,
        "workflow_type": link.workflow_type,
        "owner_type": link.owner_type,
        "owner_id": link.owner_id,
        "status": link.status,
        "temporal": temporal_result,
    }


def workflow_event_log(db: Session, workflow_id: str) -> list[dict[str, Any]]:
    rows = db.scalars(select(AuditLog).order_by(AuditLog.created_at.asc())).all()
    events = []
    for row in rows:
        payload = row.payload or {}
        if row.target_id != workflow_id and payload.get("workflow_id") != workflow_id:
            continue
        events.append(
            {
                "id": row.id,
                "type": row.action,
                "actor": row.actor,
                "target_type": row.target_type,
                "target_id": row.target_id,
                "payload": payload,
                "created_at": row.created_at,
            }
        )
    return events
