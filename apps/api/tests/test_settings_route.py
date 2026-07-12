import json

from app.api.routes_settings import runtime_settings
from app.core.config import get_settings


def test_runtime_settings_exposes_safe_non_secret_config(monkeypatch):
    monkeypatch.setenv("QUANTCONNECT_USER_ID", "qc-user-1")
    get_settings.cache_clear()
    try:
        payload = runtime_settings()
    finally:
        get_settings.cache_clear()

    assert payload["identity"]["keycloak_realm"] == "quant-team-os"
    assert payload["security_locks"]["allow_live_trading"] is False
    assert payload["security_locks"]["allow_mature_tool_fallback"] is True
    assert payload["connections"]["quantconnect_user_id_configured"] is True
    assert payload["secret_refs"]["openai_api_key_ref"] == "/quant-team-os/dev/connections/openai"

    assert "quantconnect_user_id" not in payload["connections"]
    serialized = json.dumps(payload)
    for forbidden in [
        "aws_access_key_id",
        "aws_secret_access_key",
        "infisical_machine_identity_client_secret",
    ]:
        assert forbidden not in serialized
