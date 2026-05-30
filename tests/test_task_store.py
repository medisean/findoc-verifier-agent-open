from pathlib import Path

from app.schemas.task import TaskCreate, TaskRecord, TaskResult, TaskStatus
from app.task_store import TaskStore


def test_task_store_persists_record_request_and_result(tmp_path: Path) -> None:
    store_path = tmp_path / "tasks.sqlite3"
    store = TaskStore(store_path)
    request = TaskCreate(
        task_name="persisted-task",
        document_type="annual_report_pdf",
        inputs=[{"path": "examples/inputs/annual_report.pdf"}],
    )
    record = TaskRecord(task_name=request.task_name, document_type=request.document_type)

    store.create_task(record, request)
    record.status = TaskStatus.running
    store.save_record(record)
    store.save_result(
        TaskResult(
            task_id=record.task_id,
            task_name=record.task_name,
            status=TaskStatus.succeeded,
            document_type=record.document_type,
            summary="ok",
        )
    )

    reopened = TaskStore(store_path)

    assert reopened.get_record(record.task_id).status == TaskStatus.running
    assert reopened.get_request(record.task_id).task_name == "persisted-task"
    assert reopened.get_result(record.task_id).summary == "ok"
