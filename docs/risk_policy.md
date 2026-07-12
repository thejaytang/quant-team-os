# Risk Policy

The v0.3 policy gate is **Open Policy Agent**. Python in `apps/api/app/risk/engine.py` only assembles risk metrics into OPA input and adapts the decision for API responses.

Blocking rules:

- Live trading is disabled.
- Registration requires a `RiskReview`.
- Registration requires an approved `ApprovalRecord`.
- Backtests require transaction cost and slippage models.
- Factor strategies require a factor report artifact.
- Secret leakage to audit payloads is redacted and flagged.
