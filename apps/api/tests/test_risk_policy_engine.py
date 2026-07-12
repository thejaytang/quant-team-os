import math
from datetime import date

from app.core.config import get_settings
from app.db.models import PolicyDecision
from app.risk.engine import build_risk_gate_input, evaluate_risk_gate

PASSING_METRICS = {"sharpe": 1.2, "max_drawdown": 0.1, "turnover_daily": 0.2, "trade_count": 100}
PASSING_PERIOD = {"start_date": date(2020, 1, 1), "end_date": date(2025, 1, 1)}


def test_backtest_without_cost_or_slippage_fails(db):
    decision = evaluate_risk_gate(
        db,
        metrics=PASSING_METRICS,
        cost_model={},
        slippage_model={},
        factor_report_present=True,
        **PASSING_PERIOD,
    )
    assert decision.verdict == "fail"
    failed = {item["rule"] for item in decision.hard_rule_results if not item["passed"]}
    assert "transaction_costs_required" in failed
    assert "slippage_model_required" in failed


def test_complete_backtest_passes(db):
    decision = evaluate_risk_gate(
        db,
        metrics=PASSING_METRICS,
        cost_model={"commission_bps": 1},
        slippage_model={"bps": 2},
        factor_report_present=True,
        **PASSING_PERIOD,
    )
    assert decision.verdict == "pass"


def test_missing_backtest_period_fails_closed(db):
    decision = evaluate_risk_gate(
        db,
        metrics=PASSING_METRICS,
        cost_model={"commission_bps": 1},
        slippage_model={"bps": 2},
        factor_report_present=True,
    )
    assert decision.verdict == "fail"
    failed = {item["rule"] for item in decision.hard_rule_results if not item["passed"]}
    assert "backtest_period_required" in failed
    assert "min_backtest_years" in failed


def test_short_backtest_period_fails(db):
    decision = evaluate_risk_gate(
        db,
        metrics=PASSING_METRICS,
        cost_model={"commission_bps": 1},
        slippage_model={"bps": 2},
        factor_report_present=True,
        start_date=date(2024, 1, 1),
        end_date=date(2025, 1, 1),
    )
    assert decision.verdict == "fail"
    failed = {item["rule"] for item in decision.hard_rule_results if not item["passed"]}
    assert "min_backtest_years" in failed


def test_risk_gate_records_evidence_grade_in_summary(db):
    decision = evaluate_risk_gate(
        db,
        metrics=PASSING_METRICS,
        cost_model={"commission_bps": 1},
        slippage_model={"bps": 2},
        factor_report_present=True,
        evidence_grade="sample",
        **PASSING_PERIOD,
    )
    assert decision.risk_summary["evidence_grade"] == "sample"


def test_strict_evidence_mode_rejects_sample_factor_report(db, monkeypatch):
    monkeypatch.setenv("ALLOW_MATURE_TOOL_FALLBACK", "false")
    get_settings.cache_clear()
    try:
        decision = evaluate_risk_gate(
            db,
            metrics=PASSING_METRICS,
            cost_model={"commission_bps": 1},
            slippage_model={"bps": 2},
            factor_report_present=True,
            evidence_grade="sample",
            **PASSING_PERIOD,
        )
    finally:
        get_settings.cache_clear()
    assert decision.verdict == "fail"
    failed = {item["rule"] for item in decision.hard_rule_results if not item["passed"]}
    assert "verified_evidence_required" in failed


def test_strict_evidence_mode_accepts_verified_factor_report(db, monkeypatch):
    monkeypatch.setenv("ALLOW_MATURE_TOOL_FALLBACK", "false")
    get_settings.cache_clear()
    try:
        decision = evaluate_risk_gate(
            db,
            metrics=PASSING_METRICS,
            cost_model={"commission_bps": 1},
            slippage_model={"bps": 2},
            factor_report_present=True,
            evidence_grade="verified",
            **PASSING_PERIOD,
        )
    finally:
        get_settings.cache_clear()
    assert decision.verdict == "pass"


def test_nan_sharpe_fails_closed(db):
    metrics = {**PASSING_METRICS, "sharpe": float("nan")}
    decision = evaluate_risk_gate(
        db,
        metrics=metrics,
        cost_model={"commission_bps": 1},
        slippage_model={"bps": 2},
        factor_report_present=True,
        **PASSING_PERIOD,
    )
    assert decision.verdict == "fail"
    failed = {item["rule"] for item in decision.hard_rule_results if not item["passed"]}
    assert "min_sharpe" in failed


def test_inf_drawdown_and_turnover_fail_closed(db):
    metrics = {**PASSING_METRICS, "max_drawdown": float("inf"), "turnover_daily": float("nan")}
    decision = evaluate_risk_gate(
        db,
        metrics=metrics,
        cost_model={"commission_bps": 1},
        slippage_model={"bps": 2},
        factor_report_present=True,
        **PASSING_PERIOD,
    )
    assert decision.verdict == "fail"
    failed = {item["rule"] for item in decision.hard_rule_results if not item["passed"]}
    assert "max_drawdown" in failed
    assert "max_turnover_daily" in failed


def test_build_input_produces_finite_json_serializable_metrics():
    payload = build_risk_gate_input(
        {"sharpe": float("nan"), "max_drawdown": float("inf"), "turnover_daily": float("nan"), "trade_count": "oops"},
        {"commission_bps": 1},
        {"bps": 2},
        True,
        date(2020, 1, 1),
        date(2025, 1, 1),
        "risk_review",
        {},
    )
    for key, value in payload["metrics"].items():
        assert math.isfinite(value), key
    assert payload["metrics"]["trade_count"] == 0


def test_inverted_period_treated_as_zero_history():
    payload = build_risk_gate_input(
        PASSING_METRICS, {"c": 1}, {"s": 1}, True,
        date(2025, 1, 1), date(2020, 1, 1), "risk_review", {},
    )
    assert payload["context"]["backtest_years"] == 0.0


def test_risk_gate_writes_opa_policy_decision(db):
    decision = evaluate_risk_gate(
        db,
        metrics=PASSING_METRICS,
        cost_model={"commission_bps": 1},
        slippage_model={"bps": 2},
        factor_report_present=True,
        **PASSING_PERIOD,
    )
    db.commit()

    row = db.query(PolicyDecision).one()
    assert decision.verdict == "pass"
    assert row.policy_package == "risk_gate"
    assert row.allowed is True
