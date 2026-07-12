import pytest

from app.adapters.base import AdapterRegistry, AdapterRunner, PolicyDenied, ToolContext, ToolResult
from app.adapters.stubs import BaseStubAdapter, default_registry
from app.db.models import AuditLog, ExternalConnection, PolicyDecision, ToolCall
from app.services.connections import seed_connections


class LeakyOutputAdapter(BaseStubAdapter):
    name = "report_artifact"

    def run(self, db, payload, context):
        return ToolResult(ok=True, output={"note": "sk-testsecret1234"})


class LeakyExceptionAdapter(BaseStubAdapter):
    name = "report_artifact"

    def run(self, db, payload, context):
        raise RuntimeError("upstream returned sk-testsecret1234")


def _registry_with(adapter):
    registry = AdapterRegistry()
    registry.register(adapter)
    return registry


def test_tool_gateway_writes_policy_decision(db):
    runner = AdapterRunner(default_registry())
    result = runner.run(db, "qlib", {"research": "momentum"}, ToolContext(actor="ResearchAgent", agent_run_id="wf-1"))
    db.commit()
    assert result.ok is True
    decision = db.query(PolicyDecision).filter_by(policy_package="agent").one()
    assert decision.policy_package == "agent"
    assert decision.allowed is True
    assert decision.workflow_id == "wf-1"
    connector_decision = db.query(PolicyDecision).filter_by(policy_package="connector").one()
    assert connector_decision.allowed is True
    log = db.query(AuditLog).filter_by(action="tool_call.finished").one()
    assert log.payload["observability"]["adapter"] == "qlib"


def test_tool_gateway_denies_disconnected_connector(db):
    seed_connections(db)
    runner = AdapterRunner(default_registry())
    with pytest.raises(PolicyDenied, match="connector is not connected"):
        runner.run(db, "massive", {"symbol": "SPY"}, ToolContext(actor="DataAgent", agent_run_id="wf-2"))
    db.commit()
    denied = db.query(PolicyDecision).filter_by(policy_package="connector").one()
    assert denied.allowed is False
    assert "connector is not connected" in denied.reasons
    call = db.query(ToolCall).filter_by(adapter_name="massive").one()
    assert call.status == "failed"
    assert "connector is not connected" in call.error


def test_tool_gateway_denies_value_level_secret_before_redaction(db):
    runner = AdapterRunner(default_registry())
    with pytest.raises(PolicyDenied, match="secret must not be present in tool payload"):
        runner.run(db, "qlib", {"note": "sk-testsecret1234"}, ToolContext(actor="ResearchAgent", agent_run_id="wf-secret-deny"))
    db.commit()

    denied = db.query(PolicyDecision).filter_by(policy_package="connector").one()
    assert denied.allowed is False
    assert denied.input_payload["payload"]["note"] == "[REDACTED_SECRET]"
    assert denied.input_payload["payload_meta"]["sensitive_value_present"] is True
    assert "sk-testsecret1234" not in str(denied.input_payload)
    call = db.query(ToolCall).filter_by(adapter_name="qlib").one()
    assert call.status == "failed"
    assert call.error == "secret must not be present in tool payload"


def test_tool_gateway_denies_common_secret_key_before_redaction(db):
    runner = AdapterRunner(default_registry())
    with pytest.raises(PolicyDenied, match="secret must not be present in tool payload"):
        runner.run(db, "qlib", {"client_secret": "client-secret-value"}, ToolContext(actor="ResearchAgent", agent_run_id="wf-client-secret-deny"))
    db.commit()

    denied = db.query(PolicyDecision).filter_by(policy_package="connector").one()
    assert denied.allowed is False
    assert denied.input_payload["payload"]["client_secret"].startswith("****")
    assert "client-secret-value" not in str(denied.input_payload)
    call = db.query(ToolCall).filter_by(adapter_name="qlib").one()
    assert call.status == "failed"


def test_tool_gateway_denies_agent_tool_not_in_matrix(db):
    seed_connections(db)
    connection = db.query(ExternalConnection).filter_by(provider="quantconnect").one()
    connection.status = "connected"
    runner = AdapterRunner(default_registry())

    with pytest.raises(PolicyDenied, match="agent is not allowed to call this tool"):
        runner.run(db, "quantconnect_paper", {"strategy_id": "strategy-1"}, ToolContext(actor="ResearchAgent", agent_run_id="wf-wrong-agent"))
    db.commit()

    denied = db.query(PolicyDecision).filter_by(policy_package="agent", allowed=False).one()
    assert "agent is not allowed to call this tool" in denied.reasons


def test_tool_gateway_denies_untrusted_payload_secret_ref(db):
    runner = AdapterRunner(default_registry())

    with pytest.raises(PolicyDenied, match="secret refs must be resolved by trusted service adapters"):
        runner.run(db, "qlib", {"infisical_secret_ref": "/quant-team-os/dev/connections/openai"}, ToolContext(actor="ResearchAgent", agent_run_id="wf-ref-deny"))
    db.commit()

    denied = db.query(PolicyDecision).filter_by(policy_package="connector", allowed=False).one()
    assert "secret refs must be resolved by trusted service adapters" in denied.reasons


def test_tool_gateway_does_not_register_approval_adapter(db):
    with pytest.raises(KeyError, match="unknown adapter: approval"):
        default_registry().get("approval")


def test_tool_gateway_redacts_adapter_output_before_return_and_storage(db):
    runner = AdapterRunner(_registry_with(LeakyOutputAdapter()))
    result = runner.run(db, "report_artifact", {}, ToolContext(actor="ReportAgent", agent_run_id="wf-leaky-output"))
    db.commit()

    assert result.ok is True
    assert result.output["note"] == "[REDACTED_SECRET]"
    assert "sk-testsecret1234" not in str(result.output)
    call = db.query(ToolCall).filter_by(adapter_name="report_artifact").one()
    assert call.output_payload["note"] == "[REDACTED_SECRET]"


def test_tool_gateway_redacts_adapter_exception_before_return_and_audit(db):
    runner = AdapterRunner(_registry_with(LeakyExceptionAdapter()))
    result = runner.run(db, "report_artifact", {}, ToolContext(actor="ReportAgent", agent_run_id="wf-leaky-error"))
    db.commit()

    assert result.ok is False
    assert result.error == "upstream returned [REDACTED_SECRET]"
    assert "sk-testsecret1234" not in result.error
    call = db.query(ToolCall).filter_by(adapter_name="report_artifact").one()
    log = db.query(AuditLog).filter_by(action="tool_call.failed").one()
    assert call.error == "upstream returned [REDACTED_SECRET]"
    assert "sk-testsecret1234" not in str(log.payload)
