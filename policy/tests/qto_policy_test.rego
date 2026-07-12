package qto.policy_test

import data.qto.agent
import data.qto.approval
import data.qto.connector
import data.qto.risk_gate
import data.qto.strategy_lifecycle
import data.qto.trading_lock
import data.qto.ui_surface

test_live_trading_denied_when_locked if {
  trading_lock.deny[_] == "live trading is locked" with input as {
    "action": "live_order",
    "system": {"allow_live_trading": false}
  }
}

test_agent_cannot_approve if {
  agent.deny[_] == "agent cannot approve or reject approvals" with input as {
    "action": "approve",
    "agent": {"service_account": true}
  }
}

test_agent_action_must_be_tool_call if {
  agent.deny[_] == "agent action must be tool_call" with input as {
    "action": "approve",
    "agent": {"service_account": false}
  }
}

test_agent_denies_wrong_tool if {
  agent.deny[_] == "agent is not allowed to call this tool" with input as {
    "action": "tool_call",
    "agent": {"name": "ResearchAgent", "service_account": true},
    "tool": {"name": "quantconnect_paper", "risk_level": "paper_trade"}
  }
}

test_backtest_agent_can_call_quantconnect_mcp if {
  agent.allow with input as {
    "action": "tool_call",
    "agent": {"name": "BacktestAgent", "service_account": true},
    "tool": {"name": "quantconnect_mcp", "risk_level": "backtest_run"}
  }
}

test_connector_denies_secret_payload if {
  connector.deny[_] == "secret must not be present in tool payload" with input as {
    "connection": {"status": "connected"},
    "payload": {"api_key": "sk-testsecret1234"}
  }
}

test_connector_denies_common_secret_key_payload if {
  connector.deny[_] == "secret must not be present in tool payload" with input as {
    "connection": {"status": "connected"},
    "payload": {"client_secret": "client-secret-value"}
  }
}

test_connector_denies_untrusted_secret_ref if {
  connector.deny[_] == "secret refs must be resolved by trusted service adapters" with input as {
    "agent": {"name": "ResearchAgent"},
    "connection": {"status": "connected"},
    "payload_meta": {"ref_requested": true},
    "payload": {}
  }
}

test_connector_allows_trusted_secret_ref_actor if {
  connector.allow with input as {
    "agent": {"name": "LangfuseService"},
    "connection": {"status": "connected"},
    "payload_meta": {"ref_requested": true},
    "payload": {}
  }
}

test_connector_denies_disconnected_status if {
  connector.deny[_] == "connector is not connected" with input as {
    "connection": {"status": "disconnected"},
    "payload": {"symbol": "SPY"}
  }
}

test_strategy_registration_requires_human_approval if {
  strategy_lifecycle.deny[_] == "human approval is required" with input as {
    "action": "register_strategy",
    "approval": {"status": "pending", "approved_by_human": false},
    "strategy": {"latest_risk_review": {"verdict": "pass"}}
  }
}

test_strategy_registration_requires_approved_request if {
  strategy_lifecycle.deny[_] == "approved approval is required" with input as {
    "action": "register_strategy",
    "approval": {"status": "pending", "approved_by_human": true},
    "strategy": {"latest_risk_review": {"verdict": "pass"}}
  }
}

test_strategy_registration_requires_latest_risk_pass if {
  strategy_lifecycle.deny[_] == "latest risk review must pass" with input as {
    "action": "register_strategy",
    "approval": {"status": "approved", "approved_by_human": true},
    "strategy": {"latest_risk_review": {"verdict": "fail"}}
  }
}

test_paper_promotion_requires_approved_request if {
  strategy_lifecycle.deny[_] == "approved approval is required" with input as {
    "action": "promote_to_paper",
    "approval": {"status": "pending", "approved_by_human": true},
    "strategy": {
      "latest_risk_review": {"verdict": "pass"},
      "latest_backtest": {"has_cost_model": true, "has_slippage_model": true}
    }
  }
}

test_paper_promotion_requires_latest_risk_pass if {
  strategy_lifecycle.deny[_] == "latest risk review must pass" with input as {
    "action": "promote_to_paper",
    "approval": {"status": "approved", "approved_by_human": true},
    "strategy": {
      "latest_risk_review": {"verdict": "fail"},
      "latest_backtest": {"has_cost_model": true, "has_slippage_model": true}
    }
  }
}

test_strategy_promotion_requires_cost_model if {
  strategy_lifecycle.deny[_] == "cost model is required" with input as {
    "action": "promote_to_paper",
    "approval": {"status": "approved", "approved_by_human": true},
    "strategy": {
      "latest_risk_review": {"verdict": "pass"},
      "latest_backtest": {"has_cost_model": false, "has_slippage_model": true}
    }
  }
}

test_approval_requires_comment if {
  approval.deny[_] == "human comment is required" with input as {
    "user": {"roles": ["approver"]},
    "agent": {"service_account": false},
    "comment": ""
  }
}

test_approval_denies_live_unlock_create if {
  approval.deny[_] == "Live trading is locked by OPA" with input as {
    "action": "create_request",
    "request_type": "unlock_live",
    "user": {"roles": ["approver"]},
    "agent": {"service_account": false},
    "comment": "request live unlock"
  }
}

test_approval_denies_live_unlock_approve if {
  approval.deny[_] == "Live trading is locked by OPA" with input as {
    "action": "approved",
    "request_type": "unlock_live",
    "user": {"roles": ["approver"]},
    "agent": {"service_account": false},
    "comment": "approve live unlock"
  }
}

test_approval_live_unlock_allow_false if {
  not approval.allow with input as {
    "action": "approved",
    "request_type": "unlock_live",
    "user": {"roles": ["approver"]},
    "agent": {"service_account": false},
    "comment": "approve live unlock"
  }
}

test_risk_gate_requires_cost_model if {
  risk_gate.deny[_] == "cost model is required" with input as {
    "request_type": "risk_review",
    "metrics": {"sharpe": 1.2, "max_drawdown": 0.1, "turnover_daily": 0.2, "trade_count": 100},
    "thresholds": {"min_sharpe": 0.8, "max_drawdown": 0.25, "max_turnover_daily": 0.5, "min_trade_count": 50, "min_backtest_years": 3},
    "context": {"has_cost_model": false, "has_slippage_model": true, "factor_report_present": true, "backtest_years": 5}
  }
}

test_risk_gate_requires_known_backtest_period if {
  risk_gate.deny[_] == "backtest period is required" with input as {
    "request_type": "risk_review",
    "metrics": {"sharpe": 1.2, "max_drawdown": 0.1, "turnover_daily": 0.2, "trade_count": 100},
    "thresholds": {"min_sharpe": 0.8, "max_drawdown": 0.25, "max_turnover_daily": 0.5, "min_trade_count": 50, "min_backtest_years": 3},
    "context": {"has_cost_model": true, "has_slippage_model": true, "factor_report_present": true, "backtest_period_known": false, "backtest_years": 0}
  }
}

test_risk_gate_unknown_period_fails_history_check if {
  risk_gate.deny[_] == "backtest history is too short" with input as {
    "request_type": "risk_review",
    "metrics": {"sharpe": 1.2, "max_drawdown": 0.1, "turnover_daily": 0.2, "trade_count": 100},
    "thresholds": {"min_sharpe": 0.8, "max_drawdown": 0.25, "max_turnover_daily": 0.5, "min_trade_count": 50, "min_backtest_years": 3},
    "context": {"has_cost_model": true, "has_slippage_model": true, "factor_report_present": true, "backtest_period_known": false, "backtest_years": 0}
  }
}

test_risk_gate_strict_evidence_rejects_sample_report if {
  risk_gate.deny[_] == "verified factor evidence is required" with input as {
    "request_type": "risk_review",
    "metrics": {"sharpe": 1.2, "max_drawdown": 0.1, "turnover_daily": 0.2, "trade_count": 100},
    "thresholds": {"min_sharpe": 0.8, "max_drawdown": 0.25, "max_turnover_daily": 0.5, "min_trade_count": 50, "min_backtest_years": 3},
    "context": {"has_cost_model": true, "has_slippage_model": true, "factor_report_present": true, "backtest_period_known": true, "backtest_years": 5, "strict_evidence": true, "evidence_grade": "sample"}
  }
}

test_risk_gate_allows_verified_evidence if {
  risk_gate.allow with input as {
    "request_type": "risk_review",
    "metrics": {"sharpe": 1.2, "max_drawdown": 0.1, "turnover_daily": 0.2, "trade_count": 100},
    "thresholds": {"min_sharpe": 0.8, "max_drawdown": 0.25, "max_turnover_daily": 0.5, "min_trade_count": 50, "min_backtest_years": 3},
    "context": {"has_cost_model": true, "has_slippage_model": true, "factor_report_present": true, "backtest_period_known": true, "backtest_years": 5, "strict_evidence": true, "evidence_grade": "verified"}
  }
}

test_chainlit_cannot_directly_mutate_strategy_state if {
  ui_surface.deny[_] == "Chainlit cannot directly mutate core state" with input as {
    "surface": "chainlit",
    "action": "set_strategy_status",
    "target_type": "strategy"
  }
}

test_openbb_workspace_is_read_only if {
  ui_surface.deny[_] == "external workspace is read-only for core state" with input as {
    "surface": "openbb",
    "action": "update_strategy",
    "target_type": "strategy"
  }
}

test_grafana_workspace_is_read_only if {
  ui_surface.deny[_] == "external workspace is read-only for core state" with input as {
    "surface": "grafana",
    "action": "create_strategy",
    "target_type": "strategy"
  }
}
