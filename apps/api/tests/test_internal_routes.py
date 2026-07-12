import pytest

from app.api.routes_internal import openbb_service_token
from app.core.config import get_settings
from app.db.models import ToolCall
from app.services.infisical import _LOCAL_SECRET_STORE


def test_openbb_service_token_uses_tool_gateway_secret_ref(monkeypatch, db):
    monkeypatch.setenv("OPENBB_INTERNAL_TOKEN", "internal-token")
    monkeypatch.setenv("KEYCLOAK_INTERNAL_BASE_URL", "http://keycloak:8080")
    monkeypatch.setenv("OPENBB_KEYCLOAK_CLIENT_SECRET_REF", "/quant-team-os/dev/keycloak/openbb-backend-client-secret")
    get_settings.cache_clear()
    _LOCAL_SECRET_STORE["/quant-team-os/dev/keycloak/openbb-backend-client-secret"] = ("v1", {"client_secret": "service-secret"})
    calls = []

    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {"access_token": "service-token"}

    def fake_post(url, data=None, timeout=None):
        calls.append({"url": url, "data": data, "timeout": timeout})
        return FakeResponse()

    monkeypatch.setattr("httpx.post", fake_post)

    payload = openbb_service_token(x_qto_internal_token="internal-token", db=db)

    assert payload == {"access_token": "service-token", "token_type": "bearer"}
    assert calls == [
        {
            "url": "http://keycloak:8080/realms/quant-team-os/protocol/openid-connect/token",
            "data": {"grant_type": "client_credentials", "client_id": "openbb-backend", "client_secret": "service-secret"},
            "timeout": 5.0,
        }
    ]
    call = db.query(ToolCall).filter_by(adapter_name="keycloak_service_token").one()
    assert call.output_payload == {"adapter": "keycloak_service_token", "mode": "keycloak_service_account", "credential_available": True}
    assert "service-secret" not in str(call.__dict__)
    assert "service-token" not in str(call.__dict__)
    get_settings.cache_clear()
    _LOCAL_SECRET_STORE.clear()


def test_openbb_service_token_rejects_bad_internal_token(db):
    with pytest.raises(Exception, match="invalid internal token"):
        openbb_service_token(x_qto_internal_token="bad-token", db=db)
