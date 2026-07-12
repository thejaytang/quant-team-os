from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date
from typing import Any

from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.models import RiskReview
from app.services.policy import evaluate_policy

# Large finite sentinels (JSON-serializable, unlike inf) used to force a
# fail-closed verdict when a metric is missing or non-finite (NaN/inf).
FAIL_CLOSED_LOW = -1e12
FAIL_CLOSED_HIGH = 1e12


def _finite_or(value: Any, fallback: float) -> float:
    """Return value as float, or ``fallback`` if it is non-numeric or non-finite."""
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return fallback
    return numeric if math.isfinite(numeric) else fallback


def _finite_int(value: Any) -> int:
    """Return value as int, or 0 if it is non-numeric or non-finite."""
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return 0
    if not math.isfinite(numeric):
        return 0
    return int(numeric)


DEFAULT_POLICY: dict[str, Any] = {
    "research_requirements": {
        "min_backtest_years": 3,
        "require_out_of_sample": True,
        "require_transaction_costs": True,
        "require_slippage_model": True,
        "require_factor_report": True,
    },
    "performance_thresholds": {
        "min_sharpe": 0.8,
        "max_drawdown": 0.25,
        "max_turnover_daily": 0.50,
        "min_trade_count": 50,
    },
    "live_trading": {"enabled": False, "max_notional_usd": 0},
}


@dataclass
class PolicyDecision:
    verdict: str
    hard_rule_results: list[dict[str, Any]]
    risk_summary: dict[str, Any]


def evaluate_risk_gate(
    db: Session,
    metrics: dict[str, Any],
    cost_model: dict[str, Any] | None,
    slippage_model: dict[str, Any] | None,
    factor_report_present: bool,
    start_date: date | None = None,
    end_date: date | None = None,
    request_type: str = "risk_review",
    actor: str = "RiskAgent",
    workflow_id: str | None = None,
    evidence_grade: str = "unverified",
) -> PolicyDecision:
    payload = build_risk_gate_input(
        metrics,
        cost_model,
        slippage_model,
        factor_report_present,
        start_date,
        end_date,
        request_type,
        DEFAULT_POLICY,
        evidence_grade=evidence_grade,
    )
    evaluation = evaluate_policy(db, "risk_gate", "review_backtest", payload, actor=actor, workflow_id=workflow_id)
    return risk_decision_from_reasons(metrics, evaluation.reasons, evaluation.source, evidence_grade=evidence_grade)


def build_risk_gate_input(
    metrics: dict[str, Any],
    cost_model: dict[str, Any] | None,
    slippage_model: dict[str, Any] | None,
    factor_report_present: bool,
    start_date: date | None,
    end_date: date | None,
    request_type: str,
    policy: dict[str, Any],
    evidence_grade: str = "unverified",
) -> dict[str, Any]:
    research = policy.get("research_requirements", {})
    perf = policy.get("performance_thresholds", {})
    # Fail closed: an unknown backtest period must never satisfy the minimum
    # history requirement. Missing dates evaluate as zero years of history.
    backtest_period_known = bool(start_date and end_date)
    backtest_years = (end_date - start_date).days / 365.25 if backtest_period_known else 0.0
    if backtest_years < 0:
        # An inverted (end < start) period is invalid; treat as zero history.
        backtest_years = 0.0
    return {
        "request_type": request_type,
        "metrics": {
            # NaN/inf must fail closed. A non-finite Sharpe or trade count is
            # coerced to a value that always fails its threshold; a non-finite
            # drawdown/turnover (higher is worse) is coerced to a large value.
            "sharpe": _finite_or(metrics.get("sharpe", 0), FAIL_CLOSED_LOW),
            "max_drawdown": _finite_or(metrics.get("max_drawdown", 1), FAIL_CLOSED_HIGH),
            "turnover_daily": _finite_or(metrics.get("turnover_daily", 1), FAIL_CLOSED_HIGH),
            "trade_count": _finite_int(metrics.get("trade_count", 0)),
        },
        "thresholds": {
            "min_sharpe": float(perf.get("min_sharpe", 0.8)),
            "max_drawdown": float(perf.get("max_drawdown", 0.25)),
            "max_turnover_daily": float(perf.get("max_turnover_daily", 0.5)),
            "min_trade_count": int(perf.get("min_trade_count", 50)),
            "min_backtest_years": float(research.get("min_backtest_years", 3)),
        },
        "context": {
            "has_cost_model": bool(cost_model),
            "has_slippage_model": bool(slippage_model),
            "factor_report_present": factor_report_present,
            "backtest_period_known": backtest_period_known,
            "backtest_years": backtest_years,
            "evidence_grade": evidence_grade,
            "strict_evidence": strict_evidence_mode(),
        },
    }


def strict_evidence_mode() -> bool:
    settings = get_settings()
    return settings.app_env.lower() == "production" or not settings.allow_mature_tool_fallback


def risk_decision_from_reasons(metrics: dict[str, Any], reasons: list[str], source: str, evidence_grade: str = "unverified") -> PolicyDecision:
    checks = [{"rule": _rule_for_reason(reason), "passed": False, "detail": reason} for reason in reasons]
    return PolicyDecision(
        verdict="pass" if not reasons else "fail",
        hard_rule_results=checks,
        risk_summary={"failed_rules": len(reasons), "metrics": metrics, "policy_source": source, "evidence_grade": evidence_grade},
    )


def persist_risk_review(
    db: Session,
    decision: PolicyDecision,
    *,
    strategy_id: Any,
    backtest_run_id: Any,
    actor: str = "RiskAgent",
) -> RiskReview | None:
    if not strategy_id or not backtest_run_id:
        return None
    review = RiskReview(
        strategy_id=str(strategy_id),
        backtest_run_id=str(backtest_run_id),
        verdict=decision.verdict,
        hard_rule_results=decision.hard_rule_results,
        risk_summary={**decision.risk_summary, "verdict": decision.verdict},
        created_by_agent=actor,
    )
    db.add(review)
    db.flush()
    return review


def _rule_for_reason(reason: str) -> str:
    return {
        "live trading disabled in MVP": "live_trading_locked",
        "cost model is required": "transaction_costs_required",
        "slippage model is required": "slippage_model_required",
        "factor report artifact is required": "factor_report_required",
        "backtest period is required": "backtest_period_required",
        "verified factor evidence is required": "verified_evidence_required",
        "backtest history is too short": "min_backtest_years",
        "Sharpe below threshold": "min_sharpe",
        "max drawdown above threshold": "max_drawdown",
        "daily turnover above threshold": "max_turnover_daily",
        "not enough trades": "min_trade_count",
    }.get(reason, reason)
