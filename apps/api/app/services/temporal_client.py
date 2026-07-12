from __future__ import annotations

import asyncio
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.models import WorkflowLink
from app.services.audit import write_audit_log

TASK_QUEUE = "quant-team-os"


def start_temporal_workflow(db: Session, workflow_type: str, workflow_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    result = _run(_start(workflow_type, workflow_id, payload))
    _write_workflow_event(db, workflow_id, "workflow.temporal_started" if result["ok"] else "workflow.temporal_fallback", result)
    _raise_if_fallback_disabled(result)
    return result


def signal_approval_resolved(db: Session, workflow_id: str | None, payload: dict[str, Any], actor: str) -> dict[str, Any]:
    if not workflow_id:
        return {"ok": False, "mode": "no_workflow_id"}
    result = _run(_signal(workflow_id, "approval_resolved", payload))
    _write_workflow_event(db, workflow_id, "workflow.signal_sent" if result["ok"] else "workflow.signal_fallback", result, actor=actor)
    _raise_if_fallback_disabled(result)
    return result


def cancel_temporal_workflow(db: Session, workflow_id: str, actor: str) -> dict[str, Any]:
    result = _run(_cancel(workflow_id))
    _write_workflow_event(db, workflow_id, "workflow.cancel_requested" if result["ok"] else "workflow.cancel_fallback", result, actor=actor)
    _raise_if_fallback_disabled(result)
    return result


async def _start(workflow_type: str, workflow_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    try:
        from temporalio.client import Client

        client = await Client.connect(get_settings().temporal_address, namespace=get_settings().temporal_namespace)
        await client.start_workflow(workflow_type, payload, id=workflow_id, task_queue=TASK_QUEUE)
        return {"ok": True, "mode": "temporal", "workflow_id": workflow_id}
    except Exception as exc:
        return {"ok": False, "mode": "local_fallback", "workflow_id": workflow_id, "error": str(exc)}


async def _signal(workflow_id: str, signal_name: str, payload: dict[str, Any]) -> dict[str, Any]:
    try:
        from temporalio.client import Client

        client = await Client.connect(get_settings().temporal_address, namespace=get_settings().temporal_namespace)
        handle = client.get_workflow_handle(workflow_id)
        await handle.signal(signal_name, payload)
        return {"ok": True, "mode": "temporal", "workflow_id": workflow_id, "signal": signal_name}
    except Exception as exc:
        return {"ok": False, "mode": "local_fallback", "workflow_id": workflow_id, "signal": signal_name, "error": str(exc)}


async def _cancel(workflow_id: str) -> dict[str, Any]:
    try:
        from temporalio.client import Client

        client = await Client.connect(get_settings().temporal_address, namespace=get_settings().temporal_namespace)
        handle = client.get_workflow_handle(workflow_id)
        await handle.cancel()
        return {"ok": True, "mode": "temporal", "workflow_id": workflow_id}
    except Exception as exc:
        return {"ok": False, "mode": "local_fallback", "workflow_id": workflow_id, "error": str(exc)}


def _run(coro):
    try:
        return asyncio.run(coro)
    except RuntimeError:
        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(coro)
        finally:
            loop.close()


def _write_workflow_event(db: Session, workflow_id: str, action: str, payload: dict[str, Any], actor: str = "system") -> None:
    link = db.scalar(select(WorkflowLink).where(WorkflowLink.workflow_id == workflow_id))
    if link:
        link.meta = {**(link.meta or {}), "last_temporal_event": payload}
    write_audit_log(db, action, "workflow", workflow_id, payload, actor=actor)


def _raise_if_fallback_disabled(result: dict[str, Any]) -> None:
    if result.get("ok") or get_settings().allow_temporal_fallback:
        return
    raise RuntimeError(f"Temporal call failed: {result.get('error') or result.get('mode')}")
