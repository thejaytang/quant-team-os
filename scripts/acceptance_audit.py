from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


@dataclass(frozen=True)
class Probe:
    path: str
    needles: tuple[str, ...]


@dataclass(frozen=True)
class Requirement:
    label: str
    probes: tuple[Probe, ...]


def probe(path: str, *needles: str) -> Probe:
    return Probe(path, needles)


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


MVP_REQUIREMENTS = [
    Requirement("1. Monorepo scaffold", (probe("package.json", '"workspaces"', "apps/control-ui"), probe("apps/api/pyproject.toml", "quant-team-os-api"))),
    Requirement(
        "2. Docker Compose with fixed services",
        (
            probe(
                "infra/docker-compose.yml",
                "postgres:",
                "keycloak:",
                "infisical:",
                "temporal:",
                "temporal-ui:",
                "opa:",
                "minio:",
                "mlflow:",
                "langfuse:",
                "prometheus:",
                "loki:",
                "grafana:",
                "superset:",
                "jupyterlab:",
                "agent-chat:",
                "openbb-backend:",
            ),
        ),
    ),
    Requirement("3. Keycloak realm/client/role bootstrap", (probe("infra/keycloak/realm-export.json", "control-ui", "api", "chainlit", "openbb-backend", "admin", "researcher", "approver"),)),
    Requirement("4. Infisical project/secret-path integration", (probe("apps/api/app/services/infisical.py", "InfisicalClient", "write_connection_secret", "read_secret"), probe(".env.example", "INFISICAL_PROJECT_ID", "KEYCLOAK_CLIENT_SECRET_REF", "OPENAI_API_KEY_REF"))),
    Requirement("5. Temporal workflows and workers", (probe("apps/workers/workflows.py", "ResearchWorkflow", "PaperPromotionWorkflow", "ApprovalSignalState"), probe("apps/workers/worker_main.py", "Worker", "configured_workflows", "configured_activities"))),
    Requirement("6. OPA policy bundle and policy tests", (probe("policy/opa/trading_lock.rego", "package qto.trading_lock"), probe("scripts/opa_policy_gate.py", "opa", "test"), probe("policy/tests/qto_policy_test.rego", "test_live_trading_denied_when_locked"))),
    Requirement("7. FastAPI thin orchestration API", (probe("apps/api/app/main.py", "include_router", "/api/v1/healthz", "/api/v1/metrics"), probe("apps/api/app/services/workflows.py", "start_workflow", "start_temporal_workflow"))),
    Requirement("8. Quant workbench control UI", (probe("apps/control-ui/src/routes.tsx", "工作台", "策略研究", "智能体管理", "研究管线", "因子和策略", "实验与回测", "研究报告"), probe("apps/control-ui/src/App.tsx", "DashboardPage", "AgentCanvasPage", "approvalComment.trim()"))),
    Requirement("9. Chainlit Agent Chat", (probe("apps/agent-chat/app.py", "@cl.on_message", "render_agent_steps", "@cl.action_callback"),)),
    Requirement("10. OpenBB read-only widget backend", (probe("apps/openbb-backend/app.py", "/widgets.json", "read_only", "audited_endpoint"), probe("apps/api/app/api/routes_external_ui.py", "openbb_widget", "audit_required", "audited_endpoint"))),
    Requirement("11. dlt Massive pipeline skeleton", (probe("apps/workers/activities.py", "DltIngestionActivity", "dataset_version"), probe("apps/api/app/adapters/stubs.py", "class DltAdapter"))),
    Requirement("12. Great Expectations OHLCV suite", (probe("apps/workers/activities.py", "GreatExpectationsValidationActivity", "ohlcv"), probe("apps/api/tests/test_data_quality.py", "test_ohlcv_suite_fails", "expect_column_pair_values_A_to_be_greater_than_B"))),
    Requirement("13. DVC remote config using MinIO", (probe(".dvc/config", "remote", "minio"), probe("infra/docker-compose.yml", "S3_BUCKET_DVC"), probe("apps/workers/activities.py", "DVCVersionActivity"))),
    Requirement("14. MinIO artifact storage", (probe("apps/api/app/services/artifacts.py", "MinIO", "checksum", "s3_bucket_artifacts"), probe("infra/docker-compose.yml", "minio/minio"))),
    Requirement("15. MLflow tracking with MinIO artifact store", (probe("apps/api/app/services/mlflow_tracking.py", "mlflow", "artifact"), probe("infra/docker-compose.yml", "MLFLOW_S3_ENDPOINT_URL"))),
    Requirement("16. Langfuse tracing for agent runs", (probe("apps/api/app/services/langfuse_tracking.py", "log_agent_run_to_langfuse", "AdapterRunner", "ToolContext"), probe("apps/api/app/adapters/stubs.py", "class LangfuseAdapter", "client.trace", "client.flush"))),
    Requirement("17. OTel + Prometheus + Loki + Grafana", (probe("infra/otel-collector/config.yml", "otlp", "prometheus"), probe("infra/prometheus/prometheus.yml", "api", "workers"), probe("infra/grafana/dashboards/quant-team-os-required.json", "Quant Team OS Required Dashboards"))),
    Requirement("18. Strategy workspace", (probe("apps/api/app/api/routes_strategies.py", "StrategyCard", "request-registration", "request-paper-promotion"), probe("apps/control-ui/src/pages/research/FactorsStrategiesPage.tsx", "策略库", "live_trading_status"))),
    Requirement("19. Approval drawer", (probe("apps/api/app/api/routes_approvals.py", "approve", "reject", "request-changes", "human_comment"), probe("apps/control-ui/src/App.tsx", "待办审批", "approvalComment.trim()"))),
    Requirement("20. Agent Canvas audit surfaces", (probe("apps/api/app/api/routes_audit.py", "ToolCall", "PolicyDecision", "ApprovalRequest"), probe("apps/control-ui/src/pages/agents/AgentConfigDrawer.tsx", "audit_logs", "tool_calls", "policy_decisions"))),
    Requirement("21. Qlib sample research activity", (probe("apps/workers/activities.py", "QlibResearchActivity", "Qlib"), probe("apps/api/app/adapters/stubs.py", "class QlibAdapter"))),
    Requirement("22. QuantConnect MCP backtest adapter skeleton", (probe("apps/api/app/adapters/stubs.py", "class QuantConnectMCPAdapter", "run_backtest"), probe("apps/workers/activities.py", "QuantConnectBacktestActivity"))),
    Requirement("23. Alphalens and QuantStats sample reports", (probe("apps/workers/activities.py", "AlphalensReportActivity", "QuantStatsReportActivity"), probe("apps/api/app/adapters/stubs.py", "class AlphalensAdapter", "class QuantStatsAdapter"))),
    Requirement("24. Tool workspaces surfaced in Agent Canvas", (probe("apps/api/app/api/routes_external_ui.py", "/external-workspaces", "QuantConnect Cloud"), probe("apps/control-ui/src/pages/agents/AgentConfigDrawer.tsx", "Open UI", "secret_ref", "permission level"))),
    Requirement("25. Critical tests passing", (probe("package.json", "scripts/release_gate.py", "scripts/acceptance_audit.py", "scripts/opa_policy_gate.py", "pytest apps/api/tests", "apps/control-ui run test"),)),
]


DOD_REQUIREMENTS = [
    Requirement("DoD 1. Open Quant workbench", (probe("package.json", "control-ui:dev"), probe("apps/control-ui/src/App.tsx", "DashboardPage", "ResearchPipelinePage", "AgentCanvasPage"),)),
    Requirement("DoD 2. Login through Keycloak", (probe("apps/control-ui/src/api/client.ts", "Keycloak", "VITE_KEYCLOAK"), probe("scripts/full_stack_doctor.py", "validate_keycloak_api_auth"),)),
    Requirement("DoD 3. Agent tool connections", (probe("apps/api/app/api/routes_agent_graph.py", "openai", "massive", "quantconnect", "mlflow", "langfuse", "openbb", "grafana", "infisical"), probe("apps/control-ui/src/pages/agents/AgentConfigDrawer.tsx", "Connect", "Test", "Open UI", "Secret fields are sent once"))),
    Requirement("DoD 4. Secrets in Infisical, not PostgreSQL", (probe("apps/api/app/services/connections.py", "write_connection_secret", "infisical_secret_path", "redact_secrets"), probe("apps/api/tests/test_secret_refs.py", "not in str"))),
    Requirement("DoD 5-6. Create ResearchIdea and start ResearchWorkflow", (probe("apps/api/app/api/routes_research.py", "create_research_idea", "start-workflow"), probe("apps/workers/workflows.py", "ResearchWorkflow"))),
    Requirement("DoD 7. Temporal UI can see workflow", (probe("infra/docker-compose.yml", "temporal-ui"), probe("scripts/full_stack_doctor.py", "TEMPORAL_UI_URL", "validate_temporal_server_connection"))),
    Requirement("DoD 8. Chainlit can show agent steps", (probe("apps/agent-chat/app.py", "render_agent_steps", "/api/v1/agent-runs", "parse_sse_events"),)),
    Requirement("DoD 9. Langfuse traces", (probe("apps/api/app/services/langfuse_tracking.py", "langfuse_trace_id"), probe("scripts/full_stack_doctor.py", "validate_langfuse_trace_readable"))),
    Requirement("DoD 10. dlt/GX/DVC versioned dataset artifact", (probe("apps/workers/workflows.py", "DltIngestionActivity", "GreatExpectationsValidationActivity", "DVCVersionActivity"), probe("scripts/full_stack_doctor.py", "validate_dvc_minio_roundtrip"))),
    Requirement("DoD 11. Qlib/Alphalens/QuantStats artifacts", (probe("apps/workers/activities.py", "QlibResearchActivity", "AlphalensReportActivity", "QuantStatsReportActivity", "artifacts"),)),
    Requirement("DoD 12. StrategyCard appears", (probe("apps/workers/activities.py", "StrategyCard", "StrategyRegistrationFinalizeActivity"), probe("apps/control-ui/src/api/types.ts", "type StrategyCard"))),
    Requirement("DoD 13-14. Approval pending and human approval resumes", (probe("apps/workers/workflows.py", "wait_condition", "approval_resolved"), probe("apps/api/app/api/routes_approvals.py", "human_comment", "resolve_approval"))),
    Requirement("DoD 15. MLflow experiment run", (probe("apps/workers/activities.py", "MLflowBacktestActivity"), probe("scripts/full_stack_doctor.py", "validate_mlflow_run_smoke"))),
    Requirement("DoD 16. OpenBB read-only widgets", (probe("apps/openbb-backend/app.py", "read_only", "audited_endpoint"), probe("scripts/full_stack_doctor.py", "validate_openbb_widget_audit_rows"))),
    Requirement("DoD 17. Superset dashboard", (probe("infra/superset/dashboards/strategy_backtest_aggregate.json", "Strategy and Backtest Aggregate"), probe("scripts/full_stack_doctor.py", "validate_superset_chart_queries"))),
    Requirement("DoD 18. Grafana runtime monitoring", (probe("infra/grafana/dashboards/quant-team-os-required.json", "Agent Runtime Monitoring"), probe("scripts/full_stack_doctor.py", "validate_grafana_dashboard_queries"))),
    Requirement("DoD 19. Audit Log traces tool/policy/approval", (probe("apps/api/app/api/routes_audit.py", "_tool_call_event", "_policy_decision_event", "_approval_request_event"),)),
    Requirement("DoD 20. Live trading remains locked", (probe("policy/opa/trading_lock.rego", "live trading is locked"), probe(".env.example", "ALLOW_LIVE_TRADING=false"))),
]


LIVE_EVIDENCE = [
    ("Control UI HTTP", ("CONTROL_UI_URL", "control ui")),
    ("Keycloak protected API auth", ("validate_keycloak_api_auth", "/protocol/openid-connect/token")),
    ("Infisical machine identity and internal refs", ("validate_infisical_machine_identity", "INFISICAL_INTERNAL_SECRET_REFS")),
    ("Temporal server, workers, approval signal", ("validate_temporal_server_connection", "validate_temporal_worker_registration", "_signal_temporal_approval")),
    ("OpenBB widgets and audit rows", ("validate_openbb_widget_contracts", "validate_openbb_widget_audit_rows")),
    ("Langfuse public trace readback", ("validate_langfuse_trace_readable", "/api/public/traces/")),
    ("MLflow SDK run and artifact", ("validate_mlflow_run_smoke", "mlflow.log_artifact")),
    ("Prometheus targets", ("validate_prometheus_targets", "/api/v1/targets")),
    ("Grafana dashboard query execution", ("validate_grafana_dashboard_queries", "_validate_prometheus_query", "_validate_loki_query")),
    ("Superset chart SQL execution", ("validate_superset_chart_queries", "/api/v1/sqllab/execute/")),
    ("Chainlit bridge smoke", ("validate_chainlit_bridge_smoke", 'service="agent-chat"')),
    ("MinIO and DVC roundtrip", ("validate_minio_buckets", "validate_dvc_minio_roundtrip")),
]

MUST_NOT_FORBIDDEN_TERMS = (
    "APP_MASTER_KEY",
    "PaperExecutionAdapter",
    "SandboxCodeRunner",
    "RiskPolicyEngine",
)

MUST_NOT_FORBIDDEN_SDK_TERMS = (
    "ib_insync",
    "ibapi",
    "placeOrder",
    "place_order",
)


def check_requirement(req: Requirement) -> list[str]:
    failures: list[str] = []
    for item in req.probes:
        path = ROOT / item.path
        if not path.exists():
            failures.append(f"{req.label}: missing file {item.path}")
            continue
        text = path.read_text(encoding="utf-8")
        for needle in item.needles:
            if needle not in text:
                failures.append(f"{req.label}: {item.path} missing {needle}")
    return failures


def check_live_mapping() -> list[str]:
    doctor = read("scripts/full_stack_doctor.py")
    runbook = read("docs/runbooks/v0_3_acceptance.md")
    failures: list[str] = []
    for label, needles in LIVE_EVIDENCE:
        for needle in needles:
            if needle not in doctor:
                failures.append(f"Live evidence mapping missing in full_stack_doctor for {label}: {needle}")
        if label.split()[0] not in runbook:
            failures.append(f"Live evidence mapping missing from runbook for {label}")
    return failures


def check_mature_tool_clones() -> list[str]:
    failures: list[str] = []
    script = read("scripts/clone_tools.sh")
    for line in script.splitlines():
        if not line.startswith("clone_one "):
            continue
        parts = line.split()
        if len(parts) < 3:
            failures.append(f"clone_tools.sh has invalid clone line: {line}")
            continue
        name = parts[1]
        repo = parts[2]
        if not repo.startswith("https://github.com/"):
            failures.append(f"mature tool clone must use GitHub source URL: {name}")
        if not (ROOT / "vendor" / name / ".git").exists():
            failures.append(f"mature tool repository is not cloned under vendor: {name}")
    return failures


def check_must_not_implement() -> list[str]:
    failures: list[str] = []
    for path in (ROOT / "apps").rglob("*.py"):
        if "/tests/" in path.as_posix():
            continue
        text = path.read_text(encoding="utf-8")
        for term in MUST_NOT_FORBIDDEN_TERMS:
            if term in text:
                failures.append(f"Must not implement legacy component in {path.relative_to(ROOT)}: {term}")
        for term in MUST_NOT_FORBIDDEN_SDK_TERMS:
            if term in text:
                failures.append(f"Must not implement direct IBKR API path in {path.relative_to(ROOT)}: {term}")
    adapters = read("apps/api/app/adapters/stubs.py")
    for needle in ["class IBKRLockedAdapter", "def run_live_order", "raise PermissionError", "Live trading is locked"]:
        if needle not in adapters:
            failures.append(f"IBKR adapter must stay locked-only: {needle}")
    agent_policy = read("policy/opa/agent.rego")
    for needle in ["run_arbitrary_code", "arbitrary agent code execution is disabled"]:
        if needle not in agent_policy:
            failures.append(f"Arbitrary agent code execution must remain denied by OPA: {needle}")
    return failures


def main() -> int:
    failures: list[str] = []
    for req in [*MVP_REQUIREMENTS, *DOD_REQUIREMENTS]:
        failures.extend(check_requirement(req))
    failures.extend(check_mature_tool_clones())
    failures.extend(check_must_not_implement())
    failures.extend(check_live_mapping())

    if failures:
        print("acceptance audit failed:")
        for failure in failures:
            print(f"- {failure}")
        return 1

    print(f"acceptance audit passed: {len(MVP_REQUIREMENTS)} MVP items, {len(DOD_REQUIREMENTS)} DoD checks, {len(LIVE_EVIDENCE)} live evidence mappings, must-not checks")
    print("live evidence still requires Docker Compose and manual external provider credentials where applicable")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
