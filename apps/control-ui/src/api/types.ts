export type StatusValue = string | null | undefined;

export type ConnectionCapabilities = {
  connectable?: boolean;
  read_holdings?: boolean;
  paper_trade?: boolean;
  live_trade?: boolean | "locked";
};

export type Connection = {
  id?: string;
  provider: string;
  display_name: string;
  status: string;
  permissions: string[];
  metadata?: Record<string, any> & { capabilities?: ConnectionCapabilities };
  last_checked_at?: string | null;
  last_error?: string | null;
  infisical_secret_path?: string | null;
};

export type ApprovalRequest = {
  id: string;
  request_type: string;
  target_type: string;
  target_id: string;
  requested_by_agent: string;
  status: string;
  risk_summary?: Record<string, any>;
  workflow_id?: string | null;
  human_comment?: string | null;
  policy_lock_reason?: string | null;
  allowed_actions?: string[];
  created_at?: string;
  updated_at?: string;
};

export type AgentRun = {
  id: string;
  task_type: string;
  status: string;
  workflow_id?: string | null;
  langfuse_trace_id?: string | null;
  input_payload?: Record<string, any>;
  output_payload?: Record<string, any>;
  error?: string | null;
  created_at?: string;
};

export type WorkflowLink = {
  id: string;
  workflow_id: string;
  workflow_type: string;
  owner_type: string;
  owner_id: string;
  status: string;
  metadata?: Record<string, any>;
  created_at?: string;
};

export type ResearchIdea = {
  id: string;
  title: string;
  thesis: string;
  universe: string;
  asset_class: string;
  proposed_by: string;
  status: string;
  tags: string[];
  created_at?: string;
  updated_at?: string;
};

export type FactorSpec = {
  id: string;
  research_idea_id: string;
  name: string;
  description: string;
  formula: string;
  input_fields: string[];
  lookback_window?: number | null;
  rebalance_frequency: string;
  implementation_path?: string | null;
  status: string;
  metrics: Record<string, any>;
  artifacts: string[];
  created_at?: string;
  updated_at?: string;
};

export type StrategyCard = {
  current_status: string;
  approval_status: string;
  paper_trading_status: string;
  live_trading_status: string;
  latest_backtest_metrics?: Record<string, any>;
  factor_summary?: Record<string, any>;
  workflow_id?: string | null;
};

export type StrategySpec = {
  id: string;
  name: string;
  description: string;
  universe: string;
  factors: string[];
  signal_logic?: Record<string, any>;
  portfolio_logic?: Record<string, any>;
  rebalance_frequency?: string;
  risk_constraints?: Record<string, any>;
  implementation_paths?: Record<string, any>;
  status: string;
  card?: StrategyCard | null;
  created_at?: string;
  updated_at?: string;
};

export type BacktestRun = {
  id: string;
  strategy_id: string;
  engine: string;
  dataset_spec_id?: string | null;
  dataset_version?: string | null;
  start_date?: string;
  end_date?: string;
  benchmark: string;
  cost_model?: Record<string, any>;
  slippage_model?: Record<string, any>;
  status: string;
  metrics: Record<string, any>;
  artifacts: string[];
  mlflow_run_id?: string | null;
  created_at?: string;
};

export type RiskReview = {
  id: string;
  strategy_id: string;
  backtest_run_id: string;
  verdict: string;
  hard_rule_results?: Record<string, any>[];
  risk_summary?: Record<string, any>;
  created_by_agent?: string;
  created_at?: string;
};

export type PaperTradingSession = {
  id: string;
  strategy_id: string;
  provider: string;
  status: string;
  workflow_id?: string | null;
  deployment_ref?: string | null;
  metadata?: Record<string, any>;
  created_at?: string;
};

export type Artifact = {
  id: string;
  artifact_type: string;
  owner_type: string;
  owner_id: string;
  minio_bucket?: string;
  object_key?: string;
  path?: string;
  content_type?: string;
  checksum?: string;
  mlflow_run_id?: string | null;
  dvc_rev?: string | null;
  metadata?: Record<string, any>;
  created_at?: string;
};

export type ResearchReportItem = {
  artifact: Artifact;
  owner_name: string;
  owner_status: string | null;
  related_strategy_id: string | null;
  related_factor_id: string | null;
  related_backtest_id: string | null;
};

export type DashboardSummary = {
  portfolio: {
    mode: "unavailable" | "paper" | "simulated" | "live";
    total_equity: number | null;
    cash: number | null;
    pnl_today: number | null;
    gross_exposure: number | null;
    net_exposure: number | null;
    source: string;
  };
  status: {
    api: "healthy" | "degraded" | "down";
    live_trading_locked: boolean;
    environment: string;
    last_refreshed_at: string;
  };
  counts: {
    pending_approvals: number;
    risk_alerts: number;
    running_workflows: number;
    active_agent_runs: number;
    disconnected_tools: number;
    paper_sessions: number;
  };
  approvals: ApprovalRequest[];
  risk_alerts: RiskReview[];
  running_tasks: Array<(AgentRun | WorkflowLink) & { type?: string }>;
  connections: Connection[];
};

export type ResearchPipelineItem = {
  id: string;
  item_type: "research_idea" | "strategy";
  title: string;
  stage: string;
  status: string;
  owner_agent: string | null;
  latest_action: string | null;
  missing_requirements: string[];
  linked_strategy_id: string | null;
  latest_backtest_id: string | null;
  latest_metrics: Record<string, any>;
  risk_verdict: string | null;
  approval_status: string | null;
  next_actions: string[];
  updated_at: string;
};

export type ResearchPipeline = {
  stages: Array<{ key: string; label: string; items: ResearchPipelineItem[] }>;
};

export type AgentToolRef = {
  provider: string;
  display_name: string;
  status: string;
  permission_level: string;
  secret_ref: string | null;
  open_ui_url: string | null;
};

export type AgentNodeData = {
  id: string;
  name: string;
  role: string;
  group: string;
  status: string;
  current_task: string | null;
  last_action: string | null;
  model_config: Record<string, any>;
  prompt_config: Record<string, any>;
  tool_refs: AgentToolRef[];
  permissions: Record<string, boolean>;
  risk_limits: Record<string, any>;
  position: { x: number; y: number };
  metadata: Record<string, any>;
  human_action_required?: boolean;
};

export type AgentEdgeData = {
  id: string;
  source: string;
  target: string;
  relation_type: string;
  workflow_type: string | null;
  status: string;
  metadata: Record<string, any>;
};

export type AgentGroup = {
  id: string;
  label: string;
  color: string;
  metadata: Record<string, any>;
};

export type AgentGraph = {
  nodes: AgentNodeData[];
  edges: AgentEdgeData[];
  groups: AgentGroup[];
  updated_at: string;
};

export type FactorWorkspace = {
  factor: FactorSpec;
  reports: Artifact[];
  used_by_strategies: StrategySpec[];
  latest_workflows: WorkflowLink[];
  latest_agent_runs: AgentRun[];
};

export type StrategyWorkspace = {
  strategy: StrategySpec;
  card: StrategyCard | null;
  factors: FactorSpec[];
  backtests: BacktestRun[];
  risk_reviews: RiskReview[];
  approvals: ApprovalRequest[];
  paper_sessions: PaperTradingSession[];
  artifacts: Artifact[];
  workflows: WorkflowLink[];
};

export type AgentDetail = AgentNodeData & {
  latest_agent_runs?: AgentRun[];
  workflow_events?: WorkflowLink[];
  audit_logs?: Array<Record<string, any>>;
  tool_calls?: Array<Record<string, any>>;
  policy_decisions?: Array<Record<string, any>>;
};
