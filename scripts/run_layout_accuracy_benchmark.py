from __future__ import annotations

import argparse
import json
from pathlib import Path
from statistics import mean
from typing import Any

from app.agent.structure import normalize_text, parse_html_table


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_EXPECTATIONS = ROOT / "examples" / "layout_accuracy_expectations.json"
DEFAULT_OUTPUT = ROOT / "examples" / "benchmark_results" / "layout_accuracy_summary.json"


def main() -> None:
    parser = argparse.ArgumentParser(description="Run targeted layout accuracy checks.")
    parser.add_argument("--expectations", type=Path, default=DEFAULT_EXPECTATIONS)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()

    payload = json.loads(args.expectations.read_text(encoding="utf-8"))
    cases = [evaluate_case(case) for case in payload["cases"]]
    report = {
        "benchmark_name": "layout_accuracy_targeted",
        "case_count": len(cases),
        "status": "pass" if all(case["status"] == "pass" for case in cases) else "fail",
        "aggregate": aggregate(cases),
        "cases": cases,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report["aggregate"], ensure_ascii=False, indent=2))
    print(f"layout accuracy report written: {args.output}")


def evaluate_case(case: dict[str, Any]) -> dict[str, Any]:
    table = load_case_table(case)
    periods = [normalize_text(value) for value in table.get("periods", [])]
    rows = table.get("rows", [])
    row_labels = [normalize_text(row.get("item")) for row in rows]

    expected_periods = [normalize_text(value) for value in case.get("expected_periods", [])]
    expected_rows = [normalize_text(value) for value in case.get("expected_rows", [])]
    expected_values = case.get("expected_values", [])

    period_matches = count_matches(expected_periods, periods)
    row_matches = count_matches(expected_rows, row_labels)
    value_matches = count_value_matches(rows, expected_values)
    page_span_ok = check_page_span(table, case)
    unit_ok = check_unit(table, case)

    metrics = {
        "header_precision": safe_ratio(period_matches, len(periods)) if expected_periods else None,
        "header_recall": safe_ratio(period_matches, len(expected_periods)) if expected_periods else None,
        "row_precision": safe_ratio(row_matches, len(row_labels)) if expected_rows else None,
        "row_recall": safe_ratio(row_matches, len(expected_rows)) if expected_rows else None,
        "numeric_exact_match": safe_ratio(value_matches, len(expected_values)) if expected_values else None,
        "cross_page_merge_accuracy": 1.0 if page_span_ok else 0.0 if has_page_expectation(case) else None,
        "unit_inheritance_accuracy": 1.0 if unit_ok else 0.0 if case.get("expected_unit") else None,
    }
    checks = {
        "expected_periods": {"matched": period_matches, "total": len(expected_periods)},
        "expected_rows": {"matched": row_matches, "total": len(expected_rows)},
        "expected_values": {"matched": value_matches, "total": len(expected_values)},
        "page_span_ok": page_span_ok,
        "unit_ok": unit_ok,
    }
    status = "pass" if all(
        value is None or value >= 1.0 for value in metrics.values()
    ) else "fail"
    return {
        "name": case["name"],
        "type": case["type"],
        "status": status,
        "table": {
            "name": table.get("name"),
            "title": table.get("title"),
            "row_count": len(rows),
            "periods": periods,
            "unit": table.get("unit"),
            "page_start": table.get("evidence", {}).get("page_start"),
            "page_end": table.get("evidence", {}).get("page_end"),
        },
        "metrics": metrics,
        "checks": checks,
    }


def load_case_table(case: dict[str, Any]) -> dict[str, Any]:
    if case["type"] == "html_table":
        html = (ROOT / case["input_path"]).read_text(encoding="utf-8")
        periods, rows = parse_html_table(html, page_idx=0)
        return {
            "name": normalize_text(case.get("expected_title")) or "html_table",
            "title": case.get("expected_title"),
            "unit": "人民币百万元",
            "periods": periods,
            "rows": rows,
            "evidence": {"page_start": 0, "page_end": 0},
        }

    result = json.loads((ROOT / case["result_path"]).read_text(encoding="utf-8"))
    tables = result.get("tables", [])
    expected_table = normalize_text(case.get("expected_table")).lower()
    for table in tables:
        name = normalize_text(table.get("name")).lower()
        title = normalize_text(table.get("title")).lower()
        if expected_table in {name, title} or expected_table in name or expected_table in title:
            return table
    raise ValueError(f"table not found for case={case['name']}")


def count_matches(expected: list[str], observed: list[str]) -> int:
    observed_set = {normalize_text(value).lower() for value in observed}
    return sum(1 for value in expected if normalize_text(value).lower() in observed_set)


def count_value_matches(rows: list[dict[str, Any]], expected_values: list[dict[str, Any]]) -> int:
    row_index = {normalize_text(row.get("item")).lower(): row for row in rows}
    matched = 0
    for expected in expected_values:
        row = row_index.get(normalize_text(expected["row"]).lower())
        if not row:
            continue
        observed = row.get("values", {}).get(expected["period"])
        if observed is None:
            continue
        if abs(float(observed) - float(expected["value"])) <= float(expected.get("tolerance", 0.0)):
            matched += 1
    return matched


def has_page_expectation(case: dict[str, Any]) -> bool:
    return "expected_page_start" in case or "expected_page_end" in case


def check_page_span(table: dict[str, Any], case: dict[str, Any]) -> bool:
    if not has_page_expectation(case):
        return True
    evidence = table.get("evidence", {})
    return (
        evidence.get("page_start") == case.get("expected_page_start")
        and evidence.get("page_end") == case.get("expected_page_end")
    )


def check_unit(table: dict[str, Any], case: dict[str, Any]) -> bool:
    expected = normalize_text(case.get("expected_unit"))
    if not expected:
        return True
    return expected.lower() in normalize_text(table.get("unit")).lower()


def aggregate(cases: list[dict[str, Any]]) -> dict[str, Any]:
    metric_names = [
        "header_precision",
        "header_recall",
        "row_precision",
        "row_recall",
        "numeric_exact_match",
        "cross_page_merge_accuracy",
        "unit_inheritance_accuracy",
    ]
    return {
        "status": "pass" if all(case["status"] == "pass" for case in cases) else "fail",
        "case_count": len(cases),
        "passed_count": sum(1 for case in cases if case["status"] == "pass"),
        **{name: average_metric(cases, name) for name in metric_names},
    }


def average_metric(cases: list[dict[str, Any]], name: str) -> float | None:
    values = [case["metrics"][name] for case in cases if case["metrics"][name] is not None]
    if not values:
        return None
    return round(mean(values), 4)


def safe_ratio(numerator: int, denominator: int) -> float:
    if denominator <= 0:
        return 1.0
    return round(numerator / denominator, 4)


if __name__ == "__main__":
    main()
