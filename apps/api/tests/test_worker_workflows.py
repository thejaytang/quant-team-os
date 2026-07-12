import asyncio
import hashlib
import sys
import types
from datetime import date
from pathlib import Path

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

WORKERS = Path(__file__).resolve().parents[2] / "workers"
sys.path.insert(0, str(WORKERS))

import activities as worker_activities
import workflows as worker_workflows
from activities import (
    alphalens_report_activity,
    approval_request_activity,
    connection_test_activity,
    dataset_registration_activity,
    dlt_ingestion_activity,
    dvc_restore_activity,
    dvc_version_activity,
    great_expectations_validation_activity,
    mlflow_backtest_activity,
    openai_agent_plan_activity,
    paper_promotion_finalize_activity,
    qlib_research_activity,
    quantconnect_backtest_activity,
    quantstats_report_activity,
    record_system_event_activity,
    report_generation_activity,
    risk_gate_activity,
    workflow_status_activity,
)
from worker_main import (
    configure_worker_observability,
    configured_activities,
    configured_workflows,
    start_metrics_server,
)
from workflows import (
    ApprovalSignalState,
    BacktestWorkflow,
    ConnectionTestWorkflow,
    DataIngestionWorkflow,
    PaperPromotionWorkflow,
    ResearchWorkflow,
    StrategyRegistrationWorkflow,
)

from app.adapters.base import PolicyDenied
from app.core.config import get_settings
from app.db.models import (
    AgentRun,
    ApprovalRecord,
    ApprovalRequest,
    Artifact,
    AuditLog,
    BacktestRun,
    Base,
    DatasetSpec,
    ExternalConnection,
    PaperTradingSession,
    PolicyDecision,
    RiskReview,
    StrategyCard,
    StrategySpec,
    SystemEvent,
    ToolCall,
    WorkflowLink,
)
from app.db.session import SessionLocal
from app.services.datasets import create_sample_ohlcv_dataset


def test_approval_signal_state_preserves_supported_actions():
    state = ApprovalSignalState()

    assert state.status == "waiting_approval"
    assert state.resolve({"action": "approved", "actor": "local_user"}) == "completed"
    assert state.as_dict()["approval"]["actor"] == "local_user"


def test_approval_signal_state_rejects_unknown_action():
    state = ApprovalSignalState()

    assert state.resolve({"action": "force_live"}) == "rejected"
    assert state.as_dict()["approval"]["action"] == "rejected"


def test_worker_registers_v03_workflows_and_activities():
    workflow_names = {workflow.__name__ for workflow in configured_workflows()}
    activity_names = {activity.__name__ for activity in configured_activities()}

    assert "ResearchWorkflow" in workflow_names
    assert "ConnectionTestWorkflow" in workflow_names
    assert "PaperPromotionWorkflow" in workflow_names
    assert "connection_test_activity" in activity_names
    assert "openai_agent_plan_activity" in activity_names
    assert "dlt_ingestion_activity" in activity_names
    assert "dvc_restore_activity" in activity_names
    assert "dataset_registration_activity" in activity_names
    assert "risk_gate_activity" in activity_names
    assert "mlflow_backtest_activity" in activity_names
    assert "report_generation_activity" in activity_names
    assert "strategy_registration_finalize_activity" in activity_names
    assert "paper_promotion_finalize_activity" in activity_names


def test_worker_configures_otel_without_endpoint(monkeypatch):
    monkeypatch.delenv("OTEL_EXPORTER_OTLP_ENDPOINT", raising=False)
    get_settings.cache_clear()

    assert configure_worker_observability() == "disabled"


def test_worker_metrics_server_missing_dependency_does_not_crash(monkeypatch):
    import builtins

    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == "prometheus_client":
            raise ImportError("missing")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)

    assert start_metrics_server() is False


def test_connection_test_workflow_marks_failed_activity_failed(monkeypatch):
    async def fake_execute_activity(name, payload, **_kwargs):
        if name == "WorkflowStatusActivity":
            return {"status": "recorded", "workflow_status": payload["status"]}
        return {"provider": payload["provider"], "status": "error", "ok": False, "error": "missing required fields: api_key"}

    monkeypatch.setattr(worker_workflows.workflow, "execute_activity", fake_execute_activity)

    result = asyncio.run(ConnectionTestWorkflow().run({"provider": "openai", "workflow_id": "wf-connection-failed"}))

    assert result["status"] == "failed"
    assert result["error"] == "missing required fields: api_key"
    assert [item["activity"] for item in result["activities"]] == ["ConnectionTestActivity", "WorkflowStatusActivity"]


def test_connection_test_activity_uses_gateway_and_secret_ref(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "sqlite://")
    get_settings.cache_clear()
    from app.db import session as db_session
    from app.services.connections import connect_provider

    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool, future=True)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, future=True)
    monkeypatch.setattr(db_session, "SessionLocal", Session)

    with Session() as db:
        connection = connect_provider(db, "openai", {"api_key": "sk-testsecret1234", "model": "gpt-test"})
        connection_id = connection["id"]
        db.commit()

    result = connection_test_activity({"provider": "openai", "connection_id": connection_id, "workflow_id": "wf-connection-test"})

    assert result["ok"] is True
    assert result["status"] == "connected"
    assert result["tool"] == "openai"
    assert result["adapter_output"]["credential_available"] is True
    with Session() as db:
        tool_call = db.query(ToolCall).filter_by(adapter_name="openai").order_by(ToolCall.created_at.desc()).first()
        assert tool_call is not None
        assert tool_call.status == "succeeded"
        assert tool_call.agent_run_id == "wf-connection-test"
        assert db.query(AuditLog).filter_by(action="connection.test_succeeded").count() >= 1
    get_settings.cache_clear()


def test_data_ingestion_workflow_runs_activity_chain():
    result = asyncio.run(DataIngestionWorkflow().run({"dataset_spec_id": "ds1"}))
    activities = [item["activity"] for item in result["activities"]]

    assert result["status"] == "completed"
    assert activities == ["DltIngestionActivity", "GreatExpectationsValidationActivity", "DVCVersionActivity", "DatasetRegistrationActivity"]


def test_data_ingestion_workflow_stops_when_gx_fails(monkeypatch):
    async def fake_execute_activity(name, payload, **_kwargs):
        if name == "GreatExpectationsValidationActivity":
            return {"status": "failed", "result": {"success": False}}
        if name == "RecordSystemEventActivity":
            return {"status": "recorded", "event_type": payload["event_type"]}
        return {"status": "completed", "dataset_spec_id": payload.get("dataset_spec_id")}

    monkeypatch.setattr(worker_workflows.workflow, "execute_activity", fake_execute_activity)

    result = asyncio.run(DataIngestionWorkflow().run({"dataset_spec_id": "ds-bad", "workflow_id": "wf-gx"}))
    activities = [item["activity"] for item in result["activities"]]

    assert result["status"] == "failed"
    assert activities == ["DltIngestionActivity", "GreatExpectationsValidationActivity", "RecordSystemEventActivity", "WorkflowStatusActivity"]
    assert "DVCVersionActivity" not in activities
    assert "DatasetRegistrationActivity" not in activities


def test_record_system_event_activity_writes_system_event():
    result = record_system_event_activity({"event_type": "data_ingestion.gx_failed", "severity": "error", "workflow_id": "wf-gx"})

    assert result["status"] == "recorded"
    with SessionLocal() as db:
        event = db.query(SystemEvent).filter_by(event_type="data_ingestion.gx_failed").one()
        assert event.severity == "error"
        assert event.payload["workflow_id"] == "wf-gx"


def test_workflow_status_activity_updates_link_and_writes_audit():
    with SessionLocal() as db:
        db.add(WorkflowLink(workflow_id="wf-status", workflow_type="ResearchWorkflow", owner_type="research_idea", owner_id="idea-1", status="started", meta={}))
        db.commit()

    result = workflow_status_activity({"workflow_id": "wf-status", "workflow_type": "ResearchWorkflow", "status": "rejected", "result": {"reason": "approval rejected"}})

    assert result["status"] == "recorded"
    with SessionLocal() as db:
        link = db.scalar(select(WorkflowLink).where(WorkflowLink.workflow_id == "wf-status"))
        assert link.status == "rejected"
        assert link.meta["last_worker_result"]["reason"] == "approval rejected"
        audit = db.query(AuditLog).filter_by(action="workflow.rejected", target_id="wf-status").one()
        assert audit.payload["workflow_type"] == "ResearchWorkflow"


def test_activity_chain_preserves_artifacts_between_steps(monkeypatch):
    async def fake_execute_activity(name, payload, **_kwargs):
        return {"artifacts": [{"artifact_id": f"{name}-artifact"}]}

    monkeypatch.setattr(worker_workflows.workflow, "execute_activity", fake_execute_activity)

    _results, current = asyncio.run(worker_workflows._activity_chain_with_state(["FirstActivity", "SecondActivity"], {}))

    assert [item["artifact_id"] for item in current["artifacts"]] == ["FirstActivity-artifact", "SecondActivity-artifact"]


def test_research_workflow_runs_tool_chain_without_wait_when_not_required():
    result = asyncio.run(ResearchWorkflow().run({"research_idea_id": "idea1", "requires_approval": False}))
    activities = [item["activity"] for item in result["activities"]]

    assert result["status"] == "completed"
    assert activities[:4] == ["OpenAIAgentPlanActivity", "DltIngestionActivity", "GreatExpectationsValidationActivity", "DVCVersionActivity"]
    assert "ApprovalRequestActivity" in activities


def test_research_workflow_finalize_uses_generated_strategy_after_approval(monkeypatch):
    async def fake_execute_activity(name, payload, **_kwargs):
        if name == "ReportGenerationActivity":
            return {"status": "completed", "strategy_id": "strategy-1", "target_id": "strategy-1", "request_type": "register_strategy"}
        if name == "ApprovalRequestActivity":
            return {"status": "approval_required", "approval_request_id": "approval-1", "strategy_id": payload["strategy_id"]}
        if name == "StrategyRegistrationFinalizeActivity":
            return {"status": "completed", "strategy_id": payload["strategy_id"], "approval_request_id": payload["approval_request_id"]}
        return {"status": "completed"}

    async def run_workflow():
        workflow = ResearchWorkflow()
        task = asyncio.create_task(workflow.run({"research_idea_id": "idea1"}))
        await asyncio.sleep(0.01)
        workflow.approval_resolved({"action": "approved", "approval_request_id": "approval-1", "actor": "local_user"})
        return await task

    monkeypatch.setattr(worker_workflows.workflow, "execute_activity", fake_execute_activity)

    result = asyncio.run(run_workflow())

    assert result["status"] == "completed"
    assert result["activities"][-1]["activity"] == "StrategyRegistrationFinalizeActivity"
    assert result["activities"][-1]["result"]["strategy_id"] == "strategy-1"
    assert result["activities"][-1]["result"]["approval_request_id"] == "approval-1"


def test_research_workflow_reaches_wait_state_before_signal(monkeypatch):
    async def fake_execute_activity(name, payload, **_kwargs):
        if name == "ReportGenerationActivity":
            return {"status": "completed", "strategy_id": "strategy-wait", "target_id": "strategy-wait", "request_type": "register_strategy"}
        if name == "ApprovalRequestActivity":
            return {"status": "approval_required", "approval_request_id": "approval-wait", "strategy_id": payload["strategy_id"]}
        return {"status": "completed"}

    async def run_workflow():
        workflow = ResearchWorkflow()
        task = asyncio.create_task(workflow.run({"research_idea_id": "idea-wait"}))
        for _ in range(20):
            await asyncio.sleep(0.01)
            if workflow.state()["status"] == "waiting_approval":
                break
        assert workflow.state()["status"] == "waiting_approval"
        assert not task.done()
        workflow.approval_resolved({"action": "approved", "approval_request_id": "approval-wait", "actor": "local_user"})
        return await task

    monkeypatch.setattr(worker_workflows.workflow, "execute_activity", fake_execute_activity)

    assert asyncio.run(run_workflow())["status"] == "completed"


def test_rejected_research_approval_stops_before_finalize(monkeypatch):
    async def fake_execute_activity(name, payload, **_kwargs):
        if name == "ReportGenerationActivity":
            return {"status": "completed", "strategy_id": "strategy-reject", "target_id": "strategy-reject", "request_type": "register_strategy"}
        if name == "ApprovalRequestActivity":
            return {"status": "approval_required", "approval_request_id": "approval-reject", "strategy_id": payload["strategy_id"]}
        if name == "StrategyRegistrationFinalizeActivity":
            raise AssertionError("rejected approval must not finalize strategy registration")
        return {"status": "completed"}

    async def run_workflow():
        workflow = ResearchWorkflow()
        task = asyncio.create_task(workflow.run({"research_idea_id": "idea-reject"}))
        await asyncio.sleep(0.01)
        workflow.approval_resolved({"action": "rejected", "approval_request_id": "approval-reject", "actor": "local_user"})
        return await task

    monkeypatch.setattr(worker_workflows.workflow, "execute_activity", fake_execute_activity)

    result = asyncio.run(run_workflow())

    assert result["status"] == "rejected"
    assert "StrategyRegistrationFinalizeActivity" not in [item["activity"] for item in result["activities"]]


def test_research_workflow_stops_before_report_when_risk_fails(monkeypatch):
    async def fake_execute_activity(name, payload, **_kwargs):
        if name == "RiskGateActivity":
            return {"status": "failed", "risk_verdict": "fail", "risk_summary": {"verdict": "fail"}}
        if name in {"ReportGenerationActivity", "ApprovalRequestActivity", "StrategyRegistrationFinalizeActivity"}:
            raise AssertionError(f"{name} must not run after risk failure")
        return {"status": "completed"}

    monkeypatch.setattr(worker_workflows.workflow, "execute_activity", fake_execute_activity)

    result = asyncio.run(ResearchWorkflow().run({"research_idea_id": "idea-risk-fail"}))

    activities = [item["activity"] for item in result["activities"]]
    assert result["status"] == "failed"
    assert result["reason"] == "risk_gate_failed"
    assert "RiskGateActivity" in activities
    assert "ReportGenerationActivity" not in activities
    assert "ApprovalRequestActivity" not in activities


def test_strategy_registration_workflow_stops_when_risk_fails(monkeypatch):
    async def fake_execute_activity(name, payload, **_kwargs):
        if name == "RiskGateActivity":
            return {"status": "failed", "risk_verdict": "fail", "risk_summary": {"verdict": "fail"}}
        if name in {"StrategyRegistrationPendingActivity", "ApprovalRequestActivity", "StrategyRegistrationFinalizeActivity"}:
            raise AssertionError(f"{name} must not run after risk failure")
        return {"status": "completed"}

    monkeypatch.setattr(worker_workflows.workflow, "execute_activity", fake_execute_activity)

    result = asyncio.run(StrategyRegistrationWorkflow().run({"strategy_id": "strategy-risk-fail"}))

    assert result["status"] == "failed"
    assert result["reason"] == "risk_gate_failed"
    assert [item["activity"] for item in result["activities"]] == ["RiskGateActivity"]


def test_paper_promotion_workflow_stops_when_risk_fails(monkeypatch):
    async def fake_execute_activity(name, payload, **_kwargs):
        if name == "RiskGateActivity":
            return {"status": "failed", "risk_verdict": "fail", "risk_summary": {"verdict": "fail"}}
        if name in {"PaperPromotionCandidateActivity", "ApprovalRequestActivity", "PaperPromotionFinalizeActivity"}:
            raise AssertionError(f"{name} must not run after risk failure")
        return {"status": "completed"}

    monkeypatch.setattr(worker_workflows.workflow, "execute_activity", fake_execute_activity)

    result = asyncio.run(PaperPromotionWorkflow().run({"strategy_id": "strategy-risk-fail"}))

    assert result["status"] == "failed"
    assert result["reason"] == "risk_gate_failed"
    assert [item["activity"] for item in result["activities"]] == ["RiskGateActivity"]


def test_approval_workflows_finalize_after_approved_signal():
    async def run_workflow(workflow, payload):
        task = asyncio.create_task(workflow.run(payload))
        await asyncio.sleep(0.01)
        workflow.approval_resolved({"action": "approved", "approval_request_id": "approval-1", "actor": "local_user"})
        return await task

    registration = asyncio.run(run_workflow(StrategyRegistrationWorkflow(), {"strategy_id": "strategy-1"}))
    paper = asyncio.run(run_workflow(PaperPromotionWorkflow(), {"strategy_id": "strategy-1"}))

    assert registration["status"] == "completed"
    assert [item["activity"] for item in registration["activities"]][-1] == "StrategyRegistrationFinalizeActivity"
    assert paper["status"] == "completed"
    assert [item["activity"] for item in paper["activities"]][-1] == "PaperPromotionFinalizeActivity"


def test_paper_promotion_finalize_creates_quantconnect_session(monkeypatch):
    monkeypatch.setenv("APP_ENV", "development")
    get_settings.cache_clear()
    from app.services.connections import connect_provider

    with SessionLocal() as db:
        dataset = DatasetSpec(id="ds-paper", name="Paper Dataset", dataset_version="v1")
        strategy = StrategySpec(id="strategy-paper", name="Paper Strategy", description="paper", status="PAPER_CANDIDATE")
        backtest = BacktestRun(
            id="bt-paper",
            strategy_id=strategy.id,
            dataset_spec_id=dataset.id,
            start_date=date(2020, 1, 1),
            end_date=date(2025, 1, 1),
            status="completed",
            metrics={"sharpe": 1.2},
            cost_model={"commission_bps": 1},
            slippage_model={"bps": 2},
        )
        approval = ApprovalRequest(
            id="approval-paper",
            request_type="promote_to_paper",
            target_type="strategy",
            target_id=strategy.id,
            requested_by_agent="ExecutionAgent",
            risk_summary={"verdict": "pass"},
            status="approved",
            workflow_id="wf-paper",
        )
        db.add_all([dataset, strategy, backtest, approval])
        db.flush()
        db.add(RiskReview(strategy_id=strategy.id, backtest_run_id=backtest.id, verdict="pass", hard_rule_results=[], risk_summary={"verdict": "pass"}))
        db.add(ApprovalRecord(approval_request_id=approval.id, action="approved", human_actor="approver", human_comment="approved"))
        connect_provider(db, "quantconnect", {"user_id": "qc-user", "api_token": "qc-token"})
        db.commit()

    result = paper_promotion_finalize_activity({"strategy_id": "strategy-paper", "approval_request_id": "approval-paper", "workflow_id": "wf-paper"})

    assert result["status"] == "completed"
    assert result["strategy_status"] == "PAPER_APPROVED"
    assert result["paper_session_status"] == "proposed"
    with SessionLocal() as db:
        session = db.get(PaperTradingSession, result["paper_session_id"])
        assert session.strategy_id == "strategy-paper"
        assert session.provider == "quantconnect"
        assert session.status == "proposed"
        assert session.meta["proposal"]["status"] == "paper_deployment_proposal_prepared"
        call = db.query(ToolCall).filter_by(adapter_name="quantconnect_paper").order_by(ToolCall.created_at.desc()).first()
        assert call is not None
        assert call.status == "succeeded"
    get_settings.cache_clear()


def test_openai_agent_plan_activity_returns_structured_fallback(monkeypatch):
    monkeypatch.setenv("APP_ENV", "development")
    get_settings.cache_clear()

    result = openai_agent_plan_activity({"research_idea_id": "idea1"})

    assert result["status"] == "completed"
    assert result["tool"] == "deterministic_fallback"
    assert result["langfuse_trace_id"]
    assert result["plan"]["steps"]


def test_openai_agent_plan_activity_redacts_persisted_input(monkeypatch):
    monkeypatch.setenv("APP_ENV", "development")
    get_settings.cache_clear()

    openai_agent_plan_activity({"research_idea_id": "idea-secret", "api_key": "sk-testsecret1234"})

    with SessionLocal() as db:
        run = db.query(AgentRun).filter_by(task_type="openai_agent_plan").order_by(AgentRun.created_at.desc()).first()
        assert run is not None
        assert "sk-testsecret1234" not in str(run.input_payload)
        assert run.input_payload["research_idea_id"] == "idea-secret"
    get_settings.cache_clear()


def test_openai_agent_plan_activity_reuses_existing_agent_run(monkeypatch):
    monkeypatch.setenv("APP_ENV", "development")
    get_settings.cache_clear()
    with SessionLocal() as db:
        before = db.query(AgentRun).count()
        run = AgentRun(task_type="research", status="queued", workflow_id="wf-agent", input_payload={"research_idea_id": "idea1"}, output_payload={})
        db.add(run)
        db.commit()
        run_id = run.id

    result = openai_agent_plan_activity({"research_idea_id": "idea1", "workflow_id": "wf-agent", "agent_run_id": run_id})

    assert result["langfuse_trace_id"]
    with SessionLocal() as db:
        assert db.query(AgentRun).count() == before + 1
        run = db.get(AgentRun, run_id)
        assert run.status == "completed"
        assert run.langfuse_trace_id == result["langfuse_trace_id"]
        assert run.output_payload["plan"]["objective"]
    get_settings.cache_clear()


def test_openai_agent_plan_activity_uses_gateway_secret_ref(monkeypatch):
    captured = {}
    created_agents = []

    class FakeAgent:
        def __init__(self, *args, **kwargs):
            self.name = kwargs.get("name") or args[0]
            self.handoffs = kwargs.get("handoffs", [])
            created_agents.append(self)

    class FakeRunner:
        @staticmethod
        def run_sync(agent, prompt):
            assert captured == {"key": "sk-testsecret1234", "use_for_tracing": False}
            assert agent.name == "ChiefAgent"
            assert [item.name for item in agent.handoffs] == [
                "ResearchAgent",
                "DataAgent",
                "FactorAgent",
                "BacktestAgent",
                "RiskAgent",
                "ReportAgent",
            ]
            return types.SimpleNamespace(
                final_output=types.SimpleNamespace(
                    model_dump=lambda: {"objective": "runtime plan", "steps": ["gate", "plan"], "required_tools": ["OpenAI"]}
                )
            )

    def fake_set_default_openai_key(key, use_for_tracing=True):
        captured["key"] = key
        captured["use_for_tracing"] = use_for_tracing

    monkeypatch.setitem(sys.modules, "agents", types.SimpleNamespace(Agent=FakeAgent, Runner=FakeRunner, set_default_openai_key=fake_set_default_openai_key))
    monkeypatch.setenv("APP_ENV", "development")
    get_settings.cache_clear()
    from app.db.session import init_db
    from app.services.connections import connect_provider

    init_db()
    with SessionLocal() as db:
        connect_provider(db, "openai", {"api_key": "sk-testsecret1234", "model": "gpt-test"})
        db.commit()

    result = openai_agent_plan_activity({"research_idea_id": "idea1", "workflow_id": "wf-openai-secret"})

    assert result["status"] == "completed"
    assert result["tool"] == "openai_agents_sdk"
    assert result["plan"]["objective"] == "runtime plan"
    assert [agent.name for agent in created_agents] == [
        "ResearchAgent",
        "DataAgent",
        "FactorAgent",
        "BacktestAgent",
        "RiskAgent",
        "ReportAgent",
        "ChiefAgent",
    ]
    with SessionLocal() as db:
        call = db.query(ToolCall).filter_by(adapter_name="openai").order_by(ToolCall.created_at.desc()).first()
        assert call is not None
        assert call.status == "succeeded"
        assert call.agent_run_id == "wf-openai-secret"
        assert call.output_payload["agent_team"] == [
            "ChiefAgent",
            "ResearchAgent",
            "DataAgent",
            "FactorAgent",
            "BacktestAgent",
            "RiskAgent",
            "ReportAgent",
        ]
        rendered = f"{call.input_payload} {call.output_payload} {call.error}"
        assert "sk-testsecret1234" not in rendered
    get_settings.cache_clear()


def test_openai_agent_plan_activity_fails_without_explicit_fallback(monkeypatch):
    class FakeAgent:
        def __init__(self, *args, **kwargs):
            return None

    class FakeRunner:
        @staticmethod
        def run_sync(agent, prompt):
            raise RuntimeError("sdk down")

    monkeypatch.setitem(sys.modules, "agents", types.SimpleNamespace(Agent=FakeAgent, Runner=FakeRunner, set_default_openai_key=lambda *_args, **_kwargs: None))
    monkeypatch.setenv("ALLOW_AGENT_FALLBACK", "false")
    monkeypatch.setenv("APP_ENV", "development")
    get_settings.cache_clear()
    from app.services.connections import connect_provider

    with SessionLocal() as db:
        connect_provider(db, "openai", {"api_key": "sk-testsecret1234", "model": "gpt-test"})
        db.commit()

    with SessionLocal() as db:
        run = AgentRun(task_type="research", status="queued", workflow_id="wf-agent-failed", input_payload={"research_idea_id": "idea1"}, output_payload={})
        db.add(run)
        db.commit()
        run_id = run.id

    try:
        try:
            openai_agent_plan_activity({"research_idea_id": "idea1", "workflow_id": "wf-agent-failed", "agent_run_id": run_id})
        except RuntimeError as exc:
            assert "sdk down" in str(exc)
        else:
            raise AssertionError("SDK failure should stop workflow when ALLOW_AGENT_FALLBACK=false")

        with SessionLocal() as db:
            run = db.get(AgentRun, run_id)
            assert run.status == "failed"
            assert run.output_payload["error"] == "sdk down"
            assert run.langfuse_trace_id
    finally:
        get_settings.cache_clear()


def test_openai_agent_prompt_redacts_secret_payload():
    prompt = worker_activities._agent_prompt({"api_key": "sk-testsecret1234", "symbol": "SPY"})

    assert "sk-testsecret1234" not in prompt
    assert "SPY" in prompt


def test_approval_request_activity_creates_workflow_linked_request(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "sqlite://")
    get_settings.cache_clear()
    from app.db import session as db_session

    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool, future=True)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, future=True)
    monkeypatch.setattr(db_session, "SessionLocal", Session)

    payload = {
        "workflow_id": "wf-approval-activity",
        "workflow_type": "StrategyRegistrationWorkflow",
        "strategy_id": "strategy-1",
        "risk_summary": {"verdict": "pass"},
    }
    created = approval_request_activity(payload)
    existing = approval_request_activity(payload)

    assert created["mode"] == "created"
    assert created["request_type"] == "register_strategy"
    assert created["target_id"] == "strategy-1"
    assert existing["mode"] == "existing"
    with Session() as db:
        requests = db.query(ApprovalRequest).all()
        assert len(requests) == 1
        assert requests[0].workflow_id == "wf-approval-activity"
    get_settings.cache_clear()


def test_great_expectations_activity_uses_data_contracts():
    passed = great_expectations_validation_activity(
        {"suite": "ohlcv_daily_suite", "rows": [{"symbol": "SPY", "date": "2026-01-02", "open": 1, "high": 2, "low": 1, "close": 1.5, "volume": 100}]}
    )
    failed = great_expectations_validation_activity(
        {"suite": "ohlcv_daily_suite", "rows": [{"symbol": "SPY", "date": "2026-01-02", "open": 1, "high": 1, "low": 2, "close": 1.5, "volume": -1}]}
    )

    assert passed["status"] == "passed"
    assert failed["status"] == "failed"


def test_dvc_version_activity_returns_stable_content_hash():
    payload = {"dataset_spec_id": "ds1", "filters": {"symbol": "SPY"}}

    assert dvc_version_activity(payload)["dvc_rev"] == dvc_version_activity(payload)["dvc_rev"]
    assert dvc_version_activity(payload)["mode"] == "local_fallback"
    assert dvc_version_activity(payload)["remote"] == "minio"


def test_dvc_version_activity_writes_rows_to_parquet_for_versioning(tmp_path, monkeypatch):
    monkeypatch.setenv("ARTIFACT_ROOT", str(tmp_path))
    get_settings.cache_clear()
    try:
        rows = [{"symbol": "SPY", "date": "2026-01-02", "open": 1, "high": 2, "low": 1, "close": 1.5, "volume": 100}]

        result = dvc_version_activity({"dataset_spec_id": "ds1", "rows": rows})

        dataset_path = Path(result["dataset_path"])
        assert result["status"] == "versioned"
        assert result["dataset_version"].startswith("dvc:ds1:")
        assert result["remote"] == "minio"
        assert dataset_path == tmp_path / "datasets" / "ds1" / "ohlcv_daily.parquet"
        assert dataset_path.exists()
        assert result["dvc_rev"] == hashlib.sha256(dataset_path.read_bytes()).hexdigest()[:12]
    finally:
        get_settings.cache_clear()


def test_dvc_version_activity_rejects_local_fallback_in_production(tmp_path, monkeypatch):
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("ARTIFACT_ROOT", str(tmp_path))
    monkeypatch.setattr(worker_activities, "_module_available", lambda name: name != "dvc")
    get_settings.cache_clear()
    try:
        rows = [{"symbol": "SPY", "date": "2026-01-02", "open": 1, "high": 2, "low": 1, "close": 1.5, "volume": 100}]

        try:
            dvc_version_activity({"dataset_spec_id": "ds1", "rows": rows})
        except RuntimeError as exc:
            assert "DVC versioning failed in strict mode" in str(exc)
        else:
            raise AssertionError("production DVC versioning must not silently use local fallback")
    finally:
        get_settings.cache_clear()


def test_dlt_activity_rejects_contract_fallback_when_mature_fallback_disabled(monkeypatch):
    monkeypatch.setenv("ALLOW_MATURE_TOOL_FALLBACK", "false")
    monkeypatch.setattr(worker_activities, "_module_available", lambda name: name != "dlt")
    get_settings.cache_clear()
    try:
        rows = [{"symbol": "SPY", "date": "2026-01-02", "open": 1, "high": 2, "low": 1, "close": 1.5, "volume": 100}]
        try:
            dlt_ingestion_activity({"sample_rows": rows})
        except RuntimeError as exc:
            assert "dlt pipeline failed in strict mode" in str(exc)
        else:
            raise AssertionError("strict mature tool mode must reject dlt contract fallback")
    finally:
        get_settings.cache_clear()


def test_data_activities_reject_implicit_sample_rows_when_mature_fallback_disabled(monkeypatch):
    monkeypatch.setenv("ALLOW_MATURE_TOOL_FALLBACK", "false")
    get_settings.cache_clear()
    try:
        checks = [
            (dlt_ingestion_activity, "explicit rows or Massive source output"),
            (great_expectations_validation_activity, "explicit rows"),
            (dataset_registration_activity, "explicit rows"),
        ]
        for activity_fn, message in checks:
            try:
                activity_fn({"dataset_spec_id": "ds-strict"})
            except RuntimeError as exc:
                assert message in str(exc)
            else:
                raise AssertionError(f"{activity_fn.__name__} must reject implicit sample rows in strict mode")
    finally:
        get_settings.cache_clear()


def test_gx_activity_rejects_local_fallback_when_mature_fallback_disabled(monkeypatch):
    from app.services import data_quality as data_quality_service

    monkeypatch.setenv("ALLOW_MATURE_TOOL_FALLBACK", "false")
    monkeypatch.setattr(data_quality_service, "_run_great_expectations", lambda suite, rows, *, strict=False: None)
    get_settings.cache_clear()
    try:
        rows = [{"symbol": "SPY", "date": "2026-01-02", "open": 1, "high": 2, "low": 1, "close": 1.5, "volume": 100}]
        try:
            great_expectations_validation_activity({"suite": "ohlcv_daily_suite", "rows": rows})
        except RuntimeError as exc:
            assert "Great Expectations unavailable in strict mode" in str(exc)
        else:
            raise AssertionError("strict mature tool mode must reject Great Expectations local fallback")
    finally:
        get_settings.cache_clear()


def test_dvc_restore_activity_preserves_dataset_version_boundary():
    result = dvc_restore_activity({"dataset_version": "dvc:ds1:rev123", "workflow_id": "wf-backtest"})

    assert result["status"] == "restore_prepared"
    assert result["dataset_version"] == "dvc:ds1:rev123"
    assert result["dvc_rev"] == "rev123"
    assert result["remote"] == "minio"
    with SessionLocal() as db:
        call = db.query(ToolCall).filter(ToolCall.adapter_name == "dvc").order_by(ToolCall.created_at.desc()).first()
        assert call is not None
        assert call.output_payload["action"] == "restore_dataset"


def test_dvc_restore_activity_finds_registered_dataset_path(tmp_path, monkeypatch):
    monkeypatch.setenv("ARTIFACT_ROOT", str(tmp_path))
    get_settings.cache_clear()
    try:
        with SessionLocal() as db:
            dataset = create_sample_ohlcv_dataset(db, "restore_ds")
            db.commit()

        result = dvc_restore_activity(
            {
                "dataset_version": dataset["dataset_version"],
                "dataset_spec_id": dataset["dataset_spec_id"],
                "dvc_rev": dataset["dvc_rev"],
                "workflow_id": "wf-backtest",
            }
        )

        assert result["status"] == "restore_prepared"
        assert Path(result["dataset_path"]).exists()
        assert result["dataset_path"].endswith("datasets/" + dataset["dataset_spec_id"] + "/ohlcv_daily.parquet")
    finally:
        get_settings.cache_clear()


def test_dvc_restore_activity_finds_pending_version_by_rev(tmp_path, monkeypatch):
    monkeypatch.setenv("ARTIFACT_ROOT", str(tmp_path))
    get_settings.cache_clear()
    try:
        rows = [{"symbol": "SPY", "date": "2026-01-02", "open": 1, "high": 2, "low": 1, "close": 1.5, "volume": 100}]
        dvc = dvc_version_activity({"rows": rows})
        registered = dataset_registration_activity({**dvc, "rows": rows})

        result = dvc_restore_activity({"dataset_version": dvc["dataset_version"], "dvc_rev": dvc["dvc_rev"], "workflow_id": "wf-backtest"})

        assert dvc["dataset_version"].startswith("dvc:pending:")
        assert result["status"] == "restore_prepared"
        assert result["dataset_path"] == registered["dataset_path"]
        assert Path(result["dataset_path"]).exists()
    finally:
        get_settings.cache_clear()


def test_dvc_restore_activity_requires_dataset_version():
    try:
        dvc_restore_activity({"workflow_id": "wf-backtest"})
    except ValueError as exc:
        assert "dataset_version is required" in str(exc)
    else:
        raise AssertionError("dvc_restore_activity should require dataset_version")


def test_dvc_restore_activity_rejects_prepared_restore_when_mature_fallback_disabled(monkeypatch):
    monkeypatch.setenv("ALLOW_MATURE_TOOL_FALLBACK", "false")
    get_settings.cache_clear()
    try:
        try:
            dvc_restore_activity({"dataset_version": "dvc:ds1:rev123", "workflow_id": "wf-backtest"})
        except RuntimeError as exc:
            assert "DVC restore failed in strict mode" in str(exc)
        else:
            raise AssertionError("strict mature tool mode must reject prepared DVC restore")
    finally:
        get_settings.cache_clear()


def test_dlt_activity_returns_contract_when_pipeline_not_available():
    result = dlt_ingestion_activity(
        {"sample_rows": [{"symbol": "SPY", "date": "2026-01-02", "open": 1, "high": 2, "low": 1, "close": 1.5, "volume": 100}]}
    )

    assert result["tool"] == "dlt"
    assert result["contract"]["resource"] == "massive_ohlcv_1d"
    assert result["mode"] in {"dlt_pipeline", "contract_fallback"}


def test_data_activities_fail_when_gateway_denies_secret_payload():
    for activity_fn in (dlt_ingestion_activity, great_expectations_validation_activity, dvc_version_activity, dvc_restore_activity):
        try:
            activity_fn({"api_key": "sk-testsecret1234"})
        except PolicyDenied as exc:
            assert "secret must not be present in tool payload" in str(exc)
        else:
            raise AssertionError(f"{activity_fn.__name__} should fail when ToolGateway denies payload")


def test_data_ingestion_defaults_to_valid_sample_rows():
    dlt = dlt_ingestion_activity({"dataset_spec_id": "ds-default"})
    gx = great_expectations_validation_activity(dlt)
    dvc = dvc_version_activity({**dlt, **gx})
    registered = dataset_registration_activity({**dlt, **gx, **dvc})

    assert dlt["rows"]
    assert gx["status"] == "passed"
    assert dvc["dataset_version"].startswith("dvc:ds-default:")
    assert Path(dvc["dataset_path"]).exists()
    assert registered["dataset_spec_id"] == "ds-default"
    assert registered["dataset_version"] == dvc["dataset_version"]
    assert registered["gx_artifact_id"]
    with SessionLocal() as db:
        dataset = db.get(DatasetSpec, "ds-default")
        artifact = db.get(Artifact, registered["artifact_id"])
        gx_artifact = db.get(Artifact, registered["gx_artifact_id"])
        assert dataset.dvc_rev == dvc["dvc_rev"]
        assert artifact.dvc_rev == dvc["dvc_rev"]
        assert gx_artifact.artifact_type == "gx_validation"
        assert gx_artifact.owner_id == dataset.id
        assert artifact.meta["gx_success"] is True
        assert artifact.meta["gx_validation_artifact_id"] == gx_artifact.id


def test_quantconnect_backtest_activity_prepares_mcp_sequence():
    _ensure_connected_provider("quantconnect")
    result = quantconnect_backtest_activity({"project_id": "project-1", "backtest_id": "bt-1", "backtest_name": "bt-1"})

    assert result["status"] == "mcp_request_prepared"
    assert result["tool"] == "quantconnect_mcp"
    assert [item["action"] for item in result["sequence"]] == [
        "create_project",
        "upload_strategy_files",
        "run_backtest",
        "poll_backtest_status",
        "fetch_backtest_result",
        "fetch_backtest_charts_or_links",
    ]


def test_backtest_workflow_restores_dvc_dataset_before_backtest():
    result = asyncio.run(BacktestWorkflow().run({"strategy_id": "strategy-1", "backtest_run_id": "bt-1", "dataset_version": "dvc:ds1:rev123"}))
    activities = [item["activity"] for item in result["activities"]]

    assert result["status"] == "prepared"
    assert activities == ["DVCRestoreActivity", "QuantConnectBacktestActivity"]


def test_backtest_workflow_runs_reporting_only_after_completed_backtest():
    result = asyncio.run(
        BacktestWorkflow().run(
            {
                "strategy_id": "strategy-1",
                "backtest_run_id": "bt-1",
                "dataset_version": "dvc:ds1:rev123",
                "backtest_completed": True,
            }
        )
    )
    activities = [item["activity"] for item in result["activities"]]

    assert result["status"] == "completed"
    assert activities == ["DVCRestoreActivity", "QuantConnectBacktestActivity", "QuantStatsReportActivity", "MLflowBacktestActivity", "RiskGateActivity"]


def test_risk_gate_activity_uses_opa_policy(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "sqlite://")
    get_settings.cache_clear()
    from app.db import session as db_session

    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool, future=True)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, future=True)
    monkeypatch.setattr(db_session, "SessionLocal", Session)

    result = risk_gate_activity(
        {
            "metrics": {"sharpe": 0.1, "max_drawdown": 0.4, "turnover_daily": 0.8, "trade_count": 5},
            "cost_model": {"commission_bps": 1},
            "slippage_model": {"bps": 2},
            "factor_report_present": True,
            "start_date": "2020-01-01",
            "end_date": "2025-01-01",
            "workflow_id": "wf-risk-gate",
        }
    )

    assert result["status"] == "failed"
    assert result["risk_verdict"] == "fail"
    with Session() as db:
        row = db.query(PolicyDecision).one()
        assert row.policy_package == "risk_gate"
        assert row.workflow_id == "wf-risk-gate"
        assert row.allowed is False
    get_settings.cache_clear()


def test_risk_gate_activity_persists_review_when_ids_are_present(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "sqlite://")
    get_settings.cache_clear()
    from app.db import session as db_session

    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool, future=True)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, future=True)
    monkeypatch.setattr(db_session, "SessionLocal", Session)

    with Session() as db:
        dataset = DatasetSpec(id="ds-risk", name="Risk Dataset", dataset_version="v1")
        strategy = StrategySpec(id="strategy-risk", name="Risk Strategy", description="risk")
        backtest = BacktestRun(
            id="bt-risk",
            strategy_id=strategy.id,
            dataset_spec_id=dataset.id,
            start_date=date(2020, 1, 1),
            end_date=date(2025, 1, 1),
            status="completed",
            metrics={"sharpe": 1.2, "max_drawdown": 0.1, "turnover_daily": 0.2, "trade_count": 120},
            cost_model={"commission_bps": 1},
            slippage_model={"bps": 2},
        )
        db.add_all([dataset, strategy, backtest])
        db.commit()

    result = risk_gate_activity(
        {
            "strategy_id": "strategy-risk",
            "backtest_run_id": "bt-risk",
            "metrics": {"sharpe": 1.2, "max_drawdown": 0.1, "turnover_daily": 0.2, "trade_count": 120},
            "cost_model": {"commission_bps": 1},
            "slippage_model": {"bps": 2},
            "factor_report_present": True,
            "start_date": "2020-01-01",
            "end_date": "2025-01-01",
            "workflow_id": "wf-risk-persist",
        }
    )

    assert result["status"] == "passed"
    assert result["risk_review_id"]
    with Session() as db:
        review = db.get(RiskReview, result["risk_review_id"])
        assert review.strategy_id == "strategy-risk"
        assert review.backtest_run_id == "bt-risk"
        assert review.verdict == "pass"
        assert review.risk_summary["verdict"] == "pass"
    get_settings.cache_clear()


def test_quant_research_and_report_activities_prepare_tool_requests(tmp_path, monkeypatch):
    monkeypatch.setenv("ARTIFACT_ROOT", str(tmp_path))
    monkeypatch.setenv("DATABASE_URL", "sqlite://")
    get_settings.cache_clear()

    with SessionLocal() as db:
        tool_calls_before = db.query(ToolCall).count()

    qlib = qlib_research_activity({"dataset_spec_id": "ds1", "factor_spec_id": "factor-1"})
    alphalens = alphalens_report_activity({"dataset_spec_id": "ds1", "factor_spec_id": "factor-1"})
    quantstats = quantstats_report_activity({"backtest_run_id": "bt-1", "strategy_id": "strategy-1"})

    assert qlib["tool"] == "Qlib"
    assert qlib["status"] == "tool_request_prepared"
    assert qlib["artifacts"][0]["artifact_type"] == "qlib_research_summary"
    assert alphalens["tool"] == "alphalens-reloaded"
    assert alphalens["status"] == "report_request_prepared"
    assert alphalens["artifacts"][0]["artifact_type"] == "alphalens_factor_tear_sheet"
    assert quantstats["tool"] == "QuantStats"
    assert quantstats["status"] == "report_request_prepared"
    assert quantstats["artifacts"][0]["artifact_type"] == "quantstats_strategy_tear_sheet"
    for output in [qlib, alphalens, quantstats]:
        assert (tmp_path / output["artifacts"][0]["path"]).exists()
    with SessionLocal() as db:
        names = {call.adapter_name for call in db.query(ToolCall).offset(tool_calls_before).all()}
        assert {"qlib", "alphalens", "quantstats"}.issubset(names)
    get_settings.cache_clear()


def test_mlflow_backtest_activity_logs_quantstats_artifact(tmp_path, monkeypatch):
    monkeypatch.setenv("ARTIFACT_ROOT", str(tmp_path))
    get_settings.cache_clear()
    _ensure_connected_provider("mlflow")

    quantstats = quantstats_report_activity({"backtest_run_id": "bt-mlflow", "strategy_id": "strategy-1", "metrics": {"sharpe": 1.2}})
    result = mlflow_backtest_activity(
        {
            "backtest_run_id": "bt-mlflow",
            "strategy_id": "strategy-1",
            "dataset_spec_id": "ds-mlflow",
            "dataset_version": "dlt:massive:test",
            "metrics": {"sharpe": 1.2},
            "artifacts": quantstats["artifacts"],
        }
    )

    assert result["tool"] == "MLflow"
    assert result["status"] == "logged"
    assert result["backtest_run_id"] == "bt-mlflow"
    assert result["mlflow_run_id"]
    assert result["artifact_ids"] == [quantstats["artifacts"][0]["artifact_id"]]
    with SessionLocal() as db:
        assert db.get(BacktestRun, "bt-mlflow").artifacts == [quantstats["artifacts"][0]["artifact_id"]]
        assert db.get(BacktestRun, "bt-mlflow").status == "result_pending"
    get_settings.cache_clear()


def _ensure_connected_provider(provider: str) -> None:
    with SessionLocal() as db:
        connection = db.query(ExternalConnection).filter_by(provider=provider).one_or_none()
        if not connection:
            connection = ExternalConnection(provider=provider, display_name=provider, permissions=[])
            db.add(connection)
        connection.status = "connected"
        db.commit()


def test_report_generation_activity_creates_strategy_card_and_memo(tmp_path, monkeypatch):
    monkeypatch.setenv("ARTIFACT_ROOT", str(tmp_path))
    get_settings.cache_clear()
    result = report_generation_activity(
        {
            "research_idea_id": "idea-report",
            "workflow_id": "wf-report",
            "strategy_name": "Generated Momentum",
            "thesis": "Momentum candidate",
            "universe": "US equities",
            "metrics": {"sharpe": 1.1},
            "risk_verdict": "pass",
        }
    )

    assert result["status"] == "completed"
    assert result["request_type"] == "register_strategy"
    with SessionLocal() as db:
        strategy = db.get(StrategySpec, result["strategy_id"])
        card = db.get(StrategyCard, result["strategy_card_id"])
        memo = db.get(Artifact, result["research_memo_artifact_id"])
        backtest = db.query(BacktestRun).filter_by(strategy_id=strategy.id).one()
        assert strategy.status == "APPROVAL_PENDING"
        assert card.strategy_id == strategy.id
        assert card.approval_status == "pending"
        assert card.workflow_id == "wf-report"
        assert card.latest_risk_review
        assert db.get(DatasetSpec, "sample-dataset")
        assert backtest.strategy_id == strategy.id
        assert backtest.status == "result_pending"
        assert backtest.cost_model == {}
        assert backtest.slippage_model == {}
        assert db.get(RiskReview, card.latest_risk_review).verdict == "pass"
        assert memo.artifact_type == "research_memo"
        assert (tmp_path / memo.path).exists()
    get_settings.cache_clear()


def test_report_generation_activity_reuses_strategy_card_on_workflow_retry(tmp_path, monkeypatch):
    monkeypatch.setenv("ARTIFACT_ROOT", str(tmp_path))
    get_settings.cache_clear()

    payload = {
        "research_idea_id": "idea-retry",
        "workflow_id": "wf-report-retry",
        "strategy_name": "Retry Momentum",
        "thesis": "Retry candidate",
        "universe": "US equities",
        "metrics": {"sharpe": 1.1},
        "risk_verdict": "pass",
    }
    first = report_generation_activity(payload)
    second = report_generation_activity(payload)

    assert second["strategy_id"] == first["strategy_id"]
    assert second["strategy_card_id"] == first["strategy_card_id"]
    with SessionLocal() as db:
        assert db.query(StrategySpec).filter_by(id=first["strategy_id"]).count() == 1
        assert db.query(StrategyCard).filter_by(workflow_id="wf-report-retry").count() == 1
        assert db.get(StrategyCard, first["strategy_card_id"]).strategy_id == first["strategy_id"]
    get_settings.cache_clear()
