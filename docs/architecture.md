# Quant Team OS Architecture

v0.4 is a tool-first monorepo. Heavy infrastructure is delegated to mature tools; this repository owns glue, adapters, domain schema, policy input/audit, and control UI wiring.

## Design Principles

1. **Agents never touch state directly.** Agents never receive a database session, broker client, secret value, or external SDK. Every tool call goes through `AdapterRunner` (`apps/api/app/adapters/base.py`), which evaluates OPA policy, validates the connection, resolves Infisical secret refs, redacts secrets from all persisted payloads, and writes `ToolCall` + `AuditLog` rows.
2. **Policy is evaluated, not assumed.** OPA (`policy/opa/*.rego`) is the source of truth for agent-tool allowlists, connector rules, the risk gate, approval rules, strategy lifecycle, and the live-trading lock. `apps/api/app/services/policy.py` mirrors the bundle as a local fallback that is only legal when `ALLOW_LOCAL_POLICY_FALLBACK=true`. Every decision is persisted as a `PolicyDecision` row and audit event.
3. **Risk rules fail closed.** The risk gate (`apps/api/app/risk/engine.py`) denies when inputs are missing: an unknown backtest period counts as zero years of history, and missing metrics default to failing values.
4. **Evidence is graded.** Every research artifact carries an evidence grade in `Artifact.meta["evidence_grade"]`: `verified` (real computation over real ingested rows), `sample` (placeholder or sample-data output), `unverified` (claimed without a resolvable artifact). The grade flows into `RiskReview.risk_summary` and approval requests, and the risk gate rejects non-`verified` factor evidence in strict mode (`ALLOW_MATURE_TOOL_FALLBACK=false` or production). See `apps/api/app/services/evidence.py`.
5. **Humans resolve approvals.** Strategy registration and paper promotion are Temporal workflows that block on an `approval_resolved` signal. Agents and service accounts cannot approve; a human comment is mandatory; live trading stays locked (`ALLOW_LIVE_TRADING=false`).

## Components

- `apps/api`: FastAPI orchestration API. Owns state, audit, approvals, artifact metadata, adapter execution, RBAC (Keycloak), and Prometheus metrics.
- `apps/workers`: Temporal workflows and activities. The research chain is plan → ingest (dlt) → validate (Great Expectations) → version (DVC) → register dataset → factor research → factor tear sheet → backtest request (QuantConnect MCP) → strategy tear sheet → MLflow logging → risk gate → report → human approval.
- `apps/control-ui`: Refine + Ant Design console (dashboard, research pipeline, factor/strategy registry, experiments, reports, agent canvas).
- `apps/agent-chat`: Chainlit bridge; read/approve-adjacent surface that cannot mutate core state directly (enforced by the `ui_surface` policy).
- `apps/openbb-backend`: read-only audited widget backend for OpenBB Workspace.
- `policy/`: OPA bundle and Rego tests.
- `data_contracts/`: dlt sources, Great Expectations suites, DVC remote templates.
- `infra/`: Docker Compose (full and core), Keycloak realm, Grafana/Prometheus/Loki/Superset/OTel configs.

## Analytics Boundary

Factor and strategy tear sheets are computed by `apps/api/app/services/factor_analytics.py` (`pandas_ic_v1`): cross-sectional momentum IC, quantile forward returns, and a top-quantile portfolio proxy for Sharpe/drawdown/turnover. When workflow payloads carry real ingested rows (`rows_provenance == "user_supplied"`), the resulting artifacts are graded `verified`; sample rows keep the `sample` grade. Heavyweight engines (Qlib, RD-Agent, QuantConnect) remain adapter-mediated and their outputs upgrade the same artifacts when connected.

## Deployment Profiles

- **Core stack** (`infra/docker-compose.core.yml`, `npm run full-stack:core`): postgres, redis, keycloak, infisical, temporal(+ui), opa, minio, mlflow, api, workers, control-ui. All governance locks stay on; `REQUIRE_LANGFUSE_TRACKING=false` lets agent traces degrade to the audited local mirror.
- **Full stack** (`infra/docker-compose.yml`): adds langfuse, otel-collector, prometheus, loki, promtail, grafana, superset, jupyterlab, agent-chat, openbb-backend. This is the acceptance baseline checked by `scripts/full_stack_doctor.py` and `scripts/release_gate.py`.

## Delivery Gates

`npm test` runs, in order: `scripts/release_gate.py` (structural contracts), `scripts/acceptance_audit.py` (requirement probes), `scripts/opa_policy_gate.py` (Rego tests), the API pytest suite, and the control UI contract/build tests.
