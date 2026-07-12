import sys
import types

from app.adapters.base import AdapterRunner, ToolContext
from app.adapters.stubs import default_registry
from app.core.config import get_settings
from app.db.models import AuditLog
from app.services.observability import configure_otel, tool_observation


def test_configure_otel_is_disabled_without_endpoint(monkeypatch):
    monkeypatch.delenv("OTEL_EXPORTER_OTLP_ENDPOINT", raising=False)
    get_settings.cache_clear()
    try:
        assert configure_otel() == "disabled"
    finally:
        get_settings.cache_clear()


def test_tool_observation_records_trace_and_span_ids(monkeypatch):
    class FakeSpanContext:
        trace_id = 0x123
        span_id = 0x456

    class FakeSpan:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def set_attribute(self, key, value):
            return None

        def get_span_context(self):
            return FakeSpanContext()

    class FakeTracer:
        def start_as_current_span(self, name):
            return FakeSpan()

    fake_trace = types.SimpleNamespace(get_tracer=lambda name: FakeTracer())
    fake_opentelemetry = types.ModuleType("opentelemetry")
    fake_opentelemetry.trace = fake_trace
    monkeypatch.setitem(sys.modules, "opentelemetry", fake_opentelemetry)

    with tool_observation("qlib", "ResearchAgent", "wf-1") as meta:
        assert meta["otel"] == "span"
        assert meta["trace_id"] == "00000000000000000000000000000123"
        assert meta["span_id"] == "0000000000000456"


def test_tool_gateway_persists_otel_span_ids_in_audit_log(monkeypatch, db):
    class FakeSpanContext:
        trace_id = 0xABC
        span_id = 0xDEF

    class FakeSpan:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def set_attribute(self, key, value):
            return None

        def get_span_context(self):
            return FakeSpanContext()

    class FakeTracer:
        def start_as_current_span(self, name):
            return FakeSpan()

    fake_trace = types.SimpleNamespace(get_tracer=lambda name: FakeTracer())
    fake_opentelemetry = types.ModuleType("opentelemetry")
    fake_opentelemetry.trace = fake_trace
    monkeypatch.setitem(sys.modules, "opentelemetry", fake_opentelemetry)

    result = AdapterRunner(default_registry()).run(
        db,
        "qlib",
        {"research": "momentum"},
        ToolContext(actor="ResearchAgent", agent_run_id="wf-otel"),
    )
    db.commit()

    assert result.ok is True
    log = db.query(AuditLog).filter_by(action="tool_call.finished").one()
    observability = log.payload["observability"]
    assert observability["otel"] == "span"
    assert observability["trace_id"] == "00000000000000000000000000000abc"
    assert observability["span_id"] == "0000000000000def"
