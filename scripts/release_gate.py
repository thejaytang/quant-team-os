from __future__ import annotations

import configparser
import json
import re
import subprocess
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    checks = [
        check_requirements,
        check_compose_services,
        check_policy_bundle,
        check_api_surface,
        check_worker_chain,
        check_control_ui,
        check_agent_chat,
        check_data_contracts,
        check_dependency_contracts,
        check_readme_docs,
        check_full_stack_doctor,
        check_ci_contract,
    ]
    failures = [message for check in checks for message in check()]
    if failures:
        raise SystemExit("release gate failed:\n" + "\n".join(f"- {item}" for item in failures))
    print("release gate passed")


def check_requirements() -> list[str]:
    failures: list[str] = []
    if not (ROOT / "docs/requirements/quant_team_os_requirements_v0_3.md").exists():
        failures.append("v0.3 requirements document is missing")
    for doc in [
        "architecture.md",
        "agent_policy.md",
        "connector_policy.md",
        "workflow_design.md",
        "risk_and_approval.md",
        "ui_architecture.md",
        "strategy_card_template.md",
    ]:
        if not (ROOT / "docs" / doc).exists():
            failures.append(f"delivery doc is missing: docs/{doc}")
    if (ROOT / "apps/web").exists():
        failures.append("legacy apps/web must not exist")
    if (ROOT / "infra/prefect").exists():
        failures.append("legacy infra/prefect must not exist")
    env_example = (ROOT / ".env.example").read_text(encoding="utf-8")
    for required in [
        "KEYCLOAK_BASE_URL=http://localhost:8080",
        "KEYCLOAK_INTERNAL_BASE_URL=http://keycloak:8080",
        "KEYCLOAK_JWKS_URL=http://keycloak:8080/realms/quant-team-os/protocol/openid-connect/certs",
        "KEYCLOAK_SMOKE_CLIENT_ID=openbb-backend",
        "KEYCLOAK_SMOKE_CLIENT_SECRET=openbb-backend-local-secret",
        "OPENBB_KEYCLOAK_CLIENT_SECRET_REF=/quant-team-os/dev/keycloak/openbb-backend-client-secret",
        "OPENBB_INTERNAL_TOKEN=change-me-openbb-internal-token",
        "VITE_KEYCLOAK_CLIENT_ID=control-ui",
        "CHAINLIT_AUTH_SECRET=change-me-chainlit-auth-secret",
        "OAUTH_GENERIC_NAME=keycloak",
        "OAUTH_GENERIC_CLIENT_ID=chainlit",
        "OAUTH_GENERIC_CLIENT_SECRET=chainlit-local-secret",
        "OAUTH_GENERIC_AUTH_URL=http://localhost:8080/realms/quant-team-os/protocol/openid-connect/auth",
        "OAUTH_GENERIC_TOKEN_URL=http://keycloak:8080/realms/quant-team-os/protocol/openid-connect/token",
        "OAUTH_GENERIC_USER_INFO_URL=http://keycloak:8080/realms/quant-team-os/protocol/openid-connect/userinfo",
        "OAUTH_GENERIC_SCOPES=openid profile email",
        "ENABLE_MINIO_UPLOAD=true",
        "OPA_PUBLIC_URL=http://localhost:8181",
        "AWS_ACCESS_KEY_ID=minioadmin",
        "OTEL_EXPORTER_OTLP_ENDPOINT=http://otel-collector:4317",
        "MLFLOW_TRACKING_URI=http://mlflow:5000",
        "MLFLOW_HOST_PORT=5000",
        "MLFLOW_UI_URL=http://localhost:5000",
        "MLFLOW_S3_ENDPOINT_URL=http://minio:9000",
        "LANGFUSE_UI_URL=http://localhost:3002",
        "INFISICAL_UI_URL=http://localhost:8082",
        "INFISICAL_ENCRYPTION_KEY=f13dbc92aaaf86fa7cb0ed8ac3265f47",
        "INFISICAL_AUTH_SECRET=5lrMXKKWCVocS/uerPsl7V+TX/aaUaI7iDkgl3tSmLE=",
        "OPENBB_WORKSPACE_URL=https://pro.openbb.co",
        "VITE_OPENBB_WORKSPACE_URL=https://pro.openbb.co",
        "VITE_OPENBB_BACKEND_URL=http://localhost:8010",
        "SUPERSET_ADMIN_USERNAME=admin",
        "SUPERSET_ADMIN_PASSWORD=admin",
        "MLFLOW_EXPERIMENT_NAME=quant-team-os",
        "GRAFANA_USERNAME=admin",
        "GRAFANA_PASSWORD=admin",
        "ALLOW_LOCAL_SECRET_FALLBACK=false",
        "ALLOW_LOCAL_AUTH_FALLBACK=false",
        "ALLOW_TEMPORAL_FALLBACK=false",
        "ALLOW_LOCAL_POLICY_FALLBACK=false",
        "ALLOW_AGENT_FALLBACK=false",
        "ALLOW_MATURE_TOOL_FALLBACK=false",
        "OPENAI_API_KEY_REF=/quant-team-os/dev/connections/openai",
        "MASSIVE_API_KEY_REF=/quant-team-os/dev/connections/massive",
        "QUANTCONNECT_API_TOKEN_REF=/quant-team-os/dev/connections/quantconnect",
    ]:
        if required not in env_example:
            failures.append(f".env.example missing: {required}")
    for forbidden in ["OPENAI_API_KEY=", "MASSIVE_API_KEY=", "QUANTCONNECT_API_TOKEN="]:
        if forbidden in env_example:
            failures.append(f".env.example must not expose raw provider secret env: {forbidden}")
    return failures


def check_compose_services() -> list[str]:
    compose = yaml.safe_load((ROOT / "infra/docker-compose.yml").read_text(encoding="utf-8"))
    services = compose.get("services", {})
    required = {
        "postgres",
        "keycloak",
        "redis",
        "infisical",
        "temporal",
        "temporal-ui",
        "opa",
        "minio",
        "minio-init",
        "mlflow",
        "langfuse",
        "otel-collector",
        "prometheus",
        "postgres-exporter",
        "loki",
        "promtail",
        "grafana",
        "superset",
        "superset-init",
        "jupyterlab",
        "api",
        "workers",
        "control-ui",
        "agent-chat",
        "openbb-backend",
    }
    failures = [f"docker-compose missing service: {name}" for name in sorted(required - set(services))]
    for name, service in services.items():
        image = str(service.get("image", ""))
        if image.endswith(":latest") or ":latest-" in image:
            failures.append(f"docker-compose service must pin non-latest image tag: {name} -> {image}")
    postgres_init = ROOT / "infra/postgres/init-databases.sql"
    if not postgres_init.exists():
        failures.append("Postgres mature-tool database init script is missing")
    else:
        init_text = postgres_init.read_text(encoding="utf-8")
        for database in ["qto_infisical", "qto_mlflow", "qto_langfuse", "qto_temporal", "qto_temporal_visibility", "qto_superset"]:
            if f"CREATE DATABASE {database}" not in init_text:
                failures.append(f"Postgres init must create isolated mature-tool database: {database}")
        for role in ["qto_app", "qto_infisical", "qto_mlflow", "qto_langfuse", "qto_temporal", "qto_superset", "qto_monitor"]:
            if f"CREATE ROLE {role}" not in init_text:
                failures.append(f"Postgres init must create isolated database role: {role}")
        if "ALTER DATABASE quant_team_os OWNER TO qto_app" not in init_text:
            failures.append("Postgres init must assign quant_team_os to qto_app")
    if "./postgres/init-databases.sql:/docker-entrypoint-initdb.d/10-init-qto-databases.sql:ro" not in services.get("postgres", {}).get("volumes", []):
        failures.append("postgres service must mount isolated mature-tool database init script")
    for service, marker in {
        "infisical": "qto_infisical",
        "langfuse": "qto_langfuse",
        "superset": "qto_superset",
        "superset-init": "qto_superset",
    }.items():
        if marker not in json.dumps(services.get(service, {}).get("environment", {})):
            failures.append(f"{service} must use isolated database {marker}")
    infisical_env = services.get("infisical", {}).get("environment", {})
    for key in ["DB_CONNECTION_URI", "REDIS_URL", "ENCRYPTION_KEY", "AUTH_SECRET", "SITE_URL"]:
        if key not in infisical_env:
            failures.append(f"infisical service missing official env: {key}")
    if "INFISICAL_DB_CONNECTION_URI" in infisical_env:
        failures.append("infisical service must use official DB_CONNECTION_URI, not INFISICAL_DB_CONNECTION_URI")
    if infisical_env.get("REDIS_URL") != "redis://redis:6379":
        failures.append("infisical service must use redis://redis:6379")
    if "qto_mlflow" not in str(services.get("mlflow", {}).get("command", "")):
        failures.append("mlflow must use isolated database qto_mlflow")
    temporal_env = services.get("temporal", {}).get("environment", {})
    if temporal_env.get("POSTGRES_USER") != "qto_temporal" or temporal_env.get("POSTGRES_PWD") != "qto_temporal":
        failures.append("temporal must use qto_temporal database role")
    if temporal_env.get("DBNAME") != "qto_temporal" or temporal_env.get("VISIBILITY_DBNAME") != "qto_temporal_visibility":
        failures.append("temporal must use isolated Temporal databases")
    for service in ["api", "workers"]:
        database_url = services.get(service, {}).get("environment", {}).get("DATABASE_URL", "")
        if "qto_app:qto_app" not in database_url:
            failures.append(f"{service} must use qto_app database role")
    if "qto_monitor:qto_monitor" not in services.get("postgres-exporter", {}).get("environment", {}).get("DATA_SOURCE_NAME", ""):
        failures.append("postgres-exporter must use qto_monitor database role")
    for rendered in json.dumps(services).split():
        if "postgres:postgres@postgres" in rendered:
            failures.append("runtime services must not use postgres superuser connection strings")
            break
    for name in ["postgres", "keycloak", "redis", "infisical", "temporal", "opa", "minio", "loki", "otel-collector", "prometheus", "promtail", "api"]:
        if not services.get(name, {}).get("healthcheck"):
            failures.append(f"docker-compose service must define healthcheck: {name}")
    for name in ["mlflow", "langfuse", "grafana", "superset", "jupyterlab", "workers", "control-ui", "agent-chat", "openbb-backend"]:
        if not services.get(name, {}).get("healthcheck"):
            failures.append(f"docker-compose mature app service must define healthcheck: {name}")
    for service, dependency, condition in [
        ("infisical", "postgres", "service_healthy"),
        ("infisical", "redis", "service_healthy"),
        ("temporal", "postgres", "service_healthy"),
        ("temporal-ui", "temporal", "service_healthy"),
        ("minio-init", "minio", "service_healthy"),
        ("mlflow", "postgres", "service_healthy"),
        ("mlflow", "minio-init", "service_completed_successfully"),
        ("langfuse", "postgres", "service_healthy"),
        ("otel-collector", "loki", "service_healthy"),
        ("postgres-exporter", "postgres", "service_healthy"),
        ("promtail", "loki", "service_healthy"),
        ("grafana", "prometheus", "service_healthy"),
        ("grafana", "loki", "service_healthy"),
        ("grafana", "promtail", "service_healthy"),
        ("superset-init", "postgres", "service_healthy"),
        ("superset", "postgres", "service_healthy"),
        ("superset", "superset-init", "service_completed_successfully"),
        ("api", "postgres", "service_healthy"),
        ("api", "keycloak", "service_healthy"),
        ("api", "infisical", "service_healthy"),
        ("api", "temporal", "service_healthy"),
        ("api", "opa", "service_healthy"),
        ("api", "minio-init", "service_completed_successfully"),
        ("api", "otel-collector", "service_healthy"),
        ("workers", "api", "service_healthy"),
        ("workers", "postgres", "service_healthy"),
        ("workers", "temporal", "service_healthy"),
        ("workers", "opa", "service_healthy"),
        ("workers", "infisical", "service_healthy"),
        ("workers", "minio-init", "service_completed_successfully"),
        ("workers", "otel-collector", "service_healthy"),
        ("control-ui", "api", "service_healthy"),
        ("control-ui", "keycloak", "service_healthy"),
        ("agent-chat", "api", "service_healthy"),
        ("agent-chat", "keycloak", "service_healthy"),
        ("openbb-backend", "api", "service_healthy"),
        ("openbb-backend", "otel-collector", "service_healthy"),
    ]:
        if _depends_condition(services, service, dependency) != condition:
            failures.append(f"{service} must wait for {dependency} with condition {condition}")
    api_env = services.get("api", {}).get("environment", {})
    if api_env.get("ALLOW_LIVE_TRADING") != "false":
        failures.append("api service must keep ALLOW_LIVE_TRADING=false")
    if api_env.get("ALLOW_LOCAL_AUTH_FALLBACK") != "false":
        failures.append("api service must disable local auth fallback in compose")
    if api_env.get("ALLOW_TEMPORAL_FALLBACK") != "false":
        failures.append("api service must disable Temporal fallback in compose")
    if api_env.get("ALLOW_LOCAL_POLICY_FALLBACK") != "false":
        failures.append("api service must disable local OPA policy fallback in compose")
    if api_env.get("ALLOW_LOCAL_SECRET_FALLBACK") != "false":
        failures.append("api service must disable local secret fallback in compose")
    if api_env.get("ENABLE_MINIO_UPLOAD") != "true":
        failures.append("api service must enable MinIO upload in compose")
    if api_env.get("ALLOW_AGENT_FALLBACK") != "false":
        failures.append("api service must disable agent fallback in compose")
    if api_env.get("ALLOW_MATURE_TOOL_FALLBACK") != "false":
        failures.append("api service must disable mature tool fallback in compose")
    if api_env.get("OTEL_EXPORTER_OTLP_ENDPOINT") != "http://otel-collector:4317":
        failures.append("api service must export OTLP spans to otel-collector")
    for key, value in {
        "KEYCLOAK_CLIENT_SECRET_REF": "${KEYCLOAK_CLIENT_SECRET_REF:-/quant-team-os/dev/keycloak/api-client-secret}",
        "OPENBB_KEYCLOAK_CLIENT_SECRET_REF": "${OPENBB_KEYCLOAK_CLIENT_SECRET_REF:-/quant-team-os/dev/keycloak/openbb-backend-client-secret}",
        "OPENBB_INTERNAL_TOKEN": "${OPENBB_INTERNAL_TOKEN:-change-me-openbb-internal-token}",
        "TEMPORAL_NAMESPACE": "${TEMPORAL_NAMESPACE:-default}",
        "MLFLOW_TRACKING_URI": "http://mlflow:5000",
        "MLFLOW_EXPERIMENT_NAME": "${MLFLOW_EXPERIMENT_NAME:-quant-team-os}",
        "MLFLOW_S3_ENDPOINT_URL": "http://minio:9000",
        "LANGFUSE_HOST": "http://langfuse:3000",
        "LANGFUSE_PUBLIC_KEY_REF": "${LANGFUSE_PUBLIC_KEY_REF:-/quant-team-os/dev/langfuse/public-key}",
        "LANGFUSE_SECRET_KEY_REF": "${LANGFUSE_SECRET_KEY_REF:-/quant-team-os/dev/langfuse/secret-key}",
        "OPENAI_API_KEY_REF": "${OPENAI_API_KEY_REF:-/quant-team-os/dev/connections/openai}",
        "MASSIVE_API_KEY_REF": "${MASSIVE_API_KEY_REF:-/quant-team-os/dev/connections/massive}",
        "QUANTCONNECT_API_TOKEN_REF": "${QUANTCONNECT_API_TOKEN_REF:-/quant-team-os/dev/connections/quantconnect}",
    }.items():
        if api_env.get(key) != value:
            failures.append(f"api service env {key} must be {value}")
    for key, value in {
        "MLFLOW_UI_URL": "${MLFLOW_UI_URL:-http://localhost:5000}",
        "LANGFUSE_UI_URL": "http://localhost:3002",
        "INFISICAL_UI_URL": "http://localhost:8082",
    }.items():
        if api_env.get(key) != value:
            failures.append(f"api service missing browser UI URL: {key}")
    for key in [
        "INFISICAL_API_URL",
        "INFISICAL_PROJECT_ID",
        "INFISICAL_MACHINE_IDENTITY_CLIENT_ID",
        "INFISICAL_MACHINE_IDENTITY_CLIENT_SECRET",
    ]:
        if key not in api_env:
            failures.append(f"api service missing Infisical machine identity env: {key}")
    worker_env = services.get("workers", {}).get("environment", {})
    for key in [
        "INFISICAL_API_URL",
        "INFISICAL_PROJECT_ID",
        "INFISICAL_MACHINE_IDENTITY_CLIENT_ID",
        "INFISICAL_MACHINE_IDENTITY_CLIENT_SECRET",
    ]:
        if key not in worker_env:
            failures.append(f"workers service missing Infisical machine identity env: {key}")
    for key, value in {
        "S3_ENDPOINT_URL": "http://minio:9000",
        "S3_BUCKET_ARTIFACTS": "qto-artifacts",
        "S3_BUCKET_DATASETS": "qto-datasets",
        "S3_BUCKET_MLFLOW": "qto-mlflow",
        "S3_BUCKET_REPORTS": "qto-reports",
        "S3_BUCKET_DVC": "qto-dvc",
        "AWS_ACCESS_KEY_ID": "minioadmin",
        "AWS_SECRET_ACCESS_KEY": "minioadmin",
        "ENABLE_MINIO_UPLOAD": "true",
        "ALLOW_AGENT_FALLBACK": "false",
        "ALLOW_MATURE_TOOL_FALLBACK": "false",
    }.items():
        if worker_env.get(key) != value:
            failures.append(f"workers service env {key} must be {value}")
    if "minio-init" not in services.get("workers", {}).get("depends_on", []):
        failures.append("workers service must depend on minio-init for DVC/MinIO access")
    if worker_env.get("ALLOW_LOCAL_SECRET_FALLBACK") != "false":
        failures.append("workers service must disable local secret fallback in compose")
    if worker_env.get("OTEL_EXPORTER_OTLP_ENDPOINT") != "http://otel-collector:4317":
        failures.append("workers service must export OTLP spans to otel-collector")
    for key, value in {
        "TEMPORAL_NAMESPACE": "${TEMPORAL_NAMESPACE:-default}",
        "MLFLOW_TRACKING_URI": "http://mlflow:5000",
        "MLFLOW_EXPERIMENT_NAME": "${MLFLOW_EXPERIMENT_NAME:-quant-team-os}",
        "MLFLOW_S3_ENDPOINT_URL": "http://minio:9000",
        "LANGFUSE_HOST": "http://langfuse:3000",
        "LANGFUSE_PUBLIC_KEY_REF": "${LANGFUSE_PUBLIC_KEY_REF:-/quant-team-os/dev/langfuse/public-key}",
        "LANGFUSE_SECRET_KEY_REF": "${LANGFUSE_SECRET_KEY_REF:-/quant-team-os/dev/langfuse/secret-key}",
    }.items():
        if worker_env.get(key) != value:
            failures.append(f"workers service env {key} must be {value}")
    otel_service = services.get("otel-collector", {})
    if "./otel-collector/config.yml:/etc/otel-collector/config.yml:ro" not in otel_service.get("volumes", []):
        failures.append("otel-collector must mount infra/otel-collector/config.yml")
    if not (ROOT / "infra/otel-collector/config.yml").exists():
        failures.append("OpenTelemetry Collector config is missing")
    else:
        otel_config = yaml.safe_load((ROOT / "infra/otel-collector/config.yml").read_text(encoding="utf-8"))
        log_pipeline = otel_config.get("service", {}).get("pipelines", {}).get("logs", {})
        if "otlp" not in log_pipeline.get("receivers", []):
            failures.append("OpenTelemetry logs pipeline must receive OTLP logs")
        if "otlphttp/loki" not in log_pipeline.get("exporters", []):
            failures.append("OpenTelemetry logs pipeline must export to Loki")
        if otel_config.get("exporters", {}).get("otlphttp/loki", {}).get("endpoint") != "http://loki:3100/otlp":
            failures.append("OpenTelemetry Loki exporter must target Loki OTLP endpoint")
        if "loki" not in otel_service.get("depends_on", []):
            failures.append("otel-collector must depend on loki for log export")
    prometheus = (ROOT / "infra/prometheus/prometheus.yml").read_text(encoding="utf-8")
    if "otel-collector:8889" not in prometheus:
        failures.append("Prometheus must scrape otel-collector exported metrics")
    if "workers:9002" not in prometheus:
        failures.append("Prometheus must scrape workers metrics")
    if "temporal:9091" not in prometheus:
        failures.append("Prometheus must scrape Temporal Prometheus metrics")
    if "postgres-exporter:9187" not in prometheus:
        failures.append("Prometheus must scrape postgres exporter")
    if services.get("workers", {}).get("environment", {}).get("WORKER_METRICS_PORT") != "9002":
        failures.append("workers service must expose WORKER_METRICS_PORT=9002")
    if "9002:9002" not in services.get("workers", {}).get("ports", []):
        failures.append("workers service must publish metrics port 9002")
    if temporal_env.get("PROMETHEUS_ENDPOINT") != "0.0.0.0:9091":
        failures.append("temporal service must expose PROMETHEUS_ENDPOINT=0.0.0.0:9091")
    if "9091:9091" not in services.get("temporal", {}).get("ports", []):
        failures.append("temporal service must publish metrics port 9091")
    if services.get("postgres-exporter", {}).get("environment", {}).get("DATA_SOURCE_NAME") is None:
        failures.append("postgres-exporter must define DATA_SOURCE_NAME")
    if services.get("minio", {}).get("environment", {}).get("MINIO_PROMETHEUS_AUTH_TYPE") != "public":
        failures.append("minio service must expose public Prometheus metrics for local stack")
    promtail_config = ROOT / "infra/promtail/config.yml"
    if not promtail_config.exists():
        failures.append("Promtail config is missing")
    else:
        promtail_text = promtail_config.read_text(encoding="utf-8")
        for required in ["http://loki:3100/loki/api/v1/push", "docker_sd_configs", "/var/lib/docker/containers/$1/$1-json.log"]:
            if required not in promtail_text:
                failures.append(f"Promtail config missing: {required}")
    promtail_service = services.get("promtail", {})
    if "./promtail/config.yml:/etc/promtail/config.yml:ro" not in promtail_service.get("volumes", []):
        failures.append("promtail must mount infra/promtail/config.yml")
    if "/var/run/docker.sock:/var/run/docker.sock:ro" not in promtail_service.get("volumes", []):
        failures.append("promtail must read docker metadata")
    grafana_datasources = ROOT / "infra/grafana/provisioning/datasources/datasources.yml"
    if not grafana_datasources.exists():
        failures.append("Grafana datasource provisioning is missing")
    else:
        datasource_text = grafana_datasources.read_text(encoding="utf-8")
        for required in ["http://prometheus:9090", "http://loki:3100"]:
            if required not in datasource_text:
                failures.append(f"Grafana datasource missing: {required}")
    grafana_dashboard = json.loads((ROOT / "infra/grafana/dashboards/trading-safety-lock.json").read_text(encoding="utf-8"))
    dashboard_exprs = {
        target.get("expr")
        for panel in grafana_dashboard.get("panels", [])
        for target in panel.get("targets", [])
    }
    for required in ['up{job="api"}', 'up{job="opa"}', 'up{job="otel-collector"}', "qto_live_trading_locked"]:
        if required not in dashboard_exprs:
            failures.append(f"Grafana starter dashboard missing: {required}")
    if '{service=~"api|workers|agent-chat|openbb-backend|control-ui"}' not in dashboard_exprs:
        failures.append("Grafana starter dashboard missing Loki service logs panel")
    if "LOCKED" not in json.dumps(grafana_dashboard):
        failures.append("Grafana starter dashboard missing: LOCKED")
    dashboard_dir = ROOT / "infra/grafana/dashboards"
    required_dashboard_panels = {
        "Agent Runtime Monitoring",
        "Temporal Workflow Monitoring",
        "ToolGateway Policy Denials",
        "OpenAI API Cost and Error Rate",
        "Data Ingestion and GX Validation",
        "Backtest Runtime and Failure",
        "Connector Health",
        "Trading Safety Lock",
    }
    seen_panel_titles: set[str] = set()
    seen_dashboard_titles: set[str] = set()
    for dashboard_path in dashboard_dir.glob("*.json"):
        if " " in dashboard_path.name:
            failures.append(f"Grafana dashboard filename must not contain spaces: {dashboard_path.name}")
        dashboard = json.loads(dashboard_path.read_text(encoding="utf-8"))
        title = dashboard.get("title")
        if not title:
            failures.append(f"Grafana dashboard missing title: {dashboard_path.name}")
        elif title in seen_dashboard_titles:
            failures.append(f"Grafana dashboard title must be unique: {title}")
        else:
            seen_dashboard_titles.add(title)
        if not dashboard.get("uid"):
            failures.append(f"Grafana dashboard missing stable uid: {dashboard_path.name}")
        for panel in dashboard.get("panels", []):
            title = panel.get("title")
            if title:
                seen_panel_titles.add(title)
            if not panel.get("targets"):
                failures.append(f"Grafana panel missing targets: {dashboard_path.name}:{title or '<untitled>'}")
            for target in panel.get("targets", []):
                expr = target.get("expr")
                if not expr:
                    failures.append(f"Grafana target missing expr: {dashboard_path.name}:{title or '<untitled>'}")
                if expr == "vector(0)":
                    failures.append(f"Grafana target must use real metrics instead of vector(0): {dashboard_path.name}:{title or '<untitled>'}")
    for title in sorted(required_dashboard_panels - seen_panel_titles):
        failures.append(f"Grafana required dashboard panel missing: {title}")
    superset_service = services.get("superset", {})
    superset_init = services.get("superset-init", {})
    for name, service in {"superset": superset_service, "superset-init": superset_init}.items():
        if "./superset:/app/qto-superset:ro" not in service.get("volumes", []):
            failures.append(f"{name} must mount infra/superset starter assets")
        if "./superset:/app/superset:ro" in service.get("volumes", []):
            failures.append(f"{name} must not shadow the Superset Python package path")
        if service.get("environment", {}).get("QTO_ANALYTICS_SQLALCHEMY_URI") != "postgresql+psycopg2://qto_app:qto_app@postgres:5432/quant_team_os":
            failures.append(f"{name} must configure Superset analytics database URI")
    if _depends_condition(services, "superset-init", "api") != "service_healthy":
        failures.append("superset-init must wait for api health so domain schema exists")
    superset_init_path = ROOT / "infra/superset/init.sh"
    superset_seed_path = ROOT / "infra/superset/seed_dashboard.py"
    if not superset_init_path.exists():
        failures.append("Superset init script is missing")
    else:
        superset_init_text = superset_init_path.read_text(encoding="utf-8")
        for required in ["superset init", "python /app/qto-superset/seed_dashboard.py", "superset export-dashboards", "superset import-dashboards"]:
            if required not in superset_init_text:
                failures.append(f"superset-init script missing: {required}")
    if not superset_seed_path.exists():
        failures.append("Superset dashboard seed script is missing")
    else:
        superset_seed_text = superset_seed_path.read_text(encoding="utf-8")
        for required in ["Strategy and Backtest Aggregate", "Database", "SqlaTable", "Slice", "Dashboard", "strategy_cards", "backtest_runs", "risk_reviews", "factor_specs"]:
            if required not in superset_seed_text:
                failures.append(f"Superset dashboard seed missing: {required}")
        if "postgres:postgres@postgres" in superset_seed_text:
            failures.append("Superset dashboard seed must not fall back to postgres superuser")
        if "qto_app:qto_app@postgres" not in superset_seed_text:
            failures.append("Superset dashboard seed fallback must use qto_app role")
    superset_dashboard_path = ROOT / "infra/superset/dashboards/strategy_backtest_aggregate.json"
    if not superset_dashboard_path.exists():
        failures.append("Superset starter dashboard spec is missing")
    else:
        superset_dashboard = json.loads(superset_dashboard_path.read_text(encoding="utf-8"))
        if superset_dashboard.get("dashboard_title") != "Strategy and Backtest Aggregate":
            failures.append("Superset starter dashboard has wrong title")
        chart_names = {chart.get("name") for chart in superset_dashboard.get("charts", [])}
        for required in ["Strategies by Status", "Backtest Runs by Status", "Risk Review Verdicts", "Factor Specs by Status"]:
            if required not in chart_names:
                failures.append(f"Superset starter dashboard missing chart: {required}")
        rendered_superset = json.dumps(superset_dashboard)
        if "strategy_cards group by status" in rendered_superset or "current_status" not in rendered_superset:
            failures.append("Superset strategy dashboard must query strategy_cards.current_status")
    strategy_lifecycle = (ROOT / "policy/opa/strategy_lifecycle.rego").read_text(encoding="utf-8")
    agent_policy = (ROOT / "policy/opa/agent.rego").read_text(encoding="utf-8")
    local_policy = (ROOT / "apps/api/app/services/policy.py").read_text(encoding="utf-8")
    policy_tests = (ROOT / "policy/tests/qto_policy_test.rego").read_text(encoding="utf-8")
    if 'input.action == "register_strategy"' not in strategy_lifecycle or '"latest risk review must pass"' not in strategy_lifecycle:
        failures.append("strategy_lifecycle OPA policy must deny register_strategy when latest risk review fails")
    for required in ['"approved approval is required"', 'input.approval.status != "approved"']:
        if required not in strategy_lifecycle:
            failures.append(f"strategy_lifecycle OPA policy missing: {required}")
    for required in ['"agent action must be tool_call"', 'input.action != "tool_call"']:
        if required not in agent_policy:
            failures.append(f"agent OPA policy missing: {required}")
    for required in ['"approved approval is required"', '"agent action must be tool_call"']:
        if required not in local_policy:
            failures.append(f"local policy fallback missing: {required}")
    if "test_strategy_registration_requires_latest_risk_pass" not in policy_tests:
        failures.append("OPA tests must cover register_strategy latest risk review denial")
    for required in ["test_strategy_registration_requires_approved_request", "test_paper_promotion_requires_approved_request", "test_agent_action_must_be_tool_call"]:
        if required not in policy_tests:
            failures.append(f"OPA tests missing: {required}")
    for bucket_env, bucket in {
        "S3_BUCKET_ARTIFACTS": "qto-artifacts",
        "S3_BUCKET_DATASETS": "qto-datasets",
        "S3_BUCKET_MLFLOW": "qto-mlflow",
        "S3_BUCKET_REPORTS": "qto-reports",
        "S3_BUCKET_DVC": "qto-dvc",
    }.items():
        if api_env.get(bucket_env) != bucket:
            failures.append(f"api service missing bucket env: {bucket_env}")
    if api_env.get("KEYCLOAK_BASE_URL") != "http://localhost:8080":
        failures.append("api service must validate the browser-visible Keycloak issuer")
    if api_env.get("KEYCLOAK_INTERNAL_BASE_URL") != "http://keycloak:8080":
        failures.append("api service must accept the container-internal Keycloak issuer for service accounts")
    if api_env.get("KEYCLOAK_JWKS_URL") != "http://keycloak:8080/realms/quant-team-os/protocol/openid-connect/certs":
        failures.append("api service must fetch Keycloak JWKS over the internal container URL")
    if api_env.get("KEYCLOAK_REALM") != "quant-team-os" or api_env.get("KEYCLOAK_CLIENT_ID") != "api":
        failures.append("api service must declare Keycloak realm and api audience")
    control_env = services.get("control-ui", {}).get("environment", {})
    if control_env.get("VITE_KEYCLOAK_BASE_URL") != "http://localhost:8080":
        failures.append("control-ui must receive VITE_KEYCLOAK_BASE_URL")
    if control_env.get("VITE_KEYCLOAK_REALM") != "quant-team-os" or control_env.get("VITE_KEYCLOAK_CLIENT_ID") != "control-ui":
        failures.append("control-ui must receive Keycloak realm and control-ui client id")
    if control_env.get("VITE_OPENBB_WORKSPACE_URL") != "https://pro.openbb.co" or control_env.get("VITE_OPENBB_BACKEND_URL") != "http://localhost:8010":
        failures.append("control-ui must distinguish OpenBB Workspace UI from the widget backend")
    agent_chat_env = services.get("agent-chat", {}).get("environment", {})
    if agent_chat_env.get("QTO_API_URL") != "http://api:8000":
        failures.append("agent-chat must point to QTO_API_URL=http://api:8000")
    for key, value in {
        "CHAINLIT_URL": "http://localhost:8001",
        "CHAINLIT_AUTH_SECRET": "${CHAINLIT_AUTH_SECRET:-change-me-chainlit-auth-secret}",
        "OAUTH_GENERIC_NAME": "keycloak",
        "OAUTH_GENERIC_CLIENT_ID": "chainlit",
        "OAUTH_GENERIC_AUTH_URL": "http://localhost:8080/realms/quant-team-os/protocol/openid-connect/auth",
        "OAUTH_GENERIC_TOKEN_URL": "http://keycloak:8080/realms/quant-team-os/protocol/openid-connect/token",
        "OAUTH_GENERIC_USER_INFO_URL": "http://keycloak:8080/realms/quant-team-os/protocol/openid-connect/userinfo",
        "OAUTH_GENERIC_SCOPES": "openid profile email",
    }.items():
        if agent_chat_env.get(key) != value:
            failures.append(f"agent-chat missing Keycloak OAuth env: {key}")
    if "OAUTH_GENERIC_CLIENT_SECRET" not in agent_chat_env:
        failures.append("agent-chat missing Keycloak OAuth client secret env")
    if "keycloak" not in services.get("agent-chat", {}).get("depends_on", []):
        failures.append("agent-chat must depend on keycloak for OAuth")
    openbb_env = services.get("openbb-backend", {}).get("environment", {})
    if openbb_env.get("API_BASE_URL") != "http://api:8000":
        failures.append("openbb-backend must point to API_BASE_URL=http://api:8000")
    if openbb_env.get("OTEL_EXPORTER_OTLP_ENDPOINT") != "http://otel-collector:4317":
        failures.append("openbb-backend must export OTLP spans to otel-collector")
    if openbb_env.get("OTEL_SERVICE_NAME") != "quant-team-os-openbb-backend":
        failures.append("openbb-backend must declare OTEL_SERVICE_NAME")
    for key, value in {
        "OPENBB_INTERNAL_TOKEN": "${OPENBB_INTERNAL_TOKEN:-change-me-openbb-internal-token}",
    }.items():
        if openbb_env.get(key) != value:
            failures.append(f"openbb-backend missing internal FastAPI auth env: {key}")
    for forbidden in ["KEYCLOAK_TOKEN_URL", "KEYCLOAK_CLIENT_ID", "OPENBB_KEYCLOAK_CLIENT_SECRET_REF", "INFISICAL_API_URL", "INFISICAL_MACHINE_IDENTITY_CLIENT_ID", "INFISICAL_MACHINE_IDENTITY_CLIENT_SECRET", "KEYCLOAK_CLIENT_SECRET"]:
        if forbidden in openbb_env:
            failures.append(f"openbb-backend must not hold direct secret-fetch env: {forbidden}")
    openbb_depends_on = services.get("openbb-backend", {}).get("depends_on", [])
    if "api" not in openbb_depends_on or "otel-collector" not in openbb_depends_on:
        failures.append("openbb-backend must depend on api and otel-collector")
    minio_init = services.get("minio-init", {})
    entrypoint = str(minio_init.get("entrypoint", ""))
    for bucket in ["qto-artifacts", "qto-datasets", "qto-mlflow", "qto-reports", "qto-dvc"]:
        if bucket not in entrypoint:
            failures.append(f"minio-init must create bucket: {bucket}")
    return failures


def _depends_condition(services: dict, service: str, dependency: str) -> str | None:
    depends_on = services.get(service, {}).get("depends_on", {})
    if isinstance(depends_on, dict):
        value = depends_on.get(dependency)
        return value.get("condition") if isinstance(value, dict) else None
    if isinstance(depends_on, list) and dependency in depends_on:
        return "service_started"
    return None


def check_policy_bundle() -> list[str]:
    failures: list[str] = []
    for name in ["agent", "approval", "connector", "risk_gate", "strategy_lifecycle", "trading_lock", "ui_surface"]:
        path = ROOT / f"policy/opa/{name}.rego"
        if not path.exists():
            failures.append(f"OPA policy missing: {name}")
            continue
        text = path.read_text(encoding="utf-8")
        if f"package qto.{name}" not in text:
            failures.append(f"OPA policy has wrong package: {name}")
        if name == "agent" and "default allow = false" not in text:
            failures.append("agent OPA policy must default deny")
        if name == "agent":
            for required in ["allowed_tools", "agent_tool_allowed", '"BacktestAgent"', '"quantconnect_mcp"', '"ExecutionAgent"', '"quantconnect_paper"', '"agent is not allowed to call this tool"']:
                if required not in text:
                    failures.append(f"agent OPA policy must enforce agent-tool matrix: {required}")
        if name == "connector":
            for required in ["ref_requested", "trusted_secret_ref_actor", "client_secret", "access_token", '"LangfuseService"', '"openbb-backend"', '"secret refs must be resolved by trusted service adapters"']:
                if required not in text:
                    failures.append(f"connector OPA policy must reject untrusted secret refs: {required}")
        if name == "approval":
            for required in ['input.request_type == "unlock_live"', '"Live trading is locked by OPA"']:
                if required not in text:
                    failures.append(f"approval OPA policy must deny live unlock approvals: {required}")
            if "count(deny) == 0" not in text:
                failures.append("approval OPA policy allow must be false when deny is present")
    service = (ROOT / "apps/api/app/services/policy.py").read_text(encoding="utf-8")
    if "/v1/data/qto/{policy_package}" not in service:
        failures.append("policy service must call OPA qto package path")
    if "write_audit_log" not in service or "policy_decision." not in service:
        failures.append("policy decisions must be visible in AuditLog")
    if '"Live trading is locked by OPA"' not in service or '"unlock_live"' not in service:
        failures.append("local policy fallback must mirror OPA live unlock approval denial")
    for required in ["AGENT_TOOL_ALLOWLIST", "TRUSTED_SECRET_REF_ACTORS", "SECRET_PAYLOAD_KEYS", '"client_secret"', '"agent is not allowed to call this tool"', '"secret refs must be resolved by trusted service adapters"']:
        if required not in service:
            failures.append(f"local policy fallback must enforce ToolGateway safety contract: {required}")
    gateway = (ROOT / "apps/api/app/adapters/base.py").read_text(encoding="utf-8")
    for required in ['"tool": {', '"requested_permission": adapter.risk_level', '"ref_requested": _secret_ref_requested(payload)']:
        if required not in gateway:
            failures.append(f"ToolGateway policy input missing safety metadata: {required}")
    live_idx = gateway.find('evaluate_policy(db, "trading_lock", "live_order"')
    agent_idx = gateway.find('evaluate_policy(db, "agent", adapter.name')
    if live_idx == -1 or agent_idx == -1 or live_idx > agent_idx:
        failures.append("ToolGateway live_trade adapters must hit trading_lock/live_order before agent policy")
    if "class PolicyDenied" not in gateway or "raise PolicyDenied" not in gateway:
        failures.append("ToolGateway policy denial must raise PolicyDenied after writing audit")
    return failures


def check_api_surface() -> list[str]:
    required_files = [
        "routes_agent_runs.py",
        "routes_approvals.py",
        "routes_artifacts.py",
        "routes_audit.py",
        "routes_backtests.py",
        "routes_connections.py",
        "routes_data_quality.py",
        "routes_external_ui.py",
        "routes_factors.py",
        "routes_paper_trading.py",
        "routes_research.py",
        "routes_risk.py",
        "routes_settings.py",
        "routes_strategies.py",
        "routes_workflows.py",
    ]
    failures = [f"API route missing: {name}" for name in required_files if not (ROOT / "apps/api/app/api" / name).exists()]
    api_dockerfile = (ROOT / "apps/api/Dockerfile").read_text(encoding="utf-8")
    if api_dockerfile.find("COPY apps/api/app /app/app") > api_dockerfile.find("pip install --no-cache-dir -e ."):
        failures.append("api Dockerfile must copy app package before pip install -e .")
    migration = ROOT / "apps/api/app/db/migrations/versions/0001_initial.py"
    if not migration.exists():
        failures.append("Alembic initial migration is missing")
    elif "Base.metadata.create_all" not in migration.read_text(encoding="utf-8"):
        failures.append("Alembic initial migration must create SQLAlchemy metadata")
    main = (ROOT / "apps/api/app/main.py").read_text(encoding="utf-8")
    if "dependencies=auth_dependencies" not in main:
        failures.append("API routers must include auth dependencies")
    if "routes_settings" not in main or "routes_settings.router" not in main:
        failures.append("API must expose read-only runtime settings")
    settings_route = (ROOT / "apps/api/app/api/routes_settings.py").read_text(encoding="utf-8")
    if "allow_mature_tool_fallback" not in settings_route:
        failures.append("runtime settings must expose mature tool fallback lock")
    settings_config = (ROOT / "apps/api/app/core/config.py").read_text(encoding="utf-8")
    if "allow_mature_tool_fallback: bool = False" not in settings_config:
        failures.append("mature tool fallback must default to false")
    if "validate_infisical_runtime_settings()" not in main:
        failures.append("API startup must validate Infisical machine identity when local secret fallback is disabled")
    if '"/metrics"' not in main or "qto_live_trading_locked" not in main:
        failures.append("API must expose Prometheus /metrics for runtime monitoring")
    for required in ['"/api/v1/healthz"', '"/api/v1/metrics"']:
        if required not in main:
            failures.append(f"API must expose /api/v1 probe alias: {required}")
    for metric in [
        "qto_tool_policy_denials_total",
        "qto_openai_cost_usd_total",
        "qto_openai_errors_total",
        "qto_workflow_runs_total",
        "qto_gx_validations_total",
        "qto_backtest_failures_total",
        "qto_connection_status",
    ]:
        if metric not in main:
            failures.append(f"API /metrics missing starter metric: {metric}")
    for required in ["counts = _metric_counts(db)", "PolicyDecision", "WorkflowLink", "Artifact", "BacktestRun", "ExternalConnection", "ToolCall", "_payload_cost_usd"]:
        if required not in main:
            failures.append(f"API /metrics must use live database-backed counts: {required}")
    for forbidden in ['"qto_openai_cost_usd_total 0"', '"qto_openai_errors_total 0"']:
        if forbidden in main:
            failures.append(f"API /metrics must not hard-code OpenAI metric: {forbidden}")
    artifacts = (ROOT / "apps/api/app/api/routes_artifacts.py").read_text(encoding="utf-8")
    if "/{artifact_id}/presigned-url" not in artifacts:
        failures.append("artifact presigned-url route is missing")
    artifact_service = (ROOT / "apps/api/app/services/artifacts.py").read_text(encoding="utf-8")
    if 'return {"storage_mode": "local_mirror", "minio_error"' in artifact_service:
        failures.append("MinIO-enabled artifact writes must not silently fall back to local_mirror")
    if "MinIO artifact upload failed" not in artifact_service:
        failures.append("MinIO-enabled artifact upload failures must be explicit")
    if "def _should_write_local_mirror" not in artifact_service or 'settings.app_env.lower() == "production"' not in artifact_service:
        failures.append("production MinIO artifact writes must not depend on a local artifact mirror")
    if '"local_mirror_written": local_mirror_written' not in artifact_service:
        failures.append("artifact metadata must record whether a local mirror was written")
    for required in ["_bucket_for_artifact", "s3_bucket_datasets", "s3_bucket_reports"]:
        if required not in artifact_service:
            failures.append(f"artifact service must route dataset/report artifacts to dedicated MinIO buckets: {required}")
    audit_routes = (ROOT / "apps/api/app/api/routes_audit.py").read_text(encoding="utf-8")
    for required in ["ApprovalRequest", "ApprovalRecord", "ToolCall", "PolicyDecision", "event_source", "_tool_call_event", "_policy_decision_event", "_approval_request_event"]:
        if required not in audit_routes:
            failures.append(f"Audit Log endpoint must aggregate tool calls, policy decisions, and approvals: {required}")
    for required in ['require_any_role("admin", "risk_reviewer")', "list_tool_calls", "list_policy_decisions", "list_system_events"]:
        if required not in audit_routes:
            failures.append(f"Audit and policy event routes must be restricted to admin/risk reviewer: {required}")
    backtests = (ROOT / "apps/api/app/api/routes_backtests.py").read_text(encoding="utf-8")
    if '"BacktestWorkflow"' not in backtests or "start_workflow" not in backtests:
        failures.append("backtest creation/rerun must start BacktestWorkflow")
    if 'status="completed"' in backtests or "manual-mvp-v1" in backtests:
        failures.append("backtest routes must not create completed manual runs")
    schemas = (ROOT / "apps/api/app/schemas.py").read_text(encoding="utf-8")
    if "class BacktestCreate" not in schemas or "dataset_version: str" not in schemas:
        failures.append("BacktestCreate must require dataset_version")
    if "run.dataset_version" not in backtests or '"dataset_version": run.dataset_version' not in backtests:
        failures.append("backtest rerun must preserve dataset_version")
    factors_route = (ROOT / "apps/api/app/api/routes_factors.py").read_text(encoding="utf-8")
    if '"FactorAnalysisWorkflow"' not in factors_route or "start_workflow" not in factors_route:
        failures.append("factor analysis routes must start FactorAnalysisWorkflow")
    if 'factor.status = "tested"' in factors_route:
        failures.append("factor analysis route must not directly mark factor tested")
    strategies_route = (ROOT / "apps/api/app/api/routes_strategies.py").read_text(encoding="utf-8")
    for required in ['"StrategyRegistrationWorkflow"', '"PaperPromotionWorkflow"', "start_workflow"]:
        if required not in strategies_route:
            failures.append(f"strategy lifecycle routes missing workflow boundary: {required}")
    if '"card"' not in strategies_route or "_model_dict(strategy)" not in strategies_route:
        failures.append("strategy list API must include StrategyCard lifecycle data")
    for forbidden in ["create_approval_request", "transition_strategy", 'strategy.status = "APPROVAL_PENDING"']:
        if forbidden in strategies_route:
            failures.append(f"strategy lifecycle routes must not directly mutate approval lifecycle: {forbidden}")
    paper_route = (ROOT / "apps/api/app/api/routes_paper_trading.py").read_text(encoding="utf-8")
    if 'transition_strategy(db, strategy, "PAPER_TRADING"' in paper_route:
        failures.append("paper trading session route must not directly set PAPER_TRADING")
    workflows_service = (ROOT / "apps/api/app/services/workflows.py").read_text(encoding="utf-8")
    if "run_stub_research_workflow" in workflows_service or "local_outputs" in workflows_service:
        failures.append("ResearchWorkflow must not create strategy/risk/approval outputs from local fallback")
    if 'meta={"input": redact_secrets(payload or {})}' not in workflows_service:
        failures.append("workflow links must persist redacted input metadata")
    temporal_client = (ROOT / "apps/api/app/services/temporal_client.py").read_text(encoding="utf-8")
    for required in ["cancel_temporal_workflow", "handle.cancel()", "workflow.cancel_requested", "workflow.cancel_fallback"]:
        if required not in temporal_client:
            failures.append(f"workflow cancel must call Temporal and audit the result: {required}")
    mlflow_tracking = ROOT / "apps/api/app/services/mlflow_tracking.py"
    if not mlflow_tracking.exists():
        failures.append("MLflow backtest tracking service is missing")
    else:
        mlflow_text = mlflow_tracking.read_text(encoding="utf-8")
        for required in ["import mlflow", "start_run", "log_params", "log_metrics", "log_artifact", "mlflow_run_id"]:
            if required not in mlflow_text:
                failures.append(f"MLflow tracking boundary missing: {required}")
        for required in ["strategy_id", "dataset_spec_id", "dataset_version", "workflow_id", "factor_id", "dvc_rev", "git_commit"]:
            if required not in mlflow_text:
                failures.append(f"MLflow tracking metadata missing: {required}")
    if (ROOT / "apps/api/app/workflows/research_workflow.py").exists():
        failures.append("legacy local research workflow fallback must not exist")
    approval_service = (ROOT / "apps/api/app/services/approval_service.py").read_text(encoding="utf-8")
    if "use_local_continuation" in approval_service or "local_fallback" in approval_service:
        failures.append("workflow-backed approvals must not continue locally when Temporal signal falls back")
    if approval_service.find("db.commit()") > approval_service.find("signal_approval_resolved(db"):
        failures.append("approval status/record must be committed before Temporal approval signal")
    agent_runs = (ROOT / "apps/api/app/api/routes_agent_runs.py").read_text(encoding="utf-8")
    if "/{run_id}/langfuse-link" not in agent_runs:
        failures.append("agent run Langfuse link route is missing")
    if "redact_secrets(payload.input_payload)" not in agent_runs:
        failures.append("agent run creation must persist redacted input payload")
    if "log_agent_run_to_langfuse" not in agent_runs or "langfuse_ui_url" not in agent_runs:
        failures.append("agent run API must create Langfuse trace and return browser UI URL")
    if agent_runs.find("log_agent_run_to_langfuse(db, run") < agent_runs.find("run.output_payload"):
        failures.append("agent run API must log Langfuse trace after output payload is populated")
    if "AgentMessage" not in agent_runs or "event: agent_step" not in agent_runs:
        failures.append("agent run events must expose agent step messages for Chainlit")
    for required in ["_start_agent_workflow", "start_workflow", "run.workflow_id", "temporal_workflow_started"]:
        if required not in agent_runs:
            failures.append(f"agent run API must link executable runs to Temporal workflows: {required}")
    if 'require_any_role("researcher", "risk_reviewer", "admin")' not in agent_runs:
        failures.append("agent run creation must reject viewer-only users")
    langfuse_tracking = ROOT / "apps/api/app/services/langfuse_tracking.py"
    if not langfuse_tracking.exists():
        failures.append("Langfuse tracking service is missing")
    else:
        langfuse_text = langfuse_tracking.read_text(encoding="utf-8")
        for required in [
            "redact_secrets",
            "langfuse_trace_id",
            "AdapterRunner",
            "default_registry",
            "ToolContext",
            "infisical_secret_refs",
            "langfuse_public_key_ref",
            "langfuse_secret_key_ref",
            "_trace_metadata",
            "token_usage",
            "cost",
            "latency",
            "prompt_name",
            "prompt_version",
            "policy_denials",
            "artifact_ids",
            "error = str(redact_secrets",
            "_strict_langfuse_mode",
            'settings.app_env.lower() == "production"',
            "not settings.allow_local_secret_fallback",
        ]:
            if required not in langfuse_text:
                failures.append(f"Langfuse tracking boundary missing: {required}")
        for forbidden in ["get_infisical_client", ".read_secret(", "from langfuse import Langfuse"]:
            if forbidden in langfuse_text:
                failures.append(f"Langfuse tracking service must delegate secrets and SDK calls to ToolGateway: {forbidden}")
        adapters = (ROOT / "apps/api/app/adapters/stubs.py").read_text(encoding="utf-8")
        for required in ["class LangfuseAdapter", "from langfuse import Langfuse", "client.trace", "client.flush", "public_key", "secret_key"]:
            if required not in adapters:
                failures.append(f"Langfuse adapter boundary missing: {required}")
    factors = (ROOT / "apps/api/app/api/routes_factors.py").read_text(encoding="utf-8")
    if "/{factor_id}/analyze" not in factors:
        failures.append("factor analyze route alias is missing")
    if 'require_any_role("researcher", "admin")' not in factors:
        failures.append("factor analyze routes must reject viewer-only users")
    risk = (ROOT / "apps/api/app/api/routes_risk.py").read_text(encoding="utf-8")
    if "/policy-decisions" not in risk:
        failures.append("risk policy decisions route is missing")
    for required in ['require_any_role("risk_reviewer", "admin")', 'require_any_role("admin")']:
        if required not in risk:
            failures.append(f"risk routes must enforce RBAC: {required}")
    external = (ROOT / "apps/api/app/api/routes_external_ui.py").read_text(encoding="utf-8")
    if "settings.openbb_workspace_url" not in external or "widget_provider_url" not in external or "localhost:6900" in external:
        failures.append("OpenBB workspace UI must be distinct from settings.openbb_backend_url")
    for required in ["_widget_data(widget_id, db)", "db.query(StrategyCard)", "db.query(BacktestRun)", "db.query(FactorSpec)", "db.query(RiskReview)", "db.query(ResearchIdea)"]:
        if required not in external:
            failures.append(f"OpenBB widgets must return domain data, not empty shells: {required}")
    for required in ["openbb_widgets_manifest", "external_ui.openbb_widgets_manifest_viewed", "audit_required", "audited_endpoint", "read_only"]:
        if required not in external:
            failures.append(f"OpenBB widgets manifest must be audited/read-only: {required}")
    connections = (ROOT / "apps/api/app/services/connections.py").read_text(encoding="utf-8")
    if "localhost:6900" in connections:
        failures.append("connection browser UI URLs must not use stale local ports")
    for name in ["routes_backtests.py", "routes_factors.py", "routes_paper_trading.py", "routes_research.py", "routes_strategies.py", "routes_workflows.py"]:
        route_text = (ROOT / "apps/api/app/api" / name).read_text(encoding="utf-8")
        if "require_any_role" not in route_text:
            failures.append(f"write routes must use RBAC guard: {name}")
    workflows_route = (ROOT / "apps/api/app/api/routes_workflows.py").read_text(encoding="utf-8")
    for required in ["db.get(ResearchIdea", "db.get(StrategySpec", "research idea not found", "strategy not found"]:
        if required not in workflows_route:
            failures.append(f"workflow start routes must validate owner ids: {required}")
    if "dataset_version is required" not in workflows_route:
        failures.append("BacktestWorkflow route must require dataset_version")
    for required in ["cancel_workflow_link", "workflow_event_log"]:
        if required not in workflows_route:
            failures.append(f"workflow cancel/events routes must use durable workflow audit services: {required}")
    research_route = (ROOT / "apps/api/app/api/routes_research.py").read_text(encoding="utf-8")
    agent_runtime = (ROOT / "apps/api/app/agents/runtime.py").read_text(encoding="utf-8")
    if "OpenAIAgentsRuntime().run_research_workflow" not in research_route:
        failures.append("research workflow route must use OpenAIAgentsRuntime")
    if "StubAgentRuntime" in agent_runtime:
        failures.append("legacy StubAgentRuntime must not remain")
    if "openai_agents_sdk_temporal_activity" not in agent_runtime:
        failures.append("OpenAIAgentsRuntime must mark Temporal workflow payload with OpenAI Agents SDK boundary")
    return failures


def check_worker_chain() -> list[str]:
    activities = (ROOT / "apps/workers/activities.py").read_text(encoding="utf-8")
    workflows = (ROOT / "apps/workers/workflows.py").read_text(encoding="utf-8")
    worker_main = (ROOT / "apps/workers/worker_main.py").read_text(encoding="utf-8")
    required = [
        "OpenAIAgentPlanActivity",
        "DltIngestionActivity",
        "GreatExpectationsValidationActivity",
        "DVCVersionActivity",
        "DVCRestoreActivity",
        "DatasetRegistrationActivity",
        "QlibResearchActivity",
        "QuantConnectBacktestActivity",
        "MLflowBacktestActivity",
        "RiskGateActivity",
        "ApprovalRequestActivity",
        "StrategyRegistrationPendingActivity",
        "StrategyRegistrationFinalizeActivity",
        "PaperPromotionCandidateActivity",
        "PaperPromotionFinalizeActivity",
        "WorkflowStatusActivity",
    ]
    failures = [f"Temporal activity missing: {name}" for name in required if name not in activities or name not in workflows]
    adapters = (ROOT / "apps/api/app/adapters/stubs.py").read_text(encoding="utf-8")
    for required_boundary in ['_run_gateway_activity(', '"openai"', '"purpose": "agent_plan"', "openai_agents_sdk"]:
        if required_boundary not in activities:
            failures.append(f"OpenAI agent worker must delegate through ToolGateway: {required_boundary}")
    for required_boundary in ["from agents import Agent, Runner, set_default_openai_key", "Runner.run_sync", "output_type=OpenAIAgentPlan", "openai_agents_sdk", "handoffs=specialists", '"ResearchAgent"', '"DataAgent"', '"FactorAgent"', '"BacktestAgent"', '"RiskAgent"', '"ReportAgent"', '"agent_team"']:
        if required_boundary not in adapters:
            failures.append(f"OpenAI Agents SDK adapter boundary is missing: {required_boundary}")
    for forbidden_boundary in ["get_infisical_client", ".read_secret("]:
        if forbidden_boundary in activities:
            failures.append(f"worker activities must not read Infisical secrets directly: {forbidden_boundary}")
    if "allow_agent_fallback" not in activities:
        failures.append("OpenAI Agents SDK activity must require explicit ALLOW_AGENT_FALLBACK before deterministic fallback")
    if "allow_mature_tool_fallback" not in activities:
        failures.append("worker mature tool activities must require explicit ALLOW_MATURE_TOOL_FALLBACK before local fallback")
    for forbidden in [
        '"status": "completed", "factor_spec_id"',
        '"status": "completed", "artifact_type": "alphalens_report"',
        '"status": "completed", "artifact_type": "quantstats_report"',
    ]:
        if forbidden in activities:
            failures.append(f"worker quant activity still returns fake completed result: {forbidden}")
    for required_boundary in ["prepare_factor_research", "create_factor_report", "create_strategy_report", "query_bars", "query_factor_values", "query_backtest_equity", "query_orders"]:
        if required_boundary not in adapters:
            failures.append(f"quant adapter missing mature-tool request builder: {required_boundary}")
    for required_gateway_call in ['_gateway_output("qlib"', '_gateway_output("alphalens"', '_gateway_output("quantstats"', '_gateway_output("quantconnect_mcp"']:
        if required_gateway_call not in activities:
            failures.append(f"worker quant activity must use ToolGateway output: {required_gateway_call}")
    for required_artifact in [
        "create_artifact",
        "qlib_research_summary",
        "alphalens_factor_tear_sheet",
        "quantstats_strategy_tear_sheet",
        "research_memo",
        "strategy_card.generated",
    ]:
        if required_artifact not in activities:
            failures.append(f"worker quant activity missing sample artifact output: {required_artifact}")
    for required_report in ["StrategyCard", "StrategySpec", "RiskReview", "BacktestRun", "latest_risk_review", "request_type\": \"register_strategy", "approval_status=\"pending\""]:
        if required_report not in activities:
            failures.append(f"ReportGenerationActivity must create StrategyCard and pending registration approval context: {required_report}")
    for required_finalize in ["_activity_chain_with_state", "StrategyRegistrationFinalizeActivity", "approval.get(\"approval\")"]:
        if required_finalize not in workflows:
            failures.append(f"ResearchWorkflow must finalize generated strategy after approval: {required_finalize}")
    strategy_state = (ROOT / "apps/api/app/services/strategy_state.py").read_text(encoding="utf-8")
    if "card.approval_status = \"approved\"" not in strategy_state:
        failures.append("strategy registration must update StrategyCard approval_status")
    for required_status in ['"PAPER_TRADING": {"LIVE_CANDIDATE", "RETIRED"}', '"LIVE_CANDIDATE": {"LIVE_LOCKED"}', '"LIVE_LOCKED": {"RETIRED"}']:
        if required_status not in strategy_state:
            failures.append(f"strategy lifecycle missing live locked MVP status path: {required_status}")
    for required_mlflow in ["log_backtest_run_to_mlflow", "MLflowBacktestActivity", "mlflow_run_id"]:
        if required_mlflow not in activities and required_mlflow not in workflows:
            failures.append(f"worker backtest chain missing MLflow experiment run boundary: {required_mlflow}")
    for required in ["_activity_chain_with_state", "existing_artifacts", "SAMPLE_OHLCV_ROWS", "backtest.artifacts", "create_ohlcv_dataset", "dataset_registration_activity"]:
        if required not in activities and required not in workflows:
            failures.append(f"worker chain must preserve default data/artifact continuity: {required}")
    for required in ["_backtest_status_from_payload", "_has_completed_backtest_result", 'status=_backtest_status_from_payload(payload)', '"result_pending"']:
        if required not in activities:
            failures.append(f"worker chain must not mark prepared/sample backtests completed: {required}")
    for required in ["_write_rows_for_dvc", "to_parquet", "_file_revision", "dataset_path", "_registered_dataset_path", 'dataset_id != "pending"', "Artifact.dvc_rev == dvc_rev", "_strict_mature_tool_mode", "DVC versioning failed in strict mode"]:
        if required not in activities:
            failures.append(f"DVC data chain must persist and restore concrete dataset paths: {required}")
    for required in [
        "dlt pipeline requires explicit rows or Massive source output in strict mode",
        "Great Expectations validation requires explicit rows in strict mode",
        "dataset registration requires explicit rows in strict mode",
    ]:
        if required not in activities:
            failures.append(f"strict data ingestion must reject implicit sample rows: {required}")
    datasets = (ROOT / "apps/api/app/services/datasets.py").read_text(encoding="utf-8")
    if '"dataset_path"' not in datasets:
        failures.append("dataset service must return the artifact-backed dataset_path")
    for required in ['"gx_validation"', '"gx_artifact_id"', '"gx_validation_artifact_id"', "json.dumps"]:
        if required not in datasets:
            failures.append(f"dataset service must persist GX validation result as an artifact: {required}")
    for required in ["dvc_restore_activity", "restore_dataset", "restore_request_prepared", '"DVCRestoreActivity", "QuantConnectBacktestActivity"']:
        if required not in activities and required not in workflows:
            failures.append(f"BacktestWorkflow must restore the pinned DVC dataset before backtest: {required}")
    for required in ["_run_gateway_activity", "_gateway_output", "AdapterRunner", "ToolContext", "default_registry"]:
        if required not in activities:
            failures.append(f"worker tool activities must go through ToolGateway: {required}")
    for required in ["connection_test_activity", "_connection_test_adapter", "ConnectionTestAgent", "connection.test_succeeded", "required_fields"]:
        if required not in activities:
            failures.append(f"ConnectionTestActivity must validate through ToolGateway and secret refs: {required}")
    if "evaluate_risk_gate" not in activities or "sample_gate" in activities:
        failures.append("RiskGateActivity must call OPA-backed evaluate_risk_gate, not sample pass")
    for required in ["_gx_failed", "RecordSystemEventActivity", "data_ingestion.gx_failed"]:
        if required not in workflows:
            failures.append(f"DataIngestionWorkflow must stop and record a system event when GX fails: {required}")
    for required in ["_risk_failed", "risk_gate_failed", '"ReportGenerationActivity", "ApprovalRequestActivity"']:
        if required not in workflows:
            failures.append(f"ResearchWorkflow must stop before reporting/approval when risk fails: {required}")
    for required in ["write_system_event", "system_event_id"]:
        if required not in activities:
            failures.append(f"RecordSystemEventActivity must write a real system event: {required}")
    for required in ["_log_agent_activity_trace", "log_agent_run_to_langfuse", "langfuse_trace_id", "prompt_version", "token_usage", "latency"]:
        if required not in activities:
            failures.append(f"OpenAIAgentPlanActivity must create Langfuse trace: {required}")
    if "input_payload=redact_secrets(payload)" not in activities:
        failures.append("OpenAIAgentPlanActivity must persist redacted AgentRun input")
    if "db.get(AgentRun" not in activities or "agent_run_id" not in activities:
        failures.append("OpenAIAgentPlanActivity must reuse existing AgentRun when agent_run_id is supplied")
    if "create_approval_request" not in activities or "workflow_id" not in activities:
        failures.append("ApprovalRequestActivity must create workflow-linked approval requests")
    if "configure_worker_observability()" not in worker_main or "configure_otel" not in worker_main:
        failures.append("worker entrypoint must initialize OpenTelemetry")
    return failures


def check_control_ui() -> list[str]:
    package = json.loads((ROOT / "apps/control-ui/package.json").read_text(encoding="utf-8"))
    deps = package.get("dependencies", {})
    failures = []
    for dep in ["@refinedev/antd", "@refinedev/core", "@xyflow/react", "antd"]:
        if dep not in deps:
            failures.append(f"control-ui missing dependency: {dep}")
    src_root = ROOT / "apps/control-ui/src"
    ui_source = "\n".join(
        path.read_text(encoding="utf-8")
        for path in sorted(src_root.rglob("*"))
        if path.suffix in {".ts", ".tsx", ".css"}
    )
    routes = (src_root / "routes.tsx").read_text(encoding="utf-8")
    api_client = (src_root / "api/client.ts").read_text(encoding="utf-8")
    agent_graph_route = (ROOT / "apps/api/app/api/routes_agent_graph.py").read_text(encoding="utf-8")
    for required in [
        "工作台",
        "策略研究",
        "智能体管理",
        "研究管线",
        "因子和策略",
        "实验与回测",
        "研究报告",
        "因子库",
        "策略库",
        "Agent Canvas",
        "ReactFlow",
        "AgentConfigDrawer",
        "qto-canvas-toolbar",
        "qto-agent-status-dot",
        "工具与连接",
        "权限与风控",
        "can_execute_live_trade=false",
        "live trading locked",
    ]:
        if required not in ui_source:
            failures.append(f"control-ui missing new IA/canvas contract: {required}")
    for stale in ["NAV_GROUPS", "NAV_MENU_ITEMS", "qto-mobile-group-menu", "qto-mobile-subnav"]:
        if stale in ui_source:
            failures.append(f"control-ui must not expose stale grouped navigation: {stale}")
    for required in [
        '"/": "/dashboard"',
        '"/agent-console": "/agents/canvas"',
        '"/connections": "/agents/canvas?panel=connections"',
        '"/workflows": "/agents/canvas?panel=workflows"',
        '"/audit-log": "/agents/canvas?panel=audit"',
        '"/settings": "/agents/canvas?panel=settings"',
        '"/research-lab": "/research/pipeline"',
        '"/factor-library": "/research/factors-strategies?tab=factors"',
        '"/strategy-registry": "/research/factors-strategies?tab=strategies"',
        '"/backtest-center": "/research/experiments"',
        '"/risk-center": "/dashboard?panel=risk"',
        '"/approvals": "/dashboard?panel=approvals"',
        '"/paper-trading": "/dashboard?panel=portfolio"',
        '"/external-workspaces": "/agents/canvas?panel=tools"',
    ]:
        if required not in routes:
            failures.append(f"control-ui missing legacy redirect: {required}")
    for required in [
        "VITE_KEYCLOAK_BASE_URL",
        "protocol/openid-connect/auth",
        "protocol/openid-connect/token",
        "code_challenge",
        "crypto.subtle.digest",
        "Authorization",
        "Bearer",
        "/api/v1/research-ideas",
    ]:
        if required not in ui_source:
            failures.append(f"control-ui missing OIDC boundary: {required}")
    if "openApiPath" not in api_client:
        failures.append("control-ui must open API detail links through authenticated fetch")
    if 'href={`${API_URL}' in ui_source:
        failures.append("control-ui must not open authenticated API URLs with bare href")
    for required in ["fastApiDataProvider", "getList", "RESOURCE_ENDPOINTS", '"agent-graph": "/api/v1/agent-graph"']:
        if required not in api_client:
            failures.append(f"control-ui missing FastAPI data provider/client: {required}")
    for required in ["type StrategyCard", "current_status", "approval_status", "paper_trading_status", "live_trading_status"]:
        if required not in ui_source:
            failures.append(f"control-ui missing StrategyCard lifecycle display: {required}")
    for required in [
        "openai",
        "massive",
        "quantconnect",
        "openbb",
        "mlflow",
        "langfuse",
        "grafana",
        "temporal",
        "infisical",
        "secret_ref",
    ]:
        if required not in ui_source + agent_graph_route:
            failures.append(f"control-ui Agent Canvas missing tool/connection contract: {required}")
    for required in ["Connect", "Test", "Open UI", "View audit", "Secret fields are sent once", "setCredentialDraft({})"]:
        if required not in ui_source:
            failures.append(f"control-ui Agent Canvas missing tool action/secret boundary: {required}")
    for required in ["approvalComment.trim()", "请填写审批说明", "okButtonProps={{ disabled: !approvalComment.trim() }}"]:
        if required not in ui_source:
            failures.append(f"control-ui approval drawer must require human comment: {required}")
    for required in ["policy_lock_reason", "allowed_actions", "approvalLocked || !approvalComment.trim()"]:
        if required not in ui_source:
            failures.append(f"control-ui must use backend approval policy lock fields: {required}")
    for required in ["isLiveRelatedApproval", "row.request_type", "row.target_type", "risk_summary", "Live trading is locked by MVP policy"]:
        if required not in ui_source:
            failures.append(f"control-ui must apply a structured frontend live approval lock fallback: {required}")
    for required in [
        'readResourceValue<DashboardSummary>("dashboard")',
        'readResourceValue<ResearchPipeline>("research-pipeline")',
        'readResourceList<FactorSpec>("factors")',
        'readResourceList<StrategySpec>("strategies")',
        'readResourceList<BacktestRun>("backtests")',
        'readResourceList<ApprovalRequest>("approvals")',
        'readResourceList<WorkflowLink>("workflows")',
        'readResourceList<AgentRun>("agent-runs")',
        'readResourceValue<AgentGraph>("agent-graph")',
    ]:
        if required not in ui_source:
            failures.append(f"control-ui must read new workbench data: {required}")
    realm = json.loads((ROOT / "infra/keycloak/realm-export.json").read_text(encoding="utf-8"))
    users = {user.get("username"): set(user.get("realmRoles", [])) for user in realm.get("users", [])}
    for username, role in {"qto-admin": "admin", "qto-researcher": "researcher", "qto-approver": "approver"}.items():
        if role not in users.get(username, set()):
            failures.append(f"Keycloak realm missing local login user/role: {username}:{role}")
    service_account_roles = users.get("service-account-openbb-backend", set())
    if not {"researcher", "viewer", "service_account"}.issubset(service_account_roles):
        failures.append("Keycloak openbb-backend service account must have researcher/viewer/service_account roles")
    service_accounts = {
        user.get("username"): user.get("serviceAccountClientId")
        for user in realm.get("users", [])
        if user.get("username", "").startswith("service-account-")
    }
    if service_accounts.get("service-account-openbb-backend") != "openbb-backend":
        failures.append("Keycloak openbb-backend service account must be linked to openbb-backend client")
    clients = {client.get("clientId"): client for client in realm.get("clients", [])}
    control_client = clients.get("control-ui", {})
    if not control_client.get("publicClient") or not control_client.get("standardFlowEnabled"):
        failures.append("Keycloak control-ui client must be public with standard flow")
    if "http://127.0.0.1:5173/*" not in control_client.get("redirectUris", []):
        failures.append("Keycloak control-ui client must allow 127.0.0.1 redirects")
    if "http://127.0.0.1:5173" not in control_client.get("webOrigins", []):
        failures.append("Keycloak control-ui client must allow 127.0.0.1 web origin")
    mappers = control_client.get("protocolMappers", [])
    has_api_audience = any(
        mapper.get("protocolMapper") == "oidc-audience-mapper"
        and mapper.get("config", {}).get("included.client.audience") == "api"
        and mapper.get("config", {}).get("access.token.claim") == "true"
        for mapper in mappers
    )
    if not has_api_audience:
        failures.append("Keycloak control-ui client must add api audience to access tokens")
    chainlit_client = clients.get("chainlit", {})
    if chainlit_client.get("publicClient"):
        failures.append("Keycloak chainlit client must be confidential for Chainlit OAuth")
    if not chainlit_client.get("standardFlowEnabled"):
        failures.append("Keycloak chainlit client must enable standard flow")
    if "http://127.0.0.1:8001/*" not in chainlit_client.get("redirectUris", []):
        failures.append("Keycloak chainlit client must allow 127.0.0.1 redirects")
    chainlit_mappers = chainlit_client.get("protocolMappers", [])
    has_chainlit_api_audience = any(
        mapper.get("protocolMapper") == "oidc-audience-mapper"
        and mapper.get("config", {}).get("included.client.audience") == "api"
        and mapper.get("config", {}).get("access.token.claim") == "true"
        for mapper in chainlit_mappers
    )
    if not has_chainlit_api_audience:
        failures.append("Keycloak chainlit client must add api audience to access tokens")
    openbb_client = clients.get("openbb-backend", {})
    if openbb_client.get("publicClient") or not openbb_client.get("serviceAccountsEnabled"):
        failures.append("Keycloak openbb-backend client must be a confidential service account")
    openbb_mappers = openbb_client.get("protocolMappers", [])
    has_openbb_api_audience = any(
        mapper.get("protocolMapper") == "oidc-audience-mapper"
        and mapper.get("config", {}).get("included.client.audience") == "api"
        and mapper.get("config", {}).get("access.token.claim") == "true"
        for mapper in openbb_mappers
    )
    if not has_openbb_api_audience:
        failures.append("Keycloak openbb-backend client must add api audience to access tokens")
    return failures


def check_agent_chat() -> list[str]:
    dockerfile = (ROOT / "apps/agent-chat/Dockerfile").read_text(encoding="utf-8")
    app = (ROOT / "apps/agent-chat/app.py").read_text(encoding="utf-8")
    openbb_dockerfile = (ROOT / "apps/openbb-backend/Dockerfile").read_text(encoding="utf-8")
    openbb_app = (ROOT / "apps/openbb-backend/app.py").read_text(encoding="utf-8")
    openbb_requirements = (ROOT / "apps/openbb-backend/requirements.txt").read_text(encoding="utf-8")
    failures = []
    if "chainlit" not in dockerfile or "chainlit" not in app:
        failures.append("agent-chat must use Chainlit")
    if "QTO_API_URL" not in app:
        failures.append("agent-chat must route actions through FastAPI")
    for required in [
        "cl.Action",
        "AskUserMessage",
        "@cl.action_callback",
        "oauth_callback",
        "current_api_token",
        "api_token",
        "/api/v1/tool-calls",
        "/api/v1/approvals/",
        "/api/v1/agent-runs/",
        "/events",
        "parse_sse_events",
        "render_agent_steps",
        "/approve",
        "/reject",
        "/request-changes",
        "allowed_actions",
        "policy_lock_reason",
    ]:
        if required not in app:
            failures.append(f"agent-chat missing Chainlit bridge contract: {required}")
    if "StrategyCard" in app or "/api/v1/strategies" in app:
        failures.append("agent-chat actions must not mutate StrategyCard directly")
    if "DEFAULT_APPROVAL_COMMENT" in app or "QTO_CHAINLIT_APPROVAL_COMMENT" in app:
        failures.append("agent-chat slash approvals must not auto-fill a human comment")
    if "approval_comment_required" not in app:
        failures.append("agent-chat slash approvals must reject missing human comments")
    for required in [
        "FastAPI",
        "httpx.AsyncClient",
        "trace.get_tracer",
        "start_as_current_span",
        "authorization",
        "headers=headers",
        "OPENBB_INTERNAL_TOKEN",
        "X-QTO-Internal-Token",
        "_service_account_token",
        "API_BASE_URL",
        "/api/v1/internal/openbb/service-token",
        "openbb.widgets_manifest_request",
        "_audited_manifest_endpoint",
        "/api/v1/ui/openbb/widgets.json",
        "/api/v1/ui/openbb/widgets/",
        "audit_required",
        "read_only",
    ]:
        if required not in openbb_app:
            failures.append(f"openbb-backend must expose audited FastAPI widget contracts: {required}")
    for forbidden in ["do_POST", "do_PUT", "do_DELETE", "/api/v1/approvals", "/api/v1/strategies", "/api/v3/secrets/raw", "INFISICAL_MACHINE_IDENTITY", "KEYCLOAK_CLIENT_SECRET"]:
        if forbidden in openbb_app:
            failures.append(f"openbb-backend must stay read-only and avoid mutation surface: {forbidden}")
    for required in ["requirements.txt", "pip install", "uvicorn", "app:app", "8010"]:
        if required not in openbb_dockerfile:
            failures.append(f"openbb-backend Dockerfile missing runtime contract: {required}")
    for required in ["fastapi", "httpx", "opentelemetry-api", "opentelemetry-sdk", "opentelemetry-exporter-otlp", "uvicorn"]:
        if required not in openbb_requirements:
            failures.append(f"openbb-backend requirements missing: {required}")
    return failures


def check_data_contracts() -> list[str]:
    failures: list[str] = []
    for suite in ["ohlcv_daily_suite", "factor_values_suite", "backtest_orders_suite"]:
        if not (ROOT / f"data_contracts/gx/{suite}.json").exists():
            failures.append(f"GX suite missing: {suite}")
    data_routes = (ROOT / "apps/api/app/api/routes_data_quality.py").read_text(encoding="utf-8")
    if "/sample-ohlcv-pipeline" not in data_routes:
        failures.append("sample OHLCV data pipeline route is missing")
    if 'require_any_role("researcher", "admin")' not in data_routes:
        failures.append("sample OHLCV data pipeline route must reject viewer-only users")
    datasets = (ROOT / "apps/api/app/services/datasets.py").read_text(encoding="utf-8")
    for required in [
        "create_sample_ohlcv_dataset",
        "build_source",
        "dlt_contract",
        "dlt:massive:",
        "validate_suite",
        "dvc_version_metadata",
        "dvc_rev",
        "query_ohlcv_rows",
        "duckdb",
        "to_parquet",
        "read_parquet",
        "application/vnd.apache.parquet",
    ]:
        if required not in datasets:
            failures.append(f"sample dataset pipeline missing: {required}")
    data_quality = (ROOT / "apps/api/app/services/data_quality.py").read_text(encoding="utf-8")
    for required in [
        "great_expectations",
        "PandasExecutionEngine",
        "ExpectationConfiguration",
        "Validator",
        "engine",
        "expect_column_values_to_be_strictly_increasing_within_group",
        "expect_column_values_to_be_finite",
        "expect_negative_quantity_requires_side",
        "math.isfinite",
    ]:
        if required not in data_quality:
            failures.append(f"GX boundary missing: {required}")
    if "great_expectations.dataset" in data_quality or "PandasDataset" in data_quality:
        failures.append("GX boundary must not use removed PandasDataset API")
    factor_suite = (ROOT / "data_contracts/gx/factor_values_suite.json").read_text(encoding="utf-8")
    orders_suite = (ROOT / "data_contracts/gx/backtest_orders_suite.json").read_text(encoding="utf-8")
    for required in ["expect_column_values_to_be_finite", "missing_ratio"]:
        if required not in factor_suite:
            failures.append(f"factor values suite missing: {required}")
    for required in ["expect_negative_quantity_requires_side", "allowed_negative_sides", "sell", "short"]:
        if required not in orders_suite:
            failures.append(f"backtest orders suite missing: {required}")
    dlt_source = (ROOT / "data_contracts/dlt/massive_source.py").read_text(encoding="utf-8")
    for required in ["dlt.resource", "dlt.source", "to_dlt_resource", "to_dlt_source"]:
        if required not in dlt_source:
            failures.append(f"dlt Massive source missing: {required}")
    activities = (ROOT / "apps/workers/activities.py").read_text(encoding="utf-8")
    for forbidden in ['mode": "content_hash"', 'tool": "quantconnect_lean"', 'status": "completed", "backtest_run_id"']:
        if forbidden in activities:
            failures.append(f"worker activity still has tool-first stub marker: {forbidden}")
    adapters = (ROOT / "apps/api/app/adapters/stubs.py").read_text(encoding="utf-8")
    for required in ["create_project", "upload_strategy_files", "run_backtest", "poll_backtest_status", "fetch_backtest_result", "fetch_backtest_charts_or_links", "create_deployment_proposal"]:
        if required not in adapters:
            failures.append(f"QuantConnect adapter contract missing: {required}")
    parser = configparser.ConfigParser()
    parser.read(ROOT / "data_contracts/dvc/config.template")
    if 'remote "minio"' not in parser.sections():
        failures.append("DVC MinIO remote template is invalid")
    root_parser = configparser.ConfigParser()
    root_parser.read(ROOT / ".dvc/config")
    if 'remote "minio"' not in root_parser.sections():
        failures.append("root DVC MinIO remote config is missing")
    for dockerfile in ["apps/api/Dockerfile", "apps/workers/Dockerfile"]:
        text = (ROOT / dockerfile).read_text(encoding="utf-8")
        if "COPY .dvc" not in text:
            failures.append(f"{dockerfile} must copy root DVC config into container")
        if "build-essential" not in text:
            failures.append(f"{dockerfile} must install build-essential for pyqlib Cython extensions")
    return failures


def check_dependency_contracts() -> list[str]:
    pyproject = (ROOT / "apps/api/pyproject.toml").read_text(encoding="utf-8")
    failures = []
    for dep in [
        "openai-agents",
        "temporalio",
        "prometheus-client",
        "opentelemetry-exporter-otlp",
        "boto3",
        "pandas",
        "pyarrow",
        "duckdb",
        "langfuse",
        "dlt",
        "great-expectations",
        "dvc[s3]",
        "pyqlib",
        "rdagent",
        "alphalens-reloaded",
        "quantstats",
        "PyPortfolioOpt",
    ]:
        if dep not in pyproject:
            failures.append(f"api dependency missing: {dep}")
    for clone in [
        "openai-agents-python",
        "temporal",
        "temporal-sdk-python",
        "opa",
        "infisical",
        "keycloak",
        "refine",
        "ant-design",
        "chainlit",
        "openbb-backends",
        "superset",
        "grafana",
        "prometheus",
        "loki",
        "opentelemetry-collector",
        "langfuse",
        "minio",
        "dlt",
        "great-expectations",
        "dvc",
        "jupyterlab",
        "mlflow",
        "qlib",
        "rd-agent",
        "quantconnect-lean",
        "quantconnect-mcp-server",
        "massive-mcp",
        "alphalens-reloaded",
        "quantstats",
        "pyportfolioopt",
        "duckdb",
    ]:
        if not (ROOT / "vendor" / clone / ".git").exists():
            failures.append(f"mature tool clone missing: vendor/{clone}")
    clone_script = (ROOT / "scripts/clone_tools.sh").read_text(encoding="utf-8")
    if "https://github.com/treeverse/dvc.git" not in clone_script:
        failures.append("clone_tools must use canonical treeverse/dvc repository")
    forbidden = re.compile(r"APP_MASTER_KEY|PaperExecutionAdapter|SandboxCodeRunner|RiskPolicyEngine")
    for path in list((ROOT / "apps").rglob("*.py")) + list((ROOT / "docs").rglob("*.md")):
        if path.name == "quant_team_os_requirements_v0_3.md":
            continue
        text = path.read_text(encoding="utf-8")
        if forbidden.search(text):
            failures.append(f"forbidden legacy term in {path.relative_to(ROOT)}")
    raw_provider_secret = re.compile(
        r"\b("
        r"OPENAI_API_KEY(?!_REF)|MASSIVE_API_KEY(?!_REF)|QUANTCONNECT_API_TOKEN(?!_REF)|"
        r"openai_api_key(?!_ref)|massive_api_key(?!_ref)|quantconnect_api_token(?!_ref)"
        r")\b"
    )
    for path in list((ROOT / "apps").rglob("*.py")) + list((ROOT / "apps").rglob("*.tsx")):
        if "/tests/" in path.as_posix():
            continue
        if raw_provider_secret.search(path.read_text(encoding="utf-8")):
            failures.append(f"runtime code must not read raw provider secret env: {path.relative_to(ROOT)}")
    for relative, forbidden_terms in {
        "apps/workers/activities.py": ["get_infisical_client", ".read_secret("],
        "apps/api/app/services/connections.py": [".read_secret("],
        "apps/api/app/services/langfuse_tracking.py": ["get_infisical_client", ".read_secret(", "from langfuse import Langfuse"],
        "apps/openbb-backend/app.py": ["/api/v3/secrets/raw", "INFISICAL_MACHINE_IDENTITY", "KEYCLOAK_CLIENT_SECRET"],
    }.items():
        text = (ROOT / relative).read_text(encoding="utf-8")
        for forbidden_term in forbidden_terms:
            if forbidden_term in text:
                failures.append(f"secret boundary violation in {relative}: {forbidden_term}")
    adapters = (ROOT / "apps/api/app/adapters/stubs.py").read_text(encoding="utf-8")
    for required in ["class KeycloakServiceTokenAdapter", "private_output", "class LangfuseAdapter", "set_default_openai_key"]:
        if required not in adapters:
            failures.append(f"ToolGateway secret-consuming adapter missing: {required}")
    if "ApprovalAdapter()," in adapters:
        failures.append("ApprovalAdapter must not be registered in ToolGateway default registry")
    return failures


def check_readme_docs() -> list[str]:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    failures: list[str] = []
    for required in [
        "python3 scripts/full_stack_doctor.py --env .env",
        "python3 scripts/full_stack_doctor.py --env .env --live",
        "chainlit run app.py --host 127.0.0.1 --port 8001",
        "uvicorn app:app --host 127.0.0.1 --port 8010",
        "docker compose --env-file .env -f infra/docker-compose.yml up -d postgres infisical",
        "docker compose --env-file .env -f infra/docker-compose.yml up --build",
        "SQLite local dev is only a fast fallback",
        "PostgreSQL from Compose",
        "INFISICAL_PROJECT_ID",
        "INFISICAL_MACHINE_IDENTITY_CLIENT_ID",
        "INFISICAL_MACHINE_IDENTITY_CLIENT_SECRET",
        "ALLOW_LOCAL_SECRET_FALLBACK=false",
        "ALLOW_AGENT_FALLBACK=false",
        "ALLOW_MATURE_TOOL_FALLBACK=false",
        "OAUTH_GENERIC_AUTH_URL",
        "OAUTH_GENERIC_TOKEN_URL",
        "OAUTH_GENERIC_USER_INFO_URL",
        "Superset:",
        "Grafana:",
        "Infisical:",
        "Prometheus:",
        "Loki:",
        "docs/runbooks/v0_3_acceptance.md",
    ]:
        if required not in readme:
            failures.append(f"README missing full-stack instruction: {required}")
    runbook = ROOT / "docs/runbooks/v0_3_acceptance.md"
    if not runbook.exists():
        failures.append("v0.3 acceptance runbook is missing")
    else:
        text = runbook.read_text(encoding="utf-8")
        for required in [
            "npm test",
            "npm run full-stack:doctor:template",
            "npm run full-stack:doctor:live",
            "must pass without accepting `temporal_unavailable`",
            "INFISICAL_PROJECT_ID",
            "OPENBB_INTERNAL_TOKEN",
            "OPENAI_API_KEY_REF",
            "LANGFUSE_PUBLIC_KEY_REF",
            "LANGFUSE_SECRET_KEY_REF",
            "ALLOW_MATURE_TOOL_FALLBACK=false",
            "The OpenBB backend must not read **Infisical**",
            "DVC",
            "MinIO",
            "Product DoD Mapping",
            "Known Non-Goals In MVP",
        ]:
            if required not in text:
                failures.append(f"v0.3 acceptance runbook missing: {required}")
    return failures


def check_full_stack_doctor() -> list[str]:
    failures: list[str] = []
    infisical_readme = ROOT / "infra/infisical/README.md"
    if not infisical_readme.exists():
        failures.append("Infisical bootstrap README is missing")
    else:
        infisical_text = infisical_readme.read_text(encoding="utf-8")
        for required in [
            "docker compose --env-file .env -f infra/docker-compose.yml up -d postgres infisical",
            "INFISICAL_PROJECT_ID",
            "INFISICAL_MACHINE_IDENTITY_CLIENT_ID",
            "INFISICAL_MACHINE_IDENTITY_CLIENT_SECRET",
            "python3 scripts/full_stack_doctor.py --env .env --live",
        ]:
            if required not in infisical_text:
                failures.append(f"Infisical bootstrap README missing: {required}")
    script = ROOT / "scripts/full_stack_doctor.py"
    if not script.exists():
        return ["full-stack doctor script is missing"]
    text = script.read_text(encoding="utf-8")
    for required in [
        "INFISICAL_PROJECT_ID",
        "INFISICAL_INTERNAL_SECRET_REFS",
        "OPTIONAL_EXTERNAL_PROVIDER_SECRET_REFS",
        "ALLOW_LOCAL_SECRET_FALLBACK",
        "FORBIDDEN_RAW_PROVIDER_SECRETS",
        "CHAINLIT_OAUTH",
        "OAUTH_GENERIC_CLIENT_SECRET",
        "--live",
        "--require-external-providers",
        "JUPYTERLAB_URL",
        "compose_failures",
        "docker compose",
        "TimeoutExpired",
        "privileged helper",
        "install config --user",
        "validate_openbb_widgets_json",
        "validate_openbb_widgets_payload",
        "validate_openbb_widget_payload",
        "validate_openbb_widget_contracts",
        "validate_openbb_widget_audit_rows",
        "REQUIRED_OPENBB_WIDGET_IDS",
        "external_ui.openbb_widget_viewed",
        "validate_infisical_machine_identity",
        "validate_openbb_internal_service_token",
        "/api/v1/internal/openbb/service-token",
        "X-QTO-Internal-Token",
        "/api/v1/ui/openbb/widgets.json",
        "/api/v1/ui/openbb/widgets/{expected_widget_id}",
        "protected widget manifest",
        "validate_keycloak_api_auth",
        "/protocol/openid-connect/token",
        "/api/v1/connections",
        "validate_research_workflow_smoke",
        "/api/v1/research-ideas",
        "/start-workflow",
        "/events",
        "_poll_workflow_approval",
        "_signal_temporal_approval",
        "_poll_workflow_status",
        "approval_resolved",
        "workflow.rejected",
        "workflow.temporal_started",
        "validate_langfuse_trace_smoke",
        "validate_langfuse_trace_readable",
        "/api/v1/agent-runs",
        "/langfuse-link",
        "/api/public/traces/",
        "QTO_LANGFUSE_TRACE_ID",
        "Langfuse trace was not readable",
        "validate_opa_trading_lock",
        "/v1/data/qto/trading_lock",
        "live trading is locked",
        "validate_mlflow_experiments",
        "/api/2.0/mlflow/experiments/search",
        "validate_mlflow_run_smoke",
        "mlflow.start_run",
        "mlflow.log_metric",
        "mlflow.log_artifact",
        "client.list_artifacts",
        "validate_prometheus_targets",
        "/api/v1/targets?state=active",
        "prometheus targets missing jobs",
        "validate_grafana_dashboard",
        "validate_grafana_dashboard_queries",
        "_validate_prometheus_query",
        "_validate_loki_query",
        "/api/v1/query",
        "/loki/api/v1/query",
        "/api/dashboards/uid/qto-required-dashboards",
        "Quant Team OS Required Dashboards",
        "grafana required dashboard missing panels",
        "Agent Runtime Monitoring",
        "Temporal Workflow Monitoring",
        "OpenAI API Cost and Error Rate",
        "Data Ingestion and GX Validation",
        "Backtest Runtime and Failure",
        "validate_minio_buckets",
        "S3_BUCKET_DVC",
        "QTO_DOCTOR_SMOKE_ID",
        "client.delete_object",
        "validate_dvc_minio_roundtrip",
        '["dvc", "push", "-r", "minio"]',
        '["dvc", "pull", filename, "-r", "minio"]',
        "/api/v1/chart/",
        "/api/v1/dataset/",
        "/api/v1/database/",
        "validate_superset_chart_queries",
        "/api/v1/sqllab/execute/",
        "_superset_csrf_token",
        "strategy_backtest_aggregate.json",
        "qto_strategy_backtest_aggregate",
        "validate_chainlit_bridge_smoke",
        'service="agent-chat"',
        "Chainlit OAuth env is not configured",
        "/api/v1/approvals/approval-1/approve",
        "validate_temporal_server_connection",
        "Client.connect",
        "validate_temporal_worker_registration",
        "configured_workflows",
        "ResearchWorkflow",
        "WorkflowStatusActivity",
        "DescribeTaskQueueRequest",
        "TASK_QUEUE_TYPE_WORKFLOW",
        "TASK_QUEUE_TYPE_ACTIVITY",
        "report_pollers=True",
        "no workflow task queue pollers",
        "no activity task queue pollers",
        "/api/v1/auth/universal-auth/login",
        "validate_infisical_secret_refs",
        "/api/v3/secrets/raw/",
        "infisical secret ref not readable",
        "validate_superset_dashboard",
        "Strategy and Backtest Aggregate",
        "/api/v1/security/login",
        "/api/v1/dashboard/",
        "audit_required",
        "read_only",
        'link.get("status") not in {"started", "running", "completed"}',
    ]:
        if required not in text:
            failures.append(f"full-stack doctor missing check: {required}")
    if '"temporal_unavailable"' in text:
        failures.append("full-stack doctor live ResearchWorkflow smoke must not accept temporal_unavailable")
    package = json.loads((ROOT / "package.json").read_text(encoding="utf-8"))
    if package.get("scripts", {}).get("full-stack:doctor") != "python3 scripts/full_stack_doctor.py --env .env":
        failures.append("package.json missing full-stack:doctor script")
    result = subprocess.run(
        [sys.executable, str(script), "--env", ".env.example", "--template-ok"],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        failures.append(f"full-stack doctor must pass against .env.example with --template-ok: {result.stdout}{result.stderr}")
    return failures


def check_ci_contract() -> list[str]:
    failures: list[str] = []
    package = json.loads((ROOT / "package.json").read_text(encoding="utf-8"))
    test_script = package.get("scripts", {}).get("test", "")
    if "scripts/acceptance_audit.py" not in test_script:
        failures.append("npm test must run V0.3 acceptance audit")
    if not (ROOT / "scripts/acceptance_audit.py").exists():
        failures.append("V0.3 acceptance audit script is missing")
    acceptance_audit = (ROOT / "scripts/acceptance_audit.py").read_text(encoding="utf-8")
    if "check_must_not_implement" not in acceptance_audit:
        failures.append("V0.3 acceptance audit must cover must-not-implement requirements")
    if "scripts/opa_policy_gate.py" not in test_script:
        failures.append("npm test must run OPA policy gate")
    if "--allow-static-fallback" in test_script:
        failures.append("npm test must run real OPA policy tests without static fallback")
    if "QTO_SETTINGS_ENV_FILE=" not in test_script or "-m pytest apps/api/tests" not in test_script:
        failures.append("npm test must isolate API tests from local .env")
    ci = (ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")
    if "downloads/v1.18.0/opa_linux_amd64_static" not in ci:
        failures.append("CI must install OPA v1.18.0 for Rego v1 policy tests")
    compose = yaml.safe_load((ROOT / "infra/docker-compose.yml").read_text(encoding="utf-8"))
    opa_image = compose.get("services", {}).get("opa", {}).get("image")
    if opa_image != "openpolicyagent/opa:1.18.0":
        failures.append("docker-compose OPA image must match CI OPA v1.18.0")
    if "npm --prefix apps/control-ui run test" not in test_script:
        failures.append("npm test must run control-ui contract tests")
    control_package = json.loads((ROOT / "apps/control-ui/package.json").read_text(encoding="utf-8"))
    control_test = control_package.get("scripts", {}).get("test", "")
    if "python3 ../../scripts/control_ui_contract_test.py" not in control_test or "node tests/ui-smoke.mjs" not in control_test:
        failures.append("control-ui package must run contract and UI smoke tests")
    if not (ROOT / "scripts/control_ui_contract_test.py").exists():
        failures.append("control-ui contract test script is missing")
    if not (ROOT / "apps/control-ui/tests/ui-smoke.mjs").exists():
        failures.append("control-ui UI smoke test is missing")
    ci_path = ROOT / ".github/workflows/ci.yml"
    if not ci_path.exists():
        failures.append("CI workflow is missing")
        return failures
    ci = ci_path.read_text(encoding="utf-8")
    for required in ["actions/setup-python", "actions/setup-node", "openpolicyagent.org/downloads/v1.18.0", "npm ci", "npm test"]:
        if required not in ci:
            failures.append(f"CI workflow missing: {required}")
    return failures


if __name__ == "__main__":
    main()
