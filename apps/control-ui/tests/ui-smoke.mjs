import assert from "node:assert/strict";
import { existsSync, readdirSync, readFileSync } from "node:fs";
import { dirname, extname, join, relative } from "node:path";
import { fileURLToPath } from "node:url";

const root = dirname(fileURLToPath(new URL("../package.json", import.meta.url)));
const srcRoot = join(root, "src");
const routes = readFileSync(join(srcRoot, "routes.tsx"), "utf8");
const appShell = readFileSync(join(srcRoot, "layout/AppShell.tsx"), "utf8");
const appSource = readFileSync(join(srcRoot, "App.tsx"), "utf8");
const apiClient = readFileSync(join(srcRoot, "api/client.ts"), "utf8");
const apiTypes = readFileSync(join(srcRoot, "api/types.ts"), "utf8");
const factorsStrategies = readFileSync(join(srcRoot, "pages/research/FactorsStrategiesPage.tsx"), "utf8");
const dashboardPage = readFileSync(join(srcRoot, "pages/dashboard/DashboardPage.tsx"), "utf8");
const researchPipelinePage = readFileSync(join(srcRoot, "pages/research/ResearchPipelinePage.tsx"), "utf8");
const experimentsPage = readFileSync(join(srcRoot, "pages/research/ExperimentsPage.tsx"), "utf8");
const reportsPage = readFileSync(join(srcRoot, "pages/research/ReportsPage.tsx"), "utf8");
const agentCanvasPage = readFileSync(join(srcRoot, "pages/agents/AgentCanvasPage.tsx"), "utf8");
const agentConfigDrawer = readFileSync(join(srcRoot, "pages/agents/AgentConfigDrawer.tsx"), "utf8");
const displayLabels = readFileSync(join(srcRoot, "displayLabels.ts"), "utf8");
const statusTag = readFileSync(join(srcRoot, "components/StatusTag.tsx"), "utf8");
const packageJson = JSON.parse(readFileSync(join(root, "package.json"), "utf8"));
const source = readSourceTree(srcRoot);

function includes(text, needle, label) {
  assert.ok(text.includes(needle), `${label}: missing ${needle}`);
}

function excludes(text, needle, label) {
  assert.ok(!text.includes(needle), `${label}: unexpected ${needle}`);
}

function matches(text, pattern, label) {
  assert.ok(pattern.test(text), `${label}: missing ${pattern}`);
}

function extractArray(text, name) {
  const match = text.match(new RegExp(`export const ${name}\\b[\\s\\S]*?=\\s*\\[([\\s\\S]*?)\\];`));
  assert.ok(match, `${name}: missing exported array`);
  return match[1];
}

function labelsFromArray(body) {
  return [...body.matchAll(/label:\s*"([^"]+)"/g)].map((match) => match[1]);
}

function assertExactLabels(body, expected, label) {
  assert.deepEqual(labelsFromArray(body), expected, `${label}: labels changed`);
}

function readSourceTree(dir) {
  const parts = [];
  for (const entry of readdirSync(dir, { withFileTypes: true })) {
    const path = join(dir, entry.name);
    if (entry.isDirectory()) {
      parts.push(readSourceTree(path));
    } else if ([".ts", ".tsx", ".css"].includes(extname(entry.name))) {
      parts.push(`\n/* ${relative(srcRoot, path)} */\n${readFileSync(path, "utf8")}`);
    }
  }
  return parts.join("\n");
}

const primaryNav = extractArray(routes, "PRIMARY_NAV");
assertExactLabels(primaryNav, ["工作台", "策略研究", "智能体管理"], "primary navigation");
for (const oldLabel of ["Agent Console", "Connect Center", "Approval Center", "Audit Log", "Command", "Governance", "Platform"]) {
  excludes(primaryNav, oldLabel, "primary navigation");
}

const researchNav = extractArray(routes, "RESEARCH_NAV");
assertExactLabels(researchNav, ["研究管线", "因子和策略", "实验与回测", "研究报告"], "research navigation");

for (const marker of [
  'dashboard: "/dashboard"',
  '"research-pipeline": "/research/pipeline"',
  '"factors-strategies": "/research/factors-strategies"',
  'experiments: "/research/experiments"',
  'reports: "/research/reports"',
  '"agent-canvas": "/agents/canvas"',
  '"/": "/dashboard"',
  '"/overview": "/dashboard"',
  '"/agent-console": "/agents/canvas"',
  '"/connections": "/agents/canvas?panel=connections"',
  '"/workflows": "/agents/canvas?panel=workflows"',
  '"/audit-log": "/agents/canvas?panel=audit"',
  '"/settings": "/agents/canvas?panel=settings"',
  '"/external-workspaces": "/agents/canvas?panel=tools"',
  '"/research-lab": "/research/pipeline"',
  '"/factor-library": "/research/factors-strategies?tab=factors"',
  '"/strategy-registry": "/research/factors-strategies?tab=strategies"',
  '"/backtest-center": "/research/experiments"',
]) {
  includes(routes, marker, "route and legacy redirect contract");
}

for (const marker of [
  "PRIMARY_NAV.map",
  "RESEARCH_NAV.map",
  "primaryRouteFor(route)",
  'aria-label="策略研究二级导航"',
  "qto-subnav",
]) {
  includes(appShell, marker, "AppShell navigation contract");
}

for (const staleMarker of ["NAV_GROUPS", "NAV_MENU_ITEMS", "qto-mobile-group-menu", "qto-mobile-subnav"]) {
  excludes(source, staleMarker, "stale grouped navigation contract");
}
matches(source, /\.qto-page-heading\s*\{[^}]*gap:\s*10px;[^}]*justify-content:\s*space-between;/, "global compact page heading layout");
matches(source, /\.qto-page-heading h2\s*\{[^}]*font-size:\s*24px;[^}]*line-height:\s*1\.14;/, "global compact page heading scale");
excludes(source, "font-size: 28px;", "global page heading must not use oversized hero-like title scale");
includes(source, "global low-emphasis empty state text", "global empty state emphasis contract");
matches(source, /\.qto-compact-empty\s*\{[^}]*display:\s*inline-flex;[^}]*font-weight:\s*500;[^}]*line-height:\s*1\.45;/, "global compact empty state low emphasis style");

for (const marker of ['activeTab: "factors" | "strategies"', 'label: "因子库"', 'label: "策略库"', "onTabChange"]) {
  includes(factorsStrategies, marker, "factors and strategies tabs contract");
}
for (const marker of ["qto-library-section", "qto-library-list", "qto-library-row", "qto-library-list-line", "qto-library-list-main", "qto-library-summary", "qto-library-status-line", "qto-library-action", "factorInlineSummary", "factorListSummary", "factorPriorityAction", "strategyListSummary", "strategyPriorityAction", "strategyLifecycleItems", "formatLifecycleStatus", "libraryAttentionStatus", "hasMetricValue", "const action = factorPriorityAction(row)", "const action = strategyPriorityAction(row, risk)", "factors strategies list shows actionable research priority only when meaningful", "补充因子分析", "生成分析报告", "补充使用因子", "处理风控 ${formatLifecycleStatus(risk.verdict)}", "处理审批 ${formatLifecycleStatus(approval)}", "检查 Paper ${formatLifecycleStatus(paper)}", "检查 Live ${formatLifecycleStatus(live)}", "const status = libraryAttentionStatus(row.status)", "const status = lifecycleItems.length ? null : libraryAttentionStatus(row.status)", "factors strategies list status pill is attention-only", "factors strategies compact single-line row no stacked metadata", "factors strategies compact one-line list summary", "strategy lifecycle compact attention-only status line", "lifecycleItems.length ?", "metricSummary", "factors strategies summary only shows available metrics", "factors strategies summary renders only when populated", "const summary = factorInlineSummary(row)", "const summary = strategyListSummary(row)", "row.factors?.length ?", "个因子", "风控 ${formatLifecycleStatus(risk.verdict)}", "审批 ${formatLifecycleStatus(approval)}", "Paper ${formatLifecycleStatus(paper)}", "Live ${formatLifecycleStatus(live)}", "待处理", "运行中", "待复核", "role=\"button\"", "tabIndex={0}", "library row opens detail no repeated button", "factors strategies lightweight section no card wrapper"]) {
  includes(factorsStrategies + source, marker, "reduced-density factors and strategies list contract");
}
excludes(factorsStrategies + appSource, "公式已定义", "factor formula summary must show specific content instead of generic placeholder copy");
for (const staleMarker of ["factorFormulaSummary", "const value = formula?.trim()", "value.length > 48", "value.slice(0, 48)", "公式 ${"]) {
  excludes(factorsStrategies, staleMarker, "factor list summary must keep formula in the detail drawer");
}
for (const staleMarker of ["latestBacktest", "metricSummary(\"Sharpe\"", "metricSummary(\"max DD\"", "strategyListSummary(row, backtest)", "backtests: BacktestRun[]"]) {
  excludes(factorsStrategies, staleMarker, "strategy list summary must keep backtest metrics in experiments and detail context");
}
excludes(factorsStrategies + source, "qto-library-meta", "factors and strategies list must use one-line summary instead of dense meta chips");
for (const staleMarker of ["qto-library-main", "qto-library-title", "qto-library-description"]) {
  excludes(factorsStrategies + source, staleMarker, "factors and strategies lists must not use stacked title/description/summary rows");
}
for (const staleMarker of ["Table", 'title: "输入与表现"', 'title: "验证状态"', 'title: "输入与周期"', 'title: "最新回测"', 'title: "风控/审批"', 'title: "交易状态"']) {
  excludes(factorsStrategies, staleMarker, "factors and strategies list must not split status into extra columns");
}
excludes(factorsStrategies, "Card", "factors and strategies page must not wrap the list in a card");
excludes(factorsStrategies, 'actions={[<Button key="detail"', "factors and strategies rows must not repeat detail buttons");
for (const staleMarker of ['className="qto-library-status"', "<Tag>{row.card?.approval_status", "<Tag>{row.card?.paper_trading_status", "<Tag color={row.card?.live_trading_status"]) {
  excludes(factorsStrategies, staleMarker, "strategy lifecycle status must not render as repeated tags");
}
for (const staleMarker of ["strategyLifecycleLine", "risk ${risk?.verdict ?? \"missing\"}", "live ${strategy.card?.live_trading_status ?? \"locked\"}", "风控 ${risk.verdict}", "审批 ${approval}", "Paper ${paper}", "Live ${live}", "return formula?.trim() || null"]) {
  excludes(factorsStrategies, staleMarker, "strategy lifecycle list line must not repeat default statuses");
}
for (const staleMarker of ["no inputs", 'row.lookback_window ?? "-"', 'row.factors?.length ?? 0', 'IC ${metric(row.metrics, "ic")}', 'Sharpe ${metric(backtest?.metrics, "sharpe")}']) {
  excludes(factorsStrategies, staleMarker, "factors and strategies summaries must not render missing data placeholders");
}
for (const staleMarker of ["row.lookback_window !== undefined", "row.rebalance_frequency || null", "fieldSummary(row.input_fields)", "function fieldSummary"]) {
  excludes(factorsStrategies, staleMarker, "factor list summary must keep operational fields in the detail drawer");
}
for (const staleMarker of ["`${row.factors.length} factors`", "risk ${risk.verdict}", "approval ${approval}", "paper ${paper}", "live ${live}"]) {
  excludes(factorsStrategies, staleMarker, "factors and strategies list must not expose raw English lifecycle prefixes");
}
for (const staleMarker of ["<StatusTag status={row.status}", "const status = row.status"]) {
  excludes(factorsStrategies, staleMarker, "factors and strategies list must not show normal status pills");
}

assert.ok(packageJson.dependencies?.["@xyflow/react"], "Agent Canvas dependency: missing @xyflow/react");
for (const marker of [
  "AgentGraph",
  "AgentNodeData",
  "AgentEdgeData",
  "nodes:",
  "edges:",
  "status:",
  "tool_refs:",
  "permissions:",
  "risk_limits:",
]) {
  includes(apiTypes, marker, "Agent Canvas type contract");
}
for (const marker of [
  'from "@xyflow/react"',
  "ReactFlow",
  "type Edge",
  "type Node",
  "nodes",
  "edges",
  "AgentConfigDrawer",
  "qto-canvas-toolbar",
  "qto-agent-node-status",
  "状态",
  "工具",
  "权限",
  "运行",
  "工具与连接",
  "权限与风控",
  "secret policy",
]) {
  includes(source, marker, "Agent Canvas UI contract");
}
for (const marker of ["STATUS_LABELS", "formatStatusLabel", 'healthy: "正常"', 'pending: "待处理"', 'requires_review: "待复核"', 'not_started: "未开始"', 'cancel_requested: "取消中"', 'result_pending: "结果待回传"', 'blocked: "阻塞"', 'unavailable: "不可用"', "qto-status-pill", "qto-status-dot", "qto-status-pill-amber", "data-status={normalized}", "{formatStatusLabel(status)}"]) {
  includes(statusTag + source, marker, "global lightweight status contract");
}
includes(statusTag, "global low-emphasis status text with compact dot", "global status tag low-emphasis contract");
matches(source, /\.qto-status-pill\s*\{[^}]*gap:\s*5px;[^}]*font-weight:\s*600;[^}]*line-height:\s*1\.35;/, "global status pill low-emphasis typography");
matches(source, /\.qto-status-dot\s*\{[^}]*width:\s*6px;[^}]*height:\s*6px;[^}]*box-shadow:\s*0 0 0 2px/, "global status dot compact visual weight");
excludes(source, "box-shadow: 0 0 0 3px color-mix(in srgb, currentColor 13%, transparent);", "global status dot must not use oversized halo");
excludes(statusTag, '{status ?? "unknown"}', "global status tag must not render raw backend enum values");
for (const staleMarker of ['import { Tag } from "antd"', "<Tag"]) {
  excludes(statusTag, staleMarker, "global status must not render as Ant Tag");
}
for (const marker of ["function InlineNotice", "qto-inline-notice", "qto-inline-notice-error", "qto-inline-notice-warning", "compact inline notice no heavy alert"]) {
  includes(appSource + source, marker, "global lightweight notice contract");
}
for (const staleMarker of ['import { Alert', "<Alert"]) {
  excludes(source, staleMarker, "control UI source must not use heavy Ant Alert blocks");
}
matches(source, /function ownerLinkedLabel[\s\S]*return id \? `\$\{label\} \$\{readableIdentifier\(id\)\}` : label;/, "global linked object labels must show a specific readable id");
excludes(source, "return id ? `${label}已关联` : label;", "global linked object labels must not use generic linked copy");
for (const marker of ["qto-canvas-primary-actions", "qto-canvas-toolbar-status", "agent canvas fixed stage toolbar primary action more menu no overlay", "agent canvas single view filter in fixed toolbar activity entry in action menu no bottom overlay", "agent canvas toolbar uses Chinese compact counts", "agent canvas toolbar hides zero running count", "canvasToolbarSummaryItems", "activeAgentRuns", "visibleAgents === totalAgents", "groupFlows ? `${groupFlows} 条流程` : null", "activeRuns ? `运行 ${activeRuns}` : null", "agentCanvasViewFilterLabel", "agentMatchesCanvasFilter", "视图 ${agentCanvasViewFilterLabel(viewFilter)}", "key: \"activity\"", "setActivityOpen(true)", "运行动态", "视图筛选", "viewFilter === \"attention\" ? \"✓ 待处理/异常\"", "fitViewOptions={{ padding: 0.12, minZoom: 0.36, maxZoom: 0.86 }}", "minZoom={0.34}", "onlyRenderVisibleElements", "elementsSelectable", "<Dropdown"]) {
  includes(agentCanvasPage + source, marker, "reduced-density agent canvas toolbar contract");
}
for (const marker of ["normalizeAgentPanelQuery", "defaultAgentForPanel", "handledPanelQuery", "new URLSearchParams(window.location.search).get(\"panel\")", "panel === \"workflows\" || panel === \"audit\"", "setActivityTab(panel === \"audit\" ? \"logs\" : \"workflows\")", "panel === \"connections\" || panel === \"tools\" ? \"tools\" : \"overview\"", "initialTab={drawerInitialTab}", "initialTab?: string", "setActiveTab(initialTab ?? \"overview\")"]) {
  includes(agentCanvasPage + agentConfigDrawer, marker, "agent canvas legacy panel query opens matching drawer or activity tab");
}
for (const marker of ["visibleGroupIds", "agentsByGroup", "statusSummary: summarizeGroupStatus(visibleGroupAgents)", "agent canvas filtered view hides empty group lanes and recomputes group counts"]) {
  includes(agentCanvasPage + source, marker, "agent canvas filtered group context contract");
}
for (const marker of ["MiniMap", "qto-canvas-minimap", "minimapNodeColor", "agent canvas minimap provides large-canvas orientation without changing tool stack", "nodeColor={(node) => minimapNodeColor(node as AgentFlowNode)}", "nodeStrokeWidth={3}", "pannable", "zoomable", ".qto-canvas-workspace .react-flow__edge.selected path", ".react-flow__node-agent.selected .qto-agent-node"]) {
  includes(agentCanvasPage + source, marker, "agent canvas interaction feedback and minimap contract");
}
for (const marker of ["agentStageLabel", "STAGE_ORDER", "sortAgentGroups", "orderedGroups", "agentStageIndex", "stageIndex: agentStageIndex(group.id)", "agentStageLabel(group.id, group.label)", "agentStageLabel(sourceGroup?.id ?? item.source, sourceGroup?.label)", "数据接入", "研究与策略", "回测与风控", "审批与执行", "监控与审计", "agent canvas stage lane header uses task phase labels", "agent group lane shows ordered stage index without changing backend group ids", "qto-agent-group-stage"]) {
  includes(agentCanvasPage + agentConfigDrawer + source, marker, "agent group labels must use localized display names without changing group ids");
}
for (const marker of ["agentDisplayName", "agentRoleLabel", "agentDisplayName(data.name)", "agentRoleLabel(data.name, data.role)", "agentDisplayName(agent.name)", "agentRoleLabel(selectedAgent.name, selectedAgent.role)", '\"Research Agent\": \"研究智能体\"', '\"Execution Agent\": \"执行智能体\"', '\"Research Agent\": \"研究假设、笔记与想法扩展\"', '\"Execution Agent\": \"Paper 交易提案与 Live 锁定流程\"']) {
  includes(agentCanvasPage + agentConfigDrawer + displayLabels, marker, "default agent names and roles must render as localized UI labels while preserving stored names");
}
for (const marker of ["AGENT_TEMPLATE_OPTIONS", 'value: "Research Agent", label: "研究智能体"', 'value: "Blank Agent", label: "空白智能体"', "new agent template labels localized while preserving agent template values", "自定义智能体", "例如 研究助理"]) {
  includes(agentCanvasPage + agentConfigDrawer, marker, "new agent and agent config modals must localize visible template and placeholder copy");
}
for (const staleMarker of ["AGENT_TEMPLATES.map((template) => ({ value: template, label: template }))", '"Custom agent"', 'placeholder="例如 Research Agent"']) {
  excludes(agentCanvasPage + agentConfigDrawer, staleMarker, "new agent and agent config modals must not expose English template/default copy as visible UI");
}
for (const staleMarker of ["Checkbox", "<Checkbox", "异常</Checkbox>", "运行中</Checkbox>"]) {
  excludes(agentCanvasPage, staleMarker, "agent canvas filters must live in a compact dropdown");
}
for (const marker of ["qto-activity-tabs", "agent canvas activity modal tabs no three-column log wall", "qto-activity-list", "agent canvas activity modal compact tab list", "ActivityList", "ActivityRowItem", "activityAttentionStatus(row.status)", "agent canvas activity status pill is attention-only", "agentRunActivityRows", "workflowActivityRows", "agentLogActivityRows", "agentRunActivityLabel", "agentRunActivityDetail", "workflowActivityLabel", "activityTypeLabel", "readableActivityType", "activityTabLabel", "activityTabLabel(\"任务\", agentRuns.length)", "activityTabLabel(\"工作流\", workflows.length)", "return count ? `${label} ${count}` : label", "<CompactEmpty>{emptyText}</CompactEmpty>", "研究工作流", "回测工作流", "工作流 ${readableIdentifier(run.workflow_id)}", "暂无工作流", "ownerLinkedLabel(workflow.owner_type, workflow.owner_id)"]) {
  includes(agentCanvasPage + source, marker, "agent canvas activity modal must use compact tabs");
}
for (const staleMarker of ["Workflow ${workflows.length}", "label: `任务 ${agentRuns.length}`", "label: `工作流 ${workflows.length}`", "<Typography.Text type=\"secondary\">{emptyText}</Typography.Text>", "暂无 workflow", "保存后出现在画布中，工具和权限在 agent 配置里继续设置。"]) {
  excludes(agentCanvasPage, staleMarker, "agent canvas modals must not keep mixed English labels or low-value helper text");
}
for (const staleMarker of ["label: run.id", "detail: run.workflow_id ?? run.task_type", "label: workflow.workflow_type"]) {
  excludes(agentCanvasPage, staleMarker, "agent canvas activity rows must not expose raw run or workflow identifiers as primary copy");
}
excludes(agentCanvasPage, "已关联工作流", "agent canvas activity detail must show the concrete workflow id");
excludes(agentCanvasPage, "<StatusTag status={row.status}", "agent canvas activity rows must not show normal completed status pills");
for (const marker of ["formatVisibleAgentAction", "isSeededDefaultAgentAction", 'filter((agent) => Boolean(formatVisibleAgentAction(agent.last_action)))', 'detail: formatVisibleAgentAction(agent.last_action) ?? ""', 'return action.toLowerCase() === "seeded default agent"']) {
  includes(agentCanvasPage, marker, "agent canvas recent logs and node tasks must hide seeded default noise");
}
excludes(agentCanvasPage, 'agent.last_action ?? "暂无动作"', "agent canvas recent logs must not synthesize empty action rows");
excludes(agentCanvasPage, "agent.last_action?.trim() || \"空闲\"", "agent canvas node task must not render seeded default actions");
for (const marker of ["const task = formatAgentTask(data)", "agent node hides idle task line", "{task ? (", "formatVisibleAgentAction(agent.last_action);"]) {
  includes(agentCanvasPage, marker, "agent canvas node task line must render only when useful");
}
excludes(agentCanvasPage, "formatVisibleAgentAction(agent.last_action) || \"空闲\"", "agent canvas node task line must not repeat idle state text");
for (const marker of ["agent node compact summary card no detail stack", "qto-agent-node-task", "formatAgentTask", "formatAgentStatus", 'idle: "空闲"', 'waiting_approval: "待审批"', "agentNodeAttentionItems", "summarizeToolAttention", "agent node footer attention-only no normal tool or permission counts", "工具异常", "无权限", "需人工"]) {
  includes(agentCanvasPage + source, marker, "agent canvas nodes must stay as compact summary cards");
}
for (const marker of ["agent node status text visible not color-only", "<StatusTag status={data.status} />", "qto-agent-node-status", "border-top-color: #2563eb"]) {
  includes(agentCanvasPage + source, marker, "agent canvas status must be text-visible and still distinguish running from idle");
}
excludes(agentCanvasPage + source, "qto-agent-status-dot-blue", "agent canvas status must not rely on color-only node dots");
for (const staleMarker of ["qto-canvas-toolbar-left", "qto-canvas-toolbar-right", "group flows</Tag>", "agent runs</Tag>"]) {
  excludes(agentCanvasPage + source, staleMarker, "agent canvas toolbar must not expose dense action/status clusters");
}
excludes(agentCanvasPage + source, "qto-activity-modal-grid", "agent canvas activity modal must not render a three-column log wall");
for (const staleMarker of ["qto-agent-node-meta", "qto-agent-node-section", "qto-agent-node-alert", "permissions</span>"]) {
  excludes(agentCanvasPage, staleMarker, "agent canvas node cards must not expose stacked detail fields");
}
for (const staleMarker of ["运行 {agentRuns.length}", "权限 {activePermissions}", "`工具 ${tools.length}`", 'return "无工具"']) {
  excludes(agentCanvasPage, staleMarker, "agent canvas must hide normal zero/count noise from the main canvas");
}
for (const marker of ["agent group lane uses Chinese compact agent count", "个智能体", "个异常", "个待处理", "个运行中"]) {
  includes(agentCanvasPage + source, marker, "agent group lanes must use Chinese compact attention summaries");
}
for (const staleMarker of ['"empty group"', " blocked / failed", " waiting / locked", " running`", " agents</span>", " agents ·", " flows</span>"]) {
  excludes(agentCanvasPage, staleMarker, "agent canvas must not render English default group or count copy");
}
for (const staleMarker of ["qto-canvas-activity-strip", "qto-canvas-activity-pill", "agent canvas compact activity strip", "agent canvas activity strip uses compact Chinese counts", "runs ·", "workflow {workflows.length}"]) {
  excludes(agentCanvasPage + source, staleMarker, "agent canvas activity entry must stay in action menu without bottom overlay or English plural labels");
}
excludes(agentCanvasPage, '<Button size="small" onClick={() => setActivityOpen(true)}>运行动态</Button>', "agent canvas activity entry must not render as a persistent toolbar button");
for (const marker of ["qto-detail-header", "qto-detail-code", "qto-detail-inline-meta", "detail inline metadata no boxed grid", "detail optional metadata only renders when present", "function DetailInlineMeta", "function DetailMetaList", "OptionalDetailCollapse", "factorAdvancedCollapseItems", "strategyAdvancedCollapseItems", "hasStrategyAuditData", "hasObjectEntries", "factor detail optional inputs render only when populated", "factor formula and inputs live in optional collapse", "factor metrics render as compact metadata no raw json", "strategy logic renders compact metadata no raw json", "strategy audit records render compact summary no raw workspace json", "approval risk summary renders compact metadata no raw json", "metricDetailItems", "objectSummaryItems", "summarizeObjectValue", "const summary = summarizeObjectValue(item)", "return summary ? `${metricDisplayLabel(key)}: ${summary}` : null", "strategyAuditSummaryItems", "latestStatusItem", "label: \"计算逻辑\"", "label: \"数据输入\"", "label: \"指标详情\"", "label: \"关联记录\"", "个输入", "pipelineDetailMetaItems", "linkedObjectSummary(\"策略\", item.linked_strategy_id)", "linkedObjectSummary(\"回测\", item.latest_backtest_id)", "function linkedObjectSummary", "${label} ${readableIdentifier(id)}", "pipelineActionItems(selectedPipelineItem.next_actions)", "pipelineActionLabel(selectedPipelineItem.latest_action)", "pipelineStageLabel(selectedPipelineItem.stage)", "formatDisplayDate(item.updated_at)", "formatDisplayDate(factor.updated_at, \"分析\")", "approvalTargetSummary(row)", "对象 ${readableIdentifier(row.target_id)}", "观察窗口", "strategyStatusMetaItems", "approvalRequestTypeLabel", "approvalTargetTypeLabel", "approvalLockReason", "formatApprovalLockReason", "LIVE_APPROVAL_LOCK_FALLBACK_REASON", "formatStatusLabel(item.approval_status)", "Live ${formatStatusLabel(liveStatus)}", "metricDisplayLabel", "后端请求失败", "Live 交易已按 MVP 策略锁定", "填写审批说明", "创建研究想法", "label=\"标的池\"", "label=\"资产类别\"", "label=\"标签\"", "factor id / factor name"]) {
  includes(source, marker, "reduced-density detail UI contract");
}
excludes(appSource, 'return "已配置"', "detail object summaries must hide empty metadata values");
excludes(appSource, "对象已关联", "approval details must show a specific target object instead of generic linked copy");
for (const staleMarker of ["策略已关联", "回测已关联"]) {
  excludes(appSource, staleMarker, "pipeline detail must show specific linked objects instead of generic linked copy");
}
for (const marker of ["qto-detail-list", "qto-detail-meta-line", "qto-detail-compact-row", "qto-detail-compact-line", "qto-detail-compact-main", "detail relation compact single-line row", "qto-detail-summary", "detail summary lightweight text line no summary pills", "formatMetricSummaryItem", "factorUsageSummary", "factorWeightOrRole", "strategyRelationSummary(strategy)", "权重/角色", "factor id / factor name weight/role factor analysis"]) {
  includes(appSource + source, marker, "reduced-density workspace detail list contract");
}
for (const marker of ["qto-detail-meta-list", "qto-detail-meta-item", "qto-detail-meta-item-danger", "function DetailMeta", "detail metadata no tag stack"]) {
  includes(appSource + source, marker, "detail metadata must render as lightweight text");
}
excludes(source, "Descriptions", "detail UI must not fall back to field-table descriptions");
for (const staleMarker of ["lookback unset", "rebalance unset", 'policy_lock_reason ?? "-"', 'linked_strategy_id ?? "-"', 'owner_agent ?? "-"', 'latest_backtest_id ?? "-"', 'approval_status ?? "-"', 'paper_trading_status ?? "not_started"', 'approval_status ?? "none"', "formatMetricValue", 'factor.updated_at ?? "-"']) {
  excludes(appSource, staleMarker, "detail drawers must not render unset or dash placeholders");
}
for (const staleMarker of ["因子表现、输入字段和策略使用情况。", "策略逻辑、因子使用和验证状态。"]) {
  excludes(appSource, staleMarker, "detail drawers must not render generic fallback descriptions");
}
for (const staleMarker of ['selectedPipelineItem.latest_action ?? "暂无最近动作"', '`${strategyWorkspace.factors.length} factors`', '`${strategy.factors?.length ?? 0} factors`', 'factor id: ${factor.id}', 'weight/role: ${value}', 'factor analysis: ${factor.updated_at}', 'live ${card?.live_trading_status ?? "locked"}']) {
  excludes(appSource, staleMarker, "detail drawers must not expose raw enum/default English detail labels");
}
for (const staleMarker of ['<DetailMeta>{selectedPipelineItem.stage}</DetailMeta>', '<DetailMeta>{selectedPipelineItem.updated_at}</DetailMeta>', "`策略 ${item.linked_strategy_id}`", "`回测 ${item.latest_backtest_id}`", "`目标 ${approvalTargetTypeLabel(row.target_type)}:${row.target_id}`", "`lookback ${factorWorkspace.factor.lookback_window}`"]) {
  excludes(appSource, staleMarker, "detail drawers must not expose raw stage, object ids, dates, or English detail labels");
}
for (const staleMarker of ["description={selectedPipelineItem.latest_action}", "items={selectedPipelineItem.next_actions}"]) {
  excludes(appSource, staleMarker, "research pipeline detail must format workflow actions before display");
}
for (const staleMarker of ['JsonBlock value={selectedPipelineItem}', 'label: "高级数据"']) {
  excludes(appSource, staleMarker, "research pipeline detail must not expose raw selected project payload");
}
for (const staleMarker of ['JsonBlock value={factor.metrics}', 'label: "高级指标"']) {
  excludes(appSource, staleMarker, "factor detail metrics must not expose raw metric JSON");
}
for (const staleMarker of ['JsonBlock value={workspace.strategy.signal_logic}', 'label: "高级记录"', "source_strategy:"]) {
  excludes(appSource, staleMarker, "strategy detail advanced sections must not expose raw workspace JSON");
}
excludes(appSource, "JsonBlock value={row.risk_summary}", "approval risk summary must not expose raw JSON");
for (const staleMarker of ["FastAPI request failed", '? "Live trading is locked by MVP policy" :', "human_comment 审批说明", "创建研究 idea", 'label="universe"', 'label="asset_class"', 'label="tags"']) {
  excludes(appSource + researchPipelinePage, staleMarker, "visible UI copy must not expose backend or form-field implementation names");
}
excludes(appSource, "Table", "workspace detail drawers must not use persistent tables");
excludes(appSource, "List.Item.Meta", "workspace detail drawers must use compact relation rows instead of stacked list metadata");
excludes(appSource, "<Tag", "workspace detail drawers must not render direct Ant tags");
for (const staleMarker of ["function DetailKeyValue", "qto-detail-kv-grid", "qto-detail-kv"]) {
  excludes(source, staleMarker, "detail drawers must not retain boxed key-value detail UI");
}
excludes(source, "qto-detail-block", "factor detail formula must not occupy a permanent top-level block");
for (const staleMarker of ["<Tag>factor id:", "<Tag>weight/role:", "<Tag>factor analysis:", "<Tag key={item}>"]) {
  excludes(appSource, staleMarker, "strategy factor detail metadata must not render as repeated tags");
}
for (const staleMarker of [
  '<DetailKeyValue label="关联策略">',
  '<DetailKeyValue label="关联 agent">',
  '<DetailKeyValue label="最新 backtest">',
  '<DetailKeyValue label="paper">',
  '<DetailKeyValue label="live">',
  '<DetailKeyValue label="当前状态">',
]) {
  excludes(appSource, staleMarker, "workspace detail status metadata must render inline instead of boxed key-value cards");
}
for (const marker of ["qto-run-section", "qto-run-toolbar", "qto-run-list", "qto-run-row", "qto-run-list-line", "qto-run-list-main", "experiments compact single-line run row no stacked metadata", "qto-run-summary", "qto-run-action-hint", "runTitle(row, strategies)", "runTitle(run, strategies)", "runSummary(row)", "runActionHint(row)", "function runActionHint", "isCompletedRunStatus(row.status)", "function isCompletedRunStatus", "experiments row shows next action hint without persistent action button", "等待回测完成", "复核 ${formatStatusLabel(row.status)}", "可对比并申请风控", "处理 ${formatStatusLabel(row.status)}", "function runAttentionStatus", "const status = runAttentionStatus(row.status)", "const status = runAttentionStatus(run.status)", "experiments status pill is attention-only", "function runTrackingLabel", "runArtifactSummary(run)", "experiments compare hides zero artifact count", "回测记录", "引擎 ${row.engine}", "datasetVersionLabel(row.dataset_version)", "function datasetVersionLabel", "数据 ${readableIdentifier(value.trim())}", "MLflow ${readableIdentifier(row.mlflow_run_id)}", "qto-run-metrics", "MetricLine", "const ROW_METRIC_KEYS = [\"sharpe\"]", "DETAIL_METRIC_KEYS", "keys={ROW_METRIC_KEYS}", "keys={DETAIL_METRIC_KEYS}", "experiments row metric line only shows primary metrics", "experiments compare modal shows full metric line", "metricItems.length ?", "formatMetricItem", "metricLabel(key)", "数据版本", "条记录", "例如 2026-06 因子数据", "MoreOutlined", "aria-label=\"回测操作\"", "aria-label=\"对比操作\"", "experiments icon-only action menu no persistent action text", "experiments compact metrics and implemented action menu only", "experiments compact metric line", "experiments compact metric line only shows available metrics", "experiments compact one-line run summary", "compare action lives in menu", "加入对比", "key: \"open-compare\"", "key: \"clear-compare\"", "打开对比", "清空选择", "experiments compare strip uses icon-only action menu no persistent text buttons", "qto-filter-select", "qto-run-filter-button", "experiments filters live in modal not toolbar", "experiments filter modal keeps filters off main toolbar", "experiments toolbar shows compact active filter summary only", "filterSummary ? (", "activeFilterSummary(strategyFilter, statusFilter, strategies, filtered.length, backtests.length)", "`显示 ${visibleCount}/${totalCount}`", "label: formatStatusLabel(status)", "status ? formatStatusLabel(status) : null", "qto-compare-strip", "qto-compare-pill", "experiments compare compact summary opens modal no persistent compare rows", "qto-compare-list", "qto-compare-row", "experiments compare details live in modal with compact rows", "experiments lightweight section no card wrapper"]) {
  includes(experimentsPage + source, marker, "reduced-density experiments UI contract");
}
excludes(experimentsPage + source, "qto-run-meta", "experiments run list must use one-line summary instead of wrapped metadata");
excludes(experimentsPage, "List.Item.Meta", "experiments run list must use compact single-line rows");
excludes(source, "qto-run-description", "experiments run list must not keep stacked description wrappers");
excludes(experimentsPage, 'value ?? "-"', "experiments metric line must not render missing metrics as dash placeholders");
excludes(experimentsPage, "formatMetric(metrics?.[key])", "experiments metric line must filter unavailable metrics");
for (const staleMarker of ["dataset unset", "mlflow unset"]) {
  excludes(experimentsPage, staleMarker, "experiments run summary must not render unset placeholders");
}
excludes(experimentsPage, "MLflow 已记录", "experiments run tracking must show the concrete MLflow run id");
for (const staleMarker of ["dataset_version</Typography.Text>", "runs</Typography.Text>", "${key}: ${value.toFixed(2)}"]) {
  excludes(experimentsPage, staleMarker, "experiments visible copy must not expose raw implementation labels");
}
for (const staleMarker of ['className="qto-run-count"', "{filtered.length}/{backtests.length}"]) {
  excludes(experimentsPage + source, staleMarker, "experiments toolbar must not show persistent unfiltered count");
}
for (const staleMarker of ['const ROW_METRIC_KEYS = ["sharpe", "max_drawdown"]', "metricLabel(key)}:"]) {
  excludes(experimentsPage, staleMarker, "experiments run rows must keep one primary metric with compact metric copy");
}
for (const staleMarker of ["例如 dvc:dataset:rev1", "产物 {run.artifacts.length}</Typography.Text>"]) {
  excludes(experimentsPage, staleMarker, "experiments compare and launch UI must hide low-value technical placeholders");
}
for (const staleMarker of ["label: status", "status ?? null"]) {
  excludes(experimentsPage, staleMarker, "experiments status filters must not expose raw backend status values");
}
for (const staleMarker of ["<StatusTag status={row.status}", "<StatusTag status={run.status}"]) {
  excludes(experimentsPage, staleMarker, "experiments must not show normal completed status pills");
}
for (const staleMarker of ['row.mlflow_run_id ?? row.dataset_version ?? "-"', "qto-compare-panel", "选择记录后对比指标和产物", "数据版本已配置"]) {
  excludes(experimentsPage + source, staleMarker, "experiments compare UI must not render persistent panels or tracking placeholders");
}
for (const staleMarker of ["<strong>{row.id}</strong>", "<strong>{run.id}</strong>", "row.strategy_id,", "row.dataset_version || null", "`MLflow ${row.mlflow_run_id}`", "return row.dataset_version"]) {
  excludes(experimentsPage, staleMarker, "experiments lists must not expose raw run, strategy, dataset, or tracking ids as primary copy");
}
for (const marker of ["requestRiskReview(run: BacktestRun)", 'postApi("/api/v1/risk/reviews"', "factor_report_present", "onRequestRiskReview={requestRiskReview}"]) {
  includes(appSource + source, marker, "experiments risk review action must use real API");
}
for (const marker of ["createBacktest(payload: { strategy_id: string; dataset_version: string })", 'postApi("/api/v1/backtests"', "backtest launch minimal modal requires dataset_version", "onRunBacktest={createBacktest}"]) {
  includes(appSource + source, marker, "experiments backtest launch must use real API");
}
for (const staleMarker of ["Table", "rowSelection", "qto-table-toolbar", "qto-experiments-layout", "qto-filter-panel"]) {
  excludes(source, staleMarker, "experiments page must not expose persistent side panels");
}
excludes(experimentsPage, "Card", "experiments page must not wrap the run list in a card");
for (const staleMarker of ["MetricTags", "<Tag key={key}", "申请风控</Button>", "<Button size=\"small\">更多</Button>", ">操作</Button>", "row.mlflow_run_id || null", 'key: "rerun"', 'key: "artifacts"', "查看 artifacts"]) {
  excludes(experimentsPage, staleMarker, "experiments page must not expose dense metric tags or repeated row actions");
}
for (const staleMarker of ['setCompareModalOpen(true)}>查看</Button>', 'onClick={clearCompareSelection}>清空</Button>']) {
  excludes(experimentsPage, staleMarker, "experiments compare strip must not render persistent text action buttons");
}
for (const staleMarker of ["import { Button, Checkbox", "<Checkbox key=\"compare\"", ">对比</Checkbox>"]) {
  excludes(experimentsPage, staleMarker, "experiments compare action must not render as a persistent row checkbox");
}
excludes(appSource, "已申请风控", "experiments risk review must not be a message-only fake action");
excludes(appSource, "选择策略详情后启动 backtest", "experiments backtest launch must not be a message-only fake action");
for (const marker of ["qto-workbench-status-strip", "qto-workbench-metric", "qto-workbench-priority", "qto-priority-list", "qto-priority-row", "WorkbenchPriorityRow", "workbenchPriorityItems", "portfolioPriorityItems", "dashboard today priority queue ranks risk approval research connection actions", "dashboard priority queue uses native buttons for actionable rows", "dashboard priority queue keeps non-clickable risk items honest", "今天没有必须处理的优先项。风险、审批和研究阻塞项已清空。", "[\"error\", \"testing\"].includes(source.status)", "items.slice(0, 3)", "qto-workbench-section", "qto-workbench-action-row", "qto-workbench-list-line", "qto-workbench-list-main", "WorkbenchListLine", "dashboard compact single-line list row no stacked metadata", "dashboard approval row uses native button and opens drawer no repeated button", "qto-account-note", "dashboard compact account connection note", "portfolio mode driven account note", "dashboard paper sessions render only when present no duplicate empty state", "accountConnectionNote", "accountSourceDetail", "isDefaultPortfolioSource", "isPaperSimulatedOnlySource", "Paper/模拟数据，未连接 Live 券商账户", "未接入券商或 Paper 账户", "data-mode={accountNote.mode}", "Live 账户已连接", "Paper 模式", "模拟组合", "未连接账户", "Live 未启用", "未启用真实券商持仓读取或 live trade", "WorkbenchMetric", "formatPortfolioMetric", "dashboard compact key value status strip no summary cards", "dashboard key value metric no detail stack", "dashboard heading no persistent environment badge", "qto-dashboard-activity", "dashboard running activity lives inside adaptive workbench grid", "dashboard running activity heading hides duplicate count", "runningTasks.length ?", "agentTaskTypeLabel(row.task_type)", "workflowTypeLabel(row.workflow_type)", "ownerLinkedLabel(row.owner_type, row.owner_id)", "linkedDashboardObject(\"工作流\", row.workflow_id)", "linkedDashboardObject(\"策略\", item.strategy_id)", "linkedDashboardObject(\"回测\", item.backtest_run_id)", "linkedDashboardObject(\"部署\", item.deployment_ref)", "formatApprovalTitle(item)", "formatApprovalDescription(item)", "riskReviewDetail(item)", "dashboardRiskAlerts(riskReviews)", "const riskAlertCount = counts?.risk_alerts ?? riskAlerts.length", "riskAlertCount > 0", "isDashboardRiskAlert", "normalizeRiskStatus", "dataSource={riskAlerts.slice(0, 6)}", "dashboard risk alert list filters normal pass reviews", "Paper 会话", "CompactEmpty", "qto-compact-empty", "global compact empty text no Ant Empty block", "dashboard compact empty text no Ant Empty block", "portfolio connection button replaces unavailable account status pill", "dashboard portfolio main card shows all holdings sources without opening modal", "dashboard portfolio main card keeps live trading locked visible", "PortfolioSourceSummaryLine", "portfolioConnectionRows(summary?.connections)", "portfolioSourceSummaryDetail", "portfolioSourceReadHoldingsLabel", "portfolioSourceLastCheckedLabel", "portfolioSourceErrorLabel", "portfolioSourceNextActionLabel", "portfolioConnectionCanReadHoldings", "summary?.status.live_trading_locked ?? true", "qto-portfolio-source-summary", "qto-live-lock-note", "dashboard portfolio connection modal uses multi-source holdings tablist", "dashboard portfolio source tablist title hierarchy includes provider status", "dashboard portfolio source expands inline config instead of single-provider form", "dashboard portfolio source tablist keeps ibkr visible while config changes", "dashboard portfolio source detail panel changes without hiding source list", "dashboard portfolio source detail shows read_holdings last_checked next action", "ConnectionCapabilities", "read_holdings?: boolean", "live_trade?: boolean | \"locked\"", "PORTFOLIO_CONNECTION_SOURCES", "QuantConnect Paper", "可配置", "IBKR", "不读取真实持仓，不支持 live trade", "不读取真实 IBKR 持仓", "Live trading locked；不读取真实 IBKR 持仓", "当前不可连接，仅保留 locked 来源说明", "if (source.provider === \"ibkr\") return;", "当前只有 QuantConnect Paper 可配置", "IBKR 仅为 locked 占位", "本地模拟/不可用", "本地/不可用", "Live trading locked", "读取持仓：否，live trade locked", "最近检查：尚未检查", "保存并测试 QuantConnect Paper", "QuantConnect Paper 凭据已提交", "下一步：保存并测试 QuantConnect Paper", "下一步：继续 Paper workflow；持仓读取未启用", "下一步：接入 QuantConnect Paper；真实券商保持 locked", "选择来源查看配置", "正在查看", "管理持仓来源", "持仓来源管理", "readHoldingsLabel", "lastCheckedLabel", "errorLabel", "nextActionLabel", "source.provider", "QuantConnect 用户 ID", "API token", "activePortfolioSourceKey", "role=\"tablist\"", "role=\"tab\"", "role=\"tabpanel\"", "aria-orientation=\"vertical\"", "aria-selected={isActiveSource}", "clearPortfolioSecretDrafts", "closePortfolioConnectModal", "if (portfolioConnectSubmitting) return;", "qto-portfolio-source-layout", "qto-portfolio-source-list", "qto-portfolio-source-option", "qto-portfolio-source-detail", "qto-portfolio-source-title", "qto-portfolio-field-grid", "qto-section-action", "onConnectPortfolio={connectTool}", "dashboard today decision center prioritizes risk approval research", "qto-dashboard-decision-section", "待处理研究", "pendingResearchItems", "researchDecisionItems(pipeline)", "ResearchPipeline", "pipelineActionLabel(item.next_actions[0])", "dashboard research decision list shows next action not raw ids", "dashboard research decision row uses native button and opens existing pipeline detail drawer", "onResearchItemClick", "onResearchItemClick={setSelectedPipelineItem}", "pipeline={pipeline}", "repeat(auto-fit, minmax(260px, 1fr))"] ) {
  includes(dashboardPage + source, marker, "reduced-density dashboard activity contract");
}
for (const marker of ["dashboard list row hides empty detail placeholders", "paperSessionDetail(item)", "function linkedDashboardObject", "${label} ${readableIdentifier(id)}", "dashboard status strip hides unavailable portfolio metric placeholders", "portfolioMetricItems(portfolio)", "typeof item.value === \"number\""]) {
  includes(dashboardPage + source, marker, "dashboard list rows must not render low-value placeholders");
}
for (const marker of ["dashboard portfolio source tablist supports roving tabindex arrow key selection", "handlePortfolioSourceKeyDown", "tabIndex={isActiveSource ? 0 : -1}", "ArrowDown", "ArrowUp", ".qto-portfolio-field-grid {\n    grid-template-columns: 1fr;"]) {
  includes(dashboardPage + source, marker, "dashboard portfolio source tablist keyboard contract");
}
for (const marker of ['formatPortfolioMetric(value: number)', "formatApprovalDescription(item)", "approvalPolicyReasonLabel(row.policy_lock_reason)"]) {
  includes(dashboardPage, marker, "dashboard metrics and approval rows must hide unavailable or raw backend detail");
}
excludes(dashboardPage, "return row.policy_lock_reason ?? null", "dashboard approval rows must not expose raw backend policy reasons");
for (const staleMarker of ["SummaryCard", "Card title=", "qto-summary-grid", "qto-dashboard-grid"]) {
  excludes(dashboardPage + source, staleMarker, "dashboard must not render a card grid");
}
for (const staleMarker of ["`${typeLabel[row.request_type] ?? row.request_type} · ${row.target_type}`"]) {
  excludes(dashboardPage, staleMarker, "dashboard approval titles must use product labels instead of raw target_type");
}
for (const staleMarker of ['grid-template-columns: 1fr 1fr 1fr', '  .qto-workbench-grid {\\n    grid-template-columns: 1fr;\\n  }', "Live account connected", "Paper trading mode", "Simulated portfolio", "Not connected"]) {
  excludes(dashboardPage + source, staleMarker, "dashboard workbench grid and account states must stay compact and localized");
}
excludes(dashboardPage + source, "qto-workbench-metric-detail", "dashboard status strip must not render stacked metric details");
excludes(dashboardPage, "<StatusTag status={portfolio?.mode ?? \"unavailable\"}", "dashboard portfolio header must use an add connection button");
excludes(dashboardPage, 'useState({ user_id: "", api_token: "" })', "dashboard portfolio connection must not be a single QuantConnect-only form");
excludes(dashboardPage, "dashboard portfolio connection modal uses existing quantconnect provider", "dashboard portfolio connection must list multiple holdings sources");
excludes(dashboardPage, "支持多个来源并存", "dashboard must not imply real multi-source holdings aggregation before backend support exists");
excludes(dashboardPage, 'role="button"', "dashboard clickable rows must use native buttons");
excludes(dashboardPage, '["error", "disconnected", "testing"].includes(source.status)', "dashboard priority queue must not treat ordinary disconnected portfolio source as urgent");
excludes(dashboardPage, "summary?.status.environment", "dashboard heading must not expose persistent environment badge");
excludes(dashboardPage, "暂无 paper session", "dashboard account note must not repeat an empty paper session state");
excludes(dashboardPage, "{runningTasks.length} 项", "dashboard running activity heading must not repeat list count");
excludes(dashboardPage, "List.Item.Meta", "dashboard lists must use compact single-line rows");
excludes(dashboardPage, "dataSource={riskReviews.slice(0, 6)}", "dashboard risk alert list must not render normal passed risk reviews");
for (const staleMarker of ["策略已关联", "回测已关联", "部署已关联", "已关联工作流"]) {
  excludes(dashboardPage, staleMarker, "dashboard linked objects must show specific short object summaries");
}
excludes(source, "qto-workbench-action-row:hover .ant-list-item-meta-title", "dashboard hover styles must not target stale Ant list metadata");
for (const staleMarker of [
  "账户、风险、审批和运行状态。",
  "跟踪 idea、研究、回测、风控和审批阶段。",
  "管理因子、策略和它们的最新验证状态。",
  "查看回测结果、对比指标，并把通过的记录送去风控。",
  "集中查看研究输出、关联对象和文件入口。",
  "Agent Canvas 管理 agent、连接、权限和工作流。",
  "智能体量化工作台",
  "qto-brand .ant-typography-secondary",
]) {
  excludes(source, staleMarker, "page headings must stay compact without explanatory subtitles");
}
excludes(dashboardPage, "Table", "dashboard activity must not use a persistent table");
excludes(dashboardPage, "<Alert", "dashboard account connection notice must not use a heavy alert block");
excludes(dashboardPage, "<Empty", "dashboard empty states must use compact text instead of heavy Ant Empty blocks");
excludes(source, 'import { Empty', "global empty states must not import heavy Ant Empty blocks");
excludes(source, "<Empty", "global empty states must use compact text instead of heavy Ant Empty blocks");
excludes(dashboardPage, "处理</Button>", "dashboard approvals must not repeat row action buttons");
excludes(dashboardPage, "没有真实券商持仓接入，仅显示 paper / simulated / unavailable 状态。", "dashboard account note must not be hard-coded to not connected");
excludes(dashboardPage, 'const source = portfolio?.source ?? "paper / simulated / unavailable"', "dashboard account note must format backend portfolio source before display");
for (const staleMarker of ['detail || "-"', "待部署", "未绑定 workflow"]) {
  excludes(dashboardPage, staleMarker, "dashboard list rows must hide unavailable detail instead of rendering placeholders");
}
excludes(dashboardPage, 'return "不可用"', "dashboard portfolio metrics must be hidden when unavailable instead of rendered as placeholders");
for (const staleMarker of ["formatPortfolioMetric(value: number | null | undefined)", "row.policy_lock_reason ?? row.target_id"]) {
  excludes(dashboardPage, staleMarker, "dashboard must not format missing metrics or show raw target ids in approval rows");
}
for (const staleMarker of ["title={item.strategy_id}", "detail={item.risk_summary?.reason ?? item.backtest_run_id}", "isAgentRun(row) ? row.task_type : row.workflow_type", "isAgentRun(row) ? row.workflow_id", "ownerReferenceLabel(row.owner_type, row.owner_id)"]) {
  excludes(dashboardPage, staleMarker, "dashboard must not expose raw ids or backend task names in list rows");
}
for (const marker of ["qto-kanban-count", "qto-card-summary", "qto-pipeline-card-header", "qto-pipeline-next-row", "qto-pipeline-next-action", "qto-pipeline-blockers", "pipelineCardSummary", "pipelinePrimaryAction", "pipelineBlockerItems", "const action = pipelinePrimaryAction(item)", "const blockers = pipelineBlockerItems(item)", "research pipeline card shows next action and blockers without opening drawer", "pipelineAttentionStatus", "const status = pipelineAttentionStatus(item.status)", "research pipeline status pill is attention-only", "pipelineActionLabel(item.next_actions[0])", "pipelineActionLabel(item.latest_action)", "pipelineActionLabel", "下一步 ${label}", "启动研究工作流", "申请风控复核", "research pipeline compact card one-line summary", "pipeline card summary renders only when populated", "const summary = pipelineCardSummary(item)", "activeStages", "startResearchWorkflow(item: ResearchPipelineItem)", "research workflow action scoped to selected project", "qto-detail-action-row", "pipeline detail optional sections render only when populated", "hideWhenEmpty"]) {
  includes(appSource + researchPipelinePage + source, marker, "reduced-density research pipeline contract");
}
for (const staleMarker of ["qto-stage-note", "inactiveStageCount", "空阶段", "research empty stages collapsed into heading note no duplicate stage rail"]) {
  excludes(researchPipelinePage + source, staleMarker, "research pipeline must not expose collapsed empty-stage noise");
}
excludes(source, "repeat(9", "research pipeline must not render nine fixed kanban columns");
excludes(researchPipelinePage, "stages.map((stage)", "research stage rail must not expose every empty stage");
for (const staleMarker of ["qto-stage-rail", "qto-stage-pill", "qto-stage-count", "overviewStages", "研究阶段概览"]) {
  excludes(researchPipelinePage + source, staleMarker, "research pipeline must not duplicate active stage labels above the kanban");
}
excludes(researchPipelinePage, "description=\"暂无项目\"", "research pipeline must not render empty stage placeholders");
excludes(researchPipelinePage, "onStartWorkflow", "research workflow launch must be scoped to selected project detail");
excludes(researchPipelinePage, "启动研究流", "research pipeline page heading must not expose a global workflow start action");
excludes(researchPipelinePage, "item.next_actions[0] ?? item.latest_action ?? null", "research pipeline cards must not expose raw workflow action text");
for (const staleMarker of ["<Tag>{stage.items.length}</Tag>", '<Tag color="blue">{item.owner_agent}</Tag>']) {
  excludes(researchPipelinePage, staleMarker, "research pipeline counts and agent metadata must not render as tags");
}
for (const staleMarker of ["最近动作：", "qto-card-warning", "qto-card-line"]) {
  excludes(researchPipelinePage + source, staleMarker, "research pipeline cards must not expose stacked detail lines");
}
excludes(researchPipelinePage, "<StatusTag status={item.status}", "research pipeline must not show normal lifecycle status pills");
for (const staleMarker of ["hasMetric(item.latest_metrics", "metric(item.latest_metrics", "item.owner_agent ? `智能体 ${item.owner_agent}` : null", "qto-card-agent"]) {
  excludes(researchPipelinePage, staleMarker, "research pipeline cards must keep metrics and owner agent in the detail drawer");
}
for (const staleMarker of ['"暂无动作"', 'return value ?? "-"']) {
  excludes(researchPipelinePage, staleMarker, "research pipeline cards must hide missing action and metric placeholders");
}
for (const marker of ["qto-report-section", "qto-report-list", "qto-report-row", "qto-report-list-line", "qto-report-list-main", "reports compact single-line row no stacked metadata", "qto-report-summary", "qto-report-action-hint", "reportTitle(row)", "reportSummary(row)", "reportActionHint(row)", "function reportActionHint", "reports row shows source-aware next action without repeated detail button", "处理状态 ${readableIdentifier(row.owner_status)}", "查看对象信息", "查看关联对象", "artifactTypeLabel(row.artifact.artifact_type)", "reportOwnerSummary(row)", "ownerTypeLabel(row.artifact.owner_type)", "ownerLinkedLabel(row.artifact.owner_type, row.artifact.owner_id)", "formatDisplayDate(row.artifact.created_at, \"创建\")", "readableArtifactName(sourceName)", "readableIdentifier", "研究项目", "reports compact one-line list summary", "report row opens detail no repeated detail button", "report direct open action only when link exists no single-item dropdown", "ExportOutlined", "aria-label=\"打开报告\"", "reports lightweight section no card wrapper", "reports relation metadata no tag stack", "reportAttentionStatus", "const status = reportAttentionStatus(row.owner_status)", "reports owner status pill is attention-only", "report detail optional sections render only when populated", "report detail keeps list-hidden context in compact metadata", "reportDetailMetaItems(selected)", "reportDetailSummary(selected)", "reportLink(selected)", "reportLinkLabel(selected)", "reportAuditItems(selected)", "reports audit metadata no raw artifact json", "auditReferenceLabel(\"校验\", row.artifact.checksum)", "auditReferenceLabel(\"MLflow\", row.artifact.mlflow_run_id)", "auditReferenceLabel(\"DVC\", row.artifact.dvc_rev)", "function shortReference", "value.length > 12", "contentTypeLabel(row.artifact.content_type)", "对象 ${readableArtifactName(row.artifact.object_key)}", "readableArtifactName(row.artifact.path)", "readableArtifactName(row.artifact.object_key)", "relatedReportObject(\"因子\", row.related_factor_id)", "relatedReportObject(\"策略\", row.related_strategy_id)", "relatedReportObject(\"回测\", row.related_backtest_id)", "function relatedReportObject", "${label} ${readableIdentifier(id)}", "selected.artifact.path ? ("]) {
  includes(reportsPage + source, marker, "reduced-density reports list contract");
}
for (const staleMarker of ["<Dropdown", "report compact action menu", "aria-label=\"报告操作\"", "MoreOutlined"]) {
  excludes(reportsPage, staleMarker, "reports row open action must not use a single-item dropdown");
}
excludes(reportsPage + source, "qto-report-meta", "reports list must use one-line summary instead of wrapped metadata");
excludes(reportsPage, "List.Item.Meta", "reports list must use compact single-line rows");
excludes(source, "qto-report-row:hover .ant-list-item-meta-title", "report hover styles must not target stale Ant list metadata");
excludes(source, "qto-report-row .ant-list-item-meta-title", "report row styles must not target stale Ant list metadata");
excludes(reportsPage, "Card", "reports page must not wrap the list in a card");
excludes(reportsPage, "Table", "reports page must not use a persistent table");
excludes(reportsPage, "<Tag", "reports page must not render relation metadata as tags");
excludes(reportsPage, 'row.owner_status ?? "unknown"', "reports page must not render unknown owner status placeholders");
for (const staleMarker of ["row.owner_status ? <StatusTag", "<StatusTag status={row.owner_status}"]) {
  excludes(reportsPage, staleMarker, "reports list must not show normal owner status pills");
}
excludes(reportsPage, 'key="detail"', "reports page must not repeat a detail button on every row");
excludes(reportsPage, "disabled={!row.artifact.path}", "reports page must not render disabled open buttons without links");
for (const staleMarker of ["暂无摘要", 'selected.artifact.path || selected.artifact.object_key || "-"']) {
  excludes(reportsPage, staleMarker, "report detail drawer must hide empty optional content instead of rendering placeholders");
}
for (const staleMarker of ["校验值已记录", "MLflow 已记录", "DVC 已记录", "对象存储已记录", "文件类型已记录", "可打开文件", "文件已关联"]) {
  excludes(reportsPage, staleMarker, "report detail must show specific compact references instead of generic recorded/linked copy");
}
for (const staleMarker of ['`${row.artifact.owner_type} · ${row.owner_name}`', 'row.artifact.owner_type === "research_idea" ? `研究 ${row.artifact.owner_id}` : null', "row.artifact.object_key ?? row.artifact.path ?? row.artifact.id"]) {
  excludes(reportsPage, staleMarker, "reports page must not expose raw artifact owner/type fields as visible copy");
}
for (const staleMarker of ["row.artifact.id", "checksum ${row.artifact.checksum}", "<Typography.Text>{reportLink(selected)}</Typography.Text>", "`因子 ${row.related_factor_id}`", "`策略 ${row.related_strategy_id}`", "`回测 ${row.related_backtest_id}`", 'row.related_factor_id ? "关联因子" : null', 'row.related_strategy_id ? "关联策略" : null', 'row.related_backtest_id ? "关联回测" : null']) {
  excludes(reportsPage, staleMarker, "report detail must not expose raw artifact ids, checksums, paths, or relation ids as visible copy");
}
for (const staleMarker of ['import { JsonBlock }', "<JsonBlock value={selected.artifact}", 'label: "审计记录"', "items={[{ key: \"artifact\""]) {
  excludes(reportsPage, staleMarker, "report detail audit record must not expose raw artifact JSON");
}
excludes(reportsPage, "ownerReferenceLabel(row.artifact.owner_type, row.artifact.owner_id)", "reports detail must show linked object copy instead of raw owner id");
for (const staleMarker of ["row.artifact.created_at ? `创建 ${row.artifact.created_at}` : null", "reportRelations(row)[0]"]) {
  excludes(reportsPage, staleMarker, "reports list summary must keep created time and relations in the detail drawer");
}
for (const marker of [
  "qto-agent-advanced-collapse",
  "qto-agent-readiness-strip",
  "agent readiness summary visible after node click no execution authority",
  "agentReadinessItems(selectedAgent, permissions)",
  "function agentReadinessItems",
  "agentLifecycleLabel(agent.status)",
  "function agentLifecycleLabel",
  "agentToolReadinessLabel(agent.tool_refs)",
  "function agentToolReadinessLabel",
  "agentPermissionReadinessLabel(permissions)",
  "function agentPermissionReadinessLabel",
  "任务进行中",
  "可接收任务",
  "工具需处理",
  "工具可用",
  "权限已配置",
  "agent overview inline metadata no boxed grid",
  "agent overview hides empty task and normal permission count",
  "agentOverviewMetaItems",
  "permission summary inline metadata no boxed grid",
  "permissionSummaryMetaItems",
  "编辑基本信息",
  "高级：模型与提示词",
  "模型服务",
  "系统提示词",
  "secretRefLabel(row.secret_ref)",
  "function secretRefLabel",
  "function shortSecretRef",
  "密钥 ${shortSecretRef(value)}",
  "secret policy: raw values are cleared after submit",
  "提交后只保留密钥引用",
  "livePermissionSummary(agent)",
  "function livePermissionSummary",
  "Live 已锁定，执行关闭",
  "Live 执行关闭，仅 Paper",
  "上游智能体",
  "下游智能体",
  "工作流:",
  "交接契约",
  "agentAttentionSummaryItems",
  "agent attention summary only when needed",
  "agent attention summary tool issues only no normal tool count",
  "agent attention summary permission issue only no normal permission count",
  "编辑权限开关",
  "countEnabledPermissions",
  "qto-agent-tool-list",
  "qto-agent-tool-meta",
  "toolMetaLine(row)",
  "TOOL_PERMISSION_LABELS",
  "toolPermissionLabel(row.permission_level)",
  "行情数据",
  "管理员",
  "qto-agent-compact-line",
  "qto-agent-compact-actions",
  "agent tool compact single-line row",
  "agent run compact single-line row",
  "agent tool compact action menu",
  "agent open ui action only when link exists",
  "agent audit action opens logs tab",
  "activeKey={activeTab}",
  "setActiveTab(\"logs\")",
  "qto-agent-run-list",
  "qto-agent-tool-row",
  "qto-agent-run-row",
  "agent summary lightweight text line no summary pills",
  "agent config title status pill is attention-only",
  "agentDrawerAttentionStatus(selectedAgent.status)",
  "function agentDrawerAttentionStatus",
  "agent canvas node configuration uses right drawer instead of centered modal",
  "agent canvas selection opens right side drawer keeps canvas context",
  "qto-agent-config-drawer",
  'placement="right"',
  "mask={false}",
  "width={520}",
  "agentActivityRows",
  "agent logs merged compact activity list no split workflow and run lists",
  "human action only when required no normal-state noise",
  "qto-agent-config-actions",
  "agent config scoped actions save only on editable tabs",
  "agent run action only on overview tab",
  "isEditableAgentTab",
  "const canQueueRun = activeTab === \"overview\"",
  "canQueueRun ? (",
  "edge configuration inline metadata no boxed grid",
  "edge configuration hides missing workflow placeholders",
  "edge metadata renders compact summary no raw json",
  "CompactMetaList",
  "edgeMetadataItems",
  "hasMetadataValue",
  'key !== "group_edge" && hasMetadataValue(value)',
  "formatMetadataValue",
  "agent run row hides missing workflow placeholders",
  "agent workflow events render only real workflow data no fake links",
  "const status = activityAttentionStatus(row.status)",
  "agent config activity status pill is attention-only",
  "ownerLinkedLabel(workflow.owner_type, workflow.owner_id)",
  "workflowTypeLabel(workflow.workflow_type)",
  "relationTypeLabel(edge.relation_type)",
  "readableIdentifier(edge.source)",
  "agentTaskTypeLabel(run.task_type)",
  "工作流 ${readableIdentifier(run.workflow_id)}",
]) {
  includes(agentConfigDrawer + source, marker, "reduced-density agent config list contract");
}
for (const staleMarker of ['return "已配置"', 'return value.length ? `${value.length} 项` : "空"', 'return "空"']) {
  excludes(agentConfigDrawer, staleMarker, "agent edge metadata must hide empty values instead of rendering placeholders");
}
excludes(agentConfigDrawer, "已关联工作流", "agent config run detail must show the concrete workflow id");
excludes(agentConfigDrawer, "agentLogSummaryItems", "agent config logs must not render a separate summary count row");
excludes(agentConfigDrawer, "<StatusTag status={agent.status}", "agent config title must not show normal status pills");
excludes(agentConfigDrawer, "qto-agent-config-modal", "agent config must use a right drawer instead of the old centered modal class");
excludes(agentConfigDrawer, "width={860}", "agent config drawer must not keep the old centered modal width");
excludes(agentConfigDrawer, '<Modal title="连线配置"', "edge configuration must use the right drawer instead of a centered modal");
for (const staleMarker of ["relatedWorkflows.length ?", "agent logs summary hides zero counts and normal-state noise"]) {
  excludes(agentConfigDrawer, staleMarker, "agent config logs must use one merged activity list");
}
for (const staleMarker of ["<strong>{run.id}</strong>", "{run.workflow_id ? <small>{run.workflow_id}</small> : null}", "ownerReferenceLabel(workflow.owner_type, workflow.owner_id)", "<strong>{workflow.workflow_type}</strong>"]) {
  excludes(agentConfigDrawer, staleMarker, "agent config logs must not expose raw run, workflow, or owner identifiers");
}
for (const staleMarker of ["`${workflow.owner_type}:${workflow.owner_id}`", "{workflow.owner_type}:{workflow.owner_id}", "`${row.owner_type}:${row.owner_id}`"]) {
  excludes(source, staleMarker, "workflow owner references must use product labels instead of raw owner_type:owner_id");
}
excludes(agentConfigDrawer, "Table", "agent config drawer must not use persistent tables");
excludes(agentConfigDrawer, 'import { JsonBlock }', "agent edge metadata must not import raw JSON renderer");
excludes(agentConfigDrawer, "JsonBlock value={edge.metadata}", "agent edge metadata must not expose raw JSON");
for (const staleMarker of ["密钥只写入一次，前端只显示密钥引用和连接状态。", "审计、工具调用、策略决策"]) {
  excludes(agentConfigDrawer, staleMarker, "agent config drawer must not keep low-value persistent helper text");
}
for (const staleMarker of ['<AgentKeyValue label="上游 agent">', '<AgentKeyValue label="下游 agent">', '<AgentKeyValue label="关系类型">', '<AgentKeyValue label="失败原因">']) {
  excludes(agentConfigDrawer, staleMarker, "edge configuration must render inline metadata instead of boxed key-value cards");
}
for (const staleMarker of ["上游 agent:", "下游 agent:", "workflow:", "交接契约 / handoff contract"]) {
  excludes(agentConfigDrawer, staleMarker, "edge configuration visible copy must not expose mixed raw English labels");
}
for (const staleMarker of ["关系: {edge.relation_type}", "工作流: {edge.workflow_type}", "上游智能体: {edge.source}", "下游智能体: {edge.target}"]) {
  excludes(agentConfigDrawer, staleMarker, "edge configuration must label relation and workflow types instead of raw enums");
}
for (const staleMarker of ['<AgentKeyValue label="分组">', '<AgentKeyValue label="当前任务">', '<AgentKeyValue label="模型">', '<AgentKeyValue label="权限">']) {
  excludes(agentConfigDrawer, staleMarker, "agent overview must render inline metadata instead of boxed key-value cards");
}
for (const staleMarker of ['currentTask || "空闲"', "`权限 ${activePermissionCount} enabled`", "activePermissionCount"]) {
  excludes(agentConfigDrawer, staleMarker, "agent overview must not repeat empty task or normal permission count");
}
excludes(agentConfigDrawer, " enabled`", "agent permission summary must use Chinese enabled copy");
for (const staleMarker of ["<span>provider</span>", "<span>model</span>", "<span>system_prompt</span>", 'placeholder="provider"', 'placeholder="model"', 'placeholder="system_prompt"', "secret_ref 和连接状态", "只保留 secret_ref", "live 权限 can_execute_live_trade=false", "live 已锁定", "仅 paper", "secret_ref 已配置", "workflow 事件", "申请 paper", "申请 live", "执行 live"]) {
  excludes(agentConfigDrawer, staleMarker, "agent config visible copy must use product language instead of raw implementation labels");
}
for (const staleMarker of ['<AgentKeyValue label="live 权限">', '<AgentKeyValue label="风控限制">', '<AgentKeyValue label="研究与数据">', '<AgentKeyValue label="交易与审批">']) {
  excludes(agentConfigDrawer, staleMarker, "permission summary must render inline metadata instead of boxed key-value cards");
}
for (const staleMarker of ["风控限制 ${agent.risk_limits?.live_trading_locked", 'label: "Live 执行已关闭"']) {
  excludes(agentConfigDrawer, staleMarker, "permission summary must merge duplicate live safety copy into one item");
}
for (const staleMarker of ['key="connect"', 'key="test"', "disabled: !row.open_ui_url", "人工处理：无需", "<Tag>{row.permission_level}</Tag>", "secret_ref 已配置</Tag>", "[row.permission_level, row.secret_ref"]) {
  excludes(agentConfigDrawer, staleMarker, "agent tool rows must use a compact action menu and text metadata");
}
excludes(agentConfigDrawer, "secret_ref 未配置", "agent tool rows must not repeat missing secret placeholders");
excludes(agentConfigDrawer, "密钥引用已配置", "agent tool rows must show a specific secret ref label instead of generic configured copy");
for (const staleMarker of ["summarizeToolConnection", "<span>{toolHealth}</span>", "<span>{activePermissionCount} 项权限</span>"]) {
  excludes(agentConfigDrawer, staleMarker, "agent config summary must not expose normal tool or permission counts");
}
for (const staleMarker of ['edge.workflow_type ?? "-"', "未绑定 workflow", 'model || "未设置"']) {
  excludes(agentConfigDrawer, staleMarker, "agent config drawer must hide unavailable metadata instead of rendering placeholders");
}
for (const staleMarker of ["from incoming edges", "from outgoing edges", "Langfuse link", "Temporal link", "上下游与 workflow"]) {
  excludes(agentConfigDrawer, staleMarker, "agent config logs must not render fake workflow or observability placeholders");
}
for (const marker of [
  "positionAgentInGroup(node, index, agentCount, nextGroupLayouts.get(node.group))",
  "expandParent: true",
  "onCanvasNodesChange",
  "applyNodeChanges(changes, items)",
  "fitGroupNodesToChildren([...groupNodes, ...agentNodes])",
  "fitGroupNodesToChildren(items.map((node) => {",
  "countAgentNodesByGroup(items)",
  "data: { ...node.data, width: base.width, height: base.height }",
  "style: { ...node.style, width: base.width, height: base.height }",
  "measureAgentBoundsByGroup(baseSized)",
  "groupAdjustmentsForChildBounds(baseSized, agentCounts, childBounds)",
  "normalizeAgentNodesToGroupLanes(adjusted)",
  "type AgentChildBounds",
  "agentVisualBounds(node)",
  "function agentVisualBounds",
  "position.x - AGENT_VISUAL_CLEARANCE",
  "node.position.x + size.width + AGENT_VISUAL_CLEARANCE",
  "function agentNodeDimensions",
  "numericNodeSize(node.style?.width)",
  "numericNodeSize(node.style?.height)",
  "bounds.left - AGENT_LEFT_OFFSET",
  "bounds.top - AGENT_TOP_OFFSET",
  "bounds.right - dx + GROUP_RIGHT_PADDING",
  "bounds.bottom - dy + GROUP_BOTTOM_PADDING",
  "x: node.position.x + adjustment.dx",
  "x: node.position.x - adjustment.dx",
  "clampAgentPositionToLane(node.position, lane, agentNodeDimensions(node))",
  "style: { ...node.style, width: base.width, height: base.height }",
  "width: data.width, height: data.height",
  "type AgentGridMetrics",
  "type AgentLaneBounds",
  "agentGridMetrics(groupId, agentCount)",
  "fitGroupSizeToAgentBounds(metrics)",
  "agentLaneBounds(groupWidth, groupHeight)",
  "group lane adapts to contained agent card bounds",
  "group lane expands and shifts with child agent bounds",
  "parent-controlled lane size no child expand overflow",
  "AGENT_VISUAL_CLEARANCE",
  "GROUP_MIN_WIDTH = AGENT_LEFT_OFFSET + AGENT_VISUAL_CLEARANCE + AGENT_CARD_WIDTH + AGENT_VISUAL_CLEARANCE + GROUP_RIGHT_PADDING",
  "width: Math.max(GROUP_MIN_WIDTH, AGENT_LEFT_OFFSET + AGENT_VISUAL_CLEARANCE + metrics.contentWidth + AGENT_VISUAL_CLEARANCE + GROUP_RIGHT_PADDING)",
  "height: AGENT_TOP_OFFSET + AGENT_VISUAL_CLEARANCE + metrics.contentHeight + AGENT_VISUAL_CLEARANCE + GROUP_BOTTOM_PADDING",
  "left: AGENT_LEFT_OFFSET + AGENT_VISUAL_CLEARANCE",
  "right: groupWidth - GROUP_RIGHT_PADDING - AGENT_VISUAL_CLEARANCE",
  "qto-agent-node .react-flow__handle-left",
  "maxStartX = Math.max(lane.left",
  "clampAgentPositionToLane",
  "lane.right - size.width",
  "lane.bottom - size.height",
  "box-sizing: border-box",
  "agent group lane hides normal idle summary text",
]) {
  includes(agentCanvasPage + source, marker, "agent group container-fit layout contract");
}
includes(agentCanvasPage, "expandParent: true", "agent nodes must auto-expand parent group lanes when dragged to the edge");
for (const staleMarker of ["node.data.width - dx", "node.data.height - dy", "Math.max(base.width, numericNodeSize(node.style?.width), node.data.width)"]) {
  excludes(agentCanvasPage, staleMarker, "agent group lanes must shrink stale parent size before adapting to child bounds");
}
for (const staleMarker of ["labelBgStyle", "labelStyle", "return \"all idle\"", 'return "empty group"']) {
  excludes(agentCanvasPage, staleMarker, "agent group flow edges must not show dense labels over swimlanes");
}
for (const marker of ['"agent-graph": "/api/v1/agent-graph"', "patchApi", "postApi"]) {
  includes(apiClient + source, marker, "Agent Canvas API client contract");
}

for (const marker of [
  "human_comment",
  "请填写审批说明",
  "approvalComment.trim()",
  "okButtonProps={{ disabled: !approvalComment.trim() }}",
  "placeholder=\"填写审批说明\"",
  "qto-approval-actions",
  "approval primary action plus compact secondary menu",
  "approvalDetailMetaItems",
  "approvalPolicyReasonLabel",
  "approvalCollapseItems",
  "hasObjectEntries(row.risk_summary)",
  "审批更多操作",
  "approval secondary menu icon-only no persistent text",
  "icon={<MoreOutlined />}",
  "okText=\"创建\"",
  "placeholder=\"例如 美股大盘\"",
  "placeholder=\"例如 股票\"",
  "placeholder=\"动量, 质量\"",
  "setCredentialDraft({})",
  "okText=\"连接\"",
  "placeholder=\"粘贴 API 密钥\"",
  "Secret fields are sent once",
  "secret_ref",
  "live trading locked",
  "live_trading_status",
]) {
  includes(source, marker, "approval and secret safety contract");
}
for (const staleMarker of ['aria-label="Request changes"', 'aria-label="Reject"', ">要求修改</Button>", ">拒绝</Button>", ">其他处理</Button>"]) {
  excludes(appSource, staleMarker, "approval drawer secondary actions must not render as persistent buttons");
}
excludes(dashboardPage, "return row.policy_lock_reason ?? null", "dashboard approval rows must format policy reasons before display");
for (const staleMarker of ['aria-label="Approve"', 'aria-label="More approval actions"', 'aria-label="Connect"', 'aria-label="Test"', 'aria-label="Open UI"', 'aria-label="View audit"', 'aria-label="Queue run"', 'placeholder="human_comment"', 'placeholder="US equities"', 'placeholder="equity"', 'placeholder="momentum, quality"', 'placeholder="粘贴 API key"']) {
  excludes(source, staleMarker, "visible and accessible UI copy must stay localized");
}
excludes(appSource, "<DetailMeta>{selectedApproval.target_id}</DetailMeta>", "approval drawer summary must not repeat raw target id outside request details");
for (const staleMarker of ['<DetailKeyValue label="请求类型">', '<DetailKeyValue label="目标">', '<DetailKeyValue label="策略限制">']) {
  excludes(appSource, staleMarker, "approval request detail must render inline metadata instead of boxed key-value cards");
}
excludes(source, "sk-testsecret1234", "UI source must not expose test secrets");

matches(routes, /export function normalizePath\(pathname: string\)/, "legacy redirect helper");
assert.ok(existsSync(join(srcRoot, "api/client.ts")), "API client exists");

console.log("control-ui UI smoke test passed");
