# Quant Team OS v0.3 Acceptance Runbook

This runbook is the delivery checklist for `docs/requirements/quant_team_os_requirements_v0_3.md`.

The current automated tests prove the local glue layer. Final product acceptance also requires a live Docker Compose run because **Keycloak**, **Infisical**, **Temporal**, **MinIO**, **DVC**, **MLflow**, **Langfuse**, **Superset**, **Grafana**, **Chainlit**, and **OpenBB backend** are runtime services.

## Manual Inputs

These are the only expected manual setup items:

- Install Docker Desktop and make `docker` available in the shell.
- Create the **Infisical** project and machine identity.
- Fill `.env` values:
  - `INFISICAL_PROJECT_ID`
  - `INFISICAL_MACHINE_IDENTITY_CLIENT_ID`
  - `INFISICAL_MACHINE_IDENTITY_CLIENT_SECRET`
  - `OAUTH_GENERIC_CLIENT_SECRET`
  - `OPENBB_INTERNAL_TOKEN`
- Store internal product credentials in **Infisical** at the configured `*_REF` paths:
  - `KEYCLOAK_CLIENT_SECRET_REF`
  - `OPENBB_KEYCLOAK_CLIENT_SECRET_REF`
  - `LANGFUSE_PUBLIC_KEY_REF`
  - `LANGFUSE_SECRET_KEY_REF`
- Store external provider credentials in **Infisical** when you connect those providers:
  - `OPENAI_API_KEY_REF`
  - `MASSIVE_API_KEY_REF`
  - `QUANTCONNECT_API_TOKEN_REF`

`OPENBB_INTERNAL_TOKEN` is only used between the OpenBB backend and FastAPI.
The OpenBB backend must not read **Infisical** or Keycloak client secrets
directly.

Do not put raw OpenAI, Massive, or QuantConnect secrets in `.env`, PostgreSQL, audit payloads, traces, or UI responses.

The default live doctor checks internal required refs. Add
`--require-external-providers` only after OpenAI, Massive, and QuantConnect have
been manually connected.

## Static Acceptance

Run:

```bash
npm test
npm run acceptance:audit
npm run full-stack:doctor:template
```

Expected evidence:

- `release gate passed`
- `acceptance audit passed`
- `opa policy tests passed`
- all API pytest tests pass
- Control UI smoke tests pass
- Control UI production build passes
- `.env.example` doctor passes

This proves code contracts and local fallbacks, not live service readiness.

## Live Full-Stack Acceptance

Run after filling `.env`:

```bash
docker compose --env-file .env -f infra/docker-compose.yml up --build
npm run full-stack:doctor:live
```

On macOS, if `localhost:5000` is already used by `ControlCenter`, set
`MLFLOW_HOST_PORT=5001` and `MLFLOW_UI_URL=http://localhost:5001` in `.env`
before starting Compose.

`full-stack:doctor:live` must pass without accepting `temporal_unavailable`.

Expected live evidence:

- Docker Compose services are running or init services completed successfully.
- `ALLOW_MATURE_TOOL_FALLBACK=false` for API and workers, so **dlt**,
  **Great Expectations**, **DVC**, and **MLflow** failures are visible.
- **Keycloak** service-account token can call protected FastAPI endpoints.
- **Infisical** machine identity login succeeds, and internal required secret
  refs are readable without printing secret values. External provider refs are
  enforced by `--require-external-providers`.
- FastAPI internal OpenBB service-token endpoint resolves the Keycloak service
  account secret through **ToolGateway**.
- `ResearchWorkflow` can be created, reaches pending approval, resumes through
  a real **Temporal** signal, and records rejection without fallback.
- **OPA** denies live trading when `ALLOW_LIVE_TRADING=false`.
- **OpenBB backend** exposes exactly the required read-only widgets and each
  widget request writes an audit row.
- **Langfuse** trace smoke creates a trace and verifies it through the
  Langfuse public trace API.
- **MLflow** experiment API responds, and an SDK smoke run logs a metric and
  artifact.
- **Prometheus** has active targets for API, workers, **Temporal**, **OPA**, **PostgreSQL exporter**, and **OpenTelemetry Collector**.
- **Grafana** has the required Quant Team OS dashboard panels and their
  Prometheus/Loki queries execute successfully.
- **Superset** has the Strategy and Backtest Aggregate dashboard and its seed
  chart SQL executes through SQL Lab.
- **Chainlit** bridge is configured with Keycloak OAuth and routes workflow /
  approval commands through FastAPI.
- **MinIO** buckets exist and support write/read smoke.
- **DVC** can push and pull a smoke file through the MinIO remote.
- **Temporal** server connection and worker registration checks pass.

## Product DoD Mapping

| V0.3 user-visible requirement | Acceptance evidence |
|---|---|
| Open Refine Control Console | `CONTROL_UI_URL` live endpoint returns 200 and Control UI smoke test passes |
| Login through Keycloak | `validate_keycloak_api_auth` succeeds with Keycloak token |
| Connect Center lists providers | Control UI smoke test checks all required cards |
| Secrets live in Infisical, not DB/UI/logs | secret tests, release gate raw-secret scans, live Infisical identity and internal required-ref checks |
| Create ResearchIdea | `validate_research_workflow_smoke` creates a ResearchIdea |
| Start ResearchWorkflow | live doctor reads created workflow and rejects `temporal_unavailable` |
| Temporal UI available | `TEMPORAL_UI_URL` live endpoint and Temporal server check pass |
| Chainlit shows agent steps | Chainlit bridge tests, OAuth/API bridge smoke, and live endpoint pass |
| Langfuse traces exist | agent-run Langfuse tests plus live public trace API readback |
| dlt/GX/DVC versioned dataset artifact | data tests plus live DVC-MinIO roundtrip |
| Qlib/Alphalens/QuantStats sample artifacts | worker tests create sample report/artifact boundaries |
| Strategy Registry shows StrategyCard | Control UI smoke and API tests cover lifecycle fields |
| Approval Center shows pending approval | approval API/UI tests cover pending and action locks |
| Human approval continues workflow | Temporal signal tests plus live Temporal path |
| MLflow experiment run visible | MLflow tracking tests plus live SDK metric/artifact smoke |
| OpenBB read-only widgets | OpenBB backend contract tests plus live all-widget payload and audit checks |
| Superset dashboard visible | live Superset dashboard and seed chart SQL checks |
| Grafana monitoring visible | live Grafana dashboard and Prometheus/Loki query checks |
| Audit Log traces tool/policy/approval/system events | API audit tests and Control UI smoke tests |
| Live trading remains locked | OPA tests, live OPA check, required env locks |

## Known Non-Goals In MVP

These are allowed stubs or proposal-only paths in v0.3:

- Full **RD-Agent** automation.
- Real **QuantConnect** project upload/run loop.
- Full Massive historical ingestion.
- Real **QuantConnect Paper Trading** deployment.
- Direct IBKR live trading.
- Advanced OpenBB, Superset, and Grafana dashboards.

The interface must remain fixed even when the implementation is proposal-only.

## Failure Triage

- Docker missing: install Docker Desktop, then rerun `npm run full-stack:doctor:live`.
- Docker containers stay in `Created` and never reach `Running`: complete Docker
  Desktop's privileged helper setup, for example
  `sudo /Applications/Docker.app/Contents/MacOS/install config --user "$(whoami)"`,
  then restart Docker Desktop and rerun Compose.
- Infisical failure: start `postgres` and `infisical`, create the project and machine identity, then update `.env`.
- Keycloak auth failure: confirm realm import, `openbb-backend` service account secret, and OAuth client secrets.
- Temporal failure: confirm `temporal` and `workers` are running and `ALLOW_TEMPORAL_FALLBACK=false`.
- DVC/MinIO failure: confirm buckets exist and `.dvc/config` points to the MinIO remote.
