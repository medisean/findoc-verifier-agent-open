from __future__ import annotations

import argparse
import json
from pathlib import Path
from statistics import mean
from typing import Any

import yaml

from app.agent.evaluator import evaluate_result
from app.agent.verifier import verify_tables


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_EXPECTATIONS = ROOT / "examples" / "adversarial_expectations.yaml"
DEFAULT_OUTPUT = ROOT / "examples" / "benchmark_results" / "adversarial_summary.json"
TASKS = [
    "adversarial_low_light_scan",
    "adversarial_cross_page_unit",
    "adversarial_dense_numeric_footnotes",
]


def main() -> None:
    parser = argparse.ArgumentParser(description="Summarize adversarial fixture evaluation results.")
    parser.add_argument("--expectations", type=Path, default=DEFAULT_EXPECTATIONS)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()

    expectations = yaml.safe_load(args.expectations.read_text(encoding="utf-8"))["tasks"]
    results = [evaluate_task(task, expectations[task]) for task in TASKS]
    report = {
        "benchmark_name": "adversarial_fixture_evaluation",
        "status": "pass" if all(item["status"] == "pass" for item in results) else "fail",
        "task_count": len(results),
        "passed_count": sum(1 for item in results if item["status"] == "pass"),
        "aggregate": {
            "mean_score": round(mean(item["score"] for item in results), 4),
            "total_tables": sum(item["table_count"] for item in results),
            "total_rows": sum(item["row_count"] for item in results),
            "total_required_metrics": sum(item["required_metric_count"] for item in results),
            "total_required_metric_passed": sum(item["required_metric_passed"] for item in results),
            "hard_failures": sum(item["failed_count"] for item in results),
            "mean_numeric_parse_coverage": round(
                mean(item["numeric_parse_coverage"] for item in results),
                4,
            ),
            "mean_evidence_coverage": round(
                mean(item["evidence_coverage"] for item in results),
                4,
            ),
        },
        "tasks": results,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report["aggregate"], ensure_ascii=False, indent=2))
    print(f"adversarial report written: {args.output}")


def evaluate_task(task: str, expectation: dict[str, Any]) -> dict[str, Any]:
    result_path = ROOT / "examples" / "adversarial_results" / f"{task}.json"
    result = json.loads(result_path.read_text(encoding="utf-8"))
    evaluation = evaluate_result(result, expectation)
    quality = verify_tables(result.get("tables", []))
    diagnostics = quality["diagnostics"]
    required_metric_checks = [
        check for check in evaluation["checks"] if check["name"] == "required_metric"
    ]
    return {
        "task": task,
        "status": evaluation["status"],
        "score": evaluation["score"],
        "passed_count": evaluation["passed_count"],
        "check_count": evaluation["check_count"],
        "required_metric_count": len(required_metric_checks),
        "required_metric_passed": sum(1 for check in required_metric_checks if check["status"] == "pass"),
        "table_count": diagnostics["table_count"],
        "row_count": diagnostics["row_count"],
        "failed_count": quality["failed_count"],
        "warning_count": quality["warning_count"],
        "numeric_parse_coverage": diagnostics["numeric_parse_coverage"],
        "evidence_coverage": diagnostics["evidence_coverage"],
        "result_path": str(result_path.relative_to(ROOT)),
    }


if __name__ == "__main__":
    main()
