# Workflow Design

Long-running work is owned by **Temporal**. FastAPI creates workflow links, workers run activities, and approval recovery happens through Temporal signals.

Implemented workflow families:

```text
ConnectionTestWorkflow
DataIngestionWorkflow
ResearchWorkflow
FactorAnalysisWorkflow
BacktestWorkflow
RiskReviewWorkflow
StrategyRegistrationWorkflow
PaperPromotionWorkflow
ReportGenerationWorkflow
```

Workflow rules:

- Workflow definitions stay deterministic.
- LLM calls, external API calls, Qlib, dlt, Great Expectations, DVC, MLflow, QuantConnect, Alphalens, QuantStats, and report generation run as activities.
- Approval gates create `ApprovalRequest` rows and wait for `approval_resolved` signals.
- Approval API writes the approval record before signaling Temporal.
- Workflow IDs are linked through `workflow_links`, `approval_requests`, and StrategyCard metadata where relevant.
- Local fallback is allowed only for developer tests when the explicit fallback flags are enabled.
