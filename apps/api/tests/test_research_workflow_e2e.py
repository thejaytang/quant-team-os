import os

os.environ["DATABASE_URL"] = "sqlite:///:memory:"

import pytest

from app.api.routes_agent_runs import cancel_agent_run
from app.api.routes_workflows import (
    cancel_workflow,
    list_workflows,
    start_backtest_workflow,
    start_research_workflow,
    workflow_events,
)
from app.core.auth import CurrentUser
from app.db.models import (
    AgentRun,
    ApprovalRequest,
    AuditLog,
    BacktestRun,
    ResearchIdea,
    RiskReview,
    StrategyCard,
    StrategySpec,
    WorkflowLink,
)
from app.services.workflows import start_workflow


def test_research_workflow_starts_temporal_link(db):
    idea = ResearchIdea(title="E2E Momentum", thesis="Test full controlled research workflow", universe="US equities", tags=["e2e"])
    db.add(idea)
    db.flush()

    result = start_workflow(db, "ResearchWorkflow", "research_idea", idea.id, {"research_idea_id": idea.id})
    db.commit()

    link = db.query(WorkflowLink).filter_by(workflow_id=result["workflow_id"]).one()
    assert link.workflow_type == "ResearchWorkflow"
    assert link.owner_id == idea.id
    assert link.status == "temporal_unavailable"
    assert db.query(AuditLog).filter(AuditLog.action.like("workflow.%")).count() >= 1


def test_research_workflow_route_rejects_missing_research_idea(db):
    with pytest.raises(Exception, match="research idea not found"):
        start_research_workflow({"research_idea_id": "missing"}, db=db)


def test_backtest_workflow_route_requires_dataset_version(db):
    strategy = StrategySpec(name="Backtest Route", description="Requires version")
    db.add(strategy)
    db.flush()

    with pytest.raises(Exception, match="dataset_version is required"):
        start_backtest_workflow({"strategy_id": strategy.id}, db=db)


def test_research_workflow_local_fallback_does_not_create_business_outputs(db):
    idea = ResearchIdea(title="E2E Quality Momentum", thesis="Test generated strategy path", universe="US equities", tags=["e2e"])
    db.add(idea)
    db.flush()

    result = start_workflow(db, "ResearchWorkflow", "research_idea", idea.id, {"research_idea_id": idea.id})
    link = db.query(WorkflowLink).filter_by(workflow_id=result["workflow_id"]).one()

    assert link.status == "temporal_unavailable"
    assert "outputs" not in result
    assert db.query(ApprovalRequest).count() == 0
    assert db.query(StrategySpec).count() == 0
    assert db.query(StrategyCard).count() == 0
    assert db.query(RiskReview).count() == 0
    assert db.query(BacktestRun).count() == 0


def test_list_workflows_returns_public_metadata(db):
    link = WorkflowLink(
        workflow_id="wf-list-1",
        workflow_type="ResearchWorkflow",
        owner_type="research_idea",
        owner_id="idea-1",
        status="started",
        meta={"temporal": {"mode": "local_fallback"}},
    )
    db.add(link)
    db.flush()

    rows = list_workflows(db)
    assert rows[0]["workflow_id"] == "wf-list-1"
    assert rows[0]["metadata"]["temporal"]["mode"] == "local_fallback"


def test_cancel_workflow_writes_audit_event_and_events(db):
    idea = ResearchIdea(title="Cancelable Workflow", thesis="cancel path")
    db.add(idea)
    db.flush()
    result = start_workflow(db, "ResearchWorkflow", "research_idea", idea.id, {"research_idea_id": idea.id})
    user = CurrentUser(sub="user-1", username="researcher", roles={"researcher"})

    canceled = cancel_workflow(result["workflow_id"], db=db, user=user)
    events = workflow_events(result["workflow_id"], db=db)

    assert canceled["status"] == "cancel_requested"
    assert canceled["temporal"]["mode"] in {"temporal", "local_fallback"}
    assert db.query(AuditLog).filter(AuditLog.action.in_(["workflow.cancel_requested", "workflow.cancel_fallback"])).count() == 1
    assert any(event["type"] in {"workflow.cancel_requested", "workflow.cancel_fallback"} for event in events["events"])


def test_cancel_agent_run_cancels_linked_workflow(db):
    link = WorkflowLink(
        workflow_id="wf-agent-cancel",
        workflow_type="ResearchWorkflow",
        owner_type="research_idea",
        owner_id="idea-1",
        status="started",
        meta={},
    )
    run = AgentRun(task_type="research", status="running", workflow_id=link.workflow_id, input_payload={}, output_payload={})
    db.add_all([link, run])
    db.flush()
    user = CurrentUser(sub="user-1", username="researcher", roles={"researcher"})

    canceled = cancel_agent_run(run.id, db=db, user=user)

    assert canceled.status == "canceled"
    assert canceled.output_payload["cancel"]["status"] == "cancel_requested"
    assert link.status == "cancel_requested"
    assert db.query(AuditLog).filter(AuditLog.action.in_(["workflow.cancel_requested", "workflow.cancel_fallback"])).count() == 1
