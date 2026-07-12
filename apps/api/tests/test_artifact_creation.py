import hashlib

import pytest

from app.core.config import get_settings
from app.services.artifacts import artifact_access_url, create_artifact


def test_artifact_creation(tmp_path, monkeypatch, db):
    monkeypatch.setenv("ARTIFACT_ROOT", str(tmp_path))
    get_settings.cache_clear()
    artifact = create_artifact(db, "report", "strategy", "s1", "strategies/s1/report.html", "<h1>ok</h1>", "text/html")
    db.commit()
    assert artifact.checksum
    assert (tmp_path / artifact.path).exists()
    assert artifact.meta["storage_mode"] == "local_mirror"
    get_settings.cache_clear()


def test_artifact_minio_upload_boundary(tmp_path, monkeypatch, db):
    monkeypatch.setenv("ARTIFACT_ROOT", str(tmp_path))
    monkeypatch.setenv("ENABLE_MINIO_UPLOAD", "true")
    get_settings.cache_clear()
    calls = []

    def fake_store(bucket, key, raw, content_type):
        calls.append((bucket, key, raw, content_type))
        return {"storage_mode": "minio"}

    monkeypatch.setattr("app.services.artifacts._store_minio", fake_store)
    artifact = create_artifact(db, "report", "strategy", "s1", "strategies/s1/report.html", "<h1>ok</h1>", "text/html")

    assert artifact.meta["storage_mode"] == "minio"
    assert artifact.meta["local_mirror_written"] is True
    assert (tmp_path / artifact.path).exists()
    assert artifact.checksum == hashlib.sha256(b"<h1>ok</h1>").hexdigest()
    assert calls[0][0] == artifact.minio_bucket
    assert calls[0][1] == artifact.object_key
    get_settings.cache_clear()


def test_artifact_minio_upload_skips_local_mirror_in_production(tmp_path, monkeypatch, db):
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("ARTIFACT_ROOT", str(tmp_path))
    monkeypatch.setenv("ENABLE_MINIO_UPLOAD", "true")
    get_settings.cache_clear()

    def fake_store(bucket, key, raw, content_type):
        return {"storage_mode": "minio"}

    monkeypatch.setattr("app.services.artifacts._store_minio", fake_store)
    artifact = create_artifact(db, "report", "strategy", "s1", "strategies/s1/report.html", "<h1>ok</h1>", "text/html")

    assert artifact.meta["storage_mode"] == "minio"
    assert artifact.meta["local_mirror_written"] is False
    assert not (tmp_path / artifact.path).exists()
    get_settings.cache_clear()


def test_artifact_bucket_routes_by_artifact_kind(tmp_path, monkeypatch, db):
    monkeypatch.setenv("ARTIFACT_ROOT", str(tmp_path))
    get_settings.cache_clear()

    dataset = create_artifact(db, "versioned_ohlcv_dataset", "dataset", "ds1", "datasets/ds1/ohlcv.csv", "x", "text/csv")
    report = create_artifact(db, "quantstats_strategy_tear_sheet", "backtest", "bt1", "backtests/bt1/report.html", "<h1>ok</h1>", "text/html")
    generic = create_artifact(db, "raw_json", "tool", "tool1", "tools/tool1/output.json", "{}", "application/json")

    assert dataset.minio_bucket == "qto-datasets"
    assert report.minio_bucket == "qto-reports"
    assert generic.minio_bucket == "qto-artifacts"
    get_settings.cache_clear()


def test_artifact_minio_upload_failure_is_not_silent(tmp_path, monkeypatch, db):
    monkeypatch.setenv("ARTIFACT_ROOT", str(tmp_path))
    monkeypatch.setenv("ENABLE_MINIO_UPLOAD", "true")
    get_settings.cache_clear()

    def fail_store(*_args, **_kwargs):
        raise RuntimeError("MinIO artifact upload failed: offline")

    monkeypatch.setattr("app.services.artifacts._store_minio", fail_store)
    with pytest.raises(RuntimeError, match="MinIO artifact upload failed"):
        create_artifact(db, "report", "strategy", "s1", "strategies/s1/report.html", "<h1>ok</h1>", "text/html")
    get_settings.cache_clear()


def test_artifact_access_url_uses_local_download_when_minio_disabled(tmp_path, monkeypatch, db):
    monkeypatch.setenv("ARTIFACT_ROOT", str(tmp_path))
    monkeypatch.setenv("ENABLE_MINIO_UPLOAD", "false")
    get_settings.cache_clear()
    artifact = create_artifact(db, "report", "strategy", "s1", "strategies/s1/report.html", "<h1>ok</h1>", "text/html")

    result = artifact_access_url(artifact)
    assert result["mode"] == "local_mirror"
    assert result["url"].endswith(f"/api/v1/artifacts/{artifact.id}/download")
    get_settings.cache_clear()
