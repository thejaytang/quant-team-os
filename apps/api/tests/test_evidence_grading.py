from datetime import date, timedelta

from app.db.models import Artifact
from app.services.evidence import (
    EVIDENCE_SAMPLE,
    EVIDENCE_UNVERIFIED,
    EVIDENCE_VERIFIED,
    best_grade,
    factor_report_evidence_grade,
    grade_artifact_meta,
)
from app.services.factor_analytics import analyze_factor_rows, compute_strategy_metrics


def _ohlcv_rows(days: int = 30, symbols: tuple[str, ...] = ("AAA", "BBB", "CCC", "DDD")) -> list[dict]:
    rows = []
    start = date(2024, 1, 1)
    for offset in range(days):
        day = start + timedelta(days=offset)
        for rank, symbol in enumerate(symbols):
            drift = 0.001 * (rank + 1)
            wobble = 0.01 if (offset + rank) % 3 == 0 else -0.004
            price = 100 * (1 + drift) ** offset * (1 + wobble)
            rows.append({"symbol": symbol, "date": day.isoformat(), "close": round(price, 4)})
    return rows


def test_grade_artifact_meta_defaults_fail_closed():
    assert grade_artifact_meta(None) == EVIDENCE_UNVERIFIED
    assert grade_artifact_meta({}) == EVIDENCE_UNVERIFIED
    assert grade_artifact_meta({"sample_artifact": True}) == EVIDENCE_SAMPLE
    assert grade_artifact_meta({"evidence_grade": "verified"}) == EVIDENCE_VERIFIED
    assert grade_artifact_meta({"evidence_grade": "bogus"}) == EVIDENCE_UNVERIFIED


def test_best_grade_prefers_verified():
    assert best_grade([]) == EVIDENCE_UNVERIFIED
    assert best_grade([EVIDENCE_SAMPLE, EVIDENCE_VERIFIED]) == EVIDENCE_VERIFIED
    assert best_grade([EVIDENCE_UNVERIFIED, EVIDENCE_SAMPLE]) == EVIDENCE_SAMPLE


def test_factor_report_evidence_grade_reads_artifact_meta(db):
    artifact = Artifact(
        artifact_type="alphalens_factor_tear_sheet",
        owner_type="factor",
        owner_id="factor-1",
        content_type="text/html",
        checksum="abc",
        meta={"sample_artifact": True, "evidence_grade": "sample"},
    )
    db.add(artifact)
    db.flush()

    payload = {"artifacts": [{"artifact_id": artifact.id, "artifact_type": "alphalens_factor_tear_sheet"}]}
    assert factor_report_evidence_grade(db, payload) == EVIDENCE_SAMPLE

    artifact.meta = {**artifact.meta, "evidence_grade": "verified", "sample_artifact": False}
    db.flush()
    assert factor_report_evidence_grade(db, payload) == EVIDENCE_VERIFIED


def test_factor_report_flag_without_artifact_stays_unverified(db):
    assert factor_report_evidence_grade(db, {"factor_report_present": True}) == EVIDENCE_UNVERIFIED


def test_analyze_factor_rows_returns_real_statistics():
    analysis = analyze_factor_rows(_ohlcv_rows())
    assert analysis is not None
    assert analysis["method"] == "pandas_ic_v1"
    assert analysis["observations"] > 0
    assert -1.0 <= analysis["ic"] <= 1.0
    assert analysis["ic_mode"] in {"cross_sectional", "pooled_time_series"}


def test_analyze_factor_rows_rejects_insufficient_rows():
    assert analyze_factor_rows([]) is None
    assert analyze_factor_rows([{"symbol": "AAA", "date": "2024-01-01", "close": 100}]) is None


def test_compute_strategy_metrics_returns_risk_gate_shape():
    metrics = compute_strategy_metrics(_ohlcv_rows(days=60))
    assert metrics is not None
    for key in ("sharpe", "max_drawdown", "turnover_daily", "trade_count"):
        assert key in metrics
    assert metrics["max_drawdown"] >= 0
    assert metrics["trade_count"] > 0
