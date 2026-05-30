from app.agent.repair import repair_numeric_cells, repair_numeric_text
from app.agent.verifier import verify_tables


def test_repair_numeric_text_for_ocr_digit_confusion() -> None:
    assert repair_numeric_text("1O0") == "100"
    assert repair_numeric_text("l,23O") == "1,230"
    assert repair_numeric_text("Revenue") is None


def test_repair_numeric_cells_updates_values_and_quality() -> None:
    tables = [
        {
            "name": "ocr_table",
            "title": "OCR Table",
            "unit": "USD",
            "periods": ["2025", "2024"],
            "rows": [
                {
                    "item": "Revenue",
                    "raw_values": ["1O0", "90"],
                    "values": {"2025": None, "2024": 90.0},
                    "components": [],
                    "evidence": {"page": 1, "bbox": [0, 0, 10, 10]},
                }
            ],
        }
    ]

    before = verify_tables(tables)
    repaired_tables, summary = repair_numeric_cells(tables, before)
    after = verify_tables(repaired_tables)

    assert before["warning_count"] == 1
    assert summary["applied"] is True
    assert summary["repair_count"] == 1
    assert repaired_tables[0]["rows"][0]["raw_values"][0] == "100"
    assert repaired_tables[0]["rows"][0]["values"]["2025"] == 100.0
    assert after["warning_count"] == 0


def test_contextual_repair_uses_unit_and_period_evidence() -> None:
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
    repair = summary["repairs"][0]

    assert summary["applied"] is True
    assert repair["reason"] == "contextual_ocr_unit_suffix"
    assert "table_unit" in repair["context_used"]
    assert "period_header" in repair["context_used"]
    assert "source_evidence" in repair["context_used"]
    assert repair["context_evidence"]["unit"] == "人民币百万元"
    assert repair["context_evidence"]["period"] == "2025"
    assert repair["context_evidence"]["peer_values"] == {"2024": 90.0}
    assert repaired_tables[0]["rows"][0]["raw_values"][0] == "100"
    assert repaired_tables[0]["rows"][0]["values"]["2025"] == 100.0
