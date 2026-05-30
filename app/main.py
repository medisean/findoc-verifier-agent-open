from datetime import datetime, timezone

from fastapi import BackgroundTasks, FastAPI, HTTPException

from app.agent.executor import TaskExecutor
from app.schemas.task import TaskCreate, TaskRecord, TaskResult, TaskStatus
from app.settings import get_settings
from app.task_store import TaskStore

settings = get_settings()
settings.artifact_root.mkdir(parents=True, exist_ok=True)
task_store_path = settings.task_store_path or settings.artifact_root / "tasks.sqlite3"

app = FastAPI(
    title=settings.app_name,
    version="0.1.0",
    description="MinerU-based Data Agent for financial document structuring and verification.",
)

executor = TaskExecutor(settings.artifact_root)
task_store = TaskStore(task_store_path)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok", "service": settings.app_name}


@app.post("/v1/tasks", response_model=TaskRecord)
async def create_task(payload: TaskCreate, background_tasks: BackgroundTasks) -> TaskRecord:
    record = TaskRecord(
        task_name=payload.task_name,
        document_type=payload.document_type,
        artifact_dir=None,
    )
    record.artifact_dir = str(settings.artifact_root / record.task_id)
    task_store.create_task(record, payload)
    background_tasks.add_task(run_task, record.task_id)
    return record


@app.get("/v1/tasks/{task_id}", response_model=TaskRecord)
async def get_task(task_id: str) -> TaskRecord:
    record = task_store.get_record(task_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Task not found.")
    return record


@app.get("/v1/tasks/{task_id}/result", response_model=TaskResult)
async def get_result(task_id: str) -> TaskResult:
    record = task_store.get_record(task_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Task not found.")
    result = task_store.get_result(task_id)
    if result is None:
        raise HTTPException(status_code=202, detail="Task result is not ready.")
    return result


async def run_task(task_id: str) -> None:
    record = task_store.get_record(task_id)
    payload = task_store.get_request(task_id)
    if record is None or payload is None:
        return
    record.status = TaskStatus.running
    record.updated_at = datetime.now(timezone.utc)
    task_store.save_record(record)

    try:
        result = await executor.execute(task_id, payload)
        task_store.save_result(result)
        record.status = result.status
        record.error = result.summary if result.status == TaskStatus.failed else None
    except Exception as exc:  # pragma: no cover - defensive boundary for background jobs
        record.status = TaskStatus.failed
        record.error = str(exc)
        result = TaskResult(
            task_id=task_id,
            task_name=payload.task_name,
            status=TaskStatus.failed,
            document_type=payload.document_type,
            summary=f"Execution failed: {exc}",
            result_path=str(settings.artifact_root / task_id / "result.json"),
        )
        task_store.save_result(result)
    finally:
        record.updated_at = datetime.now(timezone.utc)
        task_store.save_record(record)
