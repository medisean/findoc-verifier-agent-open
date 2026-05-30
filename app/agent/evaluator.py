from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import yaml

from app.agent.structure import normalize_text
from app.agent.verifier import verify_tables


def evaluate_result(result: dict[str, Any], expectations: dict[str, Any]) -> dict[str, Any]:
    tables = result.get("tables", [])
    quality = verify_tables(tables)
    checks: list[dict[str, Any]] = []

    _add_threshold_check(
        checks,
        name="min_table_count",
        observed=len(tables),
        expected=expectations.get("min_table_count"),
        operator=">=",
    )
    _add_threshold_check(
        checks,
        name="min_row_count",
        observed=sum(len(table.get("rows", [])) for table in tables),
        expected=expectations.get("min_row_count"),
        operator=">=",
    )
    _add_threshold_check(
        checks,
        name="max_failed_count",
        observed=quality.get("failed_count", 0),
        expected=expectations.get("max_failed_count"),
        operator="<=",
    )
    _add_threshold_check(
        checks,
        name="max_warning_count",
        observed=quality.get("warning_count", 0),
        expected=expectations.get("max_warning_count"),
        operator="<=",
    )
    _add_threshold_check(
        checks,
        name="min_validation_pass_rate",
        observed=quality.get("validation_pass_rate", 1.0),
        expected=expectations.get("min_validation_pass_rate"),
        operator=">=",
    )

    for required in expectations.get("required_tables", []):
        matched = any(_contains(table.get("name"), required) or _contains(table.get("title"), required) for table in tables)
        checks.append(
            {
                "name": "required_table",
                "expected": required,
                "status": "pass" if matched else "fail",
                "detail": "Required table was found." if matched else "Required table was not found.",
            }
        )

    for metric in expectations.get("required_metrics", []):
        checks.append(_evaluate_required_metric(tables, metric))

    passed = sum(1 for check in checks if check["status"] == "pass")
    total = len(checks)
    score = round(passed / total, 4) if total else 1.0
    threshold = expectations.get("pass_threshold", 0.8)
    return {
        "task_id": result.get("task_id"),
        "status": "pass" if score >= threshold and passed == total else "fail",
        "score": score,
        "passed_count": passed,
        "check_count": total,
        "checks": checks,
    }


def _add_threshold_check(
    checks: list[dict[str, Any]],
    *,
    name: str,
    observed: int | float,
    expected: int | float | None,
    operator: str,
) -> None:
    if expected is None:
        return
    passed = observed >= expected if operator == ">=" else observed <= expected
    checks.append(
        {
            "name": name,
            "observed": observed,
            "expected": expected,
            "operator": operator,
            "status": "pass" if passed else "fail",
        }
    )


def _evaluate_required_metric(tables: list[dict[str, Any]], metric: dict[str, Any]) -> dict[str, Any]:
    table_token = metric.get("table_contains")
    row_token = metric.get("row_contains")
    period = metric.get("period")
    expected_value = metric.get("expected_value")
    tolerance = float(metric.get("tolerance", 0.0))
    unit_contains = metric.get("unit_contains")
    evidence_required = bool(metric.get("evidence_required", False))

    for table in tables:
        if table_token and not (_contains(table.get("name"), table_token) or _contains(table.get("title"), table_token)):
            continue
        if unit_contains and not _contains(table.get("unit"), unit_contains):
            continue
        for row in table.get("rows", []):
            if row_token and not _contains(row.get("item"), row_token):
                continue
            values = row.get("values", {})
            candidates = [values.get(period)] if period else list(values.values())
            for observed in candidates:
                if observed is None:
                    continue
                if abs(float(observed) - float(expected_value)) <= tolerance:
                    if evidence_required and not _has_metric_evidence(table, row):
                        return {
                            "name": "required_metric",
                            "metric": metric,
                            "observed": observed,
                            "status": "fail",
                            "detail": "Required metric matched but source evidence was missing.",
                        }
                    return {
                        "name": "required_metric",
                        "metric": metric,
                        "observed": observed,
                        "status": "pass",
                        "detail": "Required metric matched within tolerance.",
                    }

    return {
        "name": "required_metric",
        "metric": metric,
        "status": "fail",
        "detail": "Required metric was not found within tolerance.",
    }


def _contains(value: Any, token: str) -> bool:
    return normalize_text(token).lower() in normalize_text(value).lower()


def _has_metric_evidence(table: dict[str, Any], row: dict[str, Any]) -> bool:
    row_evidence = row.get("evidence") or {}
    table_evidence = table.get("evidence") or {}
    return any(
        evidence.get("page") is not None
        or evidence.get("page_start") is not None
        or evidence.get("bbox") is not None
        for evidence in (row_evidence, table_evidence)
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate a FinDoc result against expectations.")
    parser.add_argument("result_json", type=Path)
    parser.add_argument("expectations_yaml", type=Path)
    parser.add_argument(
        "--task-key",
        default=None,
        help="Expectation key override. Defaults to result.task_name, then result.task_id.",
    )
    args = parser.parse_args()

    result = json.loads(args.result_json.read_text(encoding="utf-8"))
    expectations = yaml.safe_load(args.expectations_yaml.read_text(encoding="utf-8")) or {}
    if "tasks" in expectations:
        task_key = args.task_key or result.get("task_name") or result.get("task_id")
        expectations = expectations["tasks"].get(task_key, {})
        if not expectations:
            raise SystemExit(f"No expectations found for task_key={task_key!r}.")
    print(json.dumps(evaluate_result(result, expectations), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
