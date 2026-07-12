package qto.strategy_lifecycle

default allow = false

allow if {
  input.action == "register_strategy"
  input.approval.status == "approved"
  input.approval.approved_by_human == true
  input.strategy.latest_risk_review.verdict == "pass"
}

allow if {
  input.action == "promote_to_paper"
  input.approval.status == "approved"
  input.approval.approved_by_human == true
  input.strategy.latest_risk_review.verdict == "pass"
  input.strategy.latest_backtest.has_cost_model == true
  input.strategy.latest_backtest.has_slippage_model == true
}

deny contains "human approval is required" if {
  input.action == "register_strategy"
  input.approval.approved_by_human != true
}

deny contains "approved approval is required" if {
  input.action == "register_strategy"
  input.approval.status != "approved"
}

deny contains "latest risk review must pass" if {
  input.action == "register_strategy"
  input.strategy.latest_risk_review.verdict != "pass"
}

deny contains "approved approval is required" if {
  input.action == "promote_to_paper"
  input.approval.status != "approved"
}

deny contains "latest risk review must pass" if {
  input.action == "promote_to_paper"
  input.strategy.latest_risk_review.verdict != "pass"
}

deny contains "cost model is required" if {
  input.action == "promote_to_paper"
  input.strategy.latest_backtest.has_cost_model != true
}

deny contains "slippage model is required" if {
  input.action == "promote_to_paper"
  input.strategy.latest_backtest.has_slippage_model != true
}
