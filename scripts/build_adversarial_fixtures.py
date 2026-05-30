from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageFont

from app.agent.verifier import verify_tables
from app.schemas.task import TaskStatus


INPUT_DIR = Path("examples/inputs/adversarial")
RESULT_DIR = Path("examples/adversarial_results")
MANIFEST_PATH = Path("examples/adversarial_manifest.json")
PAGE_SIZE = (1240, 1754)


def main() -> None:
    INPUT_DIR.mkdir(parents=True, exist_ok=True)
    RESULT_DIR.mkdir(parents=True, exist_ok=True)

    samples = [
        build_low_light_scan(),
        build_cross_page_unit(),
        build_dense_numeric_footnotes(),
    ]
    manifest = {
        "version": 1,
        "description": "Deterministic adversarial financial-document fixtures.",
        "samples": samples,
    }
    MANIFEST_PATH.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"adversarial fixtures written: {INPUT_DIR}")
    print(f"adversarial result fixtures written: {RESULT_DIR}")
    print(f"manifest saved: {MANIFEST_PATH}")


def build_low_light_scan() -> dict[str, Any]:
    task_name = "adversarial_low_light_scan"
    pdf_path = INPUT_DIR / "low_light_blurred_scan.pdf"
    page = _new_page()
    draw = ImageDraw.Draw(page)
    _draw_title(draw, "Low-Light Scanned Income Metrics", "Blur, skew, and uneven lighting")
    _draw_table(
        draw,
        x=110,
        y=300,
        headers=["Metric", "2025", "2024"],
        rows=[
            ["Revenue", "2,450", "2,180"],
            ["Operating income", "610", "544"],
            ["Gross margin", "41.8%", "39.6%"],
        ],
    )
    page = _degrade_scan(page)
    page.save(pdf_path, "PDF", resolution=180.0)
    _normalize_pdf_metadata(pdf_path)

    tables = [
        _table(
            name="degraded_scan_income_metrics",
            title="Low-Light Scanned Income Metrics",
            unit="USD million; percent",
            periods=["2025", "2024"],
            rows=[
                _row("Revenue", ["2,450", "2,180"], {"2025": 2450, "2024": 2180}, page=0),
                _row("Operating income", ["610", "544"], {"2025": 610, "2024": 544}, page=0),
                _row("Gross margin", ["41.8%", "39.6%"], {"2025": 41.8, "2024": 39.6}, page=0),
            ],
            page_start=0,
        )
    ]
    _write_result(task_name, "scanned_financial_statement_pdf", tables)
    return {
        "task_name": task_name,
        "input": str(pdf_path),
        "result": str(RESULT_DIR / f"{task_name}.json"),
        "challenge": "blurred scan, skew, uneven lighting, numeric OCR risk",
        "gold_metrics": ["Revenue 2025 = 2450", "Operating income 2025 = 610"],
    }


def build_cross_page_unit() -> dict[str, Any]:
    task_name = "adversarial_cross_page_unit"
    pdf_path = INPUT_DIR / "cross_page_unit_header_shift.pdf"
    first = _new_page()
    draw = ImageDraw.Draw(first)
    _draw_title(draw, "Cash Flow Statement", "Unit: RMB thousand")
    _draw_table(
        draw,
        x=90,
        y=310,
        headers=["Item", "2025", "2024"],
        rows=[
            ["Net cash from operating activities", "183,200", "164,100"],
            ["Cash paid for capital expenditure", "(35,200)", "(29,750)"],
            ["Net increase in cash and equivalents", "61,500", "52,360"],
        ],
    )
    second = _new_page()
    draw = ImageDraw.Draw(second)
    _draw_title(draw, "Cash Flow Statement - Continued", "Header intentionally shortened")
    _draw_table(
        draw,
        x=90,
        y=300,
        headers=["Item", "2025", "2024"],
        rows=[
            ["Cash and equivalents at beginning of year", "210,400", "158,040"],
            ["Cash and equivalents at end of year", "271,900", "210,400"],
        ],
    )
    first.save(pdf_path, "PDF", save_all=True, append_images=[second], resolution=180.0)
    _normalize_pdf_metadata(pdf_path)

    tables = [
        _table(
            name="cross_page_cash_flow_statement",
            title="Cash Flow Statement",
            unit="RMB thousand",
            periods=["2025", "2024"],
            rows=[
                _row(
                    "Net cash from operating activities",
                    ["183,200", "164,100"],
                    {"2025": 183200, "2024": 164100},
                    page=0,
                ),
                _row(
                    "Cash paid for capital expenditure",
                    ["(35,200)", "(29,750)"],
                    {"2025": -35200, "2024": -29750},
                    page=0,
                ),
                _row(
                    "Cash and equivalents at end of year",
                    ["271,900", "210,400"],
                    {"2025": 271900, "2024": 210400},
                    page=1,
                ),
            ],
            page_start=0,
            page_end=1,
        )
    ]
    _write_result(task_name, "cross_page_table_pdf", tables)
    return {
        "task_name": task_name,
        "input": str(pdf_path),
        "result": str(RESULT_DIR / f"{task_name}.json"),
        "challenge": "cross-page table continuation, inherited unit, parenthesized negatives",
        "gold_metrics": ["Operating cash flow 2025 = 183200", "Ending cash 2025 = 271900"],
    }


def build_dense_numeric_footnotes() -> dict[str, Any]:
    task_name = "adversarial_dense_numeric_footnotes"
    pdf_path = INPUT_DIR / "dense_numeric_footnote_table.pdf"
    page = _new_page()
    draw = ImageDraw.Draw(page)
    _draw_title(draw, "Dense Numeric Footnote Table", "Amounts in USD million except percentages")
    _draw_table(
        draw,
        x=80,
        y=300,
        headers=["Line item", "2025", "2024", "Change"],
        rows=[
            ["Revenue*", "12,567", "11,802", "6.5%"],
            ["Net income (loss)", "2,684", "(512)", "n.m."],
            ["Diluted EPS", "3.42", "(0.66)", "n.m."],
            ["Operating margin†", "24.1%", "18.9%", "5.2ppt"],
        ],
    )
    _draw_note(draw, "Notes: * includes reclassified service revenue; † excludes one-time charges.")
    page.save(pdf_path, "PDF", resolution=180.0)
    _normalize_pdf_metadata(pdf_path)

    tables = [
        _table(
            name="dense_numeric_footnote_table",
            title="Dense Numeric Footnote Table",
            unit="USD million; percent; USD per share",
            periods=["2025", "2024", "change_percent"],
            rows=[
                _row(
                    "Revenue",
                    ["12,567", "11,802", "6.5%"],
                    {"2025": 12567, "2024": 11802, "change_percent": 6.5},
                    page=0,
                ),
                _row(
                    "Net income (loss)",
                    ["2,684", "(512)", "n.m."],
                    {"2025": 2684, "2024": -512, "change_percent": None},
                    page=0,
                ),
                _row(
                    "Operating margin",
                    ["24.1%", "18.9%", "5.2ppt"],
                    {"2025": 24.1, "2024": 18.9, "change_percent": 5.2},
                    page=0,
                ),
            ],
            page_start=0,
        )
    ]
    _write_result(task_name, "annual_report_pdf", tables)
    return {
        "task_name": task_name,
        "input": str(pdf_path),
        "result": str(RESULT_DIR / f"{task_name}.json"),
        "challenge": "dense numbers, footnote markers, percentages, negative parentheses",
        "gold_metrics": ["Revenue 2025 = 12567", "Net income 2024 = -512"],
    }


def _new_page() -> Image.Image:
    return Image.new("RGB", PAGE_SIZE, "white")


def _font(size: int, *, bold: bool = False) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    candidates = [
        "/System/Library/Fonts/Supplemental/Arial Bold.ttf" if bold else "/System/Library/Fonts/Supplemental/Arial.ttf",
        "/Library/Fonts/Arial Unicode.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    ]
    for path in candidates:
        if Path(path).exists():
            return ImageFont.truetype(path, size)
    return ImageFont.load_default()


def _draw_title(draw: ImageDraw.ImageDraw, title: str, subtitle: str) -> None:
    draw.text((90, 95), title, fill=(25, 35, 45), font=_font(48, bold=True))
    draw.text((92, 165), subtitle, fill=(70, 80, 92), font=_font(26))


def _draw_note(draw: ImageDraw.ImageDraw, note: str) -> None:
    draw.text((90, 1150), note, fill=(90, 90, 90), font=_font(24))


def _draw_table(
    draw: ImageDraw.ImageDraw,
    *,
    x: int,
    y: int,
    headers: list[str],
    rows: list[list[str]],
) -> None:
    col_widths = [430] + [210] * (len(headers) - 1)
    row_height = 72
    header_fill = (230, 237, 245)
    line = (95, 105, 115)
    text = (20, 28, 36)
    header_font = _font(24, bold=True)
    cell_font = _font(24)

    current_y = y
    _draw_row(draw, x, current_y, headers, col_widths, row_height, header_fill, line, text, header_font)
    current_y += row_height
    for idx, row in enumerate(rows):
        fill = (255, 255, 255) if idx % 2 == 0 else (247, 250, 252)
        _draw_row(draw, x, current_y, row, col_widths, row_height, fill, line, text, cell_font)
        current_y += row_height


def _draw_row(
    draw: ImageDraw.ImageDraw,
    x: int,
    y: int,
    cells: list[str],
    col_widths: list[int],
    height: int,
    fill: tuple[int, int, int],
    line: tuple[int, int, int],
    text: tuple[int, int, int],
    font: ImageFont.FreeTypeFont | ImageFont.ImageFont,
) -> None:
    current_x = x
    for col_idx, value in enumerate(cells):
        width = col_widths[col_idx]
        draw.rectangle([current_x, y, current_x + width, y + height], fill=fill, outline=line, width=2)
        draw.text((current_x + 16, y + 20), value, fill=text, font=font)
        current_x += width


def _degrade_scan(page: Image.Image) -> Image.Image:
    dark = ImageEnhance.Brightness(page).enhance(0.72)
    blurred = dark.filter(ImageFilter.GaussianBlur(radius=1.15))
    rotated = blurred.rotate(1.2, expand=True, fillcolor=(214, 214, 210))
    canvas = Image.new("RGB", PAGE_SIZE, (214, 214, 210))
    offset = ((PAGE_SIZE[0] - rotated.width) // 2, (PAGE_SIZE[1] - rotated.height) // 2)
    canvas.paste(rotated, offset)
    overlay = Image.new("RGB", PAGE_SIZE, (20, 18, 12))
    mask = Image.new("L", PAGE_SIZE, 0)
    mask_draw = ImageDraw.Draw(mask)
    for idx in range(PAGE_SIZE[1]):
        shade = int(70 * idx / PAGE_SIZE[1])
        mask_draw.line([(0, idx), (PAGE_SIZE[0], idx)], fill=shade)
    return Image.composite(overlay, canvas, mask)


def _row(item: str, raw_values: list[str], values: dict[str, float | None], *, page: int) -> dict[str, Any]:
    return {
        "item": item,
        "raw_values": raw_values,
        "values": values,
        "row_type": "line",
        "components": [],
        "evidence": {"page": page, "bbox": None, "source": "adversarial_fixture"},
    }


def _table(
    *,
    name: str,
    title: str,
    unit: str,
    periods: list[str],
    rows: list[dict[str, Any]],
    page_start: int,
    page_end: int | None = None,
) -> dict[str, Any]:
    return {
        "name": name,
        "title": title,
        "unit": unit,
        "table_type": "adversarial_financial_table",
        "table_nest_level": 0,
        "footnote": "",
        "image_source": None,
        "periods": periods,
        "rows": rows,
        "evidence": {"page_start": page_start, "page_end": page_start if page_end is None else page_end},
        "sources": [{"page_start": page_start, "page_end": page_start if page_end is None else page_end}],
        "raw_block": None,
    }


def _write_result(task_name: str, document_type: str, tables: list[dict[str, Any]]) -> None:
    quality = verify_tables(tables)
    result = {
        "task_id": task_name,
        "task_name": task_name,
        "status": TaskStatus.succeeded.value,
        "document_type": document_type,
        "summary": (
            f"Adversarial fixture with {len(tables)} tables and "
            f"{sum(len(table.get('rows', [])) for table in tables)} rows."
        ),
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
    content = re.sub(rb"/CreationDate \(D:\d{14}Z\)", b"/CreationDate (" + fixed + b")", content)
    content = re.sub(rb"/ModDate \(D:\d{14}Z\)", b"/ModDate (" + fixed + b")", content)
    path.write_bytes(content)


if __name__ == "__main__":
    main()
