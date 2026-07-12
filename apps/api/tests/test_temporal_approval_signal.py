import pytest

from app.core.config import get_settings
from app.db.models import ApprovalRecord, AuditLog
from app.services.approval_service import create_approval_request, resolve_approval


def test_workflow_backed_approval_sends_temporal_signal_fallback(db):
    request = create_approval_request(db, "memo_review", "strategy", "s1", "ChiefAgent", {}, workflow_id="wf-approval-1")
    resolve_approval(db, request.id, "approved", "reviewed", human_actor="local_user")
    db.commit()

    record = db.query(ApprovalRecord).one()
    assert record.action == "approved"
    assert db.query(AuditLog).filter(AuditLog.action.in_(["workflow.signal_sent", "workflow.signal_fallback"])).count() == 1


def test_request_changes_status_is_preserved(db):
    request = create_approval_request(db, "memo_review", "strategy", "s1", "ChiefAgent", {}, workflow_id="wf-approval-2")
    result = resolve_approval(db, request.id, "changes_requested", "revise risk memo", human_actor="local_user")
    db.commit()

    assert result.status == "changes_requested"
    record = db.query(ApprovalRecord).one()
    assert record.action == "changes_requested"


def test_service_account_cannot_resolve_approval_even_with_approver_role(db):
    request = create_approval_request(db, "memo_review", "strategy", "s1", "ResearchService", {}, workflow_id=None)

    with pytest.raises(PermissionError, match="agent service account cannot resolve approval"):
        resolve_approval(
            db,
            request.id,
            "approved",
            "service account cannot approve",
            human_actor="automation-client",
            human_roles={"approver"},
            service_account=True,
        )

    assert request.status == "pending"
    assert db.query(ApprovalRecord).count() == 0


def test_strict_temporal_signal_failure_keeps_request_pending(db, monkeypatch):
    monkeypatch.setenv("ALLOW_TEMPORAL_FALLBACK", "false")
    get_settings.cache_clear()
    request = create_approval_request(db, "memo_review", "strategy", "s1", "ChiefAgent", {}, workflow_id="wf-missing")

    try:
        with pytest.raises(RuntimeError):
            resolve_approval(db, request.id, "approved", "reviewed", human_actor="local_user")
        assert request.status == "pending"
        assert db.query(ApprovalRecord).count() == 0
    finally:
        get_settings.cache_clear()
