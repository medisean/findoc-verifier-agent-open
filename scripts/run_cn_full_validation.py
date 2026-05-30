#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any


TASKS = [
    {
        "name": "cn_byd_2025_annual_report",
        "path": "examples/inputs/public_benchmark_cn/byd_2025_annual_report.pdf",
    },
    {
        "name": "cn_catl_2025_annual_report",
        "path": "examples/inputs/public_benchmark_cn/catl_2025_annual_report.pdf",
    },
    {
        "name": "cn_moutai_2025_annual_report",
        "path": "examples/inputs/public_benchmark_cn/moutai_2025_annual_report.pdf",
    },
    {
        "name": "cn_cmb_2025_annual_report",
        "path": "examples/inputs/public_benchmark_cn/cmb_2025_annual_report.pdf",
    },
]


def main() -> None:
    args = parse_args()
    if args.diagnose_task_id:
        for task_id in args.diagnose_task_id:
            print_failure_diagnostics(task_id, args.runs_dir)
        return

    task_map = load_task_map(args.map_path)
    args.map_path.parent.mkdir(parents=True, exist_ok=True)

    options = build_mineru_options(args)
    print(f"base_url={args.base_url}")
    print(f"map_path={args.map_path}")
    print(f"options={json.dumps(options, ensure_ascii=False)}")

    for task in TASKS:
        name = task["name"]
        pdf_path = Path(task["path"])
        if not pdf_path.exists():
            raise FileNotFoundError(pdf_path)

        existing_task_id = task_map.get(name)
        if existing_task_id and not args.force and result_succeeded(existing_task_id, args.runs_dir):
            print(f"skip succeeded: {name} {existing_task_id}")
            continue

        if existing_task_id and not args.force:
            status = local_result_status(existing_task_id, args.runs_dir)
            if status == "running":
                api_status = get_api_status(args.base_url, existing_task_id)
                if api_status in {"queued", "running"}:
                    print(f"resume polling: {name} {existing_task_id} {api_status}")
                    final_status = poll_until_done(args.base_url, existing_task_id, name, args)
                    if final_status == "succeeded":
                        continue
                    print_failure_diagnostics(existing_task_id, args.runs_dir)
                    if not args.rerun_failed:
                        raise SystemExit(f"task failed: {name} {existing_task_id}")
                elif api_status == "succeeded" and result_succeeded(existing_task_id, args.runs_dir):
                    print(f"skip succeeded: {name} {existing_task_id}")
                    continue

        if existing_task_id and not args.rerun_failed and not args.force:
            print(f"skip existing non-succeeded task: {name} {existing_task_id}")
            continue

        task_id = submit_task(args.base_url, name, pdf_path, options)
        task_map[name] = task_id
        save_task_map(args.map_path, task_map)
        final_status = poll_until_done(args.base_url, task_id, name, args)
        if final_status != "succeeded":
            print_failure_diagnostics(task_id, args.runs_dir)
        if final_status != "succeeded" and not args.continue_on_failure:
            save_summary(args.summary_path, task_map, args.runs_dir)
            raise SystemExit(f"task failed: {name} {task_id}")

    save_summary(args.summary_path, task_map, args.runs_dir)
    print(f"task map saved: {args.map_path}")
    print(f"summary saved: {args.summary_path}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run China annual-report full validation once per document.")
    parser.add_argument("--base-url", default="http://localhost:8000")
    parser.add_argument("--runs-dir", type=Path, default=Path("runs"))
    parser.add_argument(
        "--map-path",
        type=Path,
        default=Path("runs/cn_full_validation_task_map.json"),
    )
    parser.add_argument(
        "--summary-path",
        type=Path,
        default=Path("runs/cn_full_validation_summary.json"),
    )
    parser.add_argument("--backend", default="pipeline")
    parser.add_argument("--method", default="txt")
    parser.add_argument("--lang", default="ch")
    parser.add_argument("--server-url", default=None)
    parser.add_argument("--poll-seconds", type=int, default=30)
    parser.add_argument("--timeout-seconds", type=int, default=0)
    parser.add_argument(
        "--diagnose-task-id",
        action="append",
        default=[],
        help="Print MinerU failure diagnostics for an existing task id and exit.",
    )
    parser.add_argument(
        "--rerun-failed",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Rerun documents whose previous result is missing or failed.",
    )
    parser.add_argument("--force", action="store_true", help="Rerun all documents, including succeeded ones.")
    parser.add_argument(
        "--continue-on-failure",
        action="store_true",
        help="Continue submitting later documents even when one task fails.",
    )
    return parser.parse_args()


def build_mineru_options(args: argparse.Namespace) -> dict[str, Any]:
    options: dict[str, Any] = {
        "backend": args.backend,
        "method": args.method,
        "lang": args.lang,
    }
    if args.server_url:
        options["backend"] = args.backend if args.backend != "pipeline" else "hybrid-http-client"
        options["server_url"] = args.server_url
    return options


def load_task_map(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        return {}
    task_map: dict[str, str] = {}
    for name, value in raw.items():
        if isinstance(value, str):
            task_map[name] = value
        elif isinstance(value, dict) and isinstance(value.get("task_id"), str):
            task_map[name] = value["task_id"]
    return task_map


def save_task_map(path: Path, task_map: dict[str, str]) -> None:
    path.write_text(json.dumps(task_map, ensure_ascii=False, indent=2), encoding="utf-8")


def result_succeeded(task_id: str, runs_dir: Path) -> bool:
    return local_result_status(task_id, runs_dir) == "succeeded"


def local_result_status(task_id: str, runs_dir: Path) -> str | None:
    result_path = runs_dir / task_id / "result.json"
    if not result_path.exists():
        trace_path = runs_dir / task_id / "trace.jsonl"
        return "running" if trace_path.exists() else None
    try:
        result = json.loads(result_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None
    return result.get("status")


def submit_task(base_url: str, name: str, pdf_path: Path, options: dict[str, Any]) -> str:
    print(f"submit: {name} {pdf_path}")
    record = http_json(
        "POST",
        base_url,
        "/v1/tasks",
        {
            "task_name": name,
            "document_type": "annual_report_pdf",
            "inputs": [
                {
                    "path": str(pdf_path),
                    "role": "primary",
                    "mime_type": "application/pdf",
                }
            ],
            "goal": (
                "Extract key financial tables, operating metrics, evidence, "
                "and numeric consistency diagnostics from the full annual report."
            ),
            "options": options,
        },
    )
    task_id = str(record["task_id"])
    print(f"submitted: {name} {task_id}")
    return task_id


def poll_until_done(
    base_url: str,
    task_id: str,
    name: str,
    args: argparse.Namespace,
) -> str:
    started = time.monotonic()
    while True:
        status = get_api_status(base_url, task_id)
        print(f"poll: {name} {task_id} {status}")
        if status in {"succeeded", "failed"}:
            return status
        if args.timeout_seconds and time.monotonic() - started > args.timeout_seconds:
            raise TimeoutError(f"task timed out: {name} {task_id}")
        time.sleep(args.poll_seconds)


def get_api_status(base_url: str, task_id: str) -> str | None:
    try:
        record = http_json("GET", base_url, f"/v1/tasks/{task_id}")
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return None
        raise
    return record.get("status")


def http_json(method: str, base_url: str, path: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    request = urllib.request.Request(
        base_url.rstrip("/") + path,
        data=data,
        method=method,
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=60) as response:
        return json.loads(response.read().decode("utf-8"))


def save_summary(path: Path, task_map: dict[str, str], runs_dir: Path) -> None:
    rows: list[dict[str, Any]] = []
    for name, task_id in task_map.items():
        result_path = runs_dir / task_id / "result.json"
        item: dict[str, Any] = {
            "task_name": name,
            "task_id": task_id,
            "result_path": str(result_path),
            "status": local_result_status(task_id, runs_dir),
        }
        if result_path.exists():
            try:
                result = json.loads(result_path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                result = {}
            quality = result.get("quality", {})
            diagnostics = quality.get("diagnostics", {})
            item.update(
                {
                    "summary": result.get("summary"),
                    "table_count": len(result.get("tables", [])),
                    "failed_count": quality.get("failed_count"),
                    "warning_count": quality.get("warning_count"),
                    "numeric_parse_coverage": diagnostics.get("numeric_parse_coverage"),
                    "evidence_coverage": diagnostics.get("evidence_coverage"),
                    "financial_table_count": diagnostics.get("financial_table_count"),
                }
            )
        rows.append(item)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")


def print_failure_diagnostics(task_id: str, runs_dir: Path) -> None:
    print(f"\n== diagnostics: {task_id} ==")
    result_path = runs_dir / task_id / "result.json"
    trace_path = runs_dir / task_id / "trace.jsonl"

    if result_path.exists():
        try:
            result = json.loads(result_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            result = {}
        print(f"result_status: {result.get('status')}")
        print(f"summary: {result.get('summary')}")

    if not trace_path.exists():
        print(f"missing trace: {trace_path}")
        return

    saw_parse_event = False
    for line in trace_path.read_text(encoding="utf-8").splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if event.get("stage") != "parse_with_mineru":
            continue
        if event.get("event_type") not in {"step_finished", "artifacts_discovered"}:
            continue

        saw_parse_event = True
        outputs = event.get("outputs") or {}
        print(f"event: {event.get('event_type')} status={event.get('status')}")
        if outputs.get("command"):
            print(f"command: {outputs.get('command')}")
        if outputs.get("returncode") is not None:
            print(f"returncode: {outputs.get('returncode')}")
        stderr = outputs.get("stderr") or ""
        stdout = outputs.get("stdout") or ""
        if stderr:
            print("stderr_tail:")
            print(stderr[-4000:])
        if stdout:
            print("stdout_tail:")
            print(stdout[-2000:])

    if not saw_parse_event:
        print("no parse_with_mineru completion event found")


if __name__ == "__main__":
    main()
