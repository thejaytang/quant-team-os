import os

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")

import pytest
from pydantic import ValidationError

from app.api.routes_agent_runs import agent_run_langfuse_link, create_agent_run
from app.api.routes_backtests import create_backtest
from app.api.routes_factors import analyze_factor
from app.api.routes_risk import list_risk_policy_decisions
from app.db.models import AgentMessage, AgentRun, FactorSpec, PolicyDecision, ResearchIdea, StrategySpec, WorkflowLink
from app.schemas import AgentRunCreate, BacktestCreate


def test_agent_run_langfuse_link(db):
    run = AgentRun(task_type="research", status="queued", input_payload={}, langfuse_trace_id="trace-1")
    db.add(run)
    db.flush()

    result = agent_run_langfuse_link(run.id, db=db)

    assert result["run_id"] == run.id
    assert result["trace_id"] == "trace-1"
    assert result["url"] == "http://localhost:3002/trace/trace-1"


def test_agent_run_creation_records_agent_step(db):
    run = create_agent_run(AgentRunCreate(task_type="chat", input_payload={"message": "hello"}), db=db)

    step = db.query(AgentMessage).filter_by(agent_run_id=run.id).one()
    assert step.agent_name == "ChiefAgent"
    assert step.role == "status"
    assert run.output_payload["steps"] == ["queued", "langfuse_trace_logged"]


def test_agent_run_creation_redacts_persisted_input(db):
    run = create_agent_run(AgentRunCreate(task_type="chat", input_payload={"api_key": "sk-testsecret1234", "message": "hello"}), db=db)

    assert "sk-testsecret1234" not in str(run.input_payload)
    assert run.input_payload["message"] == "hello"


def test_agent_run_logs_langfuse_after_output_steps(monkeypatch, db):
    captured = {}

    def fake_log(_db, run, _metadata):
        captured["output_payload"] = dict(run.output_payload or {})
        run.langfuse_trace_id = "trace-after-output"
        return {"trace_id": "trace-after-output", "mode": "test", "error": None}

    monkeypatch.setattr("app.api.routes_agent_runs.log_agent_run_to_langfuse", fake_log)

    run = create_agent_run(AgentRunCreate(task_type="chat", input_payload={"message": "hello"}), db=db)

    assert captured["output_payload"]["steps"] == ["queued", "langfuse_trace_logged"]
    assert run.langfuse_trace_id == "trace-after-output"


def test_research_agent_run_starts_temporal_workflow(db):
    idea = ResearchIdea(title="Agent Linked Idea", thesis="workflow link")
    db.add(idea)
    db.flush()

    run = create_agent_run(AgentRunCreate(task_type="research", input_payload={"research_idea_id": idea.id}), db=db)

    assert run.workflow_id
    assert run.output_payload["steps"] == ["queued", "temporal_workflow_started", "langfuse_trace_logged"]
    link = db.query(WorkflowLink).filter_by(workflow_id=run.workflow_id).one()
    assert link.workflow_type == "ResearchWorkflow"
    assert link.meta["input"]["agent_run_id"] == run.id


def test_workflow_link_redacts_persisted_input(db):
    idea = ResearchIdea(title="Secret Idea", thesis="workflow link redaction")
    db.add(idea)
    db.flush()

    run = create_agent_run(AgentRunCreate(task_type="research", input_payload={"research_idea_id": idea.id, "api_key": "sk-testsecret1234"}), db=db)

    link = db.query(WorkflowLink).filter_by(workflow_id=run.workflow_id).one()
    assert "sk-testsecret1234" not in str(link.meta)
    assert link.meta["input"]["research_idea_id"] == idea.id


def test_factor_analyze_alias(db):
    idea = ResearchIdea(title="Momentum", thesis="Test momentum")
    db.add(idea)
    db.flush()
    factor = FactorSpec(research_idea_id=idea.id, name="mom_20", description="20 day momentum", formula="close / close_20 - 1")
    db.add(factor)
    db.flush()

    result = analyze_factor(factor.id, db=db)

    assert result["workflow_type"] == "FactorAnalysisWorkflow"
    assert result["owner_id"] == factor.id
    assert db.query(WorkflowLink).filter_by(workflow_id=result["workflow_id"]).count() == 1


def test_risk_policy_decisions_alias(db):
    db.add(PolicyDecision(policy_package="risk_gate", action="risk_review", allowed=False, input_payload={}, reasons=["x"], actor="test"))
    db.add(PolicyDecision(policy_package="connector", action="tool_call", allowed=False, input_payload={}, reasons=["y"], actor="test"))
    db.flush()

    result = list_risk_policy_decisions(db=db)

    assert len(result) == 1
    assert result[0].policy_package == "risk_gate"


def test_backtest_creation_starts_workflow(db):
    strategy = StrategySpec(name="Versioned Strategy", description="dataset version test")
    db.add(strategy)
    db.flush()

    result = create_backtest(BacktestCreate(strategy_id=strategy.id, dataset_version="dvc:ds:rev1"), db=db)

    assert result["workflow_type"] == "BacktestWorkflow"
    assert result["owner_id"] == strategy.id
    link = db.query(WorkflowLink).filter_by(workflow_id=result["workflow_id"]).one()
    assert link.meta["input"]["dataset_version"] == "dvc:ds:rev1"


def test_backtest_create_requires_dataset_version():
    with pytest.raises(ValidationError):
        BacktestCreate(strategy_id="strategy-1")
