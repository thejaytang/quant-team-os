import asyncio
import importlib.util
from pathlib import Path

import pytest


def load_openbb_backend():
    path = Path(__file__).resolve().parents[2] / "openbb-backend" / "app.py"
    spec = importlib.util.spec_from_file_location("openbb_backend_app", path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


def test_openbb_backend_widgets_point_to_fastapi_audited_endpoint(monkeypatch):
    monkeypatch.setenv("API_BASE_URL", "http://api:8000")
    module = load_openbb_backend()

    widget = module._widget_contract({"id": "strategy-registry", "name": "Strategy Registry"})

    assert widget["mode"] == "read_only"
    assert widget["audit_required"] is True
    assert widget["endpoint"] == "/widgets/strategy-registry"


def test_openbb_backend_widgets_json_calls_fastapi_audited_manifest(monkeypatch):
    monkeypatch.setenv("API_BASE_URL", "http://api:8000")
    module = load_openbb_backend()
    captured = {}

    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {"widgets": [{"id": "strategy-registry", "mode": "read_only", "audit_required": True}]}

    class FakeAsyncClient:
        def __init__(self, timeout):
            captured["timeout"] = timeout

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        async def get(self, url, headers=None):
            captured["url"] = url
            captured["headers"] = headers
            return FakeResponse()

    monkeypatch.setattr(module.httpx, "AsyncClient", FakeAsyncClient)
    request = type("FakeRequest", (), {"headers": {"authorization": "Bearer kc-token"}})()

    result = asyncio.run(module.widgets_json(request))

    assert captured["url"] == "http://api:8000/api/v1/ui/openbb/widgets.json"
    assert captured["headers"] == {"Authorization": "Bearer kc-token"}
    assert result["mode"] == "read_only"
    assert result["audit_required"] is True
    assert result["audited_endpoint"] == captured["url"]
    assert result["widgets"][0]["audit_required"] is True


def test_openbb_backend_uses_service_account_when_request_has_no_token(monkeypatch):
    monkeypatch.setenv("API_BASE_URL", "http://api:8000")
    monkeypatch.setenv("OPENBB_INTERNAL_TOKEN", "internal-token")
    module = load_openbb_backend()
    calls = []

    class FakeResponse:
        def __init__(self, payload):
            self._payload = payload

        def raise_for_status(self):
            return None

        def json(self):
            return self._payload

    class FakeAsyncClient:
        def __init__(self, timeout):
            return None

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        async def post(self, url, data=None, json=None, headers=None):
            calls.append({"method": "POST", "url": url, "data": data, "json": json, "headers": headers})
            return FakeResponse({"access_token": "service-token"})

        async def get(self, url, headers=None, params=None):
            calls.append({"method": "GET", "url": url, "headers": headers, "params": params})
            return FakeResponse({"widgets": []})

    monkeypatch.setattr(module.httpx, "AsyncClient", FakeAsyncClient)
    request = type("FakeRequest", (), {"headers": {}})()

    result = asyncio.run(module.widgets_json(request))

    assert result["audit_required"] is True
    assert calls[0] == {
        "method": "POST",
        "url": "http://api:8000/api/v1/internal/openbb/service-token",
        "data": None,
        "json": None,
        "headers": {"X-QTO-Internal-Token": "internal-token"},
    }
    assert calls[1] == {
        "method": "GET",
        "url": "http://api:8000/api/v1/ui/openbb/widgets.json",
        "headers": {"Authorization": "Bearer service-token"},
        "params": None,
    }


def test_openbb_backend_widget_proxy_calls_fastapi_audited_endpoint(monkeypatch):
    monkeypatch.setenv("API_BASE_URL", "http://api:8000")
    module = load_openbb_backend()
    captured = {}

    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {"data": [{"name": "demo"}], "observability": {"otel": "span"}}

    class FakeAsyncClient:
        def __init__(self, timeout):
            captured["timeout"] = timeout

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        async def get(self, url, headers=None):
            captured["url"] = url
            captured["headers"] = headers
            return FakeResponse()

    monkeypatch.setattr(module.httpx, "AsyncClient", FakeAsyncClient)
    request = type("FakeRequest", (), {"headers": {"authorization": "Bearer kc-token"}})()

    result = asyncio.run(module.widget("strategy-registry", request))

    assert captured["url"] == "http://api:8000/api/v1/ui/openbb/widgets/strategy-registry"
    assert captured["headers"] == {"Authorization": "Bearer kc-token"}
    assert result["mode"] == "read_only"
    assert result["audit_required"] is True
    assert result["audited_endpoint"] == captured["url"]
    assert result["data"] == [{"name": "demo"}]


def test_openbb_backend_rejects_unknown_widget(monkeypatch):
    monkeypatch.setenv("API_BASE_URL", "http://api:8000")
    module = load_openbb_backend()

    with pytest.raises(module.HTTPException, match="OpenBB widget not found"):
        asyncio.run(module.widget("unknown"))
