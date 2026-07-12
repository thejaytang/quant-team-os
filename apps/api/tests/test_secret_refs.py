import json

import pytest

from app.adapters.base import AdapterRunner, ToolContext
from app.adapters.stubs import default_registry
from app.core.config import get_settings
from app.core.redaction import contains_secret, mask_secret, redact_secrets
from app.db.models import AuditLog, ExternalConnection, PolicyDecision, ToolCall
from app.services.connections import connect_provider, disconnect_provider
from app.services.infisical import (
    _LOCAL_SECRET_STORE,
    InfisicalClient,
    InfisicalError,
    get_infisical_client,
    validate_infisical_runtime_settings,
)


@pytest.fixture(autouse=True)
def reset_infisical_state():
    get_settings.cache_clear()
    _LOCAL_SECRET_STORE.clear()
    yield
    get_settings.cache_clear()
    _LOCAL_SECRET_STORE.clear()


def _configure_infisical(
    monkeypatch,
    *,
    app_env: str = "development",
    project_id: str = "",
    client_id: str = "",
    client_secret: str = "",
    allow_local_secret_fallback: str = "true",
) -> None:
    monkeypatch.setenv("APP_ENV", app_env)
    monkeypatch.setenv("INFISICAL_API_URL", "http://infisical.test")
    monkeypatch.setenv("INFISICAL_PROJECT_ID", project_id)
    monkeypatch.setenv("INFISICAL_MACHINE_IDENTITY_CLIENT_ID", client_id)
    monkeypatch.setenv("INFISICAL_MACHINE_IDENTITY_CLIENT_SECRET", client_secret)
    monkeypatch.setenv("ALLOW_LOCAL_SECRET_FALLBACK", allow_local_secret_fallback)
    get_settings.cache_clear()


class FakeResponse:
    def __init__(self, payload=None, status_code: int = 200) -> None:
        self._payload = payload or {}
        self.status_code = status_code

    def json(self):
        return self._payload

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


class FakeInfisicalHttpClient:
    def __init__(self) -> None:
        self.secrets = {}
        self.calls = []

    def post(self, url: str, **kwargs):
        self.calls.append(("post", url, kwargs))
        if url.endswith("/api/v1/auth/universal-auth/login"):
            return FakeResponse({"accessToken": "token"})
        secret_key = self._secret_key(url, kwargs["json"])
        self.secrets[secret_key] = kwargs["json"]["secretValue"]
        return FakeResponse({"secret": {"version": "remote-v1"}})

    def patch(self, url: str, **kwargs):
        self.calls.append(("patch", url, kwargs))
        secret_key = self._secret_key(url, kwargs["json"])
        self.secrets[secret_key] = kwargs["json"]["secretValue"]
        return FakeResponse({"secret": {"version": "remote-v2"}})

    def get(self, url: str, **kwargs):
        self.calls.append(("get", url, kwargs))
        secret_key = self._secret_key(url, kwargs["params"])
        return FakeResponse({"secret": {"secretValue": self.secrets[secret_key], "version": "remote-v1"}})

    def delete(self, url: str, **kwargs):
        self.calls.append(("delete", url, kwargs))
        secret_key = self._secret_key(url, kwargs["params"])
        self.secrets.pop(secret_key, None)
        return FakeResponse({})

    def _secret_key(self, url: str, selector: dict[str, str]):
        secret_name = url.rsplit("/", 1)[1]
        return (selector["workspaceId"], selector["environment"], selector["secretPath"], secret_name)


class FailingHttpClient:
    def post(self, url: str, **kwargs):
        raise RuntimeError("network down")


def test_secret_masking():
    assert mask_secret("sk-testsecret1234") == "sk--****1234"


def test_secret_detection_covers_common_secret_keys_without_flagging_masked_values():
    raw = {"client_secret": "client-secret-value", "nested": {"access_token": "token-value"}}
    redacted = redact_secrets(raw)

    assert contains_secret(raw) is True
    assert contains_secret(redacted) is False
    assert "client-secret-value" not in str(redacted)
    assert "token-value" not in str(redacted)


def test_connection_uses_infisical_ref_and_removes_secret(db, monkeypatch):
    _configure_infisical(monkeypatch)
    public = connect_provider(db, "openai", {"api_key": "sk-testsecret1234", "model": "gpt-test"})
    db.commit()
    assert "sk-testsecret1234" not in str(public)
    assert public["metadata"]["masked_credentials"]["api_key"].endswith("1234")

    connection = db.query(ExternalConnection).filter_by(provider="openai").one()
    assert connection.infisical_secret_path
    assert connection.secret_version
    assert "sk-testsecret1234" not in str(connection.meta)
    raw = get_infisical_client().read_secret(connection.infisical_secret_path)
    assert raw["api_key"] == "sk-testsecret1234"

    disconnected = disconnect_provider(db, "openai")
    db.commit()
    connection = db.query(ExternalConnection).filter_by(provider="openai").one()
    assert disconnected["status"] == "disconnected"
    assert connection.infisical_secret_path is None
    assert connection.secret_version is None


def test_tool_gateway_fetches_infisical_secret_only_after_policy(db, monkeypatch):
    _configure_infisical(monkeypatch)
    connect_provider(db, "openai", {"api_key": "sk-testsecret1234", "model": "gpt-test"})

    result = AdapterRunner(default_registry()).run(
        db,
        "openai",
        {"prompt": "research momentum"},
        ToolContext(actor="ResearchAgent", agent_run_id="wf-secret"),
    )
    db.commit()

    assert result.ok is True
    assert result.output["credential_available"] is True
    assert "sk-testsecret1234" not in str(result.output)

    tool_call = db.query(ToolCall).filter_by(adapter_name="openai", agent_run_id="wf-secret").one()
    assert "sk-testsecret1234" not in str(tool_call.input_payload)
    assert "sk-testsecret1234" not in str(tool_call.output_payload)

    decisions = db.query(PolicyDecision).filter(PolicyDecision.workflow_id == "wf-secret").all()
    assert {decision.policy_package for decision in decisions} == {"agent", "connector"}
    assert "sk-testsecret1234" not in str([decision.input_payload for decision in decisions])

    finished = next(
        row
        for row in db.query(AuditLog).filter_by(action="tool_call.finished").all()
        if row.payload.get("observability", {}).get("workflow_id") == "wf-secret"
    )
    assert finished.payload["observability"]["infisical_ref_used"] is True
    assert "sk-testsecret1234" not in str(finished.payload)


def test_tool_gateway_rejects_testing_connection_except_connection_test(db, monkeypatch):
    _configure_infisical(monkeypatch)
    connect_provider(db, "openai", {"api_key": "sk-testsecret1234", "model": "gpt-test"})
    connection = db.query(ExternalConnection).filter_by(provider="openai").one()
    connection.status = "testing"
    db.flush()

    with pytest.raises(Exception, match="connector is not connected"):
        AdapterRunner(default_registry()).run(
            db,
            "openai",
            {"prompt": "research momentum"},
            ToolContext(actor="ResearchAgent", agent_run_id="wf-testing-deny"),
        )

    result = AdapterRunner(default_registry()).run(
        db,
        "openai",
        {"connection_test": True, "required_fields": ["api_key"]},
        ToolContext(actor="ConnectionTestAgent", agent_run_id="wf-testing-allow", connection_id=connection.id),
    )

    assert result.ok is True
    assert result.output["credential_available"] is True


def test_secret_lifecycle_never_persists_raw_secret_in_db_or_audit(db, monkeypatch):
    raw_secret = "sk-full-lifecycle-secret1234"
    _configure_infisical(monkeypatch)
    public = connect_provider(db, "openai", {"api_key": raw_secret, "model": "gpt-test"})
    AdapterRunner(default_registry()).run(
        db,
        "openai",
        {"prompt": "research momentum"},
        ToolContext(actor="ResearchAgent", agent_run_id="wf-secret-sweep"),
    )
    disconnected = disconnect_provider(db, "openai")
    db.commit()

    connection = db.query(ExternalConnection).filter_by(provider="openai").one()
    audit_logs = db.query(AuditLog).all()

    assert raw_secret not in str(public)
    assert raw_secret not in str(disconnected)
    assert raw_secret not in str(connection.__dict__)
    assert raw_secret not in str([(row.action, row.payload) for row in audit_logs])


def test_unconfigured_infisical_uses_local_fallback(monkeypatch):
    _configure_infisical(monkeypatch)
    client = InfisicalClient()

    ref = client.write_connection_secret("openai", {"api_key": "sk-local"})

    assert ref.path == "/quant-team-os/development/connections/openai"
    assert client.read_secret(ref.path) == {"api_key": "sk-local"}
    client.revoke_secret(ref.path)
    assert client.read_secret(ref.path) == {}


def test_production_unconfigured_infisical_raises(monkeypatch):
    _configure_infisical(monkeypatch, app_env="production")

    with pytest.raises(InfisicalError, match="machine identity is not configured"):
        InfisicalClient().write_connection_secret("openai", {"api_key": "sk-prod"})


def test_disabled_local_secret_fallback_raises(monkeypatch):
    _configure_infisical(monkeypatch, allow_local_secret_fallback="false")

    with pytest.raises(InfisicalError, match="machine identity is not configured"):
        InfisicalClient().write_connection_secret("openai", {"api_key": "sk-compose"})


def test_disabled_local_secret_fallback_requires_startup_identity(monkeypatch):
    _configure_infisical(monkeypatch, allow_local_secret_fallback="false")

    with pytest.raises(InfisicalError, match="INFISICAL_PROJECT_ID"):
        validate_infisical_runtime_settings()


def test_development_infisical_http_failure_falls_back_to_local(monkeypatch):
    _configure_infisical(monkeypatch, project_id="project", client_id="client", client_secret="secret")
    client = InfisicalClient(http_client=FailingHttpClient())

    ref = client.write_connection_secret("openai", {"api_key": "sk-fallback"})

    assert client.read_secret(ref.path) == {"api_key": "sk-fallback"}


def test_fake_httpx_client_writes_reads_and_revokes_remote_path(monkeypatch):
    _configure_infisical(monkeypatch, project_id="project", client_id="client", client_secret="secret")
    http_client = FakeInfisicalHttpClient()
    client = InfisicalClient(http_client=http_client)

    ref = client.write_connection_secret("openai", {"api_key": "sk-remote", "model": "gpt-test"})

    assert ref.path == "/quant-team-os/development/connections/openai"
    assert ref.version == "remote-v1"
    assert client.read_secret(ref.path) == {"api_key": "sk-remote", "model": "gpt-test"}
    client.revoke_secret(ref.path)
    assert http_client.secrets == {}
    assert json.loads(http_client.calls[1][2]["json"]["secretValue"]) == {
        "api_key": "sk-remote",
        "model": "gpt-test",
    }
    assert [call[0] for call in http_client.calls] == ["post", "post", "post", "get", "post", "delete"]
