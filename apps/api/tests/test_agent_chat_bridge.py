import asyncio
import importlib.util
from pathlib import Path

APP_PATH = Path(__file__).resolve().parents[2] / "agent-chat" / "app.py"


def _load_agent_chat():
    spec = importlib.util.spec_from_file_location("agent_chat_app", APP_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader
    spec.loader.exec_module(module)
    return module


def test_chainlit_bridge_parses_workflow_command():
    app = _load_agent_chat()

    payload = app.command_payload("/workflow idea-123")

    assert payload == {"action": "start_research_workflow", "research_idea_id": "idea-123"}


def test_chainlit_bridge_renders_workflow_response():
    app = _load_agent_chat()

    text = app.render_response({"action": "start_research_workflow"}, {"workflow_id": "wf-1"})

    assert "wf-1" in text


def test_chainlit_bridge_parses_tool_call_command():
    app = _load_agent_chat()

    payload = app.command_payload("/tools")

    assert payload == {"action": "tool_calls"}


def test_chainlit_bridge_parses_approval_command_with_comment():
    app = _load_agent_chat()

    payload = app.command_payload("/approve apr-1 reviewed by human")

    assert payload == {
        "action": "resolve_approval",
        "approval_id": "apr-1",
        "resolution": "approve",
        "human_comment": "reviewed by human",
    }


def test_chainlit_bridge_rejects_slash_approval_without_comment():
    app = _load_agent_chat()

    payload = app.command_payload("/approve apr-1")

    assert payload == {"action": "approval_comment_required", "approval_id": "apr-1", "resolution": "approve"}
    assert "Human comment is required" in app.render_response(payload, {})


def test_chainlit_bridge_approval_endpoint_uses_approval_api():
    app = _load_agent_chat()

    assert app.approval_endpoint("apr-1", "approve") == "/api/v1/approvals/apr-1/approve"
    assert app.approval_endpoint("apr-1", "reject") == "/api/v1/approvals/apr-1/reject"
    assert app.approval_endpoint("apr-1", "request_changes") == "/api/v1/approvals/apr-1/request-changes"


def test_chainlit_bridge_builds_human_action_button_specs_for_pending_approval():
    app = _load_agent_chat()

    specs = app.approval_action_specs({"id": "approval-123", "status": "pending"})

    assert [spec["name"] for spec in specs] == ["approval_approve", "approval_reject", "approval_request_changes"]
    assert {spec["payload"]["approval_id"] for spec in specs} == {"approval-123"}
    assert {spec["payload"]["resolution"] for spec in specs} == {"approve", "reject", "request_changes"}


def test_chainlit_bridge_filters_approval_actions_from_backend_policy_fields():
    app = _load_agent_chat()

    approval = {
        "id": "approval-123",
        "status": "pending",
        "request_type": "unlock_live",
        "target_type": "strategy",
        "target_id": "strategy-1",
        "policy_lock_reason": "Live trading is locked by OPA",
        "allowed_actions": ["reject", "request-changes"],
    }
    specs = app.approval_action_specs(approval)
    text = app.render_approvals([approval])

    assert [spec["name"] for spec in specs] == ["approval_reject", "approval_request_changes"]
    assert "approval_approve" not in [spec["name"] for spec in specs]
    assert "Live trading is locked by OPA" in text
    assert "/approve approval-123" not in text
    assert "/reject approval-123 <comment>" in text
    assert "/request-changes approval-123 <comment>" in text


def test_chainlit_bridge_does_not_build_actions_for_resolved_approval():
    app = _load_agent_chat()

    assert app.approval_action_specs({"id": "approval-123", "status": "approved"}) == []


def test_chainlit_bridge_renders_tool_call_display():
    app = _load_agent_chat()

    text = app.render_response(
        {"action": "tool_calls"},
        [
            {
                "id": "tc-1",
                "adapter_name": "openai",
                "tool_name": "chat",
                "risk_level": "read_only",
                "status": "finished",
                "output_payload": {"ok": True},
            }
        ],
    )

    assert "Tool calls" in text
    assert "openai.chat" in text
    assert "read_only" in text


def test_chainlit_bridge_parses_and_renders_agent_steps():
    app = _load_agent_chat()

    steps = app.parse_sse_events("event: status\ndata: queued\n\nevent: output\ndata: {'ok': True}\n\n")
    text = app.render_response({"action": "chat"}, {"id": "run-1", "_agent_steps": steps})

    assert steps == [{"type": "status", "data": "queued"}, {"type": "output", "data": "{'ok': True}"}]
    assert "Agent run queued" in text
    assert "Agent steps" in text
    assert "`status` queued" in text


def test_chainlit_bridge_chat_fetches_agent_run_events(monkeypatch):
    app = _load_agent_chat()
    calls = []

    class FakeResponse:
        def __init__(self, payload=None, text=""):
            self._payload = payload
            self.text = text

        def raise_for_status(self):
            return None

        def json(self):
            return self._payload

    class FakeAsyncClient:
        def __init__(self, *args, **kwargs):
            return None

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, traceback):
            return None

        async def post(self, url, headers=None, json=None):
            calls.append({"method": "POST", "url": url, "headers": headers, "json": json})
            return FakeResponse({"id": "run-1", "status": "queued"})

        async def get(self, url, headers=None):
            calls.append({"method": "GET", "url": url, "headers": headers})
            return FakeResponse(text="event: status\ndata: queued\n\n")

    monkeypatch.setattr(app.httpx, "AsyncClient", FakeAsyncClient)

    result = asyncio.run(app.call_api({"action": "chat", "message": "hello"}, token="kc-token"))

    assert result["_agent_steps"] == [{"type": "status", "data": "queued"}]
    assert calls == [
        {
            "method": "POST",
            "url": f"{app.API_URL}/api/v1/agent-runs",
            "headers": {"Authorization": "Bearer kc-token"},
            "json": {"task_type": "chat", "input_payload": {"action": "chat", "message": "hello"}},
        },
        {
            "method": "GET",
            "url": f"{app.API_URL}/api/v1/agent-runs/run-1/events",
            "headers": {"Authorization": "Bearer kc-token"},
        },
    ]


def test_chainlit_bridge_resolve_approval_posts_to_approval_api(monkeypatch):
    app = _load_agent_chat()
    calls = []

    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {"id": "apr-1", "status": "approved"}

    class FakeAsyncClient:
        def __init__(self, *args, **kwargs):
            return None

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, traceback):
            return None

        async def post(self, url, headers=None, json=None):
            calls.append({"url": url, "headers": headers, "json": json})
            return FakeResponse()

    monkeypatch.setattr(app.httpx, "AsyncClient", FakeAsyncClient)

    result = asyncio.run(
        app.call_api(
            {
                "action": "resolve_approval",
                "approval_id": "apr-1",
                "resolution": "approve",
                "human_comment": "reviewed",
            }
        )
    )

    assert result == {"id": "apr-1", "status": "approved"}
    assert calls == [
        {
            "url": f"{app.API_URL}/api/v1/approvals/apr-1/approve",
            "headers": {},
            "json": {"human_comment": "reviewed"},
        }
    ]


def test_chainlit_bridge_forwards_oauth_token_to_api(monkeypatch):
    app = _load_agent_chat()
    calls = []

    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return []

    class FakeAsyncClient:
        def __init__(self, *args, **kwargs):
            return None

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, traceback):
            return None

        async def get(self, url, headers=None):
            calls.append({"url": url, "headers": headers})
            return FakeResponse()

    monkeypatch.setattr(app.httpx, "AsyncClient", FakeAsyncClient)

    result = asyncio.run(app.call_api({"action": "approvals"}, token="kc-token"))

    assert result == []
    assert calls == [{"url": f"{app.API_URL}/api/v1/approvals", "headers": {"Authorization": "Bearer kc-token"}}]


def test_chainlit_bridge_static_contract_does_not_mutate_strategy_card_directly():
    app_text = APP_PATH.read_text(encoding="utf-8")

    assert "AskUserMessage" in app_text
    assert "oauth_callback" in app_text
    assert "api_token" in app_text
    assert "render_agent_steps" in app_text
    assert "/api/v1/agent-runs/" in app_text
    assert "/events" in app_text
    assert "StrategyCard" not in app_text
    assert "/api/v1/strategies" not in app_text
