from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.compat import APIRouter, Depends, HTTPException
from app.core.auth import require_any_role
from app.db.models import PolicyDecision, RiskReview
from app.db.session import get_db
from app.risk.engine import DEFAULT_POLICY, evaluate_risk_gate, persist_risk_review
from app.schemas import RiskValidateRequest

router = APIRouter(prefix="/api/v1/risk", tags=["risk"])


@router.post("/reviews")
def create_risk_review(payload: RiskValidateRequest, db: Session = Depends(get_db), _user=Depends(require_any_role("risk_reviewer", "admin"))):
    decision = evaluate_risk_gate(
        db,
        payload.metrics,
        payload.cost_model,
        payload.slippage_model,
        payload.factor_report_present,
        start_date=payload.start_date,
        end_date=payload.end_date,
        request_type=payload.request_type,
        evidence_grade=payload.evidence_grade,
    )
    review = persist_risk_review(
        db,
        decision,
        strategy_id=payload.strategy_id,
        backtest_run_id=payload.backtest_run_id,
        actor="RiskAgent",
    )
    db.commit()
    return {
        "verdict": decision.verdict,
        "hard_rule_results": decision.hard_rule_results,
        "risk_summary": {**decision.risk_summary, "verdict": decision.verdict},
        "risk_review_id": review.id if review else None,
    }


@router.get("/reviews")
def list_risk_reviews(db: Session = Depends(get_db), _user=Depends(require_any_role("researcher", "risk_reviewer", "admin"))):
    return db.scalars(select(RiskReview).order_by(RiskReview.created_at.desc())).all()


@router.get("/reviews/{review_id}")
def get_risk_review(review_id: str, db: Session = Depends(get_db), _user=Depends(require_any_role("researcher", "risk_reviewer", "admin"))):
    review = db.get(RiskReview, review_id)
    if not review:
        raise HTTPException(status_code=404, detail="risk review not found")
    return review


@router.get("/policies")
def get_risk_policies(_user=Depends(require_any_role("risk_reviewer", "admin"))):
    return DEFAULT_POLICY


@router.get("/policy-decisions")
def list_risk_policy_decisions(db: Session = Depends(get_db), _user=Depends(require_any_role("risk_reviewer", "admin"))):
    return db.scalars(
        select(PolicyDecision)
        .where(PolicyDecision.policy_package == "risk_gate")
        .order_by(PolicyDecision.created_at.desc())
    ).all()


@router.patch("/policies")
def patch_risk_policies(_user=Depends(require_any_role("admin"))):
    return {"ok": False, "error": "policy editing is not enabled in MVP"}


@router.post("/policies/validate")
def validate_policy(payload: RiskValidateRequest, db: Session = Depends(get_db), _user=Depends(require_any_role("risk_reviewer", "admin"))):
    return evaluate_risk_gate(
        db,
        payload.metrics,
        payload.cost_model,
        payload.slippage_model,
        payload.factor_report_present,
        start_date=payload.start_date,
        end_date=payload.end_date,
        request_type=payload.request_type,
        evidence_grade=payload.evidence_grade,
    )
