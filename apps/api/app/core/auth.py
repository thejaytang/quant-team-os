from __future__ import annotations

import threading
import time
from collections.abc import Callable
from dataclasses import dataclass

import httpx

from app.api.compat import Depends, HTTPException
from app.core.config import get_settings

try:
    from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
except ModuleNotFoundError:  # pragma: no cover
    HTTPAuthorizationCredentials = None  # type: ignore
    HTTPBearer = None  # type: ignore

try:
    from jose import jwt
except ModuleNotFoundError:  # pragma: no cover
    jwt = None  # type: ignore


@dataclass(frozen=True)
class CurrentUser:
    sub: str
    username: str
    roles: set[str]
    service_account: bool = False


bearer = HTTPBearer(auto_error=False) if HTTPBearer else None


def get_current_user(credentials=Depends(bearer)) -> CurrentUser:
    settings = get_settings()
    if credentials is None:
        if settings.app_env == "production" or not settings.allow_local_auth_fallback:
            raise HTTPException(status_code=401, detail="authentication required")
        return CurrentUser(
            sub="local-dev",
            username="local_user",
            roles={"admin", "approver", "researcher", "risk_reviewer", "viewer"},
        )
    if jwt is None:
        raise HTTPException(status_code=500, detail="JWT support is not installed")
    token = credentials.credentials
    keys = _jwks()
    last_error: Exception | None = None
    payload = None
    for issuer in _accepted_issuers(settings):
        try:
            payload = jwt.decode(
                token,
                keys,
                algorithms=["RS256"],
                audience=settings.keycloak_client_id,
                issuer=issuer,
            )
            break
        except Exception as exc:
            last_error = exc
    if payload is None:
        raise HTTPException(status_code=401, detail="invalid token") from last_error
    roles = set(payload.get("realm_access", {}).get("roles", []))
    return CurrentUser(
        sub=payload.get("sub", ""),
        username=payload.get("preferred_username") or payload.get("client_id") or payload.get("sub", ""),
        roles=roles,
        service_account="service_account" in roles,
    )


def _accepted_issuers(settings) -> list[str]:
    issuers = [f"{settings.keycloak_base_url}/realms/{settings.keycloak_realm}"]
    if settings.keycloak_internal_base_url:
        issuers.append(f"{settings.keycloak_internal_base_url.rstrip('/')}/realms/{settings.keycloak_realm}")
    return list(dict.fromkeys(issuers))


def require_role(role: str) -> Callable[[CurrentUser], CurrentUser]:
    def dependency(user: CurrentUser = Depends(get_current_user)) -> CurrentUser:
        if role not in user.roles:
            raise HTTPException(status_code=403, detail=f"{role} role required")
        if role == "approver" and user.service_account:
            raise HTTPException(status_code=403, detail="service account cannot approve")
        return user

    return dependency


def require_any_role(*roles: str) -> Callable[[CurrentUser], CurrentUser]:
    def dependency(user: CurrentUser = Depends(get_current_user)) -> CurrentUser:
        if not set(roles).intersection(user.roles):
            raise HTTPException(status_code=403, detail=f"one of {', '.join(roles)} roles required")
        return user

    return dependency


_JWKS_TTL_SECONDS = 300
_jwks_cache: dict[str, tuple[float, dict]] = {}
_jwks_lock = threading.Lock()


def _jwks() -> dict:
    settings = get_settings()
    url = settings.keycloak_jwks_url or f"{settings.keycloak_base_url}/realms/{settings.keycloak_realm}/protocol/openid-connect/certs"
    now = time.monotonic()
    cached = _jwks_cache.get(url)
    if cached and now - cached[0] < _JWKS_TTL_SECONDS:
        return cached[1]
    try:
        keys = httpx.get(url, timeout=2).json()
    except Exception as exc:
        if cached is not None:
            # Serve the last known good key set rather than failing auth outright
            # when the identity provider is briefly unreachable.
            return cached[1]
        raise HTTPException(status_code=503, detail="identity provider unreachable") from exc
    with _jwks_lock:
        _jwks_cache[url] = (now, keys)
    return keys


def clear_jwks_cache() -> None:
    """Drop cached JWKS keys (e.g. after key rotation or in tests)."""
    with _jwks_lock:
        _jwks_cache.clear()
