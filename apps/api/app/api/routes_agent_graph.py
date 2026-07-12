from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import inspect, select
from sqlalchemy.orm import Session

from app.api.compat import APIRouter, Depends, HTTPException
from app.core.auth import require_any_role
from app.core.redaction import redact_secrets
from app.db.models import (
    AgentDefinition,
    AgentGraphEdge,
    AgentGraphGroup,
    AgentMessage,
    AgentRun,
    ApprovalRequest,
    AuditLog,
    PolicyDecision,
    ToolCall,
    WorkflowLink,
)
from app.db.session import get_db
from app.services.connections import list_connections, seed_connections

router = APIRouter(prefix="/api/v1", tags=["agent-graph"])

DEFAULT_GROUPS = [
    {"id": "research", "label": "Research Group", "color": "#2563eb"},
    {"id": "data", "label": "Data Group", "color": "#0891b2"},
    {"id": "validation", "label": "Validation Group", "color": "#d97706"},
    {"id": "trading", "label": "Trading Group", "color": "#dc2626"},
    {"id": "system", "label": "System Group", "color": "#64748b"},
]

DEFAULT_AGENTS = [
    {
        "id": "research-agent",
        "name": "Research Agent",
        "role": "Research hypothesis, notes, and idea expansion",
        "group": "research",
        "position": {"x": 120, "y": 160},
        "tools": ["openai", "langfuse"],
        "permissions": {"can_research": True, "can_write_research": True, "can_create_strategy": True},
    },
    {
        "id": "data-agent",
        "name": "Data Agent",
        "role": "Market data, dataset versions, and data quality",
        "group": "data",
        "position": {"x": 120, "y": 360},
        "tools": ["massive", "openbb", "infisical"],
        "permissions": {"can_read_market_data": True, "can_write_research": True},
    },
    {
        "id": "strategy-agent",
        "name": "Strategy Agent",
        "role": "Strategy drafting, factor selection, and lifecycle state",
        "group": "research",
        "position": {"x": 420, "y": 160},
        "tools": ["openai", "mlflow"],
        "permissions": {"can_create_strategy": True, "can_research": True},
    },
    {
        "id": "backtest-agent",
        "name": "Backtest Agent",
        "role": "Backtest execution, metrics, and reproducibility",
        "group": "validation",
        "position": {"x": 720, "y": 160},
        "tools": ["quantconnect", "mlflow", "minio"],
        "permissions": {"can_backtest": True, "can_request_risk_review": True},
    },
    {
        "id": "risk-agent",
        "name": "Risk Agent",
        "role": "Risk gate, OPA decisions, and live-trading lock evidence",
        "group": "validation",
        "position": {"x": 1020, "y": 160},
        "tools": ["grafana", "temporal"],
        "permissions": {"can_request_risk_review": True},
    },
    {
        "id": "approval-agent",
        "name": "Approval Agent",
        "role": "Human approval queue and workflow checkpoints",
        "group": "trading",
        "position": {"x": 1320, "y": 160},
        "tools": ["chainlit", "keycloak"],
        "permissions": {"can_request_paper_trade": True, "can_request_live_trade": False, "can_execute_live_trade": False},
    },
    {
        "id": "execution-agent",
        "name": "Execution Agent",
        "role": "Paper trading proposals and locked live execution",
        "group": "trading",
        "position": {"x": 1620, "y": 160},
        "tools": ["quantconnect", "grafana"],
        "permissions": {"can_request_paper_trade": True, "can_request_live_trade": False, "can_execute_live_trade": False},
    },
    {
        "id": "monitoring-agent",
        "name": "Monitoring Agent",
        "role": "Workflow, trace, audit, and health monitoring",
        "group": "system",
        "position": {"x": 720, "y": 420},
        "tools": ["grafana", "temporal", "langfuse"],
        "permissions": {"can_read_monitoring": True, "can_execute_live_trade": False},
    },
]

DEFAULT_EDGES = [
    ("data-agent", "research-agent", "data_dependency", "DataIngestionWorkflow"),
    ("research-agent", "strategy-agent", "handoff", "ResearchWorkflow"),
    ("strategy-agent", "backtest-agent", "handoff", "BacktestWorkflow"),
    ("backtest-agent", "risk-agent", "handoff", "RiskReviewWorkflow"),
    ("risk-agent", "approval-agent", "approval", "ApprovalWorkflow"),
    ("approval-agent", "execution-agent", "approval", "PaperPromotionWorkflow"),
    ("monitoring-agent", "research-agent", "monitoring", None),
    ("monitoring-agent", "data-agent", "monitoring", None),
    ("monitoring-agent", "strategy-agent", "monitoring", None),
    ("monitoring-agent", "backtest-agent", "monitoring", None),
    ("monitoring-agent", "risk-agent", "monitoring", None),
    ("monitoring-agent", "approval-agent", "monitoring", None),
    ("monitoring-agent", "execution-agent", "monitoring", None),
]

LIVE_LOCKED_PERMISSIONS = {
    "can_request_live_trade": False,
    "can_execute_live_trade": False,
}

LIVE_LOCKED_RISK_LIMITS = {
    "live_trading_locked": True,
}


@router.get("/agent-graph")
def get_agent_graph(db: Session = Depends(get_db)):
    _seed_agent_graph(db)
    seed_connections(db)
    connections = list_connections(db)
    runs = db.scalars(select(AgentRun).order_by(AgentRun.created_at.desc())).all()
    workflows = db.scalars(select(WorkflowLink).order_by(WorkflowLink.created_at.desc())).all()
    approvals = db.scalars(select(ApprovalRequest).order_by(ApprovalRequest.created_at.desc())).all()
    policies = db.scalars(select(PolicyDecision).order_by(PolicyDecision.created_at.desc())).all()
    groups = db.scalars(select(AgentGraphGroup).order_by(AgentGraphGroup.id)).all()
    agents = db.scalars(select(AgentDefinition).order_by(AgentDefinition.id)).all()
    edges = db.scalars(select(AgentGraphEdge).order_by(AgentGraphEdge.id)).all()
    return {
        "nodes": [_agent_node(agent, connections, runs, workflows, approvals, policies) for agent in agents],
        "edges": [_edge(edge, workflows, policies) for edge in edges],
        "groups": [_group(group) for group in groups],
        "updated_at": datetime.now(UTC).isoformat(),
    }


@router.put("/agent-graph")
def put_agent_graph(payload: dict[str, Any], db: Session = Depends(get_db), _user=Depends(require_any_role("admin"))):
    _seed_agent_graph(db)
    node_payloads = payload.get("nodes", [])
    if isinstance(node_payloads, list):
        for item in node_payloads:
            if not isinstance(item, dict) or not item.get("id"):
                continue
            agent = db.get(AgentDefinition, str(item["id"]))
            if agent and isinstance(item.get("position"), dict):
                agent.position = item["position"]
    edge_payloads = payload.get("edges", [])
    if isinstance(edge_payloads, list):
        for item in edge_payloads:
            if not isinstance(item, dict) or not item.get("id"):
                continue
            edge = db.get(AgentGraphEdge, str(item["id"]))
            if edge and item.get("status"):
                edge.status = str(item["status"])
    db.flush()
    return get_agent_graph(db)


@router.get("/agents/{agent_id}")
def get_agent(agent_id: str, db: Session = Depends(get_db)):
    _seed_agent_graph(db)
    agent = db.get(AgentDefinition, agent_id)
    if not agent:
        raise HTTPException(status_code=404, detail="agent not found")
    return _agent_detail(db, agent)


@router.post("/agents")
def create_agent(payload: dict[str, Any], db: Session = Depends(get_db), _user=Depends(require_any_role("admin"))):
    _seed_agent_graph(db)
    name = str(payload.get("name") or "New Agent").strip()
    agent_id = str(payload.get("id") or _slug(name)).strip()
    if not agent_id:
        raise HTTPException(status_code=422, detail="agent id is required")
    if db.get(AgentDefinition, agent_id):
        raise HTTPException(status_code=409, detail="agent already exists")
    agent = AgentDefinition(
        id=agent_id,
        name=name,
        role=str(payload.get("role") or "Custom agent"),
        group=str(payload.get("group") or "research"),
        status="idle",
        current_task=None,
        last_action="Created from Agent Canvas",
        model_config=payload.get("model_config") if isinstance(payload.get("model_config"), dict) else {"provider": "openai", "model": "gpt-4.1-mini"},
        prompt_config=payload.get("prompt_config") if isinstance(payload.get("prompt_config"), dict) else {"system_prompt": "Custom agent"},
        tool_refs=payload.get("tool_refs") if isinstance(payload.get("tool_refs"), list) else [],
        permissions=_locked_permissions(payload.get("permissions") if isinstance(payload.get("permissions"), dict) else {}),
        risk_limits=_locked_risk_limits(payload.get("risk_limits") if isinstance(payload.get("risk_limits"), dict) else {}),
        position=payload.get("position") if isinstance(payload.get("position"), dict) else {"x": 360, "y": 520},
        meta=payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {"description": "Custom agent"},
    )
    db.add(agent)
    db.flush()
    return _agent_detail(db, agent)


@router.patch("/agents/{agent_id}")
def patch_agent(agent_id: str, payload: dict[str, Any], db: Session = Depends(get_db), _user=Depends(require_any_role("admin"))):
    _seed_agent_graph(db)
    agent = db.get(AgentDefinition, agent_id)
    if not agent:
        raise HTTPException(status_code=404, detail="agent not found")
    for field in ["name", "role", "group", "status", "current_task", "last_action"]:
        if field in payload:
            setattr(agent, field, str(payload[field]) if payload[field] is not None else None)
    for field in ["model_config", "prompt_config", "tool_refs", "permissions", "risk_limits", "position", "metadata"]:
        if field in payload:
            value = redact_secrets(payload[field])
            if field == "metadata":
                agent.meta = value if isinstance(value, dict) else {}
            elif field == "permissions":
                agent.permissions = _locked_permissions(value if isinstance(value, dict) else {})
            elif field == "risk_limits":
                agent.risk_limits = _locked_risk_limits(value if isinstance(value, dict) else {})
            else:
                setattr(agent, field, value)
    db.flush()
    return _agent_detail(db, agent)


@router.post("/agents/{agent_id}/runs")
def create_agent_graph_run(agent_id: str, payload: dict[str, Any] | None = None, db: Session = Depends(get_db), _user=Depends(require_any_role("researcher", "risk_reviewer", "admin"))):
    _seed_agent_graph(db)
    agent = db.get(AgentDefinition, agent_id)
    if not agent:
        raise HTTPException(status_code=404, detail="agent not found")
    safe_payload = redact_secrets(payload or {})
    run = AgentRun(task_type=agent_id, status="queued", input_payload={"agent_id": agent_id, **safe_payload})
    db.add(run)
    db.flush()
    db.add(AgentMessage(agent_run_id=run.id, agent_name=agent.name, role="status", content=f"Queued {agent.name} from Agent Canvas."))
    agent.status = "running"
    agent.current_task = f"Queued run {run.id}"
    agent.last_action = "Agent Canvas manual run queued"
    db.flush()
    return run


def _seed_agent_graph(db: Session) -> None:
    for group in DEFAULT_GROUPS:
        if not db.get(AgentGraphGroup, group["id"]):
            db.add(AgentGraphGroup(id=group["id"], label=group["label"], color=group["color"]))
    for item in DEFAULT_AGENTS:
        if not db.get(AgentDefinition, item["id"]):
            db.add(
                AgentDefinition(
                    id=item["id"],
                    name=item["name"],
                    role=item["role"],
                    group=item["group"],
                    status="idle",
                    current_task=None,
                    last_action="Seeded default agent",
                    model_config={"provider": "openai", "model": "gpt-4.1-mini", "temperature": 0.2, "token_budget": 8000},
                    prompt_config={"system_prompt": item["role"]},
                    tool_refs=[{"provider": provider} for provider in item["tools"]],
                    permissions=_locked_permissions(item["permissions"]),
                    risk_limits=_locked_risk_limits({"requires_human_approval": True}),
                    position=item["position"],
                    meta={"description": item["role"]},
                )
            )
    for source, target, relation_type, workflow_type in DEFAULT_EDGES:
        edge_id = f"{source}->{target}"
        if not db.get(AgentGraphEdge, edge_id):
            db.add(
                AgentGraphEdge(
                    id=edge_id,
                    source_agent_id=source,
                    target_agent_id=target,
                    relation_type=relation_type,
                    workflow_type=workflow_type,
                    status="idle",
                    meta={"handoff_contract": f"{source} hands off to {target}"},
                )
            )
    db.flush()


def _agent_node(
    agent: AgentDefinition,
    connections: list[dict[str, Any]],
    runs: list[AgentRun],
    workflows: list[WorkflowLink],
    approvals: list[ApprovalRequest],
    policies: list[PolicyDecision],
) -> dict[str, Any]:
    related_run = _latest_run_for_agent(agent, runs)
    related_workflow = _latest_workflow_for_agent(agent, workflows)
    pending_approval = any(_norm(row.status) == "pending" for row in approvals)
    denied_policy = any(not row.allowed for row in policies)
    connection_map = {item["provider"]: item for item in connections}
    tool_refs = [_tool_ref(ref, connection_map) for ref in agent.tool_refs]
    status = agent.status
    if any(_norm(tool["status"]) in {"disconnected", "failed", "error"} for tool in tool_refs):
        status = "disconnected"
    if related_run and _norm(related_run.status) in {"queued", "running", "started"}:
        status = "running"
    if agent.id in {"approval-agent", "execution-agent"} and pending_approval:
        status = "waiting_approval"
    if agent.id == "execution-agent" and denied_policy:
        status = "locked"
    return {
        "id": agent.id,
        "name": agent.name,
        "role": agent.role,
        "group": agent.group,
        "status": status,
        "current_task": agent.current_task or (related_run.task_type if related_run else None),
        "last_action": agent.last_action or (related_workflow.workflow_type if related_workflow else None),
        "model_config": agent.model_config,
        "prompt_config": agent.prompt_config,
        "tool_refs": tool_refs,
        "permissions": _locked_permissions(agent.permissions),
        "risk_limits": _locked_risk_limits(agent.risk_limits),
        "position": agent.position or {"x": 0, "y": 0},
        "metadata": agent.meta,
        "human_action_required": status == "waiting_approval",
    }


def _agent_detail(db: Session, agent: AgentDefinition) -> dict[str, Any]:
    graph = get_agent_graph(db)
    node = next((item for item in graph["nodes"] if item["id"] == agent.id), None)
    return {
        **(node or _agent_node(agent, [], [], [], [], [])),
        "latest_agent_runs": [_public_model(row) for row in db.scalars(select(AgentRun).order_by(AgentRun.created_at.desc())).all() if row.input_payload.get("agent_id") == agent.id][:10],
        "workflow_events": [_public_model(row) for row in db.scalars(select(WorkflowLink).order_by(WorkflowLink.created_at.desc())).all() if _agent_matches_workflow(agent, row.workflow_type)][:10],
        "audit_logs": [_public_model(row) for row in db.scalars(select(AuditLog).order_by(AuditLog.created_at.desc())).all()[:10]],
        "tool_calls": [_public_model(row) for row in db.scalars(select(ToolCall).order_by(ToolCall.created_at.desc())).all()[:10]],
        "policy_decisions": [_public_model(row) for row in db.scalars(select(PolicyDecision).order_by(PolicyDecision.created_at.desc())).all()[:10]],
    }


def _edge(edge: AgentGraphEdge, workflows: list[WorkflowLink], policies: list[PolicyDecision]) -> dict[str, Any]:
    workflow_active = edge.workflow_type and any(row.workflow_type == edge.workflow_type and _norm(row.status) in {"running", "started", "queued"} for row in workflows)
    blocked = any((not row.allowed) and row.workflow_id for row in policies)
    return {
        "id": edge.id,
        "source": edge.source_agent_id,
        "target": edge.target_agent_id,
        "relation_type": edge.relation_type,
        "workflow_type": edge.workflow_type,
        "status": "active" if workflow_active else ("blocked" if blocked and edge.relation_type == "approval" else edge.status),
        "metadata": edge.meta,
    }


def _group(group: AgentGraphGroup) -> dict[str, Any]:
    return {"id": group.id, "label": group.label, "color": group.color, "metadata": group.meta}


def _tool_ref(ref: dict[str, Any], connection_map: dict[str, dict[str, Any]]) -> dict[str, Any]:
    provider = str(ref.get("provider") or "")
    connection = connection_map.get(provider, {})
    metadata = connection.get("metadata") or {}
    return {
        "provider": provider,
        "display_name": connection.get("display_name") or provider,
        "status": connection.get("status", "disconnected"),
        "permission_level": metadata.get("permission_level") or connection.get("permission_level") or "unknown",
        "secret_ref": metadata.get("secret_ref") or connection.get("infisical_secret_path"),
        "open_ui_url": metadata.get("open_ui_url") or connection.get("open_ui_url"),
    }


def _latest_run_for_agent(agent: AgentDefinition, runs: list[AgentRun]) -> AgentRun | None:
    return next((row for row in runs if row.input_payload.get("agent_id") == agent.id or row.task_type.replace("_", "-") in {agent.id, agent.id.replace("-agent", "")}), None)


def _latest_workflow_for_agent(agent: AgentDefinition, workflows: list[WorkflowLink]) -> WorkflowLink | None:
    return next((row for row in workflows if _agent_matches_workflow(agent, row.workflow_type)), None)


def _agent_matches_workflow(agent: AgentDefinition, workflow_type: str) -> bool:
    name = agent.name.lower()
    workflow = (workflow_type or "").lower()
    return (
        ("research" in name and "research" in workflow)
        or ("backtest" in name and "backtest" in workflow)
        or ("risk" in name and "risk" in workflow)
        or ("approval" in name and "approval" in workflow)
        or ("execution" in name and ("paper" in workflow or "execution" in workflow))
        or ("data" in name and "data" in workflow)
        or ("strategy" in name and "strategy" in workflow)
    )


def _public_model(model) -> dict:
    return {
        ("metadata" if attr.key == "meta" else attr.key): getattr(model, attr.key)
        for attr in inspect(model).mapper.column_attrs
    }


def _locked_permissions(permissions: Any) -> dict[str, Any]:
    values = permissions if isinstance(permissions, dict) else {}
    return {**values, **LIVE_LOCKED_PERMISSIONS}


def _locked_risk_limits(risk_limits: Any) -> dict[str, Any]:
    values = risk_limits if isinstance(risk_limits, dict) else {}
    return {**values, **LIVE_LOCKED_RISK_LIMITS}


def _slug(value: str) -> str:
    return "-".join(part for part in value.lower().replace("_", "-").split() if part)[:64]


def _norm(value) -> str:
    return str(value or "").strip().lower()
