from __future__ import annotations

import os
from contextlib import contextmanager
from typing import Any

import httpx

try:
    from fastapi import FastAPI, HTTPException, Request
except ModuleNotFoundError:  # pragma: no cover - local gate may not install service deps
    Request = Any

    class HTTPException(Exception):
        def __init__(self, status_code: int, detail: str):
            self.status_code = status_code
            self.detail = detail
            super().__init__(detail)

    class FastAPI:
        def __init__(self, *args: Any, **kwargs: Any):
            return None

        def on_event(self, _event: str):
            def decorator(func):
                return func

            return decorator

        def get(self, _path: str):
            def decorator(func):
                return func

            return decorator

try:
    from opentelemetry import trace
except ModuleNotFoundError:  # pragma: no cover - local gate may not install service deps
    class _NoopSpan:
        def set_attribute(self, _key: str, _value: Any) -> None:
            return None

    class _NoopTracer:
        @contextmanager
        def start_as_current_span(self, _name: str):
            yield _NoopSpan()

    class _NoopTrace:
        def get_tracer(self, _name: str):
            return _NoopTracer()

    trace = _NoopTrace()


API_BASE_URL = os.getenv("API_BASE_URL", "http://localhost:8000").rstrip("/")
REQUEST_TIMEOUT_SECONDS = float(os.getenv("OPENBB_BACKEND_REQUEST_TIMEOUT_SECONDS", "5"))
OPENBB_INTERNAL_TOKEN = (os.getenv("OPENBB_INTERNAL_TOKEN") or os.getenv("QTO_API_TOKEN", "")).strip()
WIDGETS = [
    {"id": "strategy-registry", "name": "Strategy Registry"},
    {"id": "backtest-summary", "name": "Backtest Summary"},
    {"id": "factor-library", "name": "Factor Library"},
    {"id": "risk-review", "name": "Risk Review"},
    {"id": "research-progress", "name": "Research Progress"},
]
WIDGET_IDS = {widget["id"] for widget in WIDGETS}

app = FastAPI(title="Quant Team OS OpenBB Backend", version="0.3.0")
tracer = trace.get_tracer("quant-team-os.openbb-backend")
_otel_configured = False


def configure_otel() -> str:
    global _otel_configured
    endpoint = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT")
    if not endpoint:
        return "disabled"
    if _otel_configured:
        return "configured"
    try:
        from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor

        service_name = os.getenv("OTEL_SERVICE_NAME", "quant-team-os-openbb-backend")
        provider = TracerProvider(resource=Resource.create({"service.name": service_name}))
        provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter(endpoint=endpoint)))
        trace.set_tracer_provider(provider)
        _otel_configured = True
        return "configured"
    except Exception:
        return "failed"


@app.on_event("startup")
async def startup() -> None:
    configure_otel()


@app.get("/healthz")
def healthz() -> dict[str, str]:
    return {"service": "openbb-backend", "status": "ok", "otel": configure_otel()}


@app.get("/widgets.json")
async def widgets_json(request: Request = None) -> dict[str, Any]:
    endpoint = _audited_manifest_endpoint()
    auth_header = request.headers.get("authorization") if request is not None else None
    headers = await _api_headers(auth_header)
    with tracer.start_as_current_span("openbb.widgets_manifest_request") as span:
        span.set_attribute("qto.mode", "read_only")
        span.set_attribute("qto.audit_endpoint", endpoint)
        try:
            async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT_SECONDS) as client:
                response = await client.get(endpoint, headers=headers)
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise HTTPException(status_code=exc.response.status_code, detail=exc.response.text) from exc
        except httpx.HTTPError as exc:
            raise HTTPException(status_code=502, detail=f"FastAPI widget manifest endpoint unavailable: {exc}") from exc
    payload = response.json()
    return {
        **payload,
        "mode": "read_only",
        "audit_required": True,
        "audited_endpoint": endpoint,
    }


@app.get("/widgets/{widget_id}")
async def widget(widget_id: str, request: Request = None) -> dict[str, Any]:
    if widget_id not in WIDGET_IDS:
        raise HTTPException(status_code=404, detail="OpenBB widget not found")

    endpoint = _audited_endpoint(widget_id)
    auth_header = request.headers.get("authorization") if request is not None else None
    headers = await _api_headers(auth_header)
    with tracer.start_as_current_span("openbb.widget_request") as span:
        span.set_attribute("qto.widget_id", widget_id)
        span.set_attribute("qto.mode", "read_only")
        span.set_attribute("qto.audit_endpoint", endpoint)
        try:
            async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT_SECONDS) as client:
                response = await client.get(endpoint, headers=headers)
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise HTTPException(status_code=exc.response.status_code, detail=exc.response.text) from exc
        except httpx.HTTPError as exc:
            raise HTTPException(status_code=502, detail=f"FastAPI widget endpoint unavailable: {exc}") from exc

    payload = response.json()
    return {
        **payload,
        "widget_id": widget_id,
        "mode": "read_only",
        "audit_required": True,
        "audited_endpoint": endpoint,
    }


def _audited_endpoint(widget_id: str) -> str:
    return f"{API_BASE_URL}/api/v1/ui/openbb/widgets/{widget_id}"


def _audited_manifest_endpoint() -> str:
    return f"{API_BASE_URL}/api/v1/ui/openbb/widgets.json"


async def _api_headers(auth_header: str | None = None) -> dict[str, str]:
    if auth_header:
        return {"Authorization": auth_header}
    static_token = os.getenv("QTO_API_TOKEN")
    if static_token:
        return {"Authorization": f"Bearer {static_token}"}
    token = await _service_account_token()
    return {"Authorization": f"Bearer {token}"} if token else {}


async def _service_account_token() -> str | None:
    if not OPENBB_INTERNAL_TOKEN:
        return None
    async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT_SECONDS) as client:
        response = await client.post(f"{API_BASE_URL}/api/v1/internal/openbb/service-token", headers={"X-QTO-Internal-Token": OPENBB_INTERNAL_TOKEN})
    response.raise_for_status()
    token = response.json().get("access_token")
    return str(token) if token else None


def _widget_contract(widget: dict[str, str]) -> dict[str, str | bool]:
    return {**widget, "endpoint": f"/widgets/{widget['id']}", "mode": "read_only", "audit_required": True}
