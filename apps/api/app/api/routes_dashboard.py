from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import inspect, select
from sqlalchemy.orm import Session

from app.api.compat import APIRouter, Depends
from app.core.config import get_settings
from app.db.models import (
    AgentRun,
    ApprovalRequest,
    ExternalConnection,
    PaperTradingSession,
    PolicyDecision,
    RiskReview,
    WorkflowLink,
)
from app.db.session import get_db
from app.services.connections import list_connections, seed_connections

router = APIRouter(prefix="/api/v1/dashboard", tags=["dashboard"])


@router.get("/summary")
def dashboard_summary(db: Session = Depends(get_db)):
    settings = get_settings()
    seed_connections(db)
    connections = list_connections(db)
    approvals = db.scalars(select(ApprovalRequest).order_by(ApprovalRequest.created_at.desc())).all()
    risk_reviews = db.scalars(select(RiskReview).order_by(RiskReview.created_at.desc())).all()
    workflows = db.scalars(select(WorkflowLink).order_by(WorkflowLink.created_at.desc())).all()
    agent_runs = db.scalars(select(AgentRun).order_by(AgentRun.created_at.desc())).all()
    paper_sessions = db.scalars(select(PaperTradingSession).order_by(PaperTradingSession.created_at.desc())).all()
    policy_decisions = db.scalars(select(PolicyDecision).order_by(PolicyDecision.created_at.desc())).all()

    pending_approvals = [row for row in approvals if _norm(row.status) == "pending"]
    failed_or_open_risk = [
        row
        for row in risk_reviews
        if _norm(row.verdict) in {"fail", "failed", "blocked", "warning"} or _norm(row.risk_summary.get("verdict")) in {"fail", "failed", "blocked", "warning"}
    ]
    running_workflows = [row for row in workflows if _norm(row.status) in {"running", "started", "queued"}]
    active_agent_runs = [row for row in agent_runs if _norm(row.status) in {"queued", "running", "started"}]
    disconnected = [
        row
        for row in db.scalars(select(ExternalConnection)).all()
        if _norm(row.status) in {"disconnected", "failed", "error"}
    ]
    denied_policies = [row for row in policy_decisions if not row.allowed]

    return {
        "portfolio": {
            "mode": "paper" if paper_sessions else "unavailable",
            "total_equity": None,
            "cash": None,
            "pnl_today": None,
            "gross_exposure": None,
            "net_exposure": None,
            "source": "paper/simulated only; no live broker account connected",
        },
        "status": {
            "api": "healthy",
            "live_trading_locked": not settings.allow_live_trading,
            "environment": settings.app_env,
            "last_refreshed_at": datetime.now(UTC).isoformat(),
        },
        "counts": {
            "pending_approvals": len(pending_approvals),
            "risk_alerts": len(failed_or_open_risk) + len(denied_policies),
            "running_workflows": len(running_workflows),
            "active_agent_runs": len(active_agent_runs),
            "disconnected_tools": len(disconnected),
            "paper_sessions": len(paper_sessions),
        },
        "approvals": [_public_model(row) for row in pending_approvals[:8]],
        "risk_alerts": [_public_model(row) for row in failed_or_open_risk[:8]],
        "running_tasks": [
            *({"type": "agent_run", **_public_model(row)} for row in active_agent_runs[:8]),
            *({"type": "workflow", **_public_model(row)} for row in running_workflows[:8]),
        ][:12],
        "connections": connections,
    }


def _public_model(model) -> dict:
    return {
        ("metadata" if attr.key == "meta" else attr.key): getattr(model, attr.key)
        for attr in inspect(model).mapper.column_attrs
    }


def _norm(value) -> str:
    return str(value or "").strip().lower()
