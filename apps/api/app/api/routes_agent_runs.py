from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.compat import APIRouter, Depends, HTTPException, StreamingResponse
from app.core.auth import require_any_role
from app.core.config import get_settings
from app.core.redaction import redact_secrets
from app.db.models import AgentMessage, AgentRun, ResearchIdea, StrategySpec, WorkflowLink
from app.db.session import get_db
from app.schemas import AgentRunCreate
from app.services.langfuse_tracking import log_agent_run_to_langfuse
from app.services.workflows import cancel_workflow, start_workflow

router = APIRouter(prefix="/api/v1/agent-runs", tags=["agent-runs"])


@router.post("")
def create_agent_run(payload: AgentRunCreate, db: Session = Depends(get_db), _user=Depends(require_any_role("researcher", "risk_reviewer", "admin"))):
    run = AgentRun(task_type=payload.task_type, status="queued", input_payload=redact_secrets(payload.input_payload))
    db.add(run)
    db.flush()
    workflow = _start_agent_workflow(db, run, payload)
    db.add(
        AgentMessage(
            agent_run_id=run.id,
            agent_name="ChiefAgent",
            role="status",
            content=f"Queued {payload.task_type} agent run through FastAPI.",
        )
    )
    run.output_payload = {
        **(run.output_payload or {}),
        "steps": ["queued", *([] if workflow is None else ["temporal_workflow_started"]), "langfuse_trace_logged"],
    }
    log_agent_run_to_langfuse(db, run, {"source": "api"})
    db.flush()
    return run


def _start_agent_workflow(db: Session, run: AgentRun, payload: AgentRunCreate) -> dict | None:
    task_type = payload.task_type.replace("-", "_")
    data = payload.input_payload or {}
    if task_type in {"research", "research_strategy"} and data.get("research_idea_id"):
        idea = db.get(ResearchIdea, data["research_idea_id"])
        if not idea:
            raise HTTPException(status_code=404, detail="research idea not found")
        workflow = start_workflow(db, "ResearchWorkflow", "research_idea", idea.id, {**data, "agent_run_id": run.id})
    elif task_type == "backtest" and data.get("strategy_id"):
        strategy = db.get(StrategySpec, data["strategy_id"])
        if not strategy:
            raise HTTPException(status_code=404, detail="strategy not found")
        if not str(data.get("dataset_version") or "").strip():
            raise HTTPException(status_code=422, detail="dataset_version is required")
        workflow = start_workflow(db, "BacktestWorkflow", "strategy", strategy.id, {**data, "agent_run_id": run.id})
    elif task_type in {"risk", "risk_review"} and data.get("strategy_id"):
        strategy = db.get(StrategySpec, data["strategy_id"])
        if not strategy:
            raise HTTPException(status_code=404, detail="strategy not found")
        workflow = start_workflow(db, "RiskReviewWorkflow", "strategy", strategy.id, {**data, "agent_run_id": run.id})
    else:
        return None
    run.workflow_id = workflow["workflow_id"]
    return workflow


@router.get("")
def list_agent_runs(db: Session = Depends(get_db)):
    return db.scalars(select(AgentRun).order_by(AgentRun.created_at.desc())).all()


@router.get("/{run_id}")
def get_agent_run(run_id: str, db: Session = Depends(get_db)):
    run = db.get(AgentRun, run_id)
    if not run:
        raise HTTPException(status_code=404, detail="agent run not found")
    return run


@router.post("/{run_id}/cancel")
def cancel_agent_run(run_id: str, db: Session = Depends(get_db), user=Depends(require_any_role("researcher", "risk_reviewer", "admin"))):
    run = db.get(AgentRun, run_id)
    if not run:
        raise HTTPException(status_code=404, detail="agent run not found")
    run.status = "canceled"
    if run.workflow_id:
        link = db.scalar(select(WorkflowLink).where(WorkflowLink.workflow_id == run.workflow_id))
        if link:
            cancel_result = cancel_workflow(db, link, user.username)
            run.output_payload = {**(run.output_payload or {}), "cancel": cancel_result}
    db.flush()
    return run


@router.get("/{run_id}/events")
def agent_run_events(run_id: str, db: Session = Depends(get_db)):
    run = db.get(AgentRun, run_id)
    if not run:
        raise HTTPException(status_code=404, detail="agent run not found")
    messages = db.scalars(select(AgentMessage).where(AgentMessage.agent_run_id == run.id).order_by(AgentMessage.created_at)).all()

    def stream():
        yield f"event: status\ndata: {run.status}\n\n"
        for message in messages:
            yield f"event: agent_step\ndata: {message.agent_name}:{message.role}:{message.content}\n\n"
        yield f"event: output\ndata: {run.output_payload}\n\n"

    return StreamingResponse(stream(), media_type="text/event-stream")


@router.get("/{run_id}/langfuse-link")
def agent_run_langfuse_link(run_id: str, db: Session = Depends(get_db)):
    run = db.get(AgentRun, run_id)
    if not run:
        raise HTTPException(status_code=404, detail="agent run not found")
    base_url = get_settings().langfuse_ui_url.rstrip("/")
    url = f"{base_url}/trace/{run.langfuse_trace_id}" if run.langfuse_trace_id else base_url
    return {"run_id": run_id, "trace_id": run.langfuse_trace_id, "url": url}
