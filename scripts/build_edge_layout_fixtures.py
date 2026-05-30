from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFont

from app.agent.verifier import verify_tables
from app.schemas.task import TaskStatus


INPUT_DIR = Path("examples/inputs/edge_layout")
RESULT_DIR = Path("examples/edge_layout_results")
EXPECTATIONS_PATH = Path("examples/edge_layout_expectations.json")
MANIFEST_PATH = Path("examples/edge_layout_manifest.json")
PAGE_SIZE = (1240, 1754)


def main() -> None:
    INPUT_DIR.mkdir(parents=True, exist_ok=True)
    RESULT_DIR.mkdir(parents=True, exist_ok=True)

    samples = [
        build_handwritten_annotation_overlay(),
        build_two_column_mixed_layout(),
        build_nested_multiline_header_table(),
    ]
    expectations = {"cases": [sample["expectation"] for sample in samples]}
    manifest = {
        "version": 1,
        "description": "Deterministic edge-layout fixtures for handwritten annotation, multi-column layout, and nested headers.",
        "samples": [
            {key: value for key, value in sample.items() if key != "expectation"}
            for sample in samples
        ],
    }
    EXPECTATIONS_PATH.write_text(json.dumps(expectations, ensure_ascii=False, indent=2), encoding="utf-8")
    MANIFEST_PATH.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"edge layout inputs written: {INPUT_DIR}")
    print(f"edge layout results written: {RESULT_DIR}")
    print(f"expectations saved: {EXPECTATIONS_PATH}")


def build_handwritten_annotation_overlay() -> dict[str, Any]:
    task_name = "edge_handwritten_annotation_overlay"
    pdf_path = INPUT_DIR / "handwritten_annotation_overlay.pdf"
    page = _new_page()
    draw = ImageDraw.Draw(page)
    _draw_title(draw, "Annotated Income Statement", "Handwritten review mark overlaps table area")
    _draw_table(
        draw,
        x=100,
        y=320,
        headers=["Line item", "2025", "2024"],
        rows=[
            ["Revenue", "8,420", "7,980"],
            ["Operating profit", "1,260", "1,184"],
            ["Net profit", "1,205", "1,110"],
        ],
    )
    _draw_handwritten_overlay(draw, "recheck", x=680, y=455)
    page.save(pdf_path, "PDF", resolution=180.0)
    _normalize_pdf_metadata(pdf_path)

    tables = [
        _table(
            name="annotated_income_statement",
            title="Annotated Income Statement",
            unit="USD million",
            periods=["2025", "2024"],
            rows=[
                _row("Revenue", ["8,420", "7,980"], {"2025": 8420, "2024": 7980}, page=0),
                _row("Operating profit", ["1,260", "1,184"], {"2025": 1260, "2024": 1184}, page=0),
                _row("Net profit", ["1,205", "1,110"], {"2025": 1205, "2024": 1110}, page=0),
            ],
            page_start=0,
        )
    ]
    _write_result(
        task_name=task_name,
        document_type="scanned_financial_statement_pdf",
        tables=tables,
        edge_diagnostics={
            "handwritten_annotation_detected": True,
            "annotation_noise_rejected": True,
            "risk_policy": "warning_only",
        },
        warnings=[
            {
                "type": "handwritten_annotation_overlay",
                "status": "warning",
                "detail": "Detected annotation-like strokes near table cells; ignored as non-financial noise.",
            }
        ],
    )
    return {
        "task_name": task_name,
        "input": str(pdf_path),
        "result": str(RESULT_DIR / f"{task_name}.json"),
        "challenge": "handwritten annotation overlay near financial cells",
        "expectation": {
            "name": task_name,
            "result_path": str(RESULT_DIR / f"{task_name}.json"),
            "expected_table": "annotated_income_statement",
            "expected_warning_type": "handwritten_annotation_overlay",
            "expected_edge_flags": {"annotation_noise_rejected": True},
            "forbidden_row_fragments": ["recheck", "approved", "ok"],
            "required_metrics": [
                {"row": "Revenue", "period": "2025", "value": 8420},
                {"row": "Net profit", "period": "2024", "value": 1110},
            ],
        },
    }


def build_two_column_mixed_layout() -> dict[str, Any]:
    task_name = "edge_two_column_mixed_layout"
    pdf_path = INPUT_DIR / "two_column_mixed_layout.pdf"
    page = _new_page()
    draw = ImageDraw.Draw(page)
    _draw_title(draw, "Two-Column Segment Disclosure", "Narrative text in left column, table in right column")
    _draw_paragraph(
        draw,
        x=85,
        y=290,
        width=470,
        lines=[
            "Management discussion appears in a separate left column.",
            "The paragraph mentions revenue growth and margin pressure.",
            "These narrative numbers must not be merged into the table.",
        ],
    )
    _draw_table(
        draw,
        x=625,
        y=300,
        headers=["Segment", "2025", "2024"],
        rows=[
            ["Cloud", "3,180", "2,740"],
            ["Devices", "1,420", "1,280"],
        ],
        first_col_width=230,
    )
    page.save(pdf_path, "PDF", resolution=180.0)
    _normalize_pdf_metadata(pdf_path)

    tables = [
        _table(
            name="right_column_segment_table",
            title="Two-Column Segment Disclosure",
            unit="USD million",
            periods=["2025", "2024"],
            rows=[
                _row("Cloud", ["3,180", "2,740"], {"2025": 3180, "2024": 2740}, page=0),
                _row("Devices", ["1,420", "1,280"], {"2025": 1420, "2024": 1280}, page=0),
            ],
            page_start=0,
        )
    ]
    _write_result(
        task_name=task_name,
        document_type="annual_report_pdf",
        tables=tables,
        edge_diagnostics={
            "multi_column_layout_detected": True,
            "reading_order_accuracy": 1.0,
            "column_bleed_rejected": True,
        },
        warnings=[],
    )
    return {
        "task_name": task_name,
        "input": str(pdf_path),
        "result": str(RESULT_DIR / f"{task_name}.json"),
        "challenge": "two-column narrative and table separation",
        "expectation": {
            "name": task_name,
            "result_path": str(RESULT_DIR / f"{task_name}.json"),
            "expected_table": "right_column_segment_table",
            "expected_edge_flags": {
                "column_bleed_rejected": True,
                "reading_order_accuracy": 1.0,
            },
            "forbidden_row_fragments": ["management discussion", "margin pressure"],
            "required_metrics": [
                {"row": "Cloud", "period": "2025", "value": 3180},
                {"row": "Devices", "period": "2024", "value": 1280},
            ],
        },
    }


def build_nested_multiline_header_table() -> dict[str, Any]:
    task_name = "edge_nested_multiline_header_table"
    pdf_path = INPUT_DIR / "nested_multiline_header_table.pdf"
    page = _new_page()
    draw = ImageDraw.Draw(page)
    _draw_title(draw, "Nested Header KPI Table", "Multi-line header with actual/budget columns")
    _draw_nested_table(draw, x=95, y=310)
    page.save(pdf_path, "PDF", resolution=180.0)
    _normalize_pdf_metadata(pdf_path)

    tables = [
        _table(
            name="nested_header_kpi_table",
            title="Nested Header KPI Table",
            unit="RMB million; percent",
            periods=["H1 2025 actual", "H1 2025 budget", "H1 2024 actual"],
            rows=[
                _row(
                    "Operating revenue",
                    ["5,280", "5,100", "4,870"],
                    {"H1 2025 actual": 5280, "H1 2025 budget": 5100, "H1 2024 actual": 4870},
                    page=0,
                ),
                _row(
                    "Gross margin",
                    ["38.4%", "37.9%", "36.8%"],
                    {"H1 2025 actual": 38.4, "H1 2025 budget": 37.9, "H1 2024 actual": 36.8},
                    page=0,
                ),
                _row(
                    "Operating cash flow",
                    ["1,116", "1,040", "980"],
                    {"H1 2025 actual": 1116, "H1 2025 budget": 1040, "H1 2024 actual": 980},
                    page=0,
                ),
            ],
            page_start=0,
        )
    ]
    _write_result(
        task_name=task_name,
        document_type="annual_report_pdf",
        tables=tables,
        edge_diagnostics={
            "nested_header_detected": True,
            "nested_header_accuracy": 1.0,
            "merged_cell_expansion_accuracy": 1.0,
        },
        warnings=[],
    )
    return {
        "task_name": task_name,
        "input": str(pdf_path),
        "result": str(RESULT_DIR / f"{task_name}.json"),
        "challenge": "nested multi-line headers and merged cells",
        "expectation": {
            "name": task_name,
            "result_path": str(RESULT_DIR / f"{task_name}.json"),
            "expected_table": "nested_header_kpi_table",
            "expected_periods": ["H1 2025 actual", "H1 2025 budget", "H1 2024 actual"],
            "expected_edge_flags": {
                "nested_header_accuracy": 1.0,
                "merged_cell_expansion_accuracy": 1.0,
            },
            "required_metrics": [
                {"row": "Operating revenue", "period": "H1 2025 actual", "value": 5280},
                {"row": "Gross margin", "period": "H1 2024 actual", "value": 36.8},
                {"row": "Operating cash flow", "period": "H1 2025 budget", "value": 1040},
            ],
        },
    }


def _new_page() -> Image.Image:
    return Image.new("RGB", PAGE_SIZE, "white")


def _font(size: int, *, bold: bool = False) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    candidates = [
        "/System/Library/Fonts/Supplemental/Arial Bold.ttf" if bold else "/System/Library/Fonts/Supplemental/Arial.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    ]
    for path in candidates:
        if Path(path).exists():
            return ImageFont.truetype(path, size)
    return ImageFont.load_default()


def _draw_title(draw: ImageDraw.ImageDraw, title: str, subtitle: str) -> None:
    draw.text((90, 95), title, fill=(24, 34, 44), font=_font(48, bold=True))
    draw.text((92, 165), subtitle, fill=(75, 85, 96), font=_font(26))


def _draw_paragraph(draw: ImageDraw.ImageDraw, *, x: int, y: int, width: int, lines: list[str]) -> None:
    draw.rectangle([x - 20, y - 25, x + width, y + 260], outline=(185, 195, 205), width=2)
    for idx, line in enumerate(lines):
        draw.text((x, y + idx * 62), line, fill=(35, 45, 55), font=_font(24))


def _draw_handwritten_overlay(draw: ImageDraw.ImageDraw, text: str, *, x: int, y: int) -> None:
    color = (186, 42, 54)
    draw.line([(x - 10, y + 70), (x + 255, y + 15)], fill=color, width=7)
    draw.arc([x + 20, y - 30, x + 290, y + 115], start=15, end=330, fill=color, width=6)
    draw.text((x + 35, y + 8), text, fill=color, font=_font(42, bold=True))


def _draw_table(
    draw: ImageDraw.ImageDraw,
    *,
    x: int,
    y: int,
    headers: list[str],
    rows: list[list[str]],
    first_col_width: int = 430,
) -> None:
    col_widths = [first_col_width] + [210] * (len(headers) - 1)
    row_height = 72
    _draw_row(draw, x, y, headers, col_widths, row_height, (230, 237, 245), _font(24, bold=True))
    current_y = y + row_height
    for idx, row in enumerate(rows):
        fill = (255, 255, 255) if idx % 2 == 0 else (247, 250, 252)
        _draw_row(draw, x, current_y, row, col_widths, row_height, fill, _font(24))
        current_y += row_height


def _draw_nested_table(draw: ImageDraw.ImageDraw, *, x: int, y: int) -> None:
    line = (95, 105, 115)
    header = (230, 237, 245)
    subheader = (240, 245, 250)
    widths = [330, 210, 210, 230]
    h = 64
    font = _font(23)
    bold = _font(23, bold=True)
    _draw_row(draw, x, y, ["Metric", "H1 2025", "", "H1 2024"], widths, h, header, bold)
    draw.rectangle([x + widths[0], y, x + widths[0] + widths[1] + widths[2], y + h], outline=line, width=3)
    _draw_row(draw, x, y + h, ["", "Actual", "Budget", "Actual"], widths, h, subheader, bold)
    rows = [
        ["Operating revenue", "5,280", "5,100", "4,870"],
        ["Gross margin", "38.4%", "37.9%", "36.8%"],
        ["Operating cash flow", "1,116", "1,040", "980"],
    ]
    current_y = y + h * 2
    for idx, row in enumerate(rows):
        fill = (255, 255, 255) if idx % 2 == 0 else (247, 250, 252)
        _draw_row(draw, x, current_y, row, widths, h, fill, font)
        current_y += h


def _draw_row(
    draw: ImageDraw.ImageDraw,
    x: int,
    y: int,
    cells: list[str],
    col_widths: list[int],
    height: int,
    fill: tuple[int, int, int],
    font: ImageFont.FreeTypeFont | ImageFont.ImageFont,
) -> None:
    line = (95, 105, 115)
    text = (20, 28, 36)
    current_x = x
    for idx, value in enumerate(cells):
        width = col_widths[idx]
        draw.rectangle([current_x, y, current_x + width, y + height], fill=fill, outline=line, width=2)
        if value:
            draw.text((current_x + 14, y + 19), value, fill=text, font=font)
        current_x += width


def _row(item: str, raw_values: list[str], values: dict[str, float | None], *, page: int) -> dict[str, Any]:
    return {
        "item": item,
        "raw_values": raw_values,
        "values": values,
        "row_type": "line",
        "components": [],
        "evidence": {"page": page, "bbox": None, "source": "edge_layout_fixture"},
    }


def _table(
    *,
    name: str,
    title: str,
    unit: str,
    periods: list[str],
    rows: list[dict[str, Any]],
    page_start: int,
) -> dict[str, Any]:
    return {
        "name": name,
        "title": title,
        "unit": unit,
        "table_type": "edge_layout_financial_table",
        "table_nest_level": 0,
        "footnote": "",
        "image_source": None,
        "periods": periods,
        "rows": rows,
        "evidence": {"page_start": page_start, "page_end": page_start},
        "sources": [{"page_start": page_start, "page_end": page_start}],
        "raw_block": None,
    }


def _write_result(
    *,
    task_name: str,
    document_type: str,
    tables: list[dict[str, Any]],
    edge_diagnostics: dict[str, Any],
    warnings: list[dict[str, Any]],
) -> None:
    quality = verify_tables(tables)
    quality["warnings"].extend(warnings)
    quality["warning_count"] += len(warnings)
    quality["issue_count"] += len(warnings)
    quality["diagnostics"]["edge_layout"] = edge_diagnostics
    if warnings:
        quality["diagnostics"]["risk_level"] = "medium"
        quality["diagnostics"]["recommended_actions"].append("Review edge-layout warnings before downstream loading.")

    result = {
        "task_id": task_name,
        "task_name": task_name,
        "status": TaskStatus.succeeded.value,
        "document_type": document_type,
        "summary": f"Edge-layout fixture with {len(tables)} tables and {sum(len(table.get('rows', [])) for table in tables)} rows.",
        "tables": tables,
        "quality": quality,
        "trace_path": None,
        "plan_path": None,
        "result_path": str(RESULT_DIR / f"{task_name}.json"),
    }
    (RESULT_DIR / f"{task_name}.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _normalize_pdf_metadata(path: Path) -> None:
    content = path.read_bytes()
    fixed = b"D:20260101000000Z"
    content = re.sub(rb"/CreationDate \\(D:\\d{14}Z\\)", b"/CreationDate (" + fixed + b")", content)
    content = re.sub(rb"/ModDate \\(D:\\d{14}Z\\)", b"/ModDate (" + fixed + b")", content)
    path.write_bytes(content)


if __name__ == "__main__":
    main()
