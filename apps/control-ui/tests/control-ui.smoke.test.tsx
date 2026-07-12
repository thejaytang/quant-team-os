import React from "react";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { App } from "../src/main";

function apiPayload(path: string, method: string) {
  if (method === "POST" && path === "/api/v1/connections/openai/connect") {
    return { provider: "openai", display_name: "OpenAI API", status: "connected", permissions: ["research_write"], metadata: { secret_ref: "/qto/openai" } };
  }
  if (method === "POST" && path === "/api/v1/connections/openai/test") {
    return { provider: "openai", status: "connected" };
  }
  if (method === "POST" && path === "/api/v1/agents/research-agent/runs") {
    return { id: "agent-run-new", task_type: "research-agent", status: "queued", input_payload: { agent_id: "research-agent" }, output_payload: {} };
  }
  if (method === "PUT" && path === "/api/v1/agent-graph") {
    return graphPayload;
  }
  const map: Record<string, unknown> = {
    "/api/v1/dashboard/summary": {
      portfolio: {
        mode: "unavailable",
        total_equity: null,
        cash: null,
        pnl_today: null,
        gross_exposure: null,
        net_exposure: null,
        source: "paper/simulated only; no live broker account connected",
      },
      status: { api: "healthy", live_trading_locked: true, environment: "development", last_refreshed_at: "2026-01-01T00:00:00Z" },
      counts: { pending_approvals: 1, risk_alerts: 1, running_workflows: 1, active_agent_runs: 1, disconnected_tools: 1, paper_sessions: 1 },
      approvals: [approvalPayload],
      risk_alerts: [riskPayload],
      running_tasks: [],
      connections: [],
    },
    "/api/v1/research/pipeline": {
      stages: [
        { key: "idea", label: "Idea", items: [] },
        { key: "data-prep", label: "数据准备", items: [] },
        { key: "researching", label: "研究中", items: [pipelineItem] },
        { key: "ready-backtest", label: "待回测", items: [] },
        { key: "backtest-complete", label: "回测完成", items: [] },
        { key: "ready-risk", label: "待风控", items: [] },
        { key: "waiting-approval", label: "待审批", items: [] },
        { key: "paper-candidate", label: "Paper Candidate", items: [] },
        { key: "archived", label: "Archived", items: [] },
      ],
    },
    "/api/v1/factors": [factorPayload],
    "/api/v1/factors/factor-1/workspace": {
      factor: factorPayload,
      reports: [],
      used_by_strategies: [strategyPayload],
      latest_workflows: [],
      latest_agent_runs: [],
    },
    "/api/v1/strategies": [strategyPayload],
    "/api/v1/strategies/strategy-1/workspace": {
      strategy: strategyPayload,
      card: strategyPayload.card,
      factors: [factorPayload],
      backtests: [backtestPayload],
      risk_reviews: [riskPayload],
      approvals: [approvalPayload],
      paper_sessions: [paperSessionPayload],
      artifacts: [],
      workflows: [workflowPayload],
    },
    "/api/v1/backtests": [backtestPayload],
    "/api/v1/risk/reviews": [riskPayload],
    "/api/v1/approvals": [approvalPayload],
    "/api/v1/paper-trading/sessions": [paperSessionPayload],
    "/api/v1/workflows": [workflowPayload],
    "/api/v1/agent-runs": [agentRunPayload],
    "/api/v1/research/reports": [reportPayload],
    "/api/v1/agent-graph": graphPayload,
  };
  if (!(path in map)) {
    throw new Error(`Unhandled ${method} ${path}`);
  }
  return map[path];
}

const factorPayload = {
  id: "factor-1",
  research_idea_id: "idea-1",
  name: "momentum",
  description: "Trailing return factor",
  formula: "close / close_63 - 1",
  input_fields: ["close"],
  lookback_window: 63,
  rebalance_frequency: "monthly",
  status: "analyzed",
  metrics: { ic: 0.04, rank_ic: 0.06, coverage: 0.9 },
  artifacts: ["artifact-factor"],
  updated_at: "2026-01-01T00:00:00Z",
};

const strategyPayload = {
  id: "strategy-1",
  name: "Momentum Strategy",
  description: "Trend following sample",
  universe: "US equities",
  factors: ["factor-1"],
  signal_logic: { weights: { "factor-1": 1 } },
  portfolio_logic: {},
  risk_constraints: {},
  implementation_paths: {},
  status: "APPROVAL_PENDING",
  card: {
    current_status: "APPROVAL_PENDING",
    approval_status: "pending",
    paper_trading_status: "not_started",
    live_trading_status: "locked",
  },
  updated_at: "2026-01-01T00:00:00Z",
};

const backtestPayload = {
  id: "backtest-1",
  strategy_id: "strategy-1",
  engine: "quantconnect",
  dataset_version: "dvc:dataset:rev1",
  benchmark: "SPY",
  status: "completed",
  metrics: { cagr: 0.11, sharpe: 1.2, max_drawdown: -0.12 },
  artifacts: ["artifact-1"],
  mlflow_run_id: "mlflow-run-1",
  created_at: "2026-01-01T00:00:00Z",
};

const riskPayload = {
  id: "risk-review-1",
  strategy_id: "strategy-1",
  backtest_run_id: "backtest-1",
  verdict: "warning",
  risk_summary: { reason: "drawdown review" },
  hard_rule_results: [],
  created_at: "2026-01-01T00:00:00Z",
};

const approvalPayload = {
  id: "approval-live",
  request_type: "unlock_live",
  target_type: "strategy",
  target_id: "strategy-1",
  requested_by_agent: "Execution Agent",
  status: "pending",
  workflow_id: "wf-approval",
  risk_summary: {},
  human_comment: null,
  policy_lock_reason: "Live trading is locked by OPA",
  allowed_actions: ["reject", "request-changes"],
  created_at: "2026-01-01T00:00:00Z",
};

const paperSessionPayload = {
  id: "paper-session-1",
  strategy_id: "strategy-1",
  provider: "quantconnect",
  status: "proposed",
  workflow_id: "wf-paper",
  deployment_ref: "paper_deployment_proposal_prepared",
  created_at: "2026-01-01T00:00:00Z",
};

const workflowPayload = {
  id: "workflow-1",
  workflow_id: "wf-research",
  workflow_type: "ResearchWorkflow",
  owner_type: "research_idea",
  owner_id: "idea-1",
  status: "running",
  metadata: {},
  created_at: "2026-01-01T00:00:00Z",
};

const agentRunPayload = {
  id: "agent-run-1",
  task_type: "research-agent",
  status: "queued",
  workflow_id: "wf-agent",
  input_payload: { agent_id: "research-agent" },
  output_payload: {},
  created_at: "2026-01-01T00:00:00Z",
};

const pipelineItem = {
  id: "strategy-1",
  item_type: "strategy",
  title: "Momentum Strategy",
  stage: "researching",
  status: "APPROVAL_PENDING",
  owner_agent: "Strategy Agent",
  latest_action: "StrategyRegistrationWorkflow",
  missing_requirements: ["missing risk review"],
  linked_strategy_id: "strategy-1",
  latest_backtest_id: "backtest-1",
  latest_metrics: { sharpe: 1.2, max_drawdown: -0.12 },
  risk_verdict: "warning",
  approval_status: "pending",
  next_actions: ["处理待审批"],
  updated_at: "2026-01-01T00:00:00Z",
};

const reportPayload = {
  artifact: {
    id: "artifact-1",
    artifact_type: "research_report",
    owner_type: "strategy",
    owner_id: "strategy-1",
    path: "reports/momentum.md",
    checksum: "sha256:abc",
    metadata: { title: "Momentum Report" },
    created_at: "2026-01-01T00:00:00Z",
  },
  owner_name: "Momentum Strategy",
  owner_status: "APPROVAL_PENDING",
  related_strategy_id: "strategy-1",
  related_factor_id: null,
  related_backtest_id: null,
};

const graphPayload = {
  nodes: [
    {
      id: "research-agent",
      name: "Research Agent",
      role: "Research hypothesis",
      group: "research",
      status: "running",
      current_task: "Reviewing factor candidates",
      last_action: "Agent Canvas manual run queued",
      model_config: { provider: "openai", model: "gpt-4.1-mini", temperature: 0.2, token_budget: 8000 },
      prompt_config: { system_prompt: "Research hypothesis" },
      tool_refs: [{ provider: "openai", display_name: "OpenAI API", status: "connected", permission_level: "research_write", secret_ref: "/qto/openai", open_ui_url: null }],
      permissions: { can_research: true, can_write_research: true, can_execute_live_trade: false },
      risk_limits: { live_trading_locked: true },
      position: { x: 100, y: 120 },
      metadata: {},
      human_action_required: false,
    },
    {
      id: "execution-agent",
      name: "Execution Agent",
      role: "Paper trading proposals and locked live execution",
      group: "trading",
      status: "locked",
      current_task: null,
      last_action: "Seeded default agent",
      model_config: { provider: "openai", model: "gpt-4.1-mini" },
      prompt_config: { system_prompt: "Execution" },
      tool_refs: [{ provider: "quantconnect", display_name: "QuantConnect", status: "disconnected", permission_level: "paper", secret_ref: null, open_ui_url: null }],
      permissions: { can_request_paper_trade: true, can_request_live_trade: false, can_execute_live_trade: false },
      risk_limits: { live_trading_locked: true },
      position: { x: 440, y: 120 },
      metadata: {},
      human_action_required: false,
    },
  ],
  edges: [{ id: "research-agent->execution-agent", source: "research-agent", target: "execution-agent", relation_type: "handoff", workflow_type: "PaperPromotionWorkflow", status: "idle", metadata: { handoff_contract: "research to execution" } }],
  groups: [{ id: "research", label: "Research Group", color: "#2563eb", metadata: {} }, { id: "trading", label: "Trading Group", color: "#dc2626", metadata: {} }],
  updated_at: "2026-01-01T00:00:00Z",
};

function mockApi() {
  const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = new URL(String(input), window.location.origin);
    const method = String(init?.method ?? "GET").toUpperCase();
    return new Response(JSON.stringify(apiPayload(url.pathname, method)), {
      status: 200,
      headers: { "Content-Type": "application/json" },
    });
  });
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

function renderPath(path: string) {
  window.history.pushState({}, "", path);
  return render(<App />);
}

describe("Quant Team OS control UI", () => {
  beforeEach(() => {
    mockApi();
  });

  it("renders the three primary navigation areas and dashboard safety state", async () => {
    renderPath("/");

    expect(await screen.findByRole("heading", { name: "工作台" })).toBeInTheDocument();
    expect(screen.getAllByText("工作台").length).toBeGreaterThan(0);
    expect(screen.getAllByText("策略研究").length).toBeGreaterThan(0);
    expect(screen.getAllByText("智能体管理").length).toBeGreaterThan(0);
    expect(screen.getByText("未连接账户")).toBeInTheDocument();
  });

  it("opens approval drawer and blocks live approval without a human comment", async () => {
    const user = userEvent.setup();
    renderPath("/dashboard");

    await user.click(await screen.findByText("unlock_live · strategy"));
    const drawer = await screen.findByRole("dialog", { name: "待办审批" });
    expect(within(drawer).getByText("Live 交易已被 OPA 策略锁定")).toBeInTheDocument();
    expect(within(drawer).getByRole("button", { name: "批准" })).toBeDisabled();
    expect(within(drawer).getByPlaceholderText("填写审批说明")).toBeInTheDocument();
  });

  it("renders research pipeline, factors and strategies tabs, and strategy factor detail", async () => {
    const user = userEvent.setup();
    renderPath("/research/pipeline");

    expect(await screen.findByRole("heading", { name: "研究管线" })).toBeInTheDocument();
    expect(screen.getByText("Momentum Strategy")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "因子和策略" }));
    expect(await screen.findByText("因子库")).toBeInTheDocument();
    expect(screen.getByText("策略库")).toBeInTheDocument();
    await user.click(screen.getByText("策略库"));
    await user.click(screen.getByText("Momentum Strategy"));
    expect(await screen.findByRole("dialog", { name: "策略详情" })).toHaveTextContent("使用因子");
  });

  it("renders experiments and reports workspaces", async () => {
    const user = userEvent.setup();
    renderPath("/research/experiments");

    expect(await screen.findByRole("heading", { name: "实验与回测" })).toBeInTheDocument();
    expect(screen.getByText("backtest-1")).toBeInTheDocument();
    expect(screen.getByText("dvc:dataset:rev1")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "研究报告" }));
    expect(await screen.findByRole("heading", { name: "研究报告" })).toBeInTheDocument();
    expect(screen.getByText("Momentum Report")).toBeInTheDocument();
  });

  it("renders Agent Canvas and clears raw tool secrets after connect", async () => {
    const user = userEvent.setup();
    const fetchMock = mockApi();
    renderPath("/agent-console");

    expect(await screen.findByRole("heading", { name: "智能体管理" })).toBeInTheDocument();
    expect(screen.getByTestId("agent-canvas")).toBeInTheDocument();
    const canvas = screen.getByTestId("agent-canvas");
    expect(within(canvas).getByText("研究智能体")).toBeInTheDocument();
    expect(screen.getAllByText("执行智能体").length).toBeGreaterThan(0);
    expect(document.body).not.toHaveTextContent("Connect Center");

    await user.click(within(canvas).getByText("研究智能体"));
    expect(await screen.findByText("工具与连接")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "连接" }));
    const dialog = await screen.findByRole("dialog", { name: "连接 OpenAI API" });
    await user.type(within(dialog).getByPlaceholderText("粘贴 API 密钥"), "sk-testsecret1234");
    await user.click(within(dialog).getByRole("button", { name: "连接" }));

    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledWith(
        expect.stringContaining("/api/v1/connections/openai/connect"),
        expect.objectContaining({ method: "POST" }),
      );
    });
    await waitFor(() => expect(screen.queryByDisplayValue("sk-testsecret1234")).not.toBeInTheDocument());
    expect(document.body).not.toHaveTextContent("sk-testsecret1234");
  });
});
