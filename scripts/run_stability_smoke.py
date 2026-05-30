from __future__ import annotations

import argparse
import asyncio
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path

from app.agent.executor import TaskExecutor
from app.agent.recovery import classify_mineru_failure
from app.schemas.task import TaskCreate, TaskRecord, TaskResult, TaskStatus
from app.task_store import TaskStore


async def main() -> None:
    args = parse_args()
    artifact_root = args.artifact_root
    if args.clean and artifact_root.exists():
        shutil.rmtree(artifact_root)
    artifact_root.mkdir(parents=True, exist_ok=True)

    scenarios = [
        verify_store_reopen(artifact_root / "tasks.sqlite3"),
        await verify_executor_concurrency(artifact_root),
        verify_failure_classification(),
    ]
    report = {
        "status": "pass",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "artifact_root": str(artifact_root),
        "scenario_count": len(scenarios),
        "scenarios": scenarios,
    }
    args.report_path.parent.mkdir(parents=True, exist_ok=True)
    args.report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"stability smoke passed: {artifact_root}")
    print(f"report saved: {args.report_path}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run local stability checks without invoking MinerU.")
    parser.add_argument(
        "--artifact-root",
        type=Path,
        default=Path("runs/stability_smoke"),
        help="Directory for smoke artifacts.",
    )
    parser.add_argument(
        "--report-path",
        type=Path,
        default=Path("runs/stability_smoke/report.json"),
        help="Path for the structured smoke report.",
    )
    parser.add_argument("--clean", action="store_true", help="Remove the artifact directory first.")
    return parser.parse_args()


def verify_store_reopen(store_path: Path) -> dict[str, object]:
    store = TaskStore(store_path)
    request = TaskCreate(
        task_name="stability-store",
        document_type="annual_report_pdf",
        inputs=[{"path": "examples/inputs/__missing_stability_store__.pdf"}],
    )
    record = TaskRecord(task_name=request.task_name, document_type=request.document_type)
    store.create_task(record, request)
    record.status = TaskStatus.running
    store.save_record(record)
    store.save_result(
        TaskResult(
            task_id=record.task_id,
            task_name=record.task_name,
            status=TaskStatus.failed,
            document_type=record.document_type,
            summary="intentional missing-input smoke result",
        )
    )

    reopened = TaskStore(store_path)
    assert reopened.get_record(record.task_id).status == TaskStatus.running
    assert reopened.get_request(record.task_id).task_name == "stability-store"
    assert reopened.get_result(record.task_id).status == TaskStatus.failed
    return {
        "name": "task_store_reopen",
        "status": "pass",
        "task_id": record.task_id,
        "checks": ["record persisted", "request persisted", "result persisted"],
    }


async def verify_executor_concurrency(artifact_root: Path) -> dict[str, object]:
    executor = TaskExecutor(artifact_root)
    tasks = [
        executor.execute(
            f"stability-missing-{idx}",
            TaskCreate(
                task_name=f"stability-missing-{idx}",
                document_type="annual_report_pdf",
                inputs=[{"path": f"examples/inputs/__missing_stability_{idx}.pdf"}],
            ),
        )
        for idx in range(3)
    ]
    results = await asyncio.gather(*tasks)
    for result in results:
        assert result.status == TaskStatus.failed
        assert result.plan_path and Path(result.plan_path).exists()
        assert result.trace_path and Path(result.trace_path).exists()
        assert result.result_path and Path(result.result_path).exists()
    return {
        "name": "concurrent_failure_isolation",
        "status": "pass",
        "task_count": len(results),
        "task_ids": [result.task_id for result in results],
        "checks": ["independent failed results", "plan paths", "trace paths", "result paths"],
    }


def verify_failure_classification() -> dict[str, object]:
    cases = {
        "missing_input": {"status": "missing_input"},
        "model_cache_unavailable": {
            "status": "failed",
            "stderr": "huggingface_hub.errors.LocalEntryNotFoundError: cannot find the appropriate snapshot",
        },
        "model_config_missing": {
            "status": "failed",
            "stderr": "models_download_utils.py local_models_config AttributeError: 'NoneType' object has no attribute 'get'",
        },
        "remote_backend_unavailable": {
            "status": "failed",
            "stderr": "Connection refused while calling remote service",
        },
        "resource_exhausted": {
            "status": "failed",
            "stderr": "CUDA out of memory",
        },
        "timeout": {
            "status": "failed",
            "stderr": "request timed out",
        },
    }
    observed: dict[str, str] = {}
    for expected_category, payload in cases.items():
        failure = classify_mineru_failure(payload)
        observed[expected_category] = str(failure["category"])
        assert failure["category"] == expected_category

    return {
        "name": "failure_classification_matrix",
        "status": "pass",
        "case_count": len(cases),
        "observed": observed,
    }


if __name__ == "__main__":
    asyncio.run(main())
