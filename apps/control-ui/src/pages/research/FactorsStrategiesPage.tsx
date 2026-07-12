import { List, Space, Tabs, Typography } from "antd";
import type { FactorSpec, RiskReview, StrategySpec } from "../../api/types";
import { CompactEmpty } from "../../components/CompactEmpty";
import { StatusTag } from "../../components/StatusTag";

export function FactorsStrategiesPage({
  factors,
  strategies,
  risks,
  activeTab,
  onTabChange,
  onFactorClick,
  onStrategyClick,
}: {
  factors: FactorSpec[];
  strategies: StrategySpec[];
  risks: RiskReview[];
  activeTab: "factors" | "strategies";
  onTabChange: (tab: "factors" | "strategies") => void;
  onFactorClick: (factor: FactorSpec) => void;
  onStrategyClick: (strategy: StrategySpec) => void;
}) {
  return (
    <Space direction="vertical" size={18} className="full-width">
      <div className="qto-page-heading">
        <div>
          <Typography.Title level={2}>因子和策略</Typography.Title>
        </div>
      </div>
      <section className="qto-library-section" data-contract="factors strategies lightweight section no card wrapper">
        <Tabs
          activeKey={activeTab}
          onChange={(key) => onTabChange(key as "factors" | "strategies")}
          items={[
            {
              key: "factors",
              label: "因子库",
              children: (
                <List
                  className="qto-library-list"
                  rowKey="id"
                  dataSource={factors}
                  locale={{ emptyText: <CompactEmpty>暂无因子</CompactEmpty> }}
                  renderItem={(row) => {
                    const summary = factorInlineSummary(row);
                    const action = factorPriorityAction(row);
                    const status = libraryAttentionStatus(row.status);
                    return (
                      <List.Item
                        className="qto-library-row"
                        data-contract="library row opens detail no repeated button"
                        role="button"
                        tabIndex={0}
                        onClick={() => onFactorClick(row)}
                        onKeyDown={(event) => {
                          if (event.key === "Enter" || event.key === " ") {
                            event.preventDefault();
                            onFactorClick(row);
                          }
                        }}
                      >
                        <div className="qto-library-list-line" data-contract="factors strategies compact single-line row no stacked metadata">
                          <span className="qto-library-list-main">
                            <strong>{row.name}</strong>
                            {summary ? (
                              <span className="qto-library-summary" data-contract="factors strategies compact one-line list summary; factors strategies summary only shows available metrics; factors strategies summary renders only when populated">
                                {summary}
                              </span>
                            ) : null}
                            {action ? (
                              <span className="qto-library-action" data-contract="factors strategies list shows actionable research priority only when meaningful">
                                {action}
                              </span>
                            ) : null}
                          </span>
                          {status ? (
                            <span data-contract="factors strategies list status pill is attention-only">
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
            {
              key: "strategies",
              label: "策略库",
              children: (
                <List
                  className="qto-library-list"
                  rowKey="id"
                  dataSource={strategies}
                  locale={{ emptyText: <CompactEmpty>暂无策略</CompactEmpty> }}
                  renderItem={(row) => {
                    const risk = latestRisk(risks, row.id);
                    const lifecycleItems = strategyLifecycleItems(row, risk);
                    const summary = strategyListSummary(row);
                    const action = strategyPriorityAction(row, risk);
                    const status = lifecycleItems.length ? null : libraryAttentionStatus(row.status);
                    return (
                      <List.Item
                        className="qto-library-row"
                        data-contract="library row opens detail no repeated button"
                        role="button"
                        tabIndex={0}
                        onClick={() => onStrategyClick(row)}
                        onKeyDown={(event) => {
                          if (event.key === "Enter" || event.key === " ") {
                            event.preventDefault();
                            onStrategyClick(row);
                          }
                        }}
                      >
                        <div className="qto-library-list-line" data-contract="factors strategies compact single-line row no stacked metadata">
                          <span className="qto-library-list-main">
                            <strong>{row.name}</strong>
                            {summary ? (
                              <span className="qto-library-summary" data-contract="factors strategies compact one-line list summary; factors strategies summary only shows available metrics; factors strategies summary renders only when populated">
                                {summary}
                              </span>
                            ) : null}
                          {lifecycleItems.length ? (
                            <span className="qto-library-status-line" data-contract="strategy lifecycle compact attention-only status line">
                              {lifecycleItems.join(" · ")}
                            </span>
                          ) : null}
                          {action ? (
                            <span className="qto-library-action" data-contract="factors strategies list shows actionable research priority only when meaningful">
                              {action}
                            </span>
                          ) : null}
                          </span>
                          {status ? (
                            <span data-contract="factors strategies list status pill is attention-only">
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
      </section>
    </Space>
  );
}

function factorInlineSummary(row: FactorSpec) {
  return factorListSummary(row);
}

function factorListSummary(row: FactorSpec) {
  return [
    metricSummary("IC", row.metrics, "ic"),
    metricSummary("Coverage", row.metrics, "coverage"),
  ].filter(Boolean).join(" · ");
}

function factorPriorityAction(row: FactorSpec) {
  if (libraryAttentionStatus(row.status)) return `处理状态 ${formatLifecycleStatus(row.status)}`;
  if (!hasMetricValue(row.metrics, "ic") || !hasMetricValue(row.metrics, "coverage")) return "补充因子分析";
  if (!row.artifacts.length) return "生成分析报告";
  return null;
}

function strategyListSummary(row: StrategySpec) {
  return [
    row.universe || null,
    row.factors?.length ? `${row.factors.length} 个因子` : null,
  ].filter(Boolean).join(" · ");
}

function strategyPriorityAction(strategy: StrategySpec, risk: RiskReview | undefined) {
  if (!strategy.factors?.length) return "补充使用因子";
  if (risk?.verdict && !isPositiveStatus(risk.verdict)) return `处理风控 ${formatLifecycleStatus(risk.verdict)}`;
  const approval = strategy.card?.approval_status;
  if (approval && !["none", "approved"].includes(approval)) return `处理审批 ${formatLifecycleStatus(approval)}`;
  const paper = strategy.card?.paper_trading_status;
  if (paper && !["not_started", "none", "approved"].includes(paper)) return `检查 Paper ${formatLifecycleStatus(paper)}`;
  const live = strategy.card?.live_trading_status;
  if (live && !["locked", "none"].includes(live)) return `检查 Live ${formatLifecycleStatus(live)}`;
  if (libraryAttentionStatus(strategy.status)) return `处理状态 ${formatLifecycleStatus(strategy.status)}`;
  return null;
}

function latestRisk(risks: RiskReview[], strategyId: string) {
  return risks.find((item) => item.strategy_id === strategyId);
}

function strategyLifecycleItems(strategy: StrategySpec, risk: RiskReview | undefined) {
  const items: string[] = [];
  if (risk?.verdict && !isPositiveStatus(risk.verdict)) items.push(`风控 ${formatLifecycleStatus(risk.verdict)}`);
  const approval = strategy.card?.approval_status;
  if (approval && !["none", "approved"].includes(approval)) items.push(`审批 ${formatLifecycleStatus(approval)}`);
  const paper = strategy.card?.paper_trading_status;
  if (paper && !["not_started", "none"].includes(paper)) items.push(`Paper ${formatLifecycleStatus(paper)}`);
  const live = strategy.card?.live_trading_status;
  if (live && !["locked", "none"].includes(live)) items.push(`Live ${formatLifecycleStatus(live)}`);
  return items;
}

function formatLifecycleStatus(status: string) {
  const labels: Record<string, string> = {
    approved: "已通过",
    blocked: "阻塞",
    completed: "已完成",
    denied: "已拒绝",
    failed: "失败",
    pending: "待处理",
    queued: "排队中",
    rejected: "已拒绝",
    requires_review: "待复核",
    running: "运行中",
    started: "运行中",
    warning: "注意",
  };
  return labels[status] ?? status.replace(/_/g, " ");
}

function isPositiveStatus(status: string) {
  return ["pass", "passed", "approved", "ok", "healthy"].includes(status.toLowerCase());
}

function libraryAttentionStatus(status: string) {
  const value = status.toLowerCase();
  if (["pending", "review", "blocked", "failed", "fail", "rejected", "denied", "warning", "error", "locked", "missing", "unavailable", "disconnected", "degraded"].some((marker) => value.includes(marker))) return status;
  return null;
}

function metricSummary(label: string, metrics: Record<string, unknown> | undefined, key: string) {
  const value = metrics?.[key];
  if (value === undefined || value === null || value === "") return null;
  if (typeof value === "number") return `${label} ${value.toFixed(2)}`;
  return `${label} ${value}`;
}

function hasMetricValue(metrics: Record<string, unknown> | undefined, key: string) {
  const value = metrics?.[key];
  return value !== undefined && value !== null && value !== "";
}
