from datetime import date

from app.db.models import BacktestRun, DatasetSpec, RiskReview, StrategySpec
from app.services.strategy_state import can_register_strategy


def test_strategy_cannot_register_without_approval_record(db):
    dataset = DatasetSpec(name="test")
    strategy = StrategySpec(name="s", description="d", status="APPROVAL_PENDING")
    db.add_all([dataset, strategy])
    db.flush()
    backtest = BacktestRun(
        strategy_id=strategy.id,
        dataset_spec_id=dataset.id,
        start_date=date(2020, 1, 1),
        end_date=date(2025, 1, 1),
        cost_model={"commission_bps": 1},
        slippage_model={"bps": 2},
        status="completed",
        metrics={"sharpe": 1},
    )
    db.add(backtest)
    db.flush()
    db.add(RiskReview(strategy_id=strategy.id, backtest_run_id=backtest.id, verdict="pass", hard_rule_results=[], risk_summary={}))
    ok, reason = can_register_strategy(db, strategy.id, "missing-request")
    assert ok is False
    assert "ApprovalRequest" in reason

