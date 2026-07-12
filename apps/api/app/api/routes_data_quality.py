from __future__ import annotations

from sqlalchemy.orm import Session

from app.api.compat import APIRouter, Depends, HTTPException
from app.core.auth import require_any_role
from app.db.session import get_db
from app.schemas import DataQualityValidateRequest
from app.services.data_quality import list_suites, validate_suite
from app.services.datasets import create_sample_ohlcv_dataset

router = APIRouter(prefix="/api/v1/data-quality", tags=["data-quality"])


@router.get("/suites")
def get_data_quality_suites():
    return {"items": list_suites()}


@router.post("/validate/{suite_name}")
def validate_data_quality_suite(suite_name: str, payload: DataQualityValidateRequest):
    try:
        return validate_suite(suite_name, payload.rows)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/sample-ohlcv-pipeline")
def run_sample_ohlcv_pipeline(db: Session = Depends(get_db), _user=Depends(require_any_role("researcher", "admin"))):
    return create_sample_ohlcv_dataset(db)
