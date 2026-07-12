from __future__ import annotations

import hashlib
import json
import subprocess
import time
from datetime import UTC, date, datetime
from html import escape
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field
from sqlalchemy import select

from app.core.config import get_settings
from app.core.redaction import redact_secrets

try:
    from temporalio import activity
except Exception:  # pragma: no cover - local test env may not install temporalio

    class _ActivityShim:
        @staticmethod
        def defn(name: str | None = None):
            def decorate(fn):
                fn.__temporal_name__ = name or fn.__name__
                return fn

            return decorate

    activity = _ActivityShim()


class AgentPlan(BaseModel):
    objective: str
    steps: list[str] = Field(default_factory=list)
    required_tools: list[str] = Field(default_factory=list)


@activity.defn(name="OpenAIAgentPlanActivity")
def openai_agent_plan_activity(payload: dict[str, Any]) -> dict[str, Any]:
    prompt = _agent_prompt(payload)
    started = time.perf_counter()
    try:
        output = _openai_agent_plan(payload, prompt)
        plan = output["plan"]
        tool = str(output.get("mode") or "openai_agents_sdk")
        trace = _log_agent_activity_trace(payload, plan, tool, latency=time.perf_counter() - started)
        return {"status": "completed", "tool": tool, "plan": plan, "langfuse_trace_id": trace.get("trace_id")}
    except Exception as exc:
        if not get_settings().allow_agent_fallback:
            failed_plan = AgentPlan(objective=str(payload.get("objective") or payload.get("research_idea_id") or "agent plan failed")).model_dump()
            _log_agent_activity_trace(payload, failed_plan, "openai_agents_sdk", str(exc), status="failed", latency=time.perf_counter() - started)
            raise
        plan = _fallback_plan(payload)
        trace = _log_agent_activity_trace(payload, plan, "deterministic_fallback", str(exc), latency=time.perf_counter() - started)
        return {"status": "completed", "tool": "deterministic_fallback", "error": str(exc), "plan": plan, "langfuse_trace_id": trace.get("trace_id")}


@activity.defn(name="ConnectionTestActivity")
def connection_test_activity(payload: dict[str, Any]) -> dict[str, Any]:
    from sqlalchemy import select

    from app.db.models import ExternalConnection
    from app.db.session import SessionLocal, init_db
    from app.services.audit import write_audit_log
    from app.services.connections import PROVIDERS

    provider = str(payload.get("provider") or payload.get("connection_provider") or "")
    if not provider:
        raise ValueError("provider is required")
    init_db()
    with SessionLocal() as db:
        stmt = select(ExternalConnection).where(ExternalConnection.provider == provider)
        if payload.get("connection_id"):
            stmt = select(ExternalConnection).where(ExternalConnection.id == str(payload["connection_id"]))
        connection = db.scalar(stmt)
        if not connection:
            raise ValueError(f"connection not found for provider: {provider}")
        connection.last_checked_at = datetime.now(UTC)
        if provider == "ibkr" or connection.status == "locked":
            connection.status = "locked"
            connection.last_error = None
            write_audit_log(db, "connection.test_locked", "external_connection", connection.id, {"provider": provider, "workflow_id": payload.get("workflow_id")})
            db.commit()
            return {"provider": provider, "status": "locked", "mode": "temporal_activity", "workflow_id": payload.get("workflow_id")}

        spec = PROVIDERS.get(provider, {})
        adapter_name = _connection_test_adapter(provider)
        gateway_result = _run_gateway_activity(
            adapter_name,
            {**_connection_runtime_defaults(provider), "workflow_id": payload.get("workflow_id"), "connection_test": True, "required_fields": spec.get("required_fields", [])},
            "ConnectionTestAgent",
            db=db,
            connection_id=connection.id,
        )
        if not gateway_result.ok:
            connection.status = "error"
            connection.last_error = gateway_result.error or "connection validation failed"
            write_audit_log(db, "connection.test_failed", "external_connection", connection.id, {"provider": provider, "error": connection.last_error, "workflow_id": payload.get("workflow_id")})
            db.commit()
            return {"provider": provider, "status": "error", "ok": False, "error": connection.last_error, "workflow_id": payload.get("workflow_id")}

        connection.status = "connected"
        connection.last_error = None
        write_audit_log(db, "connection.test_succeeded", "external_connection", connection.id, {"provider": provider, "workflow_id": payload.get("workflow_id")})
        db.commit()
        return {"provider": provider, "status": "connected", "ok": True, "tool": adapter_name, "adapter_output": gateway_result.output, "workflow_id": payload.get("workflow_id")}


@activity.defn(name="DltIngestionActivity")
def dlt_ingestion_activity(payload: dict[str, Any]) -> dict[str, Any]:
    from datetime import date

    from app.services.datasets import SAMPLE_OHLCV_ROWS
    from data_contracts.dlt.massive_source import build_source

    _gateway_output("dlt", payload, "DataAgent")
    input_rows = payload.get("rows") or payload.get("sample_rows")
    if not input_rows and _strict_mature_tool_mode():
        raise RuntimeError("dlt pipeline requires explicit rows or Massive source output in strict mode")
    rows = input_rows or SAMPLE_OHLCV_ROWS
    rows_provenance = "user_supplied" if input_rows else "sample"
    symbols = payload.get("symbols") or sorted({row.get("symbol") for row in rows if row.get("symbol")}) or ["SPY"]
    start = payload.get("start") or (rows[0]["date"] if rows else "2026-01-02")
    end = payload.get("end") or (rows[-1]["date"] if rows else start)
    source = build_source(symbols, date.fromisoformat(start), date.fromisoformat(end), payload.get("frequency", "1d"))
    if not _module_available("dlt") or not rows:
        if _strict_mature_tool_mode():
            raise RuntimeError("dlt pipeline failed in strict mode: dlt unavailable or no rows supplied")
        return {
            "status": "prepared",
            "dataset_spec_id": payload.get("dataset_spec_id", "pending"),
            "tool": "dlt",
            "mode": "contract_fallback",
            "contract": source.contract(),
            "rows": rows,
            "rows_provenance": rows_provenance,
        }

    try:
        import dlt

        pipeline = dlt.pipeline(
            pipeline_name=payload.get("pipeline_name", "massive_ohlcv"),
            destination=payload.get("destination", "duckdb"),
            dataset_name=payload.get("dataset_name", "market_data"),
        )
        load_info = pipeline.run(source.to_dlt_source(lambda *_args: rows))
        return {
            "status": "loaded",
            "dataset_spec_id": payload.get("dataset_spec_id", "pending"),
            "tool": "dlt",
            "mode": "dlt_pipeline",
            "contract": source.contract(),
            "rows": rows,
            "rows_provenance": rows_provenance,
            "load_info": str(load_info),
        }
    except Exception as exc:
        return {
            "status": "prepared",
            "dataset_spec_id": payload.get("dataset_spec_id", "pending"),
            "tool": "dlt",
            "mode": "contract_fallback",
            "contract": source.contract(),
            "rows": rows,
            "rows_provenance": rows_provenance,
            "error": str(exc),
        }


@activity.defn(name="GreatExpectationsValidationActivity")
def great_expectations_validation_activity(payload: dict[str, Any]) -> dict[str, Any]:
    from app.services.datasets import SAMPLE_OHLCV_ROWS

    _gateway_output("great_expectations", payload, "DataAgent")
    input_rows = payload.get("rows") or payload.get("sample_rows")
    if not input_rows and _strict_mature_tool_mode():
        raise RuntimeError("Great Expectations validation requires explicit rows in strict mode")
    rows = input_rows or SAMPLE_OHLCV_ROWS
    suite = payload.get("suite", "ohlcv_daily_suite")
    if not rows:
        return {"status": "skipped", "suite": suite, "tool": "great_expectations", "reason": "no rows supplied"}
    from app.services.data_quality import validate_suite

    result = validate_suite(suite, rows)
    return {"status": "passed" if result["success"] else "failed", "suite": suite, "tool": "great_expectations", "result": result}


@activity.defn(name="DVCVersionActivity")
def dvc_version_activity(payload: dict[str, Any]) -> dict[str, Any]:
    _gateway_output("dvc", payload, "DataAgent")
    dataset_id = payload.get("dataset_spec_id", "pending")
    dataset_path = payload.get("dataset_path") or _write_rows_for_dvc(dataset_id, payload.get("rows") or payload.get("sample_rows"))
    if dataset_path:
        if _module_available("dvc"):
            try:
                subprocess.run(["dvc", "add", str(dataset_path)], check=True, capture_output=True, text=True)
                subprocess.run(["dvc", "push", "-r", "minio"], check=True, capture_output=True, text=True)
                revision = _file_revision(dataset_path)
                return {
                    "status": "versioned",
                    "dataset_version": f"dvc:{dataset_id}:{revision}",
                    "dvc_rev": revision,
                    "tool": "dvc",
                    "mode": "dvc_cli",
                    "remote": "minio",
                    "dataset_path": str(dataset_path),
                }
            except Exception as exc:
                error = str(exc)
        else:
            error = "dvc module not available"
        if _strict_mature_tool_mode():
            raise RuntimeError(f"DVC versioning failed in strict mode: {error}")
        revision = _file_revision(dataset_path)
        return {
            "status": "versioned",
            "dataset_version": f"dvc:{dataset_id}:{revision}",
            "dvc_rev": revision,
            "tool": "dvc",
            "mode": "local_fallback",
            "remote": "minio",
            "dataset_path": str(dataset_path),
            "error": error,
        }
    raw = json.dumps(payload, sort_keys=True, default=str).encode("utf-8")
    if _strict_mature_tool_mode():
        raise RuntimeError("DVC versioning requires dataset_path or rows in strict mode")
    revision = hashlib.sha256(raw).hexdigest()[:12]
    return {"status": "versioned", "dataset_version": f"dvc:{dataset_id}:{revision}", "dvc_rev": revision, "tool": "dvc", "mode": "local_fallback", "remote": "minio"}


@activity.defn(name="DVCRestoreActivity")
def dvc_restore_activity(payload: dict[str, Any]) -> dict[str, Any]:
    _gateway_output("dvc", {**payload, "action": "restore_dataset"}, "BacktestAgent")
    dataset_version = str(payload.get("dataset_version") or "").strip()
    if not dataset_version:
        raise ValueError("dataset_version is required")
    dvc_rev = str(payload.get("dvc_rev") or dataset_version.rsplit(":", 1)[-1])
    dataset_path = payload.get("dataset_path") or _registered_dataset_path(payload.get("dataset_spec_id"), dataset_version, dvc_rev)
    if dataset_path and _module_available("dvc"):
        try:
            subprocess.run(["dvc", "pull", str(dataset_path), "-r", "minio"], check=True, capture_output=True, text=True)
            return {
                "status": "restored",
                "dataset_version": dataset_version,
                "dvc_rev": dvc_rev,
                "tool": "dvc",
                "mode": "dvc_cli",
                "remote": "minio",
                "dataset_path": str(dataset_path),
            }
        except Exception as exc:
            if _strict_mature_tool_mode():
                raise RuntimeError(f"DVC restore failed in strict mode: {exc}") from exc
            return {
                "status": "restore_prepared",
                "dataset_version": dataset_version,
                "dvc_rev": dvc_rev,
                "tool": "dvc",
                "mode": "restore_request_prepared",
                "remote": "minio",
                "dataset_path": str(dataset_path),
                "error": str(exc),
            }
    if _strict_mature_tool_mode():
        reason = "registered dataset_path is missing" if not dataset_path else "dvc module not available"
        raise RuntimeError(f"DVC restore failed in strict mode: {reason}")
    return {
        "status": "restore_prepared",
        "dataset_version": dataset_version,
        "dvc_rev": dvc_rev,
        "tool": "dvc",
        "mode": "restore_request_prepared",
        "remote": "minio",
        **({"dataset_path": str(dataset_path)} if dataset_path else {}),
    }


@activity.defn(name="DatasetRegistrationActivity")
def dataset_registration_activity(payload: dict[str, Any]) -> dict[str, Any]:
    from app.db.session import SessionLocal, init_db
    from app.services.datasets import SAMPLE_OHLCV_ROWS, create_ohlcv_dataset

    init_db()
    input_rows = payload.get("rows") or payload.get("sample_rows")
    if not input_rows and _strict_mature_tool_mode():
        raise RuntimeError("dataset registration requires explicit rows in strict mode")
    rows = input_rows or SAMPLE_OHLCV_ROWS
    name = str(payload.get("dataset_name") or payload.get("dataset_spec_id") or "massive_ohlcv")
    gx_result = payload.get("result") if isinstance(payload.get("result"), dict) else None
    contract = payload.get("contract") if isinstance(payload.get("contract"), dict) else None
    with SessionLocal() as db:
        result = create_ohlcv_dataset(
            db,
            name,
            rows,
            dataset_spec_id=payload.get("dataset_spec_id"),
            dataset_version=payload.get("dataset_version"),
            dvc_rev=payload.get("dvc_rev"),
            gx_result=gx_result,
            dlt_contract=contract,
        )
        db.commit()
        return {"status": "registered", "tool": "postgres", **result}


@activity.defn(name="QlibResearchActivity")
def qlib_research_activity(payload: dict[str, Any]) -> dict[str, Any]:
    output = _gateway_output("qlib", payload, "FactorAgent")
    output["mode"] = "library_available" if _module_available("qlib") else output["mode"]
    analysis = _factor_analysis(payload)
    evidence_grade = _analysis_evidence_grade(payload, analysis)
    metrics = {"information_coefficient": analysis["ic"], "icir": analysis.get("icir")} if analysis else {"information_coefficient": 0.0, "annualized_return": 0.0}
    output["artifacts"] = [
        _sample_artifact(
            payload,
            artifact_type="qlib_research_summary",
            owner_type="factor",
            owner_id=str(payload.get("factor_spec_id") or payload.get("research_idea_id") or "sample"),
            relative_path=f"factors/{payload.get('factor_spec_id') or 'sample'}/qlib_research_summary.json",
            content={
                "tool": "Qlib",
                "dataset_spec_id": payload.get("dataset_spec_id"),
                "factor_spec_id": payload.get("factor_spec_id"),
                "metrics": metrics,
                "factor_analysis": analysis,
                "evidence_grade": evidence_grade,
                "mode": output["mode"],
            },
            content_type="application/json",
            evidence_grade=evidence_grade,
        )
    ]
    if analysis:
        output["factor_analysis"] = analysis
    return output


@activity.defn(name="AlphalensReportActivity")
def alphalens_report_activity(payload: dict[str, Any]) -> dict[str, Any]:
    output = _gateway_output("alphalens", payload, "FactorAgent")
    output["mode"] = "library_available" if _module_available("alphalens") else output["mode"]
    factor_id = str(payload.get("factor_spec_id") or "sample")
    analysis = _factor_analysis(payload)
    evidence_grade = _analysis_evidence_grade(payload, analysis)
    if analysis:
        report_rows = {
            "factor_spec_id": factor_id,
            "IC": f"{analysis['ic']:.4f}",
            "ICIR": f"{analysis['icir']:.4f}" if analysis.get("icir") is not None else "n/a",
            "ic_mode": analysis["ic_mode"],
            "observations": analysis["observations"],
            "quantile_returns": json.dumps(analysis.get("quantile_forward_returns", {}), sort_keys=True),
            "method": analysis["method"],
            "evidence_grade": evidence_grade,
        }
    else:
        report_rows = {
            "factor_spec_id": factor_id,
            "IC": "0.000",
            "ICIR": "0.000",
            "quantile_returns": "sample",
            "turnover": "sample",
            "factor_decay": "sample",
            "evidence_grade": evidence_grade,
        }
    output["artifacts"] = [
        _sample_artifact(
            payload,
            artifact_type="alphalens_factor_tear_sheet",
            owner_type="factor",
            owner_id=factor_id,
            relative_path=f"factors/{factor_id}/alphalens_tear_sheet.html",
            content=_html_report("Alphalens factor tear sheet", report_rows),
            content_type="text/html",
            evidence_grade=evidence_grade,
        )
    ]
    if analysis:
        output["factor_analysis"] = analysis
    output["factor_report_evidence_grade"] = evidence_grade
    return output


@activity.defn(name="QuantConnectBacktestActivity")
def quantconnect_backtest_activity(payload: dict[str, Any]) -> dict[str, Any]:
    sequence = [
        _gateway_output("quantconnect_mcp", {**payload, "action": action}, "BacktestAgent")
        for action in [
            "create_project",
            "upload_strategy_files",
            "run_backtest",
            "poll_backtest_status",
            "fetch_backtest_result",
            "fetch_backtest_charts_or_links",
        ]
    ]
    return {
        "status": "mcp_request_prepared",
        "backtest_run_id": payload.get("backtest_run_id", "generated"),
        "tool": "quantconnect_mcp",
        "sequence": sequence,
    }


@activity.defn(name="QuantStatsReportActivity")
def quantstats_report_activity(payload: dict[str, Any]) -> dict[str, Any]:
    output = _gateway_output("quantstats", payload, "BacktestAgent")
    output["mode"] = "library_available" if _module_available("quantstats") else output["mode"]
    owner_id = str(payload.get("backtest_run_id") or payload.get("strategy_id") or "sample")
    strategy_stats = _strategy_stats(payload)
    evidence_grade = _analysis_evidence_grade(payload, strategy_stats)
    if strategy_stats:
        report_rows = {
            "backtest_run_id": payload.get("backtest_run_id") or "sample",
            "strategy_id": payload.get("strategy_id") or "sample",
            "Sharpe": f"{strategy_stats['sharpe']:.4f}",
            "max_drawdown": f"{strategy_stats['max_drawdown']:.4f}",
            "turnover_daily": f"{strategy_stats['turnover_daily']:.4f}",
            "cumulative_return": f"{strategy_stats['cumulative_return']:.4f}",
            "observations": strategy_stats["observations"],
            "method": strategy_stats["method"],
            "evidence_grade": evidence_grade,
        }
    else:
        report_rows = {
            "backtest_run_id": payload.get("backtest_run_id") or "sample",
            "strategy_id": payload.get("strategy_id") or "sample",
            "Sharpe": "0.000",
            "Sortino": "0.000",
            "volatility": "0.000",
            "drawdown": "0.000",
            "monthly_returns": "sample",
            "evidence_grade": evidence_grade,
        }
    output["artifacts"] = [
        _sample_artifact(
            payload,
            artifact_type="quantstats_strategy_tear_sheet",
            owner_type="backtest",
            owner_id=owner_id,
            relative_path=f"backtests/{owner_id}/quantstats_tear_sheet.html",
            content=_html_report("QuantStats strategy tear sheet", report_rows),
            content_type="text/html",
            evidence_grade=evidence_grade,
        )
    ]
    if strategy_stats:
        output["computed_strategy_metrics"] = strategy_stats
    return output


@activity.defn(name="MLflowBacktestActivity")
def mlflow_backtest_activity(payload: dict[str, Any]) -> dict[str, Any]:
    from app.db.models import Artifact, BacktestRun, DatasetSpec
    from app.db.session import SessionLocal, init_db
    from app.services.mlflow_tracking import log_backtest_run_to_mlflow

    init_db()
    with SessionLocal() as db:
        gateway_result = _run_gateway_activity("mlflow", payload, "BacktestAgent", db=db)
        if not gateway_result.ok:
            raise RuntimeError(gateway_result.error or "MLflow adapter denied")
        dataset_id = str(payload.get("dataset_spec_id") or "sample-dataset")
        dataset = db.get(DatasetSpec, dataset_id)
        if not dataset:
            dataset = DatasetSpec(
                id=dataset_id,
                name=dataset_id,
                dataset_version=str(payload.get("dataset_version") or "sample"),
                dvc_rev=str(payload.get("dvc_rev") or "sample"),
            )
            db.add(dataset)
            db.flush()

        backtest_id = str(payload.get("backtest_run_id") or "sample-backtest")
        backtest = db.get(BacktestRun, backtest_id)
        if not backtest:
            backtest = BacktestRun(
                id=backtest_id,
                strategy_id=str(payload.get("strategy_id") or "sample-strategy"),
                dataset_spec_id=dataset.id,
                dataset_version=dataset.dataset_version,
                start_date=date.fromisoformat(str(payload.get("start_date") or "2020-01-01")),
                end_date=date.fromisoformat(str(payload.get("end_date") or "2025-01-01")),
                status=_backtest_status_from_payload(payload),
                metrics=payload.get("metrics") if isinstance(payload.get("metrics"), dict) else {},
            )
            db.add(backtest)
            db.flush()

        artifact_ids = [
            item.get("artifact_id")
            for item in payload.get("artifacts", [])
            if isinstance(item, dict) and item.get("artifact_id")
        ]
        artifacts = [artifact for artifact in (db.get(Artifact, artifact_id) for artifact_id in artifact_ids) if artifact]
        result = log_backtest_run_to_mlflow(
            db,
            backtest,
            {
                "dataset_version": backtest.dataset_version or dataset.dataset_version or "sample",
                "workflow_id": payload.get("workflow_id") or "",
                "factor_id": payload.get("factor_spec_id") or payload.get("factor_id") or "",
                "dvc_rev": payload.get("dvc_rev") or dataset.dvc_rev or "",
                "git_commit": payload.get("git_commit") or "",
            },
            backtest.metrics or {},
            artifacts,
        )
        existing_artifacts = backtest.artifacts or []
        backtest.artifacts = [*existing_artifacts, *[artifact_id for artifact_id in artifact_ids if artifact_id not in existing_artifacts]]
        db.commit()
        return {
            "status": "logged",
            "tool": "MLflow",
            "backtest_run_id": backtest.id,
            "mlflow_run_id": result["mlflow_run_id"],
            "mode": result["mode"],
            "artifact_ids": artifact_ids,
        }


@activity.defn(name="RiskGateActivity")
def risk_gate_activity(payload: dict[str, Any]) -> dict[str, Any]:
    from app.db.session import SessionLocal, init_db
    from app.risk.engine import evaluate_risk_gate, persist_risk_review
    from app.services.evidence import factor_report_evidence_grade

    init_db()
    metrics = payload.get("metrics") if isinstance(payload.get("metrics"), dict) else {}
    cost_model = payload.get("cost_model") if isinstance(payload.get("cost_model"), dict) else None
    slippage_model = payload.get("slippage_model") if isinstance(payload.get("slippage_model"), dict) else None
    factor_report_present = bool(payload.get("factor_report_present") or _has_artifact(payload, "alphalens_factor_tear_sheet"))
    with SessionLocal() as db:
        evidence_grade = factor_report_evidence_grade(db, payload)
        decision = evaluate_risk_gate(
            db,
            metrics=metrics,
            cost_model=cost_model,
            slippage_model=slippage_model,
            factor_report_present=factor_report_present,
            start_date=_payload_date(payload, "start_date"),
            end_date=_payload_date(payload, "end_date"),
            request_type=str(payload.get("request_type") or "risk_review"),
            actor=str(payload.get("requested_by_agent") or "RiskAgent"),
            workflow_id=payload.get("workflow_id"),
            evidence_grade=evidence_grade,
        )
        review = persist_risk_review(
            db,
            decision,
            strategy_id=payload.get("strategy_id"),
            backtest_run_id=payload.get("backtest_run_id"),
            actor=str(payload.get("requested_by_agent") or "RiskAgent"),
        )
        db.commit()
    return {
        "status": "passed" if decision.verdict == "pass" else "failed",
        "policy_package": "risk_gate",
        "tool": "opa",
        "risk_review_id": review.id if review else None,
        "risk_verdict": decision.verdict,
        "hard_rule_results": decision.hard_rule_results,
        "risk_summary": {
            **decision.risk_summary,
            "verdict": decision.verdict,
            "policy_package": "risk_gate",
        },
    }


@activity.defn(name="ReportGenerationActivity")
def report_generation_activity(payload: dict[str, Any]) -> dict[str, Any]:
    from sqlalchemy import select

    from app.db.models import BacktestRun, DatasetSpec, RiskReview, StrategyCard, StrategySpec
    from app.db.session import SessionLocal, init_db
    from app.services.artifacts import create_artifact
    from app.services.audit import write_audit_log

    init_db()
    with SessionLocal() as db:
        strategy_id = payload.get("strategy_id")
        strategy = db.get(StrategySpec, str(strategy_id)) if strategy_id else None
        workflow_id = str(payload.get("workflow_id")) if payload.get("workflow_id") else None
        if not strategy and workflow_id:
            existing_card = db.scalar(select(StrategyCard).where(StrategyCard.workflow_id == workflow_id))
            if existing_card:
                strategy = db.get(StrategySpec, existing_card.strategy_id)
        if not strategy:
            label = str(payload.get("research_idea_id") or workflow_id or "sample")
            strategy = StrategySpec(
                name=str(payload.get("strategy_name") or f"Strategy from {label}"),
                description=str(payload.get("thesis") or payload.get("objective") or "Generated research strategy candidate."),
                universe=str(payload.get("universe") or "US equities"),
                factors=payload.get("factors") if isinstance(payload.get("factors"), list) else [],
                status="APPROVAL_PENDING",
            )
            db.add(strategy)
            db.flush()
        elif strategy.status not in {"STRATEGY_REGISTERED", "PAPER_CANDIDATE", "PAPER_APPROVED", "PAPER_TRADING"}:
            strategy.status = "APPROVAL_PENDING"

        card = db.scalar(select(StrategyCard).where(StrategyCard.strategy_id == strategy.id))
        prior_artifacts = [
            item.get("artifact_id")
            for item in payload.get("artifacts", [])
            if isinstance(item, dict) and item.get("artifact_id")
        ]
        if not card:
            card = StrategyCard(
                strategy_id=strategy.id,
                current_status=strategy.status,
                thesis=strategy.description,
                universe=strategy.universe,
                factor_summary={"factors": strategy.factors},
                latest_backtest_metrics=payload.get("metrics") if isinstance(payload.get("metrics"), dict) else {},
                approval_status="pending",
                workflow_id=workflow_id,
                artifacts=[],
            )
            db.add(card)
            db.flush()
        else:
            card.current_status = strategy.status
            card.approval_status = "pending"
            card.workflow_id = workflow_id or card.workflow_id

        dataset_id = str(payload.get("dataset_spec_id") or "sample-dataset")
        dataset = db.get(DatasetSpec, dataset_id)
        if not dataset:
            dataset = DatasetSpec(
                id=dataset_id,
                name=dataset_id,
                dataset_version=str(payload.get("dataset_version") or "sample"),
                dvc_rev=str(payload.get("dvc_rev") or "sample"),
            )
            db.add(dataset)
            db.flush()

        backtest_id = str(payload.get("backtest_run_id") or f"{strategy.id}-sample-backtest")
        backtest = db.get(BacktestRun, backtest_id)
        if not backtest:
            completed_backtest = _has_completed_backtest_result(payload)
            backtest = BacktestRun(
                id=backtest_id,
                strategy_id=strategy.id,
                dataset_spec_id=dataset.id,
                dataset_version=dataset.dataset_version,
                start_date=date.fromisoformat(str(payload.get("start_date") or "2020-01-01")),
                end_date=date.fromisoformat(str(payload.get("end_date") or "2025-01-01")),
                status=_backtest_status_from_payload(payload),
                metrics=payload.get("metrics") if isinstance(payload.get("metrics"), dict) else {},
                cost_model=payload.get("cost_model") if completed_backtest and isinstance(payload.get("cost_model"), dict) else {},
                slippage_model=payload.get("slippage_model") if completed_backtest and isinstance(payload.get("slippage_model"), dict) else {},
            )
            db.add(backtest)
            db.flush()
        elif backtest.strategy_id in {strategy.id, "sample-strategy"}:
            backtest.strategy_id = strategy.id
            if _has_completed_backtest_result(payload):
                backtest.status = _backtest_status_from_payload(payload)
                backtest.cost_model = backtest.cost_model or (payload.get("cost_model") if isinstance(payload.get("cost_model"), dict) else {})
                backtest.slippage_model = backtest.slippage_model or (payload.get("slippage_model") if isinstance(payload.get("slippage_model"), dict) else {})
            backtest.metrics = backtest.metrics or (payload.get("metrics") if isinstance(payload.get("metrics"), dict) else {})

        risk_review = db.scalar(
            select(RiskReview)
            .where(RiskReview.strategy_id == strategy.id)
            .order_by(RiskReview.created_at.desc())
            .limit(1)
        )
        if not risk_review:
            risk_summary = payload.get("risk_summary") if isinstance(payload.get("risk_summary"), dict) else {}
            risk_verdict = str(payload.get("risk_verdict") or risk_summary.get("verdict") or "fail")
            if not risk_summary:
                risk_summary = {"verdict": risk_verdict, "reason": "missing risk gate evidence"}
            else:
                risk_summary = {**risk_summary, "verdict": risk_verdict}
            risk_review = RiskReview(
                strategy_id=strategy.id,
                backtest_run_id=backtest.id,
                verdict=risk_verdict,
                hard_rule_results=[{"policy_package": "risk_gate", "status": payload.get("status") or ("passed" if risk_verdict == "pass" else "failed")}],
                risk_summary=risk_summary,
            )
            db.add(risk_review)
            db.flush()
        card.latest_risk_review = risk_review.id

        memo = create_artifact(
            db,
            "research_memo",
            "strategy",
            strategy.id,
            f"strategies/{strategy.id}/research_memo.html",
            _html_report(
                "Research memo",
                {
                    "strategy_id": strategy.id,
                    "status": strategy.status,
                    "universe": strategy.universe,
                    "workflow_id": payload.get("workflow_id") or "pending",
                },
            ),
            "text/html",
            {"sample_artifact": True, "tool": "ReportGenerationActivity"},
        )
        card.artifacts = [*card.artifacts, *[item for item in prior_artifacts if item not in card.artifacts], memo.id]
        write_audit_log(
            db,
            "strategy_card.generated",
            "strategy",
            strategy.id,
            {"strategy_card_id": card.id, "research_memo_artifact_id": memo.id},
            actor=str(payload.get("requested_by_agent") or "ReportAgent"),
        )
        db.commit()
        return {
            "status": "completed",
            "artifact_type": "strategy_card",
            "strategy_id": strategy.id,
            "target_id": strategy.id,
            "target_type": "strategy",
            "request_type": "register_strategy",
            "strategy_card_id": card.id,
            "research_memo_artifact_id": memo.id,
            "artifacts": [{"artifact_id": memo.id, "artifact_type": memo.artifact_type, "path": memo.path}],
        }


@activity.defn(name="ApprovalRequestActivity")
def approval_request_activity(payload: dict[str, Any]) -> dict[str, Any]:
    from app.db.models import ApprovalRequest
    from app.db.session import SessionLocal
    from app.services.approval_service import create_approval_request

    request_type = _approval_request_type(payload)
    target_type = str(payload.get("target_type") or payload.get("owner_type") or _approval_target_type(payload))
    target_id = str(payload.get("target_id") or payload.get("strategy_id") or payload.get("research_idea_id") or payload.get("owner_id") or payload.get("workflow_id") or "workflow")
    workflow_id = payload.get("workflow_id")

    with SessionLocal() as db:
        existing = None
        if workflow_id:
            existing = db.scalar(
                select(ApprovalRequest).where(
                    ApprovalRequest.workflow_id == workflow_id,
                    ApprovalRequest.request_type == request_type,
                    ApprovalRequest.target_id == target_id,
                )
            )
        request = existing or create_approval_request(
            db,
            request_type,
            target_type,
            target_id,
            str(payload.get("requested_by_agent") or "TemporalWorker"),
            payload.get("risk_summary") if isinstance(payload.get("risk_summary"), dict) else {},
            workflow_id=str(workflow_id) if workflow_id else None,
        )
        db.commit()
        return _approval_activity_result(request, "existing" if existing else "created")


@activity.defn(name="StrategyRegistrationPendingActivity")
def strategy_registration_pending_activity(payload: dict[str, Any]) -> dict[str, Any]:
    from app.db.models import StrategySpec
    from app.db.session import SessionLocal
    from app.services.strategy_state import transition_strategy

    strategy_id = str(payload.get("strategy_id") or payload.get("target_id") or "")
    if not strategy_id:
        raise ValueError("strategy_id is required")
    with SessionLocal() as db:
        strategy = db.get(StrategySpec, strategy_id)
        if not strategy:
            raise ValueError("strategy not found")
        if strategy.status != "APPROVAL_PENDING":
            transition_strategy(db, strategy, "APPROVAL_PENDING", actor=str(payload.get("actor") or "TemporalWorker"))
        db.commit()
        return {"status": "completed", "strategy_id": strategy.id, "strategy_status": strategy.status}


@activity.defn(name="StrategyRegistrationFinalizeActivity")
def strategy_registration_finalize_activity(payload: dict[str, Any]) -> dict[str, Any]:
    from app.db.session import SessionLocal
    from app.services.strategy_state import register_strategy_after_approval

    strategy_id = str(payload.get("strategy_id") or payload.get("target_id") or "")
    approval_request_id = str(payload.get("approval_request_id") or "")
    if not strategy_id or not approval_request_id:
        raise ValueError("strategy_id and approval_request_id are required")
    with SessionLocal() as db:
        strategy = register_strategy_after_approval(
            db,
            strategy_id,
            approval_request_id,
            actor=str(payload.get("actor") or "TemporalWorker"),
        )
        db.commit()
        return {"status": "completed", "strategy_id": strategy.id, "strategy_status": strategy.status}


@activity.defn(name="PaperPromotionCandidateActivity")
def paper_promotion_candidate_activity(payload: dict[str, Any]) -> dict[str, Any]:
    from app.db.models import StrategySpec
    from app.db.session import SessionLocal
    from app.services.strategy_state import can_request_paper_promotion, transition_strategy

    strategy_id = str(payload.get("strategy_id") or payload.get("target_id") or "")
    if not strategy_id:
        raise ValueError("strategy_id is required")
    with SessionLocal() as db:
        ok, reason = can_request_paper_promotion(db, strategy_id)
        if not ok:
            raise PermissionError(reason)
        strategy = db.get(StrategySpec, strategy_id)
        if not strategy:
            raise ValueError("strategy not found")
        if strategy.status != "PAPER_CANDIDATE":
            transition_strategy(db, strategy, "PAPER_CANDIDATE", actor=str(payload.get("actor") or "TemporalWorker"))
        db.commit()
        return {"status": "completed", "strategy_id": strategy.id, "strategy_status": strategy.status}


@activity.defn(name="PaperPromotionFinalizeActivity")
def paper_promotion_finalize_activity(payload: dict[str, Any]) -> dict[str, Any]:
    from sqlalchemy import select

    from app.db.models import PaperTradingSession
    from app.db.session import SessionLocal
    from app.services.strategy_state import promote_strategy_to_paper_after_approval

    strategy_id = str(payload.get("strategy_id") or payload.get("target_id") or "")
    approval_request_id = str(payload.get("approval_request_id") or "")
    if not strategy_id or not approval_request_id:
        raise ValueError("strategy_id and approval_request_id are required")
    with SessionLocal() as db:
        strategy = promote_strategy_to_paper_after_approval(
            db,
            strategy_id,
            approval_request_id,
            actor=str(payload.get("actor") or "TemporalWorker"),
        )
        gateway_result = _run_gateway_activity(
            "quantconnect_paper",
            {**payload, "strategy_id": strategy.id, "workflow_id": payload.get("workflow_id")},
            "ExecutionAgent",
            db=db,
        )
        existing_session = db.scalar(
            select(PaperTradingSession)
            .where(PaperTradingSession.strategy_id == strategy.id, PaperTradingSession.workflow_id == payload.get("workflow_id"))
            .order_by(PaperTradingSession.created_at.desc())
            .limit(1)
        )
        session = existing_session or PaperTradingSession(strategy_id=strategy.id, provider="quantconnect", workflow_id=payload.get("workflow_id"))
        session.status = "proposed" if gateway_result.ok else "blocked"
        session.deployment_ref = gateway_result.output.get("status") if gateway_result.ok else None
        session.meta = {
            "permission_level": "paper_trade",
            "proposal": gateway_result.output if gateway_result.ok else {},
            "error": gateway_result.error,
            "message": "QuantConnect paper deployment proposal prepared." if gateway_result.ok else "QuantConnect connection is required before paper deployment proposal.",
        }
        db.add(session)
        db.commit()
        return {
            "status": "completed",
            "strategy_id": strategy.id,
            "strategy_status": strategy.status,
            "paper_session_id": session.id,
            "paper_session_status": session.status,
        }


@activity.defn(name="RecordSystemEventActivity")
def record_system_event_activity(payload: dict[str, Any]) -> dict[str, Any]:
    from app.db.session import SessionLocal, init_db
    from app.services.audit import write_system_event

    init_db()
    event_type = str(payload.get("event_type") or "workflow.event")
    severity = str(payload.get("severity") or "info")
    with SessionLocal() as db:
        event = write_system_event(db, event_type, payload, severity=severity)
        db.commit()
        return {"status": "recorded", "event_type": event.event_type, "system_event_id": event.id, "severity": event.severity}


@activity.defn(name="WorkflowStatusActivity")
def workflow_status_activity(payload: dict[str, Any]) -> dict[str, Any]:
    from sqlalchemy import select

    from app.db.models import WorkflowLink
    from app.db.session import SessionLocal, init_db
    from app.services.audit import write_audit_log

    init_db()
    workflow_id = str(payload.get("workflow_id") or "")
    status = str(payload.get("status") or "completed")
    if not workflow_id:
        return {"status": "skipped", "reason": "missing workflow_id"}
    with SessionLocal() as db:
        link = db.scalar(select(WorkflowLink).where(WorkflowLink.workflow_id == workflow_id))
        if not link:
            return {"status": "skipped", "reason": "workflow link not found", "workflow_id": workflow_id}
        link.status = status
        link.meta = {**(link.meta or {}), "last_worker_result": payload.get("result") or {}}
        write_audit_log(
            db,
            f"workflow.{status}",
            "workflow",
            workflow_id,
            {"workflow_id": workflow_id, "workflow_type": payload.get("workflow_type"), "status": status},
            actor=str(payload.get("actor") or "TemporalWorker"),
        )
        db.commit()
        return {"status": "recorded", "workflow_id": workflow_id, "workflow_status": status}


ACTIVITY_TYPES = [
    openai_agent_plan_activity,
    connection_test_activity,
    dlt_ingestion_activity,
    great_expectations_validation_activity,
    dvc_version_activity,
    dvc_restore_activity,
    dataset_registration_activity,
    qlib_research_activity,
    alphalens_report_activity,
    quantconnect_backtest_activity,
    quantstats_report_activity,
    mlflow_backtest_activity,
    risk_gate_activity,
    report_generation_activity,
    approval_request_activity,
    strategy_registration_pending_activity,
    strategy_registration_finalize_activity,
    paper_promotion_candidate_activity,
    paper_promotion_finalize_activity,
    record_system_event_activity,
    workflow_status_activity,
]


def _agent_prompt(payload: dict[str, Any]) -> str:
    return f"Plan a controlled Quant Team OS workflow for: {redact_secrets(payload)}"


def _openai_agent_plan(payload: dict[str, Any], prompt: str) -> dict[str, Any]:
    from app.db.models import ExternalConnection
    from app.db.session import SessionLocal, init_db

    init_db()
    with SessionLocal() as db:
        connection = db.scalar(select(ExternalConnection).where(ExternalConnection.provider == "openai"))
        if not connection:
            raise RuntimeError("OpenAI connection is not connected")
        gateway_result = _run_gateway_activity(
            "openai",
            {"workflow_id": payload.get("workflow_id"), "purpose": "agent_plan", "prompt": prompt},
            "ChiefAgent",
            db=db,
            connection_id=connection.id,
        )
        if not gateway_result.ok:
            db.commit()
            raise RuntimeError(gateway_result.error or "OpenAI adapter denied")
        db.commit()
        return gateway_result.output


def _fallback_plan(payload: dict[str, Any]) -> dict[str, Any]:
    return AgentPlan(
        objective=f"Controlled workflow for {payload.get('research_idea_id') or payload.get('strategy_id') or 'request'}",
        steps=["prepare_data", "validate_quality", "run_research_or_backtest", "evaluate_policy", "request_human_approval"],
        required_tools=["Temporal", "OPA", "Qlib", "QuantConnect", "MinIO"],
    ).model_dump()


def _gateway_output(adapter_name: str, payload: dict[str, Any], actor: str) -> dict[str, Any]:
    result = _run_gateway_activity(adapter_name, payload, actor)
    if not result.ok:
        raise RuntimeError(result.error or f"{adapter_name} adapter denied")
    return result.output


def _run_gateway_activity(adapter_name: str, payload: dict[str, Any], actor: str, db=None, connection_id: str | None = None):
    from app.adapters.base import AdapterRunner, ToolContext
    from app.adapters.stubs import default_registry
    from app.db.session import SessionLocal, init_db

    init_db()
    if db is not None:
        return AdapterRunner(default_registry()).run(
            db,
            adapter_name,
            payload,
            ToolContext(actor=actor, agent_run_id=payload.get("workflow_id"), connection_id=connection_id),
        )
    with SessionLocal() as session:
        result = AdapterRunner(default_registry()).run(
            session,
            adapter_name,
            payload,
            ToolContext(actor=actor, agent_run_id=payload.get("workflow_id"), connection_id=connection_id),
        )
        session.commit()
        return result


def _connection_test_adapter(provider: str) -> str:
    return {
        "openai": "openai",
        "massive": "massive",
        "quantconnect": "quantconnect_mcp",
        "openbb": "openbb_widget",
        "mlflow": "mlflow",
        "langfuse": "langfuse",
        "superset": "superset_link",
        "grafana": "grafana_link",
        "temporal": "temporal_workflow",
        "jupyterlab": "jupyterlab_link",
        "infisical": "infisical",
        "keycloak": "keycloak_user",
        "minio": "minio_artifact",
        "chainlit": "chainlit_link",
    }.get(provider, provider)


def _connection_runtime_defaults(provider: str) -> dict[str, Any]:
    settings = get_settings()
    return {
        "mlflow": {"tracking_uri": settings.mlflow_tracking_uri},
        "langfuse": {"host": settings.langfuse_host},
    }.get(provider, {})


def _log_agent_activity_trace(
    payload: dict[str, Any],
    plan: dict[str, Any],
    tool: str,
    error: str | None = None,
    *,
    status: str = "completed",
    latency: float | None = None,
    usage: dict[str, Any] | None = None,
    cost: float | None = None,
) -> dict[str, Any]:
    from app.db.models import AgentRun
    from app.db.session import SessionLocal, init_db
    from app.services.langfuse_tracking import log_agent_run_to_langfuse

    init_db()
    with SessionLocal() as db:
        run = db.get(AgentRun, str(payload.get("agent_run_id"))) if payload.get("agent_run_id") else None
        if run:
            run.status = status
            run.workflow_id = run.workflow_id or payload.get("workflow_id")
            run.output_payload = {**(run.output_payload or {}), "plan": plan, "tool": tool, "error": error}
        else:
            run = AgentRun(
                task_type="openai_agent_plan",
                status=status,
                workflow_id=payload.get("workflow_id"),
                input_payload=redact_secrets(payload),
                output_payload={"plan": plan, "tool": tool, "error": error},
            )
            db.add(run)
        db.flush()
        trace = log_agent_run_to_langfuse(
            db,
            run,
            {
                "agent_name": "ChiefAgent",
                "activity": "OpenAIAgentPlanActivity",
                "tool": tool,
                "workflow_id": payload.get("workflow_id"),
                "research_idea_id": payload.get("research_idea_id"),
                "strategy_id": payload.get("strategy_id"),
                "model": get_settings().openai_model,
                "latency": latency,
                "token_usage": usage,
                "cost": cost,
                "prompt_name": "controlled_research_workflow_plan",
                "prompt_version": "v0.3",
            },
        )
        db.commit()
        return trace


def _agent_result_usage(result: Any) -> dict[str, Any] | None:
    usage = _lookup_attr(result, "usage") or _lookup_attr(result, "token_usage")
    if usage is None:
        raw_responses = _lookup_attr(result, "raw_responses") or []
        for response in raw_responses if isinstance(raw_responses, list) else []:
            usage = _lookup_attr(response, "usage") or _lookup_attr(_lookup_attr(response, "response"), "usage")
            if usage is not None:
                break
    if usage is None:
        return None
    if hasattr(usage, "model_dump"):
        return usage.model_dump()
    if isinstance(usage, dict):
        return usage
    return {
        key: value
        for key in ("input_tokens", "output_tokens", "total_tokens", "requests")
        if (value := getattr(usage, key, None)) is not None
    } or None


def _agent_result_cost(result: Any) -> float | None:
    value = _lookup_attr(result, "cost") or _lookup_attr(result, "cost_usd") or _lookup_attr(result, "estimated_cost_usd")
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _lookup_attr(value: Any, key: str) -> Any:
    if value is None:
        return None
    if isinstance(value, dict):
        return value.get(key)
    return getattr(value, key, None)


def _sample_artifact(
    payload: dict[str, Any],
    *,
    artifact_type: str,
    owner_type: str,
    owner_id: str,
    relative_path: str,
    content: dict[str, Any] | str,
    content_type: str,
    evidence_grade: str = "sample",
) -> dict[str, Any]:
    from app.db.session import SessionLocal, init_db
    from app.services.artifacts import create_artifact

    init_db()
    rendered = json.dumps(content, indent=2, sort_keys=True) if isinstance(content, dict) else content
    with SessionLocal() as db:
        artifact = create_artifact(
            db,
            artifact_type,
            owner_type,
            owner_id,
            relative_path,
            rendered,
            content_type,
            {"tool": payload.get("tool"), "sample_artifact": evidence_grade != "verified", "evidence_grade": evidence_grade},
        )
        db.commit()
        return {
            "artifact_id": artifact.id,
            "artifact_type": artifact.artifact_type,
            "owner_type": artifact.owner_type,
            "owner_id": artifact.owner_id,
            "bucket": artifact.minio_bucket,
            "object_key": artifact.object_key,
            "path": artifact.path,
            "checksum": artifact.checksum,
            "storage_mode": artifact.meta.get("storage_mode"),
            "evidence_grade": evidence_grade,
        }


def _payload_rows(payload: dict[str, Any]) -> list[dict[str, Any]]:
    rows = payload.get("rows") or payload.get("sample_rows")
    return rows if isinstance(rows, list) else []


def _factor_analysis(payload: dict[str, Any]) -> dict[str, Any] | None:
    from app.services.factor_analytics import analyze_factor_rows

    rows = _payload_rows(payload)
    if not rows:
        return None
    try:
        return analyze_factor_rows(rows)
    except Exception:
        return None


def _strategy_stats(payload: dict[str, Any]) -> dict[str, Any] | None:
    from app.services.factor_analytics import compute_strategy_metrics

    rows = _payload_rows(payload)
    if not rows:
        return None
    try:
        return compute_strategy_metrics(rows)
    except Exception:
        return None


def _analysis_evidence_grade(payload: dict[str, Any], analysis: dict[str, Any] | None) -> str:
    from app.services.evidence import EVIDENCE_SAMPLE, EVIDENCE_VERIFIED

    if analysis and str(payload.get("rows_provenance") or "") == "user_supplied":
        return EVIDENCE_VERIFIED
    return EVIDENCE_SAMPLE


def _html_report(title: str, rows: dict[str, Any]) -> str:
    items = "\n".join(f"<li><strong>{escape(str(key))}</strong>: {escape(str(value))}</li>" for key, value in rows.items())
    return f"<!doctype html><html><body><h1>{escape(title)}</h1><ul>{items}</ul></body></html>"


def _approval_request_type(payload: dict[str, Any]) -> str:
    if payload.get("request_type"):
        return str(payload["request_type"])
    workflow_type = payload.get("workflow_type")
    if workflow_type == "StrategyRegistrationWorkflow":
        return "register_strategy"
    if workflow_type == "PaperPromotionWorkflow":
        return "promote_to_paper"
    return "workflow_approval"


def _approval_target_type(payload: dict[str, Any]) -> str:
    if payload.get("strategy_id"):
        return "strategy"
    if payload.get("research_idea_id"):
        return "research_idea"
    return "workflow"


def _approval_activity_result(request, mode: str) -> dict[str, Any]:
    return {
        "status": "approval_required",
        "mode": mode,
        "approval_request_id": request.id,
        "request_type": request.request_type,
        "target_type": request.target_type,
        "target_id": request.target_id,
        "workflow_id": request.workflow_id,
    }


def _has_artifact(payload: dict[str, Any], artifact_type: str) -> bool:
    return any(
        isinstance(item, dict) and item.get("artifact_type") == artifact_type
        for item in payload.get("artifacts", [])
    )


def _payload_date(payload: dict[str, Any], key: str) -> date | None:
    value = payload.get(key)
    if not value:
        return None
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value))
    except ValueError:
        return None


def _has_completed_backtest_result(payload: dict[str, Any]) -> bool:
    status = str(payload.get("backtest_status") or payload.get("quantconnect_backtest_status") or "").lower()
    return status == "completed" or bool(payload.get("backtest_completed") is True or payload.get("backtest_result"))


def _backtest_status_from_payload(payload: dict[str, Any]) -> str:
    return "completed" if _has_completed_backtest_result(payload) else "result_pending"


def _write_rows_for_dvc(dataset_id: str, rows: Any) -> Path | None:
    if not rows:
        return None
    import pandas as pd

    root = Path(get_settings().artifact_root).resolve()
    safe_dataset_id = str(dataset_id or "pending").replace("/", "_")
    target = root / "datasets" / safe_dataset_id / "ohlcv_daily.parquet"
    target.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows).to_parquet(target, index=False)
    return target


def _file_revision(path: str | Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()[:12]


def _registered_dataset_path(dataset_spec_id: Any, dataset_version: str, dvc_rev: str) -> str | None:
    dataset_id = str(dataset_spec_id or _dataset_id_from_version(dataset_version) or "")
    if not dataset_id:
        return None
    try:
        from app.db.models import Artifact
        from app.db.session import SessionLocal, init_db

        init_db()
        with SessionLocal() as db:
            artifact = None
            if dataset_id != "pending":
                query = db.query(Artifact).filter(Artifact.owner_type == "dataset", Artifact.owner_id == dataset_id)
                if dvc_rev:
                    query = query.filter(Artifact.dvc_rev == dvc_rev)
                artifact = query.order_by(Artifact.created_at.desc()).first()
            if not artifact and dvc_rev:
                artifact = db.query(Artifact).filter(Artifact.owner_type == "dataset", Artifact.dvc_rev == dvc_rev).order_by(Artifact.created_at.desc()).first()
            if not artifact:
                return None
            return str(Path(get_settings().artifact_root).resolve() / artifact.path)
    except Exception:
        return None


def _dataset_id_from_version(dataset_version: str) -> str | None:
    parts = dataset_version.split(":")
    if len(parts) >= 3 and parts[0] == "dvc":
        return parts[1]
    return None


def _strict_mature_tool_mode() -> bool:
    settings = get_settings()
    return settings.app_env.lower() == "production" or not settings.allow_mature_tool_fallback


def _module_available(name: str) -> bool:
    try:
        __import__(name)
        return True
    except Exception:
        return False
