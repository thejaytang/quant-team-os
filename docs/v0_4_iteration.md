# v0.4 Iteration: Evidence Integrity and a Usable Core Stack

This iteration keeps the v0.3 philosophy (tool-first, governance-first, agents never touch state) and closes the gap between the governance shell and the research substance.

## Problems Addressed

1. **Risk gate fail-open on missing dates.** `build_risk_gate_input` previously defaulted a missing backtest period to exactly the minimum required years, so omitting dates auto-passed the history check. It now fails closed: unknown period = 0 years, plus an explicit `backtest period is required` denial, mirrored in Rego (`policy/opa/risk_gate.rego`), the local policy fallback, and regression tests.
2. **Placeholder evidence satisfied the risk gate.** The Qlib/Alphalens/QuantStats activities emitted hardcoded zero-metric artifacts, and a placeholder tear sheet satisfied the `factor_report_present` requirement. v0.4 introduces evidence grading (`apps/api/app/services/evidence.py`):
   - `verified` — real computation over real ingested rows;
   - `sample` — placeholder or sample-data output;
   - `unverified` — a payload flag with no resolvable artifact.
   The grade is stored on every artifact, propagated into `RiskReview.risk_summary` and approval requests, displayed in the control UI (工作台风险告警与待办审批), and enforced by a new `verified factor evidence is required` policy denial in strict mode (`ALLOW_MATURE_TOOL_FALLBACK=false` or production). Local dev keeps working with sample data; the label is always visible so a human approver can never mistake demo output for evidence.
3. **Tear sheets are now computed, not fabricated.** `apps/api/app/services/factor_analytics.py` (`pandas_ic_v1`) computes real IC / ICIR / quantile forward returns and a top-quantile portfolio proxy (Sharpe, max drawdown, daily turnover, trade count) directly from the OHLCV rows flowing through the workflow. `DltIngestionActivity` tags `rows_provenance` (`user_supplied` vs `sample`) and the grade follows the provenance. QuantStats output exposes `computed_strategy_metrics` without overwriting the payload `metrics` contract.
4. **The 25-service full stack was the only stack.** `infra/docker-compose.core.yml` (13 services, `npm run full-stack:core`) is the daily driver: postgres, redis, keycloak, infisical, temporal(+ui), opa, minio(+init), mlflow, api, workers, control-ui. All `ALLOW_*_FALLBACK` locks stay false. New setting `REQUIRE_LANGFUSE_TRACKING` (default true) lets the core stack degrade agent tracing to the audited local mirror instead of failing without Langfuse. `scripts/core_stack_doctor.py` (`npm run full-stack:doctor:core`) live-checks the core endpoints. The full compose file is untouched and remains the acceptance baseline.
5. **Repository hygiene.** Removed iCloud sync-conflict duplicates (`* 2.*` files) and added `.DS_Store` / `* 2.*` / `*.icloud` to `.gitignore`. The repository intentionally stays in the iCloud-synced folder per the owner's preference.

## API Changes

- `RiskValidateRequest` gains optional `evidence_grade` (default `unverified`). Manual risk reviews via `POST /api/v1/risk/reviews` are subject to the same strict-mode evidence rule.
- `evaluate_risk_gate(...)` gains `evidence_grade`; risk summaries now include `evidence_grade` and the policy input includes `context.backtest_period_known`, `context.evidence_grade`, `context.strict_evidence`.

## Compatibility

- All v0.3 delivery gates (`release_gate.py`, `acceptance_audit.py`, `opa_policy_gate.py`) still pass; the full compose file, doctor script, and acceptance runbook are unchanged.
- Existing tests were updated only where they relied on the fail-open behavior (passing risk reviews must now supply a backtest period).

## Human Configuration Checklist (unchanged from v0.3, plus one line)

1. `cp .env.example .env`, then fill Infisical project + machine identity values after `docker compose ... up -d postgres infisical` (see `infra/infisical/README.md`).
2. Connect provider keys (OpenAI, Massive, QuantConnect) through Control UI Connect Center or Infisical UI.
3. Daily work: `npm run full-stack:core` + `npm run full-stack:doctor:core`. Full acceptance: `npm run full-stack:up` + `npm run full-stack:doctor:live` (set `REQUIRE_LANGFUSE_TRACKING=true`).
4. Live trading stays locked; do not change `ALLOW_LIVE_TRADING`.
