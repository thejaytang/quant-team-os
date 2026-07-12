from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.models import Artifact
from app.services.audit import write_audit_log


def _safe_path(root: Path, relative_path: str) -> Path:
    target = (root / relative_path).resolve()
    root_resolved = root.resolve()
    if root_resolved not in target.parents and target != root_resolved:
        raise ValueError("artifact path escapes ARTIFACT_ROOT")
    return target


def create_artifact(
    db: Session,
    artifact_type: str,
    owner_type: str,
    owner_id: str,
    relative_path: str,
    content: str | bytes,
    content_type: str,
    metadata: dict[str, Any] | None = None,
) -> Artifact:
    settings = get_settings()
    root = Path(settings.artifact_root).resolve()
    target = _safe_path(root, relative_path)
    raw = content.encode("utf-8") if isinstance(content, str) else content
    checksum = hashlib.sha256(raw).hexdigest()
    bucket = _bucket_for_artifact(settings, artifact_type, owner_type)
    storage = _store_minio(bucket, relative_path, raw, content_type) if settings.enable_minio_upload else {"storage_mode": "local_mirror"}
    local_mirror_written = _should_write_local_mirror(settings)
    if local_mirror_written:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(raw)
    artifact = Artifact(
        artifact_type=artifact_type,
        owner_type=owner_type,
        owner_id=owner_id,
        minio_bucket=bucket,
        object_key=relative_path,
        path=str(target.relative_to(root)),
        content_type=content_type,
        checksum=checksum,
        meta={**(metadata or {}), **storage, "local_mirror_written": local_mirror_written},
    )
    db.add(artifact)
    db.flush()
    write_audit_log(
        db,
        "artifact.created",
        "artifact",
        artifact.id,
        {"bucket": artifact.minio_bucket, "object_key": artifact.object_key, "path": artifact.path, "type": artifact_type, "storage_mode": artifact.meta.get("storage_mode")},
    )
    return artifact


def _should_write_local_mirror(settings) -> bool:
    return not (settings.enable_minio_upload and settings.app_env.lower() == "production")


def _bucket_for_artifact(settings, artifact_type: str, owner_type: str) -> str:
    normalized = f"{owner_type}:{artifact_type}".lower()
    if owner_type == "dataset" or "dataset" in normalized or "ohlcv" in normalized:
        return settings.s3_bucket_datasets
    if any(marker in normalized for marker in ("report", "tear_sheet", "memo")):
        return settings.s3_bucket_reports
    return settings.s3_bucket_artifacts


def artifact_access_url(artifact: Artifact) -> dict[str, Any]:
    if get_settings().enable_minio_upload:
        return _presigned_minio_url(artifact.minio_bucket, artifact.object_key)
    return {"mode": "local_mirror", "url": f"/api/v1/artifacts/{artifact.id}/download"}


def _store_minio(bucket: str, key: str, raw: bytes, content_type: str) -> dict[str, Any]:
    try:
        client = _s3_client()
        client.put_object(Bucket=bucket, Key=key, Body=raw, ContentType=content_type)
        return {"storage_mode": "minio"}
    except Exception as exc:
        raise RuntimeError(f"MinIO artifact upload failed: {exc}") from exc


def _presigned_minio_url(bucket: str, key: str) -> dict[str, Any]:
    try:
        client = _s3_client()
        url = client.generate_presigned_url("get_object", Params={"Bucket": bucket, "Key": key}, ExpiresIn=900)
        return {"mode": "minio", "url": url, "expires_in_seconds": 900}
    except Exception as exc:
        raise RuntimeError(f"MinIO presigned URL failed: {exc}") from exc


def _s3_client():
    import boto3

    settings = get_settings()
    return boto3.client(
        "s3",
        endpoint_url=settings.s3_endpoint_url,
        aws_access_key_id=settings.aws_access_key_id,
        aws_secret_access_key=settings.aws_secret_access_key,
    )
