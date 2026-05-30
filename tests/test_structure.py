from pathlib import Path

from app.agent.structure import materialize_tables, parse_number
from app.agent.verifier import verify_tables
from app.tools.mineru_artifacts import MinerUArtifacts


def test_materialize_and_verify_financial_tables() -> None:
    fixture_dir = Path("tests/fixtures/mineru")
    artifacts = MinerUArtifacts.discover(fixture_dir, "annual_report")
    blocks = artifacts.load_content_blocks()
    tables = materialize_tables(blocks)

    assert len(tables) == 1
    table = tables[0]
    assert table["name"] == "consolidated_balance_sheet"
    assert table["periods"] == ["2025-12-31", "2024-12-31"]
    assert len(table["rows"]) == 3

    quality = verify_tables(tables)
    assert quality["validation_pass_rate"] == 1.0
    assert quality["failed_count"] == 0


def test_materialize_mineru_v2_html_table_with_multi_level_headers() -> None:
    html = """
    <table>
      <tr><th rowspan="2">项目</th><th colspan="2">期末余额</th></tr>
      <tr><th>2025-12-31</th><th>2024-12-31</th></tr>
      <tr><td>现金及现金等价物</td><td>1,200</td><td>(300)</td></tr>
    </table>
    """
    blocks = [
        {
            "type": "paragraph",
            "page_idx": 2,
            "content": {"paragraph_content": [{"type": "text", "content": "单位：人民币千元"}]},
        },
        {
            "type": "table",
            "page_idx": 2,
            "bbox": [80, 120, 900, 360],
            "content": {
                "table_caption": [{"type": "text", "content": "合并资产负债表"}],
                "table_footnote": [{"type": "text", "content": "单位：人民币千元"}],
                "html": html,
                "table_type": "complex_table",
                "table_nest_level": 1,
            },
        }
    ]

    tables = materialize_tables(blocks)

    assert len(tables) == 1
    table = tables[0]
    assert table["title"] == "合并资产负债表"
    assert table["unit"] == "人民币千元"
    assert table["table_type"] == "complex_table"
    assert table["footnote"] == "单位：人民币千元"
    assert table["periods"] == ["期末余额 2025-12-31", "期末余额 2024-12-31"]
    assert table["rows"][0]["item"] == "现金及现金等价物"
    assert table["rows"][0]["values"]["期末余额 2025-12-31"] == 1200.0
    assert table["rows"][0]["values"]["期末余额 2024-12-31"] == -300.0
    assert table["rows"][0]["evidence"]["page"] == 2


def test_parse_number_handles_mixed_and_unclosed_negative_parentheses() -> None:
    assert parse_number("（160)") == -160.0
    assert parse_number("（48)") == -48.0
    assert parse_number("（6") == -6.0


def test_materialize_narrative_financial_metrics_when_no_table_blocks() -> None:
    blocks = [
        {
            "type": "paragraph",
            "page_idx": 1,
            "bbox": [53, 541, 942, 571],
            "content": {
                "paragraph_content": [
                    {
                        "type": "text",
                        "content": (
                            "Financially, the year was marked by record performance. "
                            "We delivered over$245 billoninannual revenue, up 16 percent "
                            "year-over-year, and over $109 billion inoperating income, "
                            "up 24 percent."
                        ),
                    }
                ]
            },
        }
    ]

    tables = materialize_tables(blocks)

    assert len(tables) == 1
    table = tables[0]
    assert table["name"] == "financial_metrics_from_ocr_text"
    assert table["table_type"] == "narrative_metrics"
    assert table["periods"] == ["amount_usd_billions", "year_over_year_percent"]
    assert [row["item"] for row in table["rows"]] == ["Annual revenue", "Operating income"]
    assert table["rows"][0]["values"]["amount_usd_billions"] == 245.0
    assert table["rows"][0]["values"]["year_over_year_percent"] == 16.0
    assert table["rows"][1]["values"]["amount_usd_billions"] == 109.0
    assert table["rows"][1]["values"]["year_over_year_percent"] == 24.0
    assert table["evidence"]["page_start"] == 1


def test_verify_warnings_do_not_count_as_hard_failures() -> None:
    table = {
        "name": "mixed_cells",
        "unit": "USD",
        "periods": ["2025", "2024"],
        "rows": [
            {
                "item": "Revenue",
                "raw_values": ["1O0", "100"],
                "values": {"2025": None, "2024": 100.0},
                "components": [],
            }
        ],
    }

    quality = verify_tables([table])

    assert quality["validation_pass_rate"] == 1.0
    assert quality["warning_count"] == 1
    assert quality["failed_count"] == 0
    assert quality["issue_count"] == 1
    assert quality["diagnostics"]["numeric_parse_coverage"] == 0.5
    assert quality["diagnostics"]["risk_level"] == "medium"


def test_verify_marks_chinese_financial_tables_as_relevant() -> None:
    table = {
        "name": "合并资产负债表",
        "title": "合并资产负债表",
        "unit": "人民币元",
        "periods": ["2025年12月31日", "2024年12月31日"],
        "rows": [
            {
                "item": "货币资金",
                "raw_values": ["100", "90"],
                "values": {"2025年12月31日": 100.0, "2024年12月31日": 90.0},
                "components": [],
            },
            {
                "item": "资产总计",
                "raw_values": ["200", "180"],
                "values": {"2025年12月31日": 200.0, "2024年12月31日": 180.0},
                "components": [],
            },
            {
                "item": "负债合计",
                "raw_values": ["80", "70"],
                "values": {"2025年12月31日": 80.0, "2024年12月31日": 70.0},
                "components": [],
            },
        ],
    }

    quality = verify_tables([table])

    assert quality["diagnostics"]["financial_table_count"] == 1
    assert quality["diagnostics"]["tables"][0]["financial_relevance"] >= 0.5


def test_mineru_artifacts_discover_current_output_names(tmp_path: Path) -> None:
    for name in (
        "report.md",
        "report_content_list_v2.json",
        "report_middle.json",
        "report_model.json",
        "report_layout.pdf",
        "report_span.pdf",
    ):
        (tmp_path / name).write_text("[]" if name.endswith(".json") else "", encoding="utf-8")

    artifacts = MinerUArtifacts.discover(tmp_path, "report")

    assert artifacts.content_list_v2_path == tmp_path / "report_content_list_v2.json"
    assert artifacts.layout_path == tmp_path / "report_layout.pdf"
    assert artifacts.span_path == tmp_path / "report_span.pdf"
    assert "layout_path" in artifacts.existing_paths()
