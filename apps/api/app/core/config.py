import os
from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


def _env_file() -> str | None:
    value = os.getenv("QTO_SETTINGS_ENV_FILE", ".env")
    return value or None


class Settings(BaseSettings):
    app_env: str = "development"
    database_url: str = "postgresql+psycopg://qto_app:qto_app@localhost:5432/quant_team_os"
    artifact_root: Path = Field(default=Path("./artifacts"))

    keycloak_base_url: str = "http://localhost:8080"
    keycloak_internal_base_url: str = ""
    keycloak_jwks_url: str = ""
    keycloak_realm: str = "quant-team-os"
    keycloak_client_id: str = "api"
    keycloak_client_secret_ref: str = "/quant-team-os/dev/keycloak/api-client-secret"
    openbb_keycloak_client_secret_ref: str = "/quant-team-os/dev/keycloak/openbb-backend-client-secret"
    openbb_internal_token: str = "change-me-openbb-internal-token"

    infisical_api_url: str = "http://localhost:8080"
    infisical_project_id: str = ""
    infisical_machine_identity_client_id: str = ""
    infisical_machine_identity_client_secret: str = ""
    allow_local_secret_fallback: bool = False

    temporal_address: str = "localhost:7233"
    temporal_namespace: str = "default"
    allow_temporal_fallback: bool = False
    opa_url: str = "http://localhost:8181"
    allow_local_policy_fallback: bool = False

    s3_endpoint_url: str = "http://localhost:9000"
    s3_bucket_artifacts: str = "qto-artifacts"
    s3_bucket_datasets: str = "qto-datasets"
    s3_bucket_mlflow: str = "qto-mlflow"
    s3_bucket_reports: str = "qto-reports"
    s3_bucket_dvc: str = "qto-dvc"
    aws_access_key_id: str = "minioadmin"
    aws_secret_access_key: str = "minioadmin"
    enable_minio_upload: bool = True

    openai_api_key_ref: str = "/quant-team-os/dev/connections/openai"
    openai_model: str = "gpt-4.1-mini"
    allow_agent_fallback: bool = False
    allow_mature_tool_fallback: bool = False
    massive_api_key_ref: str = "/quant-team-os/dev/connections/massive"
    quantconnect_user_id: str = ""
    quantconnect_api_token_ref: str = "/quant-team-os/dev/connections/quantconnect"
    mlflow_tracking_uri: str = "http://localhost:5000"
    mlflow_ui_url: str = "http://localhost:5000"
    langfuse_host: str = "http://localhost:3000"
    langfuse_ui_url: str = "http://localhost:3002"
    langfuse_public_key_ref: str = "/quant-team-os/dev/langfuse/public-key"
    langfuse_secret_key_ref: str = "/quant-team-os/dev/langfuse/secret-key"
    # When false, Langfuse tracing degrades to local mirror even with strict
    # secret handling. Lets the core compose profile run without the
    # observability profile while keeping ALLOW_LOCAL_SECRET_FALLBACK=false.
    require_langfuse_tracking: bool = True
    otel_exporter_otlp_endpoint: str = ""
    otel_service_name: str = "quant-team-os-api"

    control_ui_url: str = "http://localhost:5173"
    chainlit_url: str = "http://localhost:8001"
    openbb_workspace_url: str = "https://pro.openbb.co"
    openbb_backend_url: str = "http://localhost:8010"
    superset_url: str = "http://localhost:8088"
    grafana_url: str = "http://localhost:3000"
    temporal_ui_url: str = "http://localhost:8233"
    jupyterlab_url: str = "http://localhost:8888"
    infisical_ui_url: str = "http://localhost:8082"
    minio_console_url: str = "http://localhost:9001"

    allow_live_trading: bool = False
    allow_agent_arbitrary_code_execution: bool = False
    allow_local_auth_fallback: bool = False
    sandbox_network: bool = False

    model_config = SettingsConfigDict(env_file=_env_file(), extra="ignore")


@lru_cache
def get_settings() -> Settings:
    return Settings()
