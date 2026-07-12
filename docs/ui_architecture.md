# UI Architecture

Quant Team OS uses a task-first control UI. Mature external tools remain connected, but the main product no longer exposes a feature-directory navigation.

Primary navigation:

```text
工作台
策略研究
智能体管理
```

## Surfaces

- **Control UI**: built with **React**, **Ant Design**, and **React Flow / xyflow**.
- **工作台**: daily status, holdings sources, risk alerts, approval work, research decisions, and running tasks.
- **策略研究**: research pipeline, factors and strategies, experiments/backtests, and reports.
- **智能体管理**: one **Agent Canvas** for agents, tool connections, permissions, workflow state, logs, and policy evidence.
- **External mature tools**: Chainlit, OpenBB, Superset, Grafana, Temporal UI, MLflow UI, Langfuse UI, JupyterLab, MinIO Console, Infisical UI, and Keycloak Admin Console stay external. They are linked from agent tool configuration, activity records, or relevant details instead of being first-level pages.

## Routing Rules

Canonical routes:

```text
/dashboard
/research/pipeline
/research/factors-strategies
/research/experiments
/research/reports
/agents/canvas
```

Legacy routes are compatibility redirects:

```text
/connections -> /agents/canvas?panel=connections
/workflows -> /agents/canvas?panel=workflows
/audit-log -> /agents/canvas?panel=audit
/settings -> /agents/canvas?panel=settings
/external-workspaces -> /agents/canvas?panel=tools
/research-lab -> /research/pipeline
/factor-library -> /research/factors-strategies?tab=factors
/strategy-registry -> /research/factors-strategies?tab=strategies
/backtest-center -> /research/experiments
/risk-center -> /dashboard?panel=risk
/approvals -> /dashboard?panel=approvals
/paper-trading -> /dashboard?panel=portfolio
```

Legacy `panel` query parameters should open the matching drawer, tab, or modal when feasible. They should not strand the user on an empty generic canvas.

## Design Rules

- The first screen is the working product, not a landing page.
- The UI must stay dense, restrained, and scannable.
- Status text must be visible, not color-only.
- Normal empty/idle states should not create noise.
- Raw backend enum values, raw IDs, and JSON payloads should not be primary user-facing copy.
- Cards are for repeated objects and configuration panels, not nested page decoration.
- Agent detail, tool connection, workflow activity, audit, and settings live inside the **Agent Canvas** context.

## Safety Rules

- FastAPI remains the only write boundary for lifecycle state.
- The frontend only displays permissions; backend policy remains authoritative.
- Raw secrets must never be rendered after submit.
- Secret references are allowed only as masked status or path-like references.
- **Live trading** remains visibly locked in MVP.
- `can_execute_live_trade=false` must remain enforced in backend responses and persisted agent config.
