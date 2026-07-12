from __future__ import annotations

import hashlib
import io
import json
from datetime import date
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.models import DatasetSpec
from app.services.artifacts import create_artifact
from app.services.data_quality import validate_suite
from data_contracts.dlt.massive_source import build_source

SAMPLE_OHLCV_ROWS = [
    {"symbol": "SPY", "date": "2026-01-02", "open": 470.0, "high": 474.0, "low": 468.5, "close": 472.2, "volume": 81230000},
    {"symbol": "SPY", "date": "2026-01-05", "open": 472.3, "high": 475.1, "low": 470.8, "close": 474.4, "volume": 73510000},
    {"symbol": "SPY", "date": "2026-01-06", "open": 474.2, "high": 477.0, "low": 473.1, "close": 476.2, "volume": 70190000},
]


def create_sample_ohlcv_dataset(db: Session, name: str = "sample_spy_daily") -> dict[str, Any]:
    rows = [dict(row) for row in SAMPLE_OHLCV_ROWS]
    return create_ohlcv_dataset(db, name, rows)


def create_ohlcv_dataset(
    db: Session,
    name: str,
    rows: list[dict[str, Any]],
    *,
    dataset_spec_id: str | None = None,
    dataset_version: str | None = None,
    dvc_rev: str | None = None,
    gx_result: dict[str, Any] | None = None,
    dlt_contract: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if not rows:
        raise ValueError("rows are required")
    parquet_bytes = _parquet_bytes(rows)
    symbols = sorted({str(row["symbol"]) for row in rows})
    source = build_source(
        symbols,
        date.fromisoformat(rows[0]["date"]),
        date.fromisoformat(rows[-1]["date"]),
        "1d",
    )
    version = dvc_version_metadata(name, parquet_bytes)
    if dvc_rev:
        version["dvc_rev"] = dvc_rev
    dataset = db.get(DatasetSpec, dataset_spec_id) if dataset_spec_id and dataset_spec_id != "pending" else None
    dataset_version = dataset_version or f"dlt:massive:{version['dvc_rev']}"

    if not dataset:
        dataset_kwargs = {"name": name}
        if dataset_spec_id and dataset_spec_id != "pending":
            dataset_kwargs["id"] = dataset_spec_id
        dataset = DatasetSpec(**dataset_kwargs)
        db.add(dataset)
    dataset.name = name
    dataset.asset_class = "equity"
    dataset.frequency = "1d"
    dataset.source = "massive"
    dataset.filters = {"symbols": symbols, "start": rows[0]["date"], "end": rows[-1]["date"]}
    dataset.dataset_version = dataset_version
    dataset.dvc_rev = version["dvc_rev"]
    db.flush()

    gx_result = gx_result or validate_suite("ohlcv_daily_suite", rows)
    gx_artifact = create_artifact(
        db,
        "gx_validation",
        "dataset",
        dataset.id,
        f"datasets/{dataset.id}/gx/ohlcv_daily_suite.json",
        json.dumps({"suite": "ohlcv_daily_suite", "result": gx_result}, sort_keys=True, default=str),
        "application/json",
        {
            "gx_suite": "ohlcv_daily_suite",
            "gx_success": gx_result["success"],
            "gx_engine": gx_result["engine"],
            "dataset_version": dataset.dataset_version,
            "dvc_rev": dataset.dvc_rev,
        },
    )
    gx_artifact.dvc_rev = version["dvc_rev"]
    artifact = create_artifact(
        db,
        "versioned_ohlcv_dataset",
        "dataset",
        dataset.id,
        f"datasets/{dataset.id}/ohlcv_daily.parquet",
        parquet_bytes,
        "application/vnd.apache.parquet",
        {
            "format": "parquet",
            "dlt_source": source.resource_name(),
            "dlt_contract": dlt_contract or source.contract(),
            "gx_suite": "ohlcv_daily_suite",
            "gx_success": gx_result["success"],
            "gx_engine": gx_result["engine"],
            "gx_validation_artifact_id": gx_artifact.id,
            "dvc_remote": "minio",
            "dvc_mode": version["mode"],
            "dvc_config": version["config_path"],
            "dataset_version": dataset.dataset_version,
            "dvc_rev": dataset.dvc_rev,
        },
    )
    artifact.dvc_rev = version["dvc_rev"]
    local_dataset_path = Path(get_settings().artifact_root) / artifact.path if artifact.meta.get("local_mirror_written") else None

    return {
        "dataset_spec_id": dataset.id,
        "dataset_version": dataset.dataset_version,
        "dvc_rev": dataset.dvc_rev,
        "dataset_path": str(local_dataset_path) if local_dataset_path else None,
        "artifact_id": artifact.id,
        "gx_artifact_id": gx_artifact.id,
        "artifact_checksum": artifact.checksum,
        "gx": gx_result,
        "query": query_ohlcv_rows(rows, local_dataset_path),
    }


def dvc_version_metadata(dataset_id: str, content: str | bytes) -> dict[str, str]:
    raw = content.encode("utf-8") if isinstance(content, str) else content
    revision = hashlib.sha256(raw).hexdigest()[:12]
    config_path = _dvc_config_path()
    try:
        import dvc.api  # noqa: F401

        mode = "dvc_ready" if config_path.exists() else "dvc_library_available"
    except Exception:
        mode = "local_fallback"
    return {
        "dataset_id": dataset_id,
        "dvc_rev": revision,
        "remote": "minio",
        "mode": mode,
        "config_path": str(config_path),
    }


def _dvc_config_path() -> Path:
    for parent in Path(__file__).resolve().parents:
        candidate = parent / ".dvc" / "config"
        if candidate.exists():
            return candidate
    return Path(__file__).resolve().parents[2] / ".dvc" / "config"


def query_ohlcv_rows(rows: list[dict[str, Any]], parquet_path: Path | None = None) -> dict[str, Any]:
    try:
        import duckdb

        if parquet_path:
            result = duckdb.connect(":memory:").execute(
                "select count(*) as row_count, avg(close) as avg_close from read_parquet(?)",
                [str(parquet_path)],
            ).fetchone()
        else:
            values = ", ".join(f"({float(row['close'])})" for row in rows)
            result = duckdb.sql(f"select count(*) as row_count, avg(close) as avg_close from (values {values}) as t(close)").fetchone()
        return {"engine": "duckdb", "row_count": result[0], "avg_close": float(result[1])}
    except Exception:
        closes = [float(row["close"]) for row in rows]
        avg_close = sum(closes) / len(closes) if closes else None
        return {"engine": "python_fallback", "row_count": len(rows), "avg_close": avg_close}


def _parquet_bytes(rows: list[dict[str, Any]]) -> bytes:
    import pandas as pd

    output = io.BytesIO()
    pd.DataFrame(rows).to_parquet(output, index=False)
    return output.getvalue()
