from __future__ import annotations

from typing import Any, ClassVar

from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.adapters.base import ToolAdapter, ToolContext, ToolResult
from app.db.models import ExternalConnection


class OpenAIAgentPlan(BaseModel):
    objective: str
    steps: list[str] = Field(default_factory=list)
    required_tools: list[str] = Field(default_factory=list)


class BaseStubAdapter(ToolAdapter):
    name = "base"
    risk_level = "read_only"
    provider: str | None = None

    def validate_connection(self, db: Session, connection_id: str | None) -> ToolResult:
        if not self.provider:
            return ToolResult(ok=True)
        stmt = select(ExternalConnection).where(ExternalConnection.provider == self.provider)
        if connection_id:
            stmt = select(ExternalConnection).where(ExternalConnection.id == connection_id)
        connection = db.scalar(stmt)
        if connection and connection.status in {"connected", "locked", "testing"}:
            return ToolResult(ok=True, output={"status": connection.status})
        return ToolResult(ok=False, error=f"{self.provider} is not connected")

    def validate_input(self, payload: dict[str, Any]) -> None:
        return None

    def run(self, db: Session, payload: dict[str, Any], context: ToolContext) -> ToolResult:
        missing = self._missing_required(payload)
        if missing:
            return ToolResult(ok=False, output={"adapter": self.name, "mode": "stub", "missing_required": missing}, error=f"missing required fields: {', '.join(missing)}")
        return ToolResult(ok=True, output={"adapter": self.name, "mode": "stub"})

    def _missing_required(self, payload: dict[str, Any]) -> list[str]:
        required = payload.get("required_fields") or []
        if not isinstance(required, list):
            return []
        return [str(field) for field in required if not payload.get(str(field))]


class OpenAIAdapter(BaseStubAdapter):
    name = "openai"
    risk_level = "research_write"
    provider = "openai"

    def run(self, db: Session, payload: dict[str, Any], context: ToolContext) -> ToolResult:
        missing = self._missing_required(payload)
        if missing:
            return ToolResult(ok=False, output={"adapter": self.name, "mode": "stub", "missing_required": missing}, error=f"missing required fields: {', '.join(missing)}")
        if payload.get("purpose") == "agent_plan":
            return self._run_agent_plan(payload)
        return ToolResult(
            ok=True,
            output={"adapter": self.name, "mode": "stub", "credential_available": bool(payload.get("api_key"))},
        )

    def _run_agent_plan(self, payload: dict[str, Any]) -> ToolResult:
        api_key = payload.get("api_key")
        if not api_key:
            return ToolResult(ok=False, output={"adapter": self.name, "mode": "openai_agents_sdk"}, error="OpenAI API key secret is missing")
        from agents import Agent, Runner, set_default_openai_key

        set_default_openai_key(str(api_key), use_for_tracing=False)
        specialists = [
            Agent(name=name, instructions=instructions, handoff_description=description)
            for name, instructions, description in [
                ("ResearchAgent", "Generate testable quant hypotheses. Do not approve or trade.", "Research hypothesis specialist."),
                ("DataAgent", "Plan dataset preparation and quality checks. Do not bypass validation.", "Data ingestion and quality specialist."),
                ("FactorAgent", "Plan factor analysis and factor tear sheets. Do not skip factor evidence.", "Factor research specialist."),
                ("BacktestAgent", "Plan controlled backtests and performance reports. Do not promote strategy state.", "Backtest specialist."),
                ("RiskAgent", "Explain risk gate evidence and OPA decisions. Do not override policy.", "Risk review specialist."),
                ("ReportAgent", "Summarize evidence into memos and StrategyCards. Do not modify experiment data.", "Reporting specialist."),
            ]
        ]
        agent = Agent(
            name="ChiefAgent",
            instructions="Coordinate the specialist quant team through handoffs and return a concise structured research workflow plan. Do not approve or trade.",
            handoffs=specialists,
            output_type=OpenAIAgentPlan,
        )
        result = Runner.run_sync(agent, str(payload.get("prompt") or ""))
        output = result.final_output
        plan = output.model_dump() if hasattr(output, "model_dump") else OpenAIAgentPlan(objective=str(output)).model_dump()
        return ToolResult(ok=True, output={"adapter": self.name, "mode": "openai_agents_sdk", "plan": plan, "agent_team": [agent.name, *[item.name for item in specialists]]})


class MassiveAdapter(BaseStubAdapter):
    name = "massive"
    provider = "massive"


class MassiveMCPAdapter(MassiveAdapter):
    name = "massive_mcp"


class QuantConnectMCPAdapter(BaseStubAdapter):
    name = "quantconnect_mcp"
    risk_level = "backtest_run"
    provider = "quantconnect"

    actions: ClassVar[set[str]] = {
        "create_project",
        "upload_strategy_files",
        "run_backtest",
        "poll_backtest_status",
        "fetch_backtest_result",
        "fetch_backtest_charts_or_links",
    }

    def validate_input(self, payload: dict[str, Any]) -> None:
        action = payload.get("action", "run_backtest")
        if action not in self.actions:
            raise ValueError(f"unsupported QuantConnect MCP action: {action}")

    def run(self, db: Session, payload: dict[str, Any], context: ToolContext) -> ToolResult:
        action = payload.get("action", "run_backtest")
        method = getattr(self, action)
        return ToolResult(ok=True, output=method(payload))

    def create_project(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._mcp_request("create_project", payload, ["project_name", "language"])

    def upload_strategy_files(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._mcp_request("upload_strategy_files", payload, ["project_id", "files"])

    def run_backtest(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._mcp_request("run_backtest", payload, ["project_id", "backtest_name"])

    def poll_backtest_status(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._mcp_request("poll_backtest_status", payload, ["project_id", "backtest_id"])

    def fetch_backtest_result(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._mcp_request("fetch_backtest_result", payload, ["project_id", "backtest_id"])

    def fetch_backtest_charts_or_links(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._mcp_request("fetch_backtest_charts_or_links", payload, ["project_id", "backtest_id"])

    def _mcp_request(self, action: str, payload: dict[str, Any], fields: list[str]) -> dict[str, Any]:
        return {
            "adapter": self.name,
            "provider": "quantconnect",
            "tool": "QuantConnect MCP Server",
            "action": action,
            "status": "mcp_request_prepared",
            "mode": "external_mcp_required",
            "request": {field: payload.get(field) for field in fields},
        }


class MLflowAdapter(BaseStubAdapter):
    name = "mlflow"
    risk_level = "research_write"
    provider = "mlflow"


class QlibAdapter(BaseStubAdapter):
    name = "qlib"
    risk_level = "research_write"

    def run(self, db: Session, payload: dict[str, Any], context: ToolContext) -> ToolResult:
        return ToolResult(ok=True, output=self.prepare_factor_research(payload))

    def prepare_factor_research(self, payload: dict[str, Any]) -> dict[str, Any]:
        return {
            "adapter": self.name,
            "tool": "Qlib",
            "action": "run_factor_research",
            "status": "tool_request_prepared",
            "mode": "external_tool_required",
            "request": {
                "dataset_spec_id": payload.get("dataset_spec_id"),
                "factor_spec_id": payload.get("factor_spec_id"),
                "model": payload.get("model", "lightgbm"),
            },
        }


class RDAgentAdapter(BaseStubAdapter):
    name = "rd_agent"
    risk_level = "research_write"

    def run(self, db: Session, payload: dict[str, Any], context: ToolContext) -> ToolResult:
        return ToolResult(ok=True, output=self.prepare_research_job(payload))

    def prepare_research_job(self, payload: dict[str, Any]) -> dict[str, Any]:
        return {
            "adapter": self.name,
            "tool": "RD-Agent",
            "action": "generate_research_ideas",
            "status": "tool_request_prepared",
            "mode": "external_tool_required",
            "request": {"research_idea_id": payload.get("research_idea_id"), "objective": payload.get("objective")},
        }


class AlphalensAdapter(BaseStubAdapter):
    name = "alphalens"
    risk_level = "research_write"

    def run(self, db: Session, payload: dict[str, Any], context: ToolContext) -> ToolResult:
        return ToolResult(ok=True, output=self.create_factor_report(payload))

    def create_factor_report(self, payload: dict[str, Any]) -> dict[str, Any]:
        return {
            "adapter": self.name,
            "tool": "alphalens-reloaded",
            "action": "create_factor_tear_sheet",
            "status": "report_request_prepared",
            "mode": "external_tool_required",
            "request": {"factor_spec_id": payload.get("factor_spec_id"), "dataset_spec_id": payload.get("dataset_spec_id")},
        }


class QuantStatsAdapter(BaseStubAdapter):
    name = "quantstats"
    risk_level = "research_write"

    def run(self, db: Session, payload: dict[str, Any], context: ToolContext) -> ToolResult:
        return ToolResult(ok=True, output=self.create_strategy_report(payload))

    def create_strategy_report(self, payload: dict[str, Any]) -> dict[str, Any]:
        return {
            "adapter": self.name,
            "tool": "QuantStats",
            "action": "create_strategy_tear_sheet",
            "status": "report_request_prepared",
            "mode": "external_tool_required",
            "request": {"backtest_run_id": payload.get("backtest_run_id"), "strategy_id": payload.get("strategy_id")},
        }


class PyPortfolioOptAdapter(BaseStubAdapter):
    name = "pyportfolioopt"
    risk_level = "research_write"

    def run(self, db: Session, payload: dict[str, Any], context: ToolContext) -> ToolResult:
        return ToolResult(ok=True, output=self.suggest_weights(payload))

    def suggest_weights(self, payload: dict[str, Any]) -> dict[str, Any]:
        return {
            "adapter": self.name,
            "tool": "PyPortfolioOpt",
            "action": "suggest_target_weights",
            "status": "tool_request_prepared",
            "mode": "external_tool_required",
            "request": {"expected_returns": payload.get("expected_returns", {}), "risk_model": payload.get("risk_model", {})},
        }


class DuckDBAdapter(BaseStubAdapter):
    name = "duckdb"

    def run(self, db: Session, payload: dict[str, Any], context: ToolContext) -> ToolResult:
        action = payload.get("action", "query_bars")
        actions = {
            "query_bars": lambda: self.query_bars(
                payload.get("symbols", []),
                payload.get("start"),
                payload.get("end"),
                payload.get("frequency", "1d"),
                payload.get("dataset_version"),
                path=payload.get("path") or payload.get("dataset_path"),
                rows=payload.get("rows"),
            ),
            "query_factor_values": lambda: self.query_factor_values(
                payload.get("factor_id"),
                payload.get("start"),
                payload.get("end"),
                payload.get("dataset_version"),
                path=payload.get("path") or payload.get("factor_values_path"),
                rows=payload.get("rows"),
            ),
            "query_backtest_equity": lambda: self.query_backtest_equity(
                payload.get("backtest_run_id"),
                path=payload.get("path") or payload.get("equity_path"),
                rows=payload.get("rows"),
            ),
            "query_orders": lambda: self.query_orders(
                payload.get("backtest_run_id"),
                path=payload.get("path") or payload.get("orders_path"),
                rows=payload.get("rows"),
            ),
        }
        if action not in actions:
            raise ValueError(f"unsupported DuckDB action: {action}")
        return ToolResult(ok=True, output=actions[action]())

    def query_bars(
        self,
        symbols: list[str],
        start: str | None,
        end: str | None,
        frequency: str,
        dataset_version: str | None,
        *,
        path: str | None = None,
        rows: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        filters = {"symbols": set(symbols or []), "start": start, "end": end, "frequency": frequency, "dataset_version": dataset_version}
        sql_rows = _duckdb_rows(path, "symbol in ({symbols}) and date >= ? and date <= ?", [start or "", end or "9999-12-31"], symbols=symbols, order_by="symbol, date")
        data = sql_rows if sql_rows is not None else _filter_rows(rows or [], filters, symbol_key="symbol", date_key="date")
        return self._query_result("query_bars", data, dataset_version, path)

    def query_factor_values(
        self,
        factor_id: str | None,
        start: str | None,
        end: str | None,
        dataset_version: str | None,
        *,
        path: str | None = None,
        rows: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        sql_rows = _duckdb_rows(path, "factor_id = ? and date >= ? and date <= ?", [factor_id or "", start or "", end or "9999-12-31"], order_by="date, symbol")
        data = sql_rows if sql_rows is not None else [
            row for row in (rows or [])
            if (factor_id is None or row.get("factor_id") == factor_id)
            and (start is None or str(row.get("date", "")) >= start)
            and (end is None or str(row.get("date", "")) <= end)
            and (dataset_version is None or row.get("dataset_version") in {None, dataset_version})
        ]
        return self._query_result("query_factor_values", data, dataset_version, path)

    def query_backtest_equity(
        self,
        backtest_run_id: str | None,
        *,
        path: str | None = None,
        rows: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        sql_rows = _duckdb_rows(path, "backtest_run_id = ?", [backtest_run_id or ""], order_by="timestamp")
        data = sql_rows if sql_rows is not None else [row for row in (rows or []) if backtest_run_id is None or row.get("backtest_run_id") == backtest_run_id]
        return self._query_result("query_backtest_equity", data, None, path)

    def query_orders(
        self,
        backtest_run_id: str | None,
        *,
        path: str | None = None,
        rows: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        sql_rows = _duckdb_rows(path, "backtest_run_id = ?", [backtest_run_id or ""], order_by="timestamp")
        data = sql_rows if sql_rows is not None else [row for row in (rows or []) if backtest_run_id is None or row.get("backtest_run_id") == backtest_run_id]
        return self._query_result("query_orders", data, None, path)

    def _query_result(self, action: str, rows: list[dict[str, Any]], dataset_version: str | None, path: str | None) -> dict[str, Any]:
        return {
            "adapter": self.name,
            "tool": "DuckDB",
            "action": action,
            "status": "queried",
            "mode": "duckdb_parquet" if path and _duckdb_available() else "rows_fallback",
            "dataset_version": dataset_version,
            "row_count": len(rows),
            "rows": rows,
        }


def _filter_rows(rows: list[dict[str, Any]], filters: dict[str, Any], *, symbol_key: str, date_key: str) -> list[dict[str, Any]]:
    symbols = filters.get("symbols") or set()
    start = filters.get("start")
    end = filters.get("end")
    frequency = filters.get("frequency")
    dataset_version = filters.get("dataset_version")
    return [
        row
        for row in rows
        if (not symbols or row.get(symbol_key) in symbols)
        and (start is None or str(row.get(date_key, "")) >= start)
        and (end is None or str(row.get(date_key, "")) <= end)
        and (frequency is None or row.get("frequency") in {None, frequency})
        and (dataset_version is None or row.get("dataset_version") in {None, dataset_version})
    ]


def _duckdb_available() -> bool:
    try:
        import duckdb  # noqa: F401
    except Exception:
        return False
    return True


def _duckdb_rows(path: str | None, where: str, params: list[Any], *, symbols: list[str] | None = None, order_by: str = "") -> list[dict[str, Any]] | None:
    if not path:
        return None
    try:
        import duckdb
    except Exception:
        return None
    symbol_params = list(symbols or [])
    symbol_clause = ", ".join(["?"] * len(symbol_params)) or "null"
    sql = f"select * from read_parquet(?) where {where.format(symbols=symbol_clause)}"
    if order_by:
        sql = f"{sql} order by {order_by}"
    con = duckdb.connect(":memory:")
    try:
        cursor = con.execute(sql, [path, *symbol_params, *params])
        columns = [item[0] for item in cursor.description]
        return [dict(zip(columns, row, strict=True)) for row in cursor.fetchall()]
    finally:
        con.close()


class OPAAdapter(BaseStubAdapter):
    name = "opa"
    risk_level = "backtest_run"
    provider = "opa"


class InfisicalAdapter(BaseStubAdapter):
    name = "infisical"
    provider = "infisical"


class TemporalWorkflowAdapter(BaseStubAdapter):
    name = "temporal_workflow"
    provider = "temporal"


class KeycloakUserAdapter(BaseStubAdapter):
    name = "keycloak_user"
    provider = "keycloak"


class KeycloakServiceTokenAdapter(BaseStubAdapter):
    name = "keycloak_service_token"
    risk_level = "read_only"

    def run(self, db: Session, payload: dict[str, Any], context: ToolContext) -> ToolResult:
        token_url = str(payload.get("token_url") or "")
        client_id = str(payload.get("client_id") or "")
        client_secret = _secret_payload_value(payload, "client_secret")
        if not (token_url and client_id and client_secret):
            return ToolResult(ok=False, output={"adapter": self.name, "mode": "keycloak_service_account"}, error="Keycloak service account credentials are incomplete")

        import httpx

        response = httpx.post(
            token_url,
            data={"grant_type": "client_credentials", "client_id": client_id, "client_secret": client_secret},
            timeout=float(payload.get("timeout_seconds") or 5),
        )
        response.raise_for_status()
        token = response.json().get("access_token")
        if not token:
            return ToolResult(ok=False, output={"adapter": self.name, "mode": "keycloak_service_account"}, error="Keycloak token response did not include access_token")
        return ToolResult(
            ok=True,
            output={"adapter": self.name, "mode": "keycloak_service_account", "credential_available": True},
            private_output={"access_token": str(token)},
        )


class LangfuseAdapter(BaseStubAdapter):
    name = "langfuse"
    risk_level = "research_write"

    def run(self, db: Session, payload: dict[str, Any], context: ToolContext) -> ToolResult:
        from langfuse import Langfuse

        client_kwargs = {"host": payload.get("host")}
        public_key = _secret_payload_value(payload, "public_key")
        secret_key = _secret_payload_value(payload, "secret_key")
        if public_key:
            client_kwargs["public_key"] = public_key
        if secret_key:
            client_kwargs["secret_key"] = secret_key
        client = Langfuse(**{key: value for key, value in client_kwargs.items() if value})
        trace = client.trace(
            name=str(payload.get("name") or "agent.run"),
            input=payload.get("input"),
            output=payload.get("output"),
            metadata=payload.get("metadata") or {},
        )
        trace_id = getattr(trace, "id", None) or getattr(trace, "trace_id", None)
        if hasattr(client, "flush"):
            client.flush()
        return ToolResult(ok=True, output={"adapter": self.name, "mode": "langfuse", "trace_id": trace_id})


def _secret_payload_value(payload: dict[str, Any], preferred_key: str) -> str | None:
    for key in [preferred_key, "value", "secret", "api_key", "key"]:
        value = payload.get(key)
        if value:
            return str(value)
    return None


class DltAdapter(BaseStubAdapter):
    name = "dlt"
    risk_level = "research_write"


class GreatExpectationsAdapter(BaseStubAdapter):
    name = "great_expectations"
    risk_level = "research_write"


class DVCAdapter(BaseStubAdapter):
    name = "dvc"
    risk_level = "research_write"

    def run(self, db: Session, payload: dict[str, Any], context: ToolContext) -> ToolResult:
        action = str(payload.get("action") or "version_dataset")
        return ToolResult(
            ok=True,
            output={
                "adapter": self.name,
                "action": action,
                "mode": "external_tool_boundary",
                "dataset_version": payload.get("dataset_version"),
                "remote": "minio",
            },
        )


class MinIOArtifactAdapter(BaseStubAdapter):
    name = "minio_artifact"
    risk_level = "research_write"
    provider = "minio"


class OpenBBWidgetAdapter(BaseStubAdapter):
    name = "openbb_widget"
    provider = "openbb"


class SupersetLinkAdapter(BaseStubAdapter):
    name = "superset_link"
    provider = "superset"


class GrafanaLinkAdapter(BaseStubAdapter):
    name = "grafana_link"
    provider = "grafana"


class JupyterLabLinkAdapter(BaseStubAdapter):
    name = "jupyterlab_link"
    provider = "jupyterlab"


class ChainlitLinkAdapter(BaseStubAdapter):
    name = "chainlit_link"
    provider = "chainlit"


class ApprovalAdapter(BaseStubAdapter):
    name = "approval"
    risk_level = "paper_trade"


class ReportArtifactAdapter(BaseStubAdapter):
    name = "report_artifact"
    risk_level = "research_write"


class QuantConnectPaperAdapter(BaseStubAdapter):
    name = "quantconnect_paper"
    risk_level = "paper_trade"
    provider = "quantconnect"

    def run(self, db: Session, payload: dict[str, Any], context: ToolContext) -> ToolResult:
        return ToolResult(ok=True, output=self.create_deployment_proposal(payload))

    def create_deployment_proposal(self, payload: dict[str, Any]) -> dict[str, Any]:
        return {
            "mode": "proposal_only",
            "provider": "quantconnect",
            "status": "paper_deployment_proposal_prepared",
            "strategy_id": payload.get("strategy_id"),
            "portfolio": payload.get("portfolio", {}),
        }


class IBKRLockedAdapter(BaseStubAdapter):
    name = "ibkr_locked"
    risk_level = "live_trade"
    provider = "ibkr"

    def run_live_order(self, payload: dict[str, Any]) -> None:
        raise PermissionError("Live trading is locked by design in MVP.")


def default_registry():
    from app.adapters.base import AdapterRegistry

    registry = AdapterRegistry()
    for adapter in (
        OpenAIAdapter(),
        MassiveAdapter(),
        MassiveMCPAdapter(),
        QuantConnectMCPAdapter(),
        MLflowAdapter(),
        QlibAdapter(),
        RDAgentAdapter(),
        AlphalensAdapter(),
        QuantStatsAdapter(),
        PyPortfolioOptAdapter(),
        DuckDBAdapter(),
        OPAAdapter(),
        InfisicalAdapter(),
        TemporalWorkflowAdapter(),
        KeycloakUserAdapter(),
        KeycloakServiceTokenAdapter(),
        LangfuseAdapter(),
        DltAdapter(),
        GreatExpectationsAdapter(),
        DVCAdapter(),
        MinIOArtifactAdapter(),
        OpenBBWidgetAdapter(),
        SupersetLinkAdapter(),
        GrafanaLinkAdapter(),
        JupyterLabLinkAdapter(),
        ChainlitLinkAdapter(),
        ReportArtifactAdapter(),
        QuantConnectPaperAdapter(),
        IBKRLockedAdapter(),
    ):
        registry.register(adapter)
    return registry
