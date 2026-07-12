import { ExportOutlined } from "@ant-design/icons";
import { Button, Drawer, List, Space, Typography } from "antd";
import { useState } from "react";
import type { ResearchReportItem } from "../../api/types";
import { CompactEmpty } from "../../components/CompactEmpty";
import { StatusTag } from "../../components/StatusTag";
import { formatDisplayDate, ownerLinkedLabel, ownerTypeLabel, readableIdentifier } from "../../displayLabels";

export function ReportsPage({ reports }: { reports: ResearchReportItem[] }) {
  const [selected, setSelected] = useState<ResearchReportItem | null>(null);

  return (
    <Space direction="vertical" size={18} className="full-width">
      <div className="qto-page-heading">
        <div>
          <Typography.Title level={2}>研究报告</Typography.Title>
        </div>
      </div>
      <section className="qto-report-section" data-contract="reports lightweight section no card wrapper">
        <List
          className="qto-report-list"
          dataSource={reports}
          locale={{ emptyText: <CompactEmpty>暂无研究报告</CompactEmpty> }}
          renderItem={(row) => {
            const status = reportAttentionStatus(row.owner_status);
            const actionHint = reportActionHint(row);
            return (
              <List.Item
                className="qto-report-row"
                data-contract="report row opens detail no repeated detail button"
                role="button"
                tabIndex={0}
                onClick={() => setSelected(row)}
                onKeyDown={(event) => {
                  if (event.key === "Enter" || event.key === " ") {
                    event.preventDefault();
                    setSelected(row);
                  }
                }}
                actions={row.artifact.path ? [
                  <Button
                    key="open"
                    size="small"
                    icon={<ExportOutlined />}
                    aria-label="打开报告"
                    href={row.artifact.path}
                    target="_blank"
                    rel="noreferrer"
                    onClick={(event) => event.stopPropagation()}
                    data-contract="report direct open action only when link exists no single-item dropdown"
                  />,
                ] : []}
              >
                <div className="qto-report-list-line" data-contract="reports compact single-line row no stacked metadata">
                  <span className="qto-report-list-main">
                    <strong>{reportTitle(row)}</strong>
                    <span className="qto-report-summary" data-contract="reports compact one-line list summary">{reportSummary(row)}</span>
                    {actionHint ? (
                      <span className="qto-report-action-hint" data-contract="reports row shows source-aware next action without repeated detail button">
                        {actionHint}
                      </span>
                    ) : null}
                  </span>
                  {status ? (
                    <span data-contract="reports owner status pill is attention-only">
                      <StatusTag status={status} />
                    </span>
                  ) : null}
                </div>
              </List.Item>
            );
          }}
        />
      </section>

      <Drawer width={560} title="报告详情" open={Boolean(selected)} onClose={() => setSelected(null)}>
        {selected ? (
          <Space direction="vertical" size={16} className="full-width">
            <section className="qto-detail-tag-section" data-contract="report detail keeps list-hidden context in compact metadata">
              <Typography.Text strong>报告信息</Typography.Text>
              <div className="qto-detail-meta-list">
                {reportDetailMetaItems(selected).map((item) => <span key={item}>{item}</span>)}
              </div>
            </section>
            {reportDetailSummary(selected) ? (
              <section className="qto-detail-tag-section" data-contract="report detail optional sections render only when populated">
                <Typography.Text strong>摘要</Typography.Text>
                <Typography.Text>{reportDetailSummary(selected)}</Typography.Text>
              </section>
            ) : null}
            {reportRelations(selected).length ? (
              <section className="qto-detail-tag-section" data-contract="report detail optional sections render only when populated">
                <Typography.Text strong>关联对象</Typography.Text>
                <div className="qto-detail-meta-list" data-contract="reports relation metadata no tag stack">
                  {reportRelations(selected).map((item) => <span key={item}>{item}</span>)}
                </div>
              </section>
            ) : null}
            {reportLink(selected) ? (
              <section className="qto-detail-tag-section" data-contract="report detail optional sections render only when populated">
                <Typography.Text strong>文件/链接</Typography.Text>
                <Space size={8} wrap>
                  <Typography.Text>{reportLinkLabel(selected)}</Typography.Text>
                  {selected.artifact.path ? (
                    <Button size="small" href={selected.artifact.path} target="_blank" rel="noreferrer">打开</Button>
                  ) : null}
                </Space>
              </section>
            ) : null}
            {reportAuditItems(selected).length ? (
              <section className="qto-detail-tag-section" data-contract="reports audit metadata no raw artifact json">
                <Typography.Text strong>审计记录</Typography.Text>
                <div className="qto-detail-meta-list">
                  {reportAuditItems(selected).map((item) => <span key={item}>{item}</span>)}
                </div>
              </section>
            ) : null}
          </Space>
        ) : null}
      </Drawer>
    </Space>
  );
}

function reportTitle(row: ResearchReportItem) {
  const title = row.artifact.metadata?.title;
  if (typeof title === "string" && title.trim()) return title.trim();
  const sourceName = row.artifact.object_key || row.artifact.path;
  return sourceName ? readableArtifactName(sourceName) : artifactTypeLabel(row.artifact.artifact_type);
}

function reportSummary(row: ResearchReportItem) {
  return [
    artifactTypeLabel(row.artifact.artifact_type),
    reportOwnerSummary(row),
  ].filter(Boolean).join(" · ");
}

function reportActionHint(row: ResearchReportItem) {
  if (row.owner_status && reportAttentionStatus(row.owner_status)) return `处理状态 ${readableIdentifier(row.owner_status)}`;
  if (row.artifact.path) return "打开报告";
  if (row.artifact.object_key) return "查看对象信息";
  if (reportRelations(row).length) return "查看关联对象";
  return null;
}

function reportAttentionStatus(status: string | null | undefined) {
  const value = status?.toLowerCase();
  return value && ["data_required", "missing", "pending", "approval", "review", "failed", "fail", "error", "blocked", "rejected", "denied", "locked"].some((marker) => value.includes(marker))
    ? status
    : null;
}

function reportDetailMetaItems(row: ResearchReportItem) {
  return [
    artifactTypeLabel(row.artifact.artifact_type),
    reportOwnerSummary(row),
    formatDisplayDate(row.artifact.created_at, "创建"),
  ].filter(Boolean) as string[];
}

function reportDetailSummary(row: ResearchReportItem) {
  const summary = row.artifact.metadata?.summary;
  return typeof summary === "string" && summary.trim() ? summary.trim() : null;
}

function reportLink(row: ResearchReportItem) {
  return row.artifact.path || row.artifact.object_key || null;
}

function reportLinkLabel(row: ResearchReportItem) {
  if (row.artifact.path) return readableArtifactName(row.artifact.path);
  if (row.artifact.object_key) return readableArtifactName(row.artifact.object_key);
  return null;
}

function reportRelations(row: ResearchReportItem) {
  const items = [
    row.artifact.owner_id ? ownerLinkedLabel(row.artifact.owner_type, row.artifact.owner_id) : null,
    relatedReportObject("因子", row.related_factor_id),
    relatedReportObject("策略", row.related_strategy_id),
    relatedReportObject("回测", row.related_backtest_id),
  ].filter(Boolean) as string[];
  return [...new Set(items)];
}

function relatedReportObject(label: string, id: string | null | undefined) {
  return id ? `${label} ${readableIdentifier(id)}` : null;
}

function reportAuditItems(row: ResearchReportItem) {
  return [
    auditReferenceLabel("校验", row.artifact.checksum),
    auditReferenceLabel("MLflow", row.artifact.mlflow_run_id),
    auditReferenceLabel("DVC", row.artifact.dvc_rev),
    row.artifact.object_key ? `对象 ${readableArtifactName(row.artifact.object_key)}` : null,
    row.artifact.content_type ? `类型 ${contentTypeLabel(row.artifact.content_type)}` : null,
  ].filter(Boolean) as string[];
}

function auditReferenceLabel(label: string, value: string | null | undefined) {
  const normalized = value?.trim();
  return normalized ? `${label} ${shortReference(normalized)}` : null;
}

function shortReference(value: string) {
  return value.length > 12 ? `${value.slice(0, 12)}...` : value;
}

function contentTypeLabel(type: string) {
  return type.split(/[;/]/)[0]?.trim() || type;
}

function reportOwnerSummary(row: ResearchReportItem) {
  const owner = ownerTypeLabel(row.artifact.owner_type);
  return row.owner_name ? `${owner} ${row.owner_name}` : owner;
}

function artifactTypeLabel(type: string) {
  const labels: Record<string, string> = {
    backtest_metrics: "回测指标",
    backtest_report: "回测报告",
    factor_report: "因子报告",
    research_report: "研究报告",
    risk_report: "风控报告",
    strategy_report: "策略报告",
  };
  return labels[type] ?? readableIdentifier(type);
}

function readableArtifactName(path: string) {
  const filename = path.split(/[\\/]/).filter(Boolean).pop() ?? path;
  return readableIdentifier(filename.replace(/\.[^.]+$/, ""));
}
