from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.models import Artifact, BacktestRun
from app.services.audit import write_audit_log


def log_backtest_run_to_mlflow(
    db: Session,
    backtest: BacktestRun,
    params: dict[str, Any],
    metrics: dict[str, Any],
    artifacts: list[Artifact],
) -> dict[str, Any]:
    settings = get_settings()
    try:
        import mlflow

        mlflow.set_tracking_uri(settings.mlflow_tracking_uri)
        with mlflow.start_run(run_name=f"backtest-{backtest.id}") as run:
            run_id = run.info.run_id
            mlflow.log_params({key: str(value) for key, value in _backtest_params(backtest, params).items()})
            mlflow.log_metrics({key: float(value) for key, value in metrics.items() if isinstance(value, (int, float))})
            for artifact in artifacts:
                path = Path(settings.artifact_root) / artifact.path
                if path.exists():
                    mlflow.log_artifact(str(path), artifact_path=artifact.owner_type)
        mode = "mlflow"
    except Exception as exc:
        if settings.app_env == "production" or not settings.allow_mature_tool_fallback:
            raise
        run_id = f"local-{backtest.id}"
        mode = "local_mirror"
        error = str(exc)
    else:
        error = None

    backtest.mlflow_run_id = run_id
    for artifact in artifacts:
        artifact.mlflow_run_id = run_id
        artifact.meta = {**(artifact.meta or {}), "mlflow_run_id": run_id, "mlflow_mode": mode}
    write_audit_log(
        db,
        "mlflow.backtest_logged",
        "backtest",
        backtest.id,
        {"mlflow_run_id": run_id, "mode": mode, "error": error},
    )
    db.flush()
    return {"mlflow_run_id": run_id, "mode": mode, "error": error}


def _backtest_params(backtest: BacktestRun, params: dict[str, Any]) -> dict[str, Any]:
    return {
        **params,
        "strategy_id": backtest.strategy_id,
        "dataset_spec_id": backtest.dataset_spec_id,
        "dataset_version": backtest.dataset_version or params.get("dataset_version") or "",
        "workflow_id": params.get("workflow_id") or "",
        "factor_id": params.get("factor_id") or "",
        "dvc_rev": params.get("dvc_rev") or "",
        "git_commit": params.get("git_commit") or os.getenv("GIT_COMMIT", "unknown"),
    }
