from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any
from urllib.parse import quote
from uuid import uuid4

import httpx

from app.core.config import get_settings


@dataclass(frozen=True)
class SecretRef:
    path: str
    version: str


_LOCAL_SECRET_STORE: dict[str, tuple[str, dict[str, Any]]] = {}


class InfisicalError(RuntimeError):
    pass


class InfisicalClient:
    """Thin Infisical boundary.

    Local store is only a development fallback when machine identity is not ready.
    """

    def __init__(self, http_client: Any | None = None) -> None:
        self._http_client = http_client

    def write_connection_secret(self, provider: str, credentials: dict[str, Any]) -> SecretRef:
        settings = get_settings()
        if not self._is_configured(settings):
            return self._fallback_or_raise(
                settings,
                "Infisical machine identity is not configured",
                lambda: self._write_local(provider, credentials),
            )

        try:
            return self._write_remote(settings, provider, credentials)
        except Exception as exc:
            return self._fallback_or_raise(
                settings,
                f"Infisical write failed: {exc}",
                lambda: self._write_local(provider, credentials),
                exc,
            )

    def read_secret(self, path: str | None) -> dict[str, Any]:
        if not path:
            return {}
        settings = get_settings()
        if not self._is_configured(settings):
            return self._fallback_or_raise(
                settings,
                "Infisical machine identity is not configured",
                lambda: self._read_local(path),
            )

        try:
            return self._read_remote(settings, path)
        except Exception as exc:
            return self._fallback_or_raise(
                settings,
                f"Infisical read failed: {exc}",
                lambda: self._read_local(path),
                exc,
            )

    def revoke_secret(self, path: str | None) -> None:
        if not path:
            return
        settings = get_settings()
        if not self._is_configured(settings):
            self._fallback_or_raise(
                settings,
                "Infisical machine identity is not configured",
                lambda: self._revoke_local(path),
            )
            return

        try:
            self._revoke_remote(settings, path)
        except Exception as exc:
            self._fallback_or_raise(
                settings,
                f"Infisical revoke failed: {exc}",
                lambda: self._revoke_local(path),
                exc,
            )

    def _write_local(self, provider: str, credentials: dict[str, Any]) -> SecretRef:
        path = self._connection_path(provider)
        version = str(uuid4())
        _LOCAL_SECRET_STORE[path] = (version, dict(credentials))
        return SecretRef(path=path, version=version)

    def _read_local(self, path: str) -> dict[str, Any]:
        item = _LOCAL_SECRET_STORE.get(path)
        return dict(item[1]) if item else {}

    def _revoke_local(self, path: str) -> None:
        _LOCAL_SECRET_STORE.pop(path, None)

    def _write_remote(self, settings: Any, provider: str, credentials: dict[str, Any]) -> SecretRef:
        path = self._connection_path(provider)
        secret_path, secret_name = self._split_secret_path(path)
        secret_value = json.dumps(dict(credentials), sort_keys=True, separators=(",", ":"))
        payload = {
            **self._secret_selector(settings, secret_path),
            "secretValue": secret_value,
        }
        headers = self._auth_headers(settings)
        response = self._request("post", self._secret_url(settings, secret_name), headers=headers, json=payload)
        if getattr(response, "status_code", None) == 409:
            response = self._request("patch", self._secret_url(settings, secret_name), headers=headers, json=payload)
        response.raise_for_status()
        return SecretRef(path=path, version=self._extract_version(response.json()))

    def _read_remote(self, settings: Any, path: str) -> dict[str, Any]:
        secret_path, secret_name = self._split_secret_path(path)
        response = self._request(
            "get",
            self._secret_url(settings, secret_name),
            headers=self._auth_headers(settings),
            params=self._secret_selector(settings, secret_path),
        )
        response.raise_for_status()
        secret_value = self._extract_secret_value(response.json())
        if not secret_value:
            return {}
        try:
            parsed = json.loads(secret_value)
        except json.JSONDecodeError:
            return {"value": secret_value}
        return parsed if isinstance(parsed, dict) else {"value": parsed}

    def _revoke_remote(self, settings: Any, path: str) -> None:
        secret_path, secret_name = self._split_secret_path(path)
        response = self._request(
            "delete",
            self._secret_url(settings, secret_name),
            headers=self._auth_headers(settings),
            params=self._secret_selector(settings, secret_path),
        )
        response.raise_for_status()

    def _auth_headers(self, settings: Any) -> dict[str, str]:
        response = self._request(
            "post",
            f"{settings.infisical_api_url.rstrip('/')}/api/v1/auth/universal-auth/login",
            json={
                "clientId": settings.infisical_machine_identity_client_id,
                "clientSecret": settings.infisical_machine_identity_client_secret,
            },
        )
        response.raise_for_status()
        token = response.json().get("accessToken")
        if not token:
            raise InfisicalError("Infisical auth response did not include accessToken")
        return {"Authorization": f"Bearer {token}"}

    def _request(self, method: str, url: str, **kwargs: Any) -> httpx.Response:
        if self._http_client is not None:
            return getattr(self._http_client, method)(url, **kwargs)
        with httpx.Client(timeout=10.0) as client:
            return getattr(client, method)(url, **kwargs)

    def _fallback_or_raise(
        self,
        settings: Any,
        message: str,
        fallback: Any,
        exc: Exception | None = None,
    ) -> Any:
        if settings.app_env.lower() == "production" or not settings.allow_local_secret_fallback:
            raise InfisicalError(message) from exc
        return fallback()

    def _is_configured(self, settings: Any) -> bool:
        return bool(
            settings.infisical_project_id
            and settings.infisical_machine_identity_client_id
            and settings.infisical_machine_identity_client_secret
        )

    def _connection_path(self, provider: str) -> str:
        settings = get_settings()
        return f"/quant-team-os/{settings.app_env}/connections/{provider}"

    def _split_secret_path(self, path: str) -> tuple[str, str]:
        secret_path, secret_name = path.rstrip("/").rsplit("/", 1)
        return secret_path or "/", secret_name

    def _secret_url(self, settings: Any, secret_name: str) -> str:
        return f"{settings.infisical_api_url.rstrip('/')}/api/v3/secrets/raw/{quote(secret_name, safe='')}"

    def _secret_selector(self, settings: Any, secret_path: str) -> dict[str, str]:
        return {
            "workspaceId": settings.infisical_project_id,
            "environment": settings.app_env,
            "secretPath": secret_path,
            "type": "shared",
        }

    def _extract_version(self, payload: dict[str, Any]) -> str:
        secret = payload.get("secret") if isinstance(payload.get("secret"), dict) else {}
        version = (
            payload.get("version")
            or payload.get("secretVersion")
            or secret.get("version")
            or secret.get("secretVersion")
        )
        return str(version or uuid4())

    def _extract_secret_value(self, payload: dict[str, Any]) -> str:
        secret = payload.get("secret") if isinstance(payload.get("secret"), dict) else {}
        return str(payload.get("secretValue") or secret.get("secretValue") or "")


def get_infisical_client() -> InfisicalClient:
    return InfisicalClient()


def validate_infisical_runtime_settings() -> None:
    settings = get_settings()
    if settings.allow_local_secret_fallback:
        return
    missing = [
        name
        for name, value in {
            "INFISICAL_PROJECT_ID": settings.infisical_project_id,
            "INFISICAL_MACHINE_IDENTITY_CLIENT_ID": settings.infisical_machine_identity_client_id,
            "INFISICAL_MACHINE_IDENTITY_CLIENT_SECRET": settings.infisical_machine_identity_client_secret,
        }.items()
        if not value
    ]
    if missing:
        raise InfisicalError(f"Infisical machine identity is required when local secret fallback is disabled: {', '.join(missing)}")
