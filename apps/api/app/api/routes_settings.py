from app.api.compat import APIRouter, Depends
from app.core.auth import require_any_role
from app.core.config import get_settings

router = APIRouter(prefix="/api/v1", tags=["settings"])


@router.get("/settings")
def runtime_settings(_user=Depends(require_any_role("admin", "risk_reviewer"))):
    settings = get_settings()
    return {
        "runtime": {
            "app_env": settings.app_env,
            "otel_service_name": settings.otel_service_name,
            "sandbox_network": settings.sandbox_network,
        },
        "identity": {
            "keycloak_base_url": settings.keycloak_base_url,
            "keycloak_internal_base_url": settings.keycloak_internal_base_url,
            "keycloak_realm": settings.keycloak_realm,
            "keycloak_client_id": settings.keycloak_client_id,
        },
        "security_locks": {
            "allow_live_trading": settings.allow_live_trading,
            "allow_agent_arbitrary_code_execution": settings.allow_agent_arbitrary_code_execution,
            "allow_local_auth_fallback": settings.allow_local_auth_fallback,
            "allow_local_secret_fallback": settings.allow_local_secret_fallback,
            "allow_local_policy_fallback": settings.allow_local_policy_fallback,
            "allow_temporal_fallback": settings.allow_temporal_fallback,
            "allow_agent_fallback": settings.allow_agent_fallback,
            "allow_mature_tool_fallback": settings.allow_mature_tool_fallback,
        },
        "secret_refs": {
            "keycloak_client_secret_ref": settings.keycloak_client_secret_ref,
            "openbb_keycloak_client_secret_ref": settings.openbb_keycloak_client_secret_ref,
            "openai_api_key_ref": settings.openai_api_key_ref,
            "massive_api_key_ref": settings.massive_api_key_ref,
            "quantconnect_api_token_ref": settings.quantconnect_api_token_ref,
            "langfuse_public_key_ref": settings.langfuse_public_key_ref,
            "langfuse_secret_key_ref": settings.langfuse_secret_key_ref,
        },
        "service_urls": {
            "control_ui_url": settings.control_ui_url,
            "chainlit_url": settings.chainlit_url,
            "openbb_workspace_url": settings.openbb_workspace_url,
            "openbb_backend_url": settings.openbb_backend_url,
            "superset_url": settings.superset_url,
            "grafana_url": settings.grafana_url,
            "temporal_ui_url": settings.temporal_ui_url,
            "jupyterlab_url": settings.jupyterlab_url,
            "infisical_ui_url": settings.infisical_ui_url,
            "minio_console_url": settings.minio_console_url,
            "mlflow_tracking_uri": settings.mlflow_tracking_uri,
            "mlflow_ui_url": settings.mlflow_ui_url,
            "langfuse_host": settings.langfuse_host,
            "langfuse_ui_url": settings.langfuse_ui_url,
        },
        "storage": {
            "s3_endpoint_url": settings.s3_endpoint_url,
            "s3_bucket_artifacts": settings.s3_bucket_artifacts,
            "s3_bucket_datasets": settings.s3_bucket_datasets,
            "s3_bucket_mlflow": settings.s3_bucket_mlflow,
            "s3_bucket_reports": settings.s3_bucket_reports,
            "s3_bucket_dvc": settings.s3_bucket_dvc,
            "enable_minio_upload": settings.enable_minio_upload,
        },
        "connections": {
            "openai_model": settings.openai_model,
            "quantconnect_user_id_configured": bool(settings.quantconnect_user_id),
        },
    }
