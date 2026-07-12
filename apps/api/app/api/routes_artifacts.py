from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.compat import APIRouter, Depends, FileResponse, HTTPException
from app.core.config import get_settings
from app.db.models import Artifact
from app.db.session import get_db
from app.services.artifacts import artifact_access_url

router = APIRouter(prefix="/api/v1/artifacts", tags=["artifacts"])


@router.get("")
def list_artifacts(db: Session = Depends(get_db)):
    return db.scalars(select(Artifact).order_by(Artifact.created_at.desc())).all()


@router.get("/{artifact_id}")
def get_artifact(artifact_id: str, db: Session = Depends(get_db)):
    artifact = db.get(Artifact, artifact_id)
    if not artifact:
        raise HTTPException(status_code=404, detail="artifact not found")
    return artifact


@router.get("/{artifact_id}/presigned-url")
def get_artifact_presigned_url(artifact_id: str, db: Session = Depends(get_db)):
    artifact = db.get(Artifact, artifact_id)
    if not artifact:
        raise HTTPException(status_code=404, detail="artifact not found")
    return artifact_access_url(artifact)


@router.get("/{artifact_id}/download")
def download_artifact(artifact_id: str, db: Session = Depends(get_db)):
    artifact = db.get(Artifact, artifact_id)
    if not artifact:
        raise HTTPException(status_code=404, detail="artifact not found")
    root = Path(get_settings().artifact_root).resolve()
    target = (root / artifact.path).resolve()
    if root not in target.parents:
        raise HTTPException(status_code=400, detail="invalid artifact path")
    if not target.exists():
        raise HTTPException(status_code=404, detail="artifact file not found")
    return FileResponse(target, media_type=artifact.content_type, filename=target.name)
