from __future__ import annotations

import sqlite3
from pathlib import Path

from app.schemas.task import TaskCreate, TaskRecord, TaskResult


class TaskStore:
    """Persistent task metadata store.

    SQLite is the default local backend for reproducible single-node runs. The API only depends
    on this small boundary, so production deployments can swap it for PostgreSQL/MySQL plus a
    worker queue without changing task execution semantics.
    """

    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def create_task(self, record: TaskRecord, request: TaskCreate) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO tasks (task_id, record_json, request_json, result_json)
                VALUES (?, ?, ?, NULL)
                """,
                (
                    record.task_id,
                    record.model_dump_json(),
                    request.model_dump_json(),
                ),
            )

    def get_record(self, task_id: str) -> TaskRecord | None:
        row = self._fetch_one(task_id)
        if row is None:
            return None
        return TaskRecord.model_validate_json(row["record_json"])

    def get_request(self, task_id: str) -> TaskCreate | None:
        row = self._fetch_one(task_id)
        if row is None:
            return None
        return TaskCreate.model_validate_json(row["request_json"])

    def get_result(self, task_id: str) -> TaskResult | None:
        row = self._fetch_one(task_id)
        if row is None or row["result_json"] is None:
            return None
        return TaskResult.model_validate_json(row["result_json"])

    def save_record(self, record: TaskRecord) -> None:
        with self._connect() as conn:
            conn.execute(
                "UPDATE tasks SET record_json = ? WHERE task_id = ?",
                (record.model_dump_json(), record.task_id),
            )

    def save_result(self, result: TaskResult) -> None:
        with self._connect() as conn:
            conn.execute(
                "UPDATE tasks SET result_json = ? WHERE task_id = ?",
                (result.model_dump_json(), result.task_id),
            )

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS tasks (
                    task_id TEXT PRIMARY KEY,
                    record_json TEXT NOT NULL,
                    request_json TEXT NOT NULL,
                    result_json TEXT
                )
                """
            )

    def _fetch_one(self, task_id: str) -> sqlite3.Row | None:
        with self._connect() as conn:
            return conn.execute(
                "SELECT record_json, request_json, result_json FROM tasks WHERE task_id = ?",
                (task_id,),
            ).fetchone()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path, timeout=30)
        conn.row_factory = sqlite3.Row
        return conn
