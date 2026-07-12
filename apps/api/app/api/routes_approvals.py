from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.compat import APIRouter, Depends, HTTPException
from app.core.auth import CurrentUser, require_role
from app.core.redaction import redact_secrets
from app.db.models import ApprovalRequest
from app.db.session import get_db
from app.schemas import ApprovalResolveRequest
from app.services.approval_service import resolve_approval

router = APIRouter(prefix="/api/v1/approvals", tags=["approvals"])


@router.get("")
def list_approvals(db: Session = Depends(get_db)):
    return [_public_approval(row) for row in db.scalars(select(ApprovalRequest).order_by(ApprovalRequest.created_at.desc())).all()]


@router.get("/{approval_id}")
def get_approval(approval_id: str, db: Session = Depends(get_db)):
    request = db.get(ApprovalRequest, approval_id)
    if not request:
        raise HTTPException(status_code=404, detail="approval request not found")
    return _public_approval(request)


@router.post("/{approval_id}/approve")
def approve(approval_id: str, payload: ApprovalResolveRequest, db: Session = Depends(get_db), user: CurrentUser = Depends(require_role("approver"))):
    try:
        return resolve_approval(db, approval_id, "approved", payload.human_comment, user.username, user.roles, service_account=user.service_account)
    except (ValueError, PermissionError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/{approval_id}/reject")
def reject(approval_id: str, payload: ApprovalResolveRequest, db: Session = Depends(get_db), user: CurrentUser = Depends(require_role("approver"))):
    try:
        return resolve_approval(db, approval_id, "rejected", payload.human_comment, user.username, user.roles, service_account=user.service_account)
    except (ValueError, PermissionError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/{approval_id}/request-changes")
def request_changes(approval_id: str, payload: ApprovalResolveRequest, db: Session = Depends(get_db), user: CurrentUser = Depends(require_role("approver"))):
    try:
        return resolve_approval(db, approval_id, "changes_requested", payload.human_comment, user.username, user.roles, service_account=user.service_account)
    except (ValueError, PermissionError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


def _public_approval(row: ApprovalRequest) -> dict:
    policy_lock_reason = _policy_lock_reason(row)
    actions = ["reject", "request-changes"]
    if not policy_lock_reason:
        actions.insert(0, "approve")
    return {
        "id": row.id,
        "request_type": row.request_type,
        "target_type": row.target_type,
        "target_id": row.target_id,
        "requested_by_agent": row.requested_by_agent,
        "risk_summary": redact_secrets(row.risk_summary),
        "status": row.status,
        "workflow_id": row.workflow_id,
        "human_comment": redact_secrets(row.human_comment),
        "resolved_at": row.resolved_at,
        "created_at": row.created_at,
        "updated_at": row.updated_at,
        "policy_lock_reason": policy_lock_reason,
        "allowed_actions": actions if row.status == "pending" else [],
    }


def _policy_lock_reason(row: ApprovalRequest) -> str | None:
    if row.request_type == "unlock_live":
        return "Live trading is locked by OPA"
    return None
