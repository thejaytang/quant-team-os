from __future__ import annotations

from sqlalchemy.orm import Session

from app.api.compat import APIRouter, Depends, HTTPException
from app.core.config import get_settings
from app.db.models import BacktestRun, FactorSpec, ResearchIdea, RiskReview, StrategyCard
from app.db.session import get_db
from app.services.audit import write_audit_log
from app.services.connections import list_connections
from app.services.observability import tool_observation

router = APIRouter(prefix="/api/v1", tags=["external-ui"])

OPENBB_WIDGETS = [
    {"id": "strategy-registry", "name": "Strategy Registry"},
    {"id": "backtest-summary", "name": "Backtest Summary"},
    {"id": "factor-library", "name": "Factor Library"},
    {"id": "risk-review", "name": "Risk Review"},
    {"id": "research-progress", "name": "Research Progress"},
]


def _workspaces() -> list[dict[str, str]]:
    settings = get_settings()
    return [
        {
            "id": "openbb",
            "name": "OpenBB Workspace",
            "url": settings.openbb_workspace_url,
            "purpose": "financial research widgets",
            "permission_level": "read_only",
            "widget_provider_url": settings.openbb_backend_url,
        },
        {"id": "superset", "name": "Superset", "url": settings.superset_url, "purpose": "strategy and backtest BI", "permission_level": "read_only"},
        {"id": "grafana", "name": "Grafana", "url": settings.grafana_url, "purpose": "runtime monitoring", "permission_level": "read_only"},
        {"id": "temporal", "name": "Temporal UI", "url": settings.temporal_ui_url, "purpose": "workflow runs and retries", "permission_level": "read_only"},
        {"id": "mlflow", "name": "MLflow UI", "url": settings.mlflow_ui_url, "purpose": "experiment metrics and artifacts", "permission_level": "read_only"},
        {"id": "langfuse", "name": "Langfuse UI", "url": settings.langfuse_ui_url, "purpose": "LLM traces", "permission_level": "read_only"},
        {"id": "jupyterlab", "name": "JupyterLab", "url": settings.jupyterlab_url, "purpose": "human notebook research", "permission_level": "human_research"},
        {"id": "infisical", "name": "Infisical", "url": settings.infisical_ui_url, "purpose": "secret admin and audit", "permission_level": "admin_only"},
        {"id": "keycloak", "name": "Keycloak Admin", "url": settings.keycloak_base_url, "purpose": "identity and RBAC admin", "permission_level": "admin_only"},
        {"id": "minio", "name": "MinIO Console", "url": settings.minio_console_url, "purpose": "artifact object browsing", "permission_level": "admin_only"},
        {"id": "chainlit", "name": "Chainlit", "url": settings.chainlit_url, "purpose": "agent chat and human action buttons", "permission_level": "human_action"},
        {"id": "quantconnect", "name": "QuantConnect Cloud", "url": "https://www.quantconnect.com", "purpose": "backtest and paper trading", "permission_level": "backtest_and_paper"},
    ]


@router.get("/external-workspaces")
def external_workspaces(db: Session = Depends(get_db)):
    connections = {item["provider"]: item for item in list_connections(db)}
    items = []
    for workspace in _workspaces():
        connection = connections.get(workspace["id"], {})
        items.append(
            {
                **workspace,
                "status": connection.get("status", "disconnected"),
                "last_checked_at": connection.get("last_checked_at"),
                "last_error": connection.get("last_error"),
            }
        )
    return {"items": items}


@router.get("/ui/openbb/widgets.json")
def openbb_widgets(db: Session = Depends(get_db)):
    with tool_observation("openbb_widgets_manifest", "system", None) as observability:
        payload = {
            "widgets": [
                {**widget, "endpoint": f"/api/v1/ui/openbb/widgets/{widget['id']}", "mode": "read_only", "audit_required": True}
                for widget in OPENBB_WIDGETS
            ],
            "mode": "read_only",
            "audit_required": True,
            "audited_endpoint": "/api/v1/ui/openbb/widgets.json",
            "observability": observability,
        }
    write_audit_log(db, "external_ui.openbb_widgets_manifest_viewed", "openbb_manifest", "widgets.json", {"observability": payload["observability"]})
    db.flush()
    return payload


@router.get("/ui/openbb/widgets/{widget_id}")
def openbb_widget(widget_id: str, db: Session = Depends(get_db)):
    if widget_id not in {widget["id"] for widget in OPENBB_WIDGETS}:
        raise HTTPException(status_code=404, detail="OpenBB widget not found")
    with tool_observation("openbb_widget", "system", None) as observability:
        payload = {
            "widget_id": widget_id,
            "mode": "read_only",
            "audit_required": True,
            "audited_endpoint": f"/api/v1/ui/openbb/widgets/{widget_id}",
            "data": _widget_data(widget_id, db),
            "observability": observability,
        }
    write_audit_log(db, "external_ui.openbb_widget_viewed", "openbb_widget", widget_id, {"widget_id": widget_id, "observability": payload["observability"]})
    db.flush()
    return payload


def _widget_data(widget_id: str, db: Session) -> list[dict]:
    if widget_id == "strategy-registry":
        return [
            {
                "strategy_id": row.strategy_id,
                "current_status": row.current_status,
                "approval_status": row.approval_status,
                "paper_trading_status": row.paper_trading_status,
                "live_trading_status": row.live_trading_status,
            }
            for row in db.query(StrategyCard).order_by(StrategyCard.updated_at.desc()).limit(20).all()
        ]
    if widget_id == "backtest-summary":
        return [
            {"id": row.id, "strategy_id": row.strategy_id, "status": row.status, "metrics": row.metrics}
            for row in db.query(BacktestRun).order_by(BacktestRun.created_at.desc()).limit(20).all()
        ]
    if widget_id == "factor-library":
        return [
            {"id": row.id, "name": row.name, "status": row.status, "metrics": row.metrics}
            for row in db.query(FactorSpec).order_by(FactorSpec.created_at.desc()).limit(20).all()
        ]
    if widget_id == "risk-review":
        return [
            {"id": row.id, "strategy_id": row.strategy_id, "verdict": row.verdict, "risk_summary": row.risk_summary}
            for row in db.query(RiskReview).order_by(RiskReview.created_at.desc()).limit(20).all()
        ]
    if widget_id == "research-progress":
        return [
            {"id": row.id, "title": row.title, "status": row.status, "tags": row.tags}
            for row in db.query(ResearchIdea).order_by(ResearchIdea.created_at.desc()).limit(20).all()
        ]
    return []


@router.get("/ui/superset/dashboards")
def superset_dashboards():
    return {"items": [{"name": "Strategy and Backtest Aggregate", "url": get_settings().superset_url}]}


@router.get("/ui/grafana/dashboards")
def grafana_dashboards():
    names = [
        "Agent Runtime Monitoring",
        "Temporal Workflow Monitoring",
        "ToolGateway Policy Denials",
        "OpenAI API Cost and Error Rate",
        "Data Ingestion and GX Validation",
        "Backtest Runtime and Failure",
        "Connector Health",
        "Trading Safety Lock",
    ]
    return {"items": [{"name": name, "url": get_settings().grafana_url} for name in names]}


@router.get("/ui/mlflow/links")
def mlflow_links():
    return {"items": [{"name": "MLflow Experiments", "url": get_settings().mlflow_ui_url}]}


@router.get("/ui/langfuse/links")
def langfuse_links():
    return {"items": [{"name": "Langfuse Traces", "url": get_settings().langfuse_ui_url}]}


@router.get("/ui/temporal/links")
def temporal_links():
    return {"items": [{"name": "Temporal Workflows", "url": get_settings().temporal_ui_url}]}


@router.get("/ui/jupyterlab/links")
def jupyterlab_links():
    return {"items": [{"name": "JupyterLab", "url": get_settings().jupyterlab_url}]}
