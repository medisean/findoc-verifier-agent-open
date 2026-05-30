from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from statistics import mean
from typing import Any

import pdfplumber
import yaml

from app.agent.evaluator import evaluate_result
from app.agent.structure import materialize_tables, normalize_text, parse_number
from app.agent.verifier import verify_tables
from app.tools.mineru_artifacts import MinerUArtifacts


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = ROOT / "examples" / "benchmark_results" / "standard_table_benchmark_summary.json"
DEFAULT_WORK_DIR = ROOT / "runs" / "standard_benchmark"


@dataclass(frozen=True)
class BenchmarkTask:
    key: str
    label: str
    input_path: Path
    agent_result_path: Path
    start_page: int
    end_page: int
    lang: str = "en"
    group: str = "public_financial_report_slices"


DEFAULT_TASKS = [
    BenchmarkTask(
        key="public-aapl-2024-financials",
        label="Apple 2024 financial statement pages",
        input_path=ROOT / "examples" / "inputs" / "public_benchmark" / "aapl_2024.pdf",
        agent_result_path=ROOT / "runs" / "public-aapl-2024-financials" / "result.json",
        start_page=31,
        end_page=36,
    ),
    BenchmarkTask(
        key="public-wmt-2024-financials",
        label="Walmart 2024 financial statement pages",
        input_path=ROOT / "examples" / "inputs" / "public_benchmark" / "wmt_2024.pdf",
        agent_result_path=ROOT / "runs" / "public-wmt-2024-financials" / "result.json",
        start_page=55,
        end_page=60,
    ),
    BenchmarkTask(
        key="public-nvda-2024-financials",
        label="NVIDIA 2024 financial statement pages",
        input_path=ROOT / "examples" / "inputs" / "public_benchmark" / "nvda_2024.pdf",
        agent_result_path=ROOT / "runs" / "public-nvda-2024-financials" / "result.json",
        start_page=149,
        end_page=154,
    ),
    BenchmarkTask(
        key="public-jpm-2024-financials",
        label="JPMorgan Chase 2024 financial statement pages",
        input_path=ROOT / "examples" / "inputs" / "public_benchmark" / "jpm_2024.pdf",
        agent_result_path=ROOT / "runs" / "public-jpm-2024-financials" / "result.json",
        start_page=205,
        end_page=210,
    ),
]


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run a local table-structure benchmark against traditional, MinerU, and Agent paths."
    )
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--work-dir", type=Path, default=DEFAULT_WORK_DIR)
    parser.add_argument("--clean", action="store_true", help="Remove previous MinerU benchmark artifacts.")
    parser.add_argument(
        "--skip-mineru",
        action="store_true",
        help="Only run pdfplumber and saved Agent results. Useful for quick CI checks.",
    )
    args = parser.parse_args()

    output = args.output.resolve()
    work_dir = args.work_dir.resolve()
    if args.clean and work_dir.exists():
        shutil.rmtree(work_dir)
    work_dir.mkdir(parents=True, exist_ok=True)
    output.parent.mkdir(parents=True, exist_ok=True)

    expectations = load_expectations()
    task_reports = [
        run_task(task, expectations.get(task.key, {}), work_dir, skip_mineru=args.skip_mineru)
        for task in DEFAULT_TASKS
    ]
    payload = {
        "benchmark_name": "standard_table_benchmark_local",
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "task_count": len(task_reports),
        "page_window_total": sum(report["page_count"] for report in task_reports),
        "methods": [
            "pdfplumber_traditional",
            "mineru_pipeline_txt_direct",
            "findoc_agent",
        ],
        "tasks": task_reports,
        "aggregate": aggregate(task_reports),
        "notes": [
            "The benchmark uses local text-layer financial statement page windows to avoid GPU OCR variance.",
            "pdfplumber_traditional is a conventional table-extraction baseline.",
            "mineru_pipeline_txt_direct uses MinerU pipeline txt artifacts and direct normalization.",
            "findoc_agent uses saved FinDoc Agent results with planning, verification, repair, and trace outputs.",
        ],
    }
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"benchmark written: {output}")
    print(json.dumps(payload["aggregate"], ensure_ascii=False, indent=2))


def load_expectations() -> dict[str, Any]:
    path = ROOT / "examples" / "evaluation_expectations.yaml"
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return data.get("tasks", data)


def run_task(
    task: BenchmarkTask,
    expectations: dict[str, Any],
    work_dir: Path,
    *,
    skip_mineru: bool,
) -> dict[str, Any]:
    method_reports: dict[str, Any] = {}
    method_reports["pdfplumber_traditional"] = summarize_result(
        result=pdfplumber_result(task),
        expectations=expectations,
        method="pdfplumber_traditional",
    )
    if skip_mineru:
        method_reports["mineru_pipeline_txt_direct"] = {"status": "skipped"}
    else:
        method_reports["mineru_pipeline_txt_direct"] = summarize_result(
            result=mineru_direct_result(task, work_dir),
            expectations=expectations,
            method="mineru_pipeline_txt_direct",
        )
    method_reports["findoc_agent"] = summarize_result(
        result=load_agent_result(task),
        expectations=expectations,
        method="findoc_agent",
    )
    return {
        "task_key": task.key,
        "label": task.label,
        "group": task.group,
        "input_path": str(task.input_path.relative_to(ROOT)),
        "page_start": task.start_page,
        "page_end": task.end_page,
        "page_count": task.end_page - task.start_page + 1,
        "methods": method_reports,
    }


def pdfplumber_result(task: BenchmarkTask) -> dict[str, Any]:
    started = time.perf_counter()
    tables: list[dict[str, Any]] = []
    with pdfplumber.open(task.input_path) as pdf:
        page_indexes = range(task.start_page, min(task.end_page + 1, len(pdf.pages)))
        for page_index in page_indexes:
            page = pdf.pages[page_index]
            for table_index, raw_table in enumerate(page.extract_tables() or []):
                normalized = normalize_pdfplumber_table(raw_table, page_index, table_index)
                if normalized:
                    tables.append(normalized)
    quality = verify_tables(tables)
    return {
        "task_id": f"{task.key}-pdfplumber",
        "task_name": task.key,
        "status": "succeeded",
        "tables": tables,
        "quality": quality,
        "elapsed_seconds": round(time.perf_counter() - started, 3),
    }


def normalize_pdfplumber_table(
    raw_table: list[list[Any]],
    page_index: int,
    table_index: int,
) -> dict[str, Any] | None:
    rows = [
        [normalize_text(cell) for cell in raw_row]
        for raw_row in raw_table
        if raw_row and any(normalize_text(cell) for cell in raw_row)
    ]
    if len(rows) < 2:
        return None

    header = rows[0]
    periods = [cell or f"col_{idx}" for idx, cell in enumerate(header[1:], start=1)]
    structured_rows = []
    for row_idx, row in enumerate(rows[1:]):
        if len(row) < 2:
            continue
        label = row[0] or f"row_{row_idx}"
        raw_values = row[1:]
        period_keys = list(periods)
        if len(period_keys) < len(raw_values):
            period_keys.extend(f"col_{idx}" for idx in range(len(period_keys), len(raw_values)))
        structured_rows.append(
            {
                "item": label,
                "raw_values": raw_values,
                "values": {
                    period: parse_number(value)
                    for period, value in zip(period_keys, raw_values)
                },
                "row_type": "line",
                "components": [],
                "evidence": {
                    "page": page_index,
                    "bbox": None,
                    "source": "pdfplumber",
                },
            }
        )
    if not structured_rows:
        return None
    return {
        "name": f"pdfplumber_table_p{page_index}_{table_index}",
        "title": f"pdfplumber table page {page_index} #{table_index}",
        "unit": "",
        "table_type": "pdfplumber_table",
        "periods": periods,
        "rows": structured_rows,
        "evidence": {"page_start": page_index, "page_end": page_index, "bbox": None},
        "sources": [{"page_start": page_index, "page_end": page_index}],
        "raw_block": None,
    }


def mineru_direct_result(task: BenchmarkTask, work_dir: Path) -> dict[str, Any]:
    started = time.perf_counter()
    output_dir = work_dir / task.key / "mineru_pipeline_txt"
    content_path = next(output_dir.rglob(f"{task.input_path.stem}_content_list_v2.json"), None) if output_dir.exists() else None
    if content_path is None:
        output_dir.mkdir(parents=True, exist_ok=True)
        command = [
            "uv",
            "run",
            "--extra",
            "mineru",
            "mineru",
            "-p",
            str(task.input_path),
            "-o",
            str(output_dir),
            "-m",
            "txt",
            "-b",
            "pipeline",
            "-l",
            task.lang,
            "-s",
            str(task.start_page),
            "-e",
            str(task.end_page),
        ]
        completed = subprocess.run(
            command,
            cwd=ROOT,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
        if completed.returncode != 0:
            return {
                "task_id": f"{task.key}-mineru-direct",
                "task_name": task.key,
                "status": "failed",
                "tables": [],
                "quality": verify_tables([]),
                "elapsed_seconds": round(time.perf_counter() - started, 3),
                "error": {
                    "returncode": completed.returncode,
                    "stderr_tail": completed.stderr[-4000:],
                    "stdout_tail": completed.stdout[-2000:],
                },
            }

    artifacts = MinerUArtifacts.discover(output_dir, task.input_path.stem)
    blocks = artifacts.load_content_blocks()
    tables = materialize_tables(blocks)
    quality = verify_tables(tables)
    return {
        "task_id": f"{task.key}-mineru-direct",
        "task_name": task.key,
        "status": "succeeded",
        "tables": tables,
        "quality": quality,
        "elapsed_seconds": round(time.perf_counter() - started, 3),
        "artifact_paths": artifacts.existing_paths(),
    }


def load_agent_result(task: BenchmarkTask) -> dict[str, Any]:
    result_path = task.agent_result_path
    if not result_path.exists():
        result_path = ROOT / "examples" / "benchmark_results" / "agent_results" / f"{task.key}.json"
    result = json.loads(result_path.read_text(encoding="utf-8"))
    result.setdefault("elapsed_seconds", None)
    return result


def summarize_result(result: dict[str, Any], expectations: dict[str, Any], method: str) -> dict[str, Any]:
    tables = result.get("tables", [])
    quality = verify_tables(tables)
    diagnostics = quality.get("diagnostics") or {}
    evaluation = evaluate_result(result, expectations) if expectations else {}
    return {
        "method": method,
        "status": result.get("status", "unknown"),
        "table_count": len(tables),
        "row_count": sum(len(table.get("rows", [])) for table in tables),
        "failed_count": quality.get("failed_count", 0),
        "warning_count": quality.get("warning_count", 0),
        "validation_pass_rate": quality.get("validation_pass_rate", 1.0),
        "numeric_parse_coverage": diagnostics.get("numeric_parse_coverage", 1.0),
        "evidence_coverage": diagnostics.get("evidence_coverage", 0.0),
        "financial_table_count": diagnostics.get("financial_table_count", 0),
        "expectation_score": evaluation.get("score"),
        "expectation_status": evaluation.get("status"),
        "expectation_passed_count": evaluation.get("passed_count"),
        "expectation_check_count": evaluation.get("check_count"),
        "elapsed_seconds": result.get("elapsed_seconds"),
        "error": result.get("error"),
    }


def aggregate(task_reports: list[dict[str, Any]]) -> dict[str, Any]:
    methods = ["pdfplumber_traditional", "mineru_pipeline_txt_direct", "findoc_agent"]
    summary: dict[str, Any] = {}
    for method in methods:
        rows = [
            task["methods"][method]
            for task in task_reports
            if task["methods"].get(method, {}).get("status") != "skipped"
        ]
        if not rows:
            summary[method] = {"status": "skipped"}
            continue
        summary[method] = {
            "task_count": len(rows),
            "succeeded_count": sum(1 for row in rows if row.get("status") == "succeeded"),
            "total_tables": sum(int(row.get("table_count", 0)) for row in rows),
            "total_rows": sum(int(row.get("row_count", 0)) for row in rows),
            "total_failed_checks": sum(int(row.get("failed_count", 0)) for row in rows),
            "mean_expectation_score": rounded_mean(row.get("expectation_score") for row in rows),
            "mean_numeric_parse_coverage": rounded_mean(row.get("numeric_parse_coverage") for row in rows),
            "mean_evidence_coverage": rounded_mean(row.get("evidence_coverage") for row in rows),
            "mean_validation_pass_rate": rounded_mean(row.get("validation_pass_rate") for row in rows),
        }
    if is_aggregated(summary.get("findoc_agent")) and is_aggregated(summary.get("pdfplumber_traditional")):
        summary["findoc_vs_pdfplumber_delta"] = delta(summary["findoc_agent"], summary["pdfplumber_traditional"])
    if is_aggregated(summary.get("findoc_agent")) and is_aggregated(summary.get("mineru_pipeline_txt_direct")):
        summary["findoc_vs_mineru_direct_delta"] = delta(summary["findoc_agent"], summary["mineru_pipeline_txt_direct"])
    return summary


def is_aggregated(value: Any) -> bool:
    return isinstance(value, dict) and value.get("status") != "skipped"


def rounded_mean(values: Any) -> float | None:
    filtered = [float(value) for value in values if value is not None]
    if not filtered:
        return None
    return round(mean(filtered), 4)


def delta(left: dict[str, Any], right: dict[str, Any]) -> dict[str, Any]:
    return {
        "tables": left.get("total_tables", 0) - right.get("total_tables", 0),
        "rows": left.get("total_rows", 0) - right.get("total_rows", 0),
        "expectation_score": none_safe_delta(
            left.get("mean_expectation_score"),
            right.get("mean_expectation_score"),
        ),
        "numeric_parse_coverage": none_safe_delta(
            left.get("mean_numeric_parse_coverage"),
            right.get("mean_numeric_parse_coverage"),
        ),
        "evidence_coverage": none_safe_delta(
            left.get("mean_evidence_coverage"),
            right.get("mean_evidence_coverage"),
        ),
    }


def none_safe_delta(left: float | None, right: float | None) -> float | None:
    if left is None or right is None:
        return None
    return round(left - right, 4)


if __name__ == "__main__":
    main()
