import { MoreOutlined } from "@ant-design/icons";
import { Button, Collapse, Drawer, Dropdown, Form, Input, List, Modal, Space, Typography, message } from "antd";
import { useCallback, useEffect, useState, type ReactNode } from "react";
import {
  clearStoredAuth,
  finishKeycloakLoginIfNeeded,
  patchApi,
  postApi,
  putApi,
  readApi,
  readResourceList,
  readResourceValue,
  readTokenUser,
  startKeycloakLoginRedirect,
  storedAccessToken,
} from "./api/client";
import type {
  AgentGraph,
  AgentRun,
  ApprovalRequest,
  BacktestRun,
  DashboardSummary,
  FactorSpec,
  FactorWorkspace,
  PaperTradingSession,
  ResearchPipeline,
  ResearchPipelineItem,
  ResearchReportItem,
  RiskReview,
  StrategySpec,
  StrategyWorkspace,
  WorkflowLink,
} from "./api/types";
import { StatusTag, formatStatusLabel } from "./components/StatusTag";
import { CompactEmpty } from "./components/CompactEmpty";
import { AppShell } from "./layout/AppShell";
import { AgentCanvasPage } from "./pages/agents/AgentCanvasPage";
import { DashboardPage } from "./pages/dashboard/DashboardPage";
import { ExperimentsPage } from "./pages/research/ExperimentsPage";
import { FactorsStrategiesPage } from "./pages/research/FactorsStrategiesPage";
import { ReportsPage } from "./pages/research/ReportsPage";
import { ResearchPipelinePage } from "./pages/research/ResearchPipelinePage";
import { LEGACY_REDIRECTS, ROUTE_PATHS, type AppRoute, pathForRoute, routeFromLocation } from "./routes";
import { approvalPolicyReasonLabel, approvalRequestTypeLabel, approvalTargetTypeLabel, formatApprovalTitle, formatDisplayDate, pipelineActionLabel, readableIdentifier } from "./displayLabels";

const APPROVAL_COMMENT_CONTRACT = "okButtonProps={{ disabled: !approvalComment.trim() }}";
const LIVE_APPROVAL_LOCK_FALLBACK_REASON = "Live trading is locked by MVP policy";

export function App() {
  const [route, setRoute] = useState<AppRoute>(() => routeFromLocation());
  const [factorTab, setFactorTab] = useState<"factors" | "strategies">("factors");
  const [dashboard, setDashboard] = useState<DashboardSummary | null>(null);
  const [pipeline, setPipeline] = useState<ResearchPipeline | null>(null);
  const [factors, setFactors] = useState<FactorSpec[]>([]);
  const [strategies, setStrategies] = useState<StrategySpec[]>([]);
  const [backtests, setBacktests] = useState<BacktestRun[]>([]);
  const [riskReviews, setRiskReviews] = useState<RiskReview[]>([]);
  const [approvals, setApprovals] = useState<ApprovalRequest[]>([]);
  const [paperSessions, setPaperSessions] = useState<PaperTradingSession[]>([]);
  const [workflows, setWorkflows] = useState<WorkflowLink[]>([]);
  const [agentRuns, setAgentRuns] = useState<AgentRun[]>([]);
  const [reports, setReports] = useState<ResearchReportItem[]>([]);
  const [agentGraph, setAgentGraph] = useState<AgentGraph | null>(null);
  const [authUser, setAuthUser] = useState<{ username?: string; roles?: string[] } | null>(() => readTokenUser(storedAccessToken()));
  const [apiError, setApiError] = useState<string | null>(null);
  const [selectedApproval, setSelectedApproval] = useState<ApprovalRequest | null>(null);
  const [approvalComment, setApprovalComment] = useState("");
  const [ideaModalOpen, setIdeaModalOpen] = useState(false);
  const [selectedPipelineItem, setSelectedPipelineItem] = useState<ResearchPipelineItem | null>(null);
  const [factorWorkspace, setFactorWorkspace] = useState<FactorWorkspace | null>(null);
  const [strategyWorkspace, setStrategyWorkspace] = useState<StrategyWorkspace | null>(null);
  const [ideaForm] = Form.useForm();

  const loadData = useCallback(async () => {
    const results = await Promise.allSettled([
      readResourceValue<DashboardSummary>("dashboard"),
      readResourceValue<ResearchPipeline>("research-pipeline"),
      readResourceList<FactorSpec>("factors"),
      readResourceList<StrategySpec>("strategies"),
      readResourceList<BacktestRun>("backtests"),
      readResourceList<RiskReview>("risk-reviews"),
      readResourceList<ApprovalRequest>("approvals"),
      readResourceList<PaperTradingSession>("paper-sessions"),
      readResourceList<WorkflowLink>("workflows"),
      readResourceList<AgentRun>("agent-runs"),
      readResourceList<ResearchReportItem>("reports"),
      readResourceValue<AgentGraph>("agent-graph"),
    ]);
    const [dashboardResult, pipelineResult, factorsResult, strategiesResult, backtestsResult, risksResult, approvalsResult, paperResult, workflowsResult, runsResult, reportsResult, graphResult] = results;
    if (dashboardResult.status === "fulfilled") setDashboard(dashboardResult.value);
    if (pipelineResult.status === "fulfilled") setPipeline(pipelineResult.value);
    if (factorsResult.status === "fulfilled") setFactors(factorsResult.value);
    if (strategiesResult.status === "fulfilled") setStrategies(strategiesResult.value);
    if (backtestsResult.status === "fulfilled") setBacktests(backtestsResult.value);
    if (risksResult.status === "fulfilled") setRiskReviews(risksResult.value);
    if (approvalsResult.status === "fulfilled") setApprovals(approvalsResult.value);
    if (paperResult.status === "fulfilled") setPaperSessions(paperResult.value);
    if (workflowsResult.status === "fulfilled") setWorkflows(workflowsResult.value);
    if (runsResult.status === "fulfilled") setAgentRuns(runsResult.value);
    if (reportsResult.status === "fulfilled") setReports(reportsResult.value);
    if (graphResult.status === "fulfilled") setAgentGraph(graphResult.value);
    const firstFailure = results.find((result) => result.status === "rejected") as PromiseRejectedResult | undefined;
    setApiError(firstFailure ? String(firstFailure.reason?.message ?? firstFailure.reason) : null);
  }, []);

  useEffect(() => {
    const syncLocation = () => {
      const cleanPath = window.location.pathname.replace(/\/$/, "") || "/";
      const redirect = LEGACY_REDIRECTS[cleanPath];
      if (redirect) {
        window.history.replaceState({}, "", redirect);
      }
      setRoute(routeFromLocation());
      const tab = new URLSearchParams(window.location.search).get("tab");
      setFactorTab(tab === "strategies" ? "strategies" : "factors");
    };
    syncLocation();
    window.addEventListener("popstate", syncLocation);
    return () => window.removeEventListener("popstate", syncLocation);
  }, []);

  useEffect(() => {
    finishKeycloakLoginIfNeeded()
      .then((token) => {
        if (token) setAuthUser(readTokenUser(token));
      })
      .catch((error) => message.error(String(error.message ?? error)));
    loadData();
  }, [loadData]);

  const apiHealthy = dashboard?.status.api === "healthy" && !apiError;

  function changeRoute(nextRoute: AppRoute) {
    const path = pathForRoute(nextRoute);
    window.history.pushState({}, "", path);
    setRoute(nextRoute);
    if (nextRoute === "factors-strategies") {
      setFactorTab("factors");
    }
  }

  function changeFactorTab(tab: "factors" | "strategies") {
    setFactorTab(tab);
    window.history.pushState({}, "", `${ROUTE_PATHS["factors-strategies"]}?tab=${tab}`);
  }

  async function createIdea(values: Record<string, string>) {
    await postApi("/api/v1/research-ideas", {
      title: values.title,
      thesis: values.thesis,
      universe: values.universe || "US equities",
      asset_class: values.asset_class || "equity",
      proposed_by: "human",
      tags: values.tags ? values.tags.split(",").map((item) => item.trim()).filter(Boolean) : [],
    });
    setIdeaModalOpen(false);
    ideaForm.resetFields();
    await loadData();
  }

  async function startResearchWorkflow(item: ResearchPipelineItem) {
    if (item.item_type !== "research_idea") {
      message.warning("只有 research idea 可以启动研究流");
      return;
    }
    await postApi(`/api/v1/research-ideas/${item.id}/start-workflow`, {});
    message.success(`已启动研究流：${item.title}`);
    await loadData();
  }

  async function openFactor(factor: FactorSpec) {
    try {
      setFactorWorkspace(await readResourceValue<FactorWorkspace>(`/api/v1/factors/${factor.id}/workspace`));
    } catch {
      setFactorWorkspace({ factor, reports: [], used_by_strategies: strategies.filter((strategy) => strategy.factors.includes(factor.id) || strategy.factors.includes(factor.name)), latest_workflows: [], latest_agent_runs: [] });
    }
  }

  async function openStrategy(strategy: StrategySpec) {
    try {
      setStrategyWorkspace(await readResourceValue<StrategyWorkspace>(`/api/v1/strategies/${strategy.id}/workspace`));
    } catch {
      setStrategyWorkspace({ strategy, card: strategy.card ?? null, factors: factors.filter((factor) => strategy.factors.includes(factor.id) || strategy.factors.includes(factor.name)), backtests: backtests.filter((run) => run.strategy_id === strategy.id), risk_reviews: riskReviews.filter((row) => row.strategy_id === strategy.id), approvals: approvals.filter((row) => row.target_id === strategy.id), paper_sessions: paperSessions.filter((row) => row.strategy_id === strategy.id), artifacts: [], workflows: workflows.filter((row) => row.owner_id === strategy.id) });
    }
  }

  async function resolveApproval(action: "approve" | "reject" | "request-changes") {
    if (!selectedApproval) return;
    const comment = approvalComment.trim();
    if (!comment) {
      message.error("请填写审批说明");
      return;
    }
    await postApi(`/api/v1/approvals/${selectedApproval.id}/${action}`, { human_comment: comment });
    setSelectedApproval(null);
    setApprovalComment("");
    await loadData();
  }

  async function requestRiskReview(run: BacktestRun) {
    await postApi("/api/v1/risk/reviews", {
      strategy_id: run.strategy_id,
      backtest_run_id: run.id,
      metrics: run.metrics ?? {},
      cost_model: run.cost_model ?? null,
      slippage_model: run.slippage_model ?? null,
      factor_report_present: Boolean(run.artifacts?.length),
      start_date: run.start_date ?? null,
      end_date: run.end_date ?? null,
      request_type: "risk_review",
    });
    message.success("已提交风控复核");
    await loadData();
  }

  async function createBacktest(payload: { strategy_id: string; dataset_version: string }) {
    await postApi("/api/v1/backtests", payload);
    message.success("已启动回测");
    await loadData();
  }

  async function saveAgentLayout(nodes: Array<{ id: string; position: { x: number; y: number } }>, edges: Array<{ id: string; status?: string }>) {
    setAgentGraph(await putApi<AgentGraph>("/api/v1/agent-graph", { nodes, edges }));
    message.success("画布已保存");
  }

  async function createAgent(payload: Record<string, unknown>) {
    await postApi("/api/v1/agents", payload);
    await loadData();
  }

  async function patchAgent(agentId: string, payload: Record<string, unknown>) {
    await patchApi(`/api/v1/agents/${agentId}`, payload);
    await loadData();
  }

  async function runAgent(agentId: string) {
    await postApi(`/api/v1/agents/${agentId}/runs`, { source: "Agent Canvas" });
    await loadData();
  }

  async function connectTool(provider: string, credentials: Record<string, string>) {
    await postApi(`/api/v1/connections/${provider}/connect`, { credentials });
    await loadData();
  }

  async function testTool(provider: string) {
    await postApi(`/api/v1/connections/${provider}/test`, {});
    await loadData();
  }

  function renderRoute() {
    if (route === "dashboard") {
      return (
        <DashboardPage
          summary={dashboard}
          approvals={dashboard?.approvals ?? approvals}
          riskReviews={dashboard?.risk_alerts ?? riskReviews}
          agentRuns={agentRuns}
          workflows={workflows}
          paperSessions={paperSessions}
          pipeline={pipeline}
          onConnectPortfolio={connectTool}
          onApprovalClick={(approval) => {
            setSelectedApproval(approval);
            setApprovalComment("");
          }}
          onResearchItemClick={setSelectedPipelineItem}
        />
      );
    }
    if (route === "research-pipeline") {
      return <ResearchPipelinePage pipeline={pipeline} onCreateIdea={() => setIdeaModalOpen(true)} onItemClick={setSelectedPipelineItem} />;
    }
    if (route === "factors-strategies") {
      return (
        <FactorsStrategiesPage
          factors={factors}
          strategies={strategies}
          risks={riskReviews}
          activeTab={factorTab}
          onTabChange={changeFactorTab}
          onFactorClick={openFactor}
          onStrategyClick={openStrategy}
        />
      );
    }
    if (route === "experiments") {
      return <ExperimentsPage backtests={backtests} strategies={strategies} onRunBacktest={createBacktest} onRequestRiskReview={requestRiskReview} />;
    }
    if (route === "reports") {
      return <ReportsPage reports={reports} />;
    }
    return (
      <AgentCanvasPage
        graph={agentGraph}
        agentRuns={agentRuns}
        workflows={workflows}
        onRefresh={loadData}
        onSaveLayout={saveAgentLayout}
        onCreateAgent={createAgent}
        onPatchAgent={patchAgent}
        onRunAgent={runAgent}
        onConnectTool={connectTool}
        onTestTool={testTool}
      />
    );
  }

  const approvalLocked = Boolean(selectedApproval && (selectedApproval.policy_lock_reason || isLiveRelatedApproval(selectedApproval)));

  return (
    <>
      <AppShell
        route={route}
        onRouteChange={changeRoute}
      >
        {apiError ? <InlineNotice tone="error" title="后端请求失败">{apiError}</InlineNotice> : null}
        {renderRoute()}
      </AppShell>

      <Drawer width={520} title="待办审批" open={Boolean(selectedApproval)} onClose={() => setSelectedApproval(null)}>
        {selectedApproval ? (
          <Space direction="vertical" size={16} className="full-width" data-contract={APPROVAL_COMMENT_CONTRACT}>
            <div className="qto-approval-summary">
              <Typography.Text strong>{formatApprovalTitle(selectedApproval)}</Typography.Text>
              <Space wrap size={[6, 6]}>
                <StatusTag status={selectedApproval.status} />
                {approvalLocked ? <DetailMeta tone="danger">策略限制</DetailMeta> : null}
              </Space>
              {approvalLocked ? (
                <InlineNotice tone="warning" title="当前不可批准">
                  {approvalLockReason(selectedApproval)}
                </InlineNotice>
              ) : null}
            </div>
            <Collapse
              size="small"
              items={approvalCollapseItems(selectedApproval)}
            />
            <Input.TextArea rows={4} placeholder="填写审批说明" value={approvalComment} onChange={(event) => setApprovalComment(event.target.value)} />
            <Space className="qto-approval-actions" data-contract="approval primary action plus compact secondary menu">
              <Button aria-label="批准" type="primary" disabled={approvalLocked || !approvalComment.trim()} onClick={() => resolveApproval("approve")}>批准</Button>
              <Dropdown
                trigger={["click"]}
                menu={{
                  items: [
                    { key: "request-changes", label: "要求修改" },
                    { key: "reject", label: "拒绝", danger: true },
                  ],
                  onClick: ({ key }) => {
                    if (key === "request-changes" || key === "reject") void resolveApproval(key);
                  },
                }}
              >
                <Button
                  aria-label="审批更多操作"
                  icon={<MoreOutlined />}
                  disabled={!approvalComment.trim()}
                  data-contract="approval secondary menu icon-only no persistent text"
                />
              </Dropdown>
            </Space>
          </Space>
        ) : null}
      </Drawer>

      <Modal title="创建研究想法" open={ideaModalOpen} onCancel={() => setIdeaModalOpen(false)} onOk={() => ideaForm.submit()} okText="创建" cancelText="取消">
        <Form form={ideaForm} layout="vertical" onFinish={createIdea}>
          <Form.Item name="title" label="研究标题" rules={[{ required: true }]}>
            <Input />
          </Form.Item>
          <Form.Item name="thesis" label="研究笔记" rules={[{ required: true }]}>
            <Input.TextArea rows={4} />
          </Form.Item>
          <Collapse
            size="small"
            items={[{
              key: "scope",
              label: "研究范围",
              children: (
                <>
                  <Form.Item name="universe" label="标的池">
                    <Input placeholder="例如 美股大盘" />
                  </Form.Item>
                  <Form.Item name="asset_class" label="资产类别">
                    <Input placeholder="例如 股票" />
                  </Form.Item>
                  <Form.Item name="tags" label="标签">
                    <Input placeholder="动量, 质量" />
                  </Form.Item>
                </>
              ),
            }]}
          />
        </Form>
      </Modal>

      <Drawer width={640} title="研究项目详情" open={Boolean(selectedPipelineItem)} onClose={() => setSelectedPipelineItem(null)}>
        {selectedPipelineItem ? (
          <Space direction="vertical" size={16} className="full-width">
            <DetailHeader title={selectedPipelineItem.title} description={pipelineActionLabel(selectedPipelineItem.latest_action)}>
              <StatusTag status={selectedPipelineItem.status} />
              <DetailMeta>{pipelineStageLabel(selectedPipelineItem.stage)}</DetailMeta>
            </DetailHeader>
            {selectedPipelineItem.item_type === "research_idea" ? (
              <div className="qto-detail-action-row" data-contract="research workflow action scoped to selected project">
                <Button type="primary" onClick={() => startResearchWorkflow(selectedPipelineItem)}>启动研究流</Button>
              </div>
            ) : null}
            <DetailInlineMeta items={pipelineDetailMetaItems(selectedPipelineItem)} />
            <MetricSummary metrics={selectedPipelineItem.latest_metrics} keys={["sharpe", "max_drawdown", "cagr", "turnover"]} />
            <DetailTagSection title="缺失项" items={selectedPipelineItem.missing_requirements} empty="无缺失项" hideWhenEmpty contract="pipeline detail optional sections render only when populated" />
            <DetailTagSection title="下一步" items={pipelineActionItems(selectedPipelineItem.next_actions)} empty="暂无动作" hideWhenEmpty contract="pipeline detail optional sections render only when populated" />
          </Space>
        ) : null}
      </Drawer>

      <Drawer width={720} title="因子详情" open={Boolean(factorWorkspace)} onClose={() => setFactorWorkspace(null)}>
        {factorWorkspace ? (
          <Space direction="vertical" size={16} className="full-width">
            <DetailHeader title={factorWorkspace.factor.name} description={factorWorkspace.factor.description}>
              <StatusTag status={factorWorkspace.factor.status} />
              {factorWorkspace.factor.input_fields.length ? <DetailMeta>{`${factorWorkspace.factor.input_fields.length} 个输入`}</DetailMeta> : null}
              {factorWorkspace.factor.rebalance_frequency ? <DetailMeta>{factorWorkspace.factor.rebalance_frequency}</DetailMeta> : null}
              {factorWorkspace.factor.lookback_window ? <DetailMeta>{`观察窗口 ${factorWorkspace.factor.lookback_window}`}</DetailMeta> : null}
            </DetailHeader>
            <MetricSummary metrics={factorWorkspace.factor.metrics} keys={["ic", "rank_ic", "coverage", "turnover"]} />
            <OptionalDetailCollapse items={factorAdvancedCollapseItems(factorWorkspace.factor)} />
            <Typography.Text strong>被哪些策略使用</Typography.Text>
            <List
              className="qto-detail-list"
              dataSource={factorWorkspace.used_by_strategies}
              locale={{ emptyText: <CompactEmpty>暂无使用策略</CompactEmpty> }}
              renderItem={(strategy) => (
                <List.Item className="qto-detail-list-row qto-detail-compact-row" data-contract="detail relation compact single-line row">
                  <div className="qto-detail-compact-line">
                    <span className="qto-detail-compact-main">
                      <strong>{strategy.name}</strong>
                      {strategyRelationSummary(strategy) ? <small>{strategyRelationSummary(strategy)}</small> : null}
                    </span>
                    <StatusTag status={strategy.status} />
                  </div>
                </List.Item>
              )}
            />
          </Space>
        ) : null}
      </Drawer>

      <Drawer width={760} title="策略详情" open={Boolean(strategyWorkspace)} onClose={() => setStrategyWorkspace(null)}>
        {strategyWorkspace ? (
          <Space direction="vertical" size={16} className="full-width">
            <DetailHeader title={strategyWorkspace.strategy.name} description={strategyWorkspace.strategy.description}>
              <StatusTag status={strategyWorkspace.strategy.status} />
              {strategyWorkspace.strategy.universe ? <DetailMeta>{strategyWorkspace.strategy.universe}</DetailMeta> : null}
              {strategyWorkspace.factors.length ? <DetailMeta>{`${strategyWorkspace.factors.length} 个因子`}</DetailMeta> : null}
              {strategyWorkspace.strategy.rebalance_frequency ? <DetailMeta>{strategyWorkspace.strategy.rebalance_frequency}</DetailMeta> : null}
            </DetailHeader>
            <DetailInlineMeta items={strategyStatusMetaItems(strategyWorkspace)} />
            <Typography.Text strong data-contract="factor id / factor name weight/role factor analysis">使用因子</Typography.Text>
            <List
              className="qto-detail-list"
              dataSource={strategyWorkspace.factors}
              locale={{ emptyText: <CompactEmpty>暂无使用因子</CompactEmpty> }}
              renderItem={(factor) => (
                <List.Item className="qto-detail-list-row qto-detail-compact-row" data-contract="detail relation compact single-line row">
                  <div className="qto-detail-compact-line">
                    <span className="qto-detail-compact-main">
                      <strong>{factor.name}</strong>
                      <small>{factorUsageSummary(strategyWorkspace.strategy, factor)}</small>
                    </span>
                    <StatusTag status={factor.status} />
                  </div>
                </List.Item>
              )}
            />
            <OptionalDetailCollapse items={strategyAdvancedCollapseItems(strategyWorkspace)} />
          </Space>
        ) : null}
      </Drawer>
    </>
  );
}

function DetailHeader({ title, description, children }: { title: string; description?: string | null; children?: ReactNode }) {
  return (
    <section className="qto-detail-header">
      <div>
        <Typography.Title level={4}>{title}</Typography.Title>
        {description ? <Typography.Text type="secondary">{description}</Typography.Text> : null}
      </div>
      {children ? <Space wrap size={[6, 6]}>{children}</Space> : null}
    </section>
  );
}

function DetailMeta({ children, tone }: { children: ReactNode; tone?: "danger" }) {
  return <span className={tone === "danger" ? "qto-detail-meta-item qto-detail-meta-item-danger" : "qto-detail-meta-item"}>{children}</span>;
}

function DetailInlineMeta({ items }: { items: string[] }) {
  if (!items.length) return null;
  return (
    <div className="qto-detail-inline-meta" data-contract="detail inline metadata no boxed grid; detail optional metadata only renders when present">
      {items.map((item) => <span key={item}>{item}</span>)}
    </div>
  );
}

function OptionalDetailCollapse({ items }: { items: Array<{ key: string; label: string; children: ReactNode }> }) {
  return items.length ? <Collapse size="small" items={items} /> : null;
}

function InlineNotice({ title, children, tone }: { title: string; children: ReactNode; tone: "error" | "warning" }) {
  return (
    <div className={`qto-inline-notice qto-inline-notice-${tone}`} data-contract="compact inline notice no heavy alert">
      <span className="qto-inline-notice-dot" />
      <div>
        <Typography.Text strong>{title}</Typography.Text>
        <Typography.Text type="secondary">{children}</Typography.Text>
      </div>
    </div>
  );
}

function isLiveRelatedApproval(row: ApprovalRequest) {
  return row.request_type.toLowerCase().includes("live") || row.target_type.toLowerCase().includes("live");
}

function approvalLockReason(row: ApprovalRequest) {
  const reason = row.policy_lock_reason ?? (isLiveRelatedApproval(row) ? LIVE_APPROVAL_LOCK_FALLBACK_REASON : "后端策略限制");
  return formatApprovalLockReason(reason);
}

function formatApprovalLockReason(reason: string) {
  return approvalPolicyReasonLabel(reason) ?? reason;
}

function approvalDetailMetaItems(row: ApprovalRequest) {
  return [
    `请求类型 ${approvalRequestTypeLabel(row.request_type)}`,
    `目标 ${approvalTargetTypeLabel(row.target_type)}`,
    approvalTargetSummary(row),
    row.policy_lock_reason ? `策略限制 ${formatApprovalLockReason(row.policy_lock_reason)}` : null,
  ].filter(Boolean) as string[];
}

function approvalTargetSummary(row: ApprovalRequest) {
  return row.target_id ? `对象 ${readableIdentifier(row.target_id)}` : null;
}

function approvalCollapseItems(row: ApprovalRequest) {
  const items = [{
    key: "request",
    label: "请求详情",
    children: <DetailInlineMeta items={approvalDetailMetaItems(row)} />,
  }];
  if (hasObjectEntries(row.risk_summary)) {
    items.push({
      key: "risk",
      label: "风险摘要",
      children: <DetailMetaList items={objectSummaryItems(row.risk_summary)} empty="暂无风险摘要" contract="approval risk summary renders compact metadata no raw json" />,
    });
  }
  return items;
}

function DetailTagSection({ title, items, empty, hideWhenEmpty = false, contract }: { title: string; items: string[]; empty: string; hideWhenEmpty?: boolean; contract?: string }) {
  if (!items.length && hideWhenEmpty) return null;
  return (
    <section className="qto-detail-tag-section" data-contract={contract}>
      <Typography.Text strong>{title}</Typography.Text>
      <DetailMetaList items={items} empty={empty} />
    </section>
  );
}

function DetailMetaList({ items, empty, contract }: { items: string[]; empty: string; contract?: string }) {
  return (
    <div className="qto-detail-meta-list" data-contract={contract ?? "detail metadata no tag stack"}>
      {items.length ? items.map((item) => <DetailMeta key={item}>{item}</DetailMeta>) : <CompactEmpty>{empty}</CompactEmpty>}
    </div>
  );
}

function pipelineDetailMetaItems(item: ResearchPipelineItem) {
  return [
    linkedObjectSummary("策略", item.linked_strategy_id),
    item.owner_agent ? `智能体 ${item.owner_agent}` : null,
    linkedObjectSummary("回测", item.latest_backtest_id),
    item.risk_verdict ? `风控 ${formatStatusLabel(item.risk_verdict)}` : null,
    item.approval_status ? `审批 ${formatStatusLabel(item.approval_status)}` : null,
    formatDisplayDate(item.updated_at),
  ].filter(Boolean) as string[];
}

function linkedObjectSummary(label: string, id: string | null | undefined) {
  return id ? `${label} ${readableIdentifier(id)}` : null;
}

function pipelineActionItems(actions: string[]) {
  return actions.map((item) => pipelineActionLabel(item)).filter(Boolean) as string[];
}

function pipelineStageLabel(stage: string) {
  const labels: Record<string, string> = {
    idea: "Idea",
    "data-prep": "数据准备",
    researching: "研究中",
    "ready-backtest": "待回测",
    "backtest-complete": "回测完成",
    "ready-risk": "待风控",
    "waiting-approval": "待审批",
    "paper-candidate": "Paper Candidate",
    archived: "已归档",
  };
  return labels[stage] ?? stage.replace(/-/g, " ");
}

function strategyStatusMetaItems(workspace: StrategyWorkspace) {
  const card = workspace.card;
  const liveStatus = card?.live_trading_status ?? "locked";
  const currentStatus = card?.current_status && card.current_status !== workspace.strategy.status
    ? `当前 ${formatStatusLabel(card.current_status)}`
    : null;
  return [
    card?.paper_trading_status && !["not_started", "none"].includes(card.paper_trading_status) ? `Paper ${formatStatusLabel(card.paper_trading_status)}` : null,
    `Live ${formatStatusLabel(liveStatus)}`,
    card?.approval_status && card.approval_status !== "none" ? `审批 ${formatStatusLabel(card.approval_status)}` : null,
    currentStatus,
  ].filter(Boolean) as string[];
}

function MetricSummary({ metrics, keys }: { metrics: Record<string, unknown>; keys: string[] }) {
  const metricItems = keys.map((key) => formatMetricSummaryItem(key, metrics?.[key])).filter(Boolean);
  return metricItems.length ? (
    <div className="qto-detail-summary" data-contract="detail summary lightweight text line no summary pills">
      {metricItems.map((item) => <span key={item}>{item}</span>)}
    </div>
  ) : null;
}

function formatMetricSummaryItem(key: string, value: unknown) {
  if (value === undefined || value === null || value === "") return null;
  if (typeof value === "number") return `${metricDisplayLabel(key)}: ${value.toFixed(2)}`;
  return `${metricDisplayLabel(key)}: ${value}`;
}

function metricDisplayLabel(key: string) {
  const labels: Record<string, string> = {
    cagr: "CAGR",
    max_drawdown: "max drawdown",
    rank_ic: "Rank IC",
    sharpe: "Sharpe",
    sortino: "Sortino",
    turnover: "turnover",
    volatility: "volatility",
    win_rate: "win rate",
  };
  return labels[key] ?? key.replace(/_/g, " ");
}

function factorAdvancedCollapseItems(factor: FactorSpec) {
  const items = [];
  if (factor.formula?.trim()) {
    items.push({
      key: "formula",
      label: "计算逻辑",
      children: <Typography.Text className="qto-detail-code">{factor.formula}</Typography.Text>,
    });
  }
  if (factor.input_fields.length) {
    items.push({
      key: "inputs",
      label: "数据输入",
      children: <DetailMetaList items={factor.input_fields} empty="暂无输入字段" contract="factor detail optional inputs render only when populated; factor formula and inputs live in optional collapse" />,
    });
  }
  if (hasObjectEntries(factor.metrics)) {
    items.push({
      key: "metrics",
      label: "指标详情",
      children: <DetailMetaList items={metricDetailItems(factor.metrics)} empty="暂无指标" contract="factor metrics render as compact metadata no raw json" />,
    });
  }
  return items;
}

function strategyAdvancedCollapseItems(workspace: StrategyWorkspace) {
  const items = [];
  if (hasObjectEntries(workspace.strategy.signal_logic)) {
    items.push({
      key: "logic",
      label: "策略逻辑",
      children: <DetailMetaList items={objectSummaryItems(workspace.strategy.signal_logic)} empty="暂无策略逻辑" contract="strategy logic renders compact metadata no raw json" />,
    });
  }
  if (hasStrategyAuditData(workspace)) {
    items.push({
      key: "audit",
      label: "关联记录",
      children: <DetailMetaList items={strategyAuditSummaryItems(workspace)} empty="暂无关联记录" contract="strategy audit records render compact summary no raw workspace json" />,
    });
  }
  return items;
}

function hasObjectEntries(value: Record<string, unknown> | undefined | null) {
  return Boolean(value && Object.keys(value).length);
}

function metricDetailItems(metrics: Record<string, unknown>) {
  return Object.entries(metrics).map(([key, value]) => formatMetricSummaryItem(key, value)).filter(Boolean) as string[];
}

function objectSummaryItems(value: Record<string, unknown> | undefined | null) {
  return Object.entries(value ?? {})
    .map(([key, item]) => {
      const summary = summarizeObjectValue(item);
      return summary ? `${metricDisplayLabel(key)}: ${summary}` : null;
    })
    .filter(Boolean) as string[];
}

function summarizeObjectValue(value: unknown) {
  if (value === undefined || value === null || value === "") return null;
  if (typeof value === "number") return Number.isInteger(value) ? String(value) : value.toFixed(2);
  if (typeof value === "boolean") return value ? "已启用" : "未启用";
  if (typeof value === "string") return value;
  if (Array.isArray(value)) return value.length ? `${value.length} 项` : null;
  if (typeof value === "object") {
    const count = Object.keys(value).length;
    return count ? `${count} 项` : null;
  }
  return String(value);
}

function strategyAuditSummaryItems(workspace: StrategyWorkspace) {
  return [
    workspace.backtests.length ? `回测 ${workspace.backtests.length} 条` : null,
    latestStatusItem("最近回测", workspace.backtests),
    workspace.risk_reviews.length ? `风控 ${workspace.risk_reviews.length} 条` : null,
    latestStatusItem("最近风控", workspace.risk_reviews, "verdict"),
    workspace.approvals.length ? `审批 ${workspace.approvals.length} 条` : null,
    latestStatusItem("最近审批", workspace.approvals),
    workspace.workflows.length ? `工作流 ${workspace.workflows.length} 条` : null,
    latestStatusItem("最近工作流", workspace.workflows),
    workspace.artifacts.length ? `产物 ${workspace.artifacts.length} 个` : null,
  ].filter(Boolean) as string[];
}

function latestStatusItem(label: string, rows: Array<{ status?: unknown; verdict?: unknown }>, statusKey: "status" | "verdict" = "status") {
  const status = rows[0]?.[statusKey];
  return typeof status === "string" && status.trim() ? `${label} ${formatStatusLabel(status)}` : null;
}

function hasStrategyAuditData(workspace: StrategyWorkspace) {
  return [
    workspace.backtests,
    workspace.risk_reviews,
    workspace.approvals,
    workspace.workflows,
    workspace.artifacts,
  ].some((items) => items.length > 0);
}

function factorUsageSummary(strategy: StrategySpec, factor: FactorSpec) {
  return [
    `ID ${factor.id}`,
    factorWeightOrRole(strategy, factor),
    formatDisplayDate(factor.updated_at, "分析"),
  ].filter(Boolean).join(" · ");
}

function factorWeightOrRole(strategy: StrategySpec, factor: FactorSpec) {
  const value = strategy.signal_logic?.weights?.[factor.id] ?? strategy.signal_logic?.roles?.[factor.id];
  return value === undefined || value === null || value === "" ? null : `权重/角色 ${value}`;
}

function strategyRelationSummary(strategy: StrategySpec) {
  return [
    strategy.universe || null,
    strategy.factors?.length ? `${strategy.factors.length} 个因子` : null,
  ].filter(Boolean).join(" · ");
}
