from __future__ import annotations

import argparse
import base64
import json
import os
import shutil
import subprocess
import sys
import time
import uuid
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]

REQUIRED_LOCKS = {
    "ALLOW_LIVE_TRADING": "false",
    "ALLOW_AGENT_ARBITRARY_CODE_EXECUTION": "false",
    "ALLOW_LOCAL_AUTH_FALLBACK": "false",
    "ALLOW_TEMPORAL_FALLBACK": "false",
    "ALLOW_LOCAL_POLICY_FALLBACK": "false",
    "ALLOW_LOCAL_SECRET_FALLBACK": "false",
    "ALLOW_AGENT_FALLBACK": "false",
    "ALLOW_MATURE_TOOL_FALLBACK": "false",
}
INFISICAL_IDENTITY = [
    "INFISICAL_PROJECT_ID",
    "INFISICAL_MACHINE_IDENTITY_CLIENT_ID",
    "INFISICAL_MACHINE_IDENTITY_CLIENT_SECRET",
]
INFISICAL_INTERNAL_SECRET_REFS = [
    "KEYCLOAK_CLIENT_SECRET_REF",
    "OPENBB_KEYCLOAK_CLIENT_SECRET_REF",
    "LANGFUSE_PUBLIC_KEY_REF",
    "LANGFUSE_SECRET_KEY_REF",
]
OPTIONAL_EXTERNAL_PROVIDER_SECRET_REFS = [
    "OPENAI_API_KEY_REF",
    "MASSIVE_API_KEY_REF",
    "QUANTCONNECT_API_TOKEN_REF",
]
CHAINLIT_OAUTH = {
    "CHAINLIT_AUTH_SECRET": None,
    "OAUTH_GENERIC_NAME": "keycloak",
    "OAUTH_GENERIC_CLIENT_ID": "chainlit",
    "OAUTH_GENERIC_AUTH_URL": "http://localhost:8080/realms/quant-team-os/protocol/openid-connect/auth",
    "OAUTH_GENERIC_TOKEN_URL": "http://keycloak:8080/realms/quant-team-os/protocol/openid-connect/token",
    "OAUTH_GENERIC_USER_INFO_URL": "http://keycloak:8080/realms/quant-team-os/protocol/openid-connect/userinfo",
    "OAUTH_GENERIC_SCOPES": "openid profile email",
}
FORBIDDEN_RAW_PROVIDER_SECRETS = [
    "OPENAI_API_KEY",
    "MASSIVE_API_KEY",
    "QUANTCONNECT_API_TOKEN",
]
LIVE_ENDPOINTS = {
    "api health": ("API_BASE_URL", "http://localhost:8000", "/healthz", {200}),
    "control ui": ("CONTROL_UI_URL", "http://localhost:5173", "", {200}),
    "keycloak": ("KEYCLOAK_BASE_URL", "http://localhost:8080", "", {200, 302}),
    "infisical": ("INFISICAL_UI_URL", "http://localhost:8082", "", {200, 302, 401, 403}),
    "temporal ui": ("TEMPORAL_UI_URL", "http://localhost:8233", "", {200}),
    "minio console": ("MINIO_CONSOLE_URL", "http://localhost:9001", "", {200, 403}),
    "mlflow": ("MLFLOW_UI_URL", "http://localhost:5000", "", {200}),
    "langfuse": ("LANGFUSE_UI_URL", "http://localhost:3002", "", {200, 302}),
    "superset": ("SUPERSET_URL", "http://localhost:8088", "", {200, 302}),
    "grafana": ("GRAFANA_URL", "http://localhost:3000", "", {200, 302}),
    "jupyterlab": ("JUPYTERLAB_URL", "http://localhost:8888", "", {200, 302}),
    "prometheus": ("PROMETHEUS_URL", "http://localhost:9090", "", {200}),
    "loki": ("LOKI_URL", "http://localhost:3100", "/ready", {200}),
    "openbb backend": ("OPENBB_BACKEND_URL", "http://localhost:8010", "/widgets.json", {200}),
    "chainlit": ("CHAINLIT_URL", "http://localhost:8001", "", {200, 302}),
}
REQUIRED_OPENBB_WIDGET_IDS = {"strategy-registry", "backtest-summary", "factor-library", "risk-review", "research-progress"}
COMPOSE_SERVICES = {
    "postgres",
    "keycloak",
    "redis",
    "infisical",
    "temporal",
    "temporal-ui",
    "opa",
    "minio",
    "minio-init",
    "api",
    "workers",
    "control-ui",
    "agent-chat",
    "openbb-backend",
    "mlflow",
    "langfuse",
    "otel-collector",
    "prometheus",
    "postgres-exporter",
    "loki",
    "promtail",
    "superset",
    "superset-init",
    "grafana",
    "jupyterlab",
}
INIT_SERVICES = {"minio-init", "superset-init"}


def parse_env(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.exists():
        raise FileNotFoundError(path)
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        if line.startswith("export "):
            line = line[len("export ") :]
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def static_failures(values: dict[str, str], *, template_ok: bool) -> list[str]:
    failures: list[str] = []
    for key, expected in REQUIRED_LOCKS.items():
        if values.get(key) != expected:
            failures.append(f"{key} must be {expected}")
    for key in INFISICAL_IDENTITY:
        if not values.get(key) and not template_ok:
            failures.append(f"{key} is required after you create the Infisical machine identity")
    for key, expected in CHAINLIT_OAUTH.items():
        if not values.get(key):
            failures.append(f"{key} is required for Chainlit Keycloak OAuth")
        elif expected is not None and values.get(key) != expected:
            failures.append(f"{key} must be {expected}")
    if not values.get("OAUTH_GENERIC_CLIENT_SECRET") and not template_ok:
        failures.append("OAUTH_GENERIC_CLIENT_SECRET is required for Chainlit Keycloak OAuth")
    for key in FORBIDDEN_RAW_PROVIDER_SECRETS:
        if values.get(key):
            failures.append(f"{key} must not be set; use Infisical secret refs instead")
    for key in [*INFISICAL_INTERNAL_SECRET_REFS, *OPTIONAL_EXTERNAL_PROVIDER_SECRET_REFS, "OPENBB_INTERNAL_TOKEN"]:
        if not values.get(key):
            failures.append(f"{key} must be present")
    if values.get("DATABASE_URL", "").startswith("sqlite"):
        failures.append("full-stack .env must use PostgreSQL, not SQLite")
    return failures


def live_failures(values: dict[str, str], timeout: float, *, require_external_providers: bool = False) -> list[str]:
    failures: list[str] = []
    for name, (env_key, default_base, path, ok_statuses) in LIVE_ENDPOINTS.items():
        base = values.get(env_key) or default_base
        url = base.rstrip("/") + path
        try:
            request = Request(url, headers={"User-Agent": "qto-full-stack-doctor"})
            with urlopen(request, timeout=timeout) as response:
                status = response.status
                body = response.read()
        except HTTPError as exc:
            status = exc.code
            body = exc.read()
        except URLError as exc:
            failures.append(f"{name} unreachable at {url}: {exc.reason}")
            continue
        except TimeoutError:
            failures.append(f"{name} timed out at {url}")
            continue
        if status not in ok_statuses:
            failures.append(f"{name} returned HTTP {status} at {url}")
            continue
        if name == "openbb backend" and status == 200:
            failures.extend(validate_openbb_widgets_json(body))
    if not any(failure.startswith("infisical ") for failure in failures):
        failures.extend(validate_infisical_machine_identity(values, timeout, require_external_providers=require_external_providers))
    if not any(failure.startswith("openbb internal ") for failure in failures) and not any(failure.startswith("api ") for failure in failures):
        failures.extend(validate_openbb_internal_service_token(values, timeout))
    if not any(failure.startswith("openbb ") for failure in failures) and not any(failure.startswith("api ") for failure in failures):
        failures.extend(validate_openbb_widget_contracts(values, timeout))
    if not any(failure.startswith("keycloak ") for failure in failures) and not any(failure.startswith("api ") for failure in failures):
        failures.extend(validate_keycloak_api_auth(values, timeout))
    if not any(failure.startswith("langfuse ") for failure in failures) and not any(failure.startswith("keycloak ") for failure in failures) and not any(failure.startswith("api ") for failure in failures):
        failures.extend(validate_langfuse_trace_smoke(values, timeout))
    if not any(failure.startswith("research workflow ") for failure in failures) and not any(failure.startswith("api ") for failure in failures):
        failures.extend(validate_research_workflow_smoke(values, timeout))
    if not any(failure.startswith("opa ") for failure in failures):
        failures.extend(validate_opa_trading_lock(values, timeout))
    if not any(failure.startswith("mlflow ") for failure in failures):
        failures.extend(validate_mlflow_experiments(values, timeout))
    if not any(failure.startswith("mlflow ") for failure in failures):
        failures.extend(validate_mlflow_run_smoke(timeout))
    if not any(failure.startswith("prometheus ") for failure in failures):
        failures.extend(validate_prometheus_targets(values, timeout))
    if not any(failure.startswith("grafana ") for failure in failures):
        failures.extend(validate_grafana_dashboard(values, timeout))
    if not any(failure.startswith("superset ") for failure in failures):
        failures.extend(validate_superset_dashboard(values, timeout))
    if not any(failure.startswith("chainlit ") for failure in failures):
        failures.extend(validate_chainlit_bridge_smoke(timeout))
    if not any(failure.startswith("minio ") for failure in failures):
        failures.extend(validate_minio_buckets(timeout))
    if not any(failure.startswith("dvc ") for failure in failures):
        failures.extend(validate_dvc_minio_roundtrip(timeout))
    failures.extend(validate_temporal_server_connection(timeout))
    failures.extend(validate_temporal_worker_registration(timeout))
    return failures


def _request_json(request: Request, timeout: float) -> dict[str, object]:
    with urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def _keycloak_token(values: dict[str, str], timeout: float) -> tuple[str | None, str | None]:
    keycloak = (values.get("KEYCLOAK_BASE_URL") or "http://localhost:8080").rstrip("/")
    realm = values.get("KEYCLOAK_REALM") or "quant-team-os"
    client_id = values.get("KEYCLOAK_SMOKE_CLIENT_ID") or "openbb-backend"
    client_secret = values.get("KEYCLOAK_SMOKE_CLIENT_SECRET") or "openbb-backend-local-secret"
    token_body = urlencode(
        {
            "grant_type": "client_credentials",
            "client_id": client_id,
            "client_secret": client_secret,
        }
    ).encode("utf-8")
    token_request = Request(
        f"{keycloak}/realms/{realm}/protocol/openid-connect/token",
        data=token_body,
        headers={"Content-Type": "application/x-www-form-urlencoded", "User-Agent": "qto-full-stack-doctor"},
        method="POST",
    )
    try:
        token_payload = _request_json(token_request, timeout)
    except HTTPError as exc:
        return None, f"keycloak smoke client token returned HTTP {exc.code}"
    except (URLError, TimeoutError) as exc:
        return None, f"keycloak smoke client token failed: {getattr(exc, 'reason', exc)}"
    except json.JSONDecodeError as exc:
        return None, f"keycloak smoke client token returned invalid JSON: {exc}"
    token = token_payload.get("access_token")
    if not token:
        return None, "keycloak smoke client token did not return access_token"
    return str(token), None


def _api_json(values: dict[str, str], token: str, path: str, timeout: float, *, payload: dict[str, object] | None = None) -> dict[str, object]:
    api = (values.get("API_BASE_URL") or "http://localhost:8000").rstrip("/")
    body = json.dumps(payload).encode("utf-8") if payload is not None else None
    headers = {"Authorization": f"Bearer {token}", "User-Agent": "qto-full-stack-doctor"}
    if body is not None:
        headers["Content-Type"] = "application/json"
    api_request = Request(f"{api}{path}", data=body, headers=headers, method="POST" if body is not None else "GET")
    return _request_json(api_request, timeout)


def validate_keycloak_api_auth(values: dict[str, str], timeout: float) -> list[str]:
    token, error = _keycloak_token(values, timeout)
    if error or not token:
        return [error or "keycloak smoke client token failed"]
    try:
        connections_payload = _api_json(values, token, "/api/v1/connections", timeout)
    except HTTPError as exc:
        return [f"api protected connections returned HTTP {exc.code} with Keycloak token"]
    except (URLError, TimeoutError) as exc:
        return [f"api protected connections failed with Keycloak token: {getattr(exc, 'reason', exc)}"]
    except json.JSONDecodeError as exc:
        return [f"api protected connections returned invalid JSON: {exc}"]
    if not isinstance(connections_payload.get("providers"), list):
        return ["api protected connections did not return providers list"]
    return []


def validate_openbb_internal_service_token(values: dict[str, str], timeout: float) -> list[str]:
    api = (values.get("API_BASE_URL") or "http://localhost:8000").rstrip("/")
    internal_token = values.get("OPENBB_INTERNAL_TOKEN")
    if not internal_token:
        return ["openbb internal token check missing OPENBB_INTERNAL_TOKEN"]
    request = Request(
        f"{api}/api/v1/internal/openbb/service-token",
        data=b"",
        headers={"X-QTO-Internal-Token": internal_token, "User-Agent": "qto-full-stack-doctor"},
        method="POST",
    )
    try:
        payload = _request_json(request, timeout)
    except HTTPError as exc:
        return [f"openbb internal service token returned HTTP {exc.code}"]
    except (URLError, TimeoutError) as exc:
        return [f"openbb internal service token failed: {getattr(exc, 'reason', exc)}"]
    except json.JSONDecodeError as exc:
        return [f"openbb internal service token returned invalid JSON: {exc}"]
    if not payload.get("access_token"):
        return ["openbb internal service token did not return access_token"]
    protected_request = Request(
        f"{api}/api/v1/ui/openbb/widgets.json",
        headers={"Authorization": f"Bearer {payload['access_token']}", "User-Agent": "qto-full-stack-doctor"},
    )
    try:
        manifest = _request_json(protected_request, timeout)
    except HTTPError as exc:
        return [f"openbb internal service token could not call protected widget manifest: HTTP {exc.code}"]
    except (URLError, TimeoutError) as exc:
        return [f"openbb internal service token protected widget manifest failed: {getattr(exc, 'reason', exc)}"]
    except json.JSONDecodeError as exc:
        return [f"openbb internal service token protected widget manifest returned invalid JSON: {exc}"]
    if manifest.get("audit_required") is not True:
        return ["openbb internal service token protected widget manifest did not return audited payload"]
    return []


def validate_openbb_widget_contracts(values: dict[str, str], timeout: float) -> list[str]:
    base = (values.get("OPENBB_BACKEND_URL") or "http://localhost:8010").rstrip("/")
    failures: list[str] = []
    try:
        manifest = _request_json(Request(f"{base}/widgets.json", headers={"User-Agent": "qto-full-stack-doctor"}), timeout)
    except HTTPError as exc:
        return [f"openbb widget contracts manifest returned HTTP {exc.code}"]
    except (URLError, TimeoutError) as exc:
        return [f"openbb widget contracts manifest failed: {getattr(exc, 'reason', exc)}"]
    except json.JSONDecodeError as exc:
        return [f"openbb widget contracts manifest returned invalid JSON: {exc}"]

    failures.extend(validate_openbb_widgets_payload(manifest))
    widgets = manifest.get("widgets")
    seen_ids = {item.get("id") for item in widgets if isinstance(item, dict)} if isinstance(widgets, list) else set()
    if seen_ids != REQUIRED_OPENBB_WIDGET_IDS:
        failures.append(f"openbb widget contracts must expose exactly required widgets: {', '.join(sorted(REQUIRED_OPENBB_WIDGET_IDS))}")
    for widget_id in sorted(REQUIRED_OPENBB_WIDGET_IDS):
        try:
            payload = _request_json(Request(f"{base}/widgets/{widget_id}", headers={"User-Agent": "qto-full-stack-doctor"}), timeout)
        except HTTPError as exc:
            failures.append(f"openbb widget contracts {widget_id} returned HTTP {exc.code}")
            continue
        except (URLError, TimeoutError) as exc:
            failures.append(f"openbb widget contracts {widget_id} failed: {getattr(exc, 'reason', exc)}")
            continue
        except json.JSONDecodeError as exc:
            failures.append(f"openbb widget contracts {widget_id} returned invalid JSON: {exc}")
            continue
        failures.extend(validate_openbb_widget_payload_object(payload, widget_id))
    if not failures:
        failures.extend(validate_openbb_widget_audit_rows(timeout))
    return failures


def validate_openbb_widget_audit_rows(timeout: float) -> list[str]:
    widget_ids = sorted(REQUIRED_OPENBB_WIDGET_IDS)
    code = f"""
import json

from app.db.models import AuditLog
from app.db.session import session_scope

widget_ids = {json.dumps(widget_ids)}
with session_scope() as db:
    manifest = (
        db.query(AuditLog)
        .filter_by(action="external_ui.openbb_widgets_manifest_viewed", target_id="widgets.json")
        .first()
    )
    rows = (
        db.query(AuditLog)
        .filter(AuditLog.action == "external_ui.openbb_widget_viewed", AuditLog.target_id.in_(widget_ids))
        .all()
    )
    seen = {{row.target_id for row in rows}}
    missing = sorted(set(widget_ids) - seen)
    assert manifest is not None, "manifest audit row missing"
    assert not missing, f"widget audit rows missing: {{missing}}"
    print(json.dumps({{"ok": True, "widgets": sorted(seen)}}))
"""
    return _compose_python_check("widget audit rows", code, timeout, "openbb")


def validate_research_workflow_smoke(values: dict[str, str], timeout: float) -> list[str]:
    token, error = _keycloak_token(values, timeout)
    if error or not token:
        return [f"research workflow smoke cannot get Keycloak token: {error or 'missing token'}"]
    idea_payload = {
        "title": "QTO doctor smoke research idea",
        "thesis": "Validate live ResearchWorkflow API boundary.",
        "universe": "US equities",
        "asset_class": "equity",
        "proposed_by": "qto-doctor",
        "tags": ["qto-doctor", "smoke"],
    }
    try:
        idea = _api_json(values, token, "/api/v1/research-ideas", timeout, payload=idea_payload)
        idea_id = idea.get("id")
        if not idea_id:
            return ["research workflow smoke did not create ResearchIdea id"]
        workflow = _api_json(values, token, f"/api/v1/research-ideas/{idea_id}/start-workflow", timeout, payload={})
        workflow_id = workflow.get("workflow_id")
        if not workflow_id or workflow.get("workflow_type") != "ResearchWorkflow":
            return ["research workflow smoke did not start ResearchWorkflow"]
        link = _api_json(values, token, f"/api/v1/workflows/{workflow_id}", timeout)
        events = _api_json(values, token, f"/api/v1/workflows/{workflow_id}/events", timeout)
        approval = _poll_workflow_approval(values, token, str(workflow_id), timeout)
        if approval is None:
            return ["research workflow smoke did not reach pending approval"]
    except HTTPError as exc:
        return [f"research workflow smoke returned HTTP {exc.code}"]
    except (URLError, TimeoutError) as exc:
        return [f"research workflow smoke failed: {getattr(exc, 'reason', exc)}"]
    except json.JSONDecodeError as exc:
        return [f"research workflow smoke returned invalid JSON: {exc}"]
    if link.get("workflow_id") != workflow_id:
        return ["research workflow smoke could not read created workflow link"]
    if link.get("status") not in {"started", "running", "completed"}:
        return [f"research workflow smoke returned unexpected status: {link.get('status')}"]
    temporal = (link.get("metadata") or {}).get("temporal") if isinstance(link.get("metadata"), dict) else None
    if not isinstance(temporal, dict) or temporal.get("ok") is not True or temporal.get("mode") != "temporal":
        return ["research workflow smoke did not record a real Temporal start"]
    event_types = {event.get("type") for event in events.get("events", []) if isinstance(event, dict)}
    if "workflow.temporal_fallback" in event_types:
        return ["research workflow smoke recorded Temporal fallback"]
    if "workflow.temporal_started" not in event_types:
        return ["research workflow smoke did not expose workflow.temporal_started event"]
    signal_failures = _signal_temporal_approval(str(workflow_id), str(approval["id"]), timeout)
    if signal_failures:
        return signal_failures
    resumed = _poll_workflow_status(values, token, str(workflow_id), "rejected", timeout)
    if resumed is None:
        return ["research workflow smoke did not resume after Temporal approval signal"]
    resumed_events = _api_json(values, token, f"/api/v1/workflows/{workflow_id}/events", timeout)
    resumed_event_types = {event.get("type") for event in resumed_events.get("events", []) if isinstance(event, dict)}
    if "workflow.signal_fallback" in resumed_event_types:
        return ["research workflow smoke recorded signal fallback"]
    if "workflow.rejected" not in resumed_event_types:
        return ["research workflow smoke did not record workflow.rejected after signal"]
    return []


def _poll_workflow_approval(values: dict[str, str], token: str, workflow_id: str, timeout: float) -> dict[str, object] | None:
    deadline = time.monotonic() + max(60.0, timeout)
    while time.monotonic() < deadline:
        approvals = _api_json(values, token, "/api/v1/approvals", timeout)
        rows = approvals if isinstance(approvals, list) else []
        for row in rows:
            if isinstance(row, dict) and row.get("workflow_id") == workflow_id and row.get("status") == "pending":
                return row
        time.sleep(2)
    return None


def _poll_workflow_status(values: dict[str, str], token: str, workflow_id: str, expected_status: str, timeout: float) -> dict[str, object] | None:
    deadline = time.monotonic() + max(60.0, timeout)
    while time.monotonic() < deadline:
        link = _api_json(values, token, f"/api/v1/workflows/{workflow_id}", timeout)
        if link.get("status") == expected_status:
            return link
        time.sleep(2)
    return None


def _signal_temporal_approval(workflow_id: str, approval_request_id: str, timeout: float) -> list[str]:
    payload = json.dumps(
        {
            "action": "rejected",
            "approval_request_id": approval_request_id,
            "actor": "qto-doctor",
            "human_comment": "Doctor smoke rejection to verify Temporal signal resume.",
        }
    )
    code = f"""
import asyncio
import json
import os

from temporalio.client import Client

workflow_id = {json.dumps(workflow_id)}
payload = json.loads({json.dumps(payload)})

async def main():
    client = await Client.connect(os.getenv("TEMPORAL_ADDRESS", "temporal:7233"), namespace=os.getenv("TEMPORAL_NAMESPACE", "default"))
    handle = client.get_workflow_handle(workflow_id)
    await handle.signal("approval_resolved", payload)
    print(json.dumps({{"ok": True, "workflow_id": workflow_id}}))

asyncio.run(main())
"""
    return _compose_python_check("research workflow approval signal", code, timeout, "temporal")


def validate_langfuse_trace_smoke(values: dict[str, str], timeout: float) -> list[str]:
    token, error = _keycloak_token(values, timeout)
    if error or not token:
        return [f"langfuse trace smoke cannot get Keycloak token: {error or 'missing token'}"]
    payload = {
        "task_type": "doctor_trace",
        "input_payload": {
            "source": "full_stack_doctor",
            "agent_name": "DoctorAgent",
            "prompt_version": "v0.3",
            "latency": 0.0,
        },
    }
    try:
        run = _api_json(values, token, "/api/v1/agent-runs", timeout, payload=payload)
        run_id = run.get("id")
        if not run_id:
            return ["langfuse trace smoke did not create AgentRun id"]
        link = _api_json(values, token, f"/api/v1/agent-runs/{run_id}/langfuse-link", timeout)
    except HTTPError as exc:
        return [f"langfuse trace smoke returned HTTP {exc.code}"]
    except (URLError, TimeoutError) as exc:
        return [f"langfuse trace smoke failed: {getattr(exc, 'reason', exc)}"]
    except json.JSONDecodeError as exc:
        return [f"langfuse trace smoke returned invalid JSON: {exc}"]
    trace_id = str(link.get("trace_id") or run.get("langfuse_trace_id") or "")
    if not trace_id:
        return ["langfuse trace smoke did not return trace_id"]
    if trace_id.startswith("local-"):
        return ["langfuse trace smoke used local_mirror instead of Langfuse"]
    return validate_langfuse_trace_readable(trace_id, timeout)


def validate_langfuse_trace_readable(trace_id: str, timeout: float) -> list[str]:
    code = r"""
import json
import os
import time
from urllib.parse import quote

import httpx

from app.core.config import get_settings
from app.services.infisical import get_infisical_client

trace_id = os.environ["QTO_LANGFUSE_TRACE_ID"]
deadline = time.monotonic() + max(30.0, float(os.environ.get("QTO_LANGFUSE_TIMEOUT_SECONDS", "2")))
settings = get_settings()
secrets = get_infisical_client()


def secret_value(path, preferred_key):
    payload = secrets.read_secret(path)
    for key in [preferred_key, "value", "secret", "api_key", "key"]:
        value = payload.get(key)
        if value:
            return str(value)
    return ""


public_key = secret_value(settings.langfuse_public_key_ref, "public_key")
secret_key = secret_value(settings.langfuse_secret_key_ref, "secret_key")
assert public_key and secret_key, "Langfuse API keys are missing from Infisical"
host = settings.langfuse_host.rstrip("/")
last_status = None
with httpx.Client(timeout=5.0) as client:
    while time.monotonic() < deadline:
        response = client.get(
            f"{host}/api/public/traces/{quote(trace_id, safe='')}",
            params={"fields": "core,metadata"},
            auth=(public_key, secret_key),
        )
        last_status = response.status_code
        if response.status_code == 200:
            payload = response.json()
            returned_id = payload.get("id") or payload.get("traceId")
            assert returned_id == trace_id, f"unexpected trace id: {returned_id}"
            print(json.dumps({"ok": True, "trace_id": trace_id}))
            raise SystemExit(0)
        if response.status_code not in {404, 408, 429, 500, 502, 503}:
            raise AssertionError(f"Langfuse trace API returned HTTP {response.status_code}")
        time.sleep(2)
raise AssertionError(f"Langfuse trace was not readable, last HTTP status: {last_status}")
"""
    return _compose_python_check(
        "trace readable smoke",
        code,
        timeout,
        "langfuse",
        env={"QTO_LANGFUSE_TRACE_ID": trace_id, "QTO_LANGFUSE_TIMEOUT_SECONDS": str(timeout)},
    )


def validate_opa_trading_lock(values: dict[str, str], timeout: float) -> list[str]:
    base = (values.get("OPA_PUBLIC_URL") or "http://localhost:8181").rstrip("/")
    payload = json.dumps({"input": {"action": "live_order", "system": {"allow_live_trading": False}}}).encode("utf-8")
    request = Request(
        f"{base}/v1/data/qto/trading_lock",
        data=payload,
        headers={"Content-Type": "application/json", "User-Agent": "qto-full-stack-doctor"},
        method="POST",
    )
    try:
        policy_payload = _request_json(request, timeout)
    except HTTPError as exc:
        return [f"opa trading lock query returned HTTP {exc.code}"]
    except (URLError, TimeoutError) as exc:
        return [f"opa trading lock query failed: {getattr(exc, 'reason', exc)}"]
    except json.JSONDecodeError as exc:
        return [f"opa trading lock query returned invalid JSON: {exc}"]
    result = policy_payload.get("result") or {}
    if result.get("allow") is not False or "live trading is locked" not in result.get("deny", []):
        return ["opa trading lock did not deny live_order"]
    return []


def validate_mlflow_experiments(values: dict[str, str], timeout: float) -> list[str]:
    base = (values.get("MLFLOW_UI_URL") or values.get("MLFLOW_TRACKING_URI") or "http://localhost:5000").rstrip("/")
    request = Request(
        f"{base}/api/2.0/mlflow/experiments/search",
        data=b"{}",
        headers={"Content-Type": "application/json", "User-Agent": "qto-full-stack-doctor"},
        method="POST",
    )
    try:
        payload = _request_json(request, timeout)
    except HTTPError as exc:
        return [f"mlflow experiments API returned HTTP {exc.code}"]
    except (URLError, TimeoutError) as exc:
        return [f"mlflow experiments API failed: {getattr(exc, 'reason', exc)}"]
    except json.JSONDecodeError as exc:
        return [f"mlflow experiments API returned invalid JSON: {exc}"]
    if not isinstance(payload.get("experiments"), list):
        return ["mlflow experiments API did not return experiments list"]
    return []


def validate_mlflow_run_smoke(timeout: float) -> list[str]:
    code = r"""
import json
import os
import shutil
import tempfile
from pathlib import Path

import mlflow

mlflow.set_tracking_uri(os.getenv("MLFLOW_TRACKING_URI", "http://mlflow:5000"))
mlflow.set_experiment(os.getenv("MLFLOW_EXPERIMENT_NAME", "quant-team-os"))
work = Path(tempfile.mkdtemp(prefix="qto-mlflow-smoke-"))
try:
    artifact = work / "smoke.txt"
    artifact.write_text("qto-mlflow-smoke\n", encoding="utf-8")
    with mlflow.start_run(run_name="qto-doctor-smoke") as run:
        run_id = run.info.run_id
        mlflow.log_metric("qto_doctor_metric", 1.0)
        mlflow.log_artifact(str(artifact), artifact_path="doctor")
    client = mlflow.tracking.MlflowClient()
    loaded = client.get_run(run_id)
    assert float(loaded.data.metrics["qto_doctor_metric"]) == 1.0
    artifacts = client.list_artifacts(run_id, "doctor")
    assert any(item.path.endswith("smoke.txt") for item in artifacts)
    print(json.dumps({"ok": True, "run_id": run_id}))
finally:
    shutil.rmtree(work, ignore_errors=True)
"""
    return _compose_python_check("run metric artifact smoke", code, timeout, "mlflow")


def validate_prometheus_targets(values: dict[str, str], timeout: float) -> list[str]:
    base = (values.get("PROMETHEUS_URL") or "http://localhost:9090").rstrip("/")
    request = Request(f"{base}/api/v1/targets?state=active", headers={"User-Agent": "qto-full-stack-doctor"})
    try:
        payload = _request_json(request, timeout)
    except HTTPError as exc:
        return [f"prometheus targets API returned HTTP {exc.code}"]
    except (URLError, TimeoutError) as exc:
        return [f"prometheus targets API failed: {getattr(exc, 'reason', exc)}"]
    except json.JSONDecodeError as exc:
        return [f"prometheus targets API returned invalid JSON: {exc}"]
    targets = payload.get("data", {}).get("activeTargets", []) if isinstance(payload.get("data"), dict) else []
    if not isinstance(targets, list):
        return ["prometheus targets API did not return activeTargets list"]
    jobs = {target.get("labels", {}).get("job") for target in targets if isinstance(target, dict) and isinstance(target.get("labels"), dict)}
    required_jobs = {"api", "temporal", "workers", "postgres-exporter", "opa", "otel-collector", "minio"}
    missing = sorted(required_jobs - jobs)
    if missing:
        return [f"prometheus targets missing jobs: {', '.join(missing)}"]
    down = sorted(
        str(target.get("labels", {}).get("job"))
        for target in targets
        if isinstance(target, dict)
        and isinstance(target.get("labels"), dict)
        and target.get("labels", {}).get("job") in required_jobs
        and target.get("health") != "up"
    )
    if down:
        return [f"prometheus targets are not up: {', '.join(down)}"]
    return []


def validate_grafana_dashboard(values: dict[str, str], timeout: float) -> list[str]:
    base = (values.get("GRAFANA_URL") or "http://localhost:3000").rstrip("/")
    username = values.get("GRAFANA_USERNAME") or "admin"
    password = values.get("GRAFANA_PASSWORD") or "admin"
    request = Request(f"{base}/api/dashboards/uid/qto-required-dashboards", headers={"User-Agent": "qto-full-stack-doctor"})
    request.add_header("Authorization", "Basic " + base64.b64encode(f"{username}:{password}".encode()).decode("ascii"))
    try:
        payload = _request_json(request, timeout)
    except HTTPError as exc:
        return [f"grafana required dashboard API returned HTTP {exc.code}"]
    except (URLError, TimeoutError) as exc:
        return [f"grafana required dashboard API failed: {getattr(exc, 'reason', exc)}"]
    except json.JSONDecodeError as exc:
        return [f"grafana required dashboard API returned invalid JSON: {exc}"]
    dashboard = payload.get("dashboard") if isinstance(payload.get("dashboard"), dict) else {}
    if dashboard.get("title") != "Quant Team OS Required Dashboards":
        return ["grafana required dashboard missing: Quant Team OS Required Dashboards"]
    panel_titles = {panel.get("title") for panel in dashboard.get("panels", []) if isinstance(panel, dict)}
    required_titles = {
        "Agent Runtime Monitoring",
        "Temporal Workflow Monitoring",
        "ToolGateway Policy Denials",
        "OpenAI API Cost and Error Rate",
        "Data Ingestion and GX Validation",
        "Backtest Runtime and Failure",
        "Connector Health",
        "Trading Safety Lock",
    }
    missing = sorted(required_titles - panel_titles)
    if missing:
        return [f"grafana required dashboard missing panels: {', '.join(missing)}"]
    return validate_grafana_dashboard_queries(values, dashboard, timeout)


def validate_grafana_dashboard_queries(values: dict[str, str], dashboard: dict[str, object], timeout: float) -> list[str]:
    failures: list[str] = []
    prometheus_base = (values.get("PROMETHEUS_URL") or "http://localhost:9090").rstrip("/")
    loki_base = (values.get("LOKI_URL") or "http://localhost:3100").rstrip("/")
    seen: set[tuple[str, str]] = set()
    for panel in dashboard.get("panels", []):
        if not isinstance(panel, dict):
            continue
        datasource = panel.get("datasource") if isinstance(panel.get("datasource"), dict) else {}
        datasource_type = str(datasource.get("type") or "")
        for target in panel.get("targets", []):
            if not isinstance(target, dict):
                continue
            expr = str(target.get("expr") or "").strip()
            if not expr:
                continue
            key = (datasource_type, expr)
            if key in seen:
                continue
            seen.add(key)
            if datasource_type == "prometheus":
                failures.extend(_validate_prometheus_query(prometheus_base, expr, timeout))
            elif datasource_type == "loki":
                failures.extend(_validate_loki_query(loki_base, expr, timeout))
            else:
                failures.append(f"grafana dashboard uses unsupported datasource type: {datasource_type or '<missing>'}")
    return failures


def _validate_prometheus_query(base: str, expr: str, timeout: float) -> list[str]:
    request = Request(f"{base}/api/v1/query?{urlencode({'query': expr})}", headers={"User-Agent": "qto-full-stack-doctor"})
    try:
        payload = _request_json(request, timeout)
    except HTTPError as exc:
        return [f"grafana prometheus query returned HTTP {exc.code}: {expr}"]
    except (URLError, TimeoutError) as exc:
        return [f"grafana prometheus query failed: {expr}: {getattr(exc, 'reason', exc)}"]
    except json.JSONDecodeError as exc:
        return [f"grafana prometheus query returned invalid JSON: {expr}: {exc}"]
    if payload.get("status") != "success":
        return [f"grafana prometheus query did not succeed: {expr}"]
    return []


def _validate_loki_query(base: str, expr: str, timeout: float) -> list[str]:
    request = Request(f"{base}/loki/api/v1/query?{urlencode({'query': expr})}", headers={"User-Agent": "qto-full-stack-doctor"})
    try:
        payload = _request_json(request, timeout)
    except HTTPError as exc:
        return [f"grafana loki query returned HTTP {exc.code}: {expr}"]
    except (URLError, TimeoutError) as exc:
        return [f"grafana loki query failed: {expr}: {getattr(exc, 'reason', exc)}"]
    except json.JSONDecodeError as exc:
        return [f"grafana loki query returned invalid JSON: {expr}: {exc}"]
    if payload.get("status") != "success":
        return [f"grafana loki query did not succeed: {expr}"]
    return []


def validate_infisical_machine_identity(values: dict[str, str], timeout: float, *, require_external_providers: bool = False) -> list[str]:
    missing = [key for key in INFISICAL_IDENTITY if not values.get(key)]
    if missing:
        return [f"Infisical machine identity is missing for live check: {', '.join(missing)}"]
    base = (values.get("INFISICAL_UI_URL") or "http://localhost:8082").rstrip("/")
    payload = json.dumps(
        {
            "clientId": values["INFISICAL_MACHINE_IDENTITY_CLIENT_ID"],
            "clientSecret": values["INFISICAL_MACHINE_IDENTITY_CLIENT_SECRET"],
        }
    ).encode("utf-8")
    request = Request(
        f"{base}/api/v1/auth/universal-auth/login",
        data=payload,
        headers={"Content-Type": "application/json", "User-Agent": "qto-full-stack-doctor"},
        method="POST",
    )
    try:
        auth_payload = _request_json(request, timeout)
    except HTTPError as exc:
        return [f"infisical machine identity login returned HTTP {exc.code}"]
    except (URLError, TimeoutError) as exc:
        return [f"infisical machine identity login failed: {getattr(exc, 'reason', exc)}"]
    except json.JSONDecodeError as exc:
        return [f"infisical machine identity login returned invalid JSON: {exc}"]
    if not auth_payload.get("accessToken"):
        return ["infisical machine identity login did not return accessToken"]
    required_refs = list(INFISICAL_INTERNAL_SECRET_REFS)
    if require_external_providers:
        required_refs.extend(OPTIONAL_EXTERNAL_PROVIDER_SECRET_REFS)
    return validate_infisical_secret_refs(values, base, str(auth_payload["accessToken"]), timeout, required_refs)


def validate_infisical_secret_refs(values: dict[str, str], base: str, access_token: str, timeout: float, required_refs: list[str]) -> list[str]:
    failures: list[str] = []
    for key in required_refs:
        ref = values.get(key)
        if not ref:
            failures.append(f"infisical secret ref missing env value: {key}")
            continue
        secret_path, secret_name = _split_infisical_secret_ref(ref)
        query = urlencode(
            {
                "workspaceId": values["INFISICAL_PROJECT_ID"],
                "environment": values.get("APP_ENV") or "dev",
                "secretPath": secret_path,
                "type": "shared",
            }
        )
        request = Request(
            f"{base}/api/v3/secrets/raw/{quote(secret_name, safe='')}?{query}",
            headers={"Authorization": f"Bearer {access_token}", "User-Agent": "qto-full-stack-doctor"},
        )
        try:
            payload = _request_json(request, timeout)
        except HTTPError as exc:
            failures.append(f"infisical secret ref not readable: {key} HTTP {exc.code}")
            continue
        except (URLError, TimeoutError) as exc:
            failures.append(f"infisical secret ref check failed: {key}: {getattr(exc, 'reason', exc)}")
            continue
        except json.JSONDecodeError as exc:
            failures.append(f"infisical secret ref returned invalid JSON: {key}: {exc}")
            continue
        secret = payload.get("secret") if isinstance(payload.get("secret"), dict) else {}
        if not (payload.get("secretValue") or secret.get("secretValue")):
            failures.append(f"infisical secret ref has empty value: {key}")
    return failures


def _split_infisical_secret_ref(ref: str) -> tuple[str, str]:
    secret_path, secret_name = ref.rstrip("/").rsplit("/", 1)
    return secret_path or "/", secret_name


def validate_superset_dashboard(values: dict[str, str], timeout: float) -> list[str]:
    base = (values.get("SUPERSET_URL") or "http://localhost:8088").rstrip("/")
    username = values.get("SUPERSET_ADMIN_USERNAME") or "admin"
    password = values.get("SUPERSET_ADMIN_PASSWORD") or "admin"
    login_payload = json.dumps({"username": username, "password": password, "provider": "db", "refresh": True}).encode("utf-8")
    try:
        login_request = Request(
            f"{base}/api/v1/security/login",
            data=login_payload,
            headers={"Content-Type": "application/json", "User-Agent": "qto-full-stack-doctor"},
            method="POST",
        )
        token_payload = _request_json(login_request, timeout)
    except HTTPError as exc:
        return [f"superset dashboard API login returned HTTP {exc.code}"]
    except (URLError, TimeoutError) as exc:
        return [f"superset dashboard API login failed: {getattr(exc, 'reason', exc)}"]
    except json.JSONDecodeError as exc:
        return [f"superset dashboard API login returned invalid JSON: {exc}"]

    token = token_payload.get("access_token") or token_payload.get("result", {}).get("access_token")
    if not token:
        return ["superset dashboard API login did not return access_token"]

    auth_headers = {"Authorization": f"Bearer {token}", "User-Agent": "qto-full-stack-doctor"}
    query = urlencode({"page_size": "100"})
    dashboard_request = Request(f"{base}/api/v1/dashboard/?{query}", headers=auth_headers)
    try:
        dashboard_payload = _request_json(dashboard_request, timeout)
        chart_payload = _request_json(Request(f"{base}/api/v1/chart/?{query}", headers=auth_headers), timeout)
        dataset_payload = _request_json(Request(f"{base}/api/v1/dataset/?{query}", headers=auth_headers), timeout)
        database_payload = _request_json(Request(f"{base}/api/v1/database/?{query}", headers=auth_headers), timeout)
    except HTTPError as exc:
        return [f"superset dashboard API returned HTTP {exc.code}"]
    except (URLError, TimeoutError) as exc:
        return [f"superset dashboard API failed: {getattr(exc, 'reason', exc)}"]
    except json.JSONDecodeError as exc:
        return [f"superset dashboard API returned invalid JSON: {exc}"]
    dashboards = _superset_rows(dashboard_payload)
    if not any(item.get("dashboard_title") == "Strategy and Backtest Aggregate" for item in dashboards):
        return ["superset dashboard missing: Strategy and Backtest Aggregate"]
    chart_names = {item.get("slice_name") or item.get("chart_name") for item in _superset_rows(chart_payload)}
    required_charts = {"Strategies by Status", "Backtest Runs by Status", "Risk Review Verdicts", "Factor Specs by Status"}
    missing_charts = sorted(required_charts - chart_names)
    if missing_charts:
        return [f"superset dashboard missing charts: {', '.join(missing_charts)}"]
    dataset_names = {item.get("table_name") or item.get("dataset_name") for item in _superset_rows(dataset_payload)}
    if "qto_strategy_backtest_aggregate" not in dataset_names:
        return ["superset dashboard missing dataset: qto_strategy_backtest_aggregate"]
    database_id = _superset_database_id(database_payload, "quant_team_os")
    if database_id is None:
        return ["superset dashboard missing database: quant_team_os"]
    return validate_superset_chart_queries(base, auth_headers, database_id, timeout)


def validate_chainlit_bridge_smoke(timeout: float) -> list[str]:
    code = r"""
import json

import app

assert app.API_URL == "http://api:8000", app.API_URL
assert app.oauth_configured(), "Chainlit OAuth env is not configured"
assert app.command_payload("/workflow idea-1") == {"action": "start_research_workflow", "research_idea_id": "idea-1"}
assert app.command_payload("/approvals pending") == {"action": "approvals", "status": "pending"}
approval = app.approval_command_payload("/approve", "approval-1 reviewed")
assert approval["action"] == "resolve_approval"
assert approval["resolution"] == "approve"
assert app.approval_endpoint("approval-1", "approve") == "/api/v1/approvals/approval-1/approve"
print(json.dumps({"ok": True, "api_url": app.API_URL}))
"""
    return _compose_python_check("bridge oauth api smoke", code, timeout, "chainlit", service="agent-chat")


def _superset_rows(payload: dict[str, object]) -> list[dict[str, object]]:
    result = payload.get("result")
    if isinstance(result, list):
        return [item for item in result if isinstance(item, dict)]
    if isinstance(result, dict):
        for key in ("data", "result"):
            rows = result.get(key)
            if isinstance(rows, list):
                return [item for item in rows if isinstance(item, dict)]
    return []


def _superset_database_id(payload: dict[str, object], database_name: str) -> int | None:
    for row in _superset_rows(payload):
        if row.get("database_name") != database_name:
            continue
        try:
            return int(row.get("id"))
        except (TypeError, ValueError):
            return None
    return None


def validate_superset_chart_queries(base: str, auth_headers: dict[str, str], database_id: int, timeout: float) -> list[str]:
    spec_path = ROOT / "infra/superset/dashboards/strategy_backtest_aggregate.json"
    spec = json.loads(spec_path.read_text(encoding="utf-8"))
    csrf = _superset_csrf_token(base, auth_headers, timeout)
    if not csrf:
        return ["superset chart query API did not return csrf token"]
    headers = {**auth_headers, "Content-Type": "application/json", "X-CSRFToken": csrf}
    failures: list[str] = []
    for chart in spec.get("charts", []):
        if not isinstance(chart, dict):
            continue
        name = str(chart.get("name") or "<unnamed>")
        sql = str(chart.get("query") or "").strip()
        if not sql:
            failures.append(f"superset chart query missing SQL: {name}")
            continue
        payload = json.dumps(
            {
                "database_id": database_id,
                "sql": sql,
                "client_id": f"qto-doctor-{uuid.uuid4().hex}",
                "queryLimit": 100,
                "schema": "public",
                "runAsync": False,
                "expand_data": True,
            }
        ).encode("utf-8")
        request = Request(f"{base}/api/v1/sqllab/execute/", data=payload, headers=headers, method="POST")
        try:
            result = _request_json(request, timeout)
        except HTTPError as exc:
            failures.append(f"superset chart query returned HTTP {exc.code}: {name}")
            continue
        except (URLError, TimeoutError) as exc:
            failures.append(f"superset chart query failed: {name}: {getattr(exc, 'reason', exc)}")
            continue
        except json.JSONDecodeError as exc:
            failures.append(f"superset chart query returned invalid JSON: {name}: {exc}")
            continue
        if result.get("errors"):
            failures.append(f"superset chart query returned errors: {name}")
        elif not any(key in result for key in ("data", "columns", "query")):
            failures.append(f"superset chart query returned unexpected payload: {name}")
    return failures


def _superset_csrf_token(base: str, auth_headers: dict[str, str], timeout: float) -> str | None:
    try:
        payload = _request_json(Request(f"{base}/api/v1/security/csrf_token/", headers=auth_headers), timeout)
    except (HTTPError, URLError, TimeoutError, json.JSONDecodeError):
        return None
    result = payload.get("result")
    if isinstance(result, dict):
        token = result.get("csrf_token")
        return str(token) if token else None
    return str(result) if result else None


def validate_minio_buckets(timeout: float) -> list[str]:
    smoke_id = uuid.uuid4().hex
    code = r"""
import json
import os

import boto3

smoke_id = os.environ["QTO_DOCTOR_SMOKE_ID"]
client = boto3.client(
    "s3",
    endpoint_url=os.environ["S3_ENDPOINT_URL"],
    aws_access_key_id=os.environ["AWS_ACCESS_KEY_ID"],
    aws_secret_access_key=os.environ["AWS_SECRET_ACCESS_KEY"],
)
buckets = [
    os.environ["S3_BUCKET_ARTIFACTS"],
    os.environ["S3_BUCKET_DATASETS"],
    os.environ["S3_BUCKET_MLFLOW"],
    os.environ["S3_BUCKET_REPORTS"],
    os.environ["S3_BUCKET_DVC"],
]
for bucket in buckets:
    client.head_bucket(Bucket=bucket)
for bucket in buckets:
    key = f"doctor/{smoke_id}/{bucket}.txt"
    body = f"qto-minio-smoke:{smoke_id}:{bucket}".encode("utf-8")
    client.put_object(Bucket=bucket, Key=key, Body=body)
    loaded = client.get_object(Bucket=bucket, Key=key)["Body"].read()
    assert loaded == body
    client.delete_object(Bucket=bucket, Key=key)
print(json.dumps({"ok": True, "buckets": buckets}))
"""
    return _compose_python_check("minio bucket check", code, timeout, "minio", env={"QTO_DOCTOR_SMOKE_ID": smoke_id})


def validate_dvc_minio_roundtrip(timeout: float) -> list[str]:
    smoke_id = uuid.uuid4().hex
    code = r"""
import json
import shutil
import subprocess
import tempfile
from pathlib import Path

smoke_id = os.environ["QTO_DOCTOR_SMOKE_ID"]
work = Path(tempfile.mkdtemp(prefix="qto-dvc-smoke-"))
try:
    shutil.copytree("/app/.dvc", work / ".dvc")
    filename = f"smoke-{smoke_id}.txt"
    expected = f"qto-dvc-smoke:{smoke_id}\n"
    (work / filename).write_text(expected, encoding="utf-8")

    def run(command):
        return subprocess.run(command, cwd=work, check=True, capture_output=True, text=True)

    run(["dvc", "config", "core.no_scm", "true"])
    run(["dvc", "add", filename])
    run(["dvc", "push", "-r", "minio"])
    (work / filename).unlink()
    run(["dvc", "pull", filename, "-r", "minio"])
    assert (work / filename).read_text(encoding="utf-8") == expected
    print(json.dumps({"ok": True, "remote": "minio", "file": filename}))
finally:
    shutil.rmtree(work, ignore_errors=True)
"""
    return _compose_python_check("dvc minio roundtrip", code, timeout, "dvc", env={"QTO_DOCTOR_SMOKE_ID": smoke_id})


def validate_temporal_worker_registration(timeout: float) -> list[str]:
    code = r"""
import asyncio
import json
import os

from worker_main import TASK_QUEUE, configured_activities, configured_workflows
from temporalio.api.enums.v1.task_queue_pb2 import TASK_QUEUE_TYPE_ACTIVITY, TASK_QUEUE_TYPE_WORKFLOW
from temporalio.api.taskqueue.v1 import TaskQueue
from temporalio.api.workflowservice.v1 import DescribeTaskQueueRequest
from temporalio.client import Client

workflow_names = {item.__name__ for item in configured_workflows()}
activity_names = {getattr(item, "__name__", str(item)) for item in configured_activities()}
required_workflows = {
    "ResearchWorkflow",
    "DataIngestionWorkflow",
    "FactorAnalysisWorkflow",
    "BacktestWorkflow",
    "RiskReviewWorkflow",
    "ReportGenerationWorkflow",
    "ConnectionTestWorkflow",
    "StrategyRegistrationWorkflow",
    "PaperPromotionWorkflow",
}
required_activities = {"DVCVersionActivity", "DVCRestoreActivity", "QuantConnectBacktestActivity", "MLflowBacktestActivity", "WorkflowStatusActivity"}
missing_workflows = sorted(required_workflows - workflow_names)
missing_activities = sorted(required_activities - activity_names)
assert not missing_workflows, missing_workflows
assert not missing_activities, missing_activities


async def poller_counts():
    address = os.getenv("TEMPORAL_ADDRESS", "temporal:7233")
    namespace = os.getenv("TEMPORAL_NAMESPACE", "default")
    client = await Client.connect(address, namespace=namespace)

    async def describe(task_queue_type):
        response = await client.workflow_service.describe_task_queue(
            DescribeTaskQueueRequest(
                namespace=namespace,
                task_queue=TaskQueue(name=TASK_QUEUE),
                task_queue_type=task_queue_type,
                report_pollers=True,
            )
        )
        return len(response.pollers)

    return {
        "workflow": await describe(TASK_QUEUE_TYPE_WORKFLOW),
        "activity": await describe(TASK_QUEUE_TYPE_ACTIVITY),
    }


pollers = asyncio.run(poller_counts())
assert pollers["workflow"] > 0, "no workflow task queue pollers"
assert pollers["activity"] > 0, "no activity task queue pollers"
print(json.dumps({"ok": True, "task_queue": TASK_QUEUE, "pollers": pollers, "workflows": sorted(workflow_names), "activities": sorted(activity_names)}))
"""
    return _compose_python_check("worker registration check", code, timeout, "temporal")


def validate_temporal_server_connection(timeout: float) -> list[str]:
    code = r"""
import asyncio
import json
import os

from temporalio.client import Client


async def main():
    address = os.getenv("TEMPORAL_ADDRESS", "temporal:7233")
    namespace = os.getenv("TEMPORAL_NAMESPACE", "default")
    await Client.connect(address, namespace=namespace)
    print(json.dumps({"ok": True, "address": address, "namespace": namespace}))


asyncio.run(main())
"""
    return _compose_python_check("server connection check", code, timeout, "temporal")


def _compose_python_check(label: str, code: str, timeout: float, prefix: str, env: dict[str, str] | None = None, service: str = "workers") -> list[str]:
    if shutil.which("docker") is None:
        return [f"{prefix} {label} failed: docker CLI not found"]
    result = subprocess.run(
        ["docker", "compose", "-f", str(ROOT / "infra/docker-compose.yml"), "exec", "-T", service, "python", "-c", code],
        cwd=ROOT,
        env={**os.environ, **(env or {})},
        text=True,
        capture_output=True,
        timeout=max(timeout, 30.0),
        check=False,
    )
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip()
        return [f"{prefix} {label} failed: {detail}"]
    try:
        payload = json.loads(result.stdout.strip().splitlines()[-1])
    except (IndexError, json.JSONDecodeError) as exc:
        return [f"{prefix} {label} returned invalid JSON: {exc}"]
    if payload.get("ok") is not True:
        return [f"{prefix} {label} did not report ok"]
    return []


def compose_failures(env_path: Path) -> list[str]:
    if shutil.which("docker") is None:
        return ["docker CLI not found; install Docker before running live full-stack checks"]
    try:
        result = subprocess.run(
            ["docker", "compose", "--env-file", str(env_path), "-f", str(ROOT / "infra/docker-compose.yml"), "ps", "--all", "--format", "json"],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
            timeout=10,
        )
    except subprocess.TimeoutExpired:
        if sys.platform == "darwin":
            return [
                "docker compose ps timed out; if Docker Desktop was manually installed, run "
                '`sudo /Applications/Docker.app/Contents/MacOS/install config --user "$(whoami)"`, restart Docker Desktop, then rerun Compose'
            ]
        return ["docker compose ps timed out; restart Docker and rerun Compose"]
    if result.returncode != 0:
        return [f"docker compose ps failed: {result.stderr.strip() or result.stdout.strip()}"]
    services = _parse_compose_ps(result.stdout)
    if not services:
        return ["docker compose has no running Quant Team OS services; run `docker compose --env-file .env -f infra/docker-compose.yml up --build`"]
    failures = [f"docker compose service missing from ps output: {name}" for name in sorted(COMPOSE_SERVICES - set(services))]
    created_services = sorted(name for name, service in services.items() if name in COMPOSE_SERVICES and _service_state(service) == "created")
    if created_services:
        if sys.platform == "darwin" and not Path("/Library/PrivilegedHelperTools/com.docker.socket").exists():
            failures.append(
                "docker compose services are stuck in Created and Docker Desktop's privileged helper is missing; "
                'run `sudo /Applications/Docker.app/Contents/MacOS/install config --user "$(whoami)"`, restart Docker Desktop, then rerun Compose'
            )
        else:
            failures.append(f"docker compose services are stuck in Created: {', '.join(created_services)}")
    for name, service in services.items():
        if name not in COMPOSE_SERVICES:
            continue
        state = _service_state(service)
        if state == "created":
            continue
        if name in INIT_SERVICES:
            if not _completed_successfully(service):
                failures.append(f"docker compose init service did not complete successfully: {name} ({state or 'unknown'})")
            continue
        if state and state != "running":
            failures.append(f"docker compose service is not running: {name} ({state})")
            continue
        health = _service_health(service)
        if health and health != "healthy":
            failures.append(f"docker compose service is not healthy: {name} ({health})")
    return failures


def _parse_compose_ps(output: str) -> dict[str, dict]:
    text = output.strip()
    if not text:
        return {}
    try:
        payload = json.loads(text)
        items = payload if isinstance(payload, list) else [payload]
    except json.JSONDecodeError:
        items = [json.loads(line) for line in text.splitlines() if line.strip()]
    services = {}
    for item in items:
        if not isinstance(item, dict):
            continue
        name = item.get("Service") or item.get("Name") or item.get("service")
        if name:
            services[str(name)] = item
    return services


def _service_state(service: dict) -> str:
    return str(service.get("State") or service.get("state") or "").lower()


def _service_health(service: dict) -> str:
    health = str(service.get("Health") or service.get("health") or "").lower()
    if health:
        return health
    status = str(service.get("Status") or service.get("status") or "").lower()
    for marker in ["healthy", "unhealthy", "starting"]:
        if marker in status:
            return marker
    return ""


def _completed_successfully(service: dict) -> bool:
    state = _service_state(service)
    raw_exit_code = service.get("ExitCode", service.get("exitCode", service.get("exit_code")))
    try:
        exit_code = int(raw_exit_code)
    except (TypeError, ValueError):
        exit_code = None
    return state in {"exited", "completed"} and exit_code == 0


def validate_openbb_widgets_json(body: bytes) -> list[str]:
    try:
        payload = json.loads(body.decode("utf-8"))
    except json.JSONDecodeError as exc:
        return [f"openbb backend returned invalid JSON: {exc}"]
    return validate_openbb_widgets_payload(payload)


def validate_openbb_widgets_payload(payload: dict[str, object]) -> list[str]:
    widgets = payload.get("widgets")
    if not isinstance(widgets, list):
        return ["openbb backend widgets.json must return a widgets list"]
    seen_ids = {item.get("id") for item in widgets if isinstance(item, dict)}
    failures = [f"openbb backend widgets.json missing widget: {widget_id}" for widget_id in sorted(REQUIRED_OPENBB_WIDGET_IDS - seen_ids)]
    if payload.get("mode") != "read_only":
        failures.append("openbb backend widgets.json mode must be read_only")
    if payload.get("audit_required") is not True:
        failures.append("openbb backend widgets.json must require audit")
    if "audited_endpoint" not in payload:
        failures.append("openbb backend widgets.json must expose audited_endpoint")
    for item in widgets:
        if not isinstance(item, dict):
            failures.append("openbb backend widgets.json contains non-object widget")
            continue
        if item.get("mode") != "read_only":
            failures.append(f"openbb widget contract must be read_only: {item.get('id')}")
        if item.get("audit_required") is not True:
            failures.append(f"openbb widget contract must require audit: {item.get('id')}")
    return failures


def validate_openbb_widget_payload(body: bytes) -> list[str]:
    try:
        payload = json.loads(body.decode("utf-8"))
    except json.JSONDecodeError as exc:
        return [f"openbb widget returned invalid JSON: {exc}"]
    return validate_openbb_widget_payload_object(payload, "strategy-registry")


def validate_openbb_widget_payload_object(payload: dict[str, object], expected_widget_id: str) -> list[str]:
    failures = []
    for key, expected in {"widget_id": expected_widget_id, "mode": "read_only", "audit_required": True}.items():
        if payload.get(key) != expected:
            failures.append(f"openbb widget payload {key} must be {expected}")
    audited_endpoint = str(payload.get("audited_endpoint") or "")
    if not audited_endpoint.endswith(f"/api/v1/ui/openbb/widgets/{expected_widget_id}"):
        failures.append("openbb widget payload must expose audited_endpoint")
    if not isinstance(payload.get("data"), list):
        failures.append("openbb widget payload data must be a list")
    observability = payload.get("observability")
    if not isinstance(observability, dict) or observability.get("adapter") != "openbb_widget":
        failures.append("openbb widget payload must include openbb_widget observability")
    return failures


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate Quant Team OS full-stack readiness.")
    parser.add_argument("--env", default=".env", help="Path to .env file to check.")
    parser.add_argument("--template-ok", action="store_true", help="Allow blank manual values when checking .env.example.")
    parser.add_argument("--live", action="store_true", help="Check local HTTP endpoints after docker compose is running.")
    parser.add_argument("--require-external-providers", action="store_true", help="Also require external provider API secret refs to be readable in Infisical.")
    parser.add_argument("--timeout", type=float, default=2.0, help="Per-endpoint timeout for --live checks.")
    args = parser.parse_args()

    env_path = Path(args.env)
    if not env_path.is_absolute():
        env_path = ROOT / env_path

    failures: list[str] = []
    warnings: list[str] = []
    try:
        values = parse_env(env_path)
    except FileNotFoundError:
        return fail([f"{env_path} is missing; run `cp .env.example .env` first"])

    if shutil.which("docker") is None and not args.live:
        warnings.append("docker CLI not found; install Docker before running the full stack")
    failures.extend(static_failures(values, template_ok=args.template_ok))
    if args.live:
        compose = compose_failures(env_path)
        failures.extend(compose)
        compose_blocked = any(
            marker in failure
            for failure in compose
            for marker in ["timed out", "stuck in Created", "has no running Quant Team OS services"]
        )
        if not compose_blocked:
            failures.extend(live_failures(values, args.timeout, require_external_providers=args.require_external_providers))

    if failures:
        return fail(failures, warnings)
    for item in warnings:
        print(f"warning: {item}")
    print("full stack doctor passed")
    return 0


def fail(failures: list[str], warnings: list[str] | None = None) -> int:
    for item in warnings or []:
        print(f"warning: {item}")
    print("full stack doctor failed:")
    for item in failures:
        print(f"- {item}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
