from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import timedelta
from typing import Any

try:
    from temporalio import workflow
except Exception:  # pragma: no cover - local test env may not install temporalio

    class _WorkflowShim:
        @staticmethod
        def defn(name: str | None = None):
            def decorate(cls):
                cls.__temporal_name__ = name or cls.__name__
                return cls

            return decorate

        @staticmethod
        def run(fn):
            return fn

        @staticmethod
        def signal(name: str | None = None):
            def decorate(fn):
                fn.__temporal_signal__ = name or fn.__name__
                return fn

            return decorate

        @staticmethod
        def query(fn):
            return fn

        @staticmethod
        async def wait_condition(predicate):
            while not predicate():
                await asyncio.sleep(0.05)

        @staticmethod
        async def execute_activity(name: str, payload: dict[str, Any], **_: Any):
            return {"activity": name, "status": "completed", "input": payload}

    workflow = _WorkflowShim()


APPROVAL_ACTIONS = {"approved", "rejected", "changes_requested"}


@dataclass
class ApprovalSignalState:
    payload: dict[str, Any] | None = None
    status: str = "waiting_approval"

    def resolve(self, payload: dict[str, Any]) -> str:
        action = str(payload.get("action", "")).strip()
        if action not in APPROVAL_ACTIONS:
            action = "rejected"
        self.payload = {**payload, "action": action}
        self.status = _status_for_action(action)
        return self.status

    def as_dict(self) -> dict[str, Any]:
        return {"status": self.status, "approval": self.payload}


def _status_for_action(action: str) -> str:
    if action == "approved":
        return "completed"
    return action


async def _activity(name: str, payload: dict[str, Any]) -> dict[str, Any]:
    result = await workflow.execute_activity(name, payload, start_to_close_timeout=timedelta(minutes=5))
    return {"activity": name, "result": result}


async def _activity_chain(names: list[str], payload: dict[str, Any]) -> list[dict[str, Any]]:
    results, _ = await _activity_chain_with_state(names, payload)
    return results


async def _activity_chain_with_state(names: list[str], payload: dict[str, Any]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    results = []
    current = dict(payload)
    for name in names:
        item = await _activity(name, current)
        results.append(item)
        if isinstance(item["result"], dict):
            next_current = {**current, **item["result"]}
            if isinstance(current.get("artifacts"), list) or isinstance(item["result"].get("artifacts"), list):
                seen = set()
                artifacts = []
                for artifact in [*(current.get("artifacts") or []), *(item["result"].get("artifacts") or [])]:
                    key = artifact.get("artifact_id") if isinstance(artifact, dict) else str(artifact)
                    if key in seen:
                        continue
                    seen.add(key)
                    artifacts.append(artifact)
                next_current["artifacts"] = artifacts
            current = next_current
    return results, current


async def _record_workflow_status(
    payload: dict[str, Any],
    workflow_name: str,
    status: str,
    activities: list[dict[str, Any]],
    result: dict[str, Any],
) -> list[dict[str, Any]]:
    if not payload.get("workflow_id"):
        return activities
    activities.append(
        await _activity(
            "WorkflowStatusActivity",
            {
                "workflow_id": payload.get("workflow_id"),
                "workflow_type": payload.get("workflow_type") or workflow_name,
                "status": status,
                "result": result,
            },
        )
    )
    return activities


class _ApprovalWorkflow:
    workflow_name = "Workflow"

    def __init__(self) -> None:
        self.approval = ApprovalSignalState()

    @workflow.signal(name="approval_resolved")
    def approval_resolved(self, payload: dict[str, Any]) -> None:
        self.approval.resolve(payload)

    @workflow.query
    def state(self) -> dict[str, Any]:
        return self.approval.as_dict()

    async def run_until_approval_resolved(self, payload: dict[str, Any]) -> dict[str, Any]:
        if payload.get("requires_approval", True):
            await workflow.wait_condition(lambda: self.approval.payload is not None)
            return {
                "workflow": self.workflow_name,
                "status": self.approval.status,
                "approval": self.approval.payload,
            }
        return {"workflow": self.workflow_name, "status": "completed"}


@workflow.defn(name="ConnectionTestWorkflow")
class ConnectionTestWorkflow:
    @workflow.run
    async def run(self, payload: dict[str, Any]) -> dict[str, Any]:
        provider = payload.get("provider") or payload.get("connection_provider") or "unknown"
        activities = await _activity_chain(["ConnectionTestActivity"], payload)
        activity_result = activities[-1].get("result", {}) if activities else {}
        failed = isinstance(activity_result, dict) and (activity_result.get("ok") is False or activity_result.get("status") == "error")
        status = "failed" if failed else "completed"
        result = {"workflow": "ConnectionTestWorkflow", "provider": provider, "status": status}
        if isinstance(activity_result, dict) and activity_result.get("error"):
            result["error"] = activity_result["error"]
        activities = await _record_workflow_status(payload, "ConnectionTestWorkflow", status, activities, result)
        return {**result, "activities": activities}


@workflow.defn(name="DataIngestionWorkflow")
class DataIngestionWorkflow:
    @workflow.run
    async def run(self, payload: dict[str, Any]) -> dict[str, Any]:
        activities, current = await _activity_chain_with_state(["DltIngestionActivity", "GreatExpectationsValidationActivity"], payload)
        if _gx_failed(activities[-1]):
            activities.append(
                await _activity(
                    "RecordSystemEventActivity",
                    {
                        "event_type": "data_ingestion.gx_failed",
                        "severity": "error",
                        "workflow_id": payload.get("workflow_id"),
                        "dataset_spec_id": current.get("dataset_spec_id"),
                        "gx_result": current.get("result"),
                    },
                )
            )
            result = {"workflow": "DataIngestionWorkflow", "status": "failed", "dataset_spec_id": current.get("dataset_spec_id")}
            activities = await _record_workflow_status(payload, "DataIngestionWorkflow", "failed", activities, result)
            return {**result, "activities": activities}
        tail, current = await _activity_chain_with_state(["DVCVersionActivity", "DatasetRegistrationActivity"], current)
        activities.extend(tail)
        result = {"workflow": "DataIngestionWorkflow", "status": "completed", "dataset_spec_id": current.get("dataset_spec_id")}
        activities = await _record_workflow_status(payload, "DataIngestionWorkflow", "completed", activities, result)
        return {**result, "activities": activities}


def _gx_failed(activity_result: dict[str, Any]) -> bool:
    result = activity_result.get("result") if isinstance(activity_result, dict) else None
    if not isinstance(result, dict):
        return False
    validation = result.get("result") if isinstance(result.get("result"), dict) else {}
    return result.get("status") == "failed" or validation.get("success") is False


@workflow.defn(name="FactorAnalysisWorkflow")
class FactorAnalysisWorkflow:
    @workflow.run
    async def run(self, payload: dict[str, Any]) -> dict[str, Any]:
        activities = await _activity_chain(["QlibResearchActivity", "AlphalensReportActivity"], payload)
        result = {"workflow": "FactorAnalysisWorkflow", "status": "completed", "factor_spec_id": payload.get("factor_spec_id")}
        activities = await _record_workflow_status(payload, "FactorAnalysisWorkflow", "completed", activities, result)
        return {**result, "activities": activities}


@workflow.defn(name="BacktestWorkflow")
class BacktestWorkflow:
    @workflow.run
    async def run(self, payload: dict[str, Any]) -> dict[str, Any]:
        activities, current = await _activity_chain_with_state(["DVCRestoreActivity", "QuantConnectBacktestActivity"], payload)
        if not _backtest_completed(current):
            result = {
                "workflow": "BacktestWorkflow",
                "status": "prepared",
                "strategy_id": payload.get("strategy_id"),
                "backtest_run_id": current.get("backtest_run_id"),
            }
            activities = await _record_workflow_status(payload, "BacktestWorkflow", "prepared", activities, result)
            return {**result, "activities": activities}
        tail, current = await _activity_chain_with_state(["QuantStatsReportActivity", "MLflowBacktestActivity", "RiskGateActivity"], current)
        activities.extend(tail)
        result = {"workflow": "BacktestWorkflow", "status": "completed", "strategy_id": payload.get("strategy_id"), "backtest_run_id": current.get("backtest_run_id")}
        activities = await _record_workflow_status(payload, "BacktestWorkflow", "completed", activities, result)
        return {**result, "activities": activities}


def _backtest_completed(payload: dict[str, Any]) -> bool:
    status = str(payload.get("backtest_status") or payload.get("quantconnect_backtest_status") or "").lower()
    return status == "completed" or payload.get("backtest_completed") is True or bool(payload.get("backtest_result"))


@workflow.defn(name="RiskReviewWorkflow")
class RiskReviewWorkflow:
    @workflow.run
    async def run(self, payload: dict[str, Any]) -> dict[str, Any]:
        activities = await _activity_chain(["RiskGateActivity"], payload)
        result = {"workflow": "RiskReviewWorkflow", "status": "completed", "strategy_id": payload.get("strategy_id")}
        activities = await _record_workflow_status(payload, "RiskReviewWorkflow", "completed", activities, result)
        return {**result, "activities": activities}


@workflow.defn(name="ReportGenerationWorkflow")
class ReportGenerationWorkflow:
    @workflow.run
    async def run(self, payload: dict[str, Any]) -> dict[str, Any]:
        activities = await _activity_chain(["ReportGenerationActivity"], payload)
        result = {"workflow": "ReportGenerationWorkflow", "status": "completed", "owner_id": payload.get("owner_id")}
        activities = await _record_workflow_status(payload, "ReportGenerationWorkflow", "completed", activities, result)
        return {**result, "activities": activities}


@workflow.defn(name="ResearchWorkflow")
class ResearchWorkflow(_ApprovalWorkflow):
    workflow_name = "ResearchWorkflow"

    @workflow.run
    async def run(self, payload: dict[str, Any]) -> dict[str, Any]:
        activities, current = await _activity_chain_with_state(
            [
                "OpenAIAgentPlanActivity",
                "DltIngestionActivity",
                "GreatExpectationsValidationActivity",
                "DVCVersionActivity",
                "DatasetRegistrationActivity",
                "QlibResearchActivity",
                "AlphalensReportActivity",
                "QuantConnectBacktestActivity",
                "QuantStatsReportActivity",
                "MLflowBacktestActivity",
                "RiskGateActivity",
            ],
            payload,
        )
        if _risk_failed(activities[-1]):
            result = {
                "workflow": self.workflow_name,
                "status": "failed",
                "reason": "risk_gate_failed",
                "risk_verdict": current.get("risk_verdict"),
                "risk_summary": current.get("risk_summary"),
            }
            activities = await _record_workflow_status(payload, self.workflow_name, "failed", activities, result)
            return {**result, "activities": activities}
        tail, current = await _activity_chain_with_state(["ReportGenerationActivity", "ApprovalRequestActivity"], current)
        activities.extend(tail)
        approval = await self.run_until_approval_resolved(payload)
        if approval["status"] == "completed" and approval.get("approval"):
            activities.append(await _activity("StrategyRegistrationFinalizeActivity", {**current, **(approval.get("approval") or {})}))
        activities = await _record_workflow_status(payload, self.workflow_name, approval["status"], activities, approval)
        return {**approval, "activities": activities}


def _risk_failed(activity_result: dict[str, Any]) -> bool:
    result = activity_result.get("result") if isinstance(activity_result, dict) else None
    if not isinstance(result, dict):
        return False
    risk_summary = result.get("risk_summary") if isinstance(result.get("risk_summary"), dict) else {}
    verdict = str(result.get("risk_verdict") or risk_summary.get("verdict") or "").lower()
    return result.get("status") == "failed" or verdict in {"fail", "failed", "deny", "denied"}


@workflow.defn(name="StrategyRegistrationWorkflow")
class StrategyRegistrationWorkflow(_ApprovalWorkflow):
    workflow_name = "StrategyRegistrationWorkflow"

    @workflow.run
    async def run(self, payload: dict[str, Any]) -> dict[str, Any]:
        activities = await _activity_chain(["RiskGateActivity"], payload)
        if _risk_failed(activities[0]):
            result = {
                "workflow": self.workflow_name,
                "status": "failed",
                "reason": "risk_gate_failed",
                "risk_verdict": activities[0].get("result", {}).get("risk_verdict"),
                "risk_summary": activities[0].get("result", {}).get("risk_summary"),
            }
            activities = await _record_workflow_status(payload, self.workflow_name, "failed", activities, result)
            return {**result, "activities": activities}
        activities.extend(await _activity_chain(["StrategyRegistrationPendingActivity", "ApprovalRequestActivity"], payload))
        approval = await self.run_until_approval_resolved(payload)
        if approval["status"] == "completed":
            activities.append(await _activity("StrategyRegistrationFinalizeActivity", {**payload, **(approval.get("approval") or {})}))
        activities = await _record_workflow_status(payload, self.workflow_name, approval["status"], activities, approval)
        return {**approval, "activities": activities}


@workflow.defn(name="PaperPromotionWorkflow")
class PaperPromotionWorkflow(_ApprovalWorkflow):
    workflow_name = "PaperPromotionWorkflow"

    @workflow.run
    async def run(self, payload: dict[str, Any]) -> dict[str, Any]:
        activities = await _activity_chain(["RiskGateActivity"], payload)
        if _risk_failed(activities[0]):
            result = {
                "workflow": self.workflow_name,
                "status": "failed",
                "reason": "risk_gate_failed",
                "risk_verdict": activities[0].get("result", {}).get("risk_verdict"),
                "risk_summary": activities[0].get("result", {}).get("risk_summary"),
            }
            activities = await _record_workflow_status(payload, self.workflow_name, "failed", activities, result)
            return {**result, "activities": activities}
        if payload.get("requires_approval", True):
            activities.extend(await _activity_chain(["PaperPromotionCandidateActivity", "ApprovalRequestActivity"], payload))
        approval = await self.run_until_approval_resolved(payload)
        if approval["status"] == "completed" and payload.get("requires_approval", True):
            activities.append(await _activity("PaperPromotionFinalizeActivity", {**payload, **(approval.get("approval") or {})}))
        activities = await _record_workflow_status(payload, self.workflow_name, approval["status"], activities, approval)
        return {**approval, "activities": activities}


WORKFLOW_TYPES = [
    ConnectionTestWorkflow,
    DataIngestionWorkflow,
    ResearchWorkflow,
    FactorAnalysisWorkflow,
    BacktestWorkflow,
    RiskReviewWorkflow,
    StrategyRegistrationWorkflow,
    PaperPromotionWorkflow,
    ReportGenerationWorkflow,
]
