from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class MinerUArtifacts:
    output_dir: Path
    markdown_path: Path | None = None
    content_list_path: Path | None = None
    content_list_v2_path: Path | None = None
    middle_path: Path | None = None
    model_path: Path | None = None
    layout_path: Path | None = None
    span_path: Path | None = None

    @classmethod
    def discover(cls, output_dir: Path, stem: str) -> "MinerUArtifacts":
        candidates = {
            "markdown_path": _find_first(output_dir, f"{stem}.md"),
            "content_list_path": _find_first(output_dir, f"{stem}_content_list.json"),
            "content_list_v2_path": _find_first(output_dir, f"{stem}_content_list_v2.json"),
            "middle_path": _find_first(output_dir, f"{stem}_middle.json"),
            "model_path": _find_first(output_dir, f"{stem}_model.json"),
            "layout_path": _find_first(output_dir, f"{stem}_layout.pdf")
            or _find_first(output_dir, "layout.pdf"),
            "span_path": _find_first(output_dir, f"{stem}_span.pdf")
            or _find_first(output_dir, "span.pdf"),
        }
        return cls(output_dir=output_dir, **candidates)

    def load_json(self, path: Path | None) -> Any:
        if path is None or not path.exists():
            return None
        return json.loads(path.read_text(encoding="utf-8"))

    def load_content_blocks(self) -> list[dict[str, Any]]:
        content = self.load_json(self.content_list_v2_path)
        if content:
            return _flatten_v2_blocks(content)
        legacy = self.load_json(self.content_list_path)
        if legacy:
            return _flatten_legacy_blocks(legacy)
        middle = self.load_json(self.middle_path)
        if middle:
            return _flatten_middle_blocks(middle)
        return []

    def existing_paths(self) -> dict[str, str]:
        paths: dict[str, str] = {}
        for field in (
            "markdown_path",
            "content_list_path",
            "content_list_v2_path",
            "middle_path",
            "model_path",
            "layout_path",
            "span_path",
        ):
            path = getattr(self, field)
            if path and path.exists():
                paths[field] = str(path)
        return paths


def _flatten_v2_blocks(data: Any) -> list[dict[str, Any]]:
    blocks: list[dict[str, Any]] = []
    if isinstance(data, list):
        for page_idx, page in enumerate(data):
            if isinstance(page, list):
                for block in page:
                    if isinstance(block, dict):
                        block = dict(block)
                        block.setdefault("page_idx", page_idx)
                        blocks.append(block)
            elif isinstance(page, dict):
                block = dict(page)
                block.setdefault("page_idx", page_idx)
                blocks.append(block)
    elif isinstance(data, dict):
        blocks.append(dict(data))
    return blocks


def _flatten_legacy_blocks(data: Any) -> list[dict[str, Any]]:
    blocks: list[dict[str, Any]] = []
    if isinstance(data, list):
        for block in data:
            if isinstance(block, dict):
                blocks.append(dict(block))
    elif isinstance(data, dict):
        for key in ("content_list", "blocks", "items"):
            value = data.get(key)
            if isinstance(value, list):
                return _flatten_legacy_blocks(value)
        blocks.append(dict(data))
    return blocks


def _flatten_middle_blocks(data: Any) -> list[dict[str, Any]]:
    if not isinstance(data, dict):
        return _flatten_legacy_blocks(data)

    pdf_info = data.get("pdf_info")
    if not isinstance(pdf_info, list):
        return _flatten_legacy_blocks(data)

    blocks: list[dict[str, Any]] = []
    for page_idx, page in enumerate(pdf_info):
        if not isinstance(page, dict):
            continue
        for key in ("preproc_blocks", "para_blocks", "blocks"):
            page_blocks = page.get(key)
            if not isinstance(page_blocks, list):
                continue
            for block in page_blocks:
                if isinstance(block, dict):
                    block = dict(block)
                    block.setdefault("page_idx", page.get("page_idx", page_idx))
                    blocks.append(block)
            if blocks:
                break
    return blocks


def _find_first(root: Path, pattern: str) -> Path | None:
    matches = sorted(root.rglob(pattern))
    return matches[0] if matches else None
