from app.adapters.base import AdapterRunner, ToolContext
from app.adapters.stubs import default_registry
from app.api.routes_audit import MAX_LIMIT, _resolve_limit, list_audit_logs, list_tool_calls
from app.db.models import ApprovalRecord, ApprovalRequest, AuditLog, PolicyDecision, ToolCall
from app.services.connections import seed_connections, validate_provider_connection


def test_tool_call_always_creates_rows(db):
    runner = AdapterRunner(default_registry())
    runner.run(db, "qlib", {"mode": "sample"}, ToolContext(actor="ResearchAgent", agent_run_id="run-1"))
    db.commit()
    assert db.query(ToolCall).count() == 1
    assert db.query(AuditLog).filter_by(action="tool_call.finished").count() == 1


def test_failed_connection_test_creates_audit(db):
    seed_connections(db)
    validate_provider_connection(db, "massive")
    db.commit()
    assert db.query(AuditLog).filter_by(action="connection.test_failed").count() == 1


def test_audit_logs_endpoint_aggregates_tool_policy_and_approval_events(db):
    db.add(ToolCall(adapter_name="openai", tool_name="openai", risk_level="research_write", status="succeeded", input_payload={}, output_payload={}))
    db.add(PolicyDecision(policy_package="agent", action="tool_call", allowed=False, input_payload={}, reasons=["denied"], actor="OPA"))
    request = ApprovalRequest(request_type="register_strategy", target_type="strategy", target_id="s1", requested_by_agent="ChiefAgent", risk_summary={}, status="approved")
    db.add(request)
    db.flush()
    db.add(ApprovalRecord(approval_request_id=request.id, action="approved", human_actor="local_user", human_comment="ok"))
    db.commit()

    events = list_audit_logs(db=db)
    sources = {event["event_source"] for event in events}

    assert {"tool_call", "policy_decision", "approval_request", "approval_record"}.issubset(sources)
    assert any(event["action"] == "policy_decision.denied" for event in events)
    assert any(event["action"] == "approval.approved" for event in events)


def test_resolve_limit_clamps_and_defaults():
    assert _resolve_limit(10) == 10
    assert _resolve_limit(0) == 1
    assert _resolve_limit(10_000) == MAX_LIMIT
    assert _resolve_limit("not-an-int") == 500  # DEFAULT_LIMIT for non-int (direct call default)


def test_tool_calls_endpoint_respects_limit(db):
    for _ in range(5):
        db.add(ToolCall(adapter_name="openai", tool_name="openai", risk_level="research_write", status="succeeded", input_payload={}, output_payload={}))
    db.commit()
    assert len(list_tool_calls(db=db, limit=2)) == 2


def test_audit_drops_payload_when_secret_survives_redaction(db, monkeypatch):
    from app.db.models import SystemEvent
    from app.services import audit

    # Simulate a residual-secret detection that redaction could not clear.
    monkeypatch.setattr(audit, "contains_secret", lambda _payload: True)

    log = audit.write_audit_log(db, "tool_call.finished", "tool_call", "t1", {"api_key": "sk-leakedsecret1234"}, actor="tester")
    db.commit()

    assert log.payload == {"redaction_incomplete": True, "action": "tool_call.finished"}
    assert "sk-leakedsecret1234" not in str(log.payload)
    assert db.query(SystemEvent).filter_by(event_type="security_violation").count() == 1
