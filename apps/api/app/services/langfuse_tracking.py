from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.adapters.base import AdapterRunner, ToolContext
from app.adapters.stubs import default_registry
from app.core.config import get_settings
from app.core.redaction import redact_secrets
from app.db.models import AgentRun
from app.services.audit import write_audit_log


def log_agent_run_to_langfuse(db: Session, run: AgentRun, metadata: dict[str, Any] | None = None) -> dict[str, Any]:
    trace_metadata = _trace_metadata(run, metadata or {})
    payload = {
        "task_type": run.task_type,
        "status": run.status,
        "workflow_id": run.workflow_id,
        "input": redact_secrets(run.input_payload or {}),
        "output": redact_secrets(run.output_payload or {}),
        "metadata": trace_metadata,
    }
    try:
        settings = get_settings()
        result = AdapterRunner(default_registry()).run(
            db,
            "langfuse",
            {
                "host": settings.langfuse_host,
                "name": f"agent.{run.task_type}",
                "input": payload["input"],
                "output": payload["output"],
                "metadata": {**{key: value for key, value in payload.items() if key not in {"input", "output", "metadata"}}, **trace_metadata},
                "infisical_secret_refs": {
                    "public_key": settings.langfuse_public_key_ref,
                    "secret_key": settings.langfuse_secret_key_ref,
                },
            },
            ToolContext(actor="LangfuseService", agent_run_id=run.workflow_id or run.id),
        )
        if not result.ok:
            raise RuntimeError(result.error or "Langfuse trace failed")
        trace_id = result.output.get("trace_id") or f"langfuse-{run.id}"
        mode = str(result.output.get("mode") or "langfuse")
        error = None
    except Exception as exc:
        if _strict_langfuse_mode():
            raise
        trace_id = f"local-{run.id}"
        mode = "local_mirror"
        error = str(redact_secrets(str(exc)))

    run.langfuse_trace_id = trace_id
    write_audit_log(
        db,
        "langfuse.agent_trace_logged",
        "agent_run",
        run.id,
        {"trace_id": trace_id, "mode": mode, "error": error, "metadata_keys": sorted(trace_metadata.keys())},
    )
    db.flush()
    return {"trace_id": trace_id, "mode": mode, "error": error}


def _strict_langfuse_mode() -> bool:
    settings = get_settings()
    if settings.app_env.lower() == "production":
        return True
    return not settings.allow_local_secret_fallback and settings.require_langfuse_tracking


def _trace_metadata(run: AgentRun, metadata: dict[str, Any]) -> dict[str, Any]:
    source = {**(run.input_payload or {}), **(run.output_payload or {}), **metadata}
    settings = get_settings()
    standard = {
        "agent_name": source.get("agent_name") or "ChiefAgent",
        "workflow_id": run.workflow_id or source.get("workflow_id"),
        "research_idea_id": source.get("research_idea_id"),
        "strategy_id": source.get("strategy_id"),
        "tool_calls": _first_present(source, "tool_calls", "tools", "sequence"),
        "model": source.get("model") or settings.openai_model,
        "latency": _first_present(source, "latency", "latency_ms", "latency_seconds"),
        "token_usage": _first_present(source, "token_usage", "usage"),
        "cost": _first_present(source, "cost", "cost_usd", "estimated_cost_usd", "openai_cost_usd"),
        "policy_denials": source.get("policy_denials") or [],
        "artifact_ids": source.get("artifact_ids") or _artifact_ids(source.get("artifacts")),
        "prompt": source.get("prompt"),
        "prompt_version": source.get("prompt_version") or source.get("prompt_id") or source.get("prompt_name"),
    }
    compact = {key: value for key, value in standard.items() if value not in (None, "", [], {})}
    extras = {key: value for key, value in metadata.items() if key not in compact}
    safe_token_usage = compact.get("token_usage")
    redacted = redact_secrets({key: value for key, value in {**extras, **compact}.items() if key != "token_usage"})
    if safe_token_usage is not None:
        redacted["token_usage"] = redact_secrets(safe_token_usage)
    return redacted


def _first_present(payload: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        value = payload.get(key)
        if value not in (None, "", [], {}):
            return value
    return None


def _artifact_ids(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item.get("artifact_id")) for item in value if isinstance(item, dict) and item.get("artifact_id")]
