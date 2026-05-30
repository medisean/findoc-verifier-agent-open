from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from app.agent.profiler import DocumentProfile, InputSignal, build_document_profile
from app.schemas.task import TaskCreate


@dataclass(frozen=True)
class PlanStep:
    name: str
    tool: str
    objective: str
    depends_on: list[str] = field(default_factory=list)
    success_criteria: list[str] = field(default_factory=list)
    on_failure: list[str] = field(default_factory=list)
    decision: dict[str, str] = field(default_factory=dict)


def build_plan(task: TaskCreate, profile: DocumentProfile | None = None) -> list[PlanStep]:
    profile = profile or build_document_profile(task)
    if _should_build_mixed_document_plan(task, profile):
        return _build_mixed_document_plan(task, profile)

    pre_parse_steps: list[PlanStep] = []
    if profile.has_office or task.document_type in {"office_attachment_pack", "ppt_xlsx_attachment_pack"}:
        pre_parse_steps.append(
            PlanStep(
                name="expand_office_attachments",
                tool="office_unpacker",
                objective="Split PPT/XLSX attachments into parseable document units.",
                depends_on=["ingest"],
                success_criteria=["Each local attachment is represented as a parse input."],
            )
        )

    if profile.scanned_hint or profile.has_image:
        pre_parse_steps.append(
            PlanStep(
                name="assess_scan_quality",
                tool="image_quality_checker",
                objective="Detect blur, skew, lighting issues, and route to robust OCR settings.",
                depends_on=["ingest"],
                success_criteria=["Scan-risk signals are reflected in MinerU OCR settings."],
            )
        )

    parse_depends_on = [step.name for step in pre_parse_steps] or ["ingest"]
    parse_tool = "native_html_parser" if profile.has_html and not profile.has_pdf and not profile.has_image else "mineru"
    steps = [
        PlanStep(
            name="profile_inputs",
            tool="document_profiler",
            objective="Build document signals for routing, cost control, and recovery choices.",
            success_criteria=["Input type, size, scan hints, and route are recorded."],
            on_failure=["Continue with conservative PDF/text defaults when profiling is incomplete."],
            decision={"parse_strategy": profile.parse_strategy},
        ),
        PlanStep(
            name="ingest",
            tool="file_loader",
            objective="Validate input files and prepare a task workspace.",
            depends_on=["profile_inputs"],
            success_criteria=["At least one primary or local parseable input is available."],
        ),
        *pre_parse_steps,
        PlanStep(
            name="parse_with_mineru",
            tool=parse_tool,
            objective=(
                "Parse the document into Markdown, content list, middle JSON, and evidence assets "
                f"using {profile.parse_strategy}."
            ),
            depends_on=parse_depends_on,
            success_criteria=["MinerU artifacts are discovered and content blocks are loaded."],
            on_failure=["Classify failure and retry with the next recovery backend/method if recoverable."],
            decision={
                "backend": profile.recommended_backend,
                "method": profile.recommended_method or "",
            },
        ),
        PlanStep(
            name="structure_financial_tables",
            tool="table_structure_builder",
            objective="Normalize table headers, units, periods, row labels, and cross-page continuations.",
            depends_on=["parse_with_mineru"],
            success_criteria=["Tables follow the stable financial table schema."],
        ),
        PlanStep(
            name="verify_numbers",
            tool="financial_verifier",
            objective="Run sum checks, period checks, unit checks, and anomaly detection.",
            depends_on=["structure_financial_tables"],
            success_criteria=["Quality diagnostics and numeric coverage metrics are produced."],
            on_failure=["Route low-quality outputs into targeted recovery before final packaging."],
        ),
        PlanStep(
            name="recover_low_quality",
            tool="recovery_policy",
            objective="Replan failed or low-quality parsing with affected-page, OCR, or remote fallback attempts.",
            depends_on=["verify_numbers"],
            success_criteria=["A recovery candidate is accepted only when diagnostics improve."],
            on_failure=["Keep the best known candidate and continue with deterministic repair where possible."],
        ),
        PlanStep(
            name="repair_low_confidence",
            tool="numeric_repair",
            objective="Repair low-confidence numeric cells and rerun validation when possible.",
            depends_on=["recover_low_quality"],
            success_criteria=["Only deterministic numeric repairs are applied and reverified."],
        ),
        PlanStep(
            name="package_result",
            tool="result_packager",
            objective="Write result JSON and trace logs for reproducible evaluation.",
            depends_on=["repair_low_confidence"],
        ),
    ]

    return steps


def plan_graph_summary(steps: list[PlanStep]) -> dict[str, Any]:
    edges = [
        {"from": dependency, "to": step.name}
        for step in steps
        for dependency in step.depends_on
    ]
    indegree = {step.name: 0 for step in steps}
    children: dict[str, list[str]] = {step.name: [] for step in steps}
    for edge in edges:
        if edge["to"] in indegree:
            indegree[edge["to"]] += 1
        children.setdefault(edge["from"], []).append(edge["to"])

    remaining = dict(indegree)
    frontier = sorted(name for name, degree in remaining.items() if degree == 0)
    levels: list[list[str]] = []
    visited: set[str] = set()
    while frontier:
        levels.append(frontier)
        next_frontier: list[str] = []
        for name in frontier:
            visited.add(name)
            for child in children.get(name, []):
                if child not in remaining:
                    continue
                remaining[child] -= 1
                if remaining[child] == 0:
                    next_frontier.append(child)
        frontier = sorted(next_frontier)

    return {
        "step_count": len(steps),
        "edge_count": len(edges),
        "edges": edges,
        "parallel_groups": levels,
        "is_dag": len(visited) == len(steps),
    }


def _should_build_mixed_document_plan(task: TaskCreate, profile: DocumentProfile) -> bool:
    if profile.local_input_count < 2:
        return False
    roles = {item.role for item in profile.inputs}
    goal = f"{task.task_name} {task.document_type} {task.goal}".lower()
    cross_file_goal = any(token in goal for token in ("核对", "核验", "reconcile", "compare", "cross-file", "附件"))
    mixed_modalities = (
        sum(bool(value) for value in (profile.has_pdf, profile.has_image, profile.has_office, profile.has_html)) >= 2
    )
    return "attachment" in roles or "reference" in roles or cross_file_goal or mixed_modalities


def _build_mixed_document_plan(task: TaskCreate, profile: DocumentProfile) -> list[PlanStep]:
    steps: list[PlanStep] = [
        PlanStep(
            name="profile_inputs",
            tool="document_profiler",
            objective="Build per-input signals and identify cross-document dependencies before parsing.",
            success_criteria=[
                "Every local input has modality, role, scan, language, and size signals.",
                "The plan records which inputs can be parsed in parallel.",
            ],
            on_failure=["Continue with conservative routing for each local input."],
            decision={
                "parse_strategy": "mixed_document_dag",
                "input_count": str(profile.input_count),
                "local_input_count": str(profile.local_input_count),
            },
        ),
        PlanStep(
            name="ingest",
            tool="file_loader",
            objective="Validate the document pack and prepare a shared task workspace.",
            depends_on=["profile_inputs"],
            success_criteria=[
                "Primary document and local attachments are available.",
                "Missing optional references are logged without blocking primary extraction.",
            ],
        ),
    ]

    structure_steps: list[str] = []
    for input_index, signal in enumerate(profile.inputs):
        if not signal.path:
            steps.append(
                PlanStep(
                    name=f"record_remote_reference_{input_index:02d}",
                    tool="reference_registry",
                    objective="Record remote reference metadata for later evidence linking.",
                    depends_on=["ingest"],
                    success_criteria=["Remote reference URL is preserved in the plan."],
                    decision={"url": signal.url or "", "role": signal.role},
                )
            )
            continue

        slug = input_plan_slug(input_index, signal)
        classify_name = f"classify_{slug}"
        prep_dependencies = [classify_name]
        steps.append(
            PlanStep(
                name=classify_name,
                tool="input_profiler",
                objective=f"Classify {signal.role} input {signal.path} and choose a parsing route.",
                depends_on=["ingest"],
                success_criteria=[
                    "Input-specific backend and method decisions are explicit.",
                    "Scan, Office, and large-PDF risks are reflected in downstream parsing.",
                ],
                decision=_input_decision(signal),
            )
        )

        if signal.office_like:
            office_name = f"expand_{slug}"
            steps.append(
                PlanStep(
                    name=office_name,
                    tool="office_unpacker",
                    objective="Expand Office input into parseable slide, sheet, table, and text units.",
                    depends_on=[classify_name],
                    success_criteria=["Office content units are available for parsing and cross-file joins."],
                )
            )
            prep_dependencies.append(office_name)

        if signal.scanned_hint or signal.image_like:
            scan_name = f"assess_scan_{slug}"
            steps.append(
                PlanStep(
                    name=scan_name,
                    tool="image_quality_checker",
                    objective="Detect blur, skew, lighting, and OCR risk before parsing this input.",
                    depends_on=[classify_name],
                    success_criteria=["Scan-risk signals are converted into OCR settings."],
                )
            )
            prep_dependencies.append(scan_name)

        parse_name = f"parse_{slug}"
        structure_name = f"structure_{slug}"
        steps.append(
            PlanStep(
                name=parse_name,
                tool=_parse_tool(signal),
                objective=f"Parse {signal.role} input into content blocks with page and source evidence.",
                depends_on=prep_dependencies,
                success_criteria=[
                    "Content blocks preserve source input role and page/sheet evidence.",
                    "Parsing can run in parallel with other independent inputs.",
                ],
                on_failure=["Classify the failure and retry the affected input only when recoverable."],
                decision=_parse_decision(signal),
            )
        )
        steps.append(
            PlanStep(
                name=structure_name,
                tool="table_structure_builder",
                objective="Normalize this input's tables, units, periods, row labels, and evidence.",
                depends_on=[parse_name],
                success_criteria=["Structured rows are keyed by input, table, period, and metric aliases."],
            )
        )
        structure_steps.append(structure_name)

    context_name = "infer_shared_financial_context"
    steps.extend(
        [
            PlanStep(
                name=context_name,
                tool="context_inferencer",
                objective=(
                    "Infer document-level units, period aliases, metric aliases, and evidence joins "
                    "across the mixed input pack."
                ),
                depends_on=structure_steps,
                success_criteria=[
                    "Shared context records unit inheritance and period normalization rules.",
                    "Context can be reused by numeric repair and cross-file checks.",
                ],
            ),
            PlanStep(
                name="reconcile_cross_file_metrics",
                tool="cross_document_reconciler",
                objective=(
                    "Compare primary PDF metrics with scanned audit evidence and XLSX/PPT attachment "
                    "values using shared metric aliases."
                ),
                depends_on=[context_name],
                success_criteria=[
                    "Repeated metrics are either matched, explained as rounding differences, or flagged.",
                    "Conflicts include source evidence for both sides.",
                ],
                on_failure=["Keep per-input results and emit unresolved cross-file discrepancies."],
                decision={
                    "join_keys": "metric_alias, period, unit, source_role",
                    "conflict_policy": "hard_fail_for_material_numeric_mismatch",
                },
            ),
            PlanStep(
                name="verify_numbers",
                tool="financial_verifier",
                objective="Run numeric, period, unit, evidence, and cross-file consistency checks.",
                depends_on=["reconcile_cross_file_metrics"],
                success_criteria=["Quality diagnostics and coverage metrics are produced."],
                on_failure=["Route low-quality outputs into targeted recovery before final packaging."],
            ),
            PlanStep(
                name="recover_low_quality",
                tool="recovery_policy",
                objective="Retry only affected inputs or page windows when diagnostics show recoverable risk.",
                depends_on=["verify_numbers"],
                success_criteria=["A recovery candidate is accepted only when diagnostics improve."],
                on_failure=["Keep the best known candidate and continue with contextual repair where possible."],
            ),
            PlanStep(
                name="repair_low_confidence",
                tool="contextual_numeric_repair",
                objective=(
                    "Repair OCR-confused or unit-suffixed numeric cells using table unit, period, "
                    "row label, footnote, and peer-value context before revalidation."
                ),
                depends_on=["recover_low_quality"],
                success_criteria=[
                    "Each repair records original value, repaired value, context evidence, and confidence.",
                    "Repaired results are reverified before packaging.",
                ],
            ),
            PlanStep(
                name="package_result",
                tool="result_packager",
                objective="Write result JSON, plan DAG, and trace logs for reproducible evaluation.",
                depends_on=["repair_low_confidence"],
                success_criteria=["Result package includes per-input outputs, cross-file checks, and trace paths."],
            ),
        ]
    )
    return steps


def input_plan_slug(input_index: int, signal: InputSignal) -> str:
    raw = Path(signal.path or signal.url or f"input_{input_index}").stem.lower()
    safe = "".join(char if char.isalnum() else "_" for char in raw).strip("_")
    safe = "_".join(part for part in safe.split("_") if part)
    return f"input_{input_index:02d}_{safe or signal.role}"


def _input_decision(signal: InputSignal) -> dict[str, str]:
    return {
        "role": signal.role,
        "suffix": signal.suffix,
        "exists": str(signal.exists).lower(),
        "scanned_hint": str(signal.scanned_hint).lower(),
        "office_like": str(signal.office_like).lower(),
        "html_like": str(signal.html_like).lower(),
        "pdf_like": str(signal.pdf_like).lower(),
    }


def _parse_tool(signal: InputSignal) -> str:
    if signal.office_like and not signal.pdf_like:
        return "native_office_or_mineru"
    if signal.html_like:
        return "native_html_parser"
    if signal.image_like or signal.scanned_hint:
        return "mineru_ocr"
    return "mineru"


def _parse_decision(signal: InputSignal) -> dict[str, str]:
    if signal.image_like or signal.scanned_hint:
        method = "ocr"
    elif signal.pdf_like:
        method = "txt"
    elif signal.html_like:
        method = "html_table"
    else:
        method = ""
    backend = "pipeline" if signal.pdf_like or signal.image_like else "native_html" if signal.html_like else "native_or_mineru"
    return {"backend": backend, "method": method, "role": signal.role}
