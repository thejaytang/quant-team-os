from __future__ import annotations

import logging
from contextlib import contextmanager
from typing import Any

from app.core.config import get_settings

logger = logging.getLogger("qto.observability")

_otel_configured = False


def configure_otel() -> str:
    global _otel_configured
    settings = get_settings()
    if not settings.otel_exporter_otlp_endpoint:
        return "disabled"
    if _otel_configured:
        return "configured"
    try:
        from opentelemetry import trace
        from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor

        provider = TracerProvider(resource=Resource.create({"service.name": settings.otel_service_name}))
        provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter(endpoint=settings.otel_exporter_otlp_endpoint)))
        trace.set_tracer_provider(provider)
        _otel_configured = True
        return "configured"
    except Exception:
        logger.warning("OTEL configuration failed; tracing degraded to disabled", exc_info=True)
        return "failed"


@contextmanager
def tool_observation(adapter_name: str, actor: str, workflow_id: str | None):
    meta = {"adapter": adapter_name, "actor": actor, "workflow_id": workflow_id, "otel": "disabled", "langfuse": "disabled"}
    try:
        from opentelemetry import trace

        tracer = trace.get_tracer("quant-team-os")
        with tracer.start_as_current_span(f"tool.{adapter_name}") as span:
            span.set_attribute("qto.actor", actor)
            if workflow_id:
                span.set_attribute("qto.workflow_id", workflow_id)
            meta["otel"] = "span"
            context = span.get_span_context()
            if getattr(context, "trace_id", 0):
                meta["trace_id"] = f"{context.trace_id:032x}"
            if getattr(context, "span_id", 0):
                meta["span_id"] = f"{context.span_id:016x}"
            yield meta
    except Exception:
        logger.debug("tool_observation span setup failed; continuing without tracing", exc_info=True)
        yield meta


def langfuse_metadata(adapter_name: str, payload: dict[str, Any], workflow_id: str | None) -> dict[str, Any]:
    if adapter_name not in {"openai", "rd_agent"}:
        return {"langfuse": "not_llm"}
    return {"langfuse": "metadata", "workflow_id": workflow_id, "input_keys": sorted(payload.keys())}
