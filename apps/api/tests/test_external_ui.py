import pytest

from app.api.routes_external_ui import external_workspaces, grafana_dashboards, openbb_widget, openbb_widgets
from app.db.models import AuditLog, StrategyCard
from app.services.connections import connect_provider


def test_external_workspaces_cover_v03_links(db):
    items = external_workspaces(db)["items"]
    ids = {item["id"] for item in items}
    assert {
        "openbb",
        "superset",
        "grafana",
        "temporal",
        "mlflow",
        "langfuse",
        "jupyterlab",
        "infisical",
        "keycloak",
        "minio",
        "chainlit",
        "quantconnect",
    }.issubset(ids)
    openbb = next(item for item in items if item["id"] == "openbb")
    assert openbb["url"] == "https://pro.openbb.co"
    assert openbb["widget_provider_url"] == "http://localhost:8010"
    mlflow = next(item for item in items if item["id"] == "mlflow")
    langfuse = next(item for item in items if item["id"] == "langfuse")
    infisical = next(item for item in items if item["id"] == "infisical")
    assert mlflow["url"] == "http://localhost:5000"
    assert langfuse["url"] == "http://localhost:3002"
    assert infisical["url"] == "http://localhost:8082"


def test_external_workspaces_reflect_connection_status(db):
    connect_provider(db, "mlflow", {"tracking_uri": "http://localhost:5000"})

    items = external_workspaces(db)["items"]
    mlflow = next(item for item in items if item["id"] == "mlflow")

    assert mlflow["status"] == "connected"
    assert mlflow["last_checked_at"] is not None
    assert mlflow["last_error"] is None


def test_grafana_dashboards_cover_required_monitoring_views():
    names = {item["name"] for item in grafana_dashboards()["items"]}

    assert {
        "Agent Runtime Monitoring",
        "Temporal Workflow Monitoring",
        "ToolGateway Policy Denials",
        "OpenAI API Cost and Error Rate",
        "Data Ingestion and GX Validation",
        "Backtest Runtime and Failure",
        "Connector Health",
        "Trading Safety Lock",
    }.issubset(names)


def test_openbb_widgets_are_read_only_contract(db):
    result = openbb_widgets(db)
    widget_ids = {item["id"] for item in result["widgets"]}
    assert {"strategy-registry", "backtest-summary", "factor-library", "risk-review", "research-progress"}.issubset(widget_ids)
    assert result["mode"] == "read_only"
    assert result["audit_required"] is True
    assert result["audited_endpoint"] == "/api/v1/ui/openbb/widgets.json"
    assert all(item["mode"] == "read_only" and item["audit_required"] is True for item in result["widgets"])


def test_openbb_widgets_manifest_writes_audit(db):
    result = openbb_widgets(db)

    assert result["observability"]["adapter"] == "openbb_widgets_manifest"
    log = db.query(AuditLog).filter_by(action="external_ui.openbb_widgets_manifest_viewed").one()
    assert log.target_id == "widgets.json"


def test_openbb_widget_view_writes_audit(db):
    result = openbb_widget("strategy-registry", db)

    assert result["mode"] == "read_only"
    assert result["audit_required"] is True
    assert result["audited_endpoint"] == "/api/v1/ui/openbb/widgets/strategy-registry"
    assert result["observability"]["adapter"] == "openbb_widget"
    log = db.query(AuditLog).filter_by(action="external_ui.openbb_widget_viewed").one()
    assert log.target_id == "strategy-registry"


def test_openbb_strategy_widget_returns_lifecycle_data(db):
    db.add(
        StrategyCard(
            strategy_id="strategy-1",
            thesis="Quality momentum",
            universe="US equities",
            current_status="APPROVAL_PENDING",
            approval_status="pending",
            paper_trading_status="not_started",
            live_trading_status="locked",
        )
    )
    db.flush()

    result = openbb_widget("strategy-registry", db)

    assert result["data"] == [
        {
            "strategy_id": "strategy-1",
            "current_status": "APPROVAL_PENDING",
            "approval_status": "pending",
            "paper_trading_status": "not_started",
            "live_trading_status": "locked",
        }
    ]


def test_openbb_unknown_widget_404(db):
    with pytest.raises(Exception, match="OpenBB widget not found"):
        openbb_widget("unknown", db)
