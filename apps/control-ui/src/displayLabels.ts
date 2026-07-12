export function readableIdentifier(value: string) {
  return value.replace(/[_-]+/g, " ");
}

export function ownerTypeLabel(type: string | null | undefined) {
  if (!type) return "对象";
  const labels: Record<string, string> = {
    agent: "智能体",
    backtest: "回测",
    dataset: "数据集",
    factor: "因子",
    paper_session: "Paper 会话",
    research_idea: "研究项目",
    risk_review: "风控评审",
    strategy: "策略",
    workflow: "工作流",
  };
  return labels[type] ?? readableIdentifier(type);
}

export function approvalRequestTypeLabel(type: string | null | undefined) {
  if (!type) return "审批请求";
  const labels: Record<string, string> = {
    strategy_registration: "策略注册",
    paper_promotion: "Paper 升级",
    live_unlock: "Live 解锁",
    risk_exception: "风险例外",
    workflow_checkpoint: "流程确认",
    risk_review: "风控评审",
  };
  return labels[type] ?? readableIdentifier(type);
}

export function approvalTargetTypeLabel(type: string | null | undefined) {
  return ownerTypeLabel(type);
}

export function formatApprovalTitle(row: { request_type: string | null | undefined; target_type: string | null | undefined }) {
  return `${approvalRequestTypeLabel(row.request_type)} · ${approvalTargetTypeLabel(row.target_type)}`;
}

export function approvalPolicyReasonLabel(reason: string | null | undefined) {
  const raw = reason?.trim();
  if (!raw) return null;
  const labels: Record<string, string> = {
    "Live trading is locked by OPA": "Live 交易已被 OPA 策略锁定",
    "Live trading is locked by MVP policy": "Live 交易已按 MVP 策略锁定",
  };
  return labels[raw] ?? readableIdentifier(raw);
}

export function ownerReferenceLabel(type: string | null | undefined, id: string | null | undefined) {
  const label = ownerTypeLabel(type);
  return id ? `${label} ${id}` : label;
}

export function ownerLinkedLabel(type: string | null | undefined, id: string | null | undefined) {
  const label = ownerTypeLabel(type);
  return id ? `${label} ${readableIdentifier(id)}` : label;
}

export function workflowTypeLabel(type: string | null | undefined) {
  if (!type) return null;
  const labels: Record<string, string> = {
    BacktestWorkflow: "回测工作流",
    ConnectionTestWorkflow: "连接测试",
    DataIngestionWorkflow: "数据接入",
    PaperPromotionWorkflow: "Paper 升级",
    ResearchWorkflow: "研究工作流",
    RiskReviewWorkflow: "风控复核",
    StrategyRegistrationWorkflow: "策略注册",
  };
  return labels[type] ?? readableIdentifier(type);
}

export function relationTypeLabel(type: string | null | undefined) {
  if (!type) return "关系";
  const labels: Record<string, string> = {
    approval: "审批",
    data_dependency: "数据依赖",
    group_flow: "分组流程",
    handoff: "交接",
    monitoring: "监控",
  };
  return labels[type] ?? readableIdentifier(type);
}

export function agentGroupLabel(groupId: string | null | undefined, rawLabel?: string | null) {
  const key = (groupId ?? rawLabel ?? "").trim();
  const labels: Record<string, string> = {
    data: "数据组",
    "Data Group": "数据组",
    research: "研究组",
    "Research Group": "研究组",
    validation: "验证组",
    "Validation Group": "验证组",
    trading: "交易组",
    "Trading Group": "交易组",
    system: "系统组",
    "System Group": "系统组",
  };
  return labels[key] ?? rawLabel ?? readableIdentifier(key);
}

export function agentDisplayName(name: string | null | undefined) {
  if (!name) return "智能体";
  const labels: Record<string, string> = {
    "Research Agent": "研究智能体",
    "Data Agent": "数据智能体",
    "Strategy Agent": "策略智能体",
    "Backtest Agent": "回测智能体",
    "Risk Agent": "风控智能体",
    "Approval Agent": "审批智能体",
    "Execution Agent": "执行智能体",
    "Monitoring Agent": "监控智能体",
    "Blank Agent": "空白智能体",
  };
  return labels[name] ?? name;
}

export function agentRoleLabel(name: string | null | undefined, role: string | null | undefined) {
  const labels: Record<string, string> = {
    "Research Agent": "研究假设、笔记与想法扩展",
    "Data Agent": "行情数据、数据集版本与质量",
    "Strategy Agent": "策略草稿、因子选择与生命周期",
    "Backtest Agent": "回测执行、指标与可复现性",
    "Risk Agent": "风险门控、策略判断与 Live 证据",
    "Approval Agent": "人工审批队列与流程确认",
    "Execution Agent": "Paper 交易提案与 Live 锁定流程",
    "Monitoring Agent": "工作流、追踪、审计与健康监控",
  };
  return labels[name ?? ""] ?? role ?? "";
}

export function pipelineActionLabel(action: string | null | undefined) {
  if (!action) return null;
  const raw = action.trim();
  const labels: Record<string, string> = {
    "启动 ResearchWorkflow": "启动研究工作流",
    "启动 BacktestWorkflow": "启动回测",
    "申请 RiskReviewWorkflow": "申请风控复核",
    "申请 paper promotion": "申请 Paper 升级",
    "申请策略注册": "申请策略注册",
    "生成因子草稿": "生成因子草稿",
    "生成策略草稿": "生成策略草稿",
    "处理待审批": "处理待审批",
  };
  return labels[raw] ?? workflowTypeLabel(raw);
}

export function agentTaskTypeLabel(type: string | null | undefined) {
  if (!type) return "智能体任务";
  const labels: Record<string, string> = {
    chat: "对话任务",
    doctor_trace: "诊断任务",
    openai_agent_plan: "研究计划",
    research: "研究任务",
  };
  return labels[type] ?? pipelineActionLabel(type) ?? readableIdentifier(type);
}

export function formatDisplayDate(value: string | null | undefined, prefix = "更新") {
  if (!value) return null;
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return null;
  return `${prefix} ${date.toLocaleDateString()}`;
}
