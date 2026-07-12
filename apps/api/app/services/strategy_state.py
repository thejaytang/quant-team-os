from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import ApprovalRecord, ApprovalRequest, BacktestRun, RiskReview, StrategyCard, StrategySpec
from app.services.audit import write_audit_log
from app.services.policy import evaluate_policy

ALLOWED_TRANSITIONS = {
    "IDEA": {"RESEARCHING"},
    "RESEARCHING": {"FACTOR_TESTED", "BACKTESTED"},
    "FACTOR_TESTED": {"BACKTESTED"},
    "BACKTESTED": {"RISK_REVIEWED"},
    "RISK_REVIEWED": {"APPROVAL_PENDING"},
    "APPROVAL_PENDING": {"STRATEGY_REGISTERED"},
    "STRATEGY_REGISTERED": {"PAPER_CANDIDATE", "RETIRED"},
    "PAPER_CANDIDATE": {"PAPER_APPROVED"},
    "PAPER_APPROVED": {"PAPER_TRADING"},
    "PAPER_TRADING": {"LIVE_CANDIDATE", "RETIRED"},
    "LIVE_CANDIDATE": {"LIVE_LOCKED"},
    "LIVE_LOCKED": {"RETIRED"},
}


def transition_strategy(db: Session, strategy: StrategySpec, new_status: str, actor: str = "system") -> StrategySpec:
    if new_status == "LIVE_TRADING":
        raise PermissionError("LIVE_TRADING is not available in MVP")
    allowed = ALLOWED_TRANSITIONS.get(strategy.status, set())
    if new_status not in allowed and strategy.status != new_status:
        raise ValueError(f"invalid strategy transition: {strategy.status} -> {new_status}")
    strategy.status = new_status
    card = db.scalar(select(StrategyCard).where(StrategyCard.strategy_id == strategy.id))
    if card:
        card.current_status = new_status
    write_audit_log(db, "strategy.status_changed", "strategy", strategy.id, {"status": new_status}, actor=actor)
    db.flush()
    return strategy


def can_register_strategy(db: Session, strategy_id: str, approval_request_id: str) -> tuple[bool, str]:
    db.flush()
    risk_review = db.scalar(
        select(RiskReview)
        .where(RiskReview.strategy_id == strategy_id)
        .order_by(RiskReview.created_at.desc())
        .limit(1)
    )
    if not risk_review:
        return False, "missing RiskReview"
    if risk_review.verdict != "pass":
        return False, f"risk review verdict is {risk_review.verdict}"
    request = db.get(ApprovalRequest, approval_request_id)
    if not request or request.status != "approved":
        return False, "missing approved ApprovalRequest"
    record = db.scalar(select(ApprovalRecord).where(ApprovalRecord.approval_request_id == approval_request_id, ApprovalRecord.action == "approved"))
    if not record:
        return False, "missing approved ApprovalRecord"
    return True, "ok"


def register_strategy_after_approval(db: Session, strategy_id: str, approval_request_id: str, actor: str = "local_user") -> StrategySpec:
    ok, reason = can_register_strategy(db, strategy_id, approval_request_id)
    if not ok:
        raise PermissionError(reason)
    strategy = db.get(StrategySpec, strategy_id)
    if not strategy:
        raise ValueError("strategy not found")
    if strategy.status != "APPROVAL_PENDING":
        raise ValueError(f"strategy must be APPROVAL_PENDING, got {strategy.status}")
    request = db.get(ApprovalRequest, approval_request_id)
    evaluation = evaluate_policy(
        db,
        "strategy_lifecycle",
        "register_strategy",
        _strategy_registration_input(db, strategy_id, request),
        actor=actor,
        workflow_id=request.workflow_id if request else None,
    )
    if not evaluation.allowed:
        raise PermissionError("; ".join(evaluation.reasons))
    strategy = transition_strategy(db, strategy, "STRATEGY_REGISTERED", actor=actor)
    card = db.scalar(select(StrategyCard).where(StrategyCard.strategy_id == strategy.id))
    if card:
        card.approval_status = "approved"
    return strategy


def can_request_paper_promotion(db: Session, strategy_id: str) -> tuple[bool, str]:
    db.flush()
    risk_review, backtest = _latest_risk_and_backtest(db, strategy_id)
    if not risk_review:
        return False, "missing RiskReview"
    if risk_review.verdict != "pass":
        return False, "latest risk review must pass"
    if not backtest or not backtest.cost_model:
        return False, "cost model is required"
    if not backtest.slippage_model:
        return False, "slippage model is required"
    return True, "ok"


def promote_strategy_to_paper_after_approval(db: Session, strategy_id: str, approval_request_id: str, actor: str = "local_user") -> StrategySpec:
    request = db.get(ApprovalRequest, approval_request_id)
    if not request or request.status != "approved":
        raise PermissionError("missing approved ApprovalRequest")
    record = db.scalar(select(ApprovalRecord).where(ApprovalRecord.approval_request_id == approval_request_id, ApprovalRecord.action == "approved"))
    if not record:
        raise PermissionError("missing approved ApprovalRecord")
    evaluation = evaluate_policy(
        db,
        "strategy_lifecycle",
        "promote_to_paper",
        _paper_promotion_input(db, strategy_id, request),
        actor=actor,
        workflow_id=request.workflow_id,
    )
    if not evaluation.allowed:
        raise PermissionError("; ".join(evaluation.reasons))
    strategy = db.get(StrategySpec, strategy_id)
    if not strategy:
        raise ValueError("strategy not found")
    if strategy.status != "PAPER_CANDIDATE":
        raise ValueError(f"strategy must be PAPER_CANDIDATE, got {strategy.status}")
    strategy = transition_strategy(db, strategy, "PAPER_APPROVED", actor=actor)
    card = db.scalar(select(StrategyCard).where(StrategyCard.strategy_id == strategy.id))
    if card:
        card.paper_trading_status = "approved"
    return strategy


def _latest_risk_and_backtest(db: Session, strategy_id: str) -> tuple[RiskReview | None, BacktestRun | None]:
    risk_review = db.scalar(
        select(RiskReview)
        .where(RiskReview.strategy_id == strategy_id)
        .order_by(RiskReview.created_at.desc())
        .limit(1)
    )
    if not risk_review:
        return None, None
    return risk_review, db.get(BacktestRun, risk_review.backtest_run_id)


def _paper_promotion_input(db: Session, strategy_id: str, request: ApprovalRequest) -> dict:
    risk_review, backtest = _latest_risk_and_backtest(db, strategy_id)
    return {
        "action": "promote_to_paper",
        "approval": {"status": request.status, "approved_by_human": request.status == "approved"},
        "strategy": {
            "id": strategy_id,
            "latest_risk_review": {"verdict": risk_review.verdict if risk_review else "missing"},
            "latest_backtest": {
                "has_cost_model": bool(backtest and backtest.cost_model),
                "has_slippage_model": bool(backtest and backtest.slippage_model),
            },
        },
    }


def _strategy_registration_input(db: Session, strategy_id: str, request: ApprovalRequest | None) -> dict:
    risk_review, backtest = _latest_risk_and_backtest(db, strategy_id)
    return {
        "action": "register_strategy",
        "approval": {
            "status": request.status if request else "missing",
            "approved_by_human": bool(request and request.status == "approved"),
        },
        "strategy": {
            "id": strategy_id,
            "latest_risk_review": {"verdict": risk_review.verdict if risk_review else "missing"},
            "latest_backtest": {
                "has_cost_model": bool(backtest and backtest.cost_model),
                "has_slippage_model": bool(backtest and backtest.slippage_model),
            },
        },
    }
