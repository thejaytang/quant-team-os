from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.compat import APIRouter, Depends, HTTPException
from app.core.auth import require_any_role
from app.db.models import BacktestRun, StrategySpec
from app.db.session import get_db
from app.schemas import BacktestCreate
from app.services.workflows import start_workflow

router = APIRouter(prefix="/api/v1/backtests", tags=["backtests"])


@router.post("")
def create_backtest(payload: BacktestCreate, db: Session = Depends(get_db), _user=Depends(require_any_role("researcher", "admin"))):
    strategy = db.get(StrategySpec, payload.strategy_id)
    if not strategy:
        raise HTTPException(status_code=404, detail="strategy not found")
    if not payload.dataset_version.strip():
        raise HTTPException(status_code=422, detail="dataset_version is required")
    return start_workflow(db, "BacktestWorkflow", "strategy", payload.strategy_id, payload.model_dump())


@router.get("")
def list_backtests(db: Session = Depends(get_db)):
    return db.scalars(select(BacktestRun).order_by(BacktestRun.created_at.desc())).all()


@router.get("/{backtest_id}")
def get_backtest(backtest_id: str, db: Session = Depends(get_db)):
    run = db.get(BacktestRun, backtest_id)
    if not run:
        raise HTTPException(status_code=404, detail="backtest not found")
    return run


@router.post("/{backtest_id}/rerun")
def rerun_backtest(backtest_id: str, db: Session = Depends(get_db), _user=Depends(require_any_role("researcher", "admin"))):
    run = db.get(BacktestRun, backtest_id)
    if not run:
        raise HTTPException(status_code=404, detail="backtest not found")
    if not run.dataset_version:
        raise HTTPException(status_code=422, detail="backtest is missing dataset_version")
    return start_workflow(
        db,
        "BacktestWorkflow",
        "strategy",
        run.strategy_id,
        {
            "backtest_run_id": run.id,
            "strategy_id": run.strategy_id,
            "dataset_spec_id": run.dataset_spec_id,
            "dataset_version": run.dataset_version,
            "rerun": True,
        },
    )


@router.get("/{backtest_id}/metrics")
def get_backtest_metrics(backtest_id: str, db: Session = Depends(get_db)):
    run = db.get(BacktestRun, backtest_id)
    if not run:
        raise HTTPException(status_code=404, detail="backtest not found")
    return run.metrics


@router.get("/{backtest_id}/artifacts")
def get_backtest_artifacts(backtest_id: str, db: Session = Depends(get_db)):
    run = db.get(BacktestRun, backtest_id)
    if not run:
        raise HTTPException(status_code=404, detail="backtest not found")
    return run.artifacts
