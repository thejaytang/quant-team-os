from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import httpx
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.redaction import contains_secret, redact_secrets
from app.db.models import PolicyDecision

AGENT_TOOL_ALLOWLIST = {
    "ChiefAgent": {"openai", "rd_agent"},
    "ResearchAgent": {"openai", "rd_agent", "qlib", "alphalens", "duckdb", "report_artifact"},
    "DataAgent": {"massive", "massive_mcp", "dlt", "great_expectations", "dvc", "duckdb", "minio_artifact"},
    "FactorAgent": {"qlib", "alphalens", "duckdb", "minio_artifact"},
    "BacktestAgent": {"dvc", "quantconnect_mcp", "quantstats", "mlflow", "duckdb", "minio_artifact"},
    "RiskAgent": {"opa", "duckdb"},
    "ReportAgent": {"report_artifact", "mlflow", "duckdb", "minio_artifact"},
    "ExecutionAgent": {"quantconnect_paper"},
    "ConnectionTestAgent": {
        "openai",
        "massive",
        "massive_mcp",
        "quantconnect_mcp",
        "openbb_widget",
        "mlflow",
        "langfuse",
        "superset_link",
        "grafana_link",
        "temporal_workflow",
        "jupyterlab_link",
        "infisical",
        "keycloak_user",
        "minio_artifact",
        "chainlit_link",
    },
    "LangfuseService": {"langfuse"},
    "openbb-backend": {"keycloak_service_token"},
}
TRUSTED_SECRET_REF_ACTORS = {"LangfuseService", "openbb-backend"}
SECRET_PAYLOAD_KEYS = {
    "secret",
    "api_key",
    "api_token",
    "access_token",
    "refresh_token",
    "client_secret",
    "secret_key",
    "private_key",
    "password",
    "credential",
    "credentials",
    "authorization",
}


@dataclass(frozen=True)
class PolicyEvaluation:
    allowed: bool
    reasons: list[str]
    source: str


def evaluate_policy(
    db: Session,
    policy_package: str,
    action: str,
    input_payload: dict[str, Any],
    actor: str = "system",
    workflow_id: str | None = None,
) -> PolicyEvaluation:
    clean_input = redact_secrets(input_payload)
    evaluation = _opa_http(policy_package, clean_input)
    if evaluation is None:
        if not get_settings().allow_local_policy_fallback:
            raise RuntimeError(f"OPA policy evaluation failed: {policy_package}")
        evaluation = _local_policy(policy_package, clean_input)
    row = PolicyDecision(
        policy_package=policy_package,
        action=action,
        allowed=evaluation.allowed,
        input_payload=clean_input,
        reasons=evaluation.reasons,
        workflow_id=workflow_id,
        actor=actor,
    )
    db.add(row)
    db.flush()
    from app.services.audit import write_audit_log

    write_audit_log(
        db,
        f"policy_decision.{'allowed' if evaluation.allowed else 'denied'}",
        "policy_decision",
        row.id,
        {
            "policy_package": policy_package,
            "action": action,
            "allowed": evaluation.allowed,
            "reasons": evaluation.reasons,
            "workflow_id": workflow_id,
        },
        actor=actor,
    )
    return evaluation


def _opa_http(policy_package: str, input_payload: dict[str, Any]) -> PolicyEvaluation | None:
    url = f"{get_settings().opa_url.rstrip('/')}/v1/data/qto/{policy_package}"
    try:
        response = httpx.post(url, json={"input": input_payload}, timeout=0.5)
        response.raise_for_status()
    except Exception:
        return None
    result = response.json().get("result", {})
    denies = sorted(result.get("deny", []))
    allowed = bool(result.get("allow", False)) and not denies
    return PolicyEvaluation(allowed=allowed, reasons=denies, source="opa")


def _local_policy(policy_package: str, input_payload: dict[str, Any]) -> PolicyEvaluation:
    # ponytail: mirrors the tiny Rego bundle for tests/dev when OPA is not running.
    reasons: list[str] = []
    if policy_package == "trading_lock":
        if input_payload.get("action") == "live_order" and input_payload.get("system", {}).get("allow_live_trading") is False:
            reasons.append("live trading is locked")
        return PolicyEvaluation(allowed=not reasons, reasons=reasons, source="local_fallback")

    if policy_package == "agent":
        actor = str(input_payload.get("agent", {}).get("name") or "")
        tool_name = str(input_payload.get("tool", {}).get("name") or "")
        if input_payload.get("action") != "tool_call":
            reasons.append("agent action must be tool_call")
        if tool_name and tool_name not in AGENT_TOOL_ALLOWLIST.get(actor, set()):
            reasons.append("agent is not allowed to call this tool")
        if input_payload.get("agent", {}).get("service_account") is True and input_payload.get("action") in {"approve", "reject"}:
            reasons.append("agent cannot approve or reject approvals")
        if input_payload.get("action") == "run_arbitrary_code" and input_payload.get("system", {}).get("allow_agent_arbitrary_code_execution") is False:
            reasons.append("arbitrary agent code execution is disabled")
        return PolicyEvaluation(allowed=not reasons, reasons=reasons, source="local_fallback")

    if policy_package == "connector":
        if input_payload.get("connection", {}).get("status") != "connected":
            reasons.append("connector is not connected")
        payload = input_payload.get("payload", {})
        payload_meta = input_payload.get("payload_meta", {})
        if any(key in payload for key in SECRET_PAYLOAD_KEYS) or payload_meta.get("sensitive_value_present") is True or contains_secret(payload):
            reasons.append("secret must not be present in tool payload")
        if payload_meta.get("ref_requested") is True and input_payload.get("agent", {}).get("name") not in TRUSTED_SECRET_REF_ACTORS:
            reasons.append("secret refs must be resolved by trusted service adapters")
        return PolicyEvaluation(allowed=not reasons, reasons=reasons, source="local_fallback")

    if policy_package == "approval":
        if input_payload.get("request_type") == "unlock_live" and input_payload.get("action") in {"create_request", "approved"}:
            reasons.append("Live trading is locked by OPA")
        roles = input_payload.get("user", {}).get("roles", [])
        if "approver" not in roles:
            reasons.append("approver role is required")
        if not input_payload.get("comment"):
            reasons.append("human comment is required")
        if input_payload.get("agent", {}).get("service_account") is True:
            reasons.append("agent service account cannot resolve approval")
        return PolicyEvaluation(allowed=not reasons, reasons=reasons, source="local_fallback")

    if policy_package == "risk_gate":
        metrics = input_payload.get("metrics", {})
        thresholds = input_payload.get("thresholds", {})
        context = input_payload.get("context", {})
        if input_payload.get("request_type") == "unlock_live":
            reasons.append("live trading disabled in MVP")
        if context.get("has_cost_model") is not True:
            reasons.append("cost model is required")
        if context.get("has_slippage_model") is not True:
            reasons.append("slippage model is required")
        if context.get("factor_report_present") is not True:
            reasons.append("factor report artifact is required")
        if context.get("strict_evidence") is True and context.get("evidence_grade") != "verified":
            reasons.append("verified factor evidence is required")
        if context.get("backtest_period_known") is not True:
            reasons.append("backtest period is required")
        # Fail closed: unknown backtest history counts as zero years.
        if float(context.get("backtest_years", 0)) < float(thresholds.get("min_backtest_years", 3)):
            reasons.append("backtest history is too short")
        if float(metrics.get("sharpe", 0)) < float(thresholds.get("min_sharpe", 0.8)):
            reasons.append("Sharpe below threshold")
        if abs(float(metrics.get("max_drawdown", 1))) > float(thresholds.get("max_drawdown", 0.25)):
            reasons.append("max drawdown above threshold")
        if float(metrics.get("turnover_daily", 1)) > float(thresholds.get("max_turnover_daily", 0.5)):
            reasons.append("daily turnover above threshold")
        if int(metrics.get("trade_count", 0)) < int(thresholds.get("min_trade_count", 50)):
            reasons.append("not enough trades")
        return PolicyEvaluation(allowed=not reasons, reasons=reasons, source="local_fallback")

    if policy_package == "strategy_lifecycle":
        strategy = input_payload.get("strategy", {})
        approval = input_payload.get("approval", {})
        backtest = strategy.get("latest_backtest", {})
        if approval.get("approved_by_human") is not True:
            reasons.append("human approval is required")
        if approval.get("status") != "approved":
            reasons.append("approved approval is required")
        if input_payload.get("action") == "register_strategy" and strategy.get("latest_risk_review", {}).get("verdict") != "pass":
            reasons.append("latest risk review must pass")
        if input_payload.get("action") == "promote_to_paper":
            if strategy.get("latest_risk_review", {}).get("verdict") != "pass":
                reasons.append("latest risk review must pass")
            if backtest.get("has_cost_model") is not True:
                reasons.append("cost model is required")
            if backtest.get("has_slippage_model") is not True:
                reasons.append("slippage model is required")
        return PolicyEvaluation(allowed=not reasons, reasons=reasons, source="local_fallback")

    if policy_package == "ui_surface":
        surface = input_payload.get("surface")
        action = input_payload.get("action")
        core_mutations = {"create_strategy", "update_strategy", "set_strategy_status", "register_strategy", "promote_to_paper"}
        read_actions = {"read", "view", "query", "list"}
        if surface == "chainlit" and action in core_mutations:
            reasons.append("Chainlit cannot directly mutate core state")
        if surface in {"openbb", "superset", "grafana", "jupyterlab"} and action not in read_actions:
            reasons.append("external workspace is read-only for core state")
        return PolicyEvaluation(allowed=not reasons, reasons=reasons, source="local_fallback")

    return PolicyEvaluation(allowed=True, reasons=[], source="local_fallback")
