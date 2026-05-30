from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from app.schemas.task import DocumentInput, TaskCreate


PDF_SUFFIXES = {".pdf"}
IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp", ".webp"}
OFFICE_SUFFIXES = {".doc", ".docx", ".ppt", ".pptx", ".xls", ".xlsx"}
HTML_SUFFIXES = {".html", ".htm"}
CHINESE_HINTS = (
    "年报",
    "财务",
    "审计",
    "招行",
    "茅台",
    "宁德",
    "比亚迪",
    "资产",
    "利润",
    "现金流",
    "china",
    "cn_",
)
SCAN_HINTS = ("scan", "scanned", "ocr", "photo", "image", "拍照", "扫描", "低质量")


@dataclass(frozen=True)
class InputSignal:
    path: str | None
    url: str | None
    role: str
    mime_type: str | None
    suffix: str
    exists: bool
    file_size_bytes: int | None
    file_size_mb: float | None
    pdf_like: bool
    image_like: bool
    office_like: bool
    html_like: bool
    scanned_hint: bool
    chinese_hint: bool

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class DocumentProfile:
    document_type: str
    goal: str
    input_count: int
    local_input_count: int
    has_pdf: bool
    has_image: bool
    has_office: bool
    has_html: bool
    has_remote_input: bool
    scanned_hint: bool
    chinese_hint: bool
    large_document_hint: bool
    recommended_backend: str
    recommended_method: str | None
    parse_strategy: str
    preflight_page_window: dict[str, int] | None
    reasons: list[str]
    inputs: list[InputSignal]

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["inputs"] = [item.to_dict() for item in self.inputs]
        return data


def build_document_profile(task: TaskCreate) -> DocumentProfile:
    signals = [_input_signal(task, item) for item in task.inputs]
    has_pdf = any(item.pdf_like for item in signals)
    has_image = any(item.image_like for item in signals)
    has_office = any(item.office_like for item in signals)
    has_html = any(item.html_like for item in signals)
    has_remote = any(item.url and not item.path for item in signals)
    scanned_hint = _has_scan_hint(task) or any(item.scanned_hint for item in signals)
    chinese_hint = _has_chinese_hint(task) or any(item.chinese_hint for item in signals)
    large_document_hint = _large_document_hint(task, signals)

    reasons: list[str] = []
    if scanned_hint or has_image:
        parse_strategy = "ocr_first"
        recommended_method = "ocr"
        reasons.append("Input metadata or file type indicates scanned/image content.")
    elif has_html and not has_pdf and not has_image and not has_office:
        parse_strategy = "native_html_table_parse"
        recommended_method = "html_table"
        reasons.append("HTML input can be parsed directly into table blocks without OCR.")
    elif has_office and not has_pdf:
        parse_strategy = "office_attachment_expansion"
        recommended_method = None
        reasons.append("Office inputs should be expanded and parsed as document units.")
    elif large_document_hint:
        parse_strategy = "sample_then_full_text"
        recommended_method = "txt"
        reasons.append("Large or annual-report-like PDF should be profiled before full extraction.")
    elif has_pdf:
        parse_strategy = "text_first_with_quality_recovery"
        recommended_method = "txt"
        reasons.append("PDF appears suitable for text-layer parsing with OCR fallback.")
    else:
        parse_strategy = "generic_document_parse"
        recommended_method = None
        reasons.append("No specialized route was inferred from inputs.")

    if chinese_hint:
        reasons.append("Chinese financial-report hints detected; prefer Chinese language settings when supplied.")
    if has_remote:
        reasons.append("Remote input URL present; caller should mount or fetch it before local parsing.")

    return DocumentProfile(
        document_type=task.document_type,
        goal=task.goal,
        input_count=len(task.inputs),
        local_input_count=sum(1 for item in signals if item.path),
        has_pdf=has_pdf,
        has_image=has_image,
        has_office=has_office,
        has_html=has_html,
        has_remote_input=has_remote,
        scanned_hint=scanned_hint,
        chinese_hint=chinese_hint,
        large_document_hint=large_document_hint,
        recommended_backend="pipeline" if has_pdf or has_image else "native_html" if has_html else "native_or_mineru",
        recommended_method=recommended_method,
        parse_strategy=parse_strategy,
        preflight_page_window={"start_page": 0, "end_page": 2} if large_document_hint else None,
        reasons=reasons,
        inputs=signals,
    )


def profile_for_input(task: TaskCreate, input_path: Path) -> InputSignal:
    for item in task.inputs:
        if item.path and Path(item.path) == input_path:
            return _input_signal(task, item)
    return _input_signal(task, DocumentInput(path=str(input_path)))


def _input_signal(task: TaskCreate, item: DocumentInput) -> InputSignal:
    suffix = ""
    exists = False
    file_size_bytes: int | None = None
    file_size_mb: float | None = None
    path = Path(item.path) if item.path else None
    if path:
        suffix = path.suffix.lower()
        exists = path.exists()
        if exists and path.is_file():
            file_size_bytes = path.stat().st_size
            file_size_mb = round(file_size_bytes / (1024 * 1024), 3)
    name = " ".join(
        part
        for part in [
            item.path or "",
            item.url or "",
            item.mime_type or "",
            item.role,
            task.task_name,
            task.document_type,
        ]
        if part
    ).lower()
    return InputSignal(
        path=item.path,
        url=item.url,
        role=item.role,
        mime_type=item.mime_type,
        suffix=suffix,
        exists=exists,
        file_size_bytes=file_size_bytes,
        file_size_mb=file_size_mb,
        pdf_like=suffix in PDF_SUFFIXES or "pdf" in (item.mime_type or "").lower(),
        image_like=suffix in IMAGE_SUFFIXES or (item.mime_type or "").lower().startswith("image/"),
        office_like=suffix in OFFICE_SUFFIXES or any(token in (item.mime_type or "").lower() for token in OFFICE_SUFFIXES),
        html_like=suffix in HTML_SUFFIXES or "html" in (item.mime_type or "").lower(),
        scanned_hint=any(hint in name for hint in SCAN_HINTS),
        chinese_hint=any(hint in name for hint in CHINESE_HINTS),
    )


def _has_scan_hint(task: TaskCreate) -> bool:
    text = f"{task.task_name} {task.document_type} {task.goal}".lower()
    return any(hint in text for hint in SCAN_HINTS)


def _has_chinese_hint(task: TaskCreate) -> bool:
    text = f"{task.task_name} {task.document_type} {task.goal}".lower()
    return any(hint in text for hint in CHINESE_HINTS)


def _large_document_hint(task: TaskCreate, signals: list[InputSignal]) -> bool:
    document_type = task.document_type.lower()
    name = task.task_name.lower()
    if "annual" in document_type or "annual" in name or "年报" in name:
        return any(item.pdf_like for item in signals)
    return any((item.file_size_mb or 0) >= 25 for item in signals if item.pdf_like)
