# Quant Team OS

Personal quant research, strategy validation, risk governance, approval, and controlled paper/live trading OS.

Current target: v0.4 **Tool-first** architecture with **evidence integrity**. Heavy infrastructure is delegated to mature tools; this repository owns glue, adapters, domain schema, policy input/audit, and control UI wiring. Every research artifact carries an evidence grade (`verified` / `sample` / `unverified`); the risk gate fails closed on missing backtest periods and rejects non-verified factor evidence in strict mode. See [docs/v0_4_iteration.md](docs/v0_4_iteration.md).

## Core Stack (daily driver)

The core stack runs the 13 services the product actually needs day to day, with every governance lock still on:

```bash
cp .env.example .env
npm run full-stack:core
npm run full-stack:doctor:core
```

This uses `infra/docker-compose.core.yml` (postgres, redis, keycloak, infisical, temporal, temporal-ui, opa, minio, minio-init, mlflow, api, workers, control-ui). It sets `REQUIRE_LANGFUSE_TRACKING=false` so agent traces degrade to the audited local mirror; everything else keeps the strict full-stack settings. Use the full stack below for acceptance and observability work.

## Local Dev

```bash
npm install
npm test
```

Lint the Python codebase with `ruff` (config in `ruff.toml`, also enforced in CI):

```bash
npm run lint        # ruff check .
npm run lint:fix    # ruff check . --fix
```

Run the local API with SQLite for development:

```bash
DATABASE_URL=sqlite:///./quant_team_os.db \
ALLOW_LOCAL_AUTH_FALLBACK=true \
ALLOW_TEMPORAL_FALLBACK=true \
ALLOW_LOCAL_POLICY_FALLBACK=true \
ALLOW_LOCAL_SECRET_FALLBACK=true \
ALLOW_MATURE_TOOL_FALLBACK=true \
.venv/bin/uvicorn app.main:app --app-dir apps/api --host 127.0.0.1 --port 8000
```

Run the v0.3 control console:

```bash
VITE_API_URL=http://127.0.0.1:8000 npm --prefix apps/control-ui run dev -- --host 127.0.0.1 --port 5173
```

Run the local Chainlit bridge:

```bash
cd apps/agent-chat
QTO_API_URL=http://127.0.0.1:8000 chainlit run app.py --host 127.0.0.1 --port 8001
```

Run the local OpenBB widget backend:

```bash
cd apps/openbb-backend
API_BASE_URL=http://127.0.0.1:8000 uvicorn app:app --host 127.0.0.1 --port 8010
```

Open:

```text
http://127.0.0.1:5173
```

Useful local endpoints:

```text
API health: http://127.0.0.1:8000/healthz
API docs:   http://127.0.0.1:8000/docs
Control UI: http://127.0.0.1:5173
```

`apps/control-ui` is the v0.3 product console. The legacy Next.js console has been removed.

SQLite local dev is only a fast fallback. It stores Quant Team OS metadata such
as connection status, workflow links, approvals, audit rows, and secret refs. Do
not store provider API keys in SQLite or PostgreSQL. Provider credentials belong
in **Infisical** and are referenced through `*_REF` settings and
`ExternalConnection.infisical_secret_path`.

## Full Stack Target

The v0.3 Docker Compose baseline is in `infra/docker-compose.yml` and includes:

```text
postgres, keycloak, infisical, temporal, temporal-ui, opa, minio, mlflow,
langfuse, otel-collector, prometheus, loki, grafana, superset, jupyterlab,
api, workers, control-ui, agent-chat, openbb-backend
```

Run the full stack with PostgreSQL and mature tool UIs:

```bash
cp .env.example .env
docker compose --env-file .env -f infra/docker-compose.yml up -d postgres infisical
# Create the Infisical project and machine identity, then fill the INFISICAL_* values in .env.
npm run full-stack:doctor
docker compose --env-file .env -f infra/docker-compose.yml up --build
npm run full-stack:doctor:live
```

Equivalent direct doctor commands:

```bash
python3 scripts/full_stack_doctor.py --env .env
python3 scripts/full_stack_doctor.py --env .env --live
```

Full-stack review uses PostgreSQL from Compose as the source of truth. The
SQLite command above is for local development only.

After the `postgres` and `infisical` services are up, initialize the
**Infisical** project and machine identity, then fill these values in `.env` or
the compose environment:

```text
INFISICAL_PROJECT_ID
INFISICAL_MACHINE_IDENTITY_CLIENT_ID
INFISICAL_MACHINE_IDENTITY_CLIENT_SECRET
KEYCLOAK_CLIENT_SECRET_REF
OPENBB_KEYCLOAK_CLIENT_SECRET_REF
OPENBB_INTERNAL_TOKEN
LANGFUSE_PUBLIC_KEY_REF
LANGFUSE_SECRET_KEY_REF
OPENAI_API_KEY_REF
MASSIVE_API_KEY_REF
QUANTCONNECT_API_TOKEN_REF
```

Store the API and OpenBB backend Keycloak service account secrets at
`KEYCLOAK_CLIENT_SECRET_REF` and `OPENBB_KEYCLOAK_CLIENT_SECRET_REF`, and store
Langfuse keys at the configured `LANGFUSE_*_REF` paths. OpenAI, Massive, and
QuantConnect refs are required as configured paths, but their secret values are
manual provider connections. To enforce those provider secrets in live checks,
run `python3 scripts/full_stack_doctor.py --env .env --live --require-external-providers`.

Connect provider API keys through the Control UI Connect Center or the
Infisical UI. The API resolves those refs through the ToolGateway; the OpenBB
backend only uses `OPENBB_INTERNAL_TOKEN` to request a
short-lived service token from FastAPI.

Chainlit Agent Chat uses Keycloak OAuth through the `chainlit` client and
Chainlit's Generic OAuth provider. In local Compose,
`OAUTH_GENERIC_AUTH_URL` uses the browser-visible `localhost:8080`, while
`OAUTH_GENERIC_TOKEN_URL` and `OAUTH_GENERIC_USER_INFO_URL` use the container
network address `keycloak:8080`.

`npm run full-stack:doctor` fails until the manual **Infisical** identity
values are filled. `npm run full-stack:doctor:template` checks only
`.env.example`. After Compose is running, `npm run full-stack:doctor:live`
checks the local mature tool UIs, API endpoints, and smoke paths.
The live doctor also verifies required **Infisical** secret refs, **Temporal**
approval signal resume, **OpenBB** widget audit rows, **Langfuse** trace
readback, **MLflow** metric/artifact logging, **Superset** seed SQL, and
**Grafana** Prometheus/Loki queries.

Use [docs/runbooks/v0_3_acceptance.md](docs/runbooks/v0_3_acceptance.md) as
the v0.3 delivery checklist. It separates automated evidence from the manual
Docker, Infisical, and provider credential steps.

Live trading remains locked:

```text
ALLOW_LIVE_TRADING=false
ALLOW_AGENT_ARBITRARY_CODE_EXECUTION=false
ALLOW_LOCAL_AUTH_FALLBACK=false
ALLOW_TEMPORAL_FALLBACK=false
ALLOW_LOCAL_POLICY_FALLBACK=false
ALLOW_LOCAL_SECRET_FALLBACK=false
ALLOW_AGENT_FALLBACK=false
ALLOW_MATURE_TOOL_FALLBACK=false
```

Default local admin consoles:

```text
Keycloak:   http://localhost:8080    admin / admin
Control UI: http://localhost:5173
Chainlit:   http://localhost:8001
Temporal:   http://localhost:8233
JupyterLab: http://localhost:8888
MinIO:      http://localhost:9001    minioadmin / minioadmin
MLflow:     http://localhost:5000
Langfuse:   http://localhost:3002
Superset:   http://localhost:8088    admin / admin
Grafana:    http://localhost:3000
Infisical:  http://localhost:8082
Prometheus: http://localhost:9090
Loki:       http://localhost:3100
OpenBB API: http://localhost:8010
```

Default `quant-team-os` realm users for Control UI login:

```text
qto-admin      / admin
qto-researcher / researcher
qto-approver   / approver
```

## Mature Tool Clones

Mature tool shallow clones live under `vendor/`:

```bash
npm run clone:tools
```

Business code must use adapters and **ToolGateway** boundaries rather than importing mature tools directly from agent code.

Data workflows use **dlt** source definitions under `data_contracts/dlt`,
**Great Expectations** suites under `data_contracts/gx`, and **DVC** remote
configuration in `.dvc/config` / `data_contracts/dvc/config.template`. Local
tests keep a deterministic fallback when those tools are not installed, but
Compose images install the declared Python dependencies and copy
`data_contracts/` into API and worker containers. Full-stack Compose sets
`ALLOW_MATURE_TOOL_FALLBACK=false`, so missing **dlt**, **Great Expectations**,
**DVC**, or **MLflow** integration fails instead of producing placeholder
evidence.

Quant research/report workers install the fixed v0.3 Python stack from
`apps/api/pyproject.toml`, including **Qlib**, **RD-Agent**,
**alphalens-reloaded**, **QuantStats**, and **PyPortfolioOpt**.
