from app.db.session import init_db
from app.services.connections import seed_connections
from app.services.infisical import validate_infisical_runtime_settings
from app.services.observability import configure_otel

try:
    from fastapi import FastAPI, Response
    from fastapi.middleware.cors import CORSMiddleware
except ModuleNotFoundError:  # pragma: no cover
    FastAPI = None
    Response = None
    CORSMiddleware = None


def create_app():
    if FastAPI is None:
        raise RuntimeError("FastAPI is not installed. Run `pip install -e apps/api`.")

    app = FastAPI(title="Quant Team OS", version="0.3.0")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[
            "http://localhost:3000",
            "http://127.0.0.1:3000",
            "http://localhost:5173",
            "http://127.0.0.1:5173",
            "http://localhost:8001",
            "http://127.0.0.1:8001",
        ],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    from app.api import (
        routes_agent_graph,
        routes_agent_runs,
        routes_approvals,
        routes_artifacts,
        routes_audit,
        routes_backtests,
        routes_connections,
        routes_dashboard,
        routes_data_quality,
        routes_external_ui,
        routes_factors,
        routes_internal,
        routes_paper_trading,
        routes_research,
        routes_research_workspace,
        routes_risk,
        routes_settings,
        routes_strategies,
        routes_workflows,
    )
    from app.api.compat import Depends
    from app.core.auth import get_current_user
    from app.db.session import SessionLocal

    auth_dependencies = [Depends(get_current_user)]
    app.include_router(routes_internal.router)
    app.include_router(routes_connections.router, dependencies=auth_dependencies)
    app.include_router(routes_dashboard.router, dependencies=auth_dependencies)
    app.include_router(routes_data_quality.router, dependencies=auth_dependencies)
    app.include_router(routes_agent_runs.router, dependencies=auth_dependencies)
    app.include_router(routes_agent_graph.router, dependencies=auth_dependencies)
    app.include_router(routes_research.router, dependencies=auth_dependencies)
    app.include_router(routes_research_workspace.router, dependencies=auth_dependencies)
    app.include_router(routes_factors.router, dependencies=auth_dependencies)
    app.include_router(routes_external_ui.router, dependencies=auth_dependencies)
    app.include_router(routes_strategies.router, dependencies=auth_dependencies)
    app.include_router(routes_backtests.router, dependencies=auth_dependencies)
    app.include_router(routes_risk.router, dependencies=auth_dependencies)
    app.include_router(routes_settings.router, dependencies=auth_dependencies)
    app.include_router(routes_workflows.router, dependencies=auth_dependencies)
    app.include_router(routes_paper_trading.router, dependencies=auth_dependencies)
    app.include_router(routes_approvals.router, dependencies=auth_dependencies)
    app.include_router(routes_artifacts.router, dependencies=auth_dependencies)
    app.include_router(routes_audit.router, dependencies=auth_dependencies)

    @app.on_event("startup")
    def startup() -> None:
        validate_infisical_runtime_settings()
        configure_otel()
        init_db()
        with SessionLocal() as db:
            seed_connections(db)
            db.commit()

    @app.get("/api/v1/healthz")
    @app.get("/healthz")
    def healthz():
        return {"ok": True, "live_trading": "locked"}

    @app.get("/api/v1/metrics")
    @app.get("/metrics")
    def metrics():
        with SessionLocal() as db:
            return Response(content=prometheus_metrics_text(db), media_type="text/plain; version=0.0.4")

    return app


def prometheus_metrics_text(db=None) -> str:
    counts = _metric_counts(db)
    lines = [
        "# HELP qto_app_info Quant Team OS application info.",
        "# TYPE qto_app_info gauge",
        'qto_app_info{version="0.3.0"} 1',
        "# HELP qto_live_trading_locked Whether live trading is locked.",
        "# TYPE qto_live_trading_locked gauge",
        "qto_live_trading_locked 1",
        "# HELP qto_tool_policy_denials_total ToolGateway policy denial count.",
        "# TYPE qto_tool_policy_denials_total counter",
        f"qto_tool_policy_denials_total {counts['policy_denials']}",
        "# HELP qto_openai_cost_usd_total OpenAI estimated cost in USD.",
        "# TYPE qto_openai_cost_usd_total counter",
        f"qto_openai_cost_usd_total {counts['openai_cost_usd']}",
        "# HELP qto_openai_errors_total OpenAI adapter error count.",
        "# TYPE qto_openai_errors_total counter",
        f"qto_openai_errors_total {counts['openai_errors']}",
        "# HELP qto_workflow_runs_total Workflow run count by status.",
        "# TYPE qto_workflow_runs_total counter",
        *[
            f'qto_workflow_runs_total{{status="{_metric_label(status)}"}} {count}'
            for status, count in counts["workflow_statuses"].items()
        ],
        "# HELP qto_gx_validations_total Great Expectations validation count by result.",
        "# TYPE qto_gx_validations_total counter",
        *[
            f'qto_gx_validations_total{{result="{_metric_label(result)}"}} {count}'
            for result, count in counts["gx_results"].items()
        ],
        "# HELP qto_backtest_failures_total Backtest failure count.",
        "# TYPE qto_backtest_failures_total counter",
        f"qto_backtest_failures_total {counts['backtest_failures']}",
        "# HELP qto_connection_status Connector status by provider.",
        "# TYPE qto_connection_status gauge",
        *[
            f'qto_connection_status{{provider="{_metric_label(provider)}",status="{_metric_label(status)}"}} {value}'
            for provider, status, value in counts["connection_statuses"]
        ],
        "",
    ]
    return "\n".join(lines)


def _metric_counts(db) -> dict:
    if db is None:
        return {
            "policy_denials": 0,
            "openai_cost_usd": 0,
            "openai_errors": 0,
            "workflow_statuses": {"started": 0},
            "gx_results": {"passed": 0},
            "backtest_failures": 0,
            "connection_statuses": [("openai", "connected", 0)],
        }
    from app.db.models import Artifact, BacktestRun, ExternalConnection, PolicyDecision, ToolCall, WorkflowLink

    workflows = {}
    for row in db.query(WorkflowLink.status).all():
        workflows[row.status] = workflows.get(row.status, 0) + 1
    gx_results = {"passed": 0, "failed": 0}
    for artifact in db.query(Artifact).all():
        if "gx_success" in (artifact.meta or {}):
            key = "passed" if artifact.meta.get("gx_success") else "failed"
            gx_results[key] = gx_results.get(key, 0) + 1
    openai_cost = 0.0
    for call in db.query(ToolCall).filter(ToolCall.adapter_name == "openai").all():
        openai_cost += _payload_cost_usd(call.output_payload or {})
    return {
        "policy_denials": db.query(PolicyDecision).filter(PolicyDecision.allowed.is_(False)).count(),
        "openai_cost_usd": openai_cost,
        "openai_errors": db.query(ToolCall).filter(ToolCall.adapter_name == "openai", ToolCall.status == "failed").count(),
        "workflow_statuses": workflows or {"started": 0},
        "gx_results": gx_results,
        "backtest_failures": db.query(BacktestRun).filter(BacktestRun.status == "failed").count(),
        "connection_statuses": [
            (row.provider, row.status, 1)
            for row in db.query(ExternalConnection).all()
        ] or [("openai", "connected", 0)],
    }


def _metric_label(value) -> str:
    return str(value).replace("\\", "\\\\").replace('"', '\\"')


def _payload_cost_usd(payload: dict) -> float:
    for key in ("cost_usd", "openai_cost_usd", "estimated_cost_usd"):
        value = payload.get(key)
        if isinstance(value, (int, float)):
            return float(value)
    usage = payload.get("usage")
    if isinstance(usage, dict):
        value = usage.get("cost_usd")
        if isinstance(value, (int, float)):
            return float(value)
    return 0.0


app = create_app() if FastAPI is not None else None
