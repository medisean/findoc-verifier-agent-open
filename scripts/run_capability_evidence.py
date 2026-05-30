#!/usr/bin/env python3
from __future__ import annotations

import argparse
import asyncio
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.agent.executor import TaskExecutor
from app.agent.repair import repair_numeric_cells
from app.agent.structure import materialize_tables
from app.agent.verifier import verify_tables
from app.schemas.task import TaskCreate


async def main() -> None:
    args = parse_args()
    if args.clean and args.artifact_root.exists():
        shutil.rmtree(args.artifact_root)
    args.artifact_root.mkdir(parents=True, exist_ok=True)

    scenarios = [
        await run_html_native_parse(args.artifact_root),
        await run_mixed_dag_execution(args.artifact_root),
        run_contextual_repair_evidence(),
        run_chart_reference_evidence(args.artifact_root),
    ]
    report = {
        "status": "pass" if all(item["status"] == "pass" for item in scenarios) else "fail",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "artifact_root": str(args.artifact_root),
        "scenario_count": len(scenarios),
        "scenarios": scenarios,
    }
    args.report_path.parent.mkdir(parents=True, exist_ok=True)
    args.report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"capability evidence saved: {args.report_path}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate local Agent capability evidence without GPU/MinerU.")
    parser.add_argument("--artifact-root", type=Path, default=Path("runs/capability_evidence"))
    parser.add_argument("--report-path", type=Path, default=Path("runs/capability_evidence/report.json"))
    parser.add_argument("--clean", action="store_true")
    return parser.parse_args()


async def run_html_native_parse(artifact_root: Path) -> dict[str, Any]:
    class ExplodingMinerUClient:
        async def parse(self, input_path: Path, output_dir: Path, options: dict[str, Any]) -> dict[str, Any]:
            raise AssertionError("HTML evidence scenario must not call MinerU")

    html_path = Path("examples/inputs/html_financial_table.html")
    executor = TaskExecutor(artifact_root)
    executor.mineru_client = ExplodingMinerUClient()
    result = await executor.execute(
        "capability-html-native",
        TaskCreate(
            task_name="capability_html_native",
            document_type="html_financial_table",
            inputs=[{"path": str(html_path), "role": "primary", "mime_type": "text/html"}],
            goal="Parse HTML financial table with native table evidence.",
        ),
    )
    events = read_trace(result.trace_path)
    table = result.tables[0] if result.tables else {}
    return {
        "name": "html_native_parse",
        "status": "pass" if result.status == "succeeded" else "fail",
        "task_id": result.task_id,
        "plan_path": result.plan_path,
        "trace_path": result.trace_path,
        "result_path": result.result_path,
        "native_html_tool_events": sum(1 for event in events if event.get("tool") == "native_html_parser"),
        "table_count": len(result.tables),
        "first_table": {
            "title": table.get("title"),
            "unit": table.get("unit"),
            "periods": table.get("periods"),
            "row_count": len(table.get("rows", [])),
        },
        "quality": result.quality.get("diagnostics", {}),
    }


async def run_mixed_dag_execution(artifact_root: Path) -> dict[str, Any]:
    class FakeMinerUClient:
        async def parse(self, input_path: Path, output_dir: Path, options: dict[str, Any]) -> dict[str, Any]:
            output_dir.mkdir(parents=True, exist_ok=True)
            payload = [
                [
                    {
                        "type": "table",
                        "page_idx": 0,
                        "content": {
                            "title": f"Income Statement {input_path.stem}",
                            "unit": "RMB million",
                            "periods": ["2025"],
                            "rows": [{"label": "Revenue", "values": ["100"], "page_idx": 0}],
                        },
                    }
                ]
            ]
            (output_dir / f"{input_path.stem}_content_list_v2.json").write_text(
                json.dumps(payload),
                encoding="utf-8",
            )
            return {"status": "succeeded", "backend": "fake", "options": options}

    input_dir = artifact_root / "mixed_inputs"
    input_dir.mkdir(parents=True, exist_ok=True)
    primary = input_dir / "annual_report.pdf"
    reference = input_dir / "scanned_financial_statement.pdf"
    attachment = input_dir / "financial_model.xlsx"
    for path in (primary, reference, attachment):
        path.write_text("placeholder", encoding="utf-8")

    executor = TaskExecutor(artifact_root)
    executor.mineru_client = FakeMinerUClient()
    result = await executor.execute(
        "capability-mixed-dag",
        TaskCreate(
            task_name="capability_mixed_dag",
            document_type="mixed_financial_pack",
            inputs=[
                {"path": str(primary), "role": "primary"},
                {"path": str(reference), "role": "reference"},
                {"path": str(attachment), "role": "attachment"},
            ],
            goal="Extract revenue, parse scanned evidence, and reconcile metrics against the XLSX model.",
        ),
    )
    plan = json.loads(Path(result.plan_path or "").read_text(encoding="utf-8"))
    events = read_trace(result.trace_path)
    parse_stages = sorted({event.get("stage") for event in events if str(event.get("stage", "")).startswith("parse_")})
    return {
        "name": "mixed_dag_execution",
        "status": "pass" if result.status == "succeeded" and plan["graph"]["is_dag"] else "fail",
        "task_id": result.task_id,
        "plan_path": result.plan_path,
        "trace_path": result.trace_path,
        "result_path": result.result_path,
        "graph": {
            "step_count": plan["graph"]["step_count"],
            "edge_count": plan["graph"]["edge_count"],
            "is_dag": plan["graph"]["is_dag"],
            "parallel_group_count": len(plan["graph"]["parallel_groups"]),
        },
        "parse_stages": parse_stages,
        "shared_context": result.quality.get("shared_context"),
        "cross_file_checks": result.quality.get("cross_file_checks"),
    }


def run_contextual_repair_evidence() -> dict[str, Any]:
    tables = [
        {
            "name": "income_statement",
            "title": "合并利润表",
            "unit": "人民币百万元",
            "footnote": "除特别注明外，单位为人民币百万元",
            "periods": ["2025", "2024"],
            "rows": [
                {
                    "item": "营业收入",
                    "raw_values": ["1O0百万元", "90"],
                    "values": {"2025": None, "2024": 90.0},
                    "components": [],
                    "evidence": {"page": 12, "bbox": [10, 20, 200, 40]},
                }
            ],
            "evidence": {"page_start": 12, "page_end": 12},
        }
    ]
    repaired_tables, summary = repair_numeric_cells(tables, verify_tables(tables))
    repair = summary["repairs"][0] if summary["repairs"] else {}
    return {
        "name": "contextual_numeric_repair",
        "status": "pass" if summary["applied"] and repair.get("reason") == "contextual_ocr_unit_suffix" else "fail",
        "repair_summary": summary,
        "repaired_value": repaired_tables[0]["rows"][0]["values"]["2025"],
    }


def run_chart_reference_evidence(artifact_root: Path) -> dict[str, Any]:
    blocks_path = Path("examples/inputs/complex_chart_reference_blocks.json")
    blocks = json.loads(blocks_path.read_text(encoding="utf-8"))
    tables = materialize_tables(blocks)
    quality = verify_tables(tables)
    chart_tables = [table for table in tables if table.get("table_type") == "chart_metrics"]
    reference_tables = [
        table for table in tables if table.get("table_type") == "global_reference_resolution"
    ]
    reference_rows = [
        row
        for table in reference_tables
        for row in table.get("rows", [])
        if row.get("row_type") == "global_reference"
    ]
    chart_types = sorted({table.get("chart_type") for table in chart_tables if table.get("chart_type")})
    resolved_kinds = sorted(
        {
            (row.get("evidence") or {}).get("target", {}).get("metric_kind")
            for row in reference_rows
            if (row.get("evidence") or {}).get("target", {}).get("metric_kind")
        }
    )
    min_confidence = min(
        (row.get("values", {}).get("confidence", 0) for row in reference_rows),
        default=0,
    )
    output_path = artifact_root / "chart_reference_tables.json"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps({"tables": tables, "quality": quality}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    passed = (
        len(chart_tables) >= 3
        and len(chart_types) >= 3
        and len(reference_rows) >= 4
        and {"revenue", "growth", "rate", "cash_flow"}.issubset(set(resolved_kinds))
        and min_confidence >= 0.7
        and quality["failed_count"] == 0
    )
    return {
        "name": "chart_reference_resolution",
        "status": "pass" if passed else "fail",
        "fixture_path": str(blocks_path),
        "tables_path": str(output_path),
        "chart_table_count": len(chart_tables),
        "chart_types": chart_types,
        "resolved_reference_count": len(reference_rows),
        "resolved_metric_kinds": resolved_kinds,
        "min_reference_confidence": min_confidence,
        "quality": quality.get("diagnostics", {}),
    }


def read_trace(path: str | None) -> list[dict[str, Any]]:
    if not path:
        return []
    return [
        json.loads(line)
        for line in Path(path).read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


if __name__ == "__main__":
    asyncio.run(main())
