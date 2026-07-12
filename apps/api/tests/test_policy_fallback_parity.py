from app.services.policy import _local_policy


def test_agent_fallback_only_allows_tool_call():
    denied = _local_policy("agent", {"action": "approve", "agent": {"service_account": False}})
    allowed = _local_policy("agent", {"action": "tool_call", "agent": {"service_account": True}})

    assert denied.allowed is False
    assert "agent action must be tool_call" in denied.reasons
    assert allowed.allowed is True


def test_strategy_registration_fallback_requires_approved_request_and_risk_pass():
    decision = _local_policy(
        "strategy_lifecycle",
        {
            "action": "register_strategy",
            "approval": {"status": "pending", "approved_by_human": True},
            "strategy": {"latest_risk_review": {"verdict": "fail"}},
        },
    )

    assert decision.allowed is False
    assert "approved approval is required" in decision.reasons
    assert "latest risk review must pass" in decision.reasons


def test_paper_promotion_fallback_requires_approved_request():
    decision = _local_policy(
        "strategy_lifecycle",
        {
            "action": "promote_to_paper",
            "approval": {"status": "pending", "approved_by_human": True},
            "strategy": {
                "latest_risk_review": {"verdict": "pass"},
                "latest_backtest": {"has_cost_model": True, "has_slippage_model": True},
            },
        },
    )

    assert decision.allowed is False
    assert "approved approval is required" in decision.reasons
