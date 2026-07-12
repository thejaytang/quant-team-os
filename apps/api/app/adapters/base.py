from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal, Protocol

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.redaction import contains_secret, redact_secrets
from app.db.models import ExternalConnection, ToolCall
from app.services.audit import write_audit_log
from app.services.infisical import get_infisical_client
from app.services.observability import langfuse_metadata, tool_observation
from app.services.policy import evaluate_policy

RiskLevel = Literal["read_only", "research_write", "backtest_run", "paper_trade", "live_trade"]


@dataclass
class ToolContext:
    actor: str = "agent"
    agent_run_id: str | None = None
    connection_id: str | None = None


@dataclass
class ToolResult:
    ok: bool
    output: dict[str, Any] = field(default_factory=dict)
    error: str | None = None
    private_output: dict[str, Any] = field(default_factory=dict)


class PolicyDenied(PermissionError):
    pass


class ToolAdapter(Protocol):
    name: str
    risk_level: RiskLevel

    def validate_connection(self, db: Session, connection_id: str | None) -> ToolResult:
        ...

    def validate_input(self, payload: dict[str, Any]) -> None:
        ...

    def run(self, db: Session, payload: dict[str, Any], context: ToolContext) -> ToolResult:
        ...


class AdapterRegistry:
    def __init__(self) -> None:
        self._adapters: dict[str, ToolAdapter] = {}

    def register(self, adapter: ToolAdapter) -> None:
        self._adapters[adapter.name] = adapter

    def get(self, name: str) -> ToolAdapter:
        if name not in self._adapters:
            raise KeyError(f"unknown adapter: {name}")
        return self._adapters[name]


class ToolGateway:
    def __init__(self, registry: AdapterRegistry) -> None:
        self.registry = registry

    def run(self, db: Session, adapter_name: str, payload: dict[str, Any], context: ToolContext) -> ToolResult:
        adapter = self.registry.get(adapter_name)
        call = ToolCall(
            agent_run_id=context.agent_run_id,
            adapter_name=adapter.name,
            tool_name=adapter.name,
            risk_level=adapter.risk_level,
            input_payload=redact_secrets(payload),
            status="started",
        )
        db.add(call)
        db.flush()
        try:
            with tool_observation(adapter.name, context.actor, context.agent_run_id) as obs:
                policy_input = _tool_policy_input(db, adapter, payload, context)
                if adapter.risk_level == "live_trade":
                    live_decision = evaluate_policy(db, "trading_lock", "live_order", policy_input, actor=context.actor, workflow_id=policy_input.get("workflow_id"))
                    if not live_decision.allowed:
                        raise PolicyDenied("; ".join(live_decision.reasons))
                agent_decision = evaluate_policy(db, "agent", adapter.name, policy_input, actor=context.actor, workflow_id=policy_input.get("workflow_id"))
                if not agent_decision.allowed:
                    raise PolicyDenied("; ".join(agent_decision.reasons))
                connector_decision = evaluate_policy(db, "connector", adapter.name, policy_input, actor=context.actor, workflow_id=policy_input.get("workflow_id"))
                if not connector_decision.allowed:
                    raise PolicyDenied("; ".join(connector_decision.reasons))
                connection_result = adapter.validate_connection(db, context.connection_id)
                if not connection_result.ok:
                    raise RuntimeError(connection_result.error or "connection validation failed")
                runtime_payload, secret_ref_used = _runtime_payload(db, adapter, payload, context)
                adapter.validate_input(runtime_payload)
                result = adapter.run(db, runtime_payload, context)
                safe_output = redact_secrets(result.output)
                safe_error = str(redact_secrets(result.error)) if result.error else None
                call.status = "succeeded" if result.ok else "failed"
                call.output_payload = safe_output
                call.error = safe_error
                observation = {**obs, **langfuse_metadata(adapter.name, payload, context.agent_run_id), "infisical_ref_used": secret_ref_used}
            write_audit_log(db, "tool_call.finished", "tool_call", call.id, {"adapter": adapter.name, "ok": result.ok, "observability": observation})
            db.flush()
            return ToolResult(ok=result.ok, output=safe_output, error=safe_error, private_output=result.private_output)
        except Exception as exc:
            safe_error = str(redact_secrets(str(exc)))
            call.status = "failed"
            call.error = safe_error
            write_audit_log(db, "tool_call.failed", "tool_call", call.id, {"adapter": adapter.name, "error": safe_error})
            db.flush()
            if isinstance(exc, PolicyDenied):
                raise PolicyDenied(safe_error) from exc
            return ToolResult(ok=False, error=safe_error)


class AdapterRunner(ToolGateway):
    pass


def _tool_policy_input(db: Session, adapter: ToolAdapter, payload: dict[str, Any], context: ToolContext) -> dict[str, Any]:
    provider = getattr(adapter, "provider", None)
    status = "connected"
    if provider:
        stmt = select(ExternalConnection).where(ExternalConnection.provider == provider)
        if context.connection_id:
            stmt = select(ExternalConnection).where(ExternalConnection.id == context.connection_id)
        connection = db.scalar(stmt)
        status = connection.status if connection else "disconnected"
        if payload.get("connection_test") is True and status == "testing":
            status = "connected"
    return {
        "action": "live_order" if adapter.risk_level == "live_trade" else "tool_call",
        "agent": {"name": context.actor, "service_account": context.actor != "human"},
        "tool": {
            "name": adapter.name,
            "risk_level": adapter.risk_level,
            "provider": provider,
            "requested_permission": adapter.risk_level,
        },
        "connection": {"provider": provider, "status": status},
        "payload": redact_secrets(payload),
        "payload_meta": {
            "sensitive_value_present": contains_secret(payload),
            "ref_requested": _secret_ref_requested(payload),
        },
        "system": {
            "allow_live_trading": get_settings().allow_live_trading,
            "allow_agent_arbitrary_code_execution": get_settings().allow_agent_arbitrary_code_execution,
        },
        "workflow_id": context.agent_run_id,
    }


def _secret_ref_requested(payload: dict[str, Any]) -> bool:
    return bool(payload.get("infisical_secret_ref") or payload.get("infisical_secret_refs"))


def _adapter_connection(db: Session, adapter: ToolAdapter, context: ToolContext) -> ExternalConnection | None:
    provider = getattr(adapter, "provider", None)
    if not provider:
        return None
    stmt = select(ExternalConnection).where(ExternalConnection.provider == provider)
    if context.connection_id:
        stmt = select(ExternalConnection).where(ExternalConnection.id == context.connection_id)
    return db.scalar(stmt)


def _runtime_payload(db: Session, adapter: ToolAdapter, payload: dict[str, Any], context: ToolContext) -> tuple[dict[str, Any], bool]:
    merged = {key: value for key, value in payload.items() if key not in {"infisical_secret_ref", "infisical_secret_refs"}}
    secret_ref_used = False

    connection = _adapter_connection(db, adapter, context)
    if connection is not None:
        visible_fields = (connection.meta or {}).get("fields", {})
        if not isinstance(visible_fields, dict):
            visible_fields = {}
        secret_values = get_infisical_client().read_secret(connection.infisical_secret_path)
        merged = {**visible_fields, **secret_values, **merged}
        secret_ref_used = bool(secret_values)

    service_secret_ref = payload.get("infisical_secret_ref")
    if isinstance(service_secret_ref, str) and service_secret_ref:
        service_values = get_infisical_client().read_secret(service_secret_ref)
        merged = {**service_values, **merged}
        secret_ref_used = secret_ref_used or bool(service_values)

    service_secret_refs = payload.get("infisical_secret_refs")
    if isinstance(service_secret_refs, dict):
        for target_key, ref in service_secret_refs.items():
            if not isinstance(ref, str) or not ref:
                continue
            service_values = get_infisical_client().read_secret(ref)
            value = service_values.get(str(target_key)) or _first_secret_value(service_values)
            if value:
                merged[str(target_key)] = value
            secret_ref_used = secret_ref_used or bool(service_values)

    return merged, secret_ref_used


def _first_secret_value(values: dict[str, Any]) -> Any:
    for key in ("value", "secret", "client_secret", "public_key", "secret_key", "api_key", "key"):
        if values.get(key):
            return values[key]
    return None
