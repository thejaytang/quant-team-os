from __future__ import annotations

from collections import defaultdict
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.compat import APIRouter, Depends, HTTPException
from app.db.models import (
    AgentRun,
    ApprovalRequest,
    Artifact,
    BacktestRun,
    FactorSpec,
    PaperTradingSession,
    ResearchIdea,
    RiskReview,
    StrategyCard,
    StrategySpec,
    WorkflowLink,
)
from app.db.session import get_db

router = APIRouter(prefix="/api/v1", tags=["research-workspace"])

PIPELINE_STAGES = [
    ("idea", "Idea"),
    ("data-prep", "数据准备"),
    ("researching", "研究中"),
    ("ready-backtest", "待回测"),
    ("backtest-complete", "回测完成"),
    ("ready-risk", "待风控"),
    ("waiting-approval", "待审批"),
    ("paper-candidate", "Paper Candidate"),
    ("archived", "Archived"),
]


@router.get("/research/pipeline")
def research_pipeline(db: Session = Depends(get_db)):
    ideas = db.scalars(select(ResearchIdea).order_by(ResearchIdea.updated_at.desc())).all()
    strategies = db.scalars(select(StrategySpec).order_by(StrategySpec.updated_at.desc())).all()
    backtests = db.scalars(select(BacktestRun).order_by(BacktestRun.created_at.desc())).all()
    risks = db.scalars(select(RiskReview).order_by(RiskReview.created_at.desc())).all()
    approvals = db.scalars(select(ApprovalRequest).order_by(ApprovalRequest.created_at.desc())).all()
    cards = {row.strategy_id: row for row in db.scalars(select(StrategyCard)).all()}
    workflows = db.scalars(select(WorkflowLink).order_by(WorkflowLink.created_at.desc())).all()

    stage_items: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for idea in ideas:
        item = _idea_pipeline_item(idea, workflows)
        stage_items[item["stage"]].append(item)

    for strategy in strategies:
        item = _strategy_pipeline_item(strategy, cards.get(strategy.id), backtests, risks, approvals, workflows)
        stage_items[item["stage"]].append(item)

    return {
        "stages": [
            {"key": key, "label": label, "items": stage_items.get(key, [])}
            for key, label in PIPELINE_STAGES
        ]
    }


@router.get("/factors/{factor_id}/workspace")
def factor_workspace(factor_id: str, db: Session = Depends(get_db)):
    factor = db.get(FactorSpec, factor_id)
    if not factor:
        raise HTTPException(status_code=404, detail="factor not found")
    strategies = [
        row
        for row in db.scalars(select(StrategySpec).order_by(StrategySpec.updated_at.desc())).all()
        if _strategy_uses_factor(row, factor)
    ]
    return {
        "factor": factor,
        "reports": db.scalars(select(Artifact).where(Artifact.owner_type == "factor", Artifact.owner_id == factor.id).order_by(Artifact.created_at.desc())).all(),
        "used_by_strategies": strategies,
        "latest_workflows": [
            row
            for row in db.scalars(select(WorkflowLink).order_by(WorkflowLink.created_at.desc())).all()
            if row.owner_type == "factor" and row.owner_id == factor.id
        ],
        "latest_agent_runs": _agent_runs_for_owner(db, "factor", factor.id),
    }


@router.get("/strategies/{strategy_id}/workspace")
def strategy_workspace(strategy_id: str, db: Session = Depends(get_db)):
    strategy = db.get(StrategySpec, strategy_id)
    if not strategy:
        raise HTTPException(status_code=404, detail="strategy not found")
    factors = [
        row
        for row in db.scalars(select(FactorSpec).order_by(FactorSpec.updated_at.desc())).all()
        if _strategy_uses_factor(strategy, row)
    ]
    return {
        "strategy": strategy,
        "card": db.scalar(select(StrategyCard).where(StrategyCard.strategy_id == strategy.id)),
        "factors": factors,
        "backtests": db.scalars(select(BacktestRun).where(BacktestRun.strategy_id == strategy.id).order_by(BacktestRun.created_at.desc())).all(),
        "risk_reviews": db.scalars(select(RiskReview).where(RiskReview.strategy_id == strategy.id).order_by(RiskReview.created_at.desc())).all(),
        "approvals": db.scalars(select(ApprovalRequest).where(ApprovalRequest.target_type == "strategy", ApprovalRequest.target_id == strategy.id).order_by(ApprovalRequest.created_at.desc())).all(),
        "paper_sessions": db.scalars(select(PaperTradingSession).where(PaperTradingSession.strategy_id == strategy.id).order_by(PaperTradingSession.created_at.desc())).all(),
        "artifacts": db.scalars(select(Artifact).where(Artifact.owner_id == strategy.id).order_by(Artifact.created_at.desc())).all(),
        "workflows": [
            row
            for row in db.scalars(select(WorkflowLink).order_by(WorkflowLink.created_at.desc())).all()
            if row.owner_type == "strategy" and row.owner_id == strategy.id
        ],
    }


@router.get("/research/reports")
def research_reports(db: Session = Depends(get_db)):
    artifacts = db.scalars(select(Artifact).order_by(Artifact.created_at.desc())).all()
    return [_report_item(db, artifact) for artifact in artifacts if artifact.owner_type in {"research", "research_idea", "factor", "strategy", "backtest", "risk_review"}]


def _idea_pipeline_item(idea: ResearchIdea, workflows: list[WorkflowLink]) -> dict[str, Any]:
    status = _norm(idea.status)
    if status in {"data_required", "data-prep"}:
        stage = "data-prep"
    elif status in {"researching", "running"}:
        stage = "researching"
    elif status in {"archived", "done"}:
        stage = "archived"
    else:
        stage = "idea"
    related_workflow = next((row for row in workflows if row.owner_type == "research_idea" and row.owner_id == idea.id), None)
    return {
        "id": idea.id,
        "item_type": "research_idea",
        "title": idea.title,
        "stage": stage,
        "status": idea.status,
        "owner_agent": "Research Agent" if related_workflow else None,
        "latest_action": related_workflow.workflow_type if related_workflow else None,
        "missing_requirements": [],
        "linked_strategy_id": None,
        "latest_backtest_id": None,
        "latest_metrics": {},
        "risk_verdict": None,
        "approval_status": None,
        "next_actions": ["启动 ResearchWorkflow", "生成因子草稿", "生成策略草稿"],
        "updated_at": idea.updated_at,
    }


def _strategy_pipeline_item(
    strategy: StrategySpec,
    card: StrategyCard | None,
    backtests: list[BacktestRun],
    risks: list[RiskReview],
    approvals: list[ApprovalRequest],
    workflows: list[WorkflowLink],
) -> dict[str, Any]:
    latest_backtest = next((row for row in backtests if row.strategy_id == strategy.id), None)
    latest_risk = next((row for row in risks if row.strategy_id == strategy.id), None)
    pending_approval = next((row for row in approvals if row.target_type == "strategy" and row.target_id == strategy.id and _norm(row.status) == "pending"), None)
    workflow = next((row for row in workflows if row.owner_type == "strategy" and row.owner_id == strategy.id), None)
    status = _norm(strategy.status)
    if card and _norm(card.paper_trading_status) in {"approved", "running"}:
        stage = "paper-candidate"
    elif pending_approval:
        stage = "waiting-approval"
    elif latest_risk is None and latest_backtest is not None:
        stage = "ready-risk"
    elif latest_backtest and _norm(latest_backtest.status) == "completed":
        stage = "backtest-complete"
    elif status in {"backtest_ready", "ready_backtest"}:
        stage = "ready-backtest"
    elif status in {"archived", "retired"}:
        stage = "archived"
    else:
        stage = "researching"
    missing = []
    if not strategy.factors:
        missing.append("missing factors")
    if not latest_backtest:
        missing.append("missing backtest")
    if not latest_risk:
        missing.append("missing risk review")
    return {
        "id": strategy.id,
        "item_type": "strategy",
        "title": strategy.name,
        "stage": stage,
        "status": strategy.status,
        "owner_agent": _agent_for_workflow(workflow.workflow_type) if workflow else None,
        "latest_action": workflow.workflow_type if workflow else None,
        "missing_requirements": missing,
        "linked_strategy_id": strategy.id,
        "latest_backtest_id": latest_backtest.id if latest_backtest else None,
        "latest_metrics": latest_backtest.metrics if latest_backtest else {},
        "risk_verdict": latest_risk.verdict if latest_risk else None,
        "approval_status": pending_approval.status if pending_approval else (card.approval_status if card else None),
        "next_actions": _strategy_next_actions(latest_backtest, latest_risk, pending_approval),
        "updated_at": strategy.updated_at,
    }


def _strategy_next_actions(backtest: BacktestRun | None, risk: RiskReview | None, approval: ApprovalRequest | None) -> list[str]:
    if approval:
        return ["处理待审批"]
    if backtest is None:
        return ["启动 BacktestWorkflow"]
    if risk is None:
        return ["申请 RiskReviewWorkflow"]
    return ["申请策略注册", "申请 paper promotion"]


def _strategy_uses_factor(strategy: StrategySpec, factor: FactorSpec) -> bool:
    values = {str(value).lower() for value in (strategy.factors or [])}
    return factor.id.lower() in values or factor.name.lower() in values


def _agent_runs_for_owner(db: Session, owner_type: str, owner_id: str):
    runs = db.scalars(select(AgentRun).order_by(AgentRun.created_at.desc())).all()
    return [
        row
        for row in runs
        if row.input_payload.get(f"{owner_type}_id") == owner_id or row.output_payload.get(f"{owner_type}_id") == owner_id
    ][:10]


def _report_item(db: Session, artifact: Artifact) -> dict[str, Any]:
    owner_name, owner_status = _owner_label(db, artifact.owner_type, artifact.owner_id)
    return {
        "artifact": artifact,
        "owner_name": owner_name,
        "owner_status": owner_status,
        "related_strategy_id": artifact.owner_id if artifact.owner_type == "strategy" else None,
        "related_factor_id": artifact.owner_id if artifact.owner_type == "factor" else None,
        "related_backtest_id": artifact.owner_id if artifact.owner_type == "backtest" else None,
    }


def _owner_label(db: Session, owner_type: str, owner_id: str) -> tuple[str, str | None]:
    if owner_type in {"research", "research_idea"}:
        row = db.get(ResearchIdea, owner_id)
        return (row.title, row.status) if row else (owner_id, None)
    if owner_type == "factor":
        row = db.get(FactorSpec, owner_id)
        return (row.name, row.status) if row else (owner_id, None)
    if owner_type == "strategy":
        row = db.get(StrategySpec, owner_id)
        return (row.name, row.status) if row else (owner_id, None)
    if owner_type == "backtest":
        row = db.get(BacktestRun, owner_id)
        return (f"Backtest {row.id}", row.status) if row else (owner_id, None)
    return owner_id, None


def _agent_for_workflow(workflow_type: str) -> str:
    if "Backtest" in workflow_type:
        return "Backtest Agent"
    if "Risk" in workflow_type:
        return "Risk Agent"
    if "Paper" in workflow_type:
        return "Execution Agent"
    if "Strategy" in workflow_type:
        return "Strategy Agent"
    return "Research Agent"


def _norm(value) -> str:
    return str(value or "").strip().lower()
