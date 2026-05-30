from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import shutil
import time
from pathlib import Path
from statistics import mean, median
from typing import Any

from app.agent.executor import TaskExecutor
from app.schemas.task import TaskCreate, TaskStatus


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ARTIFACT_ROOT = ROOT / "runs" / "soak_test"
DEFAULT_REPORT = ROOT / "examples" / "benchmark_results" / "soak_test_summary.json"


async def main() -> None:
    args = parse_args()
    if args.clean and args.artifact_root.exists():
        shutil.rmtree(args.artifact_root)
    args.artifact_root.mkdir(parents=True, exist_ok=True)

    executor = TaskExecutor(args.artifact_root)
    started = time.perf_counter()
    semaphore = asyncio.Semaphore(args.concurrency)
    task_reports = await asyncio.gather(
        *[
            run_one(executor, semaphore, idx)
            for idx in range(args.task_count)
        ]
    )
    wall_seconds = round(time.perf_counter() - started, 3)
    report = build_report(task_reports, wall_seconds, args)
    args.report_path.parent.mkdir(parents=True, exist_ok=True)
    args.report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report["aggregate"], ensure_ascii=False, indent=2))
    print(f"soak report written: {args.report_path}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run a local 100-task control-plane soak test.")
    parser.add_argument("--task-count", type=int, default=100)
    parser.add_argument("--concurrency", type=int, default=8)
    parser.add_argument("--artifact-root", type=Path, default=DEFAULT_ARTIFACT_ROOT)
    parser.add_argument("--report-path", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--clean", action="store_true")
    return parser.parse_args()


async def run_one(
    executor: TaskExecutor,
    semaphore: asyncio.Semaphore,
    idx: int,
) -> dict[str, Any]:
    async with semaphore:
        task_id = f"soak-html-{idx:03d}"
        started = time.perf_counter()
        result = await executor.execute(
            task_id,
            TaskCreate(
                task_name=task_id,
                document_type="html_financial_table",
                inputs=[{"path": "examples/inputs/html_financial_table.html"}],
                goal="Extract the HTML financial table with evidence and validation logs.",
            ),
        )
        elapsed = round(time.perf_counter() - started, 4)
        result_path = Path(result.result_path or "")
        trace_path = Path(result.trace_path or "")
        plan_path = Path(result.plan_path or "")
        return {
            "task_id": task_id,
            "status": result.status.value if isinstance(result.status, TaskStatus) else str(result.status),
            "elapsed_seconds": elapsed,
            "table_count": len(result.tables),
            "row_count": sum(len(table.get("rows", [])) for table in result.tables),
            "failed_count": result.quality.get("failed_count", 0),
            "warning_count": result.quality.get("warning_count", 0),
            "numeric_parse_coverage": result.quality.get("diagnostics", {}).get("numeric_parse_coverage"),
            "evidence_coverage": result.quality.get("diagnostics", {}).get("evidence_coverage"),
            "plan_exists": plan_path.exists(),
            "trace_exists": trace_path.exists(),
            "result_exists": result_path.exists(),
            "result_hash": file_hash(result_path) if result_path.exists() else None,
        }


def build_report(
    tasks: list[dict[str, Any]],
    wall_seconds: float,
    args: argparse.Namespace,
) -> dict[str, Any]:
    elapsed = [task["elapsed_seconds"] for task in tasks]
    succeeded = [task for task in tasks if task["status"] == "succeeded"]
    unique_hashes = {task["result_hash"] for task in succeeded if task["result_hash"]}
    output_shapes = {
        (
            task["status"],
            task["table_count"],
            task["row_count"],
            task["failed_count"],
            task["warning_count"],
            task["numeric_parse_coverage"],
            task["evidence_coverage"],
        )
        for task in succeeded
    }
    aggregate = {
        "status": "pass" if len(succeeded) == len(tasks) and all_artifacts_exist(tasks) else "fail",
        "task_count": len(tasks),
        "concurrency": args.concurrency,
        "succeeded_count": len(succeeded),
        "failed_count": len(tasks) - len(succeeded),
        "success_rate": round(len(succeeded) / len(tasks), 4) if tasks else 0.0,
        "wall_seconds": wall_seconds,
        "elapsed_seconds_min": round(min(elapsed), 4) if elapsed else None,
        "elapsed_seconds_p50": round(median(elapsed), 4) if elapsed else None,
        "elapsed_seconds_mean": round(mean(elapsed), 4) if elapsed else None,
        "elapsed_seconds_p95": percentile(elapsed, 0.95),
        "elapsed_seconds_max": round(max(elapsed), 4) if elapsed else None,
        "plan_trace_result_coverage": round(
            sum(1 for task in tasks if task["plan_exists"] and task["trace_exists"] and task["result_exists"])
            / len(tasks),
            4,
        ) if tasks else 0.0,
        "unique_result_hash_count": len(unique_hashes),
        "consistent_output_shape_count": len(output_shapes),
        "output_shape_consistency_rate": 1.0 if len(output_shapes) == 1 and succeeded else 0.0,
        "total_tables": sum(task["table_count"] for task in tasks),
        "total_rows": sum(task["row_count"] for task in tasks),
        "hard_failures": sum(task["failed_count"] for task in tasks),
    }
    return {
        "benchmark_name": "local_control_plane_soak",
        "artifact_root": str(args.artifact_root),
        "aggregate": aggregate,
        "tasks": tasks,
    }


def all_artifacts_exist(tasks: list[dict[str, Any]]) -> bool:
    return all(task["plan_exists"] and task["trace_exists"] and task["result_exists"] for task in tasks)


def percentile(values: list[float], q: float) -> float | None:
    if not values:
        return None
    sorted_values = sorted(values)
    idx = min(int(round((len(sorted_values) - 1) * q)), len(sorted_values) - 1)
    return round(sorted_values[idx], 4)


def file_hash(path: Path) -> str:
    digest = hashlib.sha256()
    digest.update(path.read_bytes())
    return digest.hexdigest()


if __name__ == "__main__":
    asyncio.run(main())
