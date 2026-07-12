from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.compat import APIRouter, Depends, HTTPException
from app.core.auth import require_any_role
from app.db.models import ResearchIdea, StrategySpec, WorkflowLink
from app.db.session import get_db
from app.services.workflows import cancel_workflow as cancel_workflow_link
from app.services.workflows import start_workflow, workflow_event_log

router = APIRouter(prefix="/api/v1/workflows", tags=["workflows"])


@router.get("")
def list_workflows(db: Session = Depends(get_db)):
    return [_public_workflow(link) for link in db.scalars(select(WorkflowLink).order_by(WorkflowLink.created_at.desc())).all()]


@router.post("/research")
def start_research_workflow(payload: dict, db: Session = Depends(get_db), _user=Depends(require_any_role("researcher", "admin"))):
    research_idea_id = payload.get("research_idea_id")
    if not research_idea_id or not db.get(ResearchIdea, research_idea_id):
        raise HTTPException(status_code=404, detail="research idea not found")
    return start_workflow(db, "ResearchWorkflow", "research_idea", research_idea_id, payload)


@router.post("/backtest")
def start_backtest_workflow(payload: dict, db: Session = Depends(get_db), _user=Depends(require_any_role("researcher", "admin"))):
    strategy_id = payload.get("strategy_id")
    if not strategy_id or not db.get(StrategySpec, strategy_id):
        raise HTTPException(status_code=404, detail="strategy not found")
    if not str(payload.get("dataset_version") or "").strip():
        raise HTTPException(status_code=422, detail="dataset_version is required")
    return start_workflow(db, "BacktestWorkflow", "strategy", strategy_id, payload)


@router.post("/data-ingestion")
def start_data_ingestion_workflow(payload: dict, db: Session = Depends(get_db), _user=Depends(require_any_role("researcher", "admin"))):
    return start_workflow(db, "DataIngestionWorkflow", "dataset", payload.get("dataset_spec_id", "pending"), payload)


@router.post("/risk-review")
def start_risk_review_workflow(payload: dict, db: Session = Depends(get_db), _user=Depends(require_any_role("risk_reviewer", "admin"))):
    strategy_id = payload.get("strategy_id")
    if not strategy_id or not db.get(StrategySpec, strategy_id):
        raise HTTPException(status_code=404, detail="strategy not found")
    return start_workflow(db, "RiskReviewWorkflow", "strategy", strategy_id, payload)


@router.get("/{workflow_id}")
def get_workflow(workflow_id: str, db: Session = Depends(get_db)):
    link = db.scalar(select(WorkflowLink).where(WorkflowLink.workflow_id == workflow_id))
    if not link:
        raise HTTPException(status_code=404, detail="workflow not found")
    return _public_workflow(link)


@router.post("/{workflow_id}/cancel")
def cancel_workflow(workflow_id: str, db: Session = Depends(get_db), user=Depends(require_any_role("researcher", "risk_reviewer", "admin"))):
    link = db.scalar(select(WorkflowLink).where(WorkflowLink.workflow_id == workflow_id))
    if not link:
        raise HTTPException(status_code=404, detail="workflow not found")
    cancel_result = cancel_workflow_link(db, link, user.username)
    return {**_public_workflow(link), "temporal": cancel_result["temporal"]}


@router.get("/{workflow_id}/events")
def workflow_events(workflow_id: str, db: Session = Depends(get_db)):
    link = db.scalar(select(WorkflowLink).where(WorkflowLink.workflow_id == workflow_id))
    if not link:
        raise HTTPException(status_code=404, detail="workflow not found")
    return {"workflow_id": workflow_id, "events": workflow_event_log(db, workflow_id)}


def _public_workflow(link: WorkflowLink) -> dict:
    return {
        "id": link.id,
        "workflow_id": link.workflow_id,
        "workflow_type": link.workflow_type,
        "owner_type": link.owner_type,
        "owner_id": link.owner_id,
        "status": link.status,
        "metadata": link.meta or {},
        "created_at": link.created_at,
        "updated_at": link.updated_at,
    }
