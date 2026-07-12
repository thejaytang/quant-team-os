from __future__ import annotations

from sqlalchemy.orm import Session

from app.adapters.base import AdapterRunner, ToolContext
from app.adapters.stubs import default_registry
from app.api.compat import APIRouter, Depends, HTTPException
from app.core.config import get_settings
from app.db.session import get_db

try:
    from fastapi import Header
except ModuleNotFoundError:  # pragma: no cover
    def Header(default=None, alias: str | None = None):  # type: ignore
        return default


router = APIRouter(prefix="/api/v1/internal", tags=["internal"])


@router.post("/openbb/service-token")
def openbb_service_token(
    x_qto_internal_token: str | None = Header(default=None, alias="X-QTO-Internal-Token"),
    db: Session = Depends(get_db),
):
    settings = get_settings()
    if not settings.openbb_internal_token or x_qto_internal_token != settings.openbb_internal_token:
        raise HTTPException(status_code=403, detail="invalid internal token")

    base_url = (settings.keycloak_internal_base_url or settings.keycloak_base_url).rstrip("/")
    result = AdapterRunner(default_registry()).run(
        db,
        "keycloak_service_token",
        {
            "token_url": f"{base_url}/realms/{settings.keycloak_realm}/protocol/openid-connect/token",
            "client_id": "openbb-backend",
            "infisical_secret_ref": settings.openbb_keycloak_client_secret_ref,
        },
        ToolContext(actor="openbb-backend"),
    )
    if not result.ok:
        raise HTTPException(status_code=502, detail=result.error or "Keycloak service token failed")
    token = result.private_output.get("access_token")
    if not token:
        raise HTTPException(status_code=502, detail="Keycloak service token missing")
    return {"access_token": token, "token_type": "bearer"}
