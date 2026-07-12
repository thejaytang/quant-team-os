from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy.orm import Session

from app.core.redaction import redact_secrets
from app.db.models import ApprovalRecord, ApprovalRequest
from app.services.audit import write_audit_log
from app.services.policy import evaluate_policy
from app.services.temporal_client import signal_approval_resolved


def create_approval_request(
    db: Session,
    request_type: str,
    target_type: str,
    target_id: str,
    requested_by_agent: str,
    risk_summary: dict[str, Any],
    workflow_id: str | None = None,
) -> ApprovalRequest:
    decision = None
    if request_type == "unlock_live":
        decision = evaluate_policy(
            db,
            "approval",
            "create_request",
            {
                "action": "create_request",
                "request_type": request_type,
                "target_type": target_type,
                "target_id": target_id,
                "user": {"id": requested_by_agent, "roles": ["approver"]},
                "agent": {"service_account": False},
                "comment": "request live unlock",
            },
            actor=requested_by_agent,
            workflow_id=workflow_id,
        )
        status = "pending" if decision.allowed else "rejected"
        comment = None if decision.allowed else "; ".join(decision.reasons)
    else:
        status = "pending"
        comment = None
    request = ApprovalRequest(
        request_type=request_type,
        target_type=target_type,
        target_id=target_id,
        requested_by_agent=requested_by_agent,
        risk_summary=risk_summary,
        status=status,
        workflow_id=workflow_id,
        human_comment=comment,
        resolved_at=datetime.now(UTC) if status == "rejected" else None,
    )
    db.add(request)
    db.flush()
    write_audit_log(db, "approval.request_created", "approval_request", request.id, {"request_type": request_type, "status": status})
    return request


def resolve_approval(
    db: Session,
    approval_request_id: str,
    action: str,
    human_comment: str,
    human_actor: str = "local_user",
    human_roles: set[str] | None = None,
    service_account: bool = False,
) -> ApprovalRequest:
    raw_comment = human_comment.strip()
    if not raw_comment:
        raise ValueError("human comment is required")
    if action not in {"approved", "rejected", "changes_requested"}:
        raise ValueError(f"unsupported approval action: {action}")
    request = db.get(ApprovalRequest, approval_request_id)
    if not request:
        raise ValueError("approval request not found")
    decision = evaluate_policy(
        db,
        "approval",
        action,
        {
            "action": action,
            "request_type": request.request_type,
            "target_type": request.target_type,
            "target_id": request.target_id,
            "user": {"id": human_actor, "roles": sorted(human_roles or set(_roles_for_actor(human_actor)))},
            "agent": {"service_account": service_account},
            "comment": raw_comment,
        },
        actor=human_actor,
        workflow_id=request.workflow_id,
    )
    if not decision.allowed:
        raise PermissionError("; ".join(decision.reasons))
    if request.status != "pending":
        raise ValueError(f"approval request is {request.status}")

    request.status = action
    stored_comment = redact_secrets(raw_comment)
    request.human_comment = stored_comment
    request.resolved_at = datetime.now(UTC)
    record = ApprovalRecord(
        approval_request_id=request.id,
        action=request.status,
        human_actor=human_actor,
        human_comment=stored_comment,
    )
    db.add(record)
    db.flush()

    if request.workflow_id:
        signal_payload = {"approval_request_id": request.id, "action": action, "comment": stored_comment, "actor": human_actor}
        db.commit()
        try:
            signal_approval_resolved(db, request.workflow_id, signal_payload, actor=human_actor)
        except Exception:
            db.rollback()
            request = db.get(ApprovalRequest, approval_request_id)
            if request:
                request.status = "pending"
                request.human_comment = None
                request.resolved_at = None
            stored_record = db.get(ApprovalRecord, record.id)
            if stored_record:
                db.delete(stored_record)
            db.commit()
            raise

    write_audit_log(db, f"approval.{request.status}", "approval_request", request.id, {"comment": stored_comment}, actor=human_actor)
    db.flush()
    return request


def _roles_for_actor(actor: str) -> list[str]:
    if actor in {"local_user", "admin", "approver"}:
        return ["approver"]
    return ["viewer"]
