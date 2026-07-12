from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.compat import APIRouter, Depends, Query
from app.core.auth import require_any_role
from app.core.redaction import redact_secrets
from app.db.models import ApprovalRecord, ApprovalRequest, AuditLog, PolicyDecision, SystemEvent, ToolCall
from app.db.session import get_db

router = APIRouter(prefix="/api/v1", tags=["audit"])

# Bound list responses so an ever-growing audit trail cannot exhaust memory or
# produce unbounded payloads. Callers may lower the limit; the cap is fixed.
DEFAULT_LIMIT = 500
MAX_LIMIT = 2000


def _resolve_limit(limit: object) -> int:
    """Coerce and clamp the limit. Works for HTTP-bound ints and for direct
    function calls (tests) where the parameter keeps its Query default sentinel."""
    try:
        value = int(limit)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return DEFAULT_LIMIT
    return max(1, min(value, MAX_LIMIT))


@router.get("/audit-logs")
def list_audit_logs(
    db: Session = Depends(get_db),
    limit: int = Query(DEFAULT_LIMIT, ge=1, le=MAX_LIMIT),
    _user=Depends(require_any_role("admin", "risk_reviewer")),
):
    limit = _resolve_limit(limit)
    logs = db.scalars(select(AuditLog).order_by(AuditLog.created_at.desc()).limit(limit)).all()
    tool_calls = db.scalars(select(ToolCall).order_by(ToolCall.created_at.desc()).limit(limit)).all()
    policies = db.scalars(select(PolicyDecision).order_by(PolicyDecision.created_at.desc()).limit(limit)).all()
    approvals = db.scalars(select(ApprovalRequest).order_by(ApprovalRequest.created_at.desc()).limit(limit)).all()
    approval_records = db.scalars(select(ApprovalRecord).order_by(ApprovalRecord.created_at.desc()).limit(limit)).all()
    events = [
        *[_audit_log_event(row) for row in logs],
        *[_tool_call_event(row) for row in tool_calls],
        *[_policy_decision_event(row) for row in policies],
        *[_approval_request_event(row) for row in approvals],
        *[_approval_record_event(row) for row in approval_records],
    ]
    return sorted(events, key=_event_sort_key, reverse=True)[:limit]


@router.get("/tool-calls")
def list_tool_calls(
    db: Session = Depends(get_db),
    limit: int = Query(DEFAULT_LIMIT, ge=1, le=MAX_LIMIT),
    _user=Depends(require_any_role("admin", "risk_reviewer")),
):
    return db.scalars(select(ToolCall).order_by(ToolCall.created_at.desc()).limit(_resolve_limit(limit))).all()


@router.get("/system-events")
def list_system_events(
    db: Session = Depends(get_db),
    limit: int = Query(DEFAULT_LIMIT, ge=1, le=MAX_LIMIT),
    _user=Depends(require_any_role("admin", "risk_reviewer")),
):
    return db.scalars(select(SystemEvent).order_by(SystemEvent.created_at.desc()).limit(_resolve_limit(limit))).all()


@router.get("/policy-decisions")
def list_policy_decisions(
    db: Session = Depends(get_db),
    limit: int = Query(DEFAULT_LIMIT, ge=1, le=MAX_LIMIT),
    _user=Depends(require_any_role("admin", "risk_reviewer")),
):
    return db.scalars(select(PolicyDecision).order_by(PolicyDecision.created_at.desc()).limit(_resolve_limit(limit))).all()


def _event_sort_key(item: dict) -> str:
    value = item.get("created_at")
    return value.isoformat() if hasattr(value, "isoformat") else str(value or "")


def _audit_log_event(row: AuditLog) -> dict:
    return {
        "id": row.id,
        "event_source": "audit_log",
        "actor": row.actor,
        "action": row.action,
        "target_type": row.target_type,
        "target_id": row.target_id,
        "payload": redact_secrets(row.payload),
        "created_at": row.created_at,
        "updated_at": row.updated_at,
    }


def _tool_call_event(row: ToolCall) -> dict:
    return {
        "id": row.id,
        "event_source": "tool_call",
        "actor": row.agent_run_id or "agent",
        "action": f"tool_call.{row.status}",
        "target_type": row.adapter_name,
        "target_id": row.id,
        "payload": {
            "tool_name": row.tool_name,
            "risk_level": row.risk_level,
            "input_payload": redact_secrets(row.input_payload),
            "output_payload": redact_secrets(row.output_payload),
            "error": redact_secrets(row.error),
        },
        "created_at": row.created_at,
        "updated_at": row.updated_at,
    }


def _policy_decision_event(row: PolicyDecision) -> dict:
    return {
        "id": row.id,
        "event_source": "policy_decision",
        "actor": row.actor,
        "action": f"policy_decision.{'allowed' if row.allowed else 'denied'}",
        "target_type": row.policy_package,
        "target_id": row.id,
        "payload": {
            "policy_package": row.policy_package,
            "policy_action": row.action,
            "allowed": row.allowed,
            "reasons": redact_secrets(row.reasons),
            "workflow_id": row.workflow_id,
            "input_payload": redact_secrets(row.input_payload),
        },
        "created_at": row.created_at,
        "updated_at": row.updated_at,
    }


def _approval_request_event(row: ApprovalRequest) -> dict:
    return {
        "id": row.id,
        "event_source": "approval_request",
        "actor": row.requested_by_agent,
        "action": f"approval_request.{row.status}",
        "target_type": row.target_type,
        "target_id": row.target_id,
        "payload": {
            "request_type": row.request_type,
            "risk_summary": redact_secrets(row.risk_summary),
            "workflow_id": row.workflow_id,
            "human_comment": redact_secrets(row.human_comment),
            "resolved_at": row.resolved_at,
        },
        "created_at": row.created_at,
        "updated_at": row.updated_at,
    }


def _approval_record_event(row: ApprovalRecord) -> dict:
    return {
        "id": row.id,
        "event_source": "approval_record",
        "actor": row.human_actor,
        "action": f"approval.{row.action}",
        "target_type": "approval_request",
        "target_id": row.approval_request_id,
        "payload": {"human_comment": redact_secrets(row.human_comment)},
        "created_at": row.created_at,
        "updated_at": row.updated_at,
    }
