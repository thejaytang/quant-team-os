import { Button, Space, Typography } from "antd";
import type { ResearchPipeline, ResearchPipelineItem } from "../../api/types";
import { CompactEmpty } from "../../components/CompactEmpty";
import { StatusTag } from "../../components/StatusTag";
import { pipelineActionLabel } from "../../displayLabels";

export function ResearchPipelinePage({
  pipeline,
  onCreateIdea,
  onItemClick,
}: {
  pipeline: ResearchPipeline | null;
  onCreateIdea: () => void;
  onItemClick: (item: ResearchPipelineItem) => void;
}) {
  const stages = pipeline?.stages ?? [];
  const activeStages = stages.filter((stage) => stage.items.length);

  return (
    <Space direction="vertical" size={18} className="full-width">
      <div className="qto-page-heading">
        <div>
          <Typography.Title level={2}>研究管线</Typography.Title>
        </div>
        <Space wrap size={8}>
          <Button type="primary" onClick={onCreateIdea}>创建研究想法</Button>
        </Space>
      </div>

      <div className="qto-kanban" data-testid="research-pipeline">
        {activeStages.length ? activeStages.map((stage) => (
          <section className="qto-kanban-column" key={stage.key}>
            <div className="qto-kanban-heading">
              <Typography.Text strong>{stage.label}</Typography.Text>
              <span className="qto-kanban-count">{stage.items.length}</span>
            </div>
            {stage.items.map((item) => {
              const summary = pipelineCardSummary(item);
              const status = pipelineAttentionStatus(item.status);
              const action = pipelinePrimaryAction(item);
              const blockers = pipelineBlockerItems(item);
              return (
                <button className="qto-pipeline-card" data-contract="research pipeline compact card one-line summary; pipeline card summary renders only when populated" type="button" key={`${item.item_type}:${item.id}`} onClick={() => onItemClick(item)}>
                  <span className="qto-pipeline-card-header">
                    <span className="qto-card-title">{item.title}</span>
                    {status ? (
                      <span data-contract="research pipeline status pill is attention-only">
                        <StatusTag status={status} />
                      </span>
                    ) : null}
                  </span>
                  {summary ? <span className="qto-card-summary">{summary}</span> : null}
                  <span className="qto-pipeline-next-row" data-contract="research pipeline card shows next action and blockers without opening drawer">
                    {action ? <span className="qto-pipeline-next-action">{action}</span> : <span className="qto-pipeline-next-muted">暂无下一步</span>}
                    {blockers.length ? <span className="qto-pipeline-blockers">{blockers.join(" / ")}</span> : null}
                  </span>
                </button>
              );
            })}
          </section>
        )) : <div className="qto-empty-column"><CompactEmpty>暂无研究项目</CompactEmpty></div>}
      </div>
    </Space>
  );
}

function pipelineCardSummary(item: ResearchPipelineItem) {
  const items = [
    pipelineActionLabel(item.next_actions[0]) ?? pipelineActionLabel(item.latest_action),
    item.missing_requirements.length ? `缺口 ${item.missing_requirements.length}` : null,
  ].filter(Boolean);
  return items.join(" · ");
}

function pipelinePrimaryAction(item: ResearchPipelineItem) {
  const label = pipelineActionLabel(item.next_actions[0]) ?? pipelineActionLabel(item.latest_action);
  return label ? `下一步 ${label}` : null;
}

function pipelineBlockerItems(item: ResearchPipelineItem) {
  return [
    item.missing_requirements.length ? `缺 ${item.missing_requirements.length}` : null,
    item.risk_verdict && pipelineAttentionStatus(item.risk_verdict) ? `风控 ${item.risk_verdict}` : null,
    item.approval_status && pipelineAttentionStatus(item.approval_status) ? `审批 ${item.approval_status}` : null,
  ].filter(Boolean) as string[];
}

function pipelineAttentionStatus(status: string) {
  const value = status.toLowerCase();
  return ["data_required", "missing", "pending", "approval", "review", "failed", "fail", "error", "blocked", "rejected", "denied", "locked"].some((marker) => value.includes(marker))
    ? status
    : null;
}
