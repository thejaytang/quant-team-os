import ast
from pathlib import Path

import pytest

from app.adapters.base import AdapterRunner, PolicyDenied, ToolContext
from app.adapters.stubs import QuantConnectMCPAdapter, QuantConnectPaperAdapter, default_registry
from app.db.models import AuditLog, ExternalConnection, PolicyDecision, ToolCall

PROJECT_ROOT = Path(__file__).resolve().parents[3]
BANNED_DIRECT_SDK_IMPORTS = {
    "alphalens",
    "boto3",
    "duckdb",
    "dvc",
    "great_expectations",
    "ib_insync",
    "ibapi",
    "langfuse",
    "massive",
    "mlflow",
    "openai",
    "quantconnect",
    "quantstats",
    "qlib",
}


def test_agent_tool_call_must_go_through_runner(db):
    runner = AdapterRunner(default_registry())
    with pytest.raises(PolicyDenied, match="secret must not be present in tool payload"):
        runner.run(db, "qlib", {"api_key": "sk-testsecret1234"}, ToolContext(actor="ResearchAgent", agent_run_id="run-1"))
    db.commit()
    call = db.query(ToolCall).one()
    assert call.status == "failed"
    assert "sk-testsecret1234" not in str(call.input_payload)
    assert db.query(PolicyDecision).filter_by(policy_package="connector", allowed=False).count() == 1
    assert db.query(AuditLog).filter_by(action="tool_call.failed").count() == 1


def test_live_adapter_is_blocked(db):
    runner = AdapterRunner(default_registry())
    with pytest.raises(PolicyDenied, match="live trading is locked"):
        runner.run(db, "ibkr_locked", {"order": {"symbol": "SPY"}}, ToolContext(actor="ExecutionAgent", agent_run_id="run-1"))
    db.commit()
    assert db.query(ToolCall).one().status == "failed"
    decision = db.query(PolicyDecision).filter_by(policy_package="trading_lock").one()
    assert decision.action == "live_order"
    assert decision.allowed is False
    assert "live trading is locked" in decision.reasons
    audit = db.query(AuditLog).filter_by(action="policy_decision.denied").one()
    assert audit.payload["policy_package"] == "trading_lock"
    assert audit.payload["action"] == "live_order"
    assert audit.payload["allowed"] is False
    assert audit.payload["workflow_id"] == "run-1"
    assert "live trading is locked" in audit.payload["reasons"]


def test_quantconnect_mcp_adapter_exposes_fixed_backtest_actions(db):
    db.add(
        ExternalConnection(
            provider="quantconnect",
            display_name="QuantConnect",
            status="connected",
            permissions=["run_backtest", "paper_trade"],
            meta={},
        )
    )
    runner = AdapterRunner(default_registry())
    result = runner.run(
        db,
        "quantconnect_mcp",
        {"action": "run_backtest", "project_id": "project-1", "backtest_name": "bt-1"},
        ToolContext(actor="BacktestAgent", agent_run_id="wf-qc"),
    )
    db.commit()

    assert result.ok is True
    assert result.output["action"] == "run_backtest"
    assert result.output["status"] == "mcp_request_prepared"
    assert result.output["mode"] == "external_mcp_required"


def test_quantconnect_adapter_rejects_unknown_action():
    adapter = QuantConnectMCPAdapter()

    try:
        adapter.validate_input({"action": "live_deploy"})
    except ValueError as exc:
        assert "unsupported QuantConnect MCP action" in str(exc)
    else:
        raise AssertionError("unknown QuantConnect action should be rejected")


def test_quantconnect_paper_adapter_is_proposal_only():
    output = QuantConnectPaperAdapter().create_deployment_proposal({"strategy_id": "strategy-1", "portfolio": {"SPY": 1.0}})

    assert output["status"] == "paper_deployment_proposal_prepared"
    assert output["mode"] == "proposal_only"
    assert output["strategy_id"] == "strategy-1"


def test_duckdb_adapter_exposes_required_query_methods(db):
    runner = AdapterRunner(default_registry())
    bars = runner.run(
        db,
        "duckdb",
        {
            "action": "query_bars",
            "symbols": ["SPY"],
            "start": "2026-01-02",
            "end": "2026-01-03",
            "frequency": "1d",
            "dataset_version": "dvc:ds:rev1",
            "rows": [
                {"symbol": "SPY", "date": "2026-01-02", "frequency": "1d", "dataset_version": "dvc:ds:rev1", "close": 1.0},
                {"symbol": "QQQ", "date": "2026-01-02", "frequency": "1d", "dataset_version": "dvc:ds:rev1", "close": 2.0},
            ],
        },
        ToolContext(actor="DataAgent", agent_run_id="wf-duckdb"),
    )
    factor = runner.run(
        db,
        "duckdb",
        {"action": "query_factor_values", "factor_id": "factor-1", "start": "2026-01-02", "end": "2026-01-03", "dataset_version": "dvc:ds:rev1", "rows": [{"factor_id": "factor-1", "date": "2026-01-02", "value": 0.2}]},
        ToolContext(actor="DataAgent", agent_run_id="wf-duckdb"),
    )
    equity = runner.run(
        db,
        "duckdb",
        {"action": "query_backtest_equity", "backtest_run_id": "bt-1", "rows": [{"backtest_run_id": "bt-1", "timestamp": "2026-01-02", "equity": 100.0}]},
        ToolContext(actor="DataAgent", agent_run_id="wf-duckdb"),
    )
    orders = runner.run(
        db,
        "duckdb",
        {"action": "query_orders", "backtest_run_id": "bt-1", "rows": [{"backtest_run_id": "bt-1", "timestamp": "2026-01-02", "symbol": "SPY"}]},
        ToolContext(actor="DataAgent", agent_run_id="wf-duckdb"),
    )

    assert bars.ok is True
    assert bars.output["action"] == "query_bars"
    assert bars.output["row_count"] == 1
    assert bars.output["rows"][0]["symbol"] == "SPY"
    assert factor.output["action"] == "query_factor_values"
    assert equity.output["action"] == "query_backtest_equity"
    assert orders.output["action"] == "query_orders"


def test_agent_facing_modules_do_not_import_provider_sdks_directly():
    violations = []
    for path in (PROJECT_ROOT / "apps/api/app/agents").glob("**/*.py"):
        tree = ast.parse(path.read_text(), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported = [alias.name.split(".")[0] for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported = [node.module.split(".")[0]]
            else:
                continue
            for name in imported:
                if name in BANNED_DIRECT_SDK_IMPORTS:
                    violations.append(f"{path.relative_to(PROJECT_ROOT)} imports {name}")

    assert violations == []
