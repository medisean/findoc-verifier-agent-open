from datetime import datetime, timezone
from enum import Enum
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field


class TraceStatus(str, Enum):
    started = "started"
    succeeded = "succeeded"
    failed = "failed"
    skipped = "skipped"


class TraceEvent(BaseModel):
    event_id: str = Field(default_factory=lambda: str(uuid4()))
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    task_id: str
    run_id: str
    stage: str
    event_type: str
    status: TraceStatus
    message: str
    tool: str | None = None
    duration_ms: int | None = None
    inputs: dict[str, Any] = Field(default_factory=dict)
    outputs: dict[str, Any] = Field(default_factory=dict)
    error: dict[str, Any] | None = None
