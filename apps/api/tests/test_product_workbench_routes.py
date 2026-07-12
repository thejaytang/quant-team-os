from __future__ import annotations

from datetime import date

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

fastapi_testclient = pytest.importorskip("fastapi.testclient")
TestClient = fastapi_testclient.TestClient

from app.db.models import (
    AgentDefinition,
    ApprovalRequest,
    Artifact,
    BacktestRun,
    Base,
    DatasetSpec,
    FactorSpec,
    ResearchIdea,
    RiskReview,
    StrategyCard,
    StrategySpec,
    WorkflowLink,
)
from app.db.session import get_db
from app.main import create_app


@pytest.fixture
def api_client():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        future=True,
    )
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, future=True)
    db = SessionLocal()
    app = create_app()

    def override_get_db():
        yield db

    app.dependency_overrides[get_db] = override_get_db
    client = TestClient(app)
    try:
        yield client, db
    finally:
        app.dependency_overrides.clear()
        client.close()
        db.close()
        engine.dispose()


def test_product_workbench_read_routes(api_client):
    client, db = api_client
    ids = _seed_product_workbench_data(db)

    summary = _json(client.get("/api/v1/dashboard/summary"))
    assert summary["status"]["live_trading_locked"] is True
    assert summary["counts"]["pending_approvals"] == 1
    assert summary["portfolio"]["source"] == "paper/simulated only; no live broker account connected"
    expected_disconnected = sum(1 for row in summary["connections"] if row["status"] in {"disconnected", "failed", "error"})
    assert summary["counts"]["disconnected_tools"] == expected_disconnected
    assert all(row["status"] != "locked" or row["provider"] == "ibkr" for row in summary["connections"])
    connections = {row["provider"]: row for row in summary["connections"]}
    quantconnect_capabilities = connections["quantconnect"]["metadata"]["capabilities"]
    assert quantconnect_capabilities["connectable"] is True
    assert quantconnect_capabilities["read_holdings"] is False
    assert quantconnect_capabilities["paper_trade"] is True
    assert quantconnect_capabilities["live_trade"] is False
    ibkr = connections["ibkr"]
    assert ibkr["status"] == "locked"
    assert ibkr["metadata"]["capabilities"]["connectable"] is False
    assert ibkr["metadata"]["capabilities"]["read_holdings"] is False
    assert ibkr["metadata"]["capabilities"]["live_trade"] == "locked"
    workflow_task = next(row for row in summary["running_tasks"] if row["type"] == "workflow")
    assert workflow_task["metadata"] == {"input": {"strategy_id": ids["strategy_id"]}}

    pipeline = _json(client.get("/api/v1/research/pipeline"))
    assert [stage["key"] for stage in pipeline["stages"]]
    waiting_approval = next(stage for stage in pipeline["stages"] if stage["key"] == "waiting-approval")
    assert any(item["linked_strategy_id"] == ids["strategy_id"] for item in waiting_approval["items"])

    reports = _json(client.get("/api/v1/research/reports"))
    assert {item["artifact"]["id"] for item in reports} >= {ids["strategy_report_id"], ids["factor_report_id"]}

    graph = _json(client.get("/api/v1/agent-graph"))
    assert graph["nodes"]
    assert graph["edges"]
    assert graph["groups"]
    execution = next(node for node in graph["nodes"] if node["id"] == "execution-agent")
    assert execution["permissions"]["can_execute_live_trade"] is False
    assert execution["risk_limits"]["live_trading_locked"] is True
    assert any(edge["relation_type"] == "approval" for edge in graph["edges"])


def test_agent_patch_redacts_secrets_and_keeps_live_trading_locked(api_client):
    client, db = api_client
    client.get("/api/v1/agent-graph")
    secret = "sk-testsecret1234567890"

    response = client.patch(
        "/api/v1/agents/research-agent",
        json={
            "current_task": "Reviewing factor candidates",
            "metadata": {"api_key": secret, "note": "safe metadata"},
            "permissions": {"can_execute_live_trade": True, "can_request_live_trade": True},
            "risk_limits": {"live_trading_locked": False, "max_notional": 1000000},
        },
    )
    agent = _json(response)

    assert agent["id"] == "research-agent"
    assert agent["current_task"] == "Reviewing factor candidates"
    assert secret not in str(agent)
    assert agent["metadata"]["api_key"] != secret
    assert agent["permissions"]["can_request_live_trade"] is False
    assert agent["permissions"]["can_execute_live_trade"] is False
    assert agent["risk_limits"]["live_trading_locked"] is True

    db.expire_all()
    stored = db.get(AgentDefinition, "research-agent")
    assert stored is not None
    assert stored.permissions["can_request_live_trade"] is False
    assert stored.permissions["can_execute_live_trade"] is False
    assert stored.risk_limits["live_trading_locked"] is True
    assert stored.risk_limits["max_notional"] == 1000000


def test_agent_create_locks_live_permissions_before_persist(api_client):
    client, db = api_client
    response = client.post(
        "/api/v1/agents",
        json={
            "id": "live-test-agent",
            "name": "Live Test Agent",
            "role": "tries to bypass live lock",
            "permissions": {"can_request_live_trade": True, "can_execute_live_trade": True, "can_backtest": True},
            "risk_limits": {"live_trading_locked": False, "max_notional": 500000},
        },
    )
    agent = _json(response)

    assert agent["id"] == "live-test-agent"
    assert agent["permissions"]["can_backtest"] is True
    assert agent["permissions"]["can_request_live_trade"] is False
    assert agent["permissions"]["can_execute_live_trade"] is False
    assert agent["risk_limits"]["live_trading_locked"] is True

    db.expire_all()
    stored = db.get(AgentDefinition, "live-test-agent")
    assert stored is not None
    assert stored.permissions["can_request_live_trade"] is False
    assert stored.permissions["can_execute_live_trade"] is False
    assert stored.risk_limits["live_trading_locked"] is True
    assert stored.risk_limits["max_notional"] == 500000


def test_agent_run_endpoint_redacts_payload_and_updates_graph(api_client):
    client, db = api_client
    ids = _seed_product_workbench_data(db)
    secret = "sk-runsecret1234567890"

    run = _json(
        client.post(
            "/api/v1/agents/research-agent/runs",
            json={"factor_id": ids["factor_id"], "instruction": "refresh analysis", "api_key": secret},
        )
    )

    assert run["task_type"] == "research-agent"
    assert run["status"] == "queued"
    assert run["input_payload"]["agent_id"] == "research-agent"
    assert run["input_payload"]["factor_id"] == ids["factor_id"]
    assert secret not in str(run)

    graph = _json(client.get("/api/v1/agent-graph"))
    research_agent = next(node for node in graph["nodes"] if node["id"] == "research-agent")
    assert research_agent["status"] == "running"
    assert run["id"] in research_agent["current_task"]


def test_factor_and_strategy_workspace_endpoints(api_client):
    client, db = api_client
    ids = _seed_product_workbench_data(db)

    factor_workspace = _json(client.get(f"/api/v1/factors/{ids['factor_id']}/workspace"))
    assert factor_workspace["factor"]["id"] == ids["factor_id"]
    assert [item["id"] for item in factor_workspace["used_by_strategies"]] == [ids["strategy_id"]]
    assert [item["id"] for item in factor_workspace["reports"]] == [ids["factor_report_id"]]

    strategy_workspace = _json(client.get(f"/api/v1/strategies/{ids['strategy_id']}/workspace"))
    assert strategy_workspace["strategy"]["id"] == ids["strategy_id"]
    assert strategy_workspace["card"]["live_trading_status"] == "locked"
    assert [item["id"] for item in strategy_workspace["factors"]] == [ids["factor_id"]]
    assert [item["id"] for item in strategy_workspace["backtests"]] == [ids["backtest_id"]]
    assert [item["id"] for item in strategy_workspace["risk_reviews"]] == [ids["risk_review_id"]]
    assert [item["id"] for item in strategy_workspace["approvals"]] == [ids["approval_id"]]


def _json(response):
    assert response.status_code == 200, response.text
    return response.json()


def _seed_product_workbench_data(db):
    idea = ResearchIdea(
        id="idea-quality-momentum",
        title="Quality momentum",
        thesis="High quality names with positive momentum should outperform.",
        universe="US equities",
        asset_class="equity",
        proposed_by="researcher",
        status="researching",
        tags=["quality", "momentum"],
    )
    factor = FactorSpec(
        id="factor-quality-momentum",
        research_idea_id=idea.id,
        name="quality_momentum",
        description="Quality score combined with trailing momentum.",
        formula="z(roe) + z(close / close_63 - 1)",
        input_fields=["roe", "close"],
        lookback_window=63,
        rebalance_frequency="monthly",
        status="analyzed",
        metrics={"ic": 0.04, "rank_ic": 0.06, "coverage": 0.91},
        artifacts=["artifact-factor-report"],
    )
    dataset = DatasetSpec(
        id="dataset-us-equities",
        name="US equities daily",
        asset_class="equity",
        frequency="1d",
        source="massive",
        dataset_version="dvc:dataset:rev1",
        dvc_rev="rev1",
    )
    strategy = StrategySpec(
        id="strategy-quality-momentum",
        name="Quality Momentum Strategy",
        description="Long high quality momentum names.",
        universe="US equities",
        factors=[factor.id],
        signal_logic={"rank": "quality_momentum"},
        portfolio_logic={"top_n": 50},
        rebalance_frequency="monthly",
        risk_constraints={"max_weight": 0.05},
        implementation_paths={"notebook": "notebooks/quality_momentum.ipynb"},
        status="APPROVAL_PENDING",
    )
    card = StrategyCard(
        id="card-quality-momentum",
        strategy_id=strategy.id,
        current_status="APPROVAL_PENDING",
        thesis=strategy.description,
        universe=strategy.universe,
        factor_summary={"factors": [factor.id]},
        latest_backtest_metrics={"sharpe": 1.35},
        approval_status="pending",
        paper_trading_status="not_started",
        live_trading_status="locked",
        workflow_id="wf-strategy-1",
        artifacts=["artifact-strategy-report"],
    )
    backtest = BacktestRun(
        id="backtest-quality-momentum",
        strategy_id=strategy.id,
        dataset_spec_id=dataset.id,
        dataset_version=dataset.dataset_version,
        start_date=date(2020, 1, 1),
        end_date=date(2025, 1, 1),
        benchmark="SPY",
        cost_model={"commission_bps": 1},
        slippage_model={"bps": 2},
        status="completed",
        metrics={"sharpe": 1.35, "max_drawdown": -0.12},
        artifacts=["artifact-backtest-report"],
        mlflow_run_id="mlflow-run-1",
    )
    risk = RiskReview(
        id="risk-quality-momentum",
        strategy_id=strategy.id,
        backtest_run_id=backtest.id,
        verdict="pass",
        hard_rule_results=[],
        risk_summary={"verdict": "pass"},
        created_by_agent="Risk Agent",
    )
    approval = ApprovalRequest(
        id="approval-quality-momentum",
        request_type="paper_promotion",
        target_type="strategy",
        target_id=strategy.id,
        requested_by_agent="Approval Agent",
        risk_summary={"verdict": "pass"},
        status="pending",
        workflow_id="wf-approval-1",
    )
    workflow = WorkflowLink(
        id="workflow-quality-momentum",
        workflow_id="wf-strategy-1",
        workflow_type="StrategyRegistrationWorkflow",
        owner_type="strategy",
        owner_id=strategy.id,
        status="started",
        meta={"input": {"strategy_id": strategy.id}},
    )
    strategy_report = Artifact(
        id="artifact-strategy-report",
        artifact_type="research_report",
        owner_type="strategy",
        owner_id=strategy.id,
        content_type="text/markdown",
        checksum="sha256:strategy",
        path="reports/strategy-quality-momentum.md",
        object_key="reports/strategy-quality-momentum.md",
        meta={"title": "Strategy report"},
    )
    factor_report = Artifact(
        id="artifact-factor-report",
        artifact_type="factor_report",
        owner_type="factor",
        owner_id=factor.id,
        content_type="text/markdown",
        checksum="sha256:factor",
        path="reports/factor-quality-momentum.md",
        object_key="reports/factor-quality-momentum.md",
        meta={"title": "Factor report"},
    )
    db.add_all([idea, factor, dataset, strategy, card, backtest, risk, approval, workflow, strategy_report, factor_report])
    db.flush()
    return {
        "factor_id": factor.id,
        "strategy_id": strategy.id,
        "backtest_id": backtest.id,
        "risk_review_id": risk.id,
        "approval_id": approval.id,
        "strategy_report_id": strategy_report.id,
        "factor_report_id": factor_report.id,
    }
