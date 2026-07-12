# Quant Team OS Product Experience Agent Team

## Team Roles

Leader owns product direction, implementation sequencing, and final quality gates.

A, Product Manager, owns information architecture, user tasks, and product priority.

B, UI/UX Expert, owns visual hierarchy, interaction model, layout, density, and acceptance criteria for screens.

C, Frontend Engineer, owns `apps/control-ui`, component behavior, state handling, routing, and UI tests.

D, Backend Engineer, owns `apps/api`, data contracts, provider connection semantics, agent graph contracts, policy enforcement, and seed data.

E, Test And Risk, owns contract tests, smoke tests, policy regressions, secret handling, approval gates, and live-trading safety.

## Current Product Judgment

The product should stop behaving like a feature directory and move toward a task-driven quant workbench.

The primary user path is:

```text
Portfolio state -> Research task -> Backtest evidence -> Risk review -> Paper candidate -> Live locked decision -> Monitoring
```

The three top-level entries remain:

```text
工作台
策略研究
智能体管理
```

However, the user's default path should begin in 工作台. 策略研究 and 智能体管理 should support the daily decision flow instead of competing as isolated modules.

## Current Problems

1. 工作台 currently shows useful fragments, but it does not yet behave like a daily decision center.

2. 策略研究 is not visibly connected to portfolio impact, account constraints, risk gates, and paper/live promotion.

3. 智能体管理 still reads too much like an object-management canvas. It should become a task execution and traceability view.

4. 持仓连接 must support multiple holdings sources. A single QuantConnect-only form is not enough. IBKR must be visible, but live trading must remain locked.

## Product Direction

### 工作台

工作台 should become 今日决策中心.

Required areas:

- 持仓与账户
- 待处理研究
- 智能体运行任务
- 风险与审批

Every visible item should answer:

- What is happening?
- Why does it matter?
- Who or which agent owns the next step?
- What action can the user safely take?

### 策略研究

策略研究 should expose a strategy lifecycle:

```text
Idea -> Research -> Backtest -> Paper -> Live -> Monitor
```

Each strategy should show:

- current lifecycle stage
- latest evidence
- linked factors
- linked backtests
- linked agent runs
- risk verdict
- approval status
- portfolio or holdings impact where available
- next action

### 智能体管理

智能体管理 should not be a freeform agent object board.

It should become an execution canvas:

- stage-based lanes from left to right
- agents grouped by task phase, not arbitrary system buckets
- edge animation only for active work
- node status visible through compact text status and current task
- click node for configuration, evidence, tool connections, logs, and policy decisions
- default view should show the task flow, not every low-level configuration field

Recommended stage model:

```text
Data -> Research -> Strategy -> Backtest -> Risk -> Approval -> Execution
Monitoring/Audit as an overlay layer
```

## Holdings Connection Direction

持仓连接 should remain inside 工作台.

The modal should be a collapsible source list:

- QuantConnect Paper
- IBKR
- 手动/模拟持仓

IBKR must be visible but locked:

- `live trading locked`
- no direct live execution
- backend policy remains the final safety boundary
- frontend only exposes the source and explains the lock

## This Round Priority

1. Make 工作台 a daily decision center.

2. Improve 持仓连接 as a multi-source holdings list.

3. Rework 智能体管理 into a stage-based execution canvas.

4. Add contract tests that prevent regressions back to single-provider connection or freeform canvas clutter.

## This Round Non-Goals

- Do not redesign the brand or full visual language.
- Do not add more agent types before current agents have clear task roles.
- Do not unlock live trading.
- Do not add real broker trading execution.
- Do not build a complex multi-account portfolio accounting engine before the product flow is clear.

## Safety Gates

The following rules must keep passing:

- Live trading defaults to locked.
- `can_execute_live_trade=false` remains enforced.
- Approval requires a human comment.
- Secrets are never rendered back to the frontend.
- API keys are submitted only to backend connection endpoints.
- Frontend permission display is never the only security boundary.

## Team Workflow

For every product-experience iteration:

1. A defines the user task and priority.
2. B defines the interaction and visible hierarchy.
3. C implements the smallest frontend change that supports the task.
4. D verifies backend/data contract support.
5. E adds or updates tests and safety checks.
6. Leader reviews whether the result improves the real task flow.

