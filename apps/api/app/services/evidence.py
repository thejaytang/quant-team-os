"""Evidence grading for research artifacts.

Every artifact that feeds the risk gate carries an evidence grade:

- ``verified``: produced by a real computation over concrete input rows.
- ``sample``: produced from placeholder/sample content. Useful for wiring
  tests and demos, but must never satisfy the risk gate in strict mode.
- ``unverified``: claimed by a payload flag without a resolvable artifact.

The grade is stored in ``Artifact.meta["evidence_grade"]`` and surfaced in
``RiskReview.risk_summary`` and approval requests so a human approver always
sees what kind of evidence backs a request.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.db.models import Artifact

EVIDENCE_VERIFIED = "verified"
EVIDENCE_SAMPLE = "sample"
EVIDENCE_UNVERIFIED = "unverified"

_GRADE_RANK = {EVIDENCE_VERIFIED: 2, EVIDENCE_SAMPLE: 1, EVIDENCE_UNVERIFIED: 0}


def grade_artifact_meta(meta: dict[str, Any] | None) -> str:
    meta = meta or {}
    grade = str(meta.get("evidence_grade") or "").strip().lower()
    if grade in _GRADE_RANK:
        return grade
    if meta.get("sample_artifact") is True:
        return EVIDENCE_SAMPLE
    return EVIDENCE_UNVERIFIED


def grade_artifact(artifact: Artifact | None) -> str:
    if artifact is None:
        return EVIDENCE_UNVERIFIED
    return grade_artifact_meta(artifact.meta)


def best_grade(grades: list[str]) -> str:
    if not grades:
        return EVIDENCE_UNVERIFIED
    return max(grades, key=lambda grade: _GRADE_RANK.get(grade, 0))


def factor_report_evidence_grade(db: Session, payload: dict[str, Any]) -> str:
    """Grade the factor-report evidence referenced by a workflow payload.

    Looks up every ``alphalens_factor_tear_sheet`` artifact referenced in
    ``payload["artifacts"]`` and returns the best grade found. A bare
    ``factor_report_present`` flag without a resolvable artifact stays
    ``unverified``.
    """
    grades: list[str] = []
    for item in payload.get("artifacts", []):
        if not isinstance(item, dict):
            continue
        if item.get("artifact_type") != "alphalens_factor_tear_sheet":
            continue
        artifact_id = item.get("artifact_id")
        artifact = db.get(Artifact, str(artifact_id)) if artifact_id else None
        if artifact is not None:
            grades.append(grade_artifact(artifact))
        else:
            grades.append(grade_artifact_meta(item if isinstance(item.get("evidence_grade"), str) else None))
    return best_grade(grades)
