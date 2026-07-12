import { CompressOutlined, MoreOutlined, PlusOutlined, ReloadOutlined, SaveOutlined } from "@ant-design/icons";
import dagre from "@dagrejs/dagre";
import { Background, Controls, Handle, MarkerType, MiniMap, Position, ReactFlow, applyNodeChanges, useEdgesState, useNodesState, type Edge, type Node, type NodeChange } from "@xyflow/react";
import { Button, Dropdown, Input, Modal, Select, Space, Tabs, Typography } from "antd";
import { useEffect, useMemo, useRef, useState, type CSSProperties } from "react";
import type { AgentEdgeData, AgentGraph, AgentGroup, AgentNodeData, AgentRun, AgentToolRef, WorkflowLink } from "../../api/types";
import { CompactEmpty } from "../../components/CompactEmpty";
import { StatusTag } from "../../components/StatusTag";
import { agentDisplayName, agentGroupLabel, agentRoleLabel, ownerLinkedLabel, readableIdentifier } from "../../displayLabels";
import { AgentConfigDrawer } from "./AgentConfigDrawer";

type AgentGroupNodeData = AgentGroup & {
  agentCount: number;
  statusSummary: string;
  stageIndex: string;
  width: number;
  height: number;
};

type GroupLayout = {
  x: number;
  y: number;
  width: number;
  height: number;
};

type AgentGridMetrics = {
  columns: number;
  rows: number;
  contentWidth: number;
  contentHeight: number;
  groupWidth: number;
  groupHeight: number;
};

type AgentLaneBounds = {
  left: number;
  top: number;
  right: number;
  bottom: number;
  width: number;
  height: number;
};

type AgentChildBounds = {
  left: number;
  top: number;
  right: number;
  bottom: number;
  width: number;
  height: number;
};

type AgentNodeDimensions = {
  width: number;
  height: number;
};

type AgentNodeFlowNode = Node<AgentNodeData> & { type: "agent" };
type AgentGroupFlowNode = Node<AgentGroupNodeData> & { type: "group" };
type AgentFlowNode = AgentNodeFlowNode | AgentGroupFlowNode;
type AgentFlowEdge = Edge<AgentEdgeData>;
type AgentCanvasViewFilter = "all" | "running" | "attention" | "disconnected";

const NODE_TYPES = { agent: AgentNodeCard, group: AgentGroupLane };
const ABNORMAL_STATUSES = new Set(["blocked", "failed", "waiting_approval", "locked", "disconnected"]);
const GROUP_NODE_PREFIX = "group:";
const SYSTEM_GROUP_ID = "system";
const STAGE_ORDER = ["data", "research", "validation", "trading", SYSTEM_GROUP_ID];
const GROUP_GAP = 84;
const GROUP_LEFT = 56;
const GROUP_TOP = 72;
const AGENT_CARD_WIDTH = 200;
const AGENT_CARD_HEIGHT = 104;
const AGENT_VISUAL_CLEARANCE = 24;
const GROUP_INSET_X = 44;
const GROUP_INSET_BOTTOM = 48;
const AGENT_TOP_OFFSET = 88;
const AGENT_LEFT_OFFSET = GROUP_INSET_X;
const AGENT_Y_GAP = 24;
const AGENT_X_GAP = 36;
const GROUP_RIGHT_PADDING = GROUP_INSET_X;
const GROUP_BOTTOM_PADDING = GROUP_INSET_BOTTOM;
const GROUP_MIN_WIDTH = AGENT_LEFT_OFFSET + AGENT_VISUAL_CLEARANCE + AGENT_CARD_WIDTH + AGENT_VISUAL_CLEARANCE + GROUP_RIGHT_PADDING;

const AGENT_TEMPLATE_OPTIONS = [
  { value: "Research Agent", label: "研究智能体" },
  { value: "Data Agent", label: "数据智能体" },
  { value: "Strategy Agent", label: "策略智能体" },
  { value: "Backtest Agent", label: "回测智能体" },
  { value: "Risk Agent", label: "风控智能体" },
  { value: "Approval Agent", label: "审批智能体" },
  { value: "Execution Agent", label: "执行智能体" },
  { value: "Monitoring Agent", label: "监控智能体" },
  { value: "Blank Agent", label: "空白智能体" },
];

export function AgentCanvasPage({
  graph,
  agentRuns,
  workflows,
  onRefresh,
  onSaveLayout,
  onCreateAgent,
  onPatchAgent,
  onRunAgent,
  onConnectTool,
  onTestTool,
}: {
  graph: AgentGraph | null;
  agentRuns: AgentRun[];
  workflows: WorkflowLink[];
  onRefresh: () => void;
  onSaveLayout: (nodes: Array<{ id: string; position: { x: number; y: number } }>, edges: Array<{ id: string; status?: string }>) => Promise<void>;
  onCreateAgent: (payload: Record<string, unknown>) => Promise<void>;
  onPatchAgent: (agentId: string, payload: Record<string, unknown>) => Promise<void>;
  onRunAgent: (agentId: string) => Promise<void>;
  onConnectTool: (provider: string, credentials: Record<string, string>) => Promise<void>;
  onTestTool: (provider: string) => Promise<void>;
}) {
  const [nodes, setNodes] = useNodesState<AgentFlowNode>([]);
  const [edges, setEdges, onEdgesChange] = useEdgesState<AgentFlowEdge>([]);
  const [selectedAgent, setSelectedAgent] = useState<AgentNodeData | null>(null);
  const [selectedEdge, setSelectedEdge] = useState<AgentEdgeData | null>(null);
  const [viewFilter, setViewFilter] = useState<AgentCanvasViewFilter>("all");
  const [newAgentOpen, setNewAgentOpen] = useState(false);
  const [activityOpen, setActivityOpen] = useState(false);
  const [activityTab, setActivityTab] = useState("runs");
  const [drawerInitialTab, setDrawerInitialTab] = useState("overview");
  const [newAgentDraft, setNewAgentDraft] = useState({ template: "Blank Agent", name: "", role: "", group: "research" });
  const handledPanelQuery = useRef<string | null>(null);
  const orderedGroups = useMemo(() => sortAgentGroups(graph?.groups ?? []), [graph?.groups]);
  const groupLayouts = useMemo(() => buildGroupLayouts(orderedGroups, graph?.nodes ?? []), [orderedGroups, graph?.nodes]);

  useEffect(() => {
    if (!graph) return;
    const nextGroupLayouts = buildGroupLayouts(orderedGroups, graph.nodes);
    const groupNodes: AgentGroupFlowNode[] = orderedGroups.map((group) => {
      const layout = nextGroupLayouts.get(group.id) ?? defaultGroupLayout(graph.groups.length, 1);
      const groupAgents = graph.nodes.filter((node) => node.group === group.id);
      return {
        id: groupNodeId(group.id),
        type: "group",
        position: { x: layout.x, y: layout.y },
        data: {
          ...group,
          label: agentStageLabel(group.id, group.label),
          agentCount: groupAgents.length,
          statusSummary: summarizeGroupStatus(groupAgents),
          stageIndex: agentStageIndex(group.id),
          width: layout.width,
          height: layout.height,
        },
        draggable: false,
        selectable: false,
        zIndex: 0,
        style: { width: layout.width, height: layout.height },
      };
    });
    const agentById = new Map(graph.nodes.map((node) => [node.id, node]));
    const groupIndex = new Map<string, number>();
    const agentNodes: AgentNodeFlowNode[] = graph.nodes.map((node) => {
      const index = groupIndex.get(node.group) ?? 0;
      groupIndex.set(node.group, index + 1);
      const group = graph.groups.find((item) => item.id === node.group);
      const agentCount = countAgentsInGroup(graph.nodes, node.group);
      const position = positionAgentInGroup(node, index, agentCount, nextGroupLayouts.get(node.group));
      return {
        id: node.id,
        type: "agent",
        parentId: groupNodeId(node.group),
        extent: "parent" as const,
        expandParent: true,
        position,
        zIndex: 10,
        style: { width: AGENT_CARD_WIDTH, height: AGENT_CARD_HEIGHT },
        data: { ...node, position, metadata: { ...node.metadata, group_label: group?.label ?? node.group } },
      };
    });
    setNodes(fitGroupNodesToChildren([...groupNodes, ...agentNodes]));
    setEdges(
      [
        ...buildGroupEdges(graph),
        ...graph.edges
          .filter((edge) => shouldRenderAgentEdge(edge, agentById))
          .map((edge) => ({
            id: edge.id,
            source: edge.source,
            target: edge.target,
            type: "smoothstep",
            markerEnd: { type: MarkerType.ArrowClosed },
            data: edge,
            zIndex: 5,
            style: {
              stroke: edge.status === "blocked" || edge.status === "failed" ? "#dc2626" : "#64748b",
              strokeOpacity: 0.38,
              strokeWidth: edge.status === "active" ? 2 : 1.2,
            },
          })),
      ],
    );
  }, [graph, orderedGroups, setEdges, setNodes]);

  useEffect(() => {
    if (!graph?.nodes.length) return;
    const panel = normalizeAgentPanelQuery(new URLSearchParams(window.location.search).get("panel"));
    if (!panel || handledPanelQuery.current === panel) return;
    handledPanelQuery.current = panel;
    if (panel === "workflows" || panel === "audit") {
      setActivityTab(panel === "audit" ? "logs" : "workflows");
      setActivityOpen(true);
      return;
    }
    const agent = defaultAgentForPanel(graph.nodes, panel);
    if (!agent) return;
    setDrawerInitialTab(panel === "connections" || panel === "tools" ? "tools" : "overview");
    setSelectedAgent(agent);
    setSelectedEdge(null);
  }, [graph?.nodes]);

  const visibleNodes = useMemo(
    () => {
      if (viewFilter === "all") return nodes;
      const matchingAgents = nodes.filter(isAgentFlowNode).filter((node) => agentMatchesCanvasFilter(node.data, viewFilter));
      const visibleGroupIds = new Set(matchingAgents.map((node) => node.data.group));
      const agentsByGroup = new Map<string, AgentNodeData[]>();
      for (const agent of matchingAgents) {
        const groupAgents = agentsByGroup.get(agent.data.group) ?? [];
        groupAgents.push(agent.data);
        agentsByGroup.set(agent.data.group, groupAgents);
      }
      const filteredNodes: AgentFlowNode[] = [];
      for (const node of nodes) {
        if (isAgentFlowNode(node)) {
          if (agentMatchesCanvasFilter(node.data, viewFilter)) filteredNodes.push(node);
          continue;
        }
        if (!visibleGroupIds.has(node.data.id)) continue;
        const visibleGroupAgents = agentsByGroup.get(node.data.id) ?? [];
        filteredNodes.push({
          ...node,
          data: {
            ...node.data,
            agentCount: visibleGroupAgents.length,
            statusSummary: summarizeGroupStatus(visibleGroupAgents),
          },
        });
      }
      return filteredNodes;
    },
    [nodes, viewFilter],
  );
  const visibleNodeIds = new Set(visibleNodes.map((node) => node.id));
  const visibleEdges = edges.filter((edge) => visibleNodeIds.has(edge.source) && visibleNodeIds.has(edge.target));
  const visibleAgentNodes = visibleNodes.filter(isAgentFlowNode);
  const allAgentNodes = nodes.filter(isAgentFlowNode);
  const visibleGroupEdges = visibleEdges.filter((edge) => edge.data?.metadata?.group_edge);
  const activeAgentRuns = agentRuns.filter((run) => ["queued", "running", "started"].includes(run.status));
  const toolbarSummary = canvasToolbarSummaryItems(visibleAgentNodes.length, allAgentNodes.length, visibleGroupEdges.length, activeAgentRuns.length, viewFilter).join(" · ");

  function onCanvasNodesChange(changes: NodeChange<AgentFlowNode>[]) {
    setNodes((items) => fitGroupNodesToChildren(applyNodeChanges(changes, items)));
  }

  function autoLayout() {
    const groupIndex = new Map<string, number>();
    const agentCounts = new Map(
      nodes.filter(isAgentFlowNode).map((node) => [node.data.group, countAgentsInGroup(nodes.filter(isAgentFlowNode).map((item) => item.data), node.data.group)]),
    );
    setNodes((items) =>
      fitGroupNodesToChildren(items.map((node) => {
        if (!isAgentFlowNode(node)) {
          const layout = groupLayouts.get(node.data.id) ?? defaultGroupLayout(groupLayouts.size, 1);
          return {
            ...node,
            position: { x: layout.x, y: layout.y },
            data: { ...node.data, width: layout.width, height: layout.height },
            style: { width: layout.width, height: layout.height },
          };
        }
        const index = groupIndex.get(node.data.group) ?? 0;
        groupIndex.set(node.data.group, index + 1);
        const layout = groupLayouts.get(node.data.group) ?? defaultGroupLayout(groupLayouts.size, agentCounts.get(node.data.group) ?? 1);
        const position = positionAgentInGroup(node.data, index, agentCounts.get(node.data.group) ?? 1, layout);
        return {
          ...node,
          parentId: groupNodeId(node.data.group),
          extent: "parent" as const,
          expandParent: true,
          position,
          style: { width: AGENT_CARD_WIDTH, height: AGENT_CARD_HEIGHT },
          data: { ...node.data, position },
        };
      })),
    );
  }

  async function saveCanvas() {
    await onSaveLayout(
      nodes.filter(isAgentFlowNode).map((node) => ({ id: node.id, position: node.position })),
      edges.filter((edge) => !edge.data?.metadata?.group_edge).map((edge) => ({ id: edge.id, status: edge.data?.status })),
    );
  }

  return (
    <div className="qto-agent-page">
      <div className="qto-page-heading qto-canvas-heading">
        <div>
          <Typography.Title level={2}>智能体管理</Typography.Title>
        </div>
      </div>

      <div className="qto-canvas-layout">
        <main className="qto-canvas-workspace" data-testid="agent-canvas">
          <div className="qto-canvas-toolbar" data-contract="agent canvas fixed stage toolbar primary action more menu no overlay">
            <div className="qto-canvas-primary-actions">
              <Button icon={<PlusOutlined />} type="primary" onClick={() => setNewAgentOpen(true)}>新增智能体</Button>
              <Dropdown
                trigger={["click"]}
                menu={{
                  items: [
                    { key: "layout", icon: <CompressOutlined />, label: "自动布局" },
                    { key: "save", icon: <SaveOutlined />, label: "保存画布" },
                    { key: "refresh", icon: <ReloadOutlined />, label: "刷新状态" },
                    { key: "activity", label: "运行动态" },
                  ],
                  onClick: ({ key }) => {
                    if (key === "layout") autoLayout();
                    if (key === "save") void saveCanvas();
                    if (key === "refresh") onRefresh();
                    if (key === "activity") setActivityOpen(true);
                  },
                }}
              >
                <Button icon={<MoreOutlined />}>画布操作</Button>
              </Dropdown>
            </div>
            <div className="qto-canvas-toolbar-status" data-contract="agent canvas single view filter in fixed toolbar activity entry in action menu no bottom overlay; agent canvas filtered view hides empty group lanes and recomputes group counts">
              <span data-contract="agent canvas toolbar uses Chinese compact counts; agent canvas toolbar hides zero running count">{toolbarSummary}</span>
              <Dropdown
                trigger={["click"]}
                menu={{
                  items: [
                    { key: "all", label: viewFilter === "all" ? "✓ 全部" : "全部" },
                    { key: "running", label: viewFilter === "running" ? "✓ 运行中" : "运行中" },
                    { key: "attention", label: viewFilter === "attention" ? "✓ 待处理/异常" : "待处理/异常" },
                    { key: "disconnected", label: viewFilter === "disconnected" ? "✓ 未连接" : "未连接" },
                  ],
                  onClick: ({ key }) => {
                    setViewFilter(key as AgentCanvasViewFilter);
                  },
                }}
              >
                <Button size="small">视图筛选</Button>
              </Dropdown>
            </div>
          </div>
          <ReactFlow
            nodes={visibleNodes}
            edges={visibleEdges}
            nodeTypes={NODE_TYPES}
            fitView
            fitViewOptions={{ padding: 0.12, minZoom: 0.36, maxZoom: 0.86 }}
            minZoom={0.34}
            maxZoom={1.08}
            onlyRenderVisibleElements
            elementsSelectable
            onNodesChange={onCanvasNodesChange}
            onEdgesChange={onEdgesChange}
            onPaneClick={() => {
              setSelectedAgent(null);
              setSelectedEdge(null);
              setDrawerInitialTab("overview");
            }}
            onNodeClick={(_, node) => {
              if (!isAgentFlowNode(node)) return;
              setDrawerInitialTab("overview");
              setSelectedAgent(node.data);
              setSelectedEdge(null);
            }}
            onEdgeClick={(_, edge) => {
              setSelectedAgent(null);
              setSelectedEdge(edge.data ?? null);
            }}
          >
            <Controls showInteractive={false} />
            <MiniMap
              className="qto-canvas-minimap"
              nodeColor={(node) => minimapNodeColor(node as AgentFlowNode)}
              nodeStrokeWidth={3}
              pannable
              zoomable
              data-contract="agent canvas minimap provides large-canvas orientation without changing tool stack"
            />
            <Background />
          </ReactFlow>
        </main>

        <AgentConfigDrawer
          open={Boolean(selectedAgent || selectedEdge)}
          onClose={() => {
            setSelectedAgent(null);
            setSelectedEdge(null);
          }}
          agent={selectedAgent}
          edge={selectedEdge}
          initialTab={drawerInitialTab}
          groups={graph?.groups ?? []}
          agentRuns={agentRuns}
          workflows={workflows}
          onPatchAgent={onPatchAgent}
          onRunAgent={onRunAgent}
          onConnectTool={onConnectTool}
          onTestTool={onTestTool}
        />
      </div>

      <Modal
        title="新增智能体"
        open={newAgentOpen}
        onCancel={() => setNewAgentOpen(false)}
        okText="保存"
        cancelText="取消"
        onOk={async () => {
          const name = newAgentDraft.name.trim() || newAgentDraft.template;
          await onCreateAgent({
            name,
            role: newAgentDraft.role.trim() || "自定义智能体",
            group: newAgentDraft.group,
            permissions: { can_research: true, can_execute_live_trade: false },
            prompt_config: { system_prompt: newAgentDraft.role.trim() || name },
          });
          setNewAgentOpen(false);
          setNewAgentDraft({ template: "Blank Agent", name: "", role: "", group: "research" });
        }}
      >
        <Space direction="vertical" size={12} className="full-width">
          <label className="qto-form-field">
            <span>模板</span>
            <Select value={newAgentDraft.template} onChange={(template) => setNewAgentDraft({ ...newAgentDraft, template })} options={AGENT_TEMPLATE_OPTIONS} data-contract="new agent template labels localized while preserving agent template values" />
          </label>
          <div className="qto-form-grid">
            <label className="qto-form-field">
              <span>名称</span>
              <Input placeholder="例如 研究助理" value={newAgentDraft.name} onChange={(event) => setNewAgentDraft({ ...newAgentDraft, name: event.target.value })} />
            </label>
            <label className="qto-form-field">
              <span>分组</span>
              <Select value={newAgentDraft.group} onChange={(group) => setNewAgentDraft({ ...newAgentDraft, group })} options={orderedGroups.map((group) => ({ value: group.id, label: agentGroupLabel(group.id, group.label) }))} />
            </label>
          </div>
          <label className="qto-form-field">
            <span>角色说明</span>
            <Input placeholder="说明这个 agent 负责什么" value={newAgentDraft.role} onChange={(event) => setNewAgentDraft({ ...newAgentDraft, role: event.target.value })} />
          </label>
        </Space>
      </Modal>

      <Modal title="运行动态" open={activityOpen} onCancel={() => setActivityOpen(false)} footer={null} width={680}>
        <Tabs
          className="qto-activity-tabs"
          activeKey={activityTab}
          onChange={setActivityTab}
          data-contract="agent canvas activity modal tabs no three-column log wall"
          items={[
            {
              key: "runs",
              label: activityTabLabel("任务", agentRuns.length),
              children: <ActivityList emptyText="暂无任务" rows={agentRunActivityRows(agentRuns)} />,
            },
            {
              key: "workflows",
              label: activityTabLabel("工作流", workflows.length),
              children: <ActivityList emptyText="暂无工作流" rows={workflowActivityRows(workflows)} />,
            },
            {
              key: "logs",
              label: "最近日志",
              children: <ActivityList emptyText="暂无日志" rows={agentLogActivityRows(graph?.nodes ?? [])} />,
            },
          ]}
        />
      </Modal>
    </div>
  );
}

type ActivityRow = {
  id: string;
  label: string;
  detail?: string | null;
  status?: string;
};

function ActivityList({ rows, emptyText }: { rows: ActivityRow[]; emptyText: string }) {
  if (!rows.length) return <CompactEmpty>{emptyText}</CompactEmpty>;
  return (
    <div className="qto-activity-list" data-contract="agent canvas activity modal compact tab list">
      {rows.map((row) => (
        <ActivityRowItem key={row.id} row={row} />
      ))}
    </div>
  );
}

function activityTabLabel(label: string, count: number) {
  return count ? `${label} ${count}` : label;
}

function ActivityRowItem({ row }: { row: ActivityRow }) {
  const status = activityAttentionStatus(row.status);
  return (
    <div className="qto-log-row">
      <span className="qto-log-row-main">
        <strong>{row.label}</strong>
        {row.detail ? <small>{row.detail}</small> : null}
      </span>
      {status ? (
        <span data-contract="agent canvas activity status pill is attention-only">
          <StatusTag status={status} />
        </span>
      ) : null}
    </div>
  );
}

function activityAttentionStatus(status: string | undefined) {
  const value = status?.toLowerCase();
  return value && ["queued", "started", "running", "pending", "approval", "review", "failed", "fail", "error", "blocked", "rejected", "denied", "locked", "disconnected", "cancel", "warning", "degraded"].some((marker) => value.includes(marker))
    ? status
    : null;
}

function agentRunActivityRows(agentRuns: AgentRun[]): ActivityRow[] {
  return agentRuns.slice(0, 6).map((run) => ({
    id: run.id,
    label: agentRunActivityLabel(run),
    detail: agentRunActivityDetail(run),
    status: run.status,
  }));
}

function workflowActivityRows(workflows: WorkflowLink[]): ActivityRow[] {
  return workflows.slice(0, 6).map((workflow) => ({
    id: workflow.id ?? workflow.workflow_id,
    label: workflowActivityLabel(workflow.workflow_type),
    detail: ownerLinkedLabel(workflow.owner_type, workflow.owner_id),
    status: workflow.status,
  }));
}

function agentLogActivityRows(agents: AgentNodeData[]): ActivityRow[] {
  return agents
    .filter((agent) => Boolean(formatVisibleAgentAction(agent.last_action)))
    .slice(0, 6)
    .map((agent) => ({
      id: agent.id,
      label: agentDisplayName(agent.name),
      detail: formatVisibleAgentAction(agent.last_action) ?? "",
      status: agent.status,
    }));
}

function agentRunActivityLabel(run: AgentRun) {
  const agentName = typeof run.input_payload?.agent_name === "string" ? run.input_payload.agent_name.trim() : "";
  return agentName ? agentDisplayName(agentName) : activityTypeLabel(run.task_type);
}

function agentRunActivityDetail(run: AgentRun) {
  return [
    run.workflow_id ? `工作流 ${readableIdentifier(run.workflow_id)}` : null,
    run.error ? "有错误" : null,
  ].filter(Boolean).join(" · ") || null;
}

function workflowActivityLabel(workflowType: string) {
  return activityTypeLabel(workflowType);
}

function activityTypeLabel(type: string) {
  const labels: Record<string, string> = {
    BacktestWorkflow: "回测工作流",
    ConnectionTestWorkflow: "连接测试",
    DataIngestionWorkflow: "数据接入",
    PaperPromotionWorkflow: "Paper 升级",
    ResearchWorkflow: "研究工作流",
    RiskReviewWorkflow: "风控复核",
    StrategyRegistrationWorkflow: "策略注册",
    chat: "对话任务",
    doctor_trace: "诊断任务",
    openai_agent_plan: "研究计划",
    research: "研究任务",
  };
  return labels[type] ?? readableActivityType(type);
}

function readableActivityType(type: string) {
  const value = type.replace(/Workflow$/, " Workflow").replace(/[-_]/g, " ").trim();
  return value || "智能体任务";
}

function AgentGroupLane({ data }: { data: AgentGroupNodeData }) {
  return (
    <div
      className="qto-agent-group-lane"
      data-contract="group lane adapts to contained agent card bounds; group lane expands and shifts with child agent bounds; parent-controlled lane size no child expand overflow"
      style={{ "--group-color": data.color, width: data.width, height: data.height } as CSSProperties}
    >
      <Handle type="target" position={Position.Left} className="qto-group-handle" />
      <div className="qto-agent-group-lane-header" data-contract="agent canvas stage lane header uses task phase labels">
        <span className="qto-agent-group-stage" data-contract="agent group lane shows ordered stage index without changing backend group ids">{data.stageIndex}</span>
        <strong>{data.label}</strong>
        <span data-contract="agent group lane uses Chinese compact agent count">{data.agentCount} 个智能体</span>
      </div>
      {data.statusSummary ? (
        <div className="qto-agent-group-lane-summary" data-contract="agent group lane hides normal idle summary text">{data.statusSummary}</div>
      ) : null}
      <Handle type="source" position={Position.Right} className="qto-group-handle" />
    </div>
  );
}

function AgentNodeCard({ data }: { data: AgentNodeData }) {
  const footerItems = agentNodeAttentionItems(data);
  const task = formatAgentTask(data);
  return (
    <div className={`qto-agent-node qto-agent-node-${data.status}`} data-contract="agent node compact summary card no detail stack">
      <Handle type="target" position={Position.Left} />
      <div className="qto-agent-node-header">
        <div className="qto-agent-node-title">
          <strong>{agentDisplayName(data.name)}</strong>
          <span>{agentRoleLabel(data.name, data.role)}</span>
        </div>
        <span className="qto-agent-node-status qto-agent-status-dot" data-contract="agent node status text visible not color-only">
          <StatusTag status={data.status} />
        </span>
      </div>
      {task ? (
        <div className="qto-agent-node-task" data-contract="agent node hides idle task line">
          <span>{task}</span>
        </div>
      ) : null}
      {footerItems.length ? (
        <div className="qto-agent-node-footer" data-contract="agent node footer attention-only no normal tool or permission counts">
          {footerItems.map((item) => (
            <span key={item}>{item}</span>
          ))}
        </div>
      ) : null}
      <Handle type="source" position={Position.Right} />
    </div>
  );
}

function canvasToolbarSummaryItems(visibleAgents: number, totalAgents: number, groupFlows: number, activeRuns: number, viewFilter: AgentCanvasViewFilter) {
  return [
    `视图 ${agentCanvasViewFilterLabel(viewFilter)}`,
    visibleAgents === totalAgents ? `${totalAgents} 个智能体` : `显示 ${visibleAgents}/${totalAgents} 个智能体`,
    groupFlows ? `${groupFlows} 条流程` : null,
    activeRuns ? `运行 ${activeRuns}` : null,
  ].filter(Boolean) as string[];
}

function agentCanvasViewFilterLabel(viewFilter: AgentCanvasViewFilter) {
  const labels: Record<AgentCanvasViewFilter, string> = {
    all: "全部",
    running: "运行中",
    attention: "待处理/异常",
    disconnected: "未连接",
  };
  return labels[viewFilter];
}

function normalizeAgentPanelQuery(value: string | null) {
  const panel = value?.trim().toLowerCase();
  if (panel === "connections" || panel === "tools" || panel === "settings" || panel === "workflows" || panel === "audit") return panel;
  return null;
}

function defaultAgentForPanel(agents: AgentNodeData[], panel: string) {
  if (panel === "connections" || panel === "tools") {
    return agents.find((agent) => agent.tool_refs.length > 0) ?? agents[0] ?? null;
  }
  return agents[0] ?? null;
}

function sortAgentGroups(groups: AgentGroup[]) {
  const stageRank = new Map(STAGE_ORDER.map((id, index) => [id, index]));
  return [...groups].sort((left, right) => {
    const leftRank = stageRank.get(left.id) ?? STAGE_ORDER.length;
    const rightRank = stageRank.get(right.id) ?? STAGE_ORDER.length;
    return leftRank - rightRank || left.id.localeCompare(right.id);
  });
}

function agentMatchesCanvasFilter(agent: AgentNodeData, viewFilter: AgentCanvasViewFilter) {
  if (viewFilter === "running") return agent.status === "running";
  if (viewFilter === "attention") return ABNORMAL_STATUSES.has(agent.status);
  if (viewFilter === "disconnected") return agent.status === "disconnected";
  return true;
}

function buildGroupLayouts(groups: AgentGroup[], agents: AgentNodeData[]) {
  const layouts = new Map<string, GroupLayout>();
  const groupIds = new Set(groups.map((group) => group.id));
  const mainIds = groups.map((group) => group.id).filter((id) => id !== SYSTEM_GROUP_ID);
  const groupGraph = new dagre.graphlib.Graph();
  groupGraph.setDefaultEdgeLabel(() => ({}));
  groupGraph.setGraph({ rankdir: "LR", nodesep: GROUP_GAP, ranksep: GROUP_GAP, marginx: GROUP_LEFT * 2, marginy: GROUP_TOP * 2 });
  mainIds.forEach((id) => {
    const agentCount = countAgentsInGroup(agents, id);
    const size = groupSize(id, agentCount);
    groupGraph.setNode(id, { width: size.width, height: size.height });
  });
  for (const edge of buildPrimaryGroupPairs(groups, agents)) {
    groupGraph.setEdge(edge.source, edge.target);
  }
  dagre.layout(groupGraph);
  const positionedGroups = mainIds.map((id, index) => {
    const size = groupSize(id, countAgentsInGroup(agents, id));
    const node = groupGraph.node(id);
    return {
      id,
      left: node ? node.x - size.width / 2 : index * (size.width + GROUP_GAP),
      top: node ? node.y - size.height / 2 : 0,
      ...size,
    };
  });
  const minLeft = Math.min(0, ...positionedGroups.map((item) => item.left));
  const minTop = Math.min(0, ...positionedGroups.map((item) => item.top));
  positionedGroups.forEach((item) => {
    layouts.set(item.id, {
      x: GROUP_LEFT + item.left - minLeft,
      y: GROUP_TOP + item.top - minTop,
      width: item.width,
      height: item.height,
    });
  });
  if (groupIds.has(SYSTEM_GROUP_ID)) {
    const mainBottom = [...layouts.values()].reduce((max, layout) => Math.max(max, layout.y + layout.height), GROUP_TOP);
    const systemSize = groupSize(SYSTEM_GROUP_ID, countAgentsInGroup(agents, SYSTEM_GROUP_ID));
    layouts.set(SYSTEM_GROUP_ID, {
      x: GROUP_LEFT,
      y: mainBottom + 78,
      width: systemSize.width,
      height: systemSize.height,
    });
  }
  return layouts;
}

function buildPrimaryGroupPairs(groups: AgentGroup[], agents: AgentNodeData[]) {
  const groupIds = new Set(groups.map((group) => group.id));
  const agentById = new Map(agents.map((agent) => [agent.id, agent]));
  const pairs = [
    ["data-agent", "research-agent"],
    ["research-agent", "strategy-agent"],
    ["strategy-agent", "backtest-agent"],
    ["backtest-agent", "risk-agent"],
    ["risk-agent", "approval-agent"],
    ["approval-agent", "execution-agent"],
  ];
  const seen = new Set<string>();
  return pairs.flatMap(([sourceId, targetId]) => {
    const source = agentById.get(sourceId);
    const target = agentById.get(targetId);
    if (!source || !target || source.group === target.group || !groupIds.has(source.group) || !groupIds.has(target.group)) return [];
    const key = `${source.group}->${target.group}`;
    if (seen.has(key)) return [];
    seen.add(key);
    return [{ source: source.group, target: target.group }];
  });
}

function shouldRenderAgentEdge(edge: AgentEdgeData, agentById: Map<string, AgentNodeData>) {
  if (edge.relation_type === "monitoring") return false;
  const source = agentById.get(edge.source);
  const target = agentById.get(edge.target);
  return Boolean(source && target && source.group === target.group);
}

function defaultGroupLayout(index: number, agentCount: number) {
  const size = groupSize("", agentCount);
  return {
    x: GROUP_LEFT + index * (size.width + GROUP_GAP),
    y: GROUP_TOP,
    width: size.width,
    height: size.height,
  };
}

function positionAgentInGroup(node: AgentNodeData, index: number, agentCount: number, layout?: GroupLayout) {
  const metrics = agentGridMetrics(node.group, agentCount);
  const columns = metrics.columns;
  const column = index % columns;
  const row = Math.floor(index / columns);
  const groupWidth = layout?.width ?? metrics.groupWidth;
  const groupHeight = layout?.height ?? metrics.groupHeight;
  const lane = agentLaneBounds(groupWidth, groupHeight);
  const contentWidth = metrics.contentWidth;
  const maxStartX = Math.max(lane.left, lane.right - contentWidth);
  const startX = node.group === SYSTEM_GROUP_ID
    ? lane.left
    : Math.min(maxStartX, Math.max(lane.left, Math.floor(lane.left + (lane.width - contentWidth) / 2)));
  const position = {
    x: startX + column * (AGENT_CARD_WIDTH + AGENT_X_GAP),
    y: lane.top + row * (AGENT_CARD_HEIGHT + AGENT_Y_GAP),
  };
  return clampAgentPositionToLane(position, lane);
}

function fitGroupNodesToChildren(items: AgentFlowNode[]) {
  const agentCounts = countAgentNodesByGroup(items);
  const baseSized = items.map((node) => {
    if (isAgentFlowNode(node)) return node;
    const base = groupSize(node.data.id, agentCounts.get(node.data.id) ?? 1);
    return {
      ...node,
      data: { ...node.data, width: base.width, height: base.height },
      style: { ...node.style, width: base.width, height: base.height },
    };
  });
  const childBounds = measureAgentBoundsByGroup(baseSized);
  const adjustments = groupAdjustmentsForChildBounds(baseSized, agentCounts, childBounds);
  const adjusted = baseSized.map((node) => {
    if (isAgentFlowNode(node)) {
      const adjustment = adjustments.get(node.data.group);
      if (!adjustment) return node;
      const position = {
        x: node.position.x - adjustment.dx,
        y: node.position.y - adjustment.dy,
      };
      return {
        ...node,
        position,
        data: { ...node.data, position },
      };
    }
    const adjustment = adjustments.get(node.data.id);
    if (!adjustment) return node;
    return {
      ...node,
      position: {
        x: node.position.x + adjustment.dx,
        y: node.position.y + adjustment.dy,
      },
      data: { ...node.data, width: adjustment.width, height: adjustment.height },
      style: { ...node.style, width: adjustment.width, height: adjustment.height },
    };
  });
  return normalizeAgentNodesToGroupLanes(adjusted);
}

function groupAdjustmentsForChildBounds(
  items: AgentFlowNode[],
  agentCounts: Map<string, number>,
  childBounds: Map<string, AgentChildBounds>,
) {
  const adjustments = new Map<string, { dx: number; dy: number; width: number; height: number }>();
  for (const node of items) {
    if (isAgentFlowNode(node)) continue;
    const bounds = childBounds.get(node.data.id);
    if (!bounds) continue;
    const base = groupSize(node.data.id, agentCounts.get(node.data.id) ?? 1);
    const dx = Math.min(0, bounds.left - AGENT_LEFT_OFFSET);
    const dy = Math.min(0, bounds.top - AGENT_TOP_OFFSET);
    adjustments.set(node.data.id, {
      dx,
      dy,
      width: Math.max(base.width - dx, bounds.right - dx + GROUP_RIGHT_PADDING),
      height: Math.max(base.height - dy, bounds.bottom - dy + GROUP_BOTTOM_PADDING),
    });
  }
  return adjustments;
}

function countAgentNodesByGroup(items: AgentFlowNode[]) {
  const counts = new Map<string, number>();
  for (const node of items) {
    if (!isAgentFlowNode(node)) continue;
    counts.set(node.data.group, (counts.get(node.data.group) ?? 0) + 1);
  }
  return counts;
}

function numericNodeSize(value: unknown) {
  return typeof value === "number" ? value : 0;
}

function measureAgentBoundsByGroup(items: AgentFlowNode[]) {
  const boundsByGroup = new Map<string, AgentChildBounds>();
  for (const node of items) {
    if (!isAgentFlowNode(node)) continue;
    const current = boundsByGroup.get(node.data.group);
    const visualBounds = agentVisualBounds(node);
    const next = {
      left: Math.min(current?.left ?? Number.POSITIVE_INFINITY, visualBounds.left),
      top: Math.min(current?.top ?? Number.POSITIVE_INFINITY, visualBounds.top),
      right: Math.max(current?.right ?? Number.NEGATIVE_INFINITY, visualBounds.right),
      bottom: Math.max(current?.bottom ?? Number.NEGATIVE_INFINITY, visualBounds.bottom),
    };
    boundsByGroup.set(node.data.group, {
      ...next,
      width: next.right - next.left,
      height: next.bottom - next.top,
    });
  }
  return boundsByGroup;
}

function normalizeAgentNodesToGroupLanes(items: AgentFlowNode[]) {
  const groupNodes = new Map(items.filter((node) => !isAgentFlowNode(node)).map((node) => [node.id, node]));
  return items.map((node) => {
    if (!isAgentFlowNode(node)) return node;
    const group = groupNodes.get(groupNodeId(node.data.group));
    if (!group) return node;
    const lane = agentLaneBounds(group.data.width, group.data.height);
    const position = clampAgentPositionToLane(node.position, lane, agentNodeDimensions(node));
    return {
      ...node,
      position,
      data: { ...node.data, position },
    };
  });
}

function agentVisualBounds(node: AgentNodeFlowNode) {
  const size = agentNodeDimensions(node);
  return {
    left: node.position.x - AGENT_VISUAL_CLEARANCE,
    top: node.position.y - AGENT_VISUAL_CLEARANCE,
    right: node.position.x + size.width + AGENT_VISUAL_CLEARANCE,
    bottom: node.position.y + size.height + AGENT_VISUAL_CLEARANCE,
  };
}

function agentNodeDimensions(node: AgentNodeFlowNode): AgentNodeDimensions {
  return {
    width: Math.max(AGENT_CARD_WIDTH, numericNodeSize(node.style?.width)),
    height: Math.max(AGENT_CARD_HEIGHT, numericNodeSize(node.style?.height)),
  };
}

function buildGroupEdges(graph: AgentGraph): AgentFlowEdge[] {
  const agentById = new Map(graph.nodes.map((node) => [node.id, node]));
  const groupById = new Map(graph.groups.map((group) => [group.id, group]));
  const grouped = new Map<string, { source: string; target: string; relationTypes: Set<string>; workflowTypes: Set<string>; status: string }>();
  for (const edge of graph.edges) {
    if (edge.relation_type === "monitoring") continue;
    const source = agentById.get(edge.source);
    const target = agentById.get(edge.target);
    if (!source || !target || source.group === target.group) continue;
    const key = `${source.group}->${target.group}`;
    const item = grouped.get(key) ?? { source: source.group, target: target.group, relationTypes: new Set<string>(), workflowTypes: new Set<string>(), status: "idle" };
    item.relationTypes.add(edge.relation_type);
    if (edge.workflow_type) item.workflowTypes.add(edge.workflow_type);
    if (["blocked", "failed"].includes(edge.status)) item.status = edge.status;
    if (edge.status === "active" && item.status === "idle") item.status = "active";
    grouped.set(key, item);
  }
  return [...grouped.values()].map((item) => {
    const sourceGroup = groupById.get(item.source);
    const targetGroup = groupById.get(item.target);
    return {
      id: `group-flow:${item.source}->${item.target}`,
      source: groupNodeId(item.source),
      target: groupNodeId(item.target),
      type: "smoothstep",
      markerEnd: { type: MarkerType.ArrowClosed },
      data: {
        id: `group-flow:${item.source}->${item.target}`,
        source: agentStageLabel(sourceGroup?.id ?? item.source, sourceGroup?.label),
        target: agentStageLabel(targetGroup?.id ?? item.target, targetGroup?.label),
        relation_type: "group_flow",
        workflow_type: [...item.workflowTypes].join(", ") || null,
        status: item.status,
        metadata: { group_edge: true, relation_types: [...item.relationTypes], workflow_types: [...item.workflowTypes] },
      },
      style: {
        stroke: item.status === "blocked" || item.status === "failed" ? "#dc2626" : "#334155",
        strokeWidth: 2.8,
        strokeDasharray: "7 5",
      },
    };
  });
}

function groupNodeId(groupId: string) {
  return `${GROUP_NODE_PREFIX}${groupId}`;
}

function agentStageLabel(groupId: string, fallback: string | undefined) {
  const labels: Record<string, string> = {
    data: "数据接入",
    research: "研究与策略",
    validation: "回测与风控",
    trading: "审批与执行",
    system: "监控与审计",
  };
  return labels[groupId] ?? agentGroupLabel(groupId, fallback);
}

function agentStageIndex(groupId: string) {
  const index = STAGE_ORDER.indexOf(groupId);
  return index >= 0 ? String(index + 1).padStart(2, "0") : "--";
}

function isAgentFlowNode(node: AgentFlowNode): node is AgentNodeFlowNode {
  return node.type === "agent";
}

function summarizeGroupStatus(agents: AgentNodeData[]) {
  if (!agents.length) return "";
  const failed = agents.filter((agent) => ["blocked", "failed"].includes(agent.status)).length;
  const waiting = agents.filter((agent) => ["waiting_approval", "locked"].includes(agent.status)).length;
  const running = agents.filter((agent) => agent.status === "running").length;
  if (failed) return `${failed} 个异常`;
  if (waiting) return `${waiting} 个待处理`;
  if (running) return `${running} 个运行中`;
  return "";
}

function groupSize(groupId: string, agentCount: number) {
  const metrics = agentGridMetrics(groupId, agentCount);
  return fitGroupSizeToAgentBounds(metrics);
}

function fitGroupSizeToAgentBounds(metrics: AgentGridMetrics) {
  return {
    width: Math.max(GROUP_MIN_WIDTH, AGENT_LEFT_OFFSET + AGENT_VISUAL_CLEARANCE + metrics.contentWidth + AGENT_VISUAL_CLEARANCE + GROUP_RIGHT_PADDING),
    height: AGENT_TOP_OFFSET + AGENT_VISUAL_CLEARANCE + metrics.contentHeight + AGENT_VISUAL_CLEARANCE + GROUP_BOTTOM_PADDING,
  };
}

function agentGridMetrics(groupId: string, agentCount: number): AgentGridMetrics {
  const count = Math.max(1, agentCount);
  const columns = columnsForGroup(groupId, count);
  const rows = Math.ceil(count / columns);
  const contentWidth = columns * AGENT_CARD_WIDTH + Math.max(0, columns - 1) * AGENT_X_GAP;
  const contentHeight = rows * AGENT_CARD_HEIGHT + Math.max(0, rows - 1) * AGENT_Y_GAP;
  return {
    columns,
    rows,
    contentWidth,
    contentHeight,
    groupWidth: Math.max(GROUP_MIN_WIDTH, AGENT_LEFT_OFFSET + contentWidth + GROUP_RIGHT_PADDING),
    groupHeight: AGENT_TOP_OFFSET + contentHeight + GROUP_BOTTOM_PADDING,
  };
}

function agentLaneBounds(groupWidth: number, groupHeight: number): AgentLaneBounds {
  return {
    left: AGENT_LEFT_OFFSET + AGENT_VISUAL_CLEARANCE,
    top: AGENT_TOP_OFFSET + AGENT_VISUAL_CLEARANCE,
    right: groupWidth - GROUP_RIGHT_PADDING - AGENT_VISUAL_CLEARANCE,
    bottom: groupHeight - GROUP_BOTTOM_PADDING - AGENT_VISUAL_CLEARANCE,
    width: Math.max(AGENT_CARD_WIDTH, groupWidth - AGENT_LEFT_OFFSET - GROUP_RIGHT_PADDING - AGENT_VISUAL_CLEARANCE * 2),
    height: Math.max(AGENT_CARD_HEIGHT, groupHeight - AGENT_TOP_OFFSET - GROUP_BOTTOM_PADDING - AGENT_VISUAL_CLEARANCE * 2),
  };
}

function clampAgentPositionToLane(
  position: { x: number; y: number },
  lane: AgentLaneBounds,
  size: AgentNodeDimensions = { width: AGENT_CARD_WIDTH, height: AGENT_CARD_HEIGHT },
) {
  return {
    x: clamp(position.x, lane.left, Math.max(lane.left, lane.right - size.width)),
    y: clamp(position.y, lane.top, Math.max(lane.top, lane.bottom - size.height)),
  };
}

function clamp(value: number, min: number, max: number) {
  return Math.min(max, Math.max(min, value));
}

function minimapNodeColor(node: AgentFlowNode) {
  if (!isAgentFlowNode(node)) {
    return typeof node.data.color === "string" ? node.data.color : "#cbd5e1";
  }
  const tone = getStatusTone(node.data.status);
  const colors: Record<string, string> = {
    blue: "#2563eb",
    green: "#0f766e",
    gray: "#94a3b8",
    red: "#dc2626",
    yellow: "#d97706",
  };
  return colors[tone] ?? "#64748b";
}

function columnsForGroup(groupId: string, agentCount: number) {
  const count = Math.max(1, agentCount);
  if (groupId === SYSTEM_GROUP_ID) return Math.min(count, 4);
  return count >= 3 ? 2 : 1;
}

function countAgentsInGroup(agents: AgentNodeData[], groupId: string) {
  return agents.filter((agent) => agent.group === groupId).length || 1;
}

function getStatusTone(status: string) {
  if (["blocked", "failed"].includes(status)) return "red";
  if (status === "locked") return "red";
  if (status === "waiting_approval") return "yellow";
  if (status === "running") return "blue";
  if (["idle", "disconnected"].includes(status)) return "gray";
  return "green";
}

function formatAgentStatus(status: string) {
  const labels: Record<string, string> = {
    idle: "空闲",
    running: "运行中",
    blocked: "阻塞",
    failed: "失败",
    waiting_approval: "待审批",
    locked: "已锁定",
    disconnected: "未连接",
  };
  return labels[status] ?? status;
}

function formatAgentTask(agent: AgentNodeData) {
  return agent.current_task?.trim() || formatVisibleAgentAction(agent.last_action);
}

function formatVisibleAgentAction(action: string | null | undefined) {
  const value = action?.trim();
  if (!value || isSeededDefaultAgentAction(value)) return null;
  return value;
}

function isSeededDefaultAgentAction(action: string) {
  return action.toLowerCase() === "seeded default agent";
}

function agentNodeAttentionItems(agent: AgentNodeData) {
  const activePermissions = Object.entries(agent.permissions ?? {}).filter(([, enabled]) => enabled).length;
  return [
    summarizeToolAttention(agent.tool_refs),
    activePermissions ? null : "无权限",
    agent.human_action_required ? "需人工" : null,
  ].filter(Boolean) as string[];
}

function summarizeToolAttention(tools: AgentToolRef[]) {
  const disconnected = tools.filter((tool) => ["disconnected", "failed", "error"].includes(tool.status)).length;
  return disconnected ? `工具异常 ${disconnected}/${tools.length}` : null;
}
