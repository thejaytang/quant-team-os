from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.compat import APIRouter, Depends, HTTPException
from app.core.auth import require_any_role
from app.db.models import Artifact, FactorSpec
from app.db.session import get_db
from app.services.workflows import start_workflow

router = APIRouter(prefix="/api/v1/factors", tags=["factors"])


@router.get("")
def list_factors(db: Session = Depends(get_db)):
    return db.scalars(select(FactorSpec).order_by(FactorSpec.created_at.desc())).all()


@router.get("/{factor_id}")
def get_factor(factor_id: str, db: Session = Depends(get_db)):
    factor = db.get(FactorSpec, factor_id)
    if not factor:
        raise HTTPException(status_code=404, detail="factor not found")
    return factor


@router.post("/{factor_id}/run-analysis")
def run_factor_analysis(factor_id: str, db: Session = Depends(get_db), _user=Depends(require_any_role("researcher", "admin"))):
    factor = db.get(FactorSpec, factor_id)
    if not factor:
        raise HTTPException(status_code=404, detail="factor not found")
    return start_workflow(db, "FactorAnalysisWorkflow", "factor", factor.id, {"factor_spec_id": factor.id})


@router.post("/{factor_id}/analyze")
def analyze_factor(factor_id: str, db: Session = Depends(get_db), _user=Depends(require_any_role("researcher", "admin"))):
    return run_factor_analysis(factor_id, db)


@router.get("/{factor_id}/reports")
def get_factor_reports(factor_id: str, db: Session = Depends(get_db)):
    return db.scalars(select(Artifact).where(Artifact.owner_type == "factor", Artifact.owner_id == factor_id)).all()
