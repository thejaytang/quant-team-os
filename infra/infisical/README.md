# Infisical Bootstrap

Quant Team OS stores provider credentials in **Infisical**. PostgreSQL stores
only secret refs.

Bootstrap order:

```bash
cp .env.example .env
docker compose --env-file .env -f infra/docker-compose.yml up -d postgres infisical
```

Then open `http://localhost:8082`, create a project and machine identity, and
copy these values into `.env`:

```text
INFISICAL_PROJECT_ID
INFISICAL_MACHINE_IDENTITY_CLIENT_ID
INFISICAL_MACHINE_IDENTITY_CLIENT_SECRET
```

After that:

```bash
python3 scripts/full_stack_doctor.py --env .env
docker compose --env-file .env -f infra/docker-compose.yml up --build
python3 scripts/full_stack_doctor.py --env .env --live
```

Do not put provider API keys in `.env`. Connect OpenAI, Massive, QuantConnect,
and other providers through the Control UI or Infisical UI so the API stores
only secret refs.
