import { FilterOutlined, MoreOutlined } from "@ant-design/icons";
import { Button, Dropdown, Input, List, Modal, Select, Space, Typography } from "antd";
import { useMemo, useState } from "react";
import type { BacktestRun, StrategySpec } from "../../api/types";
import { CompactEmpty } from "../../components/CompactEmpty";
import { StatusTag, formatStatusLabel } from "../../components/StatusTag";
import { readableIdentifier } from "../../displayLabels";

const ROW_METRIC_KEYS = ["sharpe"];
const DETAIL_METRIC_KEYS = ["cagr", "sharpe", "max_drawdown", "turnover"];
type BacktestLaunchPayload = { strategy_id: string; dataset_version: string };

export function ExperimentsPage({
  backtests,
  strategies,
  onRunBacktest,
  onRequestRiskReview,
}: {
  backtests: BacktestRun[];
  strategies: StrategySpec[];
  onRunBacktest: (payload: BacktestLaunchPayload) => void | Promise<void>;
  onRequestRiskReview: (run: BacktestRun) => void | Promise<void>;
}) {
  const [strategyFilter, setStrategyFilter] = useState<string | undefined>();
  const [statusFilter, setStatusFilter] = useState<string | undefined>();
  const [selectedIds, setSelectedIds] = useState<string[]>([]);
  const [filterModalOpen, setFilterModalOpen] = useState(false);
  const [compareModalOpen, setCompareModalOpen] = useState(false);
  const [backtestModalOpen, setBacktestModalOpen] = useState(false);
  const [backtestSubmitting, setBacktestSubmitting] = useState(false);
  const [backtestDraft, setBacktestDraft] = useState<BacktestLaunchPayload>({ strategy_id: "", dataset_version: "" });
  const filtered = useMemo(
    () =>
      backtests.filter((run) => {
        if (strategyFilter && run.strategy_id !== strategyFilter) return false;
        if (statusFilter && run.status !== statusFilter) return false;
        return true;
      }),
    [backtests, statusFilter, strategyFilter],
  );
  const selectedRuns = selectedIds.map((id) => backtests.find((run) => run.id === id)).filter(Boolean) as BacktestRun[];
  const activeFilterCount = [strategyFilter, statusFilter].filter(Boolean).length;
  const filterSummary = activeFilterCount ? activeFilterSummary(strategyFilter, statusFilter, strategies, filtered.length, backtests.length) : null;

  function setRunSelected(id: string, checked: boolean) {
    setSelectedIds((items) => (checked ? [...new Set([...items, id])] : items.filter((item) => item !== id)));
  }

  function openBacktestModal() {
    setBacktestDraft({ strategy_id: strategyFilter ?? strategies[0]?.id ?? "", dataset_version: "" });
    setBacktestModalOpen(true);
  }

  async function submitBacktest() {
    const payload = { strategy_id: backtestDraft.strategy_id, dataset_version: backtestDraft.dataset_version.trim() };
    if (!payload.strategy_id || !payload.dataset_version) return;
    setBacktestSubmitting(true);
    try {
      await onRunBacktest(payload);
      setBacktestModalOpen(false);
      setBacktestDraft({ strategy_id: "", dataset_version: "" });
    } finally {
      setBacktestSubmitting(false);
    }
  }

  function clearFilters() {
    setStrategyFilter(undefined);
    setStatusFilter(undefined);
  }

  function clearCompareSelection() {
    setSelectedIds([]);
    setCompareModalOpen(false);
  }

  return (
    <Space direction="vertical" size={18} className="full-width">
      <div className="qto-page-heading">
        <div>
          <Typography.Title level={2}>实验与回测</Typography.Title>
        </div>
        <Button type="primary" onClick={openBacktestModal} disabled={!strategies.length}>启动回测</Button>
      </div>

      <section className="qto-run-section" data-contract="experiments lightweight section no card wrapper">
        <div className="qto-run-toolbar">
          <Space wrap size={8}>
            <Typography.Text strong>回测记录</Typography.Text>
          </Space>
          <Space wrap size={8}>
            {filterSummary ? (
              <Typography.Text type="secondary" className="qto-run-filter-summary" data-contract="experiments toolbar shows compact active filter summary only">
                {filterSummary}
              </Typography.Text>
            ) : null}
            <Button
              size="small"
              icon={<FilterOutlined />}
              className="qto-run-filter-button"
              data-contract="experiments filters live in modal not toolbar"
              onClick={() => setFilterModalOpen(true)}
            >
              筛选{activeFilterCount ? ` ${activeFilterCount}` : ""}
            </Button>
          </Space>
        </div>
        <List
          className="qto-run-list"
          rowKey="id"
          dataSource={filtered}
          locale={{ emptyText: <CompactEmpty>暂无回测记录</CompactEmpty> }}
          renderItem={(row) => {
            const status = runAttentionStatus(row.status);
            const actionHint = runActionHint(row);
            return (
              <List.Item
                className="qto-run-row"
                actions={[
                  <Dropdown
                    key="actions"
                    trigger={["click"]}
                    menu={{
                      items: [
                        { key: "compare", label: selectedIds.includes(row.id) ? "移出对比" : "加入对比" },
                        { key: "risk", label: "申请风控" },
                      ],
                      onClick: ({ key }) => {
                        if (key === "compare") setRunSelected(row.id, !selectedIds.includes(row.id));
                        if (key === "risk") onRequestRiskReview(row);
                      },
                    }}
                  >
                    <Button
                      size="small"
                      icon={<MoreOutlined />}
                      aria-label="回测操作"
                      data-contract="experiments icon-only action menu no persistent action text; experiments compact metrics and implemented action menu only; compare action lives in menu"
                    />
                  </Dropdown>,
                ]}
              >
                <div className="qto-run-list-line" data-contract="experiments compact single-line run row no stacked metadata">
                  <span className="qto-run-list-main">
                    <strong>{runTitle(row, strategies)}</strong>
                    <span className="qto-run-summary" data-contract="experiments compact one-line run summary">{runSummary(row)}</span>
                    <MetricLine metrics={row.metrics} keys={ROW_METRIC_KEYS} dataContract="experiments row metric line only shows primary metrics" />
                    {actionHint ? (
                      <span className="qto-run-action-hint" data-contract="experiments row shows next action hint without persistent action button">
                        {actionHint}
                      </span>
                    ) : null}
                  </span>
                  {status ? (
                    <span data-contract="experiments status pill is attention-only">
                      <StatusTag status={status} />
                    </span>
                  ) : null}
                </div>
              </List.Item>
            );
          }}
        />
        {selectedRuns.length ? (
          <div className="qto-compare-strip" data-contract="experiments compare compact summary opens modal no persistent compare rows">
            <div className="qto-compare-pill">
              <span>
                <strong>已选对比</strong>
                <Typography.Text type="secondary">{selectedRuns.length} 条记录</Typography.Text>
              </span>
              <Dropdown
                trigger={["click"]}
                menu={{
                  items: [
                    { key: "open-compare", label: "打开对比" },
                    { key: "clear-compare", label: "清空选择" },
                  ],
                  onClick: ({ key }) => {
                    if (key === "open-compare") setCompareModalOpen(true);
                    if (key === "clear-compare") clearCompareSelection();
                  },
                }}
              >
                <Button
                  size="small"
                  icon={<MoreOutlined />}
                  aria-label="对比操作"
                  data-contract="experiments compare strip uses icon-only action menu no persistent text buttons"
                />
              </Dropdown>
            </div>
          </div>
        ) : null}
      </section>
      <Modal
        title="筛选回测"
        open={filterModalOpen}
        onCancel={() => setFilterModalOpen(false)}
        footer={[
          <Button key="clear" onClick={clearFilters} disabled={!activeFilterCount}>清除</Button>,
          <Button key="done" type="primary" onClick={() => setFilterModalOpen(false)}>完成</Button>,
        ]}
      >
        <Space direction="vertical" size={12} className="full-width" data-contract="experiments filter modal keeps filters off main toolbar">
          <div>
            <Typography.Text strong>策略</Typography.Text>
            <Select
              allowClear
              placeholder="选择策略"
              value={strategyFilter}
              onChange={setStrategyFilter}
              className="qto-filter-select"
              options={strategies.map((strategy) => ({ value: strategy.id, label: strategy.name }))}
            />
          </div>
          <div>
            <Typography.Text strong>状态</Typography.Text>
            <Select
              allowClear
              placeholder="选择状态"
              value={statusFilter}
              onChange={setStatusFilter}
              className="qto-filter-select"
              options={[...new Set(backtests.map((run) => run.status))].map((status) => ({ value: status, label: formatStatusLabel(status) }))}
            />
          </div>
        </Space>
      </Modal>
      <Modal title="回测对比" open={compareModalOpen} onCancel={() => setCompareModalOpen(false)} footer={null} width={680}>
        {selectedRuns.length ? (
          <div className="qto-compare-list" data-contract="experiments compare details live in modal with compact rows">
            {selectedRuns.map((run) => {
              const artifactSummary = runArtifactSummary(run);
              const status = runAttentionStatus(run.status);
              return (
                <div className="qto-compare-row" key={run.id}>
                  <span className="qto-compare-main">
                    <strong>{runTitle(run, strategies)}</strong>
                    <MetricLine metrics={run.metrics} keys={DETAIL_METRIC_KEYS} dataContract="experiments compare modal shows full metric line" />
                    {artifactSummary ? <Typography.Text type="secondary" data-contract="experiments compare hides zero artifact count">{artifactSummary}</Typography.Text> : null}
                  </span>
                  {status ? (
                    <span data-contract="experiments status pill is attention-only">
                      <StatusTag status={status} />
                    </span>
                  ) : null}
                </div>
              );
            })}
          </div>
        ) : <CompactEmpty>暂无对比记录</CompactEmpty>}
      </Modal>
      <Modal
        title="启动回测"
        open={backtestModalOpen}
        onCancel={() => setBacktestModalOpen(false)}
        onOk={submitBacktest}
        okText="启动"
        cancelText="取消"
        confirmLoading={backtestSubmitting}
        okButtonProps={{ disabled: !backtestDraft.strategy_id || !backtestDraft.dataset_version.trim() }}
      >
        <Space direction="vertical" size={12} className="full-width" data-contract="backtest launch minimal modal requires dataset_version">
          <div>
            <Typography.Text strong>策略</Typography.Text>
            <Select
              value={backtestDraft.strategy_id || undefined}
              onChange={(value) => setBacktestDraft((draft) => ({ ...draft, strategy_id: value }))}
              className="qto-modal-control"
              options={strategies.map((strategy) => ({ value: strategy.id, label: strategy.name }))}
            />
          </div>
          <div>
            <Typography.Text strong>数据版本</Typography.Text>
            <Input
              value={backtestDraft.dataset_version}
              onChange={(event) => setBacktestDraft((draft) => ({ ...draft, dataset_version: event.target.value }))}
              placeholder="例如 2026-06 因子数据"
            />
          </div>
        </Space>
      </Modal>
    </Space>
  );
}

function runTitle(row: BacktestRun, strategies: StrategySpec[]) {
  return strategies.find((strategy) => strategy.id === row.strategy_id)?.name ?? "回测记录";
}

function runSummary(row: BacktestRun) {
  return datasetVersionLabel(row.dataset_version) ?? "";
}

function runActionHint(row: BacktestRun) {
  const status = row.status.toLowerCase();
  if (["failed", "fail", "error", "blocked", "rejected", "denied"].some((marker) => status.includes(marker))) return `处理 ${formatStatusLabel(row.status)}`;
  if (["queued", "started", "running", "pending", "result_pending"].some((marker) => status.includes(marker))) return "等待回测完成";
  if (["review", "warning", "degraded"].some((marker) => status.includes(marker))) return `复核 ${formatStatusLabel(row.status)}`;
  if (isCompletedRunStatus(row.status)) return "可对比并申请风控";
  return null;
}

function isCompletedRunStatus(status: string) {
  return ["completed", "complete", "passed", "pass", "succeeded", "success"].some((marker) => status.toLowerCase().includes(marker));
}

function activeFilterSummary(strategyId: string | undefined, status: string | undefined, strategies: StrategySpec[], visibleCount: number, totalCount: number) {
  const labels = [
    strategyId ? strategies.find((strategy) => strategy.id === strategyId)?.name ?? strategyId : null,
    status ? formatStatusLabel(status) : null,
    `显示 ${visibleCount}/${totalCount}`,
  ].filter(Boolean);
  return labels.join(" · ");
}

function runAttentionStatus(status: string) {
  const value = status.toLowerCase();
  return ["queued", "started", "running", "pending", "review", "failed", "fail", "error", "blocked", "rejected", "denied", "warning", "cancel", "degraded", "result_pending"].some((marker) => value.includes(marker))
    ? status
    : null;
}

function runTrackingLabel(row: BacktestRun) {
  if (row.mlflow_run_id) return `MLflow ${readableIdentifier(row.mlflow_run_id)}`;
  if (row.dataset_version) return datasetVersionLabel(row.dataset_version);
  return null;
}

function runArtifactSummary(row: BacktestRun) {
  return [
    row.engine ? `引擎 ${row.engine}` : null,
    row.artifacts.length ? `产物 ${row.artifacts.length}` : null,
    runTrackingLabel(row),
  ].filter(Boolean).join(" · ");
}

function datasetVersionLabel(value: string | null | undefined) {
  return value?.trim() ? `数据 ${readableIdentifier(value.trim())}` : null;
}

function MetricLine({ metrics, keys, dataContract }: { metrics: Record<string, unknown>; keys: string[]; dataContract: string }) {
  const metricItems = keys.map((key) => formatMetricItem(key, metrics?.[key])).filter(Boolean);
  return metricItems.length ? (
    <span className="qto-run-metrics" data-contract={`experiments compact metric line only shows available metrics; ${dataContract}`}>
      {metricItems.join(" · ")}
    </span>
  ) : null;
}

function formatMetricItem(key: string, value: unknown) {
  if (value === undefined || value === null || value === "") return null;
  if (typeof value === "number") return `${metricLabel(key)} ${value.toFixed(2)}`;
  return `${metricLabel(key)} ${value}`;
}

function metricLabel(key: string) {
  const labels: Record<string, string> = {
    cagr: "CAGR",
    max_drawdown: "max drawdown",
    sharpe: "Sharpe",
    turnover: "turnover",
  };
  return labels[key] ?? key.replace(/_/g, " ");
}
