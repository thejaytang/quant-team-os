from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from sqlalchemy import JSON, Boolean, Date, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def new_id() -> str:
    return str(uuid4())


def now_utc() -> datetime:
    return datetime.now(UTC)


class Base(DeclarativeBase):
    pass


class TimestampMixin:
    # Indexed: audit/tool-call/event/policy listings all order by created_at desc.
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc, index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc, onupdate=now_utc)


class ExternalConnection(Base, TimestampMixin):
    __tablename__ = "external_connections"
    __table_args__ = (UniqueConstraint("provider", name="uq_external_connections_provider"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    provider: Mapped[str] = mapped_column(String(64), index=True)
    display_name: Mapped[str] = mapped_column(String(255))
    status: Mapped[str] = mapped_column(String(32), default="disconnected")
    permissions: Mapped[list[str]] = mapped_column(JSON, default=list)
    infisical_secret_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    secret_version: Mapped[str | None] = mapped_column(String(128), nullable=True)
    meta: Mapped[dict[str, Any]] = mapped_column("metadata", JSON, default=dict)
    last_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by_user_id: Mapped[str] = mapped_column(String(128), default="local_user")


class AgentRun(Base, TimestampMixin):
    __tablename__ = "agent_runs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    task_type: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(32), default="queued")
    workflow_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    langfuse_trace_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    input_payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    output_payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)


class AgentMessage(Base, TimestampMixin):
    __tablename__ = "agent_messages"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    agent_run_id: Mapped[str] = mapped_column(String(36), ForeignKey("agent_runs.id"))
    agent_name: Mapped[str] = mapped_column(String(128))
    role: Mapped[str] = mapped_column(String(32))
    content: Mapped[str] = mapped_column(Text)
    artifact_id: Mapped[str | None] = mapped_column(String(36), nullable=True)


class AgentDefinition(Base, TimestampMixin):
    __tablename__ = "agent_definitions"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(128))
    role: Mapped[str] = mapped_column(String(128))
    group: Mapped[str] = mapped_column("agent_group", String(128))
    status: Mapped[str] = mapped_column(String(64), default="idle")
    current_task: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_action: Mapped[str | None] = mapped_column(Text, nullable=True)
    model_config: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    prompt_config: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    tool_refs: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    permissions: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    risk_limits: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    position: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    meta: Mapped[dict[str, Any]] = mapped_column("metadata", JSON, default=dict)


class AgentGraphEdge(Base, TimestampMixin):
    __tablename__ = "agent_graph_edges"

    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    source_agent_id: Mapped[str] = mapped_column(String(64), ForeignKey("agent_definitions.id"))
    target_agent_id: Mapped[str] = mapped_column(String(64), ForeignKey("agent_definitions.id"))
    relation_type: Mapped[str] = mapped_column(String(64), default="handoff")
    workflow_type: Mapped[str | None] = mapped_column(String(128), nullable=True)
    status: Mapped[str] = mapped_column(String(64), default="idle")
    meta: Mapped[dict[str, Any]] = mapped_column("metadata", JSON, default=dict)


class AgentGraphGroup(Base, TimestampMixin):
    __tablename__ = "agent_graph_groups"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    label: Mapped[str] = mapped_column(String(128))
    color: Mapped[str] = mapped_column(String(32), default="#64748b")
    meta: Mapped[dict[str, Any]] = mapped_column("metadata", JSON, default=dict)


class ToolCall(Base, TimestampMixin):
    __tablename__ = "tool_calls"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    agent_run_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    adapter_name: Mapped[str] = mapped_column(String(128))
    tool_name: Mapped[str] = mapped_column(String(128))
    risk_level: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(32), default="started")
    input_payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    output_payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)


class AuditLog(Base, TimestampMixin):
    __tablename__ = "audit_logs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    actor: Mapped[str] = mapped_column(String(128), default="system")
    action: Mapped[str] = mapped_column(String(128))
    target_type: Mapped[str] = mapped_column(String(128))
    target_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


class ResearchIdea(Base, TimestampMixin):
    __tablename__ = "research_ideas"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    title: Mapped[str] = mapped_column(String(255))
    thesis: Mapped[str] = mapped_column(Text)
    universe: Mapped[str] = mapped_column(String(255), default="US equities")
    asset_class: Mapped[str] = mapped_column(String(64), default="equity")
    proposed_by: Mapped[str] = mapped_column(String(128), default="human")
    status: Mapped[str] = mapped_column(String(64), default="IDEA")
    tags: Mapped[list[str]] = mapped_column(JSON, default=list)


class FactorSpec(Base, TimestampMixin):
    __tablename__ = "factor_specs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    research_idea_id: Mapped[str] = mapped_column(String(36), ForeignKey("research_ideas.id"))
    name: Mapped[str] = mapped_column(String(255))
    description: Mapped[str] = mapped_column(Text)
    formula: Mapped[str] = mapped_column(Text)
    input_fields: Mapped[list[str]] = mapped_column(JSON, default=list)
    lookback_window: Mapped[int | None] = mapped_column(Integer, nullable=True)
    rebalance_frequency: Mapped[str] = mapped_column(String(64), default="daily")
    implementation_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(64), default="created")
    metrics: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    artifacts: Mapped[list[str]] = mapped_column(JSON, default=list)


class DatasetSpec(Base, TimestampMixin):
    __tablename__ = "dataset_specs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    name: Mapped[str] = mapped_column(String(255))
    asset_class: Mapped[str] = mapped_column(String(64), default="equity")
    frequency: Mapped[str] = mapped_column(String(64), default="1d")
    source: Mapped[str] = mapped_column(String(128), default="massive")
    filters: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    dataset_version: Mapped[str | None] = mapped_column(String(255), nullable=True)
    dvc_rev: Mapped[str | None] = mapped_column(String(255), nullable=True)


class StrategySpec(Base, TimestampMixin):
    __tablename__ = "strategy_specs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    name: Mapped[str] = mapped_column(String(255))
    description: Mapped[str] = mapped_column(Text)
    universe: Mapped[str] = mapped_column(String(255), default="US equities")
    factors: Mapped[list[str]] = mapped_column(JSON, default=list)
    signal_logic: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    portfolio_logic: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    rebalance_frequency: Mapped[str] = mapped_column(String(64), default="daily")
    risk_constraints: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    implementation_paths: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String(64), default="IDEA")


class StrategyCard(Base, TimestampMixin):
    __tablename__ = "strategy_cards"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    strategy_id: Mapped[str] = mapped_column(String(36), ForeignKey("strategy_specs.id"), unique=True)
    current_status: Mapped[str] = mapped_column(String(64), default="IDEA")
    thesis: Mapped[str] = mapped_column(Text)
    universe: Mapped[str] = mapped_column(String(255))
    factor_summary: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    latest_backtest_metrics: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    latest_risk_review: Mapped[str | None] = mapped_column(String(36), nullable=True)
    approval_status: Mapped[str] = mapped_column(String(64), default="none")
    paper_trading_status: Mapped[str] = mapped_column(String(64), default="not_started")
    live_trading_status: Mapped[str] = mapped_column(String(64), default="locked")
    workflow_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    artifacts: Mapped[list[str]] = mapped_column(JSON, default=list)


class BacktestRun(Base, TimestampMixin):
    __tablename__ = "backtest_runs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    strategy_id: Mapped[str] = mapped_column(String(36), ForeignKey("strategy_specs.id"))
    engine: Mapped[str] = mapped_column(String(64), default="qlib")
    dataset_spec_id: Mapped[str] = mapped_column(String(36), ForeignKey("dataset_specs.id"))
    dataset_version: Mapped[str | None] = mapped_column(String(255), nullable=True)
    start_date: Mapped[str] = mapped_column(Date)
    end_date: Mapped[str] = mapped_column(Date)
    benchmark: Mapped[str] = mapped_column(String(128), default="SPY")
    cost_model: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    slippage_model: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String(64), default="queued")
    metrics: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    artifacts: Mapped[list[str]] = mapped_column(JSON, default=list)
    mlflow_run_id: Mapped[str | None] = mapped_column(String(255), nullable=True)


class BacktestMetric(Base, TimestampMixin):
    __tablename__ = "backtest_metrics"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    backtest_run_id: Mapped[str] = mapped_column(String(36), ForeignKey("backtest_runs.id"))
    metric_name: Mapped[str] = mapped_column(String(128))
    metric_value: Mapped[float] = mapped_column(Float)


class RiskReview(Base, TimestampMixin):
    __tablename__ = "risk_reviews"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    strategy_id: Mapped[str] = mapped_column(String(36), ForeignKey("strategy_specs.id"))
    backtest_run_id: Mapped[str] = mapped_column(String(36), ForeignKey("backtest_runs.id"))
    verdict: Mapped[str] = mapped_column(String(64))
    hard_rule_results: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    llm_commentary: Mapped[str] = mapped_column(Text, default="")
    risk_summary: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_by_agent: Mapped[str] = mapped_column(String(128), default="RiskAgent")


class ApprovalRequest(Base, TimestampMixin):
    __tablename__ = "approval_requests"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    request_type: Mapped[str] = mapped_column(String(64))
    target_type: Mapped[str] = mapped_column(String(128))
    target_id: Mapped[str] = mapped_column(String(36))
    requested_by_agent: Mapped[str] = mapped_column(String(128))
    risk_summary: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String(64), default="pending")
    workflow_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    human_comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ApprovalRecord(Base, TimestampMixin):
    __tablename__ = "approval_records"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    approval_request_id: Mapped[str] = mapped_column(String(36), ForeignKey("approval_requests.id"))
    action: Mapped[str] = mapped_column(String(64))
    human_actor: Mapped[str] = mapped_column(String(128), default="local_user")
    human_comment: Mapped[str] = mapped_column(Text)


class PortfolioProposal(Base, TimestampMixin):
    __tablename__ = "portfolio_proposals"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    strategy_id: Mapped[str] = mapped_column(String(36), ForeignKey("strategy_specs.id"))
    status: Mapped[str] = mapped_column(String(64), default="stub")
    target_weights: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


class PaperTradingSession(Base, TimestampMixin):
    __tablename__ = "paper_trading_sessions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    strategy_id: Mapped[str] = mapped_column(String(36), ForeignKey("strategy_specs.id"))
    provider: Mapped[str] = mapped_column(String(64), default="quantconnect")
    status: Mapped[str] = mapped_column(String(64), default="proposed")
    workflow_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    deployment_ref: Mapped[str | None] = mapped_column(String(255), nullable=True)
    meta: Mapped[dict[str, Any]] = mapped_column("metadata", JSON, default=dict)


class TradeProposal(Base, TimestampMixin):
    __tablename__ = "trade_proposals"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    strategy_id: Mapped[str] = mapped_column(String(36), ForeignKey("strategy_specs.id"))
    mode: Mapped[str] = mapped_column(String(64), default="paper")
    status: Mapped[str] = mapped_column(String(64), default="locked")
    orders: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)


class OrderTicket(Base, TimestampMixin):
    __tablename__ = "order_tickets"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    trade_proposal_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    mode: Mapped[str] = mapped_column(String(64), default="paper")
    status: Mapped[str] = mapped_column(String(64), default="locked")
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


class ExecutionReport(Base, TimestampMixin):
    __tablename__ = "execution_reports"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    order_ticket_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    mode: Mapped[str] = mapped_column(String(64), default="paper")
    status: Mapped[str] = mapped_column(String(64), default="stub")
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


class Artifact(Base, TimestampMixin):
    __tablename__ = "artifacts"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    artifact_type: Mapped[str] = mapped_column(String(128))
    owner_type: Mapped[str] = mapped_column(String(128))
    owner_id: Mapped[str] = mapped_column(String(36))
    minio_bucket: Mapped[str] = mapped_column(String(128), default="qto-artifacts")
    object_key: Mapped[str] = mapped_column(Text, default="")
    path: Mapped[str] = mapped_column(Text, default="")
    content_type: Mapped[str] = mapped_column(String(128))
    checksum: Mapped[str] = mapped_column(String(128))
    mlflow_run_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    dvc_rev: Mapped[str | None] = mapped_column(String(255), nullable=True)
    meta: Mapped[dict[str, Any]] = mapped_column("metadata", JSON, default=dict)


class SystemEvent(Base, TimestampMixin):
    __tablename__ = "system_events"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    event_type: Mapped[str] = mapped_column(String(128))
    severity: Mapped[str] = mapped_column(String(32), default="info")
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    resolved: Mapped[bool] = mapped_column(Boolean, default=False)


class WorkflowLink(Base, TimestampMixin):
    __tablename__ = "workflow_links"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    workflow_id: Mapped[str] = mapped_column(String(255), index=True)
    workflow_type: Mapped[str] = mapped_column(String(128))
    owner_type: Mapped[str] = mapped_column(String(128))
    owner_id: Mapped[str] = mapped_column(String(36))
    status: Mapped[str] = mapped_column(String(64), default="running")
    meta: Mapped[dict[str, Any]] = mapped_column("metadata", JSON, default=dict)


class PolicyDecision(Base, TimestampMixin):
    __tablename__ = "policy_decisions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    policy_package: Mapped[str] = mapped_column(String(128))
    action: Mapped[str] = mapped_column(String(128))
    allowed: Mapped[bool] = mapped_column(Boolean, default=False)
    input_payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    reasons: Mapped[list[str]] = mapped_column(JSON, default=list)
    workflow_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    actor: Mapped[str] = mapped_column(String(128), default="system")
