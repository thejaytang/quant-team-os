from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.compat import APIRouter, Depends, HTTPException
from app.core.auth import require_any_role
from app.db.models import StrategyCard, StrategySpec
from app.db.session import get_db
from app.schemas import StrategyCreate
from app.services.audit import write_audit_log
from app.services.strategy_state import can_request_paper_promotion
from app.services.workflows import start_workflow

router = APIRouter(prefix="/api/v1/strategies", tags=["strategies"])


@router.get("")
def list_strategies(db: Session = Depends(get_db)):
    strategies = db.scalars(select(StrategySpec).order_by(StrategySpec.created_at.desc())).all()
    cards = {
        card.strategy_id: card
        for card in db.scalars(select(StrategyCard).where(StrategyCard.strategy_id.in_([strategy.id for strategy in strategies]))).all()
    }
    return [{**_model_dict(strategy), "card": cards.get(strategy.id)} for strategy in strategies]


@router.post("")
def create_strategy(payload: StrategyCreate, db: Session = Depends(get_db), _user=Depends(require_any_role("researcher", "admin"))):
    strategy = StrategySpec(name=payload.name, description=payload.description, universe=payload.universe)
    db.add(strategy)
    db.flush()
    write_audit_log(db, "strategy.created", "strategy", strategy.id, payload.model_dump())
    return strategy


@router.get("/{strategy_id}")
def get_strategy(strategy_id: str, db: Session = Depends(get_db)):
    strategy = db.get(StrategySpec, strategy_id)
    if not strategy:
        raise HTTPException(status_code=404, detail="strategy not found")
    return strategy


@router.get("/{strategy_id}/card")
def get_strategy_card(strategy_id: str, db: Session = Depends(get_db)):
    card = db.scalar(select(StrategyCard).where(StrategyCard.strategy_id == strategy_id))
    if not card:
        raise HTTPException(status_code=404, detail="strategy card not found")
    return card


def _model_dict(model) -> dict:
    return {column.name: getattr(model, column.name) for column in model.__table__.columns}


@router.post("/{strategy_id}/request-registration")
def request_registration(strategy_id: str, db: Session = Depends(get_db), _user=Depends(require_any_role("researcher", "admin"))):
    strategy = db.get(StrategySpec, strategy_id)
    if not strategy:
        raise HTTPException(status_code=404, detail="strategy not found")
    return start_workflow(db, "StrategyRegistrationWorkflow", "strategy", strategy.id, {"strategy_id": strategy.id})


@router.post("/{strategy_id}/request-paper-promotion")
def request_paper_promotion(strategy_id: str, db: Session = Depends(get_db), _user=Depends(require_any_role("researcher", "admin"))):
    strategy = db.get(StrategySpec, strategy_id)
    if not strategy:
        raise HTTPException(status_code=404, detail="strategy not found")
    if strategy.status != "STRATEGY_REGISTERED":
        raise HTTPException(status_code=409, detail="strategy must be STRATEGY_REGISTERED")
    ok, reason = can_request_paper_promotion(db, strategy.id)
    if not ok:
        raise HTTPException(status_code=409, detail=reason)
    return start_workflow(db, "PaperPromotionWorkflow", "strategy", strategy.id, {"strategy_id": strategy.id, "requires_approval": True})
