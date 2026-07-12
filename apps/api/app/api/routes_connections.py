from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.compat import APIRouter, Depends, HTTPException
from app.core.auth import CurrentUser, get_current_user, require_any_role, require_role
from app.db.models import AuditLog
from app.db.session import get_db
from app.schemas import ConnectRequest
from app.services.connections import (
    connect_provider,
    disconnect_provider,
    list_connections,
    seed_connections,
    validate_provider_connection,
)

router = APIRouter(prefix="/api/v1/connections", tags=["connections"])


@router.get("")
def get_connections(db: Session = Depends(get_db), user: CurrentUser = Depends(get_current_user)):
    return list_connections(db)


@router.get("/{provider}")
def get_connection(provider: str, db: Session = Depends(get_db), user: CurrentUser = Depends(get_current_user)):
    try:
        seed_connections(db)
        return next(item for item in list_connections(db) if item["provider"] == provider)
    except StopIteration as exc:
        raise HTTPException(status_code=404, detail="provider not found") from exc


@router.post("/{provider}/connect")
def connect(provider: str, payload: ConnectRequest, db: Session = Depends(get_db), user: CurrentUser = Depends(require_role("admin"))):
    try:
        return connect_provider(db, provider, payload.credentials)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/{provider}/test")
def test(provider: str, db: Session = Depends(get_db), user: CurrentUser = Depends(require_role("admin"))):
    try:
        return validate_provider_connection(db, provider)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/{provider}/disconnect")
def disconnect(provider: str, db: Session = Depends(get_db), user: CurrentUser = Depends(require_role("admin"))):
    try:
        return disconnect_provider(db, provider)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/{provider}/audit")
def audit(provider: str, db: Session = Depends(get_db), user: CurrentUser = Depends(require_any_role("admin", "risk_reviewer"))):
    seed_connections(db)
    connection = next((item for item in list_connections(db) if item["provider"] == provider), None)
    if not connection:
        raise HTTPException(status_code=404, detail="provider not found")
    rows = db.scalars(
        select(AuditLog)
        .where(AuditLog.target_type == "external_connection")
        .order_by(AuditLog.created_at.desc())
        .limit(100)
    ).all()
    logs = [row for row in rows if row.payload.get("provider") == provider or row.target_id == connection["id"]]
    return {"provider": provider, "connection": connection, "logs": logs}


@router.get("/{provider}/logs")
def logs(provider: str, db: Session = Depends(get_db), user: CurrentUser = Depends(require_any_role("admin", "risk_reviewer"))):
    return audit(provider, db, user)
