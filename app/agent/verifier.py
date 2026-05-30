from __future__ import annotations

import re
from typing import Any

from app.agent.structure import index_table_rows, parse_number, normalize_text


def verify_tables(tables: list[dict[str, Any]]) -> dict[str, Any]:
    checks: list[dict[str, Any]] = []
    for table in tables:
        checks.extend(_verify_table(table))

    summary_warnings = _build_warnings(tables, checks)
    passed = sum(1 for check in checks if check["status"] == "pass")
    warning = sum(1 for check in checks if check["status"] == "warn") + len(summary_warnings)
    failed = sum(1 for check in checks if check["status"] == "fail")
    hard_total = passed + failed
    return {
        "validation_pass_rate": round(passed / hard_total, 4) if hard_total else 1.0,
        "check_count": len(checks),
        "hard_check_count": hard_total,
        "passed_count": passed,
        "warning_count": warning,
        "failed_count": failed,
        "issue_count": warning + failed,
        "checks": checks,
        "warnings": summary_warnings,
        "diagnostics": build_quality_diagnostics(tables, checks, summary_warnings),
    }


def _verify_table(table: dict[str, Any]) -> list[dict[str, Any]]:
    checks: list[dict[str, Any]] = []
    row_index = index_table_rows(table)
    for row in table.get("rows", []):
        raw_values = row.get("raw_values", [])
        unparsed_numeric_cells = [
            normalize_text(value)
            for value in raw_values
            if _looks_numeric_like(value) and parse_number(value) is None
        ]
        if unparsed_numeric_cells:
            checks.append(
                {
                    "table": table.get("name"),
                    "type": "numeric_parse",
                    "row": row.get("item"),
                    "status": "warn",
                    "detail": "Numeric-looking cells could not be parsed.",
                    "cells": unparsed_numeric_cells[:5],
                }
            )

        components = [
            normalize_text(component).lower()
            for component in row.get("components", [])
            if normalize_text(component)
        ]
        if components:
            component_sum_check = _component_sum_check(table, row, row_index, components)
            if component_sum_check:
                checks.append(component_sum_check)

    if not checks:
        checks.append(
            {
                "table": table.get("name"),
                "type": "table_presence",
                "status": "pass",
                "detail": "Table loaded successfully.",
            }
        )
    return checks


def _component_sum_check(
    table: dict[str, Any],
    row: dict[str, Any],
    row_index: dict[str, dict[str, Any]],
    components: list[str],
) -> dict[str, Any] | None:
    expected = row.get("values", {})
    component_rows = [row_index.get(component) for component in components if row_index.get(component)]
    if not component_rows:
        return {
            "table": table.get("name"),
            "type": "sum_check",
            "row": row.get("item"),
            "status": "warn",
            "detail": "Referenced component rows were not found in the same table.",
        }

    period_keys = set(expected)
    for component_row in component_rows:
        period_keys.update(component_row.get("values", {}).keys())

    mismatches: list[str] = []
    for period in period_keys:
        expected_value = expected.get(period)
        if expected_value is None:
            continue
        component_total = 0.0
        saw_component = False
        for component_row in component_rows:
            value = component_row.get("values", {}).get(period)
            if value is None:
                continue
            component_total += float(value)
            saw_component = True
        if saw_component and abs(float(expected_value) - component_total) > 1e-6:
            mismatches.append(f"{period}: expected {expected_value}, got {component_total}")

    if mismatches:
        return {
            "table": table.get("name"),
            "type": "sum_check",
            "row": row.get("item"),
            "status": "fail",
            "detail": "; ".join(mismatches),
        }

    return {
        "table": table.get("name"),
        "type": "sum_check",
        "row": row.get("item"),
        "status": "pass",
        "detail": "Component rows match the referenced total row.",
    }


def _build_warnings(tables: list[dict[str, Any]], checks: list[dict[str, Any]]) -> list[str]:
    warnings: list[str] = []
    if not tables:
        warnings.append("No structured tables were produced.")
    if any(check["status"] == "fail" for check in checks):
        warnings.append("One or more numeric consistency checks failed.")
    if any(not table.get("periods") for table in tables):
        warnings.append("At least one table is missing explicit period headers.")
    if any(not table.get("unit") for table in tables):
        warnings.append("At least one table is missing an explicit unit or scale.")
    return warnings


def build_quality_diagnostics(
    tables: list[dict[str, Any]],
    checks: list[dict[str, Any]],
    warnings: list[str],
) -> dict[str, Any]:
    table_diagnostics = [_table_diagnostics(table) for table in tables]
    row_count = sum(item["row_count"] for item in table_diagnostics)
    raw_cell_count = sum(item["raw_cell_count"] for item in table_diagnostics)
    numeric_like_cell_count = sum(item["numeric_like_cell_count"] for item in table_diagnostics)
    parsed_numeric_cell_count = sum(item["parsed_numeric_cell_count"] for item in table_diagnostics)
    evidence_rows = sum(item["rows_with_evidence"] for item in table_diagnostics)

    failed = sum(1 for check in checks if check["status"] == "fail")
    parse_warnings = sum(1 for check in checks if check["type"] == "numeric_parse")
    parseable_rate = _safe_ratio(parsed_numeric_cell_count, numeric_like_cell_count)
    evidence_rate = _safe_ratio(evidence_rows, row_count)
    risk_level = _risk_level(
        table_count=len(tables),
        failed=failed,
        parse_warnings=parse_warnings,
        warnings=warnings,
        parseable_rate=parseable_rate,
        evidence_rate=evidence_rate,
    )

    return {
        "risk_level": risk_level,
        "table_count": len(tables),
        "row_count": row_count,
        "raw_cell_count": raw_cell_count,
        "numeric_like_cell_count": numeric_like_cell_count,
        "parsed_numeric_cell_count": parsed_numeric_cell_count,
        "numeric_parse_coverage": round(parseable_rate, 4),
        "evidence_coverage": round(evidence_rate, 4),
        "financial_table_count": sum(
            1 for item in table_diagnostics if item["financial_relevance"] >= 0.5
        ),
        "recommended_actions": _recommended_actions(
            table_count=len(tables),
            failed=failed,
            parse_warnings=parse_warnings,
            warnings=warnings,
            parseable_rate=parseable_rate,
            evidence_rate=evidence_rate,
        ),
        "tables": table_diagnostics,
    }


def _table_diagnostics(table: dict[str, Any]) -> dict[str, Any]:
    rows = table.get("rows", [])
    evidence = table.get("evidence") or {}
    raw_values = [
        value
        for row in rows
        for value in row.get("raw_values", [])
        if normalize_text(value)
    ]
    numeric_like_values = [value for value in raw_values if _looks_numeric_like(value)]
    parsed_numeric_values = [
        value for value in numeric_like_values if parse_number(value) is not None
    ]
    rows_with_evidence = sum(1 for row in rows if _has_row_evidence(row))
    return {
        "name": table.get("name"),
        "title": table.get("title"),
        "table_type": table.get("table_type"),
        "page_start": evidence.get("page_start"),
        "page_end": evidence.get("page_end", evidence.get("page_start")),
        "row_count": len(rows),
        "raw_cell_count": len(raw_values),
        "numeric_like_cell_count": len(numeric_like_values),
        "parsed_numeric_cell_count": len(parsed_numeric_values),
        "numeric_parse_coverage": round(
            _safe_ratio(len(parsed_numeric_values), len(numeric_like_values)),
            4,
        ),
        "rows_with_evidence": rows_with_evidence,
        "evidence_coverage": round(_safe_ratio(rows_with_evidence, len(rows)), 4),
        "has_periods": bool(table.get("periods")),
        "has_unit": bool(table.get("unit")),
        "financial_relevance": _financial_relevance(table),
    }


def _has_row_evidence(row: dict[str, Any]) -> bool:
    evidence = row.get("evidence") or {}
    return evidence.get("page") is not None or evidence.get("bbox") is not None


def _looks_numeric_like(value: Any) -> bool:
    text = normalize_text(value)
    if not text or not any(char.isdigit() for char in text):
        return False
    if _looks_like_period_label(text):
        return False

    currency_or_percent = bool(re.search(r"[$￥¥%％]|\b(RMB|CNY|USD|HKD)\b", text, re.I))
    compact = re.sub(r"[\s,，$￥¥%％()（）*†‡+\-—–]", "", text)
    compact = re.sub(r"^(RMB|CNY|USD|HKD)", "", compact, flags=re.IGNORECASE)
    if re.fullmatch(r"\d+(\.\d+)?", compact):
        return True
    if currency_or_percent:
        return True
    return bool(re.fullmatch(r"[\dOoIl.,，()（）+\-—–\s$￥¥%％]+", text))


def _looks_like_period_label(text: str) -> bool:
    normalized = normalize_text(text).lower()
    if re.search(r"\b(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\b", normalized):
        return True
    return bool(re.search(r"\b(year|month|quarter|period|ended|as of)\b", normalized))


def _financial_relevance(table: dict[str, Any]) -> float:
    text = " ".join(
        [
            normalize_text(table.get("name")),
            normalize_text(table.get("title")),
            " ".join(normalize_text(row.get("item")) for row in table.get("rows", [])[:25]),
        ]
    ).lower()
    terms = (
        "revenue",
        "income",
        "asset",
        "liabil",
        "equity",
        "cash",
        "expense",
        "profit",
        "loss",
        "debt",
        "operating",
        "balance",
        "financial",
        "资产负债表",
        "利润表",
        "现金流量表",
        "财务报表",
        "所有者权益",
        "股东权益",
        "营业收入",
        "营业成本",
        "货币资金",
        "净资产",
        "负债",
        "资产",
        "权益",
        "现金",
        "收入",
        "利润",
        "成本",
        "费用",
        "财务",
        "会计",
    )
    hits = sum(1 for term in terms if term in text)
    return round(min(1.0, hits / 4), 4)


def _risk_level(
    *,
    table_count: int,
    failed: int,
    parse_warnings: int,
    warnings: list[str],
    parseable_rate: float,
    evidence_rate: float,
) -> str:
    if table_count == 0 or failed:
        return "high"
    if parse_warnings or parseable_rate < 0.95 or evidence_rate < 0.9:
        return "medium"
    if warnings:
        return "medium"
    return "low"


def _recommended_actions(
    *,
    table_count: int,
    failed: int,
    parse_warnings: int,
    warnings: list[str],
    parseable_rate: float,
    evidence_rate: float,
) -> list[str]:
    actions: list[str] = []
    if table_count == 0:
        actions.append("Rerun with OCR or remote VLM/hybrid backend to improve table recall.")
    if failed:
        actions.append("Review failed sum checks and rerun affected pages with stricter parsing.")
    if parse_warnings or parseable_rate < 0.95:
        actions.append("Apply numeric repair for OCR-confused digits and footnote markers.")
    if evidence_rate < 0.9:
        actions.append("Preserve page and bbox evidence for rows missing source references.")
    if any("unit" in warning for warning in warnings):
        actions.append("Infer or confirm units from nearby paragraphs and table footnotes.")
    if any("period" in warning for warning in warnings):
        actions.append("Infer or confirm period headers from multi-level table headers.")
    return actions


def _safe_ratio(numerator: int, denominator: int) -> float:
    if denominator <= 0:
        return 1.0
    return numerator / denominator
