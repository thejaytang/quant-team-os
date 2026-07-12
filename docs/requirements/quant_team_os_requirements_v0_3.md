# Quant Team OS 开发需求文档 v0.3

> 目标读者：Codex / 工程开发智能体  
> 项目性质：个人版量化研究、策略验证、风险治理、审批和受控 paper/live trading 操作系统  
> 设计原则：**Tool-first, agent-orchestrated, policy-governed, human-approved**  
> 本版变化：把 v0.2 中仍然偏自建的基础设施替换为成熟项目。自建代码只允许承担 glue、adapter、domain schema 和 UI wiring。

---

## 0. 核心判断

本项目不是从零开发量化平台、BI 系统、风控平台、密钥系统、权限系统、workflow engine、实验平台或监控平台。

本项目要做的是：

```text
把成熟工具接入一个统一的 Quant Team OS
让 agent 团队通过受控 adapter 使用这些工具
让 policy engine 和 human approval 管住所有敏感动作
让 UI 复用成熟项目，只自建业务 glue 页面
```

最终系统边界：

```text
Mature tools do the heavy work.
Quant Team OS coordinates them.
Agents request actions.
Policies decide gates.
Humans approve promotions.
Live trading is locked by default.
```

---

## 1. v0.2 审计结论：哪些地方还自建过重

v0.2 已经使用了成熟 UI 项目，但仍有这些地方不够 **Tool-first**：

| v0.2 位置 | 问题 | v0.3 固定替换 |
|---|---|---|
| 自建 `APP_MASTER_KEY` secret encryption | 不应自己管理密钥生命周期、轮换、审计 | **Infisical** |
| 自建 auth / `users` 表 | 不应自己写登录、OIDC、session、RBAC | **Keycloak** |
| `Prefect` 承担长流程和 approval | 适合数据 workflow，但不够适合长时间 human-in-the-loop agent workflow | **Temporal** |
| 自建 `RiskPolicyEngine` 硬规则 | 不应把关键 gate 写死在 Python if/else | **Open Policy Agent** |
| 自建 data quality checks | 不应自己写完整数据质量框架 | **Great Expectations** |
| 自建 market data ingestion framework | 不应手写通用 ETL 框架 | **dlt** |
| 本地 artifact folder | 不适合长期 artifact、HTML report、Parquet、MLflow artifact | **MinIO** S3-compatible object storage |
| 无 dataset versioning | 回测不可复现 | **DVC** with MinIO remote |
| 结构化 JSON logs + Grafana | 缺少标准 observability pipeline | **OpenTelemetry + Prometheus + Loki + Grafana** |
| MLflow 同时承担 agent trace | MLflow 适合量化实验，但 LLM/agent 追踪应专用 | **Langfuse** |
| 自建 notebook/research viewing | 不应自己做 notebook UI | **JupyterLab** |
| `PaperExecutionAdapter` stub | paper trading 不应自己模拟 | **QuantConnect Paper Trading** |
| `IBKRLockedAdapter` 作为未来直连 | MVP 不应直连 broker | **QuantConnect IBKR integration** future-only, live locked |
| `SandboxCodeRunner` | 不应让 agent 任意运行代码 | 删除。只允许通过 Temporal activity 调用成熟工具，或在 JupyterLab 人工运行 |

v0.3 后，Quant Team OS 的自建部分只保留：

```text
1. Thin FastAPI orchestration API
2. ToolAdapter / Connector glue
3. Domain schema: StrategyCard, ResearchIdea, ApprovalRequest 等
4. Refine resource pages and OpenBB widget backend
5. OPA input assembly and audit event writing
6. Temporal workflow definitions and activities
```

这些不是“造轮子”，而是把成熟工具粘到同一个业务系统里必须写的胶水层。

---

## 2. 固定技术栈

本项目不再提供多选方案。Codex 必须按以下固定栈实现。

### 2.1 Runtime / API / Glue

| 层 | 固定项目 | 作用 |
|---|---|---|
| Backend API | `FastAPI` | 只做 orchestration API 和 glue，不重造平台 |
| Data model | `Pydantic v2` + `SQLAlchemy 2.x` | API schema 和 PostgreSQL mapping |
| Main DB | `PostgreSQL` | domain metadata、StrategyCard、ApprovalRequest、AuditLog |
| Workflow engine | **Temporal** | durable workflow、agent workflow、human approval waiting、retries |
| Policy engine | **Open Policy Agent** | approval gate、agent permission、trading lock、connector policy |
| Secret manager | **Infisical** | API keys、broker credentials、service tokens |
| Identity provider | **Keycloak** | login、OIDC、RBAC、service account |

### 2.2 Agent / AI

| 层 | 固定项目 | 作用 |
|---|---|---|
| Agent runtime | **OpenAI Agents SDK** | multi-agent、tools、handoffs、guardrails |
| Agent chat UI | **Chainlit** | agent chat、tool call 展示、human action buttons |
| LLM observability | **Langfuse** | agent trace、LLM call、token、cost、prompt/version tracking |

### 2.3 Quant / Research / Backtest

| 层 | 固定项目 | 作用 |
|---|---|---|
| Quant research | **Qlib** | factor/model research、research-stage backtest |
| Automated quant R&D | **RD-Agent** | automated quant research engine |
| Standard backtest | **QuantConnect MCP Server + LEAN** | 创建项目、运行标准化 backtest、读取结果 |
| Market data | **Massive** | market data API / MCP |
| Factor analytics | **alphalens-reloaded** | factor tear sheet |
| Performance analytics | **QuantStats** | strategy tear sheet |
| Portfolio suggestion | **PyPortfolioOpt** | target weights suggestion, not direct trading |
| Paper trading | **QuantConnect Paper Trading** | paper trading only |
| Live trading | **QuantConnect + IBKR future-only** | MVP 只显示 locked，不执行 |

### 2.4 Data / Artifact / Versioning

| 层 | 固定项目 | 作用 |
|---|---|---|
| Data ingestion | **dlt** | Massive → structured datasets |
| Data quality | **Great Expectations** | OHLCV、missing data、timestamp、duplicate、split-adjustment checks |
| Local analytics | **DuckDB** | Parquet query、factor/backtest analysis |
| Object storage | **MinIO** | reports、Parquet、MLflow artifacts、DVC remote |
| Data versioning | **DVC** | dataset version, backtest reproducibility |
| Experiment tracking | **MLflow** | experiment runs、metrics、artifacts、model/strategy registry links |
| Notebook UI | **JupyterLab** | human research review、notebook exploration |

### 2.5 UI / Observability

| UI 位置 | 固定项目 | 作用 |
|---|---|---|
| Core control UI | **Refine + Ant Design** | Connect Center、Strategy Registry、Approval Center、Risk Center |
| Financial workspace | **OpenBB Workspace custom backend** | financial widgets |
| BI dashboard | **Apache Superset** | strategy/backtest/factor aggregate analytics |
| Monitoring UI | **Grafana** | metrics/logs/health dashboard |
| Workflow UI | **Temporal Web UI** | workflow execution、retries、signals |
| Experiment UI | **MLflow UI** | experiment metrics and artifacts |
| LLM trace UI | **Langfuse UI** | agent/LLM traces |
| Notebook UI | **JupyterLab** | notebook-based research |
| Object UI | **MinIO Console** | artifact/object browsing for admin only |
| Secret UI | **Infisical UI** | secret admin and audit |
| Auth UI | **Keycloak Admin Console** | users, roles, clients |

---

## 3. 使用的成熟项目与链接

Codex 必须优先阅读官方仓库或文档，不要替换主栈。

| 用途 | 项目 | 链接 |
|---|---|---|
| Agent runtime | OpenAI Agents SDK Python | https://github.com/openai/openai-agents-python |
| Workflow | Temporal | https://github.com/temporalio/temporal |
| Temporal Python SDK | temporalio/sdk-python | https://github.com/temporalio/sdk-python |
| Policy engine | Open Policy Agent | https://github.com/open-policy-agent/opa |
| Secrets | Infisical | https://github.com/Infisical/infisical |
| Identity | Keycloak | https://github.com/keycloak/keycloak |
| Control UI framework | Refine | https://github.com/refinedev/refine |
| Enterprise UI | Ant Design | https://github.com/ant-design/ant-design |
| Agent chat UI | Chainlit | https://github.com/Chainlit/chainlit |
| OpenBB backend examples | backends-for-openbb | https://github.com/OpenBB-finance/backends-for-openbb |
| BI | Apache Superset | https://github.com/apache/superset |
| Monitoring UI | Grafana | https://github.com/grafana/grafana |
| Metrics | Prometheus | https://github.com/prometheus/prometheus |
| Logs | Grafana Loki | https://github.com/grafana/loki |
| Telemetry standard | OpenTelemetry | https://github.com/open-telemetry/opentelemetry-collector |
| LLM observability | Langfuse | https://github.com/langfuse/langfuse |
| Object storage | MinIO | https://github.com/minio/minio |
| Data ingestion | dlt | https://github.com/dlt-hub/dlt |
| Data quality | Great Expectations | https://github.com/great-expectations/great_expectations |
| Data versioning | DVC | https://github.com/treeverse/dvc |
| Notebook UI | JupyterLab | https://github.com/jupyterlab/jupyterlab |
| Experiment tracking | MLflow | https://github.com/mlflow/mlflow |
| Quant research | Microsoft Qlib | https://github.com/microsoft/qlib |
| Automated quant R&D | Microsoft RD-Agent | https://github.com/microsoft/RD-Agent |
| Standard backtest/live engine | QuantConnect LEAN | https://github.com/QuantConnect/Lean |
| QuantConnect agent bridge | QuantConnect MCP Server | https://github.com/QuantConnect/mcp-server |
| Market data MCP | Massive MCP Server | https://github.com/massive-com/mcp_massive |
| Factor analytics | alphalens-reloaded | https://github.com/stefan-jansen/alphalens-reloaded |
| Performance analytics | QuantStats | https://github.com/ranaroussi/quantstats |
| Portfolio optimization | PyPortfolioOpt | https://github.com/PyPortfolio/PyPortfolioOpt |
| Local analytics DB | DuckDB | https://github.com/duckdb/duckdb |

---

## 4. Monorepo 结构

```text
quant-team-os/
├── apps/
│   ├── api/                    # FastAPI orchestration API only
│   ├── workers/                # Temporal workers and activities
│   ├── control-ui/             # Refine + Ant Design
│   ├── agent-chat/             # Chainlit
│   └── openbb-backend/         # OpenBB Workspace widget provider
│
├── policy/
│   ├── opa/
│   │   ├── agent.rego
│   │   ├── connector.rego
│   │   ├── strategy_lifecycle.rego
│   │   ├── trading_lock.rego
│   │   └── approval.rego
│   └── tests/
│
├── data_contracts/
│   ├── gx/                     # Great Expectations suites
│   ├── dlt/                    # dlt sources/pipelines
│   └── dvc/                    # DVC config templates
│
├── notebooks/                  # JupyterLab notebooks, human-readable research only
├── artifacts/                  # local dev mirror only; production artifact goes to MinIO
├── infra/
│   ├── docker-compose.yml
│   ├── keycloak/
│   ├── infisical/
│   ├── temporal/
│   ├── opa/
│   ├── minio/
│   ├── mlflow/
│   ├── langfuse/
│   ├── grafana/
│   ├── prometheus/
│   ├── loki/
│   ├── superset/
│   └── jupyterlab/
│
├── docs/
│   ├── architecture.md
│   ├── agent_policy.md
│   ├── connector_policy.md
│   ├── workflow_design.md
│   ├── risk_and_approval.md
│   ├── ui_architecture.md
│   └── strategy_card_template.md
│
└── README.md
```

---

## 5. 系统总架构

```text
┌─────────────────────────────────────────────────────────────┐
│ Mature UI Layer                                             │
│ Refine / Chainlit / OpenBB / Superset / Grafana / MLflow    │
│ Temporal UI / Langfuse / JupyterLab / Infisical / Keycloak  │
└─────────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────────┐
│ FastAPI Thin Orchestration API                              │
│ Connect Center / Strategy Registry / Approval API / Audit   │
└─────────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────────┐
│ Temporal Durable Workflows                                  │
│ ResearchWorkflow / BacktestWorkflow / ApprovalWorkflow      │
│ DataIngestionWorkflow / PaperTradingWorkflow                │
└─────────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────────┐
│ Agent Activities                                            │
│ OpenAI Agents SDK + Chainlit Bridge + Langfuse Trace        │
└─────────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────────┐
│ Tool Gateway                                                │
│ OPA policy check → Infisical secret fetch → adapter call    │
│ → audit log → OpenTelemetry trace                           │
└─────────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────────┐
│ Mature Quant/Data Tools                                     │
│ Qlib / RD-Agent / QuantConnect MCP / LEAN / Massive / dlt   │
│ Great Expectations / Alphalens / QuantStats / PyPortfolioOpt│
└─────────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────────┐
│ State, Artifact, Observability                              │
│ PostgreSQL / MinIO / DVC / DuckDB / MLflow / Langfuse       │
│ Prometheus / Loki / Grafana                                 │
└─────────────────────────────────────────────────────────────┘
```

---

## 6. Auth 与 RBAC

### 6.1 固定方案

使用 **Keycloak**，不自建用户登录系统。

Keycloak realm：`quant-team-os`

Keycloak clients：

```text
control-ui
api
chainlit
superset
jupyterlab
mlflow
langfuse
```

### 6.2 角色

```text
admin
researcher
risk_reviewer
approver
viewer
service_account
```

### 6.3 API 规则

FastAPI 必须验证 Keycloak JWT。

```text
1. 所有 API 默认需要 authenticated user。
2. agent service account 不能审批。
3. approver 角色才能调用 /approvals/{id}/approve。
4. admin 才能修改 connector config、policy bundle、system settings。
5. viewer 只能读 StrategyCard、BacktestResult、Report artifact。
```

Refine 使用 OIDC login，不实现自建 password form。

---

## 7. Secret 与 Connect Center

### 7.1 固定方案

使用 **Infisical** 管理所有 secret。

PostgreSQL 不保存 secret ciphertext，只保存 secret reference。

```python
class ExternalConnection(Base):
    id: UUID
    provider: str
    display_name: str
    status: Literal["disconnected", "connected", "error", "locked"]
    permissions: list[str]
    infisical_secret_path: str | None
    secret_version: str | None
    metadata: dict
    last_checked_at: datetime | None
    last_error: str | None
    created_by_user_id: str
    created_at: datetime
    updated_at: datetime
```

### 7.2 Connect Center UI

Refine `/connections` 页面必须显示这些 card：

```text
OpenAI API
Massive Market Data
QuantConnect
OpenBB Workspace
MLflow
Langfuse
Superset
Grafana
Temporal
JupyterLab
Infisical
Keycloak
MinIO
Chainlit
IBKR via QuantConnect - Locked
```

每个 card 必须有：

```text
Status: disconnected / connected / error / locked
Permissions
Last checked
[Connect] [Test] [Disconnect] [Open UI] [View audit]
```

### 7.3 Secret 流程

```text
1. Human clicks Connect.
2. Refine opens provider-specific form.
3. FastAPI validates user role through Keycloak JWT.
4. FastAPI sends secret to Infisical.
5. FastAPI stores only infisical_secret_path in PostgreSQL.
6. FastAPI immediately starts Temporal ConnectionTestWorkflow.
7. ToolGateway uses Infisical machine identity to fetch secret at runtime.
8. Secret never enters agent prompt, agent trace, audit log, Langfuse, MLflow, Loki, or UI response.
```

### 7.4 Agent 规则

```text
Agent cannot ask user for API keys.
Agent cannot read secret values.
Agent can request `connection_status(provider)` only.
ToolGateway resolves secrets after OPA permits the tool call.
```

---

## 8. Policy 与风控 gate

### 8.1 固定方案

使用 **Open Policy Agent** 执行 gate decision。

Python 不再实现一个完整 `RiskPolicyEngine`。Python 只负责计算 risk metrics 和组装 OPA input。

```text
RiskMetricsService:
    使用 QuantStats / PyPortfolioOpt / custom minimal statistics 计算指标

OPA:
    决定是否允许 status transition、tool call、paper promotion、live unlock
```

### 8.2 OPA policy package

```text
policy/opa/agent.rego
policy/opa/connector.rego
policy/opa/strategy_lifecycle.rego
policy/opa/trading_lock.rego
policy/opa/approval.rego
policy/opa/risk_gate.rego
```

### 8.3 OPA input 示例

```json
{
  "user": {
    "id": "keycloak-sub",
    "roles": ["approver"]
  },
  "agent": {
    "name": "RiskAgent",
    "service_account": true
  },
  "action": "promote_to_paper",
  "strategy": {
    "id": "uuid",
    "status": "STRATEGY_REGISTERED",
    "latest_backtest": {
      "sharpe": 1.02,
      "max_drawdown": 0.18,
      "has_cost_model": true,
      "has_slippage_model": true,
      "years": 5
    },
    "latest_risk_review": {
      "verdict": "pass"
    }
  },
  "approval": {
    "status": "approved",
    "approved_by_human": true
  },
  "system": {
    "allow_live_trading": false
  }
}
```

### 8.4 硬规则

OPA 必须拒绝：

```text
1. allow_live_trading=false 时任何 live order。
2. agent 发起 approval approve/reject。
3. 没有 cost model 的 backtest promotion。
4. 没有 slippage model 的 backtest promotion。
5. 没有 factor report 的 factor strategy registration。
6. 没有 human approval 的 strategy registration 或 paper promotion。
7. connector 未 connected 时调用外部平台。
8. Chainlit action 直接改变策略状态。
9. OpenBB/Superset/Grafana/JupyterLab 修改核心状态。
10. secret 出现在任何 log/trace/artifact payload。
```

---

## 9. Temporal workflow 设计

### 9.1 原则

```text
1. 所有长流程必须用 Temporal。
2. Workflow code 必须 deterministic。
3. LLM call、API call、Qlib run、backtest run、report generation 都必须是 Temporal Activity。
4. Human approval 必须通过 Temporal Signal 恢复 workflow。
5. Temporal Workflow ID 必须写入 agent_runs / strategy_cards / approval_requests。
```

### 9.2 Workflows

```text
ConnectionTestWorkflow(provider)
DataIngestionWorkflow(provider, dataset_spec)
ResearchWorkflow(research_idea_id)
FactorAnalysisWorkflow(factor_spec_id)
BacktestWorkflow(strategy_id, engine)
RiskReviewWorkflow(strategy_id, backtest_run_id)
StrategyRegistrationWorkflow(strategy_id)
PaperPromotionWorkflow(strategy_id)
ReportGenerationWorkflow(owner_type, owner_id)
```

### 9.3 Human approval with signal

Approval flow：

```text
1. Workflow reaches approval gate.
2. Activity creates ApprovalRequest in PostgreSQL.
3. Workflow waits for Temporal Signal: approval_resolved.
4. Refine Approval Center approve/reject action calls FastAPI.
5. FastAPI validates Keycloak role.
6. FastAPI asks OPA whether the user can resolve the request.
7. FastAPI writes ApprovalRecord.
8. FastAPI sends signal to Temporal workflow.
9. Workflow continues or stops.
```

---

## 10. Agent 团队设计

### 10.1 Agent runtime

所有 agent 使用 **OpenAI Agents SDK**。

Agent calls must be invoked only inside Temporal Activities.

Agent output must be structured Pydantic object, not free-form chat as system state.

### 10.2 Agent 列表

| Agent | 责任 | 可调用 mature tools | 不允许 |
|---|---|---|---|
| ChiefAgent | 拆解任务、调度 workflow、汇总结果 | Temporal query、StrategyRegistry read | 不能审批、不能下单 |
| ResearchAgent | 生成可测试 hypothesis | RD-Agent、OpenBB data widgets、Qlib metadata | 不能宣布策略有效 |
| DataAgent | 请求数据准备和质量验证 | dlt、Great Expectations、DuckDB | 不能绕过 data quality |
| FactorAgent | 生成 FactorSpec 和分析请求 | Qlib、alphalens-reloaded | 不能跳过 factor tear sheet |
| BacktestAgent | 运行研究和标准回测 | Qlib、QuantConnect MCP、LEAN、QuantStats | 不能推进状态 |
| RiskAgent | 解释风险指标和 OPA 结果 | QuantStats metrics、PyPortfolioOpt、OPA decision read | 不能覆盖 OPA |
| PortfolioAgent | 生成目标权重建议 | PyPortfolioOpt | 不能生成 broker order |
| ExecutionAgent | 仅格式化 paper proposal | QuantConnect Paper Trading future activity | MVP 不能 live |
| MonitoringAgent | 总结运行状态 | Grafana、Prometheus、Loki、Temporal query | 不能改策略 |
| ReportAgent | 生成 memo、StrategyCard、report summary | MLflow、MinIO artifact、Jupyter notebooks read | 不能改实验数据 |
| ComplianceAgent | 检查 audit、policy、approval consistency | OPA、AuditLog、Infisical audit ref | 不能审批自己的请求 |

### 10.3 ToolGateway

所有 agent tool call 必须经过 `ToolGateway`。

```python
class ToolGateway:
    async def request_tool_call(
        self,
        agent_name: str,
        tool_name: str,
        payload: dict,
        workflow_id: str,
        user_context: UserContext,
    ) -> ToolResult:
        # 1. build OPA input
        # 2. call OPA
        # 3. if denied: write audit + raise PolicyDenied
        # 4. fetch secret from Infisical if needed
        # 5. call adapter
        # 6. write PostgreSQL audit log
        # 7. emit OpenTelemetry span
        # 8. log Langfuse trace metadata for LLM-related calls
        # 9. store artifact in MinIO/MLflow if needed
```

Agent never imports Qlib, RD-Agent, QuantConnect, Massive SDK, or broker SDK directly.

---

## 11. Data layer

### 11.1 Data ingestion

Use **dlt**. Do not hand-roll a generic ETL framework.

Required pipeline：

```text
MassiveDltSource
→ dlt pipeline
→ PostgreSQL metadata tables
→ Parquet files in MinIO
→ DVC versioned dataset
→ DuckDB query layer
→ QlibDataConverter
```

允许自建的只有 `MassiveDltSource`，因为它是外部 API 到 dlt 的 source definition，不是完整 ETL 框架。

### 11.2 Data quality

Use **Great Expectations**.

Required expectation suites：

```text
gx/ohlcv_daily_suite.json
    no null symbol/date/open/high/low/close/volume
    high >= low
    open/close within high-low range
    date strictly increasing per symbol
    no duplicate symbol-date
    volume >= 0

gx/factor_values_suite.json
    no duplicate factor-symbol-date
    finite numeric values
    no extreme missing ratio

gx/backtest_orders_suite.json
    no negative quantity unless sell/short semantics explicitly encoded
    timestamp present
    symbol present
```

GX validation result must be stored as artifact and linked to `DatasetSpec`.

### 11.3 Dataset versioning

Use **DVC**.

Rules：

```text
1. Every DatasetSpec must include dvc_rev or dataset_version.
2. Every BacktestRun must bind dataset_version.
3. MinIO is DVC remote.
4. Re-running the same BacktestRun must be able to pull the same DVC dataset version.
```

### 11.4 Object storage

Use **MinIO**.

Buckets：

```text
qto-artifacts
qto-datasets
qto-mlflow
qto-reports
qto-dvc
```

No production artifact should depend on local disk.

### 11.5 DuckDB

DuckDB is query engine for Parquet.

Required adapter methods：

```text
query_bars(symbols, start, end, frequency, dataset_version)
query_factor_values(factor_id, start, end, dataset_version)
query_backtest_equity(backtest_run_id)
query_orders(backtest_run_id)
```

---

## 12. Research / Backtest / Report tools

### 12.1 Qlib

Qlib handles factor/model research and research-stage backtesting.

Qlib output：

```text
FactorSpec
QlibExperimentRun
QlibMetrics
QlibArtifactRef
```

### 12.2 RD-Agent

RD-Agent is called by ResearchAgent as an external quant R&D engine.

RD-Agent output must be normalized into：

```text
ResearchIdea revision
FactorSpec candidate
ModelSpec candidate
Experiment summary
Artifact refs
```

### 12.3 QuantConnect MCP + LEAN

QuantConnect MCP is the standard backtesting bridge.

Required functions through adapter：

```text
create_project
upload_strategy_files
run_backtest
poll_backtest_status
fetch_backtest_result
fetch_backtest_charts_or_links
```

LEAN project files must be stored as artifacts and linked to StrategySpec.

### 12.4 Alphalens and QuantStats

```text
Alphalens:
    factor tear sheet
    IC
    ICIR
    quantile returns
    turnover
    factor decay

QuantStats:
    strategy tear sheet
    equity curve
    drawdown
    monthly returns
    Sharpe
    Sortino
    volatility
```

Reports stored in MinIO and MLflow.

### 12.5 MLflow

MLflow tracks quant experiments, not secrets.

MLflow must store：

```text
params
metrics
artifact links
dataset_version
strategy_id
factor_id
Temporal workflow_id
Git commit
DVC revision
```

MLflow Model Registry can be used to register strategy artifacts, but StrategyCard lifecycle remains in PostgreSQL because it is domain-specific.

---

## 13. UI 层

### 13.1 UI 分工

```text
Refine + Ant Design:
    主控制台、Connect Center、Strategy Registry、Approval Center、Risk Center、Audit Log

Chainlit:
    Agent chat、tool call display、human action buttons

OpenBB Workspace:
    金融研究 widgets，只读

Superset:
    研究/策略/回测聚合 BI，只读

Grafana:
    system metrics/log monitoring，只读

Temporal UI:
    workflow run、retry、signal、activity 状态，只读入口

MLflow UI:
    experiment tracking、metrics、artifact，只读入口

Langfuse UI:
    LLM traces、prompt/version、token/cost，只读入口

JupyterLab:
    human research notebook UI，不能直接改 StrategyCard 状态

Infisical UI:
    secret admin, admin only

Keycloak Admin Console:
    identity/admin only

MinIO Console:
    artifact admin only
```

### 13.2 Refine Control Console

Refine 是业务 glue UI，不重造成熟 dashboard。

主导航必须按功能域分组，一级导航不得平铺所有页面：

```text
Command
    Overview
    Agent Console
    Workflows
    Audit Log

Research
    Research Lab
    Factor Library
    Strategy Registry
    Backtest Center

Governance
    Approval Center
    Risk Center
    Paper Trading

Platform
    Connect Center
    External Workspaces
    Settings
```

Refine 必须通过 FastAPI data provider 获取数据。

### 13.3 External Workspaces

必须实现 `/external-workspaces` 页面。

Cards：

```text
OpenBB Workspace
Superset
Grafana
Temporal UI
MLflow UI
Langfuse UI
JupyterLab
Infisical
Keycloak Admin
MinIO Console
Chainlit
QuantConnect Cloud
```

每个 card 必须显示：

```text
Status
Purpose
Permission level
[Open UI]
[Test Connection]
[View Audit]
```

### 13.4 Approval Center

Approval Center 是业务 glue UI，不能完全外包，因为它绑定 StrategyCard lifecycle。

但 durable waiting 和 state resume 必须由 Temporal 完成，permission gate 必须由 OPA 完成，human identity 必须来自 Keycloak。

Approval action：

```text
Approve
Reject
Request Changes
```

Every action requires human comment.

MVP refuses all live-related approvals through OPA.

---

## 14. Connectors / Tool Adapters

### 14.1 Adapter list

```text
OpenAIAdapter
MassiveAdapter
MassiveMCPAdapter
QlibAdapter
RDAgentAdapter
AlphalensAdapter
QuantConnectMCPAdapter
QuantStatsAdapter
PyPortfolioOptAdapter
MLflowAdapter
LangfuseAdapter
DltAdapter
GreatExpectationsAdapter
DVCAdapter
DuckDBAdapter
MinIOArtifactAdapter
OPAAdapter
InfisicalAdapter
TemporalWorkflowAdapter
KeycloakUserAdapter
OpenBBWidgetAdapter
SupersetLinkAdapter
GrafanaLinkAdapter
JupyterLabLinkAdapter
QuantConnectPaperAdapter
QuantConnectIBKRLockedAdapter
```

### 14.2 Adapter rules

```text
1. Adapter cannot read secret directly from DB.
2. Adapter receives secret only from ToolGateway after OPA approval.
3. Adapter must write ToolCall row.
4. Adapter must create OpenTelemetry span.
5. Adapter must redact secret before logging.
6. Adapter must store large output in MinIO.
7. Adapter must attach MLflow artifact when experiment-related.
8. Adapter must attach Langfuse trace when LLM-related.
```

---

## 15. Domain schema

PostgreSQL remains necessary for Quant Team OS domain state.

Required tables：

```text
external_connections
agent_runs
agent_messages
tool_calls
audit_logs
research_ideas
factor_specs
dataset_specs
strategy_specs
strategy_cards
backtest_runs
backtest_metrics
risk_reviews
approval_requests
approval_records
portfolio_proposals
paper_trading_sessions
trade_proposals
order_tickets
execution_reports
artifacts
system_events
workflow_links
policy_decisions
```

Do not store raw secret in any table.

### 15.1 Strategy lifecycle

```text
IDEA
→ RESEARCHING
→ FACTOR_TESTED
→ BACKTESTED
→ RISK_REVIEWED
→ APPROVAL_PENDING
→ STRATEGY_REGISTERED
→ PAPER_CANDIDATE
→ PAPER_APPROVED
→ PAPER_TRADING
→ LIVE_CANDIDATE
→ LIVE_LOCKED
→ RETIRED
```

No `LIVE_TRADING` state in MVP.

### 15.2 Artifact model

```python
class Artifact(Base):
    id: UUID
    artifact_type: str
    owner_type: str
    owner_id: UUID
    minio_bucket: str
    object_key: str
    content_type: str
    checksum: str
    mlflow_run_id: str | None
    dvc_rev: str | None
    metadata: dict
    created_at: datetime
```

---

## 16. API 设计

All API paths start with `/api/v1`.

### 16.1 Connections

```text
GET    /connections
GET    /connections/{provider}
POST   /connections/{provider}/connect
POST   /connections/{provider}/test
POST   /connections/{provider}/disconnect
GET    /connections/{provider}/audit
```

### 16.2 Workflows

```text
POST   /workflows/research
POST   /workflows/backtest
POST   /workflows/data-ingestion
POST   /workflows/risk-review
GET    /workflows/{workflow_id}
POST   /workflows/{workflow_id}/cancel
GET    /workflows/{workflow_id}/events
```

### 16.3 Agent runs

```text
POST   /agent-runs
GET    /agent-runs
GET    /agent-runs/{id}
GET    /agent-runs/{id}/events
GET    /agent-runs/{id}/langfuse-link
```

### 16.4 Research / Strategy

```text
POST   /research-ideas
GET    /research-ideas
GET    /research-ideas/{id}
POST   /research-ideas/{id}/start-workflow

GET    /factors
GET    /factors/{id}
POST   /factors/{id}/analyze

GET    /strategies
POST   /strategies
GET    /strategies/{id}
GET    /strategies/{id}/card
POST   /strategies/{id}/request-registration
POST   /strategies/{id}/request-paper-promotion
```

### 16.5 Backtests / Risk / Approvals

```text
POST   /backtests
GET    /backtests
GET    /backtests/{id}
GET    /backtests/{id}/artifacts

POST   /risk/reviews
GET    /risk/reviews
GET    /risk/reviews/{id}
GET    /risk/policy-decisions

GET    /approvals
GET    /approvals/{id}
POST   /approvals/{id}/approve
POST   /approvals/{id}/reject
POST   /approvals/{id}/request-changes
```

### 16.6 Artifacts / Audit / External UI

```text
GET    /artifacts
GET    /artifacts/{id}
GET    /artifacts/{id}/presigned-url

GET    /audit-logs
GET    /tool-calls
GET    /policy-decisions
GET    /system-events

GET    /external-workspaces
GET    /ui/openbb/widgets.json
GET    /ui/openbb/widgets/{widget_id}
GET    /ui/superset/dashboards
GET    /ui/grafana/dashboards
GET    /ui/mlflow/links
GET    /ui/langfuse/links
GET    /ui/temporal/links
GET    /ui/jupyterlab/links
```

---

## 17. 主要工作流

### 17.1 ResearchWorkflow

```text
Input: research_idea_id

1. ChiefAgentActivity creates research plan.
2. ResearchAgentActivity calls RD-Agent if needed.
3. DataIngestionWorkflow ensures required Massive data exists through dlt.
4. GreatExpectationsActivity validates dataset.
5. DVCActivity versions dataset.
6. FactorAgentActivity creates FactorSpec.
7. QlibActivity runs factor/model research.
8. AlphalensActivity generates factor report.
9. BacktestWorkflow runs QuantConnect/LEAN backtest.
10. QuantStatsActivity generates strategy report.
11. RiskMetricsActivity computes metrics.
12. OPAActivity evaluates strategy registration gate.
13. ReportAgentActivity creates StrategyCard and ResearchMemo.
14. ApprovalRequestActivity creates human approval.
15. Workflow waits for Temporal approval signal.
16. If approved, strategy state becomes STRATEGY_REGISTERED.
17. All artifacts saved to MinIO, MLflow, DVC when relevant.
18. Langfuse traces all LLM calls.
```

### 17.2 PaperPromotionWorkflow

```text
Input: strategy_id

1. Load StrategyCard.
2. Run latest OPA policy check.
3. Create ApprovalRequest.
4. Wait for human signal.
5. If approved and QuantConnect paper connector is connected:
   create QuantConnect paper trading deployment proposal.
6. MVP may create PaperTradingSession record only.
7. No self-built paper execution simulator.
```

### 17.3 DataIngestionWorkflow

```text
Input: provider, symbols, date_range, frequency

1. dlt extracts Massive data.
2. dlt loads structured dataset.
3. Export normalized Parquet to MinIO.
4. Run Great Expectations.
5. If GX fails, stop workflow and create system_event.
6. Commit DVC metadata.
7. Register DatasetSpec with dataset_version.
```

---

## 18. OpenBB Workspace custom backend

This remains a thin read-only widget provider.

Endpoints：

```text
GET /widgets.json
GET /widgets/strategy-registry
GET /widgets/backtest-summary
GET /widgets/factor-library
GET /widgets/risk-review
GET /widgets/research-progress
```

Rules：

```text
1. Read-only.
2. No secret.
3. No strategy state mutation.
4. No approval actions.
5. Each widget request emits OpenTelemetry span and access audit.
```

---

## 19. Observability

### 19.1 OpenTelemetry

All services must emit traces, metrics, and logs through OpenTelemetry Collector.

### 19.2 Prometheus

Prometheus scrapes metrics from：

```text
api
workers
temporal
opa
postgres exporters
minio exporters
```

### 19.3 Loki

Logs go to Loki.

Do not rely on raw local JSON logs as the monitoring source of truth.

### 19.4 Grafana dashboards

Required dashboards：

```text
Agent Runtime Monitoring
Temporal Workflow Monitoring
ToolGateway Policy Denials
OpenAI API Cost and Error Rate
Data Ingestion and GX Validation
Backtest Runtime and Failure
Connector Health
Trading Safety Lock
```

### 19.5 Langfuse

Every OpenAI Agents SDK run must create Langfuse trace.

Trace metadata：

```text
agent_name
workflow_id
research_idea_id
strategy_id
tool_calls
model
latency
token_usage
cost
policy_denials
artifact_ids
```

No secret may appear in Langfuse.

---

## 20. Docker Compose services

MVP `docker-compose.yml` must include：

```text
postgres
keycloak
infisical
temporal
temporal-ui
opa
minio
mlflow
langfuse
prometheus
loki
grafana
superset
jupyterlab
api
workers
control-ui
agent-chat
openbb-backend
```

Optional external SaaS endpoints can be used later, but MVP must run self-hosted local services where possible.

---

## 21. Environment variables

```env
APP_ENV=development
API_BASE_URL=http://localhost:8000
DATABASE_URL=postgresql+psycopg://qto_app:qto_app@postgres:5432/quant_team_os

# Keycloak
KEYCLOAK_BASE_URL=http://localhost:8080
KEYCLOAK_JWKS_URL=http://keycloak:8080/realms/quant-team-os/protocol/openid-connect/certs
KEYCLOAK_REALM=quant-team-os
KEYCLOAK_CLIENT_ID=api
KEYCLOAK_CLIENT_SECRET_REF=/quant-team-os/dev/keycloak/api-client-secret
VITE_KEYCLOAK_BASE_URL=http://localhost:8080
VITE_KEYCLOAK_REALM=quant-team-os
VITE_KEYCLOAK_CLIENT_ID=control-ui

# Infisical
INFISICAL_API_URL=http://infisical:8080
INFISICAL_PROJECT_ID=
INFISICAL_MACHINE_IDENTITY_CLIENT_ID=
INFISICAL_MACHINE_IDENTITY_CLIENT_SECRET=

# Temporal
TEMPORAL_ADDRESS=temporal:7233
TEMPORAL_NAMESPACE=default
ALLOW_TEMPORAL_FALLBACK=false
ALLOW_MATURE_TOOL_FALLBACK=false

# OPA
OPA_URL=http://opa:8181
ALLOW_LOCAL_POLICY_FALLBACK=false

# MinIO
S3_ENDPOINT_URL=http://minio:9000
S3_BUCKET_ARTIFACTS=qto-artifacts
S3_BUCKET_DATASETS=qto-datasets
S3_BUCKET_MLFLOW=qto-mlflow
S3_BUCKET_DVC=qto-dvc

# MLflow
MLFLOW_TRACKING_URI=http://mlflow:5000

# Langfuse
LANGFUSE_HOST=http://langfuse:3000
LANGFUSE_PUBLIC_KEY_REF=/quant-team-os/dev/langfuse/public-key
LANGFUSE_SECRET_KEY_REF=/quant-team-os/dev/langfuse/secret-key

# UI service URLs
CONTROL_UI_URL=http://localhost:5173
CHAINLIT_URL=http://localhost:8001
OPENBB_BACKEND_URL=http://localhost:8010
SUPERSET_URL=http://localhost:8088
GRAFANA_URL=http://localhost:3000
TEMPORAL_UI_URL=http://localhost:8233
JUPYTERLAB_URL=http://localhost:8888
MINIO_CONSOLE_URL=http://localhost:9001

# Safety
ALLOW_LIVE_TRADING=false
ALLOW_AGENT_ARBITRARY_CODE_EXECUTION=false
```

`ALLOW_LIVE_TRADING=false` and `ALLOW_AGENT_ARBITRARY_CODE_EXECUTION=false` are mandatory for MVP.

---

## 22. Testing requirements

### 22.1 Policy tests

```text
OPA denies live trading when ALLOW_LIVE_TRADING=false
OPA denies approval by agent service account
OPA denies strategy registration without human approval
OPA denies paper promotion without latest risk pass
OPA denies connector call when connection status != connected
OPA denies secret in tool payload
OPA policy tests run in CI
```

### 22.2 Secret tests

```text
Secret saved in Infisical, not PostgreSQL
Secret never returned by API
Secret never appears in audit_logs
Secret never appears in Langfuse trace
Disconnect removes or revokes secret reference
```

### 22.3 Workflow tests

```text
Temporal ResearchWorkflow reaches approval wait state
Approval Center sends Temporal signal
Rejected approval stops workflow
Approved registration updates StrategyCard
Workflow retry does not duplicate StrategyCard
Cancelled workflow writes audit event
```

### 22.4 Agent/tool tests

```text
Agent cannot import external SDK directly
All agent tool calls go through ToolGateway
ToolGateway writes ToolCall row
ToolGateway creates OTel span
Langfuse trace exists for each agent run
Policy denial is visible in Audit Log
```

### 22.5 Data tests

```text
dlt pipeline creates dataset metadata
Great Expectations fails invalid OHLCV data
DVC revision is attached to DatasetSpec
BacktestRun cannot start without dataset_version
MinIO artifact checksum is stored
DuckDB can query versioned Parquet dataset
```

### 22.6 UI tests

```text
Refine Connect Center renders all providers
Connect modal never displays raw secret after save
Approval action requires human comment
Live-related approval is disabled in MVP
External Workspaces page links all mature UIs
Chainlit action routes through Approval API
Strategy Registry displays StrategyCard lifecycle
```

---

## 23. MVP delivery scope

### 23.1 Must implement

```text
1. Monorepo scaffold
2. Docker Compose with all fixed services
3. Keycloak realm/client/role bootstrap
4. Infisical project/secret-path integration
5. Temporal workflows and workers
6. OPA policy bundle and policy tests
7. FastAPI thin orchestration API
8. Refine Control Console
9. Chainlit Agent Chat
10. OpenBB read-only widget backend
11. dlt Massive pipeline skeleton
12. Great Expectations OHLCV suite
13. DVC remote config using MinIO
14. MinIO artifact storage
15. MLflow tracking with MinIO artifact store
16. Langfuse tracing for agent runs
17. OpenTelemetry Collector + Prometheus + Loki + Grafana
18. Strategy Registry
19. Approval Center
20. Audit Log
21. Qlib sample research activity
22. QuantConnect MCP backtest adapter skeleton
23. Alphalens and QuantStats sample reports
24. External Workspaces page
25. Critical tests passing
```

### 23.2 May stub, but interface fixed

```text
RD-Agent full automation
QuantConnect real project upload/run loop
Massive full historical ingestion
QuantConnect Paper Trading deployment
IBKR live integration
Advanced OpenBB widgets
Advanced Superset dashboards
Advanced Grafana dashboards
```

### 23.3 Must not implement

```text
Direct IBKR API order execution
Self-built paper trading simulator
Self-built secret encryption system
Self-built login/password system
Self-built workflow engine
Self-built policy engine
Self-built BI/monitoring/experiment UI
Arbitrary agent code execution
Agent-driven live trading
```

---

## 24. Codex 开发顺序

```text
1. Create monorepo scaffold.
2. Add docker-compose with postgres, keycloak, infisical, temporal, temporal-ui, opa, minio, mlflow, langfuse, prometheus, loki, grafana, superset, jupyterlab.
3. Create FastAPI health endpoint.
4. Bootstrap Keycloak realm, clients, roles.
5. Implement JWT verification in FastAPI.
6. Integrate Infisical for secret refs.
7. Create PostgreSQL models and Alembic migrations.
8. Implement OPA policy bundle and policy tests.
9. Implement ToolGateway with OPA → Infisical → Adapter → Audit → OTel flow.
10. Implement Temporal workers and ConnectionTestWorkflow.
11. Build Refine Control Console scaffold.
12. Build Connect Center UI and API.
13. Build External Workspaces page.
14. Build Approval Center API and UI.
15. Implement Temporal approval signal flow.
16. Build Strategy Registry API and UI.
17. Integrate OpenAI Agents SDK inside Temporal activities.
18. Integrate Langfuse tracing.
19. Build Chainlit bridge and action buttons.
20. Implement dlt Massive skeleton pipeline.
21. Implement Great Expectations validation.
22. Implement DVC + MinIO dataset versioning.
23. Implement MLflow + MinIO artifact logging.
24. Implement Qlib sample activity.
25. Implement Alphalens and QuantStats sample report activities.
26. Implement QuantConnect MCP adapter skeleton.
27. Implement OpenBB widget backend.
28. Add Superset/Grafana starter dashboards.
29. Add tests and CI.
```

---

## 25. Definition of Done

第一版完成时，用户必须可以：

```text
1. 打开 Refine Control Console。
2. 通过 Keycloak 登录。
3. 在 Connect Center 连接 OpenAI、Massive、QuantConnect、MLflow、Langfuse、OpenBB、Superset、Grafana、JupyterLab 等。
4. Secret 存在 Infisical，不在 PostgreSQL。
5. 创建 ResearchIdea。
6. 启动 ResearchWorkflow。
7. Temporal UI 能看到 workflow。
8. Chainlit 能看到 agent steps。
9. Langfuse 能看到 LLM traces。
10. dlt/GX/DVC 能产生 versioned dataset artifact。
11. Qlib/Alphalens/QuantStats 能产生 sample artifacts。
12. Strategy Registry 出现 StrategyCard。
13. Approval Center 出现 pending approval。
14. Human approve 后 workflow 继续。
15. MLflow 能看到 experiment run。
16. OpenBB Workspace 能显示 read-only widgets。
17. Superset 能显示 strategy/backtest aggregate dashboard。
18. Grafana 能显示 runtime monitoring。
19. Audit Log 能追踪所有 tool call、policy decision、approval。
20. Live trading 仍然 locked。
```

---

## 26. 最终工程边界

Codex 必须遵守：

```text
不要重造 auth：用 Keycloak。
不要重造 secret manager：用 Infisical。
不要重造 workflow engine：用 Temporal。
不要重造 policy engine：用 OPA。
不要重造 ETL framework：用 dlt。
不要重造 data quality：用 Great Expectations。
不要重造 artifact store：用 MinIO。
不要重造 dataset versioning：用 DVC。
不要重造 observability：用 OpenTelemetry, Prometheus, Loki, Grafana。
不要重造 LLM observability：用 Langfuse。
不要重造 experiment tracking：用 MLflow。
不要重造 notebook UI：用 JupyterLab。
不要重造 BI：用 Superset。
不要重造 agent chat：用 Chainlit。
不要重造 financial workspace：用 OpenBB Workspace custom backend。
不要重造 backtest platform：用 QuantConnect MCP + LEAN。
不要重造 quant research platform：用 Qlib + RD-Agent。
不要重造 paper/live trading：用 QuantConnect Paper and future QuantConnect IBKR。
```

只允许自建：

```text
FastAPI glue API
Refine glue UI pages
ToolGateway and adapters
OPA input assembly
Temporal workflow definitions
Domain schema and state mapping
OpenBB widget provider
Report normalization
Audit mapping
```

这些是系统整合层，不是替代成熟工具。
