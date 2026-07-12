import type { StatusValue } from "../api/types";

const STATUS_LABELS: Record<string, string> = {
  healthy: "正常",
  connected: "已连接",
  approved: "已批准",
  completed: "已完成",
  passed: "通过",
  pass: "通过",
  ok: "正常",
  running: "运行中",
  queued: "排队中",
  started: "运行中",
  researching: "研究中",
  idea: "想法",
  data_required: "待数据",
  factor_tested: "因子已测试",
  backtested: "已回测",
  backtest_ready: "待回测",
  ready_backtest: "待回测",
  ready_risk: "待风控",
  archived: "已归档",
  paper: "Paper",
  simulated: "模拟",
  live: "Live",
  pending: "待处理",
  waiting_approval: "待审批",
  requires_review: "待复核",
  review_required: "待复核",
  warning: "警告",
  changes_requested: "需修改",
  blocked: "阻塞",
  locked: "已锁定",
  fail: "失败",
  failed: "失败",
  rejected: "已拒绝",
  denied: "已拒绝",
  error: "错误",
  canceled: "已取消",
  cancelled: "已取消",
  cancel_requested: "取消中",
  disconnected: "未连接",
  unavailable: "不可用",
  none: "无",
  not_started: "未开始",
  missing: "缺失",
  skipped: "已跳过",
  unknown: "未知",
  idle: "空闲",
  degraded: "降级",
  down: "离线",
  created: "已创建",
  draft: "草稿",
  submitted: "已提交",
  active: "启用",
  inactive: "停用",
  result_pending: "结果待回传",
};

export function normalizeStatus(status: StatusValue) {
  return String(status ?? "unknown").trim().toLowerCase();
}

export function statusColor(status: StatusValue) {
  const value = normalizeStatus(status);
  if (["healthy", "connected", "approved", "completed", "passed", "pass", "ok", "active"].includes(value)) return "green";
  if (["queued", "started", "running", "researching", "idea", "created", "draft", "submitted", "paper", "simulated"].includes(value)) return "blue";
  if (["pending", "waiting_approval", "requires_review", "review_required", "warning", "changes_requested", "data_required", "backtest_ready", "ready_backtest", "ready_risk", "result_pending", "degraded", "cancel_requested"].includes(value)) return "amber";
  if (["blocked", "locked", "fail", "failed", "rejected", "denied", "error", "down"].includes(value)) return "red";
  if (["disconnected", "unavailable", "unknown", "idle", "none", "not_started", "missing", "skipped", "archived", "canceled", "cancelled", "inactive"].includes(value)) return "gray";
  return "blue";
}

export function formatStatusLabel(status: StatusValue) {
  const normalized = normalizeStatus(status);
  const raw = String(status ?? "unknown").trim();
  return STATUS_LABELS[normalized] ?? raw.replace(/_/g, " ");
}

export function StatusTag({ status }: { status: StatusValue }) {
  const normalized = normalizeStatus(status);
  const tone = statusColor(status);
  return (
    <span className={`qto-status-pill qto-status-pill-${tone}`} data-status={normalized} data-contract="global low-emphasis status text with compact dot">
      <span className="qto-status-dot" />
      {formatStatusLabel(status)}
    </span>
  );
}
