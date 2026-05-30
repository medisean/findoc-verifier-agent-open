from scripts.run_capability_evidence import (
    run_chart_reference_evidence,
    run_contextual_repair_evidence,
    run_html_native_parse,
    run_mixed_dag_execution,
)


async def test_capability_evidence_scenarios_pass(tmp_path):
    scenarios = [
        await run_html_native_parse(tmp_path),
        await run_mixed_dag_execution(tmp_path),
        run_contextual_repair_evidence(),
        run_chart_reference_evidence(tmp_path),
    ]

    assert [scenario["status"] for scenario in scenarios] == ["pass", "pass", "pass", "pass"]
    assert scenarios[0]["native_html_tool_events"] >= 1
    assert scenarios[1]["graph"]["is_dag"] is True
    assert scenarios[1]["cross_file_checks"]["matched_metric_count"] >= 1
    assert scenarios[2]["repair_summary"]["repairs"][0]["context_evidence"]["unit"] == "人民币百万元"
    assert set(scenarios[3]["chart_types"]) == {"line_chart", "stacked_bar", "waterfall"}
    assert scenarios[3]["resolved_reference_count"] >= 4
    assert {"revenue", "growth", "rate", "cash_flow"}.issubset(
        set(scenarios[3]["resolved_metric_kinds"])
    )
