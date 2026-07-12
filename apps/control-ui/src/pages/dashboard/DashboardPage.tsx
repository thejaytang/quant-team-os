import { PlusOutlined } from "@ant-design/icons";
import { Button, Input, List, Modal, Space, Typography, message } from "antd";
import type { KeyboardEvent, ReactNode } from "react";
import { useRef, useState } from "react";
import { CompactEmpty } from "../../components/CompactEmpty";
import { StatusTag } from "../../components/StatusTag";
import type { AgentRun, ApprovalRequest, DashboardSummary, PaperTradingSession, ResearchPipeline, ResearchPipelineItem, RiskReview, WorkflowLink } from "../../api/types";
import { agentTaskTypeLabel, approvalPolicyReasonLabel, formatApprovalTitle, ownerLinkedLabel, pipelineActionLabel, readableIdentifier, workflowTypeLabel } from "../../displayLabels";

type RunningTask = AgentRun | WorkflowLink;
type ResearchDecisionItem = ResearchPipelineItem & { stage_label: string };
type PortfolioConnection = DashboardSummary["connections"][number];
type PortfolioConnectionProvider = "quantconnect" | "ibkr";
type PortfolioCredentialField = {
  name: string;
  label: string;
  placeholder: string;
  secret?: boolean;
  required?: boolean;
};
type PortfolioConnectionSource = {
  key: string;
  provider?: PortfolioConnectionProvider;
  title: string;
  subtitle: string;
  status: string;
  note: string;
  capabilityLabel: string;
  actionLabel?: string;
  fields: PortfolioCredentialField[];
};
type PortfolioSourceSummary = {
  key: string;
  title: string;
  capabilityLabel: string;
  detail: string;
  status: string;
  readHoldingsLabel: string;
  lastCheckedLabel: string;
  errorLabel: string | null;
  nextActionLabel: string;
};
type WorkbenchPriorityItem = {
  kind: "risk" | "approval" | "research" | "portfolio";
  key: string;
  title: string;
  detail: string;
  ownerLabel: string;
  actionLabel: string;
  status: string;
  onClick?: () => void;
};

const PORTFOLIO_CONNECTION_SOURCES: PortfolioConnectionSource[] = [
  {
    key: "quantconnect",
    provider: "quantconnect",
    title: "QuantConnect Paper",
    subtitle: "Paper workflow、回测和策略候选运行",
    status: "paper",
    note: "适合先接入 Paper workflow 和回测结果。密钥只提交到后端保存引用，不在前端明文展示。",
    capabilityLabel: "可配置",
    actionLabel: "保存并测试 QuantConnect Paper",
    fields: [
      { name: "user_id", label: "QuantConnect 用户 ID", placeholder: "输入 QuantConnect 用户 ID", required: true },
      { name: "api_token", label: "API token", placeholder: "粘贴 QuantConnect API token", secret: true, required: true },
    ],
  },
  {
    key: "ibkr",
    provider: "ibkr",
    title: "IBKR",
    subtitle: "不读取真实持仓，不支持 live trade",
    status: "locked",
    note: "IBKR 仅作为 locked 来源显示。当前不可连接、不读取真实持仓、不支持 live trade，交易执行必须继续经过后端策略和人工审批。",
    capabilityLabel: "不可连接",
    fields: [],
  },
  {
    key: "simulated",
    title: "本地模拟/不可用",
    subtitle: "本地模拟组合和未连接状态",
    status: "simulated",
    note: "没有外部券商或 Paper 账户时，工作台继续显示本地模拟/不可用状态，不伪造真实资产。",
    capabilityLabel: "本地/不可用",
    fields: [],
  },
];

export function DashboardPage({
  summary,
  approvals,
  riskReviews,
  agentRuns,
  workflows,
  paperSessions,
  pipeline,
  onApprovalClick,
  onResearchItemClick,
  onConnectPortfolio,
}: {
  summary: DashboardSummary | null;
  approvals: ApprovalRequest[];
  riskReviews: RiskReview[];
  agentRuns: AgentRun[];
  workflows: WorkflowLink[];
  paperSessions: PaperTradingSession[];
  pipeline: ResearchPipeline | null;
  onApprovalClick: (approval: ApprovalRequest) => void;
  onResearchItemClick: (item: ResearchPipelineItem) => void;
  onConnectPortfolio: (provider: PortfolioConnectionProvider, credentials: Record<string, string>) => Promise<void> | void;
}) {
  const [portfolioConnectOpen, setPortfolioConnectOpen] = useState(false);
  const [portfolioConnectSubmitting, setPortfolioConnectSubmitting] = useState<PortfolioConnectionProvider | null>(null);
  const [portfolioConnectionDrafts, setPortfolioConnectionDrafts] = useState<Record<PortfolioConnectionProvider, Record<string, string>>>(() => freshPortfolioDrafts());
  const [activePortfolioSourceKey, setActivePortfolioSourceKey] = useState(PORTFOLIO_CONNECTION_SOURCES[0].key);
  const portfolioSourceRefs = useRef<Record<string, HTMLButtonElement | null>>({});
  const portfolio = summary?.portfolio;
  const counts = summary?.counts;
  const liveTradingLocked = summary?.status.live_trading_locked ?? true;
  const accountNote = accountConnectionNote(portfolio, liveTradingLocked);
  const pendingApprovals = approvals.filter((item) => item.status === "pending");
  const riskAlerts = dashboardRiskAlerts(riskReviews);
  const riskAlertCount = counts?.risk_alerts ?? riskAlerts.length;
  const portfolioMetrics = portfolioMetricItems(portfolio);
  const pendingResearchItems = researchDecisionItems(pipeline);
  const activePortfolioSource = PORTFOLIO_CONNECTION_SOURCES.find((source) => source.key === activePortfolioSourceKey) ?? PORTFOLIO_CONNECTION_SOURCES[0];
  const portfolioSourceRows = portfolioConnectionRows(summary?.connections);
  const runningTasks = [
    ...agentRuns.filter((item) => ["queued", "running", "started"].includes(item.status)),
    ...workflows.filter((item) => ["queued", "running", "started"].includes(item.status)),
  ];
  const priorityItems = workbenchPriorityItems({
    riskAlerts,
    pendingApprovals,
    pendingResearchItems,
    portfolioSourceRows,
    onApprovalClick,
    onResearchItemClick,
    onPortfolioSourceClick: () => setPortfolioConnectOpen(true),
  });

  function updatePortfolioCredential(provider: PortfolioConnectionProvider, field: string, value: string) {
    setPortfolioConnectionDrafts((drafts) => ({
      ...drafts,
      [provider]: { ...drafts[provider], [field]: value },
    }));
  }

  function clearPortfolioSecretDrafts() {
    setPortfolioConnectionDrafts((drafts) => {
      const next = { ...drafts };
      for (const source of PORTFOLIO_CONNECTION_SOURCES) {
        if (!source.provider) continue;
        const current = { ...(next[source.provider] ?? {}) };
        for (const field of source.fields) {
          if (field.secret) current[field.name] = "";
        }
        next[source.provider] = current;
      }
      return next;
    });
  }

  function closePortfolioConnectModal() {
    clearPortfolioSecretDrafts();
    setPortfolioConnectOpen(false);
  }

  async function submitPortfolioConnection(source: PortfolioConnectionSource) {
    if (!source.provider) return;
    if (source.provider === "ibkr") return;
    if (portfolioConnectSubmitting) return;
    const draft = portfolioConnectionDrafts[source.provider] ?? {};
    const credentials = Object.fromEntries(source.fields.map((field) => [field.name, (draft[field.name] ?? "").trim()]));
    const missingRequired = source.fields.some((field) => field.required && !credentials[field.name]);
    if (missingRequired) return;
    setPortfolioConnectSubmitting(source.provider);
    try {
      await onConnectPortfolio(source.provider, credentials);
      setPortfolioConnectionDrafts((drafts) => ({ ...drafts, [source.provider as PortfolioConnectionProvider]: freshPortfolioDrafts()[source.provider as PortfolioConnectionProvider] }));
      message.success(source.provider === "quantconnect" ? "QuantConnect Paper 凭据已提交" : `${source.title} 来源已提交`);
    } catch (error) {
      message.error(error instanceof Error ? error.message : "持仓来源提交失败");
    } finally {
      clearPortfolioSecretDrafts();
      setPortfolioConnectSubmitting(null);
    }
  }

  function focusPortfolioSource(key: string) {
    setActivePortfolioSourceKey(key);
    window.requestAnimationFrame(() => {
      portfolioSourceRefs.current[key]?.focus();
    });
  }

  function movePortfolioSource(currentKey: string, offset: number) {
    const currentIndex = PORTFOLIO_CONNECTION_SOURCES.findIndex((source) => source.key === currentKey);
    const nextIndex = (currentIndex + offset + PORTFOLIO_CONNECTION_SOURCES.length) % PORTFOLIO_CONNECTION_SOURCES.length;
    focusPortfolioSource(PORTFOLIO_CONNECTION_SOURCES[nextIndex].key);
  }

  function handlePortfolioSourceKeyDown(event: KeyboardEvent<HTMLButtonElement>, source: PortfolioConnectionSource) {
    if (event.key === "ArrowDown") {
      event.preventDefault();
      movePortfolioSource(source.key, 1);
    }
    if (event.key === "ArrowUp") {
      event.preventDefault();
      movePortfolioSource(source.key, -1);
    }
    if (event.key === "Home") {
      event.preventDefault();
      focusPortfolioSource(PORTFOLIO_CONNECTION_SOURCES[0].key);
    }
    if (event.key === "End") {
      event.preventDefault();
      focusPortfolioSource(PORTFOLIO_CONNECTION_SOURCES[PORTFOLIO_CONNECTION_SOURCES.length - 1].key);
    }
  }

  return (
    <Space direction="vertical" size={18} className="full-width">
      <div className="qto-page-heading" data-contract="dashboard heading no persistent environment badge">
        <div>
          <Typography.Title level={2}>工作台</Typography.Title>
        </div>
      </div>

      <section className="qto-workbench-status-strip" data-contract="dashboard compact key value status strip no summary cards; dashboard status strip hides unavailable portfolio metric placeholders">
        {portfolioMetrics.map((item) => (
          <WorkbenchMetric key={item.label} label={item.label} value={formatPortfolioMetric(item.value)} />
        ))}
        <WorkbenchMetric label="当前风险状态" value={<StatusTag status={riskAlertCount > 0 ? "blocked" : "healthy"} />} />
        <WorkbenchMetric label="待审批" value={counts?.pending_approvals ?? pendingApprovals.length} />
        <WorkbenchMetric label="待处理研究" value={pendingResearchItems.length} />
        <WorkbenchMetric label="运行中任务" value={counts?.running_workflows ?? runningTasks.length} />
      </section>

      <section className="qto-workbench-priority" data-contract="dashboard today priority queue ranks risk approval research connection actions">
        <div className="qto-section-heading">
          <Typography.Text strong>今日优先处理</Typography.Text>
          <Typography.Text type="secondary">按风险、审批、研究、连接排序</Typography.Text>
        </div>
        <List
          className="qto-priority-list"
          dataSource={priorityItems}
          locale={{ emptyText: <CompactEmpty>今天没有必须处理的优先项。风险、审批和研究阻塞项已清空。</CompactEmpty> }}
          renderItem={(item, index) => (
            <List.Item>
              <WorkbenchPriorityRow item={item} rank={index + 1} />
            </List.Item>
          )}
        />
      </section>

      <div className="qto-workbench-grid" data-contract="dashboard today decision center prioritizes risk approval research">
        <section className="qto-workbench-section qto-dashboard-decision-section">
          <div className="qto-section-heading">
            <Typography.Text strong>风险与告警</Typography.Text>
          </div>
          <List
            className="qto-compact-list"
            dataSource={riskAlerts.slice(0, 6)}
            data-contract="dashboard risk alert list filters normal pass reviews"
            locale={{ emptyText: <CompactEmpty>暂无风险告警</CompactEmpty> }}
            renderItem={(item) => (
              <List.Item>
                <WorkbenchListLine
                  title="策略风险"
                  detail={riskReviewDetail(item)}
                  status={item.verdict}
                />
              </List.Item>
            )}
          />
        </section>

        <section className="qto-workbench-section qto-dashboard-decision-section">
          <div className="qto-section-heading">
            <Typography.Text strong>待办审批</Typography.Text>
          </div>
          <List
            className="qto-compact-list"
            dataSource={pendingApprovals.slice(0, 8)}
            locale={{ emptyText: <CompactEmpty>暂无待办审批</CompactEmpty> }}
            renderItem={(item) => (
              <List.Item>
                <button
                  type="button"
                  className="qto-workbench-action-row"
                  data-contract="dashboard approval row uses native button and opens drawer no repeated button"
                  onClick={() => onApprovalClick(item)}
                >
                  <WorkbenchListLine
                    title={formatApprovalTitle(item)}
                    detail={formatApprovalDescription(item)}
                    status={item.status}
                  />
                </button>
              </List.Item>
            )}
          />
        </section>

        <section className="qto-workbench-section qto-dashboard-decision-section">
          <div className="qto-section-heading">
            <Typography.Text strong>待处理研究</Typography.Text>
          </div>
          <List
            className="qto-compact-list"
            dataSource={pendingResearchItems.slice(0, 6)}
            data-contract="dashboard research decision list shows next action not raw ids"
            locale={{ emptyText: <CompactEmpty>暂无待处理研究</CompactEmpty> }}
            renderItem={(item) => (
              <List.Item>
                <button
                  type="button"
                  className="qto-workbench-action-row"
                  data-contract="dashboard research decision row uses native button and opens existing pipeline detail drawer"
                  onClick={() => onResearchItemClick(item)}
                >
                  <WorkbenchListLine
                    title={item.title}
                    detail={researchDecisionDetail(item)}
                    status={item.approval_status ?? item.risk_verdict ?? item.status}
                  />
                </button>
              </List.Item>
            )}
          />
        </section>

        <section className="qto-workbench-section">
          <div className="qto-section-heading">
            <Typography.Text strong>持仓与账户</Typography.Text>
            <Button
              className="qto-section-action"
              icon={<PlusOutlined />}
              aria-label="管理持仓来源"
              title="管理持仓来源"
              size="small"
              onClick={() => setPortfolioConnectOpen(true)}
              data-contract="portfolio connection button replaces unavailable account status pill"
            />
          </div>
          <div className="qto-account-note" data-mode={accountNote.mode} data-contract="dashboard compact account connection note; portfolio mode driven account note">
            <strong>{accountNote.title}</strong>
            <span>{accountNote.detail}</span>
          </div>
          {liveTradingLocked ? (
            <div className="qto-live-lock-note" data-contract="dashboard portfolio main card keeps live trading locked visible">
              Live trading locked：未启用真实券商持仓读取或 live trade。
            </div>
          ) : null}
          <div className="qto-portfolio-source-summary" data-contract="dashboard portfolio main card shows all holdings sources without opening modal">
            {portfolioSourceRows.map((source) => (
              <PortfolioSourceSummaryLine key={source.key} source={source} />
            ))}
          </div>
          {paperSessions.length ? (
            <List
              className="qto-compact-list"
              data-contract="dashboard paper sessions render only when present no duplicate empty state"
              dataSource={paperSessions}
              renderItem={(item) => (
                <List.Item>
                  <WorkbenchListLine
                    title="Paper 会话"
                    detail={paperSessionDetail(item)}
                    status={item.status}
                  />
                </List.Item>
              )}
            />
          ) : null}
        </section>

        {runningTasks.length ? (
          <section className="qto-workbench-section qto-dashboard-activity" data-contract="dashboard running activity lives inside adaptive workbench grid; dashboard running activity heading hides duplicate count">
            <div className="qto-section-heading">
              <Typography.Text strong>运行动态</Typography.Text>
            </div>
            <List
              className="qto-compact-list"
              dataSource={runningTasks.slice(0, 5)}
              renderItem={(item) => (
                <List.Item key={runningTaskKey(item)}>
                  <WorkbenchListLine
                    title={runningTaskTitle(item)}
                    detail={runningTaskDescription(item)}
                    status={item.status}
                  />
                </List.Item>
              )}
            />
          </section>
        ) : null}
      </div>
      <Modal
        title="持仓来源管理"
        open={portfolioConnectOpen}
        onCancel={closePortfolioConnectModal}
        footer={null}
        width={760}
        destroyOnClose
      >
        <div className="qto-portfolio-connect-panel full-width" data-contract="dashboard portfolio connection modal uses multi-source holdings tablist">
          <Typography.Text className="qto-portfolio-connect-copy" type="secondary">
            当前只有 QuantConnect Paper 可配置。IBKR 仅为 locked 占位，不读取真实持仓，不支持 live trade。
          </Typography.Text>
          <div className="qto-portfolio-source-layout" data-contract="dashboard portfolio source tablist keeps ibkr visible while config changes">
            <div className="qto-portfolio-source-list" role="tablist" aria-orientation="vertical" aria-label="持仓来源">
              <div className="qto-portfolio-source-list-header">
                <span>持仓来源</span>
                <small>选择来源查看配置</small>
              </div>
              {PORTFOLIO_CONNECTION_SOURCES.map((source) => {
                const sourceSummary = portfolioSourceRows.find((row) => row.key === source.key);
                const isActiveSource = source.key === activePortfolioSource.key;
                const canSubmitSource = Boolean(source.provider && source.fields.length);
                return (
                <div className="qto-portfolio-source-item" key={source.key}>
                  <button
                    type="button"
                    className="qto-portfolio-source-option"
                    role="tab"
                    aria-controls={`portfolio-source-config-${source.key}`}
                    aria-selected={isActiveSource}
                    tabIndex={isActiveSource ? 0 : -1}
                    ref={(element) => {
                      portfolioSourceRefs.current[source.key] = element;
                    }}
                    onClick={() => setActivePortfolioSourceKey(source.key)}
                    onKeyDown={(event) => handlePortfolioSourceKeyDown(event, source)}
                    data-contract="dashboard portfolio source tablist supports roving tabindex arrow key selection"
                  >
                    <PortfolioSourceTitle source={source} summary={sourceSummary} active={isActiveSource} />
                  </button>
                  {isActiveSource ? (
                    <div
                      id={`portfolio-source-config-${source.key}`}
                      className="qto-portfolio-source-detail"
                      role="tabpanel"
                      aria-label={`${source.title} 配置`}
                      data-contract="dashboard portfolio source detail panel changes without hiding source list"
                    >
                      <PortfolioSourceConfig
                        source={source}
                        summary={sourceSummary}
                        draft={source.provider ? portfolioConnectionDrafts[source.provider] ?? {} : {}}
                        submitting={source.provider ? portfolioConnectSubmitting === source.provider : false}
                        onDraftChange={canSubmitSource ? (field, value) => updatePortfolioCredential(source.provider as PortfolioConnectionProvider, field, value) : undefined}
                        onSubmit={canSubmitSource ? () => submitPortfolioConnection(source) : undefined}
                      />
                    </div>
                  ) : null}
                </div>
                );
              })}
            </div>
          </div>
        </div>
      </Modal>
    </Space>
  );
}

function PortfolioSourceTitle({ source, summary, active }: { source: PortfolioConnectionSource; summary: PortfolioSourceSummary | undefined; active: boolean }) {
  return (
    <span className="qto-portfolio-source-title" data-contract="dashboard portfolio source tablist title hierarchy includes provider status">
      <span className="qto-portfolio-source-copy">
        <strong>{source.title}</strong>
        <small>{source.subtitle}</small>
        {summary ? <small className="qto-portfolio-source-secondary">{summary.readHoldingsLabel} · {summary.nextActionLabel}</small> : null}
      </span>
      <span className="qto-portfolio-source-title-status">
        {active ? <small className="qto-portfolio-source-active">正在查看</small> : null}
        <StatusTag status={summary?.status ?? source.status} />
      </span>
    </span>
  );
}

function PortfolioSourceConfig({
  source,
  summary,
  draft,
  submitting,
  onDraftChange,
  onSubmit,
}: {
  source: PortfolioConnectionSource;
  summary: PortfolioSourceSummary | undefined;
  draft: Record<string, string>;
  submitting: boolean;
  onDraftChange?: (field: string, value: string) => void;
  onSubmit?: () => void;
}) {
  const missingRequired = source.fields.some((field) => field.required && !draft[field.name]?.trim());
  const canSubmit = Boolean(onSubmit && source.fields.length);
  return (
    <Space direction="vertical" size={12} className="full-width" data-contract="dashboard portfolio source expands inline config instead of single-provider form">
      <Typography.Text type="secondary">{source.note}</Typography.Text>
      {summary ? (
        <div className="qto-portfolio-source-meta" data-contract="dashboard portfolio source detail shows read_holdings last_checked next action">
          <span><strong>读取持仓</strong>{summary.readHoldingsLabel.replace("读取持仓：", "")}</span>
          <span><strong>最近检查</strong>{summary.lastCheckedLabel.replace("最近检查：", "")}</span>
          <span><strong>下一步</strong>{summary.nextActionLabel.replace("下一步：", "")}</span>
          {summary.errorLabel ? <span data-state="error"><strong>错误</strong>{summary.errorLabel.replace("错误：", "")}</span> : null}
        </div>
      ) : null}
      {source.fields.length ? (
        <div className="qto-portfolio-field-grid">
          {source.fields.map((field) => (
            <label className="qto-form-field" key={field.name}>
              <span>{field.label}</span>
              {field.secret ? (
                <Input.Password
                  value={draft[field.name] ?? ""}
                  onChange={(event) => onDraftChange?.(field.name, event.target.value)}
                  placeholder={field.placeholder}
                />
              ) : (
                <Input
                  value={draft[field.name] ?? ""}
                  onChange={(event) => onDraftChange?.(field.name, event.target.value)}
                  placeholder={field.placeholder}
                />
              )}
            </label>
          ))}
        </div>
      ) : null}
      {canSubmit ? (
        <Button type="primary" onClick={onSubmit} loading={submitting} disabled={submitting || missingRequired}>
          {source.actionLabel ?? "保存来源"}
        </Button>
      ) : source.provider === "ibkr" ? (
        <Typography.Text type="secondary">当前不可连接，仅保留 locked 来源说明。</Typography.Text>
      ) : (
        <Typography.Text type="secondary">无需外部连接配置。</Typography.Text>
      )}
    </Space>
  );
}

function PortfolioSourceSummaryLine({ source }: { source: PortfolioSourceSummary }) {
  return (
    <div className="qto-portfolio-source-summary-row">
      <span className="qto-portfolio-source-summary-copy">
        <strong>{source.title}</strong>
        <small>{source.detail}</small>
        <small>{source.readHoldingsLabel} · {source.lastCheckedLabel}</small>
        {source.errorLabel ? <small className="qto-portfolio-source-error">{source.errorLabel}</small> : null}
        <small className="qto-portfolio-source-next">{source.nextActionLabel}</small>
      </span>
      <span className="qto-portfolio-source-summary-status">
        <span>{source.capabilityLabel}</span>
        <StatusTag status={source.status} />
      </span>
    </div>
  );
}

function freshPortfolioDrafts(): Record<PortfolioConnectionProvider, Record<string, string>> {
  return {
    quantconnect: { user_id: "", api_token: "" },
    ibkr: {},
  };
}

function WorkbenchListLine({ title, detail, status }: { title: string; detail: string | null | undefined; status: string }) {
  return (
    <div className="qto-workbench-list-line" data-contract="dashboard compact single-line list row no stacked metadata; dashboard list row hides empty detail placeholders">
      <span className="qto-workbench-list-main">
        <strong>{title}</strong>
        {detail ? <small>{detail}</small> : null}
      </span>
      <StatusTag status={status} />
    </div>
  );
}

function WorkbenchPriorityRow({ item, rank }: { item: WorkbenchPriorityItem; rank: number }) {
  const content = (
    <>
      <span className="qto-priority-rank">{rank}</span>
      <span className="qto-priority-main">
        <strong>{item.title}</strong>
        <small>{item.detail}</small>
        <small>负责人 {item.ownerLabel} · {item.actionLabel}</small>
      </span>
      <StatusTag status={item.status} />
    </>
  );
  if (item.onClick) {
    return (
      <button type="button" className="qto-priority-row qto-priority-row-button" onClick={item.onClick} data-contract="dashboard priority queue uses native buttons for actionable rows">
        {content}
      </button>
    );
  }
  return (
    <div className="qto-priority-row" data-contract="dashboard priority queue keeps non-clickable risk items honest">
      {content}
    </div>
  );
}

function WorkbenchMetric({ label, value }: { label: string; value: ReactNode }) {
  return (
    <div className="qto-workbench-metric" data-contract="dashboard key value metric no detail stack">
      <Typography.Text type="secondary">{label}</Typography.Text>
      <span className="qto-workbench-metric-value">{value}</span>
    </div>
  );
}

function formatPortfolioMetric(value: number) {
  return value.toLocaleString(undefined, { maximumFractionDigits: 2 });
}

function portfolioMetricItems(portfolio: DashboardSummary["portfolio"] | undefined) {
  return [
    { label: "总资产", value: portfolio?.total_equity },
    { label: "今日 PnL", value: portfolio?.pnl_today },
    { label: "现金", value: portfolio?.cash },
  ].filter((item): item is { label: string; value: number } => typeof item.value === "number");
}

function workbenchPriorityItems({
  riskAlerts,
  pendingApprovals,
  pendingResearchItems,
  portfolioSourceRows,
  onApprovalClick,
  onResearchItemClick,
  onPortfolioSourceClick,
}: {
  riskAlerts: RiskReview[];
  pendingApprovals: ApprovalRequest[];
  pendingResearchItems: ResearchDecisionItem[];
  portfolioSourceRows: PortfolioSourceSummary[];
  onApprovalClick: (approval: ApprovalRequest) => void;
  onResearchItemClick: (item: ResearchPipelineItem) => void;
  onPortfolioSourceClick: () => void;
}) {
  const items: WorkbenchPriorityItem[] = [
    ...riskAlerts.slice(0, 2).map((item) => ({
      kind: "risk" as const,
      key: `risk:${item.id}`,
      title: "复核策略风险",
      detail: riskReviewDetail(item) || "风险结果需要人工复核",
      ownerLabel: "风控",
      actionLabel: "在下方风险区查看",
      status: item.verdict,
    })),
    ...pendingApprovals.slice(0, 3).map((item) => ({
      kind: "approval" as const,
      key: `approval:${item.id}`,
      title: formatApprovalTitle(item),
      detail: formatApprovalDescription(item) ?? "等待人工审批说明",
      ownerLabel: "审批",
      actionLabel: "处理审批",
      status: item.status,
      onClick: () => onApprovalClick(item),
    })),
    ...pendingResearchItems.slice(0, 3).map((item) => ({
      kind: "research" as const,
      key: `research:${item.id}`,
      title: item.title,
      detail: researchDecisionDetail(item) || "研究项目需要下一步动作",
      ownerLabel: item.owner_agent ?? "研究",
      actionLabel: "打开研究详情",
      status: item.approval_status ?? item.risk_verdict ?? item.status,
      onClick: () => onResearchItemClick(item),
    })),
    ...portfolioPriorityItems(portfolioSourceRows, onPortfolioSourceClick),
  ];
  return items.slice(0, 3);
}

function portfolioPriorityItems(rows: PortfolioSourceSummary[], onPortfolioSourceClick: () => void): WorkbenchPriorityItem[] {
  return rows
    .filter((source) => source.key === "quantconnect" && (["error", "testing"].includes(source.status) || Boolean(source.errorLabel)))
    .map((source) => ({
      kind: "portfolio",
      key: `portfolio:${source.key}`,
      title: source.status === "testing" ? "等待 QuantConnect Paper 检查" : "配置 QuantConnect Paper",
      detail: source.errorLabel ?? source.detail,
      ownerLabel: "数据连接",
      actionLabel: source.nextActionLabel.replace("下一步：", ""),
      status: source.status,
      onClick: onPortfolioSourceClick,
    }));
}

function portfolioConnectionRows(connections: DashboardSummary["connections"] | undefined): PortfolioSourceSummary[] {
  const byProvider = new Map((connections ?? []).map((connection) => [connection.provider, connection]));
  return PORTFOLIO_CONNECTION_SOURCES.map((source) => {
    const connection = source.provider ? byProvider.get(source.provider) : undefined;
    return {
      key: source.key,
      title: source.title,
      capabilityLabel: portfolioSourceCapabilityLabel(source, connection),
      detail: portfolioSourceSummaryDetail(source, connection),
      status: portfolioSourceSummaryStatus(source, connection),
      readHoldingsLabel: portfolioSourceReadHoldingsLabel(source, connection),
      lastCheckedLabel: portfolioSourceLastCheckedLabel(connection),
      errorLabel: portfolioSourceErrorLabel(connection),
      nextActionLabel: portfolioSourceNextActionLabel(source, connection),
    };
  });
}

function portfolioSourceSummaryStatus(source: PortfolioConnectionSource, connection: PortfolioConnection | undefined) {
  if (!source.provider) return source.status;
  if (source.provider === "ibkr") return "locked";
  return connection?.status ?? "disconnected";
}

function portfolioSourceSummaryDetail(source: PortfolioConnectionSource, connection: PortfolioConnection | undefined) {
  if (source.provider === "quantconnect") {
    if (connection?.status === "connected" && portfolioConnectionCanReadHoldings(connection)) return "Paper 来源已验证，secret 只保存为后端引用";
    if (connection?.status === "connected") return "连接已验证，持仓读取未启用";
    if (connection?.status === "testing") return "连接检查中，等待后端返回结果";
    if (connection?.last_error) return `连接异常：${connection.last_error}`;
    return "Paper workflow 可配置，需要 user_id 和 API token";
  }
  if (source.provider === "ibkr") return "Live trading locked；不读取真实 IBKR 持仓";
  return "无外部连接时的本地 fallback，不伪造真实账户";
}

function portfolioSourceCapabilityLabel(source: PortfolioConnectionSource, connection: PortfolioConnection | undefined) {
  if (source.provider === "ibkr") return "locked";
  if (!source.provider) return source.capabilityLabel;
  if (connection?.status === "connected") return portfolioConnectionCanReadHoldings(connection) ? "可读持仓" : "已验证";
  if (connection?.status === "testing") return "检查中";
  if (connection?.status === "error") return "异常";
  return source.capabilityLabel;
}

function portfolioSourceReadHoldingsLabel(source: PortfolioConnectionSource, connection: PortfolioConnection | undefined) {
  if (!source.provider) return "读取持仓：不适用，本地 fallback";
  if (source.provider === "ibkr") return "读取持仓：否，live trade locked";
  if (portfolioConnectionCanReadHoldings(connection)) return "读取持仓：已启用";
  if (connection?.metadata?.capabilities?.paper_trade) return "读取持仓：暂未启用，Paper workflow 可用";
  return "读取持仓：暂未启用";
}

function portfolioSourceLastCheckedLabel(connection: PortfolioConnection | undefined) {
  if (!connection?.last_checked_at) return "最近检查：尚未检查";
  const date = new Date(connection.last_checked_at);
  if (Number.isNaN(date.getTime())) return "最近检查：尚未检查";
  return `最近检查：${date.toLocaleString()}`;
}

function portfolioSourceErrorLabel(connection: PortfolioConnection | undefined) {
  return connection?.last_error ? `错误：${connection.last_error}` : null;
}

function portfolioSourceNextActionLabel(source: PortfolioConnectionSource, connection: PortfolioConnection | undefined) {
  if (source.provider === "quantconnect") {
    if (connection?.status === "connected" && portfolioConnectionCanReadHoldings(connection)) return "下一步：刷新持仓";
    if (connection?.status === "connected") return "下一步：继续 Paper workflow；持仓读取未启用";
    if (connection?.status === "testing") return "下一步：刷新状态";
    if (connection?.status === "error") return "下一步：重新测试或重新连接";
    return "下一步：保存并测试 QuantConnect Paper";
  }
  if (source.provider === "ibkr") return "下一步：保持 locked，等待真实账户接入合同";
  return "下一步：接入 QuantConnect Paper；真实券商保持 locked";
}

function portfolioConnectionCanReadHoldings(connection: PortfolioConnection | undefined) {
  return connection?.metadata?.capabilities?.read_holdings === true;
}

function researchDecisionItems(pipeline: ResearchPipeline | null) {
  if (!pipeline) return [];
  return pipeline.stages
    .flatMap((stage) => stage.items.map((item) => ({ ...item, stage_label: stage.label })))
    .filter(isResearchDecisionItem)
    .sort((left, right) => researchDecisionPriority(right) - researchDecisionPriority(left));
}

function isResearchDecisionItem(item: ResearchDecisionItem) {
  const status = normalizeResearchStatus(item.status);
  return (
    item.missing_requirements.length > 0
    || item.next_actions.length > 0
    || normalizeResearchStatus(item.approval_status) === "pending"
    || ["fail", "failed", "blocked", "warning"].includes(normalizeResearchStatus(item.risk_verdict))
    || ["data_required", "waiting_approval", "blocked"].includes(status)
  );
}

function researchDecisionPriority(item: ResearchDecisionItem) {
  let score = 0;
  if (normalizeResearchStatus(item.approval_status) === "pending") score += 40;
  if (item.missing_requirements.length > 0) score += 30;
  if (["fail", "failed", "blocked", "warning"].includes(normalizeResearchStatus(item.risk_verdict))) score += 25;
  if (item.next_actions.length > 0) score += 10;
  return score;
}

function researchDecisionDetail(item: ResearchDecisionItem) {
  const nextAction = pipelineActionLabel(item.next_actions[0]) ?? item.next_actions[0] ?? null;
  const missing = item.missing_requirements.slice(0, 2).map(researchRequirementLabel).join("、");
  return [
    item.stage_label || item.stage,
    missing ? `缺 ${missing}` : null,
    nextAction ? `下一步 ${nextAction}` : null,
    researchMetricSummary(item.latest_metrics),
  ].filter(Boolean).join(" · ");
}

function researchRequirementLabel(value: string) {
  const labels: Record<string, string> = {
    approval: "审批",
    connection: "连接",
    data: "数据",
    risk_review: "风控复核",
    backtest: "回测",
  };
  return labels[value] ?? readableIdentifier(value);
}

function researchMetricSummary(metrics: Record<string, unknown>) {
  const sharpe = firstMetricValue(metrics, ["sharpe", "Sharpe"]);
  const drawdown = firstMetricValue(metrics, ["max_drawdown", "max drawdown", "maxDrawdown"]);
  if (sharpe !== null) return `Sharpe ${sharpe}`;
  if (drawdown !== null) return `max drawdown ${drawdown}`;
  return null;
}

function firstMetricValue(metrics: Record<string, unknown>, keys: string[]) {
  for (const key of keys) {
    const value = metrics[key];
    if (typeof value === "number") return value.toFixed(2);
    if (typeof value === "string" && value.trim()) return value.trim();
  }
  return null;
}

function normalizeResearchStatus(value: unknown) {
  return String(value ?? "").trim().toLowerCase();
}

function accountConnectionNote(portfolio: DashboardSummary["portfolio"] | undefined, liveTradingLocked: boolean) {
  const mode = portfolio?.mode ?? "unavailable";
  const detail = accountSourceDetail(mode, portfolio?.source);
  if (mode === "live" && liveTradingLocked) return { mode, title: "Live 未启用", detail: "Live trading locked；未启用真实券商持仓读取或 live trade" };
  if (mode === "live") return { mode, title: "Live 账户已连接", detail };
  if (mode === "paper") return { mode, title: "Paper 模式", detail };
  if (mode === "simulated") return { mode, title: "模拟组合", detail };
  return { mode, title: "未连接账户", detail };
}

function accountSourceDetail(mode: DashboardSummary["portfolio"]["mode"], source: string | undefined) {
  const value = source?.trim();
  if (value && isPaperSimulatedOnlySource(value)) return "Paper/模拟数据，未连接 Live 券商账户";
  if (value && !isDefaultPortfolioSource(value)) return value;
  if (mode === "live") return "实时券商数据";
  if (mode === "paper") return "Paper 交易数据";
  if (mode === "simulated") return "模拟组合数据";
  return "未接入券商或 Paper 账户";
}

function isDefaultPortfolioSource(source: string) {
  const value = source.toLowerCase();
  return (
    value === "paper / simulated / unavailable"
    || isPaperSimulatedOnlySource(source)
  );
}

function isPaperSimulatedOnlySource(source: string) {
  const value = source.toLowerCase();
  return value.includes("paper/simulated only") || value.includes("no live broker account connected");
}

function isAgentRun(row: RunningTask): row is AgentRun {
  return "task_type" in row;
}

function runningTaskKey(row: RunningTask) {
  return isAgentRun(row) ? row.id : row.id ?? row.workflow_id;
}

function runningTaskTitle(row: RunningTask) {
  return isAgentRun(row) ? agentTaskTypeLabel(row.task_type) : workflowTypeLabel(row.workflow_type) ?? "工作流";
}

function runningTaskDescription(row: RunningTask) {
  return isAgentRun(row) ? linkedDashboardObject("工作流", row.workflow_id) : ownerLinkedLabel(row.owner_type, row.owner_id);
}

function paperSessionDetail(item: PaperTradingSession) {
  return [
    linkedDashboardObject("策略", item.strategy_id),
    item.provider || null,
    linkedDashboardObject("部署", item.deployment_ref),
  ].filter(Boolean).join(" · ");
}

function riskReviewDetail(item: RiskReview) {
  return [
    linkedDashboardObject("策略", item.strategy_id),
    linkedDashboardObject("回测", item.backtest_run_id),
    typeof item.risk_summary?.reason === "string" ? item.risk_summary.reason : null,
    evidenceGradeLabel(item.risk_summary?.evidence_grade),
  ].filter(Boolean).join(" · ");
}

function evidenceGradeLabel(value: unknown) {
  const grade = String(value ?? "").trim().toLowerCase();
  if (grade === "verified") return "证据: 已验证";
  if (grade === "sample") return "证据: 样例数据";
  if (grade === "unverified") return "证据: 未验证";
  return null;
}

function dashboardRiskAlerts(riskReviews: RiskReview[]) {
  return riskReviews.filter(isDashboardRiskAlert);
}

function isDashboardRiskAlert(item: RiskReview) {
  const verdict = normalizeRiskStatus(item.verdict);
  const summaryVerdict = normalizeRiskStatus(item.risk_summary?.verdict);
  return [verdict, summaryVerdict].some((value) => ["fail", "failed", "blocked", "warning"].includes(value));
}

function normalizeRiskStatus(value: unknown) {
  return String(value ?? "").trim().toLowerCase();
}

function linkedDashboardObject(label: string, id: string | null | undefined) {
  return id ? `${label} ${readableIdentifier(id)}` : null;
}

function formatApprovalDescription(row: ApprovalRequest) {
  return [
    approvalPolicyReasonLabel(row.policy_lock_reason),
    evidenceGradeLabel(row.risk_summary?.evidence_grade),
  ].filter(Boolean).join(" · ") || null;
}
