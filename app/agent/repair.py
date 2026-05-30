from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
import re
from typing import Any

from app.agent.structure import normalize_text, parse_number


_OCR_DIGIT_TRANSLATION = str.maketrans(
    {
        "O": "0",
        "o": "0",
        "I": "1",
        "l": "1",
    }
)


@dataclass(frozen=True)
class RepairCandidate:
    text: str
    value: float
    reason: str
    context_used: list[str]
    confidence: float


def repair_numeric_cells(
    tables: list[dict[str, Any]],
    quality: dict[str, Any] | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    repaired_tables = deepcopy(tables)
    repairs: list[dict[str, Any]] = []

    for table in repaired_tables:
        for row in table.get("rows", []):
            raw_values = row.get("raw_values", [])
            if not isinstance(raw_values, list):
                continue
            values = row.setdefault("values", {})
            period_keys = list(values.keys())
            for cell_index, raw_value in enumerate(raw_values):
                if parse_number(raw_value) is not None:
                    continue
                period = period_keys[cell_index] if cell_index < len(period_keys) else str(cell_index)
                context = _build_cell_context(table, row, period, values)
                candidate = repair_numeric_candidate(raw_value, context=context)
                if candidate is None:
                    continue

                raw_values[cell_index] = candidate.text
                if cell_index < len(period_keys):
                    values[period_keys[cell_index]] = candidate.value
                else:
                    values[period] = candidate.value

                repairs.append(
                    {
                        "table": table.get("name"),
                        "row": row.get("item"),
                        "period": period,
                        "original": normalize_text(raw_value),
                        "repaired": candidate.text,
                        "value": candidate.value,
                        "reason": candidate.reason,
                        "confidence": candidate.confidence,
                        "context_used": candidate.context_used,
                        "context_evidence": _context_evidence(context),
                    }
                )

    return repaired_tables, {
        "applied": bool(repairs),
        "repair_count": len(repairs),
        "repairs": repairs[:50],
        "truncated": len(repairs) > 50,
        "input_warning_count": (quality or {}).get("warning_count", 0),
    }


def repair_numeric_text(value: Any, context: dict[str, Any] | None = None) -> str | None:
    candidate = repair_numeric_candidate(value, context=context)
    return candidate.text if candidate else None


def repair_numeric_candidate(
    value: Any,
    context: dict[str, Any] | None = None,
) -> RepairCandidate | None:
    text = normalize_text(value)
    if not text or parse_number(text) is not None:
        return None
    if not any(char.isdigit() for char in text):
        return None

    candidate = text.translate(_OCR_DIGIT_TRANSLATION)
    context = context or {}
    context_used = _context_used(context)
    if candidate != text:
        parsed = parse_number(candidate)
        if parsed is not None:
            return RepairCandidate(
                text=candidate,
                value=parsed,
                reason="ocr_digit_confusion",
                context_used=context_used,
                confidence=_confidence(context_used, base=0.72),
            )

    unit_stripped = _strip_context_unit(candidate, context)
    if unit_stripped and unit_stripped != candidate:
        parsed = parse_number(unit_stripped)
        if parsed is not None:
            return RepairCandidate(
                text=unit_stripped,
                value=parsed,
                reason="contextual_ocr_unit_suffix"
                if candidate != text
                else "contextual_unit_suffix",
                context_used=context_used,
                confidence=_confidence(context_used, base=0.82),
            )

    return None


def _build_cell_context(
    table: dict[str, Any],
    row: dict[str, Any],
    period: str,
    values: dict[str, Any],
) -> dict[str, Any]:
    peer_values = {
        str(peer_period): peer_value
        for peer_period, peer_value in values.items()
        if str(peer_period) != str(period) and peer_value is not None
    }
    return {
        "table_name": table.get("name"),
        "table_title": table.get("title"),
        "unit": table.get("unit"),
        "footnote": table.get("footnote"),
        "period": period,
        "row_label": row.get("item"),
        "row_evidence": row.get("evidence") or {},
        "table_evidence": table.get("evidence") or {},
        "peer_values": peer_values,
    }


def _context_used(context: dict[str, Any]) -> list[str]:
    used: list[str] = []
    if normalize_text(context.get("unit")):
        used.append("table_unit")
    if normalize_text(context.get("footnote")):
        used.append("table_footnote")
    if normalize_text(context.get("period")):
        used.append("period_header")
    if normalize_text(context.get("row_label")):
        used.append("row_label")
    if context.get("row_evidence") or context.get("table_evidence"):
        used.append("source_evidence")
    if context.get("peer_values"):
        used.append("peer_period_values")
    return used or ["cell_text"]


def _context_evidence(context: dict[str, Any]) -> dict[str, Any]:
    peer_values = context.get("peer_values") or {}
    return {
        "table": context.get("table_name"),
        "title": context.get("table_title"),
        "unit": normalize_text(context.get("unit")),
        "footnote": normalize_text(context.get("footnote")),
        "period": normalize_text(context.get("period")),
        "row": normalize_text(context.get("row_label")),
        "row_evidence": context.get("row_evidence") or {},
        "table_evidence": context.get("table_evidence") or {},
        "peer_values": dict(list(peer_values.items())[:3]),
    }


def _strip_context_unit(value: str, context: dict[str, Any]) -> str | None:
    unit_text = " ".join(
        normalize_text(part)
        for part in (context.get("unit"), context.get("footnote"))
        if normalize_text(part)
    )
    tokens = _unit_tokens(unit_text)
    if not tokens:
        return None

    stripped = value
    for token in tokens:
        if re.search(r"[\u4e00-\u9fff]", token):
            stripped = stripped.replace(token, "")
        else:
            stripped = re.sub(rf"\b{re.escape(token)}\b", "", stripped, flags=re.IGNORECASE)
    stripped = normalize_text(stripped)
    return stripped or None


def _unit_tokens(unit_text: str) -> list[str]:
    normalized = normalize_text(unit_text)
    if not normalized:
        return []
    lower = normalized.lower()
    candidates = [
        "人民币百万元",
        "人民币千元",
        "人民币万元",
        "百万元",
        "千元",
        "万元",
        "亿元",
        "人民币",
        "million",
        "billion",
        "thousand",
        "yuan",
        "rmb",
        "cny",
        "usd",
        "hkd",
        "元",
    ]
    tokens = [
        token
        for token in candidates
        if token in normalized or token in lower
    ]
    return sorted(set(tokens), key=len, reverse=True)


def _confidence(context_used: list[str], *, base: float) -> float:
    bonus = 0.0
    for signal in ("table_unit", "period_header", "row_label", "source_evidence", "peer_period_values"):
        if signal in context_used:
            bonus += 0.04
    return round(min(0.98, base + bonus), 2)
