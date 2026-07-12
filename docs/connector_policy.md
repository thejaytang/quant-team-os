# Connector Policy

Quant Team OS treats external systems as governed connectors. The backend stores connection metadata in PostgreSQL and stores provider credentials only as **Infisical** secret references.

Connector actions follow this path:

```text
Refine or Chainlit request
→ FastAPI RBAC guard
→ ToolGateway
→ OPA agent/connector policy
→ Infisical secret fetch
→ adapter call
→ ToolCall and AuditLog rows
→ OpenTelemetry span
```

Rules:

- No connector may read raw secrets from PostgreSQL.
- No connector may return raw secrets to UI, audit logs, Langfuse, MLflow, or Loki.
- Read-only UI connectors such as OpenBB, Superset, Grafana, JupyterLab, Temporal UI, MLflow, Langfuse, MinIO, Infisical, and Keycloak must not mutate StrategyCard lifecycle state.
- `QuantConnectPaperAdapter` may prepare paper deployment proposals only.
- `IBKRLockedAdapter` remains locked in MVP and must not place live orders.
