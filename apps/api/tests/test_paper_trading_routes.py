import os

import pytest

os.environ["DATABASE_URL"] = "sqlite:///:memory:"

from app.api.routes_paper_trading import create_paper_trading_session, list_paper_trading_sessions
from app.db.models import ExternalConnection, StrategySpec, WorkflowLink
from app.services.connections import seed_connections


def test_paper_trading_sessions_list_public_metadata(db):
    strategy = StrategySpec(name="Paper Candidate", description="Paper test", status="PAPER_APPROVED")
    db.add(strategy)
    db.flush()
    seed_connections(db)
    db.query(ExternalConnection).filter_by(provider="quantconnect").one().status = "connected"

    session = create_paper_trading_session({"strategy_id": strategy.id}, db)
    rows = list_paper_trading_sessions(db)

    assert session["provider"] == "quantconnect"
    assert session["status"] == "proposed"
    assert session["metadata"]["permission_level"] == "paper_trade"
    assert strategy.status == "PAPER_APPROVED"
    assert rows[0]["workflow_id"].startswith("PaperPromotionWorkflow-")
    assert db.query(WorkflowLink).filter_by(workflow_type="PaperPromotionWorkflow").count() == 1


def test_paper_trading_session_requires_paper_approval(db):
    strategy = StrategySpec(name="Registered", description="Paper test", status="STRATEGY_REGISTERED")
    db.add(strategy)
    db.flush()
    seed_connections(db)
    db.query(ExternalConnection).filter_by(provider="quantconnect").one().status = "connected"

    with pytest.raises(Exception, match="strategy must be PAPER_APPROVED"):
        create_paper_trading_session({"strategy_id": strategy.id}, db)
