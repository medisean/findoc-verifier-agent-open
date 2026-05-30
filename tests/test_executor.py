import json
from pathlib import Path

from app.agent.executor import TaskExecutor
from app.agent.planner import build_plan, plan_graph_summary
from app.agent.profiler import build_document_profile
from app.agent.recovery import classify_mineru_failure
from app.schemas.task import TaskCreate


def test_resolve_mineru_options_for_pdf_types() -> None:
    executor = TaskExecutor(Path("runs"))

    annual_report = TaskCreate(
        task_name="annual",
        document_type="annual_report_pdf",
        inputs=[{"path": "examples/inputs/annual_report.pdf"}],
    )
    scanned_report = TaskCreate(
        task_name="scanned",
        document_type="scanned_financial_statement_pdf",
        inputs=[{"path": "examples/inputs/scanned_financial_statement.pdf"}],
    )
    office_report = TaskCreate(
        task_name="office",
        document_type="docx_management_report",
        inputs=[{"path": "examples/inputs/management_report.docx"}],
    )

    assert executor._resolve_mineru_options(annual_report, Path("examples/inputs/annual_report.pdf")) == {
        "backend": "pipeline",
        "method": "txt",
    }
    assert executor._resolve_mineru_options(
        scanned_report,
        Path("examples/inputs/scanned_financial_statement.pdf"),
    ) == {
        "backend": "pipeline",
        "method": "ocr",
    }
    assert executor._resolve_mineru_options(
        office_report,
        Path("examples/inputs/management_report.docx"),
    ) == {}


def test_document_profile_selects_dynamic_strategy() -> None:
    task = TaskCreate(
        task_name="cn_byd_annual_report",
        document_type="annual_report_pdf",
        inputs=[{"path": "examples/inputs/public_benchmark_cn/byd_2025_annual_report.pdf"}],
    )

    profile = build_document_profile(task)

    assert profile.parse_strategy == "sample_then_full_text"
    assert profile.recommended_method == "txt"
    assert profile.preflight_page_window == {"start_page": 0, "end_page": 2}


def test_document_profile_selects_native_html_strategy() -> None:
    task = TaskCreate(
        task_name="html_financial_table",
        document_type="html_financial_table",
        inputs=[{"path": "examples/inputs/html_financial_table.html", "mime_type": "text/html"}],
    )

    profile = build_document_profile(task)
    steps = build_plan(task, profile)

    assert profile.has_html is True
    assert profile.parse_strategy == "native_html_table_parse"
    assert profile.recommended_backend == "native_html"
    assert profile.recommended_method == "html_table"
    assert any(step.tool == "native_html_parser" for step in steps)


def test_resolve_mineru_options_preserves_explicit_overrides() -> None:
    executor = TaskExecutor(Path("runs"))
    task = TaskCreate(
        task_name="custom",
        document_type="annual_report_pdf",
        inputs=[{"path": "examples/inputs/annual_report.pdf"}],
        options={
            "backend": "hybrid-http-client",
            "method": "ocr",
            "server_url": "http://localhost:30000",
        },
    )

    assert executor._resolve_mineru_options(task, Path("examples/inputs/annual_report.pdf")) == {
        "backend": "hybrid-http-client",
        "method": "ocr",
        "server_url": "http://localhost:30000",
    }


def test_parse_attempt_options_adds_ocr_recovery_for_text_pdf() -> None:
    executor = TaskExecutor(Path("runs"))
    task = TaskCreate(
        task_name="annual",
        document_type="annual_report_pdf",
        inputs=[{"path": "examples/inputs/annual_report.pdf"}],
    )

    attempts = executor._parse_attempt_options(task, Path("examples/inputs/annual_report.pdf"))

    assert attempts[0] == {"backend": "pipeline", "method": "txt"}
    assert attempts[1]["backend"] == "pipeline"
    assert attempts[1]["method"] == "ocr"
    assert attempts[1]["recovery_reason"] == "retry_with_ocr"


def test_missing_input_failure_is_terminal() -> None:
    failure = classify_mineru_failure({"status": "missing_input"})

    assert failure["category"] == "missing_input"
    assert failure["terminal"] is True
    assert failure["recoverable"] is False


def test_quality_retry_policy_targets_high_risk_results() -> None:
    executor = TaskExecutor(Path("runs"))

    assert executor._should_retry_quality(
        {"failed_count": 0, "diagnostics": {"risk_level": "high", "numeric_parse_coverage": 0.99}}
    )
    assert not executor._should_retry_quality(
        {
            "failed_count": 0,
            "diagnostics": {
                "risk_level": "medium",
                "table_count": 200,
                "numeric_parse_coverage": 0.96,
                "evidence_coverage": 1.0,
            },
        }
    )


def test_quality_improvement_prefers_lower_failed_count() -> None:
    executor = TaskExecutor(Path("runs"))

    assert executor._quality_improved(
        {"failed_count": 1, "diagnostics": {"risk_level": "high", "table_count": 1}},
        {"failed_count": 0, "diagnostics": {"risk_level": "medium", "table_count": 1}},
    )


def test_targeted_recovery_options_use_affected_pages() -> None:
    executor = TaskExecutor(Path("runs"))
    quality = {
        "checks": [{"status": "fail", "table": "cash_flow"}],
        "diagnostics": {
            "tables": [
                {
                    "name": "cash_flow",
                    "page_start": 8,
                    "page_end": 9,
                    "numeric_parse_coverage": 0.8,
                    "evidence_coverage": 1.0,
                }
            ]
        },
    }

    options = executor._targeted_recovery_options(
        {"backend": "pipeline", "method": "txt"},
        Path("annual_report.pdf"),
        quality,
    )

    assert options == [
        {
            "backend": "pipeline",
            "method": "ocr",
            "start_page": 8,
            "end_page": 9,
            "target_pages": [8, 9],
            "recovery_reason": "retry_affected_pages_with_ocr",
        }
    ]


def test_select_parse_inputs_includes_local_attachments() -> None:
    executor = TaskExecutor(Path("runs"))
    task = TaskCreate(
        task_name="attachment-pack",
        document_type="ppt_xlsx_attachment_pack",
        inputs=[
            {"path": "examples/inputs/investor_deck.pptx", "role": "primary"},
            {"path": "examples/inputs/financial_model.xlsx", "role": "attachment"},
            {"url": "https://example.test/reference.pdf", "role": "reference"},
        ],
    )

    parse_inputs = executor._select_parse_inputs(task)

    assert [item.role for item in parse_inputs] == ["primary", "attachment"]
    assert [item.path for item in parse_inputs] == [
        "examples/inputs/investor_deck.pptx",
        "examples/inputs/financial_model.xlsx",
    ]


def test_plan_includes_repair_before_packaging() -> None:
    task = TaskCreate(
        task_name="annual",
        document_type="annual_report_pdf",
        inputs=[{"path": "examples/inputs/annual_report.pdf"}],
    )

    step_names = [step.name for step in build_plan(task)]

    assert "repair_low_confidence" in step_names
    assert step_names.index("verify_numbers") < step_names.index("repair_low_confidence")
    assert step_names.index("repair_low_confidence") < step_names.index("package_result")


def test_mixed_document_plan_builds_dynamic_dag() -> None:
    task = TaskCreate(
        task_name="mixed_financial_verification_pack",
        document_type="mixed_financial_pack",
        inputs=[
            {"path": "examples/inputs/annual_report.pdf", "role": "primary"},
            {
                "path": "examples/inputs/scanned_financial_statement.pdf",
                "role": "reference",
            },
            {"path": "examples/inputs/financial_model.xlsx", "role": "attachment"},
        ],
        goal=(
            "Extract revenue and operating income from the PDF, parse scanned audit evidence, "
            "then reconcile repeated metrics against the XLSX model."
        ),
    )

    steps = build_plan(task)
    step_names = [step.name for step in steps]
    graph = plan_graph_summary(steps)

    assert graph["is_dag"] is True
    assert graph["step_count"] >= 14
    assert "infer_shared_financial_context" in step_names
    assert "reconcile_cross_file_metrics" in step_names
    assert step_names.index("reconcile_cross_file_metrics") < step_names.index("verify_numbers")
    assert any(name.startswith("parse_input_00") for name in step_names)
    assert any(name.startswith("parse_input_01") for name in step_names)
    assert any(name.startswith("parse_input_02") for name in step_names)
    assert any(len(group) >= 2 for group in graph["parallel_groups"])


async def test_executor_writes_plan_for_failed_task(tmp_path: Path) -> None:
    executor = TaskExecutor(tmp_path)
    task = TaskCreate(
        task_name="missing",
        document_type="annual_report_pdf",
        inputs=[{"path": "examples/inputs/__missing_plan_fixture__.pdf"}],
    )

    result = await executor.execute("missing-task", task)

    assert result.status == "failed"
    assert result.plan_path is not None
    plan_path = Path(result.plan_path)
    assert plan_path.exists()
    assert '"profile"' in plan_path.read_text(encoding="utf-8")


async def test_mixed_executor_trace_follows_dynamic_plan(tmp_path: Path) -> None:
    class FakeMinerUClient:
        async def parse(self, input_path: Path, output_dir: Path, options: dict) -> dict:
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
                            "rows": [
                                {
                                    "label": "Revenue",
                                    "values": ["100"],
                                    "page_idx": 0,
                                }
                            ],
                        },
                    }
                ]
            ]
            (output_dir / f"{input_path.stem}_content_list_v2.json").write_text(
                json.dumps(payload),
                encoding="utf-8",
            )
            return {"status": "succeeded", "backend": "fake", "options": options}

    primary = tmp_path / "annual_report.pdf"
    reference = tmp_path / "scanned_financial_statement.pdf"
    attachment = tmp_path / "financial_model.xlsx"
    for path in (primary, reference, attachment):
        path.write_text("placeholder", encoding="utf-8")

    executor = TaskExecutor(tmp_path)
    executor.mineru_client = FakeMinerUClient()
    task = TaskCreate(
        task_name="mixed_financial_verification_pack",
        document_type="mixed_financial_pack",
        inputs=[
            {"path": str(primary), "role": "primary"},
            {"path": str(reference), "role": "reference"},
            {"path": str(attachment), "role": "attachment"},
        ],
        goal="Extract revenue, parse scanned evidence, and reconcile metrics against the XLSX model.",
    )

    result = await executor.execute("mixed-task", task)
    events = [
        json.loads(line)
        for line in Path(result.trace_path or "").read_text(encoding="utf-8").splitlines()
    ]
    stages = {event["stage"] for event in events}

    assert result.status == "succeeded"
    assert any(stage.startswith("parse_input_00") for stage in stages)
    assert any(stage.startswith("parse_input_01") for stage in stages)
    assert any(stage.startswith("parse_input_02") for stage in stages)
    assert "infer_shared_financial_context" in stages
    assert "reconcile_cross_file_metrics" in stages
    assert result.quality["shared_context"]["source_roles"] == {
        "primary": 1,
        "reference": 1,
        "attachment": 1,
    }
    assert result.quality["cross_file_checks"]["matched_metric_count"] >= 1
    assert result.quality["cross_file_checks"]["conflict_count"] == 0


async def test_executor_parses_html_without_mineru(tmp_path: Path) -> None:
    class ExplodingMinerUClient:
        async def parse(self, input_path: Path, output_dir: Path, options: dict) -> dict:
            raise AssertionError("HTML should use the native parser, not MinerU")

    html_path = tmp_path / "financial.html"
    html_path.write_text(
        """
        <!doctype html>
        <html>
          <head><title>HTML Financial Fixture</title></head>
          <body>
            <p>单位：人民币百万元</p>
            <table>
              <caption>主要财务指标</caption>
              <tr><th rowspan="2">项目</th><th colspan="2">报告期</th></tr>
              <tr><th>2025 Q2</th><th>2024 Q2</th></tr>
              <tr><td>营业收入</td><td>1,250</td><td>1,080</td></tr>
              <tr><td>经营利润</td><td>（215）</td><td>180</td></tr>
            </table>
          </body>
        </html>
        """,
        encoding="utf-8",
    )
    executor = TaskExecutor(tmp_path)
    executor.mineru_client = ExplodingMinerUClient()
    task = TaskCreate(
        task_name="html_financial_table",
        document_type="html_financial_table",
        inputs=[{"path": str(html_path), "role": "primary", "mime_type": "text/html"}],
        goal="Extract HTML financial tables with evidence.",
    )

    result = await executor.execute("html-task", task)
    events = [
        json.loads(line)
        for line in Path(result.trace_path or "").read_text(encoding="utf-8").splitlines()
    ]
    table = result.tables[0]

    assert result.status == "succeeded"
    assert table["title"] == "主要财务指标"
    assert table["unit"] == "人民币百万元"
    assert table["periods"] == ["报告期 2025 Q2", "报告期 2024 Q2"]
    assert table["rows"][0]["values"]["报告期 2025 Q2"] == 1250.0
    assert table["rows"][1]["values"]["报告期 2025 Q2"] == -215.0
    assert any(event["tool"] == "native_html_parser" for event in events)
    assert result.quality["diagnostics"]["financial_table_count"] == 1
