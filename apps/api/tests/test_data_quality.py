import json
from datetime import date

import pandas as pd

from app.api.routes_data_quality import get_data_quality_suites, validate_data_quality_suite
from app.core.config import get_settings
from app.db.models import Artifact, DatasetSpec
from app.schemas import DataQualityValidateRequest
from app.services.data_quality import validate_suite
from app.services.datasets import (
    SAMPLE_OHLCV_ROWS,
    create_ohlcv_dataset,
    create_sample_ohlcv_dataset,
    dvc_version_metadata,
    query_ohlcv_rows,
)
from data_contracts.dlt.massive_source import build_source


def test_number_rejects_non_finite_values():
    from app.services.data_quality import _between_failures, _number, _pair_failures

    assert _number(float("nan")) is None
    assert _number(float("inf")) is None
    assert _number("1.5") == 1.5

    # NaN in a bounded column must be flagged, not silently pass the range check.
    rows = [{"close": float("nan")}, {"close": 1.5}]
    assert _between_failures(rows, "close", 0, 10) == [0]

    # NaN in a pairwise comparison must fail closed too.
    pair_rows = [{"high": float("nan"), "low": 1.0}, {"high": 2.0, "low": 1.0}]
    assert _pair_failures(pair_rows, "high", "low", or_equal=False) == [0]


def test_ohlcv_suite_passes_valid_rows():
    result = validate_suite(
        "ohlcv_daily_suite",
        [{"symbol": "SPY", "date": "2026-01-02", "open": 1, "high": 2, "low": 1, "close": 1.5, "volume": 100}],
    )

    assert result["success"] is True
    assert result["row_count"] == 1
    assert result["engine"] in {"great_expectations", "great_expectations_with_local_custom", "local_fallback"}


def test_ohlcv_suite_fails_duplicate_and_bad_range():
    result = validate_suite(
        "ohlcv_daily_suite",
        [
            {"symbol": "SPY", "date": "2026-01-02", "open": 1, "high": 1, "low": 2, "close": 1.5, "volume": -1},
            {"symbol": "SPY", "date": "2026-01-02", "open": 1, "high": 2, "low": 1, "close": 1.5, "volume": 100},
        ],
    )

    assert result["success"] is False
    failed = {item["expectation_type"] for item in result["results"] if not item["success"]}
    assert "expect_column_pair_values_A_to_be_greater_than_B" in failed
    assert "expect_compound_columns_to_be_unique" in failed
    assert result["engine"] in {"great_expectations", "great_expectations_with_local_custom", "local_fallback"}


def test_ohlcv_suite_fails_unsorted_dates_within_symbol():
    result = validate_suite(
        "ohlcv_daily_suite",
        [
            {"symbol": "SPY", "date": "2026-01-03", "open": 1, "high": 2, "low": 1, "close": 1.5, "volume": 100},
            {"symbol": "SPY", "date": "2026-01-02", "open": 1, "high": 2, "low": 1, "close": 1.5, "volume": 100},
        ],
    )

    assert result["success"] is False
    failed = {item["expectation_type"] for item in result["results"] if not item["success"]}
    assert "expect_column_values_to_be_strictly_increasing_within_group" in failed


def test_massive_source_exposes_dlt_contract():
    source = build_source(["SPY"], date(2026, 1, 2), date(2026, 1, 3))

    assert source.resource_name() == "massive_ohlcv_1d"
    assert source.contract()["tool"] == "dlt"
    assert source.contract()["source"] == "massive"


def test_data_quality_routes_use_contracts():
    suites = get_data_quality_suites()["items"]
    assert any(item["name"] == "ohlcv_daily_suite" for item in suites)

    result = validate_data_quality_suite(
        "backtest_orders_suite",
        DataQualityValidateRequest(rows=[{"timestamp": "2026-01-02T14:30:00Z", "symbol": "SPY", "quantity": 10, "side": "buy"}]),
    )
    assert result["success"] is True


def test_factor_values_suite_rejects_non_finite_values():
    result = validate_suite(
        "factor_values_suite",
        [
            {"factor_id": "mom", "symbol": "SPY", "date": "2026-01-02", "value": float("nan"), "missing_ratio": 0.01},
            {"factor_id": "mom", "symbol": "QQQ", "date": "2026-01-02", "value": 1.2, "missing_ratio": 0.01},
        ],
    )

    assert result["success"] is False
    failed = {item["expectation_type"] for item in result["results"] if not item["success"]}
    assert "expect_column_values_to_be_finite" in failed


def test_backtest_orders_suite_rejects_negative_buy_quantity():
    failed = validate_suite(
        "backtest_orders_suite",
        [{"timestamp": "2026-01-02T14:30:00Z", "symbol": "SPY", "quantity": -10, "side": "buy"}],
    )
    passed = validate_suite(
        "backtest_orders_suite",
        [{"timestamp": "2026-01-02T14:30:00Z", "symbol": "SPY", "quantity": -10, "side": "sell"}],
    )

    failed_types = {item["expectation_type"] for item in failed["results"] if not item["success"]}
    assert failed["success"] is False
    assert "expect_negative_quantity_requires_side" in failed_types
    assert passed["success"] is True


def test_sample_ohlcv_pipeline_creates_versioned_dataset(tmp_path, monkeypatch, db):
    monkeypatch.setenv("ARTIFACT_ROOT", str(tmp_path))
    monkeypatch.setenv("ENABLE_MINIO_UPLOAD", "false")
    get_settings.cache_clear()
    try:
        result = create_sample_ohlcv_dataset(db)
    finally:
        get_settings.cache_clear()

    dataset = db.get(DatasetSpec, result["dataset_spec_id"])
    artifact = db.get(Artifact, result["artifact_id"])
    gx_artifact = db.get(Artifact, result["gx_artifact_id"])

    assert dataset.dataset_version.startswith("dlt:massive:")
    assert dataset.dvc_rev == result["dvc_rev"]
    assert artifact.dvc_rev == dataset.dvc_rev
    assert gx_artifact.dvc_rev == dataset.dvc_rev
    assert gx_artifact.artifact_type == "gx_validation"
    assert gx_artifact.owner_type == "dataset"
    assert gx_artifact.owner_id == dataset.id
    assert gx_artifact.meta["gx_success"] is True
    assert artifact.meta["dlt_source"] == "massive_ohlcv_1d"
    assert artifact.meta["dlt_contract"]["tool"] == "dlt"
    assert artifact.meta["format"] == "parquet"
    assert artifact.meta["gx_validation_artifact_id"] == gx_artifact.id
    assert artifact.meta["gx_success"] is True
    assert artifact.meta["gx_engine"] in {"great_expectations", "great_expectations_with_local_custom", "local_fallback"}
    assert artifact.meta["dvc_remote"] == "minio"
    assert artifact.meta["dvc_mode"] in {"dvc_ready", "dvc_library_available", "local_fallback"}
    assert result["gx"]["success"] is True
    assert result["query"]["row_count"] == 3
    artifact_path = tmp_path / artifact.path
    assert result["dataset_path"] == str(artifact_path)
    assert artifact_path.suffix == ".parquet"
    assert artifact_path.exists()
    assert len(pd.read_parquet(artifact_path)) == 3
    gx_payload = json.loads((tmp_path / gx_artifact.path).read_text())
    assert gx_payload["suite"] == "ohlcv_daily_suite"
    assert gx_payload["result"]["success"] is True
    duckdb_result = query_ohlcv_rows([], artifact_path)
    assert duckdb_result["engine"] == "duckdb"
    assert duckdb_result["row_count"] == 3


def test_sample_ohlcv_pipeline_skips_local_artifacts_in_production(tmp_path, monkeypatch, db):
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("ARTIFACT_ROOT", str(tmp_path))
    monkeypatch.setenv("ENABLE_MINIO_UPLOAD", "true")
    get_settings.cache_clear()
    calls = []

    def fake_store(bucket, key, raw, content_type):
        calls.append((bucket, key, raw, content_type))
        return {"storage_mode": "minio"}

    monkeypatch.setattr("app.services.artifacts._store_minio", fake_store)
    try:
        result = create_ohlcv_dataset(
            db,
            "sample_spy_daily",
            [dict(row) for row in SAMPLE_OHLCV_ROWS],
            gx_result={"suite": "ohlcv_daily_suite", "success": True, "row_count": len(SAMPLE_OHLCV_ROWS), "results": [], "engine": "great_expectations"},
        )
    finally:
        get_settings.cache_clear()

    artifact = db.get(Artifact, result["artifact_id"])
    gx_artifact = db.get(Artifact, result["gx_artifact_id"])

    assert result["dataset_path"] is None
    assert result["query"]["row_count"] == 3
    assert artifact.meta["storage_mode"] == "minio"
    assert gx_artifact.meta["storage_mode"] == "minio"
    assert artifact.meta["local_mirror_written"] is False
    assert gx_artifact.meta["local_mirror_written"] is False
    assert not (tmp_path / artifact.path).exists()
    assert not (tmp_path / gx_artifact.path).exists()
    assert {call[0] for call in calls} == {"qto-datasets"}


def test_dvc_metadata_uses_minio_remote_boundary():
    meta = dvc_version_metadata("ds1", "symbol,date\nSPY,2026-01-02\n")

    assert meta["remote"] == "minio"
    assert meta["mode"] in {"dvc_ready", "dvc_library_available", "local_fallback"}
    assert len(meta["dvc_rev"]) == 12
