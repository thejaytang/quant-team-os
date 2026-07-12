from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.compat import APIRouter, Depends, HTTPException
from app.core.auth import require_any_role
from app.db.models import ExternalConnection, PaperTradingSession, StrategySpec
from app.db.session import get_db
from app.services.connections import seed_connections
from app.services.workflows import start_workflow

router = APIRouter(prefix="/api/v1/paper-trading", tags=["paper-trading"])


@router.get("/sessions")
def list_paper_trading_sessions(db: Session = Depends(get_db)):
    rows = db.scalars(select(PaperTradingSession).order_by(PaperTradingSession.created_at.desc())).all()
    return [_public_session(row) for row in rows]


@router.post("/sessions")
def create_paper_trading_session(payload: dict, db: Session = Depends(get_db), _user=Depends(require_any_role("approver", "admin"))):
    strategy_id = payload.get("strategy_id")
    if not strategy_id:
        raise HTTPException(status_code=400, detail="strategy_id is required")
    strategy = db.get(StrategySpec, strategy_id)
    if not strategy:
        raise HTTPException(status_code=404, detail="strategy not found")
    if strategy.status != "PAPER_APPROVED":
        raise HTTPException(status_code=409, detail="strategy must be PAPER_APPROVED")
    seed_connections(db)
    quantconnect = db.scalar(select(ExternalConnection).where(ExternalConnection.provider == "quantconnect"))
    if not quantconnect or quantconnect.status != "connected":
        raise HTTPException(status_code=409, detail="QuantConnect connection must be connected")
    workflow = start_workflow(db, "PaperPromotionWorkflow", "strategy", strategy_id, {"strategy_id": strategy_id, "requires_approval": False})
    session = PaperTradingSession(
        strategy_id=strategy_id,
        provider="quantconnect",
        status="proposed",
        workflow_id=workflow["workflow_id"],
        meta={"permission_level": "paper_trade", "message": "QuantConnect paper trading proposal only until approval resolves."},
    )
    db.add(session)
    db.flush()
    return _public_session(session)


@router.get("/sessions/{session_id}")
def get_paper_trading_session(session_id: str, db: Session = Depends(get_db)):
    session = db.get(PaperTradingSession, session_id)
    if not session:
        raise HTTPException(status_code=404, detail="paper trading session not found")
    return _public_session(session)


def _public_session(session: PaperTradingSession) -> dict:
    return {
        "id": session.id,
        "strategy_id": session.strategy_id,
        "provider": session.provider,
        "status": session.status,
        "workflow_id": session.workflow_id,
        "deployment_ref": session.deployment_ref,
        "metadata": session.meta or {},
        "created_at": session.created_at,
        "updated_at": session.updated_at,
    }
