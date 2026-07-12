import pytest

from app.adapters.stubs import IBKRLockedAdapter
from app.risk.engine import evaluate_risk_gate
from app.services.approval_service import create_approval_request, resolve_approval


def test_ibkr_live_order_is_locked():
    with pytest.raises(PermissionError):
        IBKRLockedAdapter().run_live_order({"symbol": "SPY"})


def test_live_policy_fails(db):
    decision = evaluate_risk_gate(
        db,
        metrics={"sharpe": 2, "max_drawdown": 0.1, "turnover_daily": 0.1, "trade_count": 200},
        cost_model={"commission_bps": 1},
        slippage_model={"bps": 2},
        factor_report_present=True,
        request_type="unlock_live",
    )
    failed = {item["rule"] for item in decision.hard_rule_results if not item["passed"]}
    assert "live_trading_locked" in failed


def test_unlock_live_cannot_be_approved(db):
    request = create_approval_request(db, "unlock_live", "strategy", "s1", "ExecutionAgent", {})
    db.flush()
    assert request.status == "rejected"
    with pytest.raises(PermissionError):
        resolve_approval(db, request.id, "approved", "no")
