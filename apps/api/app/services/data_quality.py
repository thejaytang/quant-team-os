from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

from app.core.config import get_settings

GX_SUPPORTED_EXPECTATIONS = {
    "expect_column_values_to_not_be_null",
    "expect_column_pair_values_A_to_be_greater_than_B",
    "expect_column_values_to_be_between",
    "expect_compound_columns_to_be_unique",
    "expect_column_values_to_be_in_set",
}
GX_EXPECTATION_TYPE_MAP = {
    "expect_column_pair_values_A_to_be_greater_than_B": "expect_column_pair_values_a_to_be_greater_than_b",
}


def _contract_root() -> Path:
    for parent in Path(__file__).resolve().parents:
        candidate = parent / "data_contracts" / "gx"
        if candidate.exists():
            return candidate
    return Path(__file__).resolve().parents[2] / "data_contracts" / "gx"


def list_suites() -> list[dict[str, str]]:
    return [{"name": path.stem, "path": str(path)} for path in sorted(_contract_root().glob("*.json"))]


def validate_suite(suite_name: str, rows: list[dict[str, Any]]) -> dict[str, Any]:
    suite = _load_suite(suite_name)
    strict = _strict_mature_tool_mode()
    gx_result = _run_great_expectations(suite, rows, strict=strict)
    if gx_result is not None:
        return gx_result
    if strict:
        raise RuntimeError("Great Expectations unavailable in strict mode")
    return _run_local_suite(suite, rows, fallback_reason="great_expectations_unavailable")


def _run_local_suite(suite: dict[str, Any], rows: list[dict[str, Any]], fallback_reason: str | None = None) -> dict[str, Any]:
    results = [_run_expectation(item, rows) for item in suite.get("expectations", [])]
    output = {
        "suite": suite["expectation_suite_name"],
        "success": all(item["success"] for item in results),
        "row_count": len(rows),
        "results": results,
        "engine": "local_fallback",
    }
    if fallback_reason:
        output["fallback_reason"] = fallback_reason
    return output


def _load_suite(suite_name: str) -> dict[str, Any]:
    path = _contract_root() / f"{suite_name.removesuffix('.json')}.json"
    if not path.exists():
        raise ValueError(f"unknown data quality suite: {suite_name}")
    return json.loads(path.read_text(encoding="utf-8"))


def _run_great_expectations(suite: dict[str, Any], rows: list[dict[str, Any]], *, strict: bool = False) -> dict[str, Any] | None:
    try:
        import pandas as pd
        from great_expectations.core import ExpectationSuite
        from great_expectations.core.batch import Batch
        from great_expectations.execution_engine import PandasExecutionEngine
        from great_expectations.expectations.expectation_configuration import ExpectationConfiguration
        from great_expectations.validator.validator import Validator
    except Exception as exc:
        if strict:
            raise RuntimeError(f"Great Expectations unavailable in strict mode: {exc}") from exc
        return None

    try:
        gx_expectations = []
        gx_original_types = []
        local_results = []
        for expectation in suite.get("expectations", []):
            kind = expectation["expectation_type"]
            if kind in GX_SUPPORTED_EXPECTATIONS:
                gx_expectations.append(ExpectationConfiguration(type=GX_EXPECTATION_TYPE_MAP.get(kind, kind), kwargs=expectation.get("kwargs", {})))
                gx_original_types.append(kind)
            else:
                local_results.append(_run_expectation(expectation, rows))
        batch = Batch(data=pd.DataFrame(rows))
        validator = Validator(execution_engine=PandasExecutionEngine(), batches=[batch])
        gx_suite = ExpectationSuite(name=suite["expectation_suite_name"], expectations=gx_expectations)
        validation = validator.validate(expectation_suite=gx_suite, result_format="SUMMARY")
        results = [_gx_result_item(item, gx_original_types[idx]) for idx, item in enumerate(validation.results)] + local_results
        engine = "great_expectations_with_local_custom" if local_results else "great_expectations"
        return {
            "suite": suite["expectation_suite_name"],
            "success": all(item["success"] for item in results),
            "row_count": len(rows),
            "results": results,
            "engine": engine,
        }
    except Exception as exc:
        if strict:
            raise RuntimeError(f"Great Expectations validation failed in strict mode: {exc}") from exc
        return _run_local_suite(suite, rows, fallback_reason=f"great_expectations_error:{type(exc).__name__}")


def _gx_result_item(item: Any, expectation_type: str | None = None) -> dict[str, Any]:
    config = getattr(item, "expectation_config", None)
    result = getattr(item, "result", {}) or {}
    kind = expectation_type or getattr(config, "type", None) or getattr(config, "expectation_type", None)
    if kind is None and isinstance(config, dict):
        kind = config.get("type") or config.get("expectation_type")
    return {
        "expectation_type": str(kind or "unknown"),
        "success": bool(getattr(item, "success", False)),
        "unexpected_count": int(result.get("unexpected_count", 0) or 0),
        "unexpected_index_list": list(result.get("unexpected_index_list", []) or [])[:20],
    }


def _run_expectation(expectation: dict[str, Any], rows: list[dict[str, Any]]) -> dict[str, Any]:
    kind = expectation["expectation_type"]
    kwargs = expectation.get("kwargs", {})
    if kind == "expect_column_values_to_not_be_null":
        failures = [idx for idx, row in enumerate(rows) if row.get(kwargs["column"]) in (None, "")]
    elif kind == "expect_column_pair_values_A_to_be_greater_than_B":
        failures = _pair_failures(rows, kwargs["column_A"], kwargs["column_B"], bool(kwargs.get("or_equal")))
    elif kind == "expect_column_values_to_be_between":
        failures = _between_failures(rows, kwargs["column"], kwargs.get("min_value"), kwargs.get("max_value"))
    elif kind == "expect_compound_columns_to_be_unique":
        failures = _duplicate_failures(rows, kwargs["column_list"])
    elif kind == "expect_column_values_to_be_in_set":
        allowed = set(kwargs["value_set"])
        failures = [idx for idx, row in enumerate(rows) if row.get(kwargs["column"]) not in allowed]
    elif kind == "expect_column_values_to_be_finite":
        failures = _finite_failures(rows, kwargs["column"])
    elif kind == "expect_negative_quantity_requires_side":
        failures = _negative_quantity_failures(rows, kwargs["quantity_column"], kwargs["side_column"], set(kwargs["allowed_negative_sides"]))
    elif kind == "expect_column_values_to_be_strictly_increasing_within_group":
        failures = _increasing_failures(rows, kwargs["group_column"], kwargs["sort_column"])
    else:
        failures = list(range(len(rows)))
    return {
        "expectation_type": kind,
        "success": not failures,
        "unexpected_count": len(failures),
        "unexpected_index_list": failures[:20],
    }


def _strict_mature_tool_mode() -> bool:
    settings = get_settings()
    return settings.app_env.lower() == "production" or not settings.allow_mature_tool_fallback


def _pair_failures(rows: list[dict[str, Any]], column_a: str, column_b: str, or_equal: bool) -> list[int]:
    failures: list[int] = []
    for idx, row in enumerate(rows):
        left = _number(row.get(column_a))
        right = _number(row.get(column_b))
        if left is None or right is None or (left < right if or_equal else left <= right):
            failures.append(idx)
    return failures


def _between_failures(rows: list[dict[str, Any]], column: str, min_value: Any, max_value: Any) -> list[int]:
    failures: list[int] = []
    lower = _number(min_value)
    upper = _number(max_value)
    for idx, row in enumerate(rows):
        value = _number(row.get(column))
        if value is None or (lower is not None and value < lower) or (upper is not None and value > upper):
            failures.append(idx)
    return failures


def _finite_failures(rows: list[dict[str, Any]], column: str) -> list[int]:
    failures: list[int] = []
    for idx, row in enumerate(rows):
        value = _number(row.get(column))
        if value is None or not math.isfinite(value):
            failures.append(idx)
    return failures


def _negative_quantity_failures(rows: list[dict[str, Any]], quantity_column: str, side_column: str, allowed_negative_sides: set[str]) -> list[int]:
    failures: list[int] = []
    for idx, row in enumerate(rows):
        quantity = _number(row.get(quantity_column))
        side = str(row.get(side_column) or "").lower()
        if quantity is None or (quantity < 0 and side not in allowed_negative_sides):
            failures.append(idx)
    return failures


def _duplicate_failures(rows: list[dict[str, Any]], columns: list[str]) -> list[int]:
    seen: set[tuple[Any, ...]] = set()
    failures: list[int] = []
    for idx, row in enumerate(rows):
        key = tuple(row.get(column) for column in columns)
        if key in seen:
            failures.append(idx)
        seen.add(key)
    return failures


def _increasing_failures(rows: list[dict[str, Any]], group_column: str, sort_column: str) -> list[int]:
    last_seen: dict[Any, Any] = {}
    failures: list[int] = []
    for idx, row in enumerate(rows):
        group = row.get(group_column)
        value = row.get(sort_column)
        if group in last_seen and value <= last_seen[group]:
            failures.append(idx)
        last_seen[group] = value
    return failures


def _number(value: Any) -> float | None:
    # Non-finite values (NaN/inf) are treated as "not a number" so that range
    # and pairwise checks fail closed instead of silently passing (NaN
    # comparisons always evaluate False).
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    return numeric if math.isfinite(numeric) else None
