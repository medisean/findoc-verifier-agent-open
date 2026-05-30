from __future__ import annotations

import argparse
import json
from pathlib import Path
from statistics import mean
from typing import Any

from app.agent.structure import normalize_text


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_EXPECTATIONS = ROOT / "examples" / "edge_layout_expectations.json"
DEFAULT_OUTPUT = ROOT / "examples" / "benchmark_results" / "edge_layout_summary.json"


def main() -> None:
    parser = argparse.ArgumentParser(description="Run edge-layout fixture benchmark.")
    parser.add_argument("--expectations", type=Path, default=DEFAULT_EXPECTATIONS)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()

    payload = json.loads(args.expectations.read_text(encoding="utf-8"))
    cases = [evaluate_case(case) for case in payload["cases"]]
    report = {
        "benchmark_name": "edge_layout_targeted",
        "status": "pass" if all(case["status"] == "pass" for case in cases) else "fail",
        "case_count": len(cases),
        "passed_count": sum(1 for case in cases if case["status"] == "pass"),
        "aggregate": aggregate(cases),
        "cases": cases,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report["aggregate"], ensure_ascii=False, indent=2))
    print(f"edge layout report written: {args.output}")


def evaluate_case(case: dict[str, Any]) -> dict[str, Any]:
    result = json.loads((ROOT / case["result_path"]).read_text(encoding="utf-8"))
    table = find_table(result, case["expected_table"])
    checks = {
        "table_found": {
            "name": "table_found",
            "status": "pass" if table is not None else "fail",
            "expected": case["expected_table"],
        },
        "required_metrics": check_required_metrics(table, case.get("required_metrics", [])),
        "warning_type": check_warning_type(result, case.get("expected_warning_type")),
        "edge_flags": check_edge_flags(result, case.get("expected_edge_flags", {})),
        "forbidden_rows": check_forbidden_rows(table, case.get("forbidden_row_fragments", [])),
        "expected_periods": check_expected_periods(table, case.get("expected_periods", [])),
    }
    status = "pass" if all(check["status"] == "pass" for check in flatten_checks(checks)) else "fail"
    diagnostics = result.get("quality", {}).get("diagnostics", {})
    edge = diagnostics.get("edge_layout", {})
    return {
        "name": case["name"],
        "status": status,
        "table": {
            "name": table.get("name") if table else None,
            "row_count": len(table.get("rows", [])) if table else 0,
            "periods": table.get("periods", []) if table else [],
            "unit": table.get("unit") if table else None,
        },
        "metrics": {
            "required_metric_accuracy": required_metric_accuracy(checks["required_metrics"]),
            "evidence_coverage": diagnostics.get("evidence_coverage"),
            "numeric_parse_coverage": diagnostics.get("numeric_parse_coverage"),
            "hard_failures": result.get("quality", {}).get("failed_count", 0),
            "warning_count": result.get("quality", {}).get("warning_count", 0),
            "annotation_noise_rejection": bool_to_score(edge.get("annotation_noise_rejected")),
            "reading_order_accuracy": edge.get("reading_order_accuracy"),
            "nested_header_accuracy": edge.get("nested_header_accuracy"),
            "merged_cell_expansion_accuracy": edge.get("merged_cell_expansion_accuracy"),
        },
        "checks": checks,
        "result_path": case["result_path"],
    }


def find_table(result: dict[str, Any], expected_table: str) -> dict[str, Any] | None:
    needle = normalize_text(expected_table).lower()
    for table in result.get("tables", []):
        name = normalize_text(table.get("name")).lower()
        title = normalize_text(table.get("title")).lower()
        if needle in {name, title} or needle in name or needle in title:
            return table
    return None


def check_required_metrics(
    table: dict[str, Any] | None,
    metrics: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    if table is None:
        return [
            {"name": "required_metric", "status": "fail", "detail": metric}
            for metric in metrics
        ]
    rows = {normalize_text(row.get("item")).lower(): row for row in table.get("rows", [])}
    checks = []
    for metric in metrics:
        row = rows.get(normalize_text(metric["row"]).lower())
        observed = None if row is None else row.get("values", {}).get(metric["period"])
        expected = metric["value"]
        passed = observed is not None and abs(float(observed) - float(expected)) <= 1e-6
        checks.append(
            {
                "name": "required_metric",
                "status": "pass" if passed else "fail",
                "row": metric["row"],
                "period": metric["period"],
                "expected": expected,
                "observed": observed,
            }
        )
    return checks


def check_warning_type(result: dict[str, Any], warning_type: str | None) -> dict[str, Any]:
    if not warning_type:
        return {"name": "warning_type", "status": "pass", "expected": None}
    warnings = result.get("quality", {}).get("warnings", [])
    matched = any(warning.get("type") == warning_type for warning in warnings)
    return {
        "name": "warning_type",
        "status": "pass" if matched else "fail",
        "expected": warning_type,
    }


def check_edge_flags(result: dict[str, Any], expected: dict[str, Any]) -> list[dict[str, Any]]:
    edge = result.get("quality", {}).get("diagnostics", {}).get("edge_layout", {})
    checks = []
    for key, expected_value in expected.items():
        observed = edge.get(key)
        checks.append(
            {
                "name": "edge_flag",
                "status": "pass" if observed == expected_value else "fail",
                "flag": key,
                "expected": expected_value,
                "observed": observed,
            }
        )
    return checks


def check_forbidden_rows(
    table: dict[str, Any] | None,
    fragments: list[str],
) -> dict[str, Any]:
    if table is None or not fragments:
        return {"name": "forbidden_rows", "status": "pass", "fragments": fragments}
    labels = [normalize_text(row.get("item")).lower() for row in table.get("rows", [])]
    hits = [
        fragment
        for fragment in fragments
        if any(fragment.lower() in label for label in labels)
    ]
    return {
        "name": "forbidden_rows",
        "status": "pass" if not hits else "fail",
        "fragments": fragments,
        "hits": hits,
    }


def check_expected_periods(table: dict[str, Any] | None, periods: list[str]) -> dict[str, Any]:
    if table is None or not periods:
        return {"name": "expected_periods", "status": "pass", "expected": periods}
    observed = {normalize_text(period).lower() for period in table.get("periods", [])}
    missing = [period for period in periods if normalize_text(period).lower() not in observed]
    return {
        "name": "expected_periods",
        "status": "pass" if not missing else "fail",
        "expected": periods,
        "missing": missing,
    }


def aggregate(cases: list[dict[str, Any]]) -> dict[str, Any]:
    required_checks = [
        check
        for case in cases
        for check in case["checks"]["required_metrics"]
    ]
    return {
        "status": "pass" if all(case["status"] == "pass" for case in cases) else "fail",
        "case_count": len(cases),
        "passed_count": sum(1 for case in cases if case["status"] == "pass"),
        "required_metric_count": len(required_checks),
        "required_metric_passed": sum(1 for check in required_checks if check["status"] == "pass"),
        "required_metric_accuracy": required_metric_accuracy(required_checks),
        "mean_evidence_coverage": average_metric(cases, "evidence_coverage"),
        "mean_numeric_parse_coverage": average_metric(cases, "numeric_parse_coverage"),
        "hard_failures": sum(case["metrics"]["hard_failures"] for case in cases),
        "annotation_noise_rejection": average_metric(cases, "annotation_noise_rejection"),
        "reading_order_accuracy": average_metric(cases, "reading_order_accuracy"),
        "nested_header_accuracy": average_metric(cases, "nested_header_accuracy"),
        "merged_cell_expansion_accuracy": average_metric(cases, "merged_cell_expansion_accuracy"),
    }


def flatten_checks(checks: dict[str, Any]) -> list[dict[str, Any]]:
    flattened = []
    for value in checks.values():
        if isinstance(value, list):
            flattened.extend(value)
        else:
            flattened.append(value)
    return flattened


def required_metric_accuracy(checks: list[dict[str, Any]]) -> float:
    if not checks:
        return 1.0
    return round(sum(1 for check in checks if check["status"] == "pass") / len(checks), 4)


def average_metric(cases: list[dict[str, Any]], metric_name: str) -> float | None:
    values = [
        case["metrics"][metric_name]
        for case in cases
        if case["metrics"].get(metric_name) is not None
    ]
    if not values:
        return None
    return round(mean(float(value) for value in values), 4)


def bool_to_score(value: Any) -> float | None:
    if value is None:
        return None
    return 1.0 if value is True else 0.0


if __name__ == "__main__":
    main()
