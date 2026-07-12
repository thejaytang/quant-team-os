# Risk and Approval

Risk review is advisory evidence. **OPA** decides whether a lifecycle transition is allowed, and humans resolve approval requests through the Approval Center.

Lifecycle gates:

- Strategy registration requires a StrategyCard, backtest evidence, risk review, policy pass, and human approval.
- Paper promotion requires latest risk pass, policy pass, and human approval.
- Live trading remains locked by default and is refused in MVP.
- Agent service accounts cannot approve or reject approval requests.
- Every approval action requires a human comment.

Audit evidence:

- `policy_decisions` records OPA outcomes.
- `approval_requests` records pending work.
- `approval_records` records human decisions.
- `audit_logs` records policy decisions, tool calls, and approval actions.
- Temporal workflow continuation must happen through `approval_resolved` signals, not direct UI state mutation.
