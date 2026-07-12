import types

import pytest

from app.core.config import get_settings
from app.db.models import AgentRun, AuditLog
from app.services.infisical import InfisicalClient
from app.services.langfuse_tracking import log_agent_run_to_langfuse


def test_log_agent_run_to_langfuse_redacts_payload(monkeypatch, db):
    monkeypatch.setenv("LANGFUSE_HOST", "http://langfuse:3000")
    get_settings.cache_clear()
    calls = []

    class FakeLangfuse:
        def __init__(self, host):
            calls.append(("init", host))

        def trace(self, **kwargs):
            calls.append(("trace", kwargs))
            return types.SimpleNamespace(id="trace-123")

    monkeypatch.setitem(__import__("sys").modules, "langfuse", types.SimpleNamespace(Langfuse=FakeLangfuse))
    run = AgentRun(
        task_type="research",
        status="completed",
        workflow_id="wf-1",
        input_payload={"api_key": "sk-test-secret-value", "symbol": "SPY"},
        output_payload={"answer": "ok", "token": "plain-token-value"},
    )
    db.add(run)
    db.flush()

    result = log_agent_run_to_langfuse(db, run, {"source": "test"})

    assert result == {"trace_id": "trace-123", "mode": "langfuse", "error": None}
    assert run.langfuse_trace_id == "trace-123"
    trace_payload = next(call[1] for call in calls if call[0] == "trace")
    assert trace_payload["input"]["api_key"] != "sk-test-secret-value"
    assert trace_payload["output"]["token"] != "plain-token-value"
    assert trace_payload["metadata"]["workflow_id"] == "wf-1"
    assert db.query(AuditLog).filter_by(action="langfuse.agent_trace_logged").count() == 1
    get_settings.cache_clear()


def test_log_agent_run_to_langfuse_uses_infisical_secret_refs(monkeypatch, db):
    monkeypatch.setenv("LANGFUSE_HOST", "http://langfuse:3000")
    get_settings.cache_clear()
    calls = []

    class FakeInfisical:
        def read_secret(self, path):
            if path.endswith("/public-key"):
                return {"value": "pk-test"}
            if path.endswith("/secret-key"):
                return {"secret_key": "sk-test"}
            return {}

    class FakeLangfuse:
        def __init__(self, **kwargs):
            calls.append(("init", kwargs))

        def trace(self, **kwargs):
            return types.SimpleNamespace(id="trace-456")

    monkeypatch.setattr("app.adapters.base.get_infisical_client", lambda: FakeInfisical())
    monkeypatch.setitem(__import__("sys").modules, "langfuse", types.SimpleNamespace(Langfuse=FakeLangfuse))
    run = AgentRun(task_type="research", status="completed", input_payload={}, output_payload={})
    db.add(run)
    db.flush()

    result = log_agent_run_to_langfuse(db, run, {"source": "test"})

    assert result["mode"] == "langfuse"
    assert calls[0] == ("init", {"host": "http://langfuse:3000", "public_key": "pk-test", "secret_key": "sk-test"})
    assert "sk-test" not in str(db.query(AuditLog).filter_by(action="langfuse.agent_trace_logged").one().payload)
    get_settings.cache_clear()


def test_log_agent_run_to_langfuse_flushes_sdk_client(monkeypatch, db):
    monkeypatch.setenv("LANGFUSE_HOST", "http://langfuse:3000")
    get_settings.cache_clear()
    calls = []

    class FakeLangfuse:
        def __init__(self, **_kwargs):
            return None

        def trace(self, **kwargs):
            calls.append(("trace", kwargs))
            return types.SimpleNamespace(id="trace-flush")

        def flush(self):
            calls.append(("flush", None))

    monkeypatch.setitem(__import__("sys").modules, "langfuse", types.SimpleNamespace(Langfuse=FakeLangfuse))
    run = AgentRun(task_type="research", status="completed", input_payload={}, output_payload={})
    db.add(run)
    db.flush()

    result = log_agent_run_to_langfuse(db, run, {"source": "test"})

    assert result["trace_id"] == "trace-flush"
    assert [call[0] for call in calls] == ["trace", "flush"]
    get_settings.cache_clear()


def test_log_agent_run_to_langfuse_tracks_required_trace_metadata(monkeypatch, db):
    monkeypatch.setenv("LANGFUSE_HOST", "http://langfuse:3000")
    monkeypatch.setenv("OPENAI_MODEL", "gpt-test")
    get_settings.cache_clear()
    calls = []

    class FakeLangfuse:
        def __init__(self, **_kwargs):
            return None

        def trace(self, **kwargs):
            calls.append(kwargs)
            return types.SimpleNamespace(id="trace-meta")

    monkeypatch.setitem(__import__("sys").modules, "langfuse", types.SimpleNamespace(Langfuse=FakeLangfuse))
    run = AgentRun(
        task_type="research",
        status="completed",
        workflow_id="wf-1",
        input_payload={"research_idea_id": "ri-1", "prompt": "use api_key=sk-testsecret1234"},
        output_payload={
            "tool_calls": [{"adapter": "openai"}],
            "usage": {"input": 10, "output": 20},
            "cost_usd": 0.12,
            "policy_denials": ["live trading is locked"],
            "artifacts": [{"artifact_id": "artifact-1"}],
        },
    )
    db.add(run)
    db.flush()

    result = log_agent_run_to_langfuse(db, run, {"agent_name": "ChiefAgent", "prompt_version": "research-plan-v1"})

    assert result["trace_id"] == "trace-meta"
    meta = calls[0]["metadata"]
    assert meta["agent_name"] == "ChiefAgent"
    assert meta["workflow_id"] == "wf-1"
    assert meta["research_idea_id"] == "ri-1"
    assert meta["model"] == "gpt-test"
    assert meta["token_usage"] == {"input": 10, "output": 20}
    assert meta["cost"] == 0.12
    assert meta["prompt_version"] == "research-plan-v1"
    assert meta["policy_denials"] == ["live trading is locked"]
    assert meta["artifact_ids"] == ["artifact-1"]
    assert "sk-testsecret1234" not in str(meta)
    get_settings.cache_clear()


def test_infisical_read_remote_accepts_raw_secret_value():
    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {"secret": {"secretValue": "plain-secret-value"}}

    class FakeHttp:
        def get(self, *args, **kwargs):
            return FakeResponse()

        def post(self, *args, **kwargs):
            return types.SimpleNamespace(raise_for_status=lambda: None, json=lambda: {"accessToken": "token"})

    settings = types.SimpleNamespace(
        infisical_api_url="http://infisical",
        infisical_project_id="project",
        infisical_machine_identity_client_id="client",
        infisical_machine_identity_client_secret="secret",
        app_env="dev",
    )

    assert InfisicalClient(FakeHttp())._read_remote(settings, "/x/raw") == {"value": "plain-secret-value"}


def test_log_agent_run_to_langfuse_local_fallback_redacts_metadata(monkeypatch, db):
    monkeypatch.delenv("LANGFUSE_HOST", raising=False)
    monkeypatch.delitem(__import__("sys").modules, "langfuse", raising=False)
    get_settings.cache_clear()
    run = AgentRun(
        task_type="research",
        status="failed",
        input_payload={"symbol": "SPY"},
        output_payload={"error": "api_key=secret-value"},
    )
    db.add(run)
    db.flush()

    result = log_agent_run_to_langfuse(db, run, {"api_token": "secret-token-value"})

    assert result["trace_id"] == f"local-{run.id}"
    assert result["mode"] == "local_mirror"
    assert run.langfuse_trace_id == result["trace_id"]
    log = db.query(AuditLog).filter_by(action="langfuse.agent_trace_logged").one()
    assert "secret-token-value" not in str(log.payload)
    get_settings.cache_clear()


def test_log_agent_run_to_langfuse_redacts_fallback_error(monkeypatch, db):
    get_settings.cache_clear()

    class FakeLangfuse:
        def __init__(self, **_kwargs):
            raise RuntimeError("api_key=sk-testsecret1234")

    monkeypatch.setitem(__import__("sys").modules, "langfuse", types.SimpleNamespace(Langfuse=FakeLangfuse))
    run = AgentRun(task_type="research", status="failed", input_payload={}, output_payload={})
    db.add(run)
    db.flush()

    result = log_agent_run_to_langfuse(db, run, {})

    assert "sk-testsecret1234" not in result["error"]
    log = db.query(AuditLog).filter_by(action="langfuse.agent_trace_logged").one()
    assert "sk-testsecret1234" not in str(log.payload)
    get_settings.cache_clear()


def test_log_agent_run_to_langfuse_strict_full_stack_raises(monkeypatch, db):
    monkeypatch.setenv("ALLOW_LOCAL_SECRET_FALLBACK", "false")
    get_settings.cache_clear()

    class FakeInfisical:
        def read_secret(self, path):
            if path.endswith("/public-key"):
                return {"value": "pk-test"}
            if path.endswith("/secret-key"):
                return {"secret_key": "sk-test"}
            return {}

    class FakeLangfuse:
        def __init__(self, **_kwargs):
            raise RuntimeError("langfuse offline")

    monkeypatch.setattr("app.adapters.base.get_infisical_client", lambda: FakeInfisical())
    monkeypatch.setitem(__import__("sys").modules, "langfuse", types.SimpleNamespace(Langfuse=FakeLangfuse))
    run = AgentRun(task_type="research", status="failed", input_payload={}, output_payload={})
    db.add(run)
    db.flush()

    with pytest.raises(RuntimeError, match="langfuse offline"):
        log_agent_run_to_langfuse(db, run, {})
    assert db.query(AuditLog).filter_by(action="langfuse.agent_trace_logged").count() == 0
    get_settings.cache_clear()
