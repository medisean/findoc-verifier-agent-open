from __future__ import annotations

import re
from bs4 import BeautifulSoup

from typing import Any


def normalize_text(value: Any) -> str:
    if value is None:
        return ""
    return " ".join(str(value).split()).strip()


def extract_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return normalize_text(value)
    if isinstance(value, (int, float)):
        return normalize_text(value)
    if isinstance(value, list):
        return normalize_text(" ".join(extract_text(item) for item in value))
    if isinstance(value, dict):
        parts: list[str] = []
        for key in (
            "content",
            "text",
            "title",
            "caption",
            "title_content",
            "paragraph_content",
            "table_caption",
            "table_footnote",
            "item_content",
            "children",
        ):
            if key in value:
                parts.append(extract_text(value.get(key)))
        return normalize_text(" ".join(part for part in parts if part))
    return normalize_text(value)


def slugify_name(value: Any) -> str:
    text = extract_text(value).lower()
    chars: list[str] = []
    last_was_underscore = False
    for char in text:
        if char.isalnum():
            chars.append(char)
            last_was_underscore = False
        elif not last_was_underscore:
            chars.append("_")
            last_was_underscore = True
    result = "".join(chars).strip("_")
    return result or "table"


def parse_number(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = extract_text(value)
    if text in {"", "-", "--", "—", "–", "N/A", "NA", "null", "None"}:
        return None
    negative = False
    if text[:1] in {"(", "（"} and text[-1:] in {")", "）"}:
        negative = True
        text = text[1:-1].strip()
    elif text[:1] in {"(", "（"} and any(char.isdigit() for char in text[1:]):
        negative = True
        text = text[1:].strip()
    text = (
        text.replace(",", "")
        .replace("，", "")
        .replace(" ", "")
        .replace("%", "")
        .replace("％", "")
        .replace("￥", "")
        .replace("¥", "")
        .replace("$", "")
    )
    text = re.sub(r"^(RMB|CNY|USD|HKD)", "", text, flags=re.IGNORECASE)
    text = re.sub(r"[*†‡]+$", "", text)
    try:
        number = float(text)
        return -number if negative else number
    except ValueError:
        return None


def infer_periods(table_content: dict[str, Any]) -> list[str]:
    periods = table_content.get("periods")
    if isinstance(periods, list) and periods:
        return [extract_text(period) for period in periods if extract_text(period)]

    headers = table_content.get("headers")
    if isinstance(headers, list) and headers:
        last_row = headers[-1]
        if isinstance(last_row, list):
            inferred = [extract_text(cell) for cell in last_row[1:]]
            if any(inferred):
                return [period for period in inferred if period]
    return []


def parse_html_table(
    html: str,
    *,
    page_idx: int | None = None,
    table_bbox: Any = None,
) -> tuple[list[str], list[dict[str, Any]]]:
    grid = _html_table_to_grid(html)
    if not grid:
        return [], []

    body_start = _infer_body_start(grid)
    header_rows = grid[:body_start] if body_start > 0 else [grid[0]]
    body_rows = grid[body_start:] if body_start > 0 else grid[1:]
    max_values = max((max(len(row) - 1, 0) for row in body_rows), default=0)
    periods = _infer_periods_from_header_rows(header_rows, max_values)

    parsed_rows: list[dict[str, Any]] = []
    for raw_row in body_rows:
        if not any(extract_text(cell) for cell in raw_row):
            continue
        label = extract_text(raw_row[0]) if raw_row else ""
        values = raw_row[1:] if len(raw_row) > 1 else []
        if not label and not any(extract_text(value) for value in values):
            continue

        period_keys = list(periods)
        if len(period_keys) < len(values):
            period_keys.extend(f"col_{idx}" for idx in range(len(period_keys), len(values)))
        numeric_values = {
            period: parse_number(value)
            for period, value in zip(period_keys, values)
        }
        parsed_rows.append(
            {
                "item": label,
                "raw_values": [extract_text(value) for value in values],
                "values": numeric_values,
                "row_type": "line",
                "components": [],
                "evidence": {
                    "page": page_idx,
                    "bbox": table_bbox,
                    "source": "html_table",
                },
            }
        )
    return periods, parsed_rows


def _html_table_to_grid(html: str) -> list[list[str]]:
    soup = BeautifulSoup(html, "html.parser")
    table = soup.find("table")
    if table is None:
        return []

    rows: list[list[str]] = []
    rowspans: dict[int, tuple[str, int]] = {}
    for tr in table.find_all("tr"):
        current: list[str] = []
        col_idx = 0
        for cell in tr.find_all(["th", "td"], recursive=False):
            while col_idx in rowspans:
                text, remaining = rowspans[col_idx]
                current.append(text)
                if remaining <= 1:
                    del rowspans[col_idx]
                else:
                    rowspans[col_idx] = (text, remaining - 1)
                col_idx += 1

            text = extract_text(cell.get_text(" ", strip=True))
            colspan = _safe_int(cell.get("colspan"), 1)
            rowspan = _safe_int(cell.get("rowspan"), 1)
            for offset in range(colspan):
                current.append(text)
                if rowspan > 1:
                    rowspans[col_idx + offset] = (text, rowspan - 1)
            col_idx += colspan

        while col_idx in rowspans:
            text, remaining = rowspans[col_idx]
            current.append(text)
            if remaining <= 1:
                del rowspans[col_idx]
            else:
                rowspans[col_idx] = (text, remaining - 1)
            col_idx += 1
        if any(current):
            rows.append(current)
    return rows


def _safe_int(value: Any, default: int) -> int:
    try:
        return max(int(value), 1)
    except (TypeError, ValueError):
        return default


def _infer_body_start(rows: list[list[str]]) -> int:
    for idx, row in enumerate(rows):
        values = row[1:] if len(row) > 1 else []
        if any(parse_number(value) is not None for value in values):
            return idx
    return 1 if len(rows) > 1 else 0


def _infer_periods_from_header_rows(header_rows: list[list[str]], value_count: int) -> list[str]:
    if value_count <= 0:
        return []
    periods: list[str] = []
    for col_idx in range(1, value_count + 1):
        parts: list[str] = []
        for row in header_rows:
            if col_idx < len(row):
                text = extract_text(row[col_idx])
                if text and text not in parts:
                    parts.append(text)
        periods.append(normalize_text(" ".join(parts)) or f"col_{col_idx - 1}")
    return periods


def _first_text(*values: Any) -> str:
    for value in values:
        text = extract_text(value)
        if text:
            return text
    return ""


def normalize_table_block(block: dict[str, Any]) -> dict[str, Any]:
    content = block.get("content") or {}
    if not isinstance(content, dict):
        content = {"raw_content": content}

    title = _first_text(
        content.get("title"),
        content.get("caption"),
        content.get("table_caption"),
        block.get("context_title"),
        block.get("title"),
        block.get("text"),
        block.get("content_title"),
    )
    name = slugify_name(title or content.get("name") or block.get("name") or f"table_{block.get('page_idx', 0)}")
    periods = infer_periods(content)
    unit = _first_text(content.get("unit"), content.get("currency"), content.get("scale"), block.get("context_unit"))
    rows = []

    if content.get("html"):
        inferred_periods, parsed_rows = parse_html_table(
            content["html"],
            page_idx=block.get("page_idx"),
            table_bbox=block.get("bbox"),
        )
        if inferred_periods:
            periods = inferred_periods
        rows = parsed_rows
    else:
        raw_rows = content.get("rows") or content.get("table_rows") or []
        if isinstance(raw_rows, dict):
            raw_rows = [raw_rows]

        for raw_row in raw_rows:
            if not isinstance(raw_row, dict):
                continue
            label = normalize_text(
                raw_row.get("label") or raw_row.get("item") or raw_row.get("name") or raw_row.get("text")
            )
            values = raw_row.get("values") or raw_row.get("cells") or raw_row.get("data") or []
            if isinstance(values, dict):
                values = list(values.values())
            values = list(values) if isinstance(values, list) else [values]

            numeric_values: dict[str, float | None] = {}
            if periods and len(periods) == len(values):
                for period, value in zip(periods, values):
                    numeric_values[period] = parse_number(value)
            else:
                for idx, value in enumerate(values):
                    numeric_values[str(idx)] = parse_number(value)

            rows.append(
                {
                    "item": label,
                    "raw_values": values,
                    "values": numeric_values,
                    "row_type": normalize_text(raw_row.get("row_type") or "line"),
                    "components": [normalize_text(v) for v in raw_row.get("components", [])]
                    if isinstance(raw_row.get("components"), list)
                    else [],
                    "evidence": {
                        "page": raw_row.get("page_idx", block.get("page_idx")),
                        "bbox": raw_row.get("bbox") or block.get("bbox"),
                    },
                }
            )

    return {
        "name": name,
        "title": title or name,
        "unit": unit,
        "table_type": normalize_text(content.get("table_type")),
        "table_nest_level": content.get("table_nest_level"),
        "footnote": extract_text(content.get("table_footnote")),
        "image_source": content.get("image_source"),
        "periods": periods,
        "rows": rows,
        "evidence": {
            "page_start": block.get("page_idx"),
            "bbox": block.get("bbox"),
        },
        "raw_block": block,
    }


def merge_cross_page_tables(tables: list[dict[str, Any]]) -> list[dict[str, Any]]:
    merged: list[dict[str, Any]] = []
    by_name: dict[str, dict[str, Any]] = {}

    for table in sorted(tables, key=lambda item: item.get("evidence", {}).get("page_start", 0) or 0):
        key = table.get("name") or slugify_name(table.get("title"))
        existing = by_name.get(key)
        if existing and _can_merge(existing, table):
            existing["rows"].extend(table.get("rows", []))
            existing["evidence"]["page_end"] = table.get("evidence", {}).get("page_start")
            existing.setdefault("sources", []).append(table.get("evidence", {}))
            continue

        clone = dict(table)
        clone.setdefault("sources", [table.get("evidence", {})])
        clone["evidence"] = dict(table.get("evidence", {}))
        clone["evidence"]["page_end"] = table.get("evidence", {}).get("page_start")
        merged.append(clone)
        by_name[key] = clone

    return merged


def _can_merge(left: dict[str, Any], right: dict[str, Any]) -> bool:
    left_title = normalize_text(left.get("title")).lower()
    right_title = normalize_text(right.get("title")).lower()
    if not left_title or left_title != right_title:
        return False
    left_page = left.get("evidence", {}).get("page_end", left.get("evidence", {}).get("page_start"))
    right_page = right.get("evidence", {}).get("page_start")
    if left_page is None or right_page is None:
        return False
    return int(right_page) - int(left_page) <= 1


def index_table_rows(table: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        normalize_text(row.get("item")).lower(): row
        for row in table.get("rows", [])
        if normalize_text(row.get("item"))
    }


_NARRATIVE_FINANCIAL_PATTERNS = (
    (
        "Annual revenue",
        re.compile(
            r"(?:over|approximately|about)?\s*\$?\s*"
            r"(?P<amount>\d+(?:\.\d+)?)\s*billi?on\s*(?:in)?\s*annual\s*revenue"
            r"[^\d]{0,40}(?:up|increased?|growth)\s*"
            r"(?P<change>\d+(?:\.\d+)?)\s*percent",
            flags=re.IGNORECASE,
        ),
    ),
    (
        "Operating income",
        re.compile(
            r"(?:over|approximately|about)?\s*\$?\s*"
            r"(?P<amount>\d+(?:\.\d+)?)\s*billi?on\s*(?:in)?\s*operating\s*income"
            r"[^\d]{0,40}(?:up|increased?|growth)\s*"
            r"(?P<change>\d+(?:\.\d+)?)\s*percent",
            flags=re.IGNORECASE,
        ),
    ),
)


def materialize_narrative_metric_tables(blocks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    pages: list[int] = []
    for block in blocks:
        if _is_table_block(block):
            continue
        text = _block_text(block)
        if not text:
            continue
        for label, pattern in _NARRATIVE_FINANCIAL_PATTERNS:
            match = pattern.search(text)
            if not match:
                continue
            page_idx = block.get("page_idx")
            if isinstance(page_idx, int):
                pages.append(page_idx)
            rows.append(
                {
                    "item": label,
                    "raw_values": [match.group("amount"), match.group("change")],
                    "values": {
                        "amount_usd_billions": parse_number(match.group("amount")),
                        "year_over_year_percent": parse_number(match.group("change")),
                    },
                    "row_type": "narrative_metric",
                    "components": [],
                    "evidence": {
                        "page": page_idx,
                        "bbox": block.get("bbox"),
                        "source": "ocr_paragraph",
                    },
                }
            )

    if not rows:
        return []

    page_start = min(pages) if pages else None
    page_end = max(pages) if pages else page_start
    return [
        {
            "name": "financial_metrics_from_ocr_text",
            "title": "Financial Metrics From OCR Text",
            "unit": "USD billion; percent",
            "table_type": "narrative_metrics",
            "table_nest_level": 0,
            "footnote": "",
            "image_source": None,
            "periods": ["amount_usd_billions", "year_over_year_percent"],
            "rows": rows,
            "evidence": {
                "page_start": page_start,
                "page_end": page_end,
                "bbox": None,
            },
            "sources": [{"page_start": page_start, "page_end": page_end}],
            "raw_block": None,
        }
    ]


def materialize_chart_metric_tables(blocks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    tables: list[dict[str, Any]] = []
    for block in blocks:
        if not _is_chart_block(block):
            continue
        content = block.get("content") if isinstance(block.get("content"), dict) else {}
        title = _first_text(
            content.get("title"),
            content.get("caption"),
            block.get("title"),
            block.get("text"),
        )
        chart_type = normalize_text(content.get("chart_type") or block.get("chart_type") or "chart")
        unit = _first_text(
            content.get("unit"),
            content.get("value_unit"),
            content.get("y_axis_unit"),
            block.get("context_unit"),
        )
        periods = _chart_periods(content)
        rows = _chart_series_rows(content, periods, block, chart_type)
        rows.extend(_chart_annotation_rows(content, block))
        if not rows:
            continue

        table_periods = periods[:]
        for row in rows:
            for period in row.get("values", {}):
                if period not in table_periods:
                    table_periods.append(period)
        tables.append(
            {
                "name": slugify_name(title or chart_type),
                "title": title or chart_type,
                "unit": unit or "mixed",
                "table_type": "chart_metrics",
                "chart_type": chart_type,
                "table_nest_level": 0,
                "footnote": extract_text(content.get("note") or content.get("footnote")),
                "image_source": content.get("image_source"),
                "periods": table_periods,
                "rows": rows,
                "evidence": {
                    "page_start": block.get("page_idx"),
                    "page_end": block.get("page_idx"),
                    "bbox": block.get("bbox"),
                    "source": "chart_block",
                    "chart_type": chart_type,
                },
                "sources": [{"page_start": block.get("page_idx"), "page_end": block.get("page_idx")}],
                "raw_block": block,
            }
        )
    return tables


def materialize_global_reference_tables(
    blocks: list[dict[str, Any]],
    source_tables: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    candidates = _metric_candidates(source_tables)
    if not candidates:
        return []

    rows: list[dict[str, Any]] = []
    for block in blocks:
        if _is_table_block(block) or _is_chart_block(block):
            continue
        text = _block_text(block)
        mentions = _reference_mentions(text)
        if not mentions:
            continue
        for mention in mentions:
            resolved = _resolve_reference_candidate(mention, candidates, block)
            if not resolved:
                continue
            confidence = resolved["confidence"]
            candidate = resolved["candidate"]
            rows.append(
                {
                    "item": mention["phrase"],
                    "raw_values": [str(candidate["value"]), f"{confidence:.2f}"],
                    "values": {
                        "resolved_value": candidate["value"],
                        "confidence": confidence,
                    },
                    "row_type": "global_reference",
                    "components": [candidate["label"]],
                    "evidence": {
                        "page": block.get("page_idx"),
                        "bbox": block.get("bbox"),
                        "source": "global_reference_resolver",
                        "reference_text": text,
                        "target": {
                            "table": candidate["table"],
                            "row": candidate["label"],
                            "period": candidate["period"],
                            "unit": candidate["unit"],
                            "page": candidate["page"],
                            "metric_kind": candidate["metric_kind"],
                        },
                    },
                }
            )

    if not rows:
        return []

    pages = [row.get("evidence", {}).get("page") for row in rows if row.get("evidence", {}).get("page") is not None]
    return [
        {
            "name": "global_reference_resolution",
            "title": "Global Reference Resolution",
            "unit": "mixed; confidence score",
            "table_type": "global_reference_resolution",
            "table_nest_level": 0,
            "footnote": "",
            "image_source": None,
            "periods": ["resolved_value", "confidence"],
            "rows": rows,
            "evidence": {
                "page_start": min(pages) if pages else None,
                "page_end": max(pages) if pages else None,
                "bbox": None,
            },
            "sources": [{"page_start": min(pages) if pages else None, "page_end": max(pages) if pages else None}],
            "raw_block": None,
        }
    ]


def materialize_tables(blocks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    tables: list[dict[str, Any]] = []
    last_title_by_page: dict[Any, str] = {}
    last_unit_by_page: dict[Any, str] = {}
    for block in blocks:
        page_idx = block.get("page_idx")
        if not _is_table_block(block):
            unit = _extract_unit_from_text(_block_text(block))
            if unit:
                last_unit_by_page[page_idx] = unit
        if _is_heading_block(block):
            title = _block_heading_text(block)
            if title:
                last_title_by_page[page_idx] = title
        if _is_table_block(block):
            table_block = dict(block)
            if page_idx in last_title_by_page:
                table_block.setdefault("context_title", last_title_by_page[page_idx])
            if page_idx in last_unit_by_page:
                table_block.setdefault("context_unit", last_unit_by_page[page_idx])
            tables.append(normalize_table_block(table_block))

    structured_tables = merge_cross_page_tables(tables) if tables else []
    chart_tables = materialize_chart_metric_tables(blocks)
    all_tables = merge_cross_page_tables(structured_tables + chart_tables) if chart_tables else structured_tables
    if all_tables:
        return all_tables + materialize_global_reference_tables(blocks, all_tables)
    narrative_tables = materialize_narrative_metric_tables(blocks)
    return narrative_tables + materialize_global_reference_tables(blocks, narrative_tables)



def _is_table_block(block: dict[str, Any]) -> bool:
    block_type = normalize_text(block.get("type")).lower()
    if block_type in {"table", "simple_table", "complex_table"}:
        return True
    content = block.get("content")
    return isinstance(content, dict) and (
        "rows" in content or "table_rows" in content or "headers" in content or "html" in content
    )


def _is_chart_block(block: dict[str, Any]) -> bool:
    block_type = normalize_text(block.get("type")).lower()
    if block_type in {"chart", "figure_chart", "complex_chart", "plot"}:
        return True
    content = block.get("content")
    return isinstance(content, dict) and (
        "chart_type" in content or "series" in content or "annotations" in content
    )


def _is_heading_block(block: dict[str, Any]) -> bool:
    block_type = normalize_text(block.get("type")).lower()
    return block_type in {"title", "doc_title", "paragraph_title"}


def _block_heading_text(block: dict[str, Any]) -> str:
    content = block.get("content")
    if isinstance(content, dict):
        return extract_text(content.get("title_content") or content.get("paragraph_content"))
    return extract_text(content or block.get("text") or block.get("title"))


def _block_text(block: dict[str, Any]) -> str:
    content = block.get("content")
    if isinstance(content, dict):
        return extract_text(
            content.get("paragraph_content")
            or content.get("title_content")
            or content.get("page_footnote_content")
            or content
        )
    return extract_text(content or block.get("text") or block.get("title"))


def _extract_unit_from_text(text: str) -> str:
    normalized = normalize_text(text)
    match = re.search(r"单位\s*[:：]\s*([^,，。；;\n]+)", normalized)
    if match:
        return normalize_text(match.group(1))
    match = re.search(
        r"(RMB|CNY|USD|HKD)\s*(thousand|million|billion|yuan|元|千元|万元|百万元)",
        normalized,
        flags=re.IGNORECASE,
    )
    if match:
        return normalize_text(match.group(0))
    match = re.search(r"人民币[^,，。；;\n]*(元|千元|万元|百万元)", normalized)
    if match:
        return normalize_text(match.group(0))
    return ""


def _chart_periods(content: dict[str, Any]) -> list[str]:
    periods = content.get("periods") or content.get("x_axis") or content.get("categories")
    if isinstance(periods, list):
        return [extract_text(period) for period in periods if extract_text(period)]
    return []


def _chart_series_rows(
    content: dict[str, Any],
    periods: list[str],
    block: dict[str, Any],
    chart_type: str,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    series = content.get("series") or []
    if isinstance(series, dict):
        series = [series]
    if not isinstance(series, list):
        return rows

    for series_index, raw_series in enumerate(series):
        if not isinstance(raw_series, dict):
            continue
        label = _first_text(raw_series.get("name"), raw_series.get("label"), raw_series.get("metric"))
        values = raw_series.get("values") or raw_series.get("data") or []
        period_values = _period_values(values, periods)
        if not period_values:
            continue
        rows.append(
            {
                "item": label or f"series_{series_index}",
                "raw_values": [value for _, value in period_values],
                "values": {
                    period: parse_number(value)
                    for period, value in period_values
                },
                "row_type": f"chart_{chart_type}",
                "components": [normalize_text(v) for v in raw_series.get("components", [])]
                if isinstance(raw_series.get("components"), list)
                else [],
                "evidence": {
                    "page": block.get("page_idx"),
                    "bbox": raw_series.get("bbox") or block.get("bbox"),
                    "source": "chart_series",
                    "chart_type": chart_type,
                    "series_index": series_index,
                },
            }
        )
    return rows


def _chart_annotation_rows(content: dict[str, Any], block: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    annotations = content.get("annotations") or []
    if isinstance(annotations, dict):
        annotations = [annotations]
    if not isinstance(annotations, list):
        return rows

    for annotation_index, annotation in enumerate(annotations):
        if not isinstance(annotation, dict):
            continue
        label = _first_text(annotation.get("label"), annotation.get("metric"), annotation.get("text"))
        value = annotation.get("value") or annotation.get("amount") or annotation.get("percent")
        period = extract_text(annotation.get("period") or annotation.get("metric_period") or "annotation_value")
        if parse_number(value) is None:
            continue
        rows.append(
            {
                "item": label or f"annotation_{annotation_index}",
                "raw_values": [extract_text(value)],
                "values": {period: parse_number(value)},
                "row_type": "chart_annotation",
                "components": [],
                "evidence": {
                    "page": block.get("page_idx"),
                    "bbox": annotation.get("bbox") or block.get("bbox"),
                    "source": "chart_annotation",
                    "annotation_text": extract_text(annotation.get("text")),
                    "annotation_index": annotation_index,
                },
            }
        )
    return rows


def _period_values(values: Any, periods: list[str]) -> list[tuple[str, Any]]:
    if isinstance(values, dict):
        if periods:
            return [(period, values.get(period)) for period in periods if period in values]
        return [(extract_text(period), value) for period, value in values.items() if extract_text(period)]
    if isinstance(values, list):
        keys = periods[:] if periods else [str(idx) for idx in range(len(values))]
        if len(keys) < len(values):
            keys.extend(f"col_{idx}" for idx in range(len(keys), len(values)))
        return [(period, value) for period, value in zip(keys, values)]
    if values is not None:
        return [("value", values)]
    return []


def _metric_candidates(tables: list[dict[str, Any]]) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    for table in tables:
        for row in table.get("rows", []):
            values = row.get("values") or {}
            if not isinstance(values, dict):
                continue
            for period, value in values.items():
                if value is None:
                    continue
                label = normalize_text(row.get("item"))
                page = (row.get("evidence") or {}).get("page")
                if page is None:
                    page = (table.get("evidence") or {}).get("page_start")
                candidates.append(
                    {
                        "table": table.get("name"),
                        "table_title": table.get("title"),
                        "label": label,
                        "label_norm": label.lower(),
                        "period": normalize_text(period),
                        "value": float(value),
                        "unit": normalize_text(table.get("unit")),
                        "page": page,
                        "row_type": normalize_text(row.get("row_type")),
                        "metric_kind": _metric_kind(label, period, table),
                    }
                )
    return candidates


def _metric_kind(label: Any, period: Any, table: dict[str, Any]) -> str:
    text = normalize_text(" ".join([extract_text(label), extract_text(period), extract_text(table.get("title"))])).lower()
    if any(token in text for token in ("同比", "增幅", "增长率", "growth", "increase", "yoy")):
        return "growth"
    if any(token in text for token in ("毛利率", "利润率", "比率", "率", "margin", "rate", "ratio")):
        return "rate"
    if any(token in text for token in ("营业收入", "收入", "revenue", "sales")):
        return "revenue"
    if any(token in text for token in ("现金流", "cash flow", "cash")):
        return "cash_flow"
    if any(token in text for token in ("利润", "profit", "income")):
        return "profit"
    return "amount"


def _reference_mentions(text: str) -> list[dict[str, str]]:
    normalized = normalize_text(text)
    if not normalized:
        return []
    patterns = [
        ("growth", r"(?:该|上述|上文|图中|this|the)\s*(?:增幅|增长率|同比增长|increase|growth)"),
        ("rate", r"(?:该|上述|上文|图中|this|the)\s*(?:比率|毛利率|利润率|率|margin|rate|ratio)"),
        ("revenue", r"(?:该|上述|上文|图中|this|the)\s*(?:营业收入|收入|revenue|sales)"),
        ("cash_flow", r"(?:该|上述|上文|图中|this|the)\s*(?:现金流|经营现金流|cash flow|cash)"),
        ("amount", r"(?:该|上述|上文|图中|this|the)\s*(?:金额|数值|amount|figure|value)"),
    ]
    mentions: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for kind, pattern in patterns:
        for match in re.finditer(pattern, normalized, flags=re.IGNORECASE):
            phrase = normalize_text(match.group(0))
            key = (kind, phrase)
            if key in seen:
                continue
            seen.add(key)
            mentions.append(
                {
                    "kind": kind,
                    "phrase": phrase,
                    "text": normalized,
                    "period": _period_from_text(normalized),
                }
            )
    return mentions


def _period_from_text(text: str) -> str:
    match = re.search(r"(20\d{2}|19\d{2})", text)
    return match.group(1) if match else ""


def _resolve_reference_candidate(
    mention: dict[str, str],
    candidates: list[dict[str, Any]],
    block: dict[str, Any],
) -> dict[str, Any] | None:
    scored: list[tuple[float, dict[str, Any]]] = []
    mention_page = block.get("page_idx")
    for candidate in candidates:
        score = 0.0
        if candidate["metric_kind"] == mention["kind"]:
            score += 6.0
        elif mention["kind"] == "amount" and candidate["metric_kind"] in {"revenue", "profit", "cash_flow", "amount"}:
            score += 3.0
        if mention.get("period") and mention["period"] == candidate["period"]:
            score += 2.0
        if mention_page is not None and candidate.get("page") is not None:
            distance = int(mention_page) - int(candidate["page"])
            if distance >= 0:
                score += max(0.0, 2.0 - min(distance, 4) * 0.35)
            else:
                score -= 1.0
        phrase = mention["phrase"].lower()
        if any(token in candidate["label_norm"] for token in phrase.split() if len(token) > 2):
            score += 0.5
        scored.append((score, candidate))

    if not scored:
        return None
    scored.sort(key=lambda item: (item[0], item[1].get("page") or -1), reverse=True)
    best_score, best_candidate = scored[0]
    if best_score < 3.0:
        return None
    return {
        "candidate": best_candidate,
        "confidence": round(min(0.96, 0.55 + best_score / 12), 2),
    }
