from datetime import datetime, timezone
from enum import Enum
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field


class TaskStatus(str, Enum):
    queued = "queued"
    running = "running"
    succeeded = "succeeded"
    failed = "failed"


class DocumentInput(BaseModel):
    path: str | None = Field(default=None, description="Local file path or mounted path.")
    url: str | None = Field(default=None, description="Remote file URL.")
    role: str = Field(default="primary", description="primary, attachment, or reference.")
    mime_type: str | None = None


class TaskCreate(BaseModel):
    task_name: str = Field(default="financial-document-task")
    document_type: str = Field(
        default="unknown",
        description="annual_report_pdf, scanned_financial_pdf, cross_page_table_pdf, docx_report, office_attachment_pack, or unknown.",
    )
    inputs: list[DocumentInput]
    goal: str = Field(default="Extract structured data with evidence and validation logs.")
    options: dict[str, Any] = Field(default_factory=dict)


class TaskRecord(BaseModel):
    task_id: str = Field(default_factory=lambda: str(uuid4()))
    task_name: str
    document_type: str
    status: TaskStatus = TaskStatus.queued
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    error: str | None = None
    artifact_dir: str | None = None


class TaskResult(BaseModel):
    task_id: str
    task_name: str | None = None
    status: TaskStatus
    document_type: str
    summary: str
    tables: list[dict[str, Any]] = Field(default_factory=list)
    quality: dict[str, Any] = Field(default_factory=dict)
    trace_path: str | None = None
    plan_path: str | None = None
    result_path: str | None = None
