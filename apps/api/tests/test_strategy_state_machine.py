from datetime import date

import pytest

from app.api.routes_strategies import list_strategies, request_paper_promotion
from app.db.models import (
    ApprovalRequest,
    BacktestRun,
    DatasetSpec,
    PolicyDecision,
    RiskReview,
    StrategyCard,
    StrategySpec,
)
from app.services.approval_service import resolve_approval
from app.services.strategy_state import (
    promote_strategy_to_paper_after_approval,
    register_strategy_after_approval,
    transition_strategy,
)


def test_approval_registers_strategy(db):
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
    db.add(StrategyCard(strategy_id=strategy.id, current_status=strategy.status, thesis="d", universe="US equities"))
    request = ApprovalRequest(
        request_type="register_strategy",
        target_type="strategy",
        target_id=strategy.id,
        requested_by_agent="ChiefAgent",
        risk_summary={},
        status="pending",
    )
    db.add(request)
    db.flush()
    resolve_approval(db, request.id, "approved", "reviewed")
    register_strategy_after_approval(db, strategy.id, request.id)
    db.commit()
    assert strategy.status == "STRATEGY_REGISTERED"
    assert db.query(StrategyCard).filter_by(strategy_id=strategy.id).one().approval_status == "approved"


def test_strategy_list_includes_strategy_card_lifecycle(db):
    strategy = StrategySpec(name="s", description="d", status="APPROVAL_PENDING")
    db.add(strategy)
    db.flush()
    card = StrategyCard(
        strategy_id=strategy.id,
        current_status="APPROVAL_PENDING",
        thesis="d",
        universe="US equities",
        approval_status="pending",
        paper_trading_status="not_started",
        live_trading_status="locked",
    )
    db.add(card)
    db.flush()

    rows = list_strategies(db)

    assert rows[0]["id"] == strategy.id
    assert rows[0]["card"].current_status == "APPROVAL_PENDING"
    assert rows[0]["card"].approval_status == "pending"


def test_live_trading_transition_never_exists(db):
    strategy = StrategySpec(name="s", description="d", status="PAPER_TRADING")
    db.add(strategy)
    db.flush()
    with pytest.raises(PermissionError):
        transition_strategy(db, strategy, "LIVE_TRADING")


def test_live_candidate_can_only_move_to_locked_before_retirement(db):
    strategy = StrategySpec(name="s", description="d", status="PAPER_TRADING")
    db.add(strategy)
    db.flush()
    db.add(StrategyCard(strategy_id=strategy.id, current_status=strategy.status, thesis="d", universe="US equities"))

    transition_strategy(db, strategy, "LIVE_CANDIDATE")
    transition_strategy(db, strategy, "LIVE_LOCKED")
    transition_strategy(db, strategy, "RETIRED")

    card = db.query(StrategyCard).filter_by(strategy_id=strategy.id).one()
    assert strategy.status == "RETIRED"
    assert card.current_status == "RETIRED"


def test_live_candidate_cannot_skip_live_locked(db):
    strategy = StrategySpec(name="s", description="d", status="LIVE_CANDIDATE")
    db.add(strategy)
    db.flush()

    with pytest.raises(ValueError, match="LIVE_CANDIDATE -> RETIRED"):
        transition_strategy(db, strategy, "RETIRED")


def test_approval_promotes_strategy_to_paper_approved(db):
    dataset = DatasetSpec(name="test")
    strategy = StrategySpec(name="s", description="d", status="PAPER_CANDIDATE")
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
    db.add(StrategyCard(strategy_id=strategy.id, current_status=strategy.status, thesis="d", universe="US equities"))
    request = ApprovalRequest(
        request_type="promote_to_paper",
        target_type="strategy",
        target_id=strategy.id,
        requested_by_agent="PortfolioAgent",
        risk_summary={},
        status="pending",
    )
    db.add(request)
    db.flush()

    resolve_approval(db, request.id, "approved", "reviewed")
    promote_strategy_to_paper_after_approval(db, strategy.id, request.id)
    db.commit()

    assert strategy.status == "PAPER_APPROVED"
    card = db.query(StrategyCard).filter_by(strategy_id=strategy.id).one()
    assert card.current_status == "PAPER_APPROVED"
    assert card.paper_trading_status == "approved"
    decision = db.query(PolicyDecision).filter_by(policy_package="strategy_lifecycle").one()
    assert decision.allowed is True


def test_request_paper_promotion_requires_latest_risk_pass(db):
    strategy = StrategySpec(name="s", description="d", status="STRATEGY_REGISTERED")
    db.add(strategy)
    db.flush()

    with pytest.raises(Exception, match="missing RiskReview"):
        request_paper_promotion(strategy.id, db)


def test_request_paper_promotion_starts_workflow_without_direct_transition(db):
    dataset = DatasetSpec(name="test")
    strategy = StrategySpec(name="s", description="d", status="STRATEGY_REGISTERED")
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

    result = request_paper_promotion(strategy.id, db)

    assert strategy.status == "STRATEGY_REGISTERED"
    assert result["workflow_type"] == "PaperPromotionWorkflow"
    assert result["owner_id"] == strategy.id
