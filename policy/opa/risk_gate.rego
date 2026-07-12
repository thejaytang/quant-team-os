package qto.risk_gate

default allow = false

allow if {
  count(deny) == 0
}

deny contains "live trading disabled in MVP" if {
  input.request_type == "unlock_live"
}

deny contains "cost model is required" if {
  input.context.has_cost_model != true
}

deny contains "slippage model is required" if {
  input.context.has_slippage_model != true
}

deny contains "factor report artifact is required" if {
  input.context.factor_report_present != true
}

verified_evidence if {
  input.context.evidence_grade == "verified"
}

backtest_period_known if {
  input.context.backtest_period_known == true
}

deny contains "verified factor evidence is required" if {
  input.context.strict_evidence == true
  not verified_evidence
}

deny contains "backtest period is required" if {
  not backtest_period_known
}

deny contains "backtest history is too short" if {
  input.context.backtest_years < input.thresholds.min_backtest_years
}

deny contains "Sharpe below threshold" if {
  input.metrics.sharpe < input.thresholds.min_sharpe
}

deny contains "max drawdown above threshold" if {
  input.metrics.max_drawdown > input.thresholds.max_drawdown
}

deny contains "max drawdown above threshold" if {
  -input.metrics.max_drawdown > input.thresholds.max_drawdown
}

deny contains "daily turnover above threshold" if {
  input.metrics.turnover_daily > input.thresholds.max_turnover_daily
}

deny contains "not enough trades" if {
  input.metrics.trade_count < input.thresholds.min_trade_count
}
