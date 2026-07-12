from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.redaction import mask_secret, redact_secrets
from app.db.models import ExternalConnection
from app.services.audit import write_audit_log
from app.services.infisical import get_infisical_client
from app.services.workflows import start_workflow

try:
    from app.adapters.base import AdapterRunner, ToolContext
    from app.adapters.stubs import default_registry
except Exception:  # pragma: no cover - optional in narrow import checks
    AdapterRunner = None  # type: ignore
    ToolContext = None  # type: ignore
    default_registry = None  # type: ignore


PROVIDERS: dict[str, dict[str, Any]] = {
    "openai": {
        "display_name": "OpenAI API",
        "permissions": ["read_only", "research_write"],
        "secret_fields": ["api_key"],
        "required_fields": ["api_key"],
        "optional_fields": ["model"],
        "open_ui_url": None,
        "permission_level": "research_write",
    },
    "massive": {
        "display_name": "Massive Market Data",
        "permissions": ["read_data"],
        "secret_fields": ["api_key"],
        "required_fields": ["api_key"],
        "open_ui_url": "https://www.massive.com",
        "permission_level": "market_data",
    },
    "quantconnect": {
        "display_name": "QuantConnect",
        "permissions": ["run_backtest", "paper_trade"],
        "secret_fields": ["api_token"],
        "required_fields": ["user_id", "api_token"],
        "open_ui_url": "https://www.quantconnect.com",
        "permission_level": "backtest_and_paper",
    },
    "openbb": {
        "display_name": "OpenBB Workspace",
        "permissions": ["read_data"],
        "secret_fields": [],
        "required_fields": ["url"],
        "permission_level": "read_only",
    },
    "mlflow": {
        "display_name": "MLflow",
        "permissions": ["research_write"],
        "secret_fields": [],
        "required_fields": ["tracking_uri"],
        "open_ui_url": "http://localhost:5000",
        "permission_level": "experiment_read_write",
    },
    "langfuse": {
        "display_name": "Langfuse",
        "permissions": ["trace_write"],
        "secret_fields": ["secret_key"],
        "required_fields": ["host", "public_key", "secret_key"],
        "permission_level": "trace_read_write",
    },
    "superset": {
        "display_name": "Superset",
        "permissions": ["analytics_read"],
        "secret_fields": [],
        "required_fields": ["url"],
        "open_ui_url": "http://localhost:8088",
        "permission_level": "read_only",
    },
    "grafana": {
        "display_name": "Grafana",
        "permissions": ["monitoring_read"],
        "secret_fields": [],
        "required_fields": ["url"],
        "open_ui_url": "http://localhost:3000",
        "permission_level": "read_only",
    },
    "temporal": {
        "display_name": "Temporal",
        "permissions": ["workflow_query"],
        "secret_fields": [],
        "required_fields": ["url"],
        "open_ui_url": "http://localhost:8233",
        "permission_level": "read_only",
    },
    "jupyterlab": {
        "display_name": "JupyterLab",
        "permissions": ["notebook_read"],
        "secret_fields": [],
        "required_fields": ["url"],
        "open_ui_url": "http://localhost:8888",
        "permission_level": "human_research",
    },
    "infisical": {
        "display_name": "Infisical",
        "permissions": ["secret_admin"],
        "secret_fields": [],
        "required_fields": ["url"],
        "permission_level": "admin_only",
    },
    "keycloak": {
        "display_name": "Keycloak",
        "permissions": ["identity_admin"],
        "secret_fields": [],
        "required_fields": ["url"],
        "open_ui_url": "http://localhost:8080",
        "permission_level": "admin_only",
    },
    "minio": {
        "display_name": "MinIO",
        "permissions": ["artifact_admin"],
        "secret_fields": [],
        "required_fields": ["url"],
        "open_ui_url": "http://localhost:9001",
        "permission_level": "admin_only",
    },
    "chainlit": {
        "display_name": "Chainlit",
        "permissions": ["agent_chat"],
        "secret_fields": [],
        "required_fields": ["url"],
        "open_ui_url": "http://localhost:8001",
        "permission_level": "human_action",
    },
    "ibkr": {
        "display_name": "IBKR via QuantConnect - Locked",
        "permissions": ["paper_trade", "live_trade_locked"],
        "secret_fields": [],
        "required_fields": [],
        "open_ui_url": "https://www.quantconnect.com/docs/v2/cloud-platform/live-trading/brokerages/interactive-brokers",
        "permission_level": "locked",
        "locked": True,
    },
}


def seed_connections(db: Session) -> None:
    for provider, spec in PROVIDERS.items():
        existing = db.scalar(select(ExternalConnection).where(ExternalConnection.provider == provider))
        if existing:
            existing.display_name = spec["display_name"]
            existing.permissions = spec["permissions"]
            existing.meta = {**(existing.meta or {}), **_default_meta(provider, spec)}
            if spec.get("locked"):
                existing.status = "locked"
            continue
        db.add(
            ExternalConnection(
                provider=provider,
                display_name=spec["display_name"],
                status="locked" if spec.get("locked") else "disconnected",
                permissions=spec["permissions"],
                meta=_default_meta(provider, spec),
            )
        )
    db.flush()


def _default_meta(provider: str, spec: dict[str, Any]) -> dict[str, Any]:
    meta = {
        "open_ui_url": _provider_open_ui_url(provider, spec),
        "permission_level": spec.get("permission_level", "read_only"),
        "credential_fields": _credential_fields(spec),
        "capabilities": _provider_capabilities(spec),
    }
    if provider == "ibkr":
        meta["message"] = "Live trading is locked by design in MVP."
    return meta


def _provider_capabilities(spec: dict[str, Any]) -> dict[str, Any]:
    permissions = set(spec.get("permissions", []))
    locked = bool(spec.get("locked")) or "live_trade_locked" in permissions
    return {
        "connectable": not bool(spec.get("locked")),
        "read_holdings": bool(spec.get("read_holdings")),
        "paper_trade": "paper_trade" in permissions,
        "live_trade": "locked" if locked else "live_trade" in permissions,
    }


def _credential_fields(spec: dict[str, Any]) -> list[dict[str, Any]]:
    required_fields = list(spec.get("required_fields", []))
    optional_fields = list(spec.get("optional_fields", []))
    secret_fields = set(spec.get("secret_fields", []))
    names: list[str] = []
    for field in [*required_fields, *optional_fields, *spec.get("secret_fields", [])]:
        if field not in names:
            names.append(field)
    return [
        {
            "name": field,
            "label": field.replace("_", " ").title(),
            "secret": field in secret_fields,
            "required": field in required_fields,
        }
        for field in names
    ]


def _allowed_credential_fields(spec: dict[str, Any]) -> set[str]:
    return set(spec.get("required_fields", [])) | set(spec.get("optional_fields", [])) | set(spec.get("secret_fields", []))


def _provider_open_ui_url(provider: str, spec: dict[str, Any]) -> str | None:
    settings = get_settings()
    urls = {
        "openbb": settings.openbb_workspace_url,
        "mlflow": settings.mlflow_ui_url,
        "langfuse": settings.langfuse_ui_url,
        "superset": settings.superset_url,
        "grafana": settings.grafana_url,
        "temporal": settings.temporal_ui_url,
        "jupyterlab": settings.jupyterlab_url,
        "infisical": settings.infisical_ui_url,
        "keycloak": settings.keycloak_base_url,
        "minio": settings.minio_console_url,
        "chainlit": settings.chainlit_url,
    }
    return urls.get(provider, spec.get("open_ui_url"))


def _get_connection(db: Session, provider: str) -> ExternalConnection:
    if provider not in PROVIDERS:
        raise ValueError(f"unknown provider: {provider}")
    seed_connections(db)
    connection = db.scalar(select(ExternalConnection).where(ExternalConnection.provider == provider))
    if connection is None:
        raise ValueError(f"missing provider: {provider}")
    return connection


def _masked(credentials: dict[str, Any], provider: str) -> dict[str, str]:
    secret_fields = set(PROVIDERS[provider].get("secret_fields", []))
    return {key: mask_secret(str(value)) for key, value in credentials.items() if key in secret_fields and value}


def public_connection(connection: ExternalConnection) -> dict[str, Any]:
    meta = dict(connection.meta or {})
    meta["secret_ref_present"] = bool(connection.infisical_secret_path)
    if connection.secret_version:
        meta["secret_version"] = connection.secret_version
    return {
        "id": connection.id,
        "provider": connection.provider,
        "display_name": connection.display_name,
        "status": connection.status,
        "permissions": connection.permissions,
        "metadata": meta,
        "last_checked_at": connection.last_checked_at.isoformat() if connection.last_checked_at else None,
        "last_error": connection.last_error,
        "created_at": connection.created_at.isoformat() if connection.created_at else None,
        "updated_at": connection.updated_at.isoformat() if connection.updated_at else None,
    }


def list_connections(db: Session) -> list[dict[str, Any]]:
    seed_connections(db)
    rows = db.scalars(select(ExternalConnection).order_by(ExternalConnection.provider)).all()
    return [public_connection(row) for row in rows]


def connect_provider(db: Session, provider: str, credentials: dict[str, Any]) -> dict[str, Any]:
    connection = _get_connection(db, provider)
    spec = PROVIDERS[provider]
    if provider == "ibkr":
        connection.status = "locked"
        connection.meta = {
            **_default_meta(provider, spec),
            "masked_credentials": {},
            "message": "Live trading is locked by design in MVP.",
        }
        connection.last_error = None
        write_audit_log(db, "connection.locked_config_saved", "external_connection", connection.id, {"provider": provider})
        db.flush()
        return public_connection(connection)

    credentials = {key: value for key, value in credentials.items() if value not in (None, "")}
    unknown = sorted(set(credentials) - _allowed_credential_fields(spec))
    if unknown:
        raise ValueError(f"unsupported credential fields for {provider}: {', '.join(unknown)}")
    missing = [field for field in spec.get("required_fields", []) if not credentials.get(field)]
    if missing:
        raise ValueError(f"missing required fields: {', '.join(missing)}")

    secret_fields = set(spec.get("secret_fields", []))
    secret_payload = {key: value for key, value in credentials.items() if key in secret_fields}
    visible_fields = {key: value for key, value in credentials.items() if key not in secret_fields}
    if secret_payload:
        ref = get_infisical_client().write_connection_secret(provider, secret_payload)
        connection.infisical_secret_path = ref.path
        connection.secret_version = ref.version

    connection.status = "testing"
    connection.meta = {
        **_default_meta(provider, spec),
        "masked_credentials": _masked(credentials, provider),
        "fields": visible_fields,
    }
    connection.last_error = None
    write_audit_log(db, "connection.connected", "external_connection", connection.id, {"provider": provider, "credentials": redact_secrets(credentials)})
    result = validate_provider_connection(db, provider)
    if result.get("status") == "testing":
        connection.status = "testing"
    db.flush()
    return public_connection(connection)


def validate_provider_connection(db: Session, provider: str) -> dict[str, Any]:
    spec = PROVIDERS[provider]
    connection = _get_connection(db, provider)
    connection.last_checked_at = datetime.now(UTC)
    if spec.get("locked"):
        connection.status = "locked"
        connection.last_error = None
        write_audit_log(db, "connection.test_locked", "external_connection", connection.id, {"provider": provider})
        db.flush()
        return {"ok": True, "status": "locked", "message": "Live trading is locked by design in MVP."}

    workflow = _start_connection_test_workflow(db, provider, connection)
    visible_fields = (connection.meta or {}).get("fields", {})
    visible_values = visible_fields if isinstance(visible_fields, dict) else {}
    secret_fields = set(spec.get("secret_fields", []))
    runtime_fields = _non_secret_runtime_fields(provider)
    missing = [
        field
        for field in spec.get("required_fields", [])
        if not visible_values.get(field) and not runtime_fields.get(field) and not (field in secret_fields and connection.infisical_secret_path)
    ]
    connection.meta = {**(connection.meta or {}), "last_test_workflow_id": workflow["workflow_id"]}
    if missing:
        connection.status = "error"
        connection.last_error = f"missing required fields: {', '.join(missing)}"
        write_audit_log(
            db,
            "connection.test_failed",
            "external_connection",
            connection.id,
            {"provider": provider, "missing": missing, "workflow_id": workflow["workflow_id"]},
        )
        db.flush()
        return {"ok": False, "status": "error", "error": connection.last_error, "workflow_id": workflow["workflow_id"]}

    if _can_run_local_connection_test(workflow):
        if _local_connection_test_succeeds(db, provider, connection, workflow["workflow_id"]):
            db.flush()
            return {"ok": True, "status": "connected", "workflow_id": workflow["workflow_id"]}
        db.flush()
        return {"ok": False, "status": "error", "error": connection.last_error, "workflow_id": workflow["workflow_id"]}

    if workflow.get("status") == "temporal_unavailable":
        connection.status = "testing"
        connection.last_error = "connection test workflow pending Temporal worker"
        write_audit_log(db, "connection.test_pending", "external_connection", connection.id, {"provider": provider, "workflow_id": workflow["workflow_id"]})
        db.flush()
        return {"ok": True, "status": "testing", "workflow_id": workflow["workflow_id"]}

    connection.status = "testing"
    connection.last_error = "connection test workflow started"
    write_audit_log(db, "connection.test_started", "external_connection", connection.id, {"provider": provider, "workflow_id": workflow["workflow_id"]})
    db.flush()
    return {"ok": True, "status": "testing", "workflow_id": workflow["workflow_id"]}


def _can_run_local_connection_test(workflow: dict[str, Any]) -> bool:
    return bool(get_settings().allow_temporal_fallback)


def _local_connection_test_succeeds(db: Session, provider: str, connection: ExternalConnection, workflow_id: str) -> bool:
    if AdapterRunner is None or ToolContext is None or default_registry is None:
        connection.status = "error"
        connection.last_error = "connection test runtime is unavailable"
        return False
    spec = PROVIDERS.get(provider, {})
    result = AdapterRunner(default_registry()).run(
        db,
        _connection_test_adapter(provider),
        {
            **_connection_runtime_defaults(provider),
            "workflow_id": workflow_id,
            "connection_test": True,
            "required_fields": spec.get("required_fields", []),
        },
        ToolContext(actor="ConnectionTestAgent", agent_run_id=workflow_id, connection_id=connection.id),
    )
    if result.ok:
        connection.status = "connected"
        connection.last_error = None
        write_audit_log(db, "connection.test_succeeded", "external_connection", connection.id, {"provider": provider, "workflow_id": workflow_id})
        return True
    connection.status = "error"
    connection.last_error = result.error or "connection validation failed"
    write_audit_log(db, "connection.test_failed", "external_connection", connection.id, {"provider": provider, "error": connection.last_error, "workflow_id": workflow_id})
    return False


def _connection_test_adapter(provider: str) -> str:
    return {
        "openai": "openai",
        "massive": "massive",
        "quantconnect": "quantconnect_mcp",
        "openbb": "openbb_widget",
        "mlflow": "mlflow",
        "langfuse": "langfuse",
        "superset": "superset_link",
        "grafana": "grafana_link",
        "temporal": "temporal_workflow",
        "jupyterlab": "jupyterlab_link",
        "infisical": "infisical",
        "keycloak": "keycloak_user",
        "minio": "minio_artifact",
        "chainlit": "chainlit_link",
    }.get(provider, provider)


def _connection_runtime_defaults(provider: str) -> dict[str, Any]:
    return _non_secret_runtime_fields(provider)


def disconnect_provider(db: Session, provider: str) -> dict[str, Any]:
    connection = _get_connection(db, provider)
    get_infisical_client().revoke_secret(connection.infisical_secret_path)
    connection.infisical_secret_path = None
    connection.secret_version = None
    connection.meta = _default_meta(provider, PROVIDERS[provider])
    connection.status = "locked" if provider == "ibkr" else "disconnected"
    connection.last_error = None
    write_audit_log(db, "connection.disconnected", "external_connection", connection.id, {"provider": provider})
    db.flush()
    return public_connection(connection)


def _non_secret_runtime_fields(provider: str) -> dict[str, Any]:
    settings = get_settings()
    if provider == "mlflow":
        return {"tracking_uri": settings.mlflow_tracking_uri}
    if provider == "langfuse":
        return {"host": settings.langfuse_host}
    return {}


def _start_connection_test_workflow(db: Session, provider: str, connection: ExternalConnection) -> dict[str, Any]:
    return start_workflow(
        db,
        "ConnectionTestWorkflow",
        "external_connection",
        connection.id,
        {"provider": provider, "connection_id": connection.id},
    )
