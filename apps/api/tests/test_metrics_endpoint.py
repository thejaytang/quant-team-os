from datetime import date
from pathlib import Path

from app.db.models import Artifact, BacktestRun, ExternalConnection, PolicyDecision, ToolCall, WorkflowLink
from app.main import prometheus_metrics_text


def test_api_v1_probe_aliases_exist():
    source = (Path(__file__).resolve().parents[1] / "app" / "main.py").read_text(encoding="utf-8")

    assert '"/healthz"' in source
    assert '"/api/v1/healthz"' in source
    assert '"/metrics"' in source
    assert '"/api/v1/metrics"' in source


def test_metrics_text_exposes_prometheus_gauges():
    text = prometheus_metrics_text()
    assert "qto_app_info" in text
    assert "qto_live_trading_locked 1" in text
    assert "qto_tool_policy_denials_total" in text
    assert "qto_openai_cost_usd_total" in text
    assert "qto_workflow_runs_total" in text
    assert "qto_gx_validations_total" in text
    assert "qto_backtest_failures_total" in text
    assert "qto_connection_status" in text


def test_metrics_text_reflects_database_counts(db):
    db.add_all(
        [
            PolicyDecision(policy_package="agent", action="tool_call", allowed=False, input_payload={}, reasons=["denied"]),
            WorkflowLink(workflow_id="wf-1", workflow_type="ResearchWorkflow", owner_type="research_idea", owner_id="idea-1", status="running"),
            Artifact(artifact_type="gx_validation", owner_type="dataset", owner_id="dataset-1", content_type="application/json", checksum="sha256:ok", meta={"gx_success": True}),
            Artifact(artifact_type="gx_validation", owner_type="dataset", owner_id="dataset-2", content_type="application/json", checksum="sha256:bad", meta={"gx_success": False}),
            BacktestRun(strategy_id="strategy-1", dataset_spec_id="dataset-1", start_date=date(2024, 1, 1), end_date=date(2024, 1, 31), status="failed"),
            ExternalConnection(provider="massive", display_name="Massive Market Data", status="connected"),
            ToolCall(adapter_name="openai", tool_name="openai", risk_level="research_write", status="succeeded", output_payload={"cost_usd": 0.42}),
            ToolCall(adapter_name="openai", tool_name="openai", risk_level="research_write", status="failed", output_payload={}),
        ]
    )
    db.flush()

    text = prometheus_metrics_text(db)

    assert "qto_tool_policy_denials_total 1" in text
    assert 'qto_workflow_runs_total{status="running"} 1' in text
    assert "qto_openai_cost_usd_total 0.42" in text
    assert "qto_openai_errors_total 1" in text
    assert 'qto_gx_validations_total{result="passed"} 1' in text
    assert 'qto_gx_validations_total{result="failed"} 1' in text
    assert "qto_backtest_failures_total 1" in text
    assert 'qto_connection_status{provider="massive",status="connected"} 1' in text
