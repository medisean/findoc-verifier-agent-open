from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field
from pathlib import Path
from time import perf_counter
from uuid import uuid4
from typing import Any

from bs4 import BeautifulSoup

from app.agent.planner import PlanStep, build_plan, input_plan_slug, plan_graph_summary
from app.agent.profiler import DocumentProfile, build_document_profile, profile_for_input
from app.agent.repair import repair_numeric_cells
from app.agent.recovery import classify_mineru_failure
from app.agent.structure import materialize_tables, normalize_text
from app.agent.verifier import verify_tables
from app.schemas.task import DocumentInput, TaskCreate, TaskResult, TaskStatus
from app.schemas.trace import TraceEvent, TraceStatus
from app.settings import get_settings
from app.tools.mineru_artifacts import MinerUArtifacts
from app.tools.mineru_client import MinerUClient


@dataclass
class ExecutionContext:
    task_id: str
    task: TaskCreate
    artifact_dir: Path
    recorder: "TraceRecorder"
    primary_input: DocumentInput | None = None
    profile: DocumentProfile | None = None
    plan: list[PlanStep] = field(default_factory=list)
    mineru_output_dir: Path | None = None
    mineru_result: dict | None = None
    parse_attempts: list[dict[str, Any]] = field(default_factory=list)
    failure_diagnostics: list[dict[str, Any]] = field(default_factory=list)
    blocks: list[dict] = field(default_factory=list)
    tables: list[dict] = field(default_factory=list)
    quality: dict = field(default_factory=dict)
    repairs: dict = field(default_factory=dict)
    shared_context: dict = field(default_factory=dict)
    cross_file_checks: dict = field(default_factory=dict)
    summary: str = ""
    status: TaskStatus = TaskStatus.succeeded


class TraceRecorder:
    def __init__(self, task_id: str, artifact_dir: Path) -> None:
        self.task_id = task_id
        self.run_id = str(uuid4())
        self.artifact_dir = artifact_dir
        self.trace_path = artifact_dir / "trace.jsonl"

    async def emit(
        self,
        *,
        stage: str,
        event_type: str,
        status: TraceStatus,
        message: str,
        tool: str | None = None,
        duration_ms: int | None = None,
        inputs: dict | None = None,
        outputs: dict | None = None,
        error: dict | None = None,
    ) -> None:
        event = TraceEvent(
            task_id=self.task_id,
            run_id=self.run_id,
            stage=stage,
            event_type=event_type,
            status=status,
            message=message,
            tool=tool,
            duration_ms=duration_ms,
            inputs=inputs or {},
            outputs=outputs or {},
            error=error,
        )
        with self.trace_path.open("a", encoding="utf-8") as file:
            file.write(event.model_dump_json() + "\n")


class TaskExecutor:
    def __init__(self, artifact_root: Path) -> None:
        self.artifact_root = artifact_root
        settings = get_settings()
        self.mineru_client = MinerUClient(endpoint=settings.mineru_endpoint, cli=settings.mineru_cli)
        self.mineru_semaphore = asyncio.Semaphore(max(settings.mineru_max_concurrency, 1))

    async def execute(self, task_id: str, task: TaskCreate) -> TaskResult:
        artifact_dir = self.artifact_root / task_id
        artifact_dir.mkdir(parents=True, exist_ok=True)
        recorder = TraceRecorder(task_id, artifact_dir)
        profile = build_document_profile(task)
        context = ExecutionContext(
            task_id=task_id,
            task=task,
            artifact_dir=artifact_dir,
            recorder=recorder,
            primary_input=self._select_primary_input(task),
            profile=profile,
            plan=build_plan(task, profile),
        )

        try:
            await self._emit_plan(context)
            await self._profile_inputs(context)
            await self._ingest(context)
            await self._parse_with_mineru(context)
            await self._structure_tables(context)
            await self._infer_shared_financial_context(context)
            await self._reconcile_cross_file_metrics(context)
            await self._verify(context)
            await self._recover_low_quality(context)
            await self._repair_low_confidence(context)
            await self._package(context)
        except Exception as exc:  # pragma: no cover - defensive boundary for background jobs
            context.status = TaskStatus.failed
            context.summary = f"Execution failed: {exc}"
            await recorder.emit(
                stage="fatal",
                event_type="task_failed",
                status=TraceStatus.failed,
                message="Task execution failed.",
                error={"type": type(exc).__name__, "message": str(exc)},
            )

        result = TaskResult(
            task_id=task_id,
            task_name=task.task_name,
            status=context.status,
            document_type=task.document_type,
            summary=context.summary or "No summary produced.",
            tables=context.tables,
            quality=context.quality,
            trace_path=str(recorder.trace_path),
            plan_path=str(artifact_dir / "plan.json"),
            result_path=str(artifact_dir / "result.json"),
        )
        (artifact_dir / "result.json").write_text(
            json.dumps(result.model_dump(mode="json"), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return result

    async def _emit_plan(self, context: ExecutionContext) -> None:
        plan_payload = {
            "task_id": context.task_id,
            "task_name": context.task.task_name,
            "document_type": context.task.document_type,
            "goal": context.task.goal,
            "profile": context.profile.to_dict() if context.profile else {},
            "graph": plan_graph_summary(context.plan),
            "steps": [step.__dict__ for step in context.plan],
        }
        (context.artifact_dir / "plan.json").write_text(
            json.dumps(plan_payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        await context.recorder.emit(
            stage="planner",
            event_type="plan_created",
            status=TraceStatus.succeeded,
            message="Execution plan created.",
            outputs=plan_payload,
        )

    async def _profile_inputs(self, context: ExecutionContext) -> None:
        step = self._find_step("profile_inputs", context)
        await context.recorder.emit(
            stage="profile_inputs",
            event_type="step_finished",
            status=TraceStatus.succeeded,
            message=step.objective if step else "Document profile created.",
            tool=step.tool if step else "document_profiler",
            outputs=context.profile.to_dict() if context.profile else {},
        )

    async def _ingest(self, context: ExecutionContext) -> None:
        step = self._find_step("ingest", context)
        started = perf_counter()
        await context.recorder.emit(
            stage="ingest",
            event_type="step_started",
            status=TraceStatus.started,
            message=step.objective if step else "Validate inputs.",
            tool=step.tool if step else "file_loader",
            inputs={"inputs": [item.model_dump() for item in context.task.inputs]},
        )

        if context.primary_input is None:
            context.status = TaskStatus.failed
            context.summary = "No input files were supplied."
            await context.recorder.emit(
                stage="ingest",
                event_type="step_finished",
                status=TraceStatus.failed,
                message="Primary input file is missing.",
                tool=step.tool if step else "file_loader",
                duration_ms=int((perf_counter() - started) * 1000),
            )
            return

        await asyncio.sleep(0)
        await context.recorder.emit(
            stage="ingest",
            event_type="step_finished",
            status=TraceStatus.succeeded,
            message="Primary input selected.",
            tool=step.tool if step else "file_loader",
            duration_ms=int((perf_counter() - started) * 1000),
            outputs={"primary_input": context.primary_input.model_dump()},
        )

    async def _parse_with_mineru(self, context: ExecutionContext) -> None:
        if context.status == TaskStatus.failed:
            return

        step = self._find_step("parse_with_mineru", context)
        context.mineru_output_dir = context.artifact_dir / "mineru"
        parse_inputs = self._select_parse_inputs(context.task)
        if not parse_inputs:
            context.status = TaskStatus.failed
            context.summary = "No local input paths were supplied."
            await context.recorder.emit(
                stage="parse_with_mineru",
                event_type="step_finished",
                status=TraceStatus.failed,
                message="No local input paths were supplied.",
                tool=step.tool if step else "mineru",
                outputs={"inputs": [item.model_dump() for item in context.task.inputs]},
            )
            return

        for input_index, document_input in enumerate(parse_inputs):
            input_path = Path(document_input.path or "")
            step = self._parse_step_for_input(context, input_index, document_input)
            stage_name = step.name if step and step.name.startswith("parse_") else "parse_with_mineru"
            tool_name = step.tool if step else "mineru"
            base_options = self._resolve_mineru_options(context.task, input_path)
            if self._is_html_input(input_path):
                parsed = await self._parse_native_html(
                    context=context,
                    document_input=document_input,
                    input_index=input_index,
                    input_path=input_path,
                    stage_name=stage_name,
                    message=step.objective if step else "Parse HTML tables natively.",
                    tool_name=tool_name,
                )
                if not parsed:
                    context.status = TaskStatus.failed
                    context.summary = "Native HTML parsing failed."
                    return
                continue
            base_options = await self._preflight_route(
                context=context,
                document_input=document_input,
                input_index=input_index,
                input_path=input_path,
                base_options=base_options,
            )
            attempt_options = (
                []
                if self._last_failure_is_terminal(context)
                else self._parse_attempt_options_from_base(base_options, input_path)
            )
            parsed = False
            for attempt_index, mineru_options in enumerate(attempt_options):
                parsed = await self._run_mineru_attempt(
                    context=context,
                    document_input=document_input,
                    input_index=input_index,
                    input_path=input_path,
                    mineru_options=mineru_options,
                    attempt_index=attempt_index,
                    stage_name=stage_name,
                    message=step.objective if step else "Parse the document with MinerU.",
                    tool_name=tool_name,
                )
                if parsed:
                    break
                if self._last_failure_is_terminal(context):
                    break

            if not parsed:
                context.status = TaskStatus.failed
                context.summary = "MinerU parsing failed after recovery attempts."
                return

    async def _parse_native_html(
        self,
        *,
        context: ExecutionContext,
        document_input: DocumentInput,
        input_index: int,
        input_path: Path,
        stage_name: str,
        message: str,
        tool_name: str,
    ) -> bool:
        output_dir = self._attempt_output_dir(context, input_index, input_path, {"backend": "native_html"}, 0)
        started = perf_counter()
        await context.recorder.emit(
            stage=stage_name,
            event_type="step_started",
            status=TraceStatus.started,
            message=message,
            tool=tool_name,
            inputs={
                "input_index": input_index,
                "input_role": document_input.role,
                "input_path": str(input_path),
                "output_dir": str(output_dir),
                "options": {"backend": "native_html", "method": "html_table"},
            },
        )
        if not input_path.exists():
            await context.recorder.emit(
                stage=stage_name,
                event_type="step_finished",
                status=TraceStatus.failed,
                message="HTML input file is missing.",
                tool=tool_name,
                duration_ms=int((perf_counter() - started) * 1000),
                outputs={"status": "missing_input", "input_path": str(input_path)},
            )
            return False

        html = input_path.read_text(encoding="utf-8", errors="ignore")
        blocks = self._html_blocks(html, document_input)
        for block in blocks:
            block.setdefault("source_input", document_input.model_dump())

        output_dir.mkdir(parents=True, exist_ok=True)
        artifact_path = output_dir / f"{input_path.stem}_content_list_v2.json"
        artifact_path.write_text(json.dumps([blocks], ensure_ascii=False, indent=2), encoding="utf-8")
        context.blocks.extend(blocks)
        context.parse_attempts.append(
            {
                "input_index": input_index,
                "input_path": str(input_path),
                "output_dir": str(output_dir),
                "options": {"backend": "native_html", "method": "html_table"},
                "status": "succeeded",
                "failure": None,
            }
        )
        await context.recorder.emit(
            stage=stage_name,
            event_type="step_finished",
            status=TraceStatus.succeeded,
            message="Native HTML parse completed.",
            tool=tool_name,
            duration_ms=int((perf_counter() - started) * 1000),
            outputs={
                "status": "succeeded",
                "input_path": str(input_path),
                "output_dir": str(output_dir),
                "artifact": str(artifact_path),
                "block_count": len(blocks),
            },
        )
        return True

    async def _preflight_route(
        self,
        *,
        context: ExecutionContext,
        document_input: DocumentInput,
        input_index: int,
        input_path: Path,
        base_options: dict[str, Any],
    ) -> dict[str, Any]:
        if not self._should_preflight(context, input_path, base_options):
            return base_options

        original_blocks = list(context.blocks)
        window = context.profile.preflight_page_window if context.profile else None
        preflight_options = dict(base_options)
        preflight_options["start_page"] = int((window or {}).get("start_page", 0))
        preflight_options["end_page"] = int((window or {}).get("end_page", 2))
        preflight_options["recovery_reason"] = "preflight_sample"
        parsed = await self._run_mineru_attempt(
            context=context,
            document_input=document_input,
            input_index=input_index,
            input_path=input_path,
            mineru_options=preflight_options,
            attempt_index=len(context.parse_attempts),
            stage_name="parse_preflight",
            message="Profile a small page window before full extraction.",
        )
        sample_blocks = context.blocks[len(original_blocks):] if parsed else []
        context.blocks = original_blocks
        if not parsed:
            return base_options

        sample_quality = verify_tables(materialize_tables(sample_blocks))
        selected_options = dict(base_options)
        sample_diag = sample_quality.get("diagnostics", {})
        has_sample_tables = sample_diag.get("table_count", 0) > 0
        sample_numeric_risk = float(sample_diag.get("numeric_parse_coverage", 1.0)) < 0.85
        scanned_route = bool(context.profile and (context.profile.scanned_hint or context.profile.has_image))
        if scanned_route or (has_sample_tables and (sample_diag.get("risk_level") == "high" or sample_numeric_risk)):
            selected_options["method"] = "ocr"
            selected_options["planning_reason"] = "preflight_selected_ocr"
        else:
            selected_options["planning_reason"] = "preflight_kept_text"

        await context.recorder.emit(
            stage="parse_preflight",
            event_type="route_selected",
            status=TraceStatus.succeeded,
            message="Preflight sample evaluated and full-parse route selected.",
            tool="adaptive_router",
            outputs={
                "sample_quality": self._quality_summary(sample_quality),
                "selected_options": selected_options,
            },
        )
        return selected_options

    async def _run_mineru_attempt(
        self,
        *,
        context: ExecutionContext,
        document_input: DocumentInput,
        input_index: int,
        input_path: Path,
        mineru_options: dict[str, Any],
        attempt_index: int,
        stage_name: str,
        message: str,
        tool_name: str = "mineru",
    ) -> bool:
        output_dir = self._attempt_output_dir(context, input_index, input_path, mineru_options, attempt_index)
        started = perf_counter()
        await context.recorder.emit(
            stage=stage_name,
            event_type="step_started",
            status=TraceStatus.started,
            message=message,
            tool=tool_name,
            inputs={
                "input_index": input_index,
                "input_role": document_input.role,
                "input_path": str(input_path),
                "output_dir": str(output_dir),
                "attempt_index": attempt_index,
                "options": mineru_options,
            },
        )

        async with self.mineru_semaphore:
            parse_result = await self.mineru_client.parse(
                input_path,
                output_dir,
                mineru_options,
            )
        context.mineru_result = parse_result
        failure = None
        if parse_result.get("status") != "succeeded":
            failure = classify_mineru_failure(parse_result)
            parse_result = dict(parse_result)
            parse_result["failure"] = failure
            context.failure_diagnostics.append(
                {
                    "input_index": input_index,
                    "input_path": str(input_path),
                    "attempt_index": attempt_index,
                    "options": mineru_options,
                    "failure": failure,
                }
            )
        context.parse_attempts.append(
            {
                "input_index": input_index,
                "input_path": str(input_path),
                "output_dir": str(output_dir),
                "options": mineru_options,
                "status": parse_result.get("status"),
                "failure": failure,
            }
        )

        status = TraceStatus.succeeded if parse_result.get("status") == "succeeded" else TraceStatus.failed
        await context.recorder.emit(
            stage=stage_name,
            event_type="step_finished",
            status=status,
            message="MinerU parse completed."
            if status == TraceStatus.succeeded
            else "MinerU parse did not complete successfully; recovery may retry.",
            tool=tool_name,
            duration_ms=int((perf_counter() - started) * 1000),
            outputs=parse_result,
        )
        if status == TraceStatus.failed:
            return False

        artifacts = MinerUArtifacts.discover(output_dir, input_path.stem)
        blocks = artifacts.load_content_blocks()
        for block in blocks:
            block.setdefault("source_input", document_input.model_dump())
        context.blocks.extend(blocks)
        await context.recorder.emit(
            stage=stage_name,
            event_type="artifacts_discovered",
            status=TraceStatus.succeeded,
            message="MinerU artifacts discovered and content blocks loaded.",
            tool=tool_name,
            outputs={
                "input_index": input_index,
                "input_role": document_input.role,
                "artifacts": artifacts.existing_paths(),
                "block_count": len(blocks),
                "total_block_count": len(context.blocks),
            },
        )
        return True

    async def _infer_shared_financial_context(self, context: ExecutionContext) -> None:
        if context.status == TaskStatus.failed:
            return
        step = self._find_step("infer_shared_financial_context", context)
        if step is None:
            return

        started = perf_counter()
        await context.recorder.emit(
            stage=step.name,
            event_type="step_started",
            status=TraceStatus.started,
            message=step.objective,
            tool=step.tool,
            inputs={"table_count": len(context.tables), "block_count": len(context.blocks)},
        )
        context.shared_context = self._build_shared_financial_context(context)
        await context.recorder.emit(
            stage=step.name,
            event_type="step_finished",
            status=TraceStatus.succeeded,
            message="Shared financial context inferred.",
            tool=step.tool,
            duration_ms=int((perf_counter() - started) * 1000),
            outputs=context.shared_context,
        )

    async def _reconcile_cross_file_metrics(self, context: ExecutionContext) -> None:
        if context.status == TaskStatus.failed:
            return
        step = self._find_step("reconcile_cross_file_metrics", context)
        if step is None:
            return

        started = perf_counter()
        await context.recorder.emit(
            stage=step.name,
            event_type="step_started",
            status=TraceStatus.started,
            message=step.objective,
            tool=step.tool,
            inputs={"shared_context": context.shared_context},
        )
        context.cross_file_checks = self._build_cross_file_checks(context.tables)
        await context.recorder.emit(
            stage=step.name,
            event_type="step_finished",
            status=TraceStatus.succeeded,
            message="Cross-file metric reconciliation completed.",
            tool=step.tool,
            duration_ms=int((perf_counter() - started) * 1000),
            outputs=context.cross_file_checks,
        )

    async def _structure_tables(self, context: ExecutionContext) -> None:
        if context.status == TaskStatus.failed:
            return

        step = self._find_step("structure_financial_tables", context)
        started = perf_counter()
        await context.recorder.emit(
            stage="structure_financial_tables",
            event_type="step_started",
            status=TraceStatus.started,
            message=step.objective if step else "Structure financial tables.",
            tool=step.tool if step else "table_structure_builder",
            inputs={"block_count": len(context.blocks)},
        )

        context.tables = materialize_tables(context.blocks)
        await context.recorder.emit(
            stage="structure_financial_tables",
            event_type="step_finished",
            status=TraceStatus.succeeded,
            message="Structured tables materialized.",
            tool=step.tool if step else "table_structure_builder",
            duration_ms=int((perf_counter() - started) * 1000),
            outputs={
                "table_count": len(context.tables),
                "table_names": [table.get("name") for table in context.tables],
            },
        )

    async def _verify(self, context: ExecutionContext) -> None:
        if context.status == TaskStatus.failed:
            return

        step = self._find_step("verify_numbers", context)
        started = perf_counter()
        await context.recorder.emit(
            stage="verify_numbers",
            event_type="step_started",
            status=TraceStatus.started,
            message=step.objective if step else "Verify numeric consistency.",
            tool=step.tool if step else "financial_verifier",
            inputs={"table_count": len(context.tables)},
        )

        context.quality = verify_tables(context.tables)
        self._attach_contextual_quality(context)
        await context.recorder.emit(
            stage="verify_numbers",
            event_type="step_finished",
            status=TraceStatus.succeeded,
            message="Verification completed.",
            tool=step.tool if step else "financial_verifier",
            duration_ms=int((perf_counter() - started) * 1000),
            outputs=context.quality,
        )

    async def _recover_low_quality(self, context: ExecutionContext) -> None:
        if context.status == TaskStatus.failed or not self._should_retry_quality(context.quality):
            return
        step = self._find_step("recover_low_quality", context)

        parse_inputs = self._select_parse_inputs(context.task)
        if len(parse_inputs) != 1:
            await context.recorder.emit(
                stage="recover_low_quality",
                event_type="step_finished",
                status=TraceStatus.succeeded,
                message="Low-quality recovery skipped for multi-input task.",
                tool=step.tool if step else "recovery_policy",
                outputs={"input_count": len(parse_inputs)},
            )
            return

        document_input = parse_inputs[0]
        input_path = Path(document_input.path or "")
        base_options = self._resolve_mineru_options(context.task, input_path)
        recovery_options = self._dedupe_options(
            self._targeted_recovery_options(base_options, input_path, context.quality)
            + self._fallback_mineru_options(base_options, input_path)
        )
        if not recovery_options:
            await context.recorder.emit(
                stage="recover_low_quality",
                event_type="step_finished",
                status=TraceStatus.succeeded,
                message="Low-quality recovery skipped because no fallback backend is available.",
                tool=step.tool if step else "recovery_policy",
                outputs={"quality": context.quality},
            )
            return

        original_blocks = list(context.blocks)
        original_tables = list(context.tables)
        original_quality = dict(context.quality)

        for offset, mineru_options in enumerate(recovery_options, start=len(context.parse_attempts) + 1):
            context.blocks = []
            parsed = await self._run_mineru_attempt(
                context=context,
                document_input=document_input,
                input_index=0,
                input_path=input_path,
                mineru_options=mineru_options,
                attempt_index=offset,
                stage_name="recover_low_quality",
                message="Retry parsing because verification quality was low.",
            )
            if not parsed:
                context.blocks = original_blocks
                continue

            candidate_tables = materialize_tables(context.blocks)
            target_pages = self._option_target_pages(mineru_options)
            if target_pages:
                candidate_tables = self._merge_targeted_tables(
                    original_tables,
                    candidate_tables,
                    target_pages,
                )
            candidate_quality = verify_tables(candidate_tables)
            improved = self._quality_improved(original_quality, candidate_quality)
            await context.recorder.emit(
                stage="recover_low_quality",
                event_type="quality_retry_evaluated",
                status=TraceStatus.succeeded,
                message="Recovery candidate evaluated.",
                tool=step.tool if step else "recovery_policy",
                outputs={
                    "accepted": improved,
                    "target_pages": sorted(target_pages),
                    "old_quality": self._quality_summary(original_quality),
                    "new_quality": self._quality_summary(candidate_quality),
                    "options": mineru_options,
                },
            )
            if improved:
                context.tables = candidate_tables
                context.quality = candidate_quality
                if target_pages:
                    context.blocks = original_blocks + context.blocks
                return

            context.blocks = original_blocks
            context.tables = original_tables
            context.quality = original_quality

    async def _repair_low_confidence(self, context: ExecutionContext) -> None:
        if context.status == TaskStatus.failed:
            return

        step = self._find_step("repair_low_confidence", context)
        started = perf_counter()
        await context.recorder.emit(
            stage="repair_low_confidence",
            event_type="step_started",
            status=TraceStatus.started,
            message=step.objective if step else "Repair low-confidence numeric cells.",
            tool=step.tool if step else "numeric_repair",
            inputs={
                "warning_count": context.quality.get("warning_count", 0),
                "risk_level": context.quality.get("diagnostics", {}).get("risk_level"),
                "recommended_actions": context.quality.get("diagnostics", {}).get(
                    "recommended_actions",
                    [],
                ),
            },
        )

        repaired_tables, repair_summary = repair_numeric_cells(context.tables, context.quality)
        context.repairs = repair_summary
        if repair_summary["applied"]:
            context.tables = repaired_tables
            context.quality = verify_tables(context.tables)
            self._attach_contextual_quality(context)

        context.quality["repairs"] = repair_summary
        await context.recorder.emit(
            stage="repair_low_confidence",
            event_type="step_finished",
            status=TraceStatus.succeeded,
            message="Numeric repair applied."
            if repair_summary["applied"]
            else "No numeric repair was needed.",
            tool=step.tool if step else "numeric_repair",
            duration_ms=int((perf_counter() - started) * 1000),
            outputs={
                "repair_summary": repair_summary,
                "post_repair_quality": context.quality,
            },
        )

    async def _package(self, context: ExecutionContext) -> None:
        if context.status == TaskStatus.failed:
            return

        step = self._find_step("package_result", context)
        started = perf_counter()
        total_rows = sum(len(table.get("rows", [])) for table in context.tables)
        validation_pass_rate = context.quality.get("validation_pass_rate", 1.0)
        warning_count = context.quality.get("warning_count", 0)
        failed_count = context.quality.get("failed_count", 0)
        repair_count = context.quality.get("repairs", {}).get("repair_count", 0)
        context.summary = (
            f"Parsed {len(context.tables)} tables with {total_rows} rows. "
            f"Validation pass rate: {validation_pass_rate:.2%}. "
            f"Warnings: {warning_count}; failures: {failed_count}; "
            f"repairs: {repair_count}."
        )
        await context.recorder.emit(
            stage="package_result",
            event_type="step_started",
            status=TraceStatus.started,
            message=step.objective if step else "Package the result.",
            tool=step.tool if step else "result_packager",
            inputs={"table_count": len(context.tables)},
        )
        await context.recorder.emit(
            stage="package_result",
            event_type="step_finished",
            status=TraceStatus.succeeded,
            message="Result packaging completed.",
            tool=step.tool if step else "result_packager",
            duration_ms=int((perf_counter() - started) * 1000),
            outputs={"summary": context.summary},
        )

    def _select_primary_input(self, task: TaskCreate) -> DocumentInput | None:
        if not task.inputs:
            return None
        for item in task.inputs:
            if item.role == "primary":
                return item
        return task.inputs[0]

    def _select_parse_inputs(self, task: TaskCreate) -> list[DocumentInput]:
        return [item for item in task.inputs if item.path]

    def _parse_step_for_input(
        self,
        context: ExecutionContext,
        input_index: int,
        document_input: DocumentInput,
    ) -> PlanStep | None:
        if context.profile is None:
            return self._find_step("parse_with_mineru", context)
        original_index = input_index
        for candidate_index, signal in enumerate(context.profile.inputs):
            if signal.path == document_input.path and signal.role == document_input.role:
                original_index = candidate_index
                break
        signal = context.profile.inputs[original_index]
        step_name = f"parse_{input_plan_slug(original_index, signal)}"
        return self._find_step(step_name, context) or self._find_step("parse_with_mineru", context)

    def _resolve_mineru_options(self, task: TaskCreate, input_path: Path) -> dict[str, Any]:
        options = dict(task.options)
        suffix = input_path.suffix.lower()
        document_type = task.document_type.lower()
        input_name = input_path.name.lower()
        input_profile = profile_for_input(task, input_path)

        if self._is_html_input(input_path):
            options.setdefault("backend", "native_html")
            options.setdefault("method", "html_table")
        elif suffix == ".pdf" or suffix in {".png", ".jpg", ".jpeg", ".tif", ".tiff"}:
            options.setdefault("backend", "pipeline")
            if input_profile.image_like or input_profile.scanned_hint or "scanned" in document_type or "scan" in input_name:
                options.setdefault("method", "ocr")
            else:
                options.setdefault("method", "txt")

        return options

    def _is_html_input(self, input_path: Path) -> bool:
        return input_path.suffix.lower() in {".html", ".htm"}

    def _parse_attempt_options(self, task: TaskCreate, input_path: Path) -> list[dict[str, Any]]:
        base_options = self._resolve_mineru_options(task, input_path)
        return self._parse_attempt_options_from_base(base_options, input_path)

    def _parse_attempt_options_from_base(
        self,
        base_options: dict[str, Any],
        input_path: Path,
    ) -> list[dict[str, Any]]:
        attempts = [base_options]
        if base_options.get("auto_recovery", True) is False:
            return attempts
        attempts.extend(self._fallback_mineru_options(base_options, input_path))
        return self._dedupe_options(attempts)

    def _should_preflight(
        self,
        context: ExecutionContext,
        input_path: Path,
        base_options: dict[str, Any],
    ) -> bool:
        if base_options.get("preflight", True) is False:
            return False
        if base_options.get("start_page") is not None or base_options.get("end_page") is not None:
            return False
        if input_path.suffix.lower() != ".pdf":
            return False
        profile = context.profile
        if profile is None or not profile.large_document_hint:
            return False
        return str(base_options.get("method") or "").lower() == "txt"

    def _fallback_mineru_options(self, base_options: dict[str, Any], input_path: Path) -> list[dict[str, Any]]:
        suffix = input_path.suffix.lower()
        if suffix not in {".pdf", ".png", ".jpg", ".jpeg", ".tif", ".tiff"}:
            return []

        fallbacks: list[dict[str, Any]] = []
        backend = str(base_options.get("backend") or "").lower()
        method = str(base_options.get("method") or "").lower()
        remote_backend = backend in {"vlm-http-client", "hybrid-http-client"}

        if backend in {"", "pipeline"} and method != "ocr":
            retry = dict(base_options)
            retry["backend"] = "pipeline"
            retry["method"] = "ocr"
            retry["recovery_reason"] = "retry_with_ocr"
            fallbacks.append(retry)

        server_url = base_options.get("server_url") or get_settings().mineru_endpoint
        if server_url and not remote_backend:
            retry = dict(base_options)
            retry["backend"] = "hybrid-http-client"
            retry["server_url"] = server_url
            retry["recovery_reason"] = "retry_with_remote_hybrid"
            fallbacks.append(retry)

        if remote_backend:
            retry = dict(base_options)
            retry["backend"] = "pipeline"
            retry.setdefault("method", "ocr" if method == "ocr" else "txt")
            retry.pop("server_url", None)
            retry["recovery_reason"] = "retry_with_local_pipeline"
            fallbacks.append(retry)

        return self._dedupe_options(fallbacks)

    def _targeted_recovery_options(
        self,
        base_options: dict[str, Any],
        input_path: Path,
        quality: dict[str, Any],
    ) -> list[dict[str, Any]]:
        if input_path.suffix.lower() != ".pdf":
            return []
        if base_options.get("auto_recovery", True) is False:
            return []
        pages = self._attention_pages(quality)
        if not pages:
            return []

        start_page = min(pages)
        end_page = max(pages)
        if end_page - start_page > 12:
            return []

        retry = dict(base_options)
        retry["backend"] = "pipeline"
        retry["method"] = "ocr"
        retry["start_page"] = start_page
        retry["end_page"] = end_page
        retry["target_pages"] = sorted(pages)
        retry["recovery_reason"] = "retry_affected_pages_with_ocr"
        return [retry]

    def _attempt_output_dir(
        self,
        context: ExecutionContext,
        input_index: int,
        input_path: Path,
        mineru_options: dict[str, Any],
        attempt_index: int,
    ) -> Path:
        if context.mineru_output_dir is None:
            context.mineru_output_dir = context.artifact_dir / "mineru"
        base_name = f"{input_index}_{input_path.stem or 'input'}"
        reason_value = mineru_options.get("recovery_reason")
        if attempt_index == 0 and not reason_value:
            return context.mineru_output_dir / base_name
        reason = str(reason_value or f"attempt_{attempt_index}")
        safe_reason = "".join(char if char.isalnum() or char in {"_", "-"} else "_" for char in reason)
        return context.mineru_output_dir / f"{base_name}_{safe_reason}"

    def _should_retry_quality(self, quality: dict[str, Any]) -> bool:
        diagnostics = quality.get("diagnostics", {})
        return (
            quality.get("failed_count", 0) > 0
            or diagnostics.get("risk_level") == "high"
            or diagnostics.get("table_count", 0) == 0
            or diagnostics.get("numeric_parse_coverage", 1.0) < 0.85
            or diagnostics.get("evidence_coverage", 1.0) < 0.8
        )

    def _last_failure_is_terminal(self, context: ExecutionContext) -> bool:
        if not context.parse_attempts:
            return False
        failure = context.parse_attempts[-1].get("failure") or {}
        return bool(failure.get("terminal"))

    def _attention_pages(self, quality: dict[str, Any]) -> set[int]:
        diagnostics = quality.get("diagnostics", {})
        pages: set[int] = set()
        failed_tables = {
            str(check.get("table"))
            for check in quality.get("checks", [])
            if check.get("status") == "fail" and check.get("table")
        }
        for item in diagnostics.get("tables", []):
            table_name = str(item.get("name"))
            low_numeric = float(item.get("numeric_parse_coverage", 1.0)) < 0.95
            low_evidence = float(item.get("evidence_coverage", 1.0)) < 0.9
            if table_name not in failed_tables and not low_numeric and not low_evidence:
                continue
            pages.update(self._page_range(item.get("page_start"), item.get("page_end")))
        return pages

    def _option_target_pages(self, options: dict[str, Any]) -> set[int]:
        values = options.get("target_pages") or []
        pages: set[int] = set()
        if isinstance(values, list):
            for value in values:
                try:
                    pages.add(int(value))
                except (TypeError, ValueError):
                    continue
        return pages

    def _merge_targeted_tables(
        self,
        original_tables: list[dict[str, Any]],
        candidate_tables: list[dict[str, Any]],
        target_pages: set[int],
    ) -> list[dict[str, Any]]:
        if not candidate_tables:
            return list(original_tables)
        kept = [
            table
            for table in original_tables
            if not self._table_overlaps_pages(table, target_pages)
        ]
        return kept + candidate_tables

    def _table_overlaps_pages(self, table: dict[str, Any], target_pages: set[int]) -> bool:
        evidence = table.get("evidence") or {}
        pages = self._page_range(evidence.get("page_start"), evidence.get("page_end"))
        if not pages:
            row_pages = {
                row.get("evidence", {}).get("page")
                for row in table.get("rows", [])
                if row.get("evidence", {}).get("page") is not None
            }
            pages = {int(page) for page in row_pages if isinstance(page, int)}
        return bool(pages & target_pages)

    def _page_range(self, start: Any, end: Any) -> set[int]:
        if start is None and end is None:
            return set()
        try:
            start_int = int(start if start is not None else end)
            end_int = int(end if end is not None else start)
        except (TypeError, ValueError):
            return set()
        if end_int < start_int:
            start_int, end_int = end_int, start_int
        if end_int - start_int > 20:
            return {start_int, end_int}
        return set(range(start_int, end_int + 1))

    def _quality_improved(self, old_quality: dict[str, Any], new_quality: dict[str, Any]) -> bool:
        old_diag = old_quality.get("diagnostics", {})
        new_diag = new_quality.get("diagnostics", {})
        old_risk = self._risk_rank(old_diag.get("risk_level"))
        new_risk = self._risk_rank(new_diag.get("risk_level"))
        if new_quality.get("failed_count", 0) < old_quality.get("failed_count", 0):
            return True
        if new_risk < old_risk:
            return True
        if old_diag.get("table_count", 0) == 0 and new_diag.get("table_count", 0) > 0:
            return True
        old_numeric = float(old_diag.get("numeric_parse_coverage", 1.0))
        new_numeric = float(new_diag.get("numeric_parse_coverage", 1.0))
        old_evidence = float(old_diag.get("evidence_coverage", 1.0))
        new_evidence = float(new_diag.get("evidence_coverage", 1.0))
        return new_numeric >= old_numeric + 0.03 and new_evidence >= old_evidence

    def _quality_summary(self, quality: dict[str, Any]) -> dict[str, Any]:
        diagnostics = quality.get("diagnostics", {})
        return {
            "failed_count": quality.get("failed_count"),
            "warning_count": quality.get("warning_count"),
            "risk_level": diagnostics.get("risk_level"),
            "table_count": diagnostics.get("table_count"),
            "numeric_parse_coverage": diagnostics.get("numeric_parse_coverage"),
            "evidence_coverage": diagnostics.get("evidence_coverage"),
        }

    def _build_shared_financial_context(self, context: ExecutionContext) -> dict[str, Any]:
        roles: dict[str, int] = {}
        units: set[str] = set()
        periods: set[str] = set()
        metric_aliases: set[str] = set()

        for block in context.blocks:
            role = self._source_role_from_block(block)
            roles[role] = roles.get(role, 0) + 1
        for table in context.tables:
            unit = normalize_text(table.get("unit"))
            if unit:
                units.add(unit)
            for period in table.get("periods", []):
                period_text = normalize_text(period)
                if period_text:
                    periods.add(period_text)
            for row in table.get("rows", []):
                label = normalize_text(row.get("item"))
                if label:
                    metric_aliases.add(label.lower())
                for period in row.get("values", {}).keys():
                    period_text = normalize_text(period)
                    if period_text:
                        periods.add(period_text)

        return {
            "source_roles": roles,
            "units": sorted(units)[:20],
            "periods": sorted(periods)[:20],
            "metric_alias_count": len(metric_aliases),
            "metric_alias_examples": sorted(metric_aliases)[:20],
        }

    def _build_cross_file_checks(self, tables: list[dict[str, Any]]) -> dict[str, Any]:
        grouped: dict[tuple[str, str], list[dict[str, Any]]] = {}
        for table in tables:
            role = self._source_role_from_table(table)
            for row in table.get("rows", []):
                metric = normalize_text(row.get("item")).lower()
                if not metric:
                    continue
                for period, value in row.get("values", {}).items():
                    if value is None:
                        continue
                    try:
                        numeric_value = float(value)
                    except (TypeError, ValueError):
                        continue
                    grouped.setdefault((metric, normalize_text(period)), []).append(
                        {
                            "value": numeric_value,
                            "role": role,
                            "table": table.get("name"),
                            "evidence": row.get("evidence") or table.get("evidence") or {},
                        }
                    )

        matched = 0
        conflicts: list[dict[str, Any]] = []
        for (metric, period), records in grouped.items():
            roles = {record["role"] for record in records}
            if len(records) < 2 or len(roles) < 2:
                continue
            values = [record["value"] for record in records]
            tolerance = max(1.0, max(abs(value) for value in values) * 0.01)
            if max(values) - min(values) <= tolerance:
                matched += 1
                continue
            conflicts.append(
                {
                    "metric": metric,
                    "period": period,
                    "values": records[:5],
                    "delta": round(max(values) - min(values), 6),
                }
            )

        return {
            "matched_metric_count": matched,
            "conflict_count": len(conflicts),
            "conflicts": conflicts[:20],
            "truncated": len(conflicts) > 20,
        }

    def _attach_contextual_quality(self, context: ExecutionContext) -> None:
        if context.shared_context:
            context.quality["shared_context"] = context.shared_context
        if context.cross_file_checks:
            context.quality["cross_file_checks"] = context.cross_file_checks

    def _source_role_from_table(self, table: dict[str, Any]) -> str:
        raw_block = table.get("raw_block") or {}
        if isinstance(raw_block, dict):
            return self._source_role_from_block(raw_block)
        return "unknown"

    def _source_role_from_block(self, block: dict[str, Any]) -> str:
        source_input = block.get("source_input") or {}
        if isinstance(source_input, dict):
            return normalize_text(source_input.get("role")) or "unknown"
        return "unknown"

    def _html_blocks(self, html: str, document_input: DocumentInput) -> list[dict[str, Any]]:
        soup = BeautifulSoup(html, "html.parser")
        document_unit = self._extract_html_unit(soup.get_text(" ", strip=True))
        document_title = normalize_text(soup.title.string if soup.title and soup.title.string else "")
        blocks: list[dict[str, Any]] = []
        for index, table in enumerate(soup.find_all("table")):
            caption_tag = table.find("caption")
            caption = normalize_text(caption_tag.get_text(" ", strip=True) if caption_tag else "")
            table_unit = self._extract_html_unit(table.get_text(" ", strip=True)) or document_unit
            content: dict[str, Any] = {
                "table_caption": caption or document_title or f"HTML table {index + 1}",
                "html": str(table),
                "table_type": "html_table",
                "table_nest_level": 0,
            }
            if table_unit:
                content["unit"] = table_unit
                content["table_footnote"] = table_unit
            blocks.append(
                {
                    "type": "table",
                    "page_idx": index,
                    "bbox": None,
                    "content": content,
                    "source_input": document_input.model_dump(),
                }
            )
        return blocks

    def _extract_html_unit(self, text: str) -> str:
        normalized = normalize_text(text)
        for marker in ("单位：", "单位:", "Unit:", "Unit："):
            if marker not in normalized:
                continue
            tail = normalized.split(marker, 1)[1]
            return normalize_text(tail.split()[0].strip(" ,，;；。"))
        return ""

    def _risk_rank(self, risk_level: Any) -> int:
        return {"low": 0, "medium": 1, "high": 2}.get(str(risk_level), 1)

    def _dedupe_options(self, options: list[dict[str, Any]]) -> list[dict[str, Any]]:
        seen: set[tuple[tuple[str, str], ...]] = set()
        deduped: list[dict[str, Any]] = []
        for item in options:
            key = tuple(sorted((key, str(value)) for key, value in item.items()))
            if key in seen:
                continue
            seen.add(key)
            deduped.append(item)
        return deduped

    def _find_step(self, name: str, context: ExecutionContext) -> PlanStep | None:
        for step in context.plan:
            if step.name == name:
                return step
        return None
