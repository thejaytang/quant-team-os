from __future__ import annotations

from datetime import date
from typing import Any

from pydantic import BaseModel, Field


class ConnectRequest(BaseModel):
    credentials: dict[str, Any] = Field(default_factory=dict)


class ResearchIdeaCreate(BaseModel):
    title: str
    thesis: str
    universe: str = "US equities"
    asset_class: str = "equity"
    proposed_by: str = "human"
    tags: list[str] = Field(default_factory=list)


class StrategyCreate(BaseModel):
    name: str
    description: str
    universe: str = "US equities"


class BacktestCreate(BaseModel):
    strategy_id: str
    dataset_version: str
    dataset_spec_id: str | None = None
    engine: str = "qlib"
    benchmark: str = "SPY"
    cost_model: dict[str, Any] = Field(default_factory=lambda: {"commission_bps": 1})
    slippage_model: dict[str, Any] = Field(default_factory=lambda: {"bps": 2})


class RiskValidateRequest(BaseModel):
    strategy_id: str | None = None
    backtest_run_id: str | None = None
    metrics: dict[str, Any] = Field(default_factory=dict)
    cost_model: dict[str, Any] | None = None
    slippage_model: dict[str, Any] | None = None
    factor_report_present: bool = False
    start_date: date | None = None
    end_date: date | None = None
    request_type: str = "risk_review"
    evidence_grade: str = "unverified"


class DataQualityValidateRequest(BaseModel):
    rows: list[dict[str, Any]] = Field(default_factory=list)


class ApprovalResolveRequest(BaseModel):
    human_comment: str
    human_actor: str = "local_user"


class AgentRunCreate(BaseModel):
    task_type: str = "research_strategy"
    input_payload: dict[str, Any] = Field(default_factory=dict)
