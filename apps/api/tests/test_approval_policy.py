import pytest

from app.api.routes_approvals import list_approvals
from app.api.routes_audit import list_audit_logs
from app.core.config import get_settings
from app.db.models import ApprovalRecord, ApprovalRequest, AuditLog, PolicyDecision
from app.services.approval_service import create_approval_request, resolve_approval
from app.services.policy import evaluate_policy


def test_approval_resolution_writes_policy_decision(db):
    request = create_approval_request(db, "memo_review", "strategy", "s1", "ChiefAgent", {})
    resolve_approval(db, request.id, "approved", "reviewed", human_actor="local_user")
    db.commit()
    decision = db.query(PolicyDecision).filter_by(policy_package="approval").one()
    assert decision.allowed is True
    assert decision.actor == "local_user"
    audit = db.query(AuditLog).filter_by(action="policy_decision.allowed", target_id=decision.id).one()
    assert audit.payload["policy_package"] == "approval"


def test_approval_requires_approver_role(db):
    request = create_approval_request(db, "memo_review", "strategy", "s1", "ChiefAgent", {})
    with pytest.raises(PermissionError, match="approver role is required"):
        resolve_approval(db, request.id, "approved", "reviewed", human_actor="viewer")


def test_approval_rejects_blank_human_comment(db):
    request = create_approval_request(db, "memo_review", "strategy", "s1", "ChiefAgent", {})

    with pytest.raises(ValueError, match="human comment is required"):
        resolve_approval(db, request.id, "approved", "   ", human_actor="local_user")

    assert request.status == "pending"
    assert request.human_comment is None
    assert db.query(ApprovalRecord).count() == 0


def test_approval_comment_redacts_secrets_in_records_and_audit(db):
    request = create_approval_request(db, "memo_review", "strategy", "s1", "ChiefAgent", {})
    secret = "sk-testsecret1234567890"
    comment = f"approve with api_key={secret} and Bearer abcdefghijklmnopqrstuvwxyz"

    result = resolve_approval(db, request.id, "approved", comment, human_actor="local_user")
    db.commit()

    record = db.query(ApprovalRecord).filter_by(approval_request_id=request.id).one()
    audit = db.query(AuditLog).filter_by(action="approval.approved", target_id=request.id).one()
    audit_events = list_audit_logs(db=db)
    stored_request = db.get(ApprovalRequest, request.id)
    approval_rows = list_approvals(db)[0]
    serialized = str({
        "request": stored_request.human_comment,
        "record": record.human_comment,
        "audit_payload": audit.payload,
        "audit_events": audit_events,
        "approval_rows": approval_rows,
    })

    assert secret not in serialized
    assert "api_key=sk-testsecret1234567890" not in serialized
    assert "Bearer abcdefghijklmnopqrstuvwxyz" not in serialized
    assert "[REDACTED_SECRET]" in result.human_comment
    assert result.human_comment == record.human_comment
    assert audit.payload["comment"] == result.human_comment


def test_approval_and_audit_lists_redact_legacy_plaintext_comments(db):
    secret = "sk-legacysecret1234567890"
    comment = f"legacy api_key={secret} Bearer abcdefghijklmnopqrstuvwxyz"
    request = ApprovalRequest(
        request_type="register_strategy",
        target_type="strategy",
        target_id="s1",
        requested_by_agent="ChiefAgent",
        risk_summary={"api_key": secret},
        status="approved",
        human_comment=comment,
    )
    db.add(request)
    db.flush()
    db.add(ApprovalRecord(approval_request_id=request.id, action="approved", human_actor="local_user", human_comment=comment))
    db.add(AuditLog(actor="local_user", action="approval.approved", target_type="approval_request", target_id=request.id, payload={"comment": comment}))
    db.commit()

    serialized = str({
        "approvals": list_approvals(db),
        "audit_events": list_audit_logs(db=db),
    })

    assert secret not in serialized
    assert "api_key=sk-legacysecret1234567890" not in serialized
    assert "Bearer abcdefghijklmnopqrstuvwxyz" not in serialized
    assert "abcdefghijklmnopqrstuvwxyz" not in serialized
    assert "[REDACTED_SECRET]" in serialized


def test_approval_list_exposes_backend_policy_lock_for_live_unlock(db):
    request = ApprovalRequest(
        request_type="unlock_live",
        target_type="broker",
        target_id="ibkr",
        requested_by_agent="PortfolioAgent",
        risk_summary={},
        status="pending",
    )
    db.add(request)
    db.flush()

    row = list_approvals(db)[0]

    assert row["id"] == request.id
    assert row["policy_lock_reason"] == "Live trading is locked by OPA"
    assert "approve" not in row["allowed_actions"]
    assert {"reject", "request-changes"}.issubset(set(row["allowed_actions"]))


def test_unlock_live_request_is_rejected_by_opa_policy(db):
    request = create_approval_request(db, "unlock_live", "strategy", "s1", "ExecutionAgent", {})

    assert request.status == "rejected"
    assert request.human_comment == "Live trading is locked by OPA"
    decision = db.query(PolicyDecision).filter_by(policy_package="approval", action="create_request").one()
    assert decision.allowed is False
    assert decision.reasons == ["Live trading is locked by OPA"]


def test_unlock_live_approval_attempt_writes_opa_deny(db):
    request = create_approval_request(db, "unlock_live", "strategy", "s1", "ExecutionAgent", {})

    with pytest.raises(PermissionError, match="Live trading is locked by OPA"):
        resolve_approval(db, request.id, "approved", "reviewed", human_actor="local_user")

    decisions = db.query(PolicyDecision).filter_by(policy_package="approval").order_by(PolicyDecision.created_at).all()
    assert [decision.action for decision in decisions] == ["create_request", "approved"]
    assert decisions[-1].allowed is False
    assert decisions[-1].reasons == ["Live trading is locked by OPA"]


def test_strict_opa_mode_rejects_local_policy_fallback(db, monkeypatch):
    monkeypatch.setenv("ALLOW_LOCAL_POLICY_FALLBACK", "false")
    monkeypatch.setenv("OPA_URL", "http://127.0.0.1:9")
    get_settings.cache_clear()

    try:
        with pytest.raises(RuntimeError, match="OPA policy evaluation failed"):
            evaluate_policy(db, "approval", "approve", {"user": {"roles": ["approver"]}, "comment": "reviewed"})
        assert db.query(PolicyDecision).count() == 0
    finally:
        get_settings.cache_clear()


def test_ui_surface_policy_denies_direct_core_mutation(db):
    chainlit = evaluate_policy(db, "ui_surface", "set_strategy_status", {"surface": "chainlit", "action": "set_strategy_status", "target_type": "strategy"})
    openbb = evaluate_policy(db, "ui_surface", "update_strategy", {"surface": "openbb", "action": "update_strategy", "target_type": "strategy"})
    grafana_read = evaluate_policy(db, "ui_surface", "read", {"surface": "grafana", "action": "read", "target_type": "strategy"})

    assert chainlit.allowed is False
    assert "Chainlit cannot directly mutate core state" in chainlit.reasons
    assert openbb.allowed is False
    assert "external workspace is read-only for core state" in openbb.reasons
    assert grafana_read.allowed is True
