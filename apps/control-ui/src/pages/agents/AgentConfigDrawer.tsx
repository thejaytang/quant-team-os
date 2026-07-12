import { MoreOutlined } from "@ant-design/icons";
import { Button, Collapse, Drawer, Dropdown, Input, List, Modal, Select, Space, Switch, Tabs, Typography, message } from "antd";
import { useEffect, useMemo, useState } from "react";
import type { AgentEdgeData, AgentGroup, AgentNodeData, AgentRun, AgentToolRef, WorkflowLink } from "../../api/types";
import { CompactEmpty } from "../../components/CompactEmpty";
import { StatusTag } from "../../components/StatusTag";
import { agentDisplayName, agentGroupLabel, agentRoleLabel, agentTaskTypeLabel, readableIdentifier, relationTypeLabel, ownerLinkedLabel, workflowTypeLabel } from "../../displayLabels";

const PERMISSION_LABELS: Record<string, string> = {
  can_research: "研究",
  can_read_market_data: "读取行情",
  can_write_research: "写入研究",
  can_create_strategy: "创建策略",
  can_backtest: "运行回测",
  can_request_risk_review: "申请风控",
  can_request_paper_trade: "申请 Paper",
  can_request_live_trade: "申请 Live",
  can_execute_live_trade: "执行 Live",
};

const TOOL_PERMISSION_LABELS: Record<string, string> = {
  admin_only: "管理员",
  backtest_and_paper: "回测与 Paper",
  experiment_read_write: "实验读写",
  human_action: "人工确认",
  market_data: "行情数据",
  read_only: "只读",
  research_write: "研究写入",
  trace_read_write: "追踪读写",
};

const PERMISSION_GROUPS = [
  {
    title: "研究与数据",
    keys: ["can_research", "can_read_market_data", "can_write_research", "can_create_strategy", "can_backtest"],
  },
  {
    title: "交易与审批",
    keys: ["can_request_risk_review", "can_request_paper_trade", "can_request_live_trade", "can_execute_live_trade"],
  },
];

export function AgentConfigDrawer({
  open,
  onClose,
  agent,
  edge,
  initialTab,
  groups,
  agentRuns,
  workflows,
  onPatchAgent,
  onRunAgent,
  onConnectTool,
  onTestTool,
}: {
  open: boolean;
  onClose: () => void;
  agent: AgentNodeData | null;
  edge: AgentEdgeData | null;
  initialTab?: string;
  groups: AgentGroup[];
  agentRuns: AgentRun[];
  workflows: WorkflowLink[];
  onPatchAgent: (agentId: string, payload: Record<string, unknown>) => Promise<void>;
  onRunAgent: (agentId: string) => Promise<void>;
  onConnectTool: (provider: string, credentials: Record<string, string>) => Promise<void>;
  onTestTool: (provider: string) => Promise<void>;
}) {
  const [draft, setDraft] = useState<Record<string, any>>({});
  const [activeTab, setActiveTab] = useState("overview");
  const [credentialProvider, setCredentialProvider] = useState<AgentToolRef | null>(null);
  const [credentialDraft, setCredentialDraft] = useState<Record<string, string>>({});

  useEffect(() => {
    if (!agent) return;
    setActiveTab(initialTab ?? "overview");
    setDraft({
      name: agent.name,
      role: agent.role,
      group: agent.group,
      current_task: agent.current_task ?? "",
      provider: agent.model_config?.provider ?? "openai",
      model: agent.model_config?.model ?? "",
      system_prompt: agent.prompt_config?.system_prompt ?? "",
      temperature: agent.model_config?.temperature ?? 0.2,
      token_budget: agent.model_config?.token_budget ?? 8000,
      permissions: { ...agent.permissions, can_execute_live_trade: false },
    });
  }, [agent, initialTab]);

  const relatedRuns = useMemo(
    () => agentRuns.filter((run) => run.input_payload?.agent_id === agent?.id || run.task_type === agent?.id).slice(0, 8),
    [agent?.id, agentRuns],
  );
  const relatedWorkflows = useMemo(
    () => workflows.filter((workflow) => agent && matchesWorkflow(agent, workflow.workflow_type)).slice(0, 8),
    [agent, workflows],
  );
  const activityRows = useMemo(
    () => agentActivityRows(relatedWorkflows, relatedRuns),
    [relatedRuns, relatedWorkflows],
  );

  if (edge) {
    return (
      <Drawer
        title="连线配置"
        open={open}
        onClose={onClose}
        width={480}
        placement="right"
        mask={false}
        destroyOnClose
        className="qto-agent-config-drawer"
        data-contract="agent canvas selection opens right side drawer keeps canvas context"
      >
        <div className="qto-detail-inline-meta" data-contract="edge configuration inline metadata no boxed grid; edge configuration hides missing workflow placeholders">
          <span>上游智能体: {readableIdentifier(edge.source)}</span>
          <span>下游智能体: {readableIdentifier(edge.target)}</span>
          <span>关系: {relationTypeLabel(edge.relation_type)}</span>
          {edge.workflow_type ? <span>工作流: {workflowTypeLabel(edge.workflow_type)}</span> : null}
          <span>状态: <StatusTag status={edge.status} /></span>
          {edge.metadata?.failure_reason ? <span>失败原因: {edge.metadata.failure_reason}</span> : null}
        </div>
        <Collapse
          className="qto-detail-collapse"
          size="small"
          items={[{
            key: "handoff",
            label: "交接契约",
            children: <CompactMetaList items={edgeMetadataItems(edge.metadata)} empty="暂无交接配置" contract="edge metadata renders compact summary no raw json" />,
          }]}
        />
      </Drawer>
    );
  }

  if (!agent) {
    return null;
  }

  const selectedAgent = agent;
  const permissions = draft.permissions ?? {};
  const selectedGroup = groups.find((group) => group.id === (draft.group ?? selectedAgent.group));
  const groupLabel = selectedGroup ? agentGroupLabel(selectedGroup.id, selectedGroup.label) : agentGroupLabel(draft.group ?? selectedAgent.group);
  const attentionSummary = agentAttentionSummaryItems(selectedAgent, permissions);
  const drawerStatus = agentDrawerAttentionStatus(selectedAgent.status);
  const researchPermissionCount = countEnabledPermissions(PERMISSION_GROUPS[0].keys, permissions);
  const tradingPermissionCount = countEnabledPermissions(PERMISSION_GROUPS[1].keys, permissions);
  const readinessItems = agentReadinessItems(selectedAgent, permissions);
  const canSaveConfig = isEditableAgentTab(activeTab);
  const canQueueRun = activeTab === "overview";

  async function saveAgentConfig() {
    await onPatchAgent(selectedAgent.id, {
      name: draft.name,
      role: draft.role,
      group: draft.group,
      current_task: draft.current_task || null,
      model_config: { ...selectedAgent.model_config, provider: draft.provider, model: draft.model, temperature: Number(draft.temperature), token_budget: Number(draft.token_budget) },
      prompt_config: { ...selectedAgent.prompt_config, system_prompt: draft.system_prompt },
      permissions: { ...permissions, can_execute_live_trade: false },
    });
  }

  return (
    <>
      <Drawer
        title={(
          <div className="qto-sidepanel-heading">
            <div>
              <Typography.Text strong>{agentDisplayName(selectedAgent.name)}</Typography.Text>
              <Typography.Text type="secondary">{agentRoleLabel(selectedAgent.name, selectedAgent.role)}</Typography.Text>
            </div>
            {drawerStatus ? (
              <span data-contract="agent config title status pill is attention-only">
                <StatusTag status={drawerStatus} />
              </span>
            ) : null}
          </div>
        )}
        open={open}
        onClose={onClose}
        width={520}
        placement="right"
        mask={false}
        destroyOnClose
        className="qto-agent-config-drawer"
        data-contract="agent canvas node configuration uses right drawer instead of centered modal"
      >
        <Space direction="vertical" size={12} className="full-width">
          {attentionSummary.length ? (
            <div className="qto-agent-config-summary" data-contract="live trading locked; agent summary lightweight text line no summary pills; agent attention summary only when needed">
              {attentionSummary.map((item) => <span key={item.label} data-contract={item.contract}>{item.label}</span>)}
            </div>
          ) : null}
          <div className="qto-agent-readiness-strip" data-contract="agent readiness summary visible after node click no execution authority">
            {readinessItems.map((item) => (
              <span key={item}>{item}</span>
            ))}
          </div>

          <Tabs
            activeKey={activeTab}
            onChange={setActiveTab}
            items={[
              {
                key: "overview",
                label: "概览",
                children: (
                  <Space direction="vertical" size={12} className="full-width">
                    <div className="qto-detail-inline-meta" data-contract="agent overview inline metadata no boxed grid; agent overview hides empty task and normal permission count">
                      {agentOverviewMetaItems(groupLabel, draft.current_task, draft.model).map((item) => <span key={item}>{item}</span>)}
                    </div>
                    <Collapse
                      className="qto-agent-advanced-collapse"
                      size="small"
                      items={[
                        {
                          key: "basic",
                          label: "编辑基本信息",
                          children: (
                            <Space direction="vertical" size={12} className="full-width">
                              <div className="qto-form-grid">
                                <label className="qto-form-field">
                                  <span>名称</span>
                                  <Input value={draft.name} onChange={(event) => setDraft({ ...draft, name: event.target.value })} placeholder="例如 研究助理" />
                                </label>
                                <label className="qto-form-field">
                                  <span>分组</span>
                                  <Select
                                    value={draft.group}
                                    onChange={(group) => setDraft({ ...draft, group })}
                                    options={groups.map((group) => ({ value: group.id, label: agentGroupLabel(group.id, group.label) }))}
                                  />
                                </label>
                              </div>
                              <label className="qto-form-field">
                                <span>角色说明</span>
                                <Input value={draft.role} onChange={(event) => setDraft({ ...draft, role: event.target.value })} placeholder="说明这个 agent 负责什么" />
                              </label>
                              <label className="qto-form-field">
                                <span>当前任务</span>
                                <Input value={draft.current_task} onChange={(event) => setDraft({ ...draft, current_task: event.target.value })} placeholder="当前没有任务可留空" />
                              </label>
                            </Space>
                          ),
                        },
                        {
                          key: "model",
                          label: "高级：模型与提示词",
                          children: (
                            <Space direction="vertical" size={12} className="full-width">
                              <div className="qto-form-grid">
                                <label className="qto-form-field">
                                  <span>模型服务</span>
                                  <Input value={draft.provider} onChange={(event) => setDraft({ ...draft, provider: event.target.value })} placeholder="例如 openai" />
                                </label>
                                <label className="qto-form-field">
                                  <span>模型</span>
                                  <Input value={draft.model} onChange={(event) => setDraft({ ...draft, model: event.target.value })} placeholder="例如 gpt-4.1-mini" />
                                </label>
                              </div>
                              <label className="qto-form-field">
                                <span>系统提示词</span>
                                <Input.TextArea rows={3} value={draft.system_prompt} onChange={(event) => setDraft({ ...draft, system_prompt: event.target.value })} placeholder="定义这个智能体的工作边界" />
                              </label>
                            </Space>
                          ),
                        },
                      ]}
                    />
                  </Space>
                ),
              },
              {
                key: "tools",
                label: "工具与连接",
                children: (
                  <Space direction="vertical" size={10} className="full-width">
                    <List
                      className="qto-agent-tool-list"
                      locale={{ emptyText: <CompactEmpty>暂无工具连接</CompactEmpty> }}
                      dataSource={agent.tool_refs}
                      renderItem={(row) => (
                        <List.Item className="qto-agent-tool-row" data-contract="agent tool compact single-line row">
                          <div className="qto-agent-compact-line">
                            <span className="qto-agent-compact-main">
                              <strong>{row.display_name}</strong>
                              <span className="qto-agent-tool-meta" data-contract="permission level secret_ref">
                                {toolMetaLine(row)}
                              </span>
                            </span>
                            <span className="qto-agent-compact-actions">
                              <StatusTag status={row.status} />
                              <Dropdown
                                trigger={["click"]}
                                menu={{
                                  items: [
                                    { key: "connect", label: <span aria-label="连接">连接</span> },
                                    { key: "test", label: <span aria-label="测试">测试</span> },
                                    ...(row.open_ui_url ? [{
                                      key: "open-ui",
                                      label: <a aria-label="打开界面" href={row.open_ui_url} target="_blank" rel="noreferrer" data-contract="agent open ui action only when link exists; Open UI">打开界面</a>,
                                    }] : []),
                                    { key: "audit", label: <span aria-label="查看审计" data-contract="agent audit action opens logs tab; View audit">查看审计</span> },
                                  ],
                                  onClick: ({ key }) => {
                                    if (key === "connect") {
                                      setCredentialProvider(row);
                                      setCredentialDraft({});
                                    }
                                    if (key === "test") void onTestTool(row.provider);
                                    if (key === "audit") setActiveTab("logs");
                                  },
                                }}
                              >
                                <Button size="small" icon={<MoreOutlined />} aria-label="工具操作" data-contract="agent tool compact action menu" />
                              </Dropdown>
                            </span>
                          </div>
                        </List.Item>
                      )}
                    />
                  </Space>
                ),
              },
              {
                key: "policy",
                label: "权限与风控",
                children: (
                  <Space direction="vertical" size={12} className="full-width">
                    <div className="qto-detail-inline-meta" data-contract="permission summary inline metadata no boxed grid">
                      {permissionSummaryMetaItems(agent, researchPermissionCount, tradingPermissionCount).map((item) => (
                        <span key={item.label} data-contract={item.contract}>{item.label}</span>
                      ))}
                    </div>
                    <Collapse
                      className="qto-agent-advanced-collapse"
                      size="small"
                      items={[{
                        key: "permission-switches",
                        label: "编辑权限开关",
                        children: (
                          <div className="qto-permission-groups">
                            {PERMISSION_GROUPS.map((group) => (
                              <section className="qto-permission-group" key={group.title}>
                                <Typography.Text strong>{group.title}</Typography.Text>
                                <div className="qto-permission-grid">
                                  {group.keys.map((key) => (
                                    <label key={key} className="qto-permission-row">
                                      <span title={key}>{PERMISSION_LABELS[key] ?? key}</span>
                                      <Switch
                                        size="small"
                                        checked={Boolean(permissions[key])}
                                        disabled={key === "can_execute_live_trade"}
                                        onChange={(checked) => setDraft({ ...draft, permissions: { ...permissions, [key]: key === "can_execute_live_trade" ? false : checked } })}
                                      />
                                    </label>
                                  ))}
                                </div>
                              </section>
                            ))}
                          </div>
                        ),
                      }]}
                    />
                  </Space>
                ),
              },
              {
                key: "logs",
                label: "日志",
                children: (
                  <List
                    className="qto-agent-run-list"
                    data-contract="audit_logs tool_calls policy_decisions; agent logs merged compact activity list no split workflow and run lists; agent workflow events render only real workflow data no fake links"
                    dataSource={activityRows}
                    locale={{ emptyText: <CompactEmpty>暂无运行记录</CompactEmpty> }}
                    renderItem={(row) => {
                      const status = activityAttentionStatus(row.status);
                      return (
                        <List.Item className="qto-agent-run-row" data-contract="agent run compact single-line row; agent run row hides missing workflow placeholders">
                          <div className="qto-agent-compact-line">
                            <span className="qto-agent-compact-main">
                              <strong>{row.label}</strong>
                              {row.detail ? <small>{row.detail}</small> : null}
                            </span>
                            {status ? (
                              <span data-contract="agent config activity status pill is attention-only">
                                <StatusTag status={status} />
                              </span>
                            ) : null}
                          </div>
                        </List.Item>
                      );
                    }}
                  />
                ),
              },
            ]}
          />

          <div className="qto-agent-config-actions" data-contract="agent config scoped actions save only on editable tabs; agent run action only on overview tab">
            {canSaveConfig ? (
              <Button type="primary" onClick={saveAgentConfig}>保存配置</Button>
            ) : null}
            {canQueueRun ? (
              <Button aria-label="运行一次" onClick={() => onRunAgent(agent.id)}>运行一次</Button>
            ) : null}
          </div>
        </Space>
      </Drawer>

      <Modal
        title={credentialProvider ? `连接 ${credentialProvider.display_name}` : "连接工具"}
        open={Boolean(credentialProvider)}
        onCancel={() => {
          setCredentialProvider(null);
          setCredentialDraft({});
        }}
        onOk={async () => {
          if (!credentialProvider) return;
          if (!Object.values(credentialDraft).some((value) => value.trim())) {
            message.error("请填写凭证");
            return;
          }
          await onConnectTool(credentialProvider.provider, credentialDraft);
          setCredentialProvider(null);
          setCredentialDraft({});
        }}
        okText="连接"
        cancelText="取消"
      >
        <Space direction="vertical" size={12} className="full-width">
          <Typography.Text type="secondary" data-contract="Secret fields are sent once to FastAPI and stored through Infisical; secret policy: raw values are cleared after submit. secret_ref">
            提交后只保留密钥引用，原始密钥会立即从表单清空。
          </Typography.Text>
          <Input.Password
            placeholder="粘贴 API 密钥"
            value={credentialDraft.api_key ?? ""}
            onChange={(event) => setCredentialDraft({ ...credentialDraft, api_key: event.target.value })}
          />
        </Space>
      </Modal>
    </>
  );
}

function CompactMetaList({ items, empty, contract }: { items: string[]; empty: string; contract: string }) {
  return (
    <div className="qto-detail-meta-list" data-contract={contract}>
      {items.length ? items.map((item) => <span className="qto-detail-meta-item" key={item}>{item}</span>) : <CompactEmpty>{empty}</CompactEmpty>}
    </div>
  );
}

function edgeMetadataItems(metadata: Record<string, unknown>) {
  return Object.entries(metadata ?? {})
    .filter(([key, value]) => key !== "group_edge" && hasMetadataValue(value))
    .map(([key, value]) => `${readableIdentifier(key)} ${formatMetadataValue(value)}`);
}

function hasMetadataValue(value: unknown) {
  if (value === null || value === undefined || value === "") return false;
  if (Array.isArray(value)) return value.length > 0;
  if (typeof value === "object") return Object.keys(value).length > 0;
  return true;
}

function formatMetadataValue(value: unknown) {
  if (typeof value === "boolean") return value ? "已启用" : "未启用";
  if (typeof value === "number") return Number.isInteger(value) ? String(value) : value.toFixed(2);
  if (typeof value === "string") return readableIdentifier(value);
  if (Array.isArray(value)) return `${value.length} 项`;
  if (value && typeof value === "object") return `${Object.keys(value).length} 项`;
  return String(value);
}

function agentOverviewMetaItems(groupLabel: string, currentTask: string | undefined, model: string | undefined) {
  return [
    `分组 ${groupLabel}`,
    currentTask?.trim() ? `当前任务 ${currentTask.trim()}` : null,
    model ? `模型 ${model}` : null,
  ].filter(Boolean) as string[];
}

function agentReadinessItems(agent: AgentNodeData, permissions: Record<string, unknown>) {
  return [
    `状态 ${agentLifecycleLabel(agent.status)}`,
    agent.current_task?.trim() ? "任务进行中" : "可接收任务",
    agentToolReadinessLabel(agent.tool_refs),
    agentPermissionReadinessLabel(permissions),
    livePermissionSummary(agent),
  ];
}

function agentLifecycleLabel(status: string) {
  const labels: Record<string, string> = {
    idle: "空闲",
    running: "运行中",
    blocked: "阻塞",
    failed: "失败",
    waiting_approval: "待审批",
    locked: "已锁定",
    disconnected: "未连接",
  };
  return labels[status] ?? readableIdentifier(status);
}

function agentToolReadinessLabel(tools: AgentToolRef[]) {
  const hasIssue = tools.some((tool) => ["disconnected", "failed", "error"].includes(tool.status));
  return hasIssue ? "工具需处理" : "工具可用";
}

function agentPermissionReadinessLabel(permissions: Record<string, unknown>) {
  return Object.values(permissions).some(Boolean) ? "权限已配置" : "无启用权限";
}

function permissionSummaryMetaItems(agent: AgentNodeData, researchPermissionCount: number, tradingPermissionCount: number) {
  return [
    { label: livePermissionSummary(agent), contract: "live trading locked can_execute_live_trade=false" },
    { label: `研究与数据 ${researchPermissionCount}/${PERMISSION_GROUPS[0].keys.length} 已启用` },
    { label: `交易与审批 ${tradingPermissionCount}/${PERMISSION_GROUPS[1].keys.length} 已启用` },
  ];
}

function livePermissionSummary(agent: AgentNodeData) {
  return agent.risk_limits?.live_trading_locked ? "Live 已锁定，执行关闭" : "Live 执行关闭，仅 Paper";
}

function toolMetaLine(row: AgentToolRef) {
  return [toolPermissionLabel(row.permission_level), secretRefLabel(row.secret_ref)].filter(Boolean).join(" · ");
}

function toolPermissionLabel(permissionLevel: string) {
  return TOOL_PERMISSION_LABELS[permissionLevel] ?? permissionLevel.replace(/_/g, " ");
}

function secretRefLabel(secretRef: string | null | undefined) {
  const value = secretRef?.trim();
  return value ? `密钥 ${shortSecretRef(value)}` : null;
}

function shortSecretRef(value: string) {
  const segment = value.split(/[/\\:]/).filter(Boolean).pop() ?? value;
  return segment.length > 18 ? `${segment.slice(0, 18)}...` : segment;
}

function matchesWorkflow(agent: AgentNodeData, workflowType: string) {
  const name = agent.name.toLowerCase();
  const workflow = workflowType.toLowerCase();
  return (
    (name.includes("research") && workflow.includes("research"))
    || (name.includes("data") && workflow.includes("data"))
    || (name.includes("strategy") && workflow.includes("strategy"))
    || (name.includes("backtest") && workflow.includes("backtest"))
    || (name.includes("risk") && workflow.includes("risk"))
    || (name.includes("approval") && workflow.includes("approval"))
    || (name.includes("execution") && (workflow.includes("paper") || workflow.includes("execution")))
  );
}

type AgentActivityRow = {
  id: string;
  label: string;
  detail: string | null;
  status: string;
};

function agentActivityRows(workflows: WorkflowLink[], runs: AgentRun[]): AgentActivityRow[] {
  return [
    ...workflows.map((workflow) => ({
      id: `工作流:${workflow.id ?? workflow.workflow_id}`,
      label: workflowTypeLabel(workflow.workflow_type) ?? "工作流",
      detail: ownerLinkedLabel(workflow.owner_type, workflow.owner_id),
      status: workflow.status,
    })),
    ...runs.map((run) => ({
      id: `运行:${run.id}`,
      label: agentTaskTypeLabel(run.task_type),
      detail: run.workflow_id ? `工作流 ${readableIdentifier(run.workflow_id)}` : null,
      status: run.status,
    })),
  ].slice(0, 10);
}

function activityAttentionStatus(status: string) {
  const value = status.toLowerCase();
  return ["queued", "started", "running", "pending", "approval", "review", "failed", "fail", "error", "blocked", "rejected", "denied", "locked", "disconnected", "cancel", "warning", "degraded"].some((marker) => value.includes(marker))
    ? status
    : null;
}

function agentDrawerAttentionStatus(status: string) {
  return activityAttentionStatus(status);
}

function agentAttentionSummaryItems(agent: AgentNodeData, permissions: Record<string, unknown>) {
  const disconnected = agent.tool_refs.filter((tool) => ["disconnected", "failed", "error"].includes(tool.status)).length;
  return [
    agent.human_action_required ? { label: "需要人工处理", contract: "human action only when required no normal-state noise" } : null,
    agent.risk_limits?.live_trading_locked ? { label: "Live 已锁定", contract: "live trading locked" } : null,
    disconnected ? { label: `工具异常 ${disconnected}/${agent.tool_refs.length}`, contract: "agent attention summary tool issues only no normal tool count" } : null,
    Object.values(permissions).some(Boolean) ? null : { label: "无启用权限", contract: "agent attention summary permission issue only no normal permission count" },
  ].filter(Boolean) as Array<{ label: string; contract: string }>;
}

function countEnabledPermissions(keys: string[], permissions: Record<string, unknown>) {
  return keys.filter((key) => Boolean(permissions[key])).length;
}

function isEditableAgentTab(tab: string) {
  return tab === "overview" || tab === "policy";
}
