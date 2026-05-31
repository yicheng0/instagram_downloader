from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from threading import RLock
from typing import Any, Dict, Iterable, Iterator, List, Optional
from urllib.parse import urlparse

from .models import AppSettings, Creator, DownloadOptions, ErrorCode, Task, TaskCreate, TaskEvent, TaskStatus


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class Database:
    def __init__(self, path: Path):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = RLock()
        self._init()

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.path, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def _init(self) -> None:
        with self._lock, self.connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS tasks (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    status TEXT NOT NULL,
                    target_type TEXT NOT NULL,
                    targets_json TEXT NOT NULL,
                    options_json TEXT NOT NULL,
                    error TEXT,
                    error_code TEXT,
                    attempt_count INTEGER NOT NULL DEFAULT 0,
                    next_retry_at TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    started_at TEXT,
                    finished_at TEXT
                );

                CREATE TABLE IF NOT EXISTS task_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    task_id INTEGER NOT NULL,
                    level TEXT NOT NULL,
                    message TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(task_id) REFERENCES tasks(id)
                );

                CREATE TABLE IF NOT EXISTS app_settings (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS creators (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    username TEXT NOT NULL UNIQUE COLLATE NOCASE,
                    full_name TEXT,
                    avatar_url TEXT,
                    biography TEXT,
                    is_private INTEGER NOT NULL DEFAULT 0,
                    is_verified INTEGER NOT NULL DEFAULT 0,
                    followers INTEGER,
                    followees INTEGER,
                    mediacount INTEGER,
                    status TEXT NOT NULL DEFAULT 'pending',
                    error TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    refreshed_at TEXT
                );
                """
            )
            self._ensure_column(conn, "tasks", "error_code", "TEXT")
            self._ensure_column(conn, "tasks", "attempt_count", "INTEGER NOT NULL DEFAULT 0")
            self._ensure_column(conn, "tasks", "next_retry_at", "TEXT")

    def create_or_get_creator(self, username: str) -> Creator:
        now = utc_now()
        normalized = normalize_username(username)
        if not normalized:
            raise ValueError("请输入有效的 Instagram 博主主页或用户名。")
        with self._lock, self.connect() as conn:
            conn.execute(
                """
                INSERT INTO creators (username, status, created_at, updated_at)
                VALUES (?, 'pending', ?, ?)
                ON CONFLICT(username) DO UPDATE SET updated_at = excluded.updated_at
                """,
                (normalized, now, now),
            )
            row = conn.execute("SELECT * FROM creators WHERE username = ? COLLATE NOCASE", (normalized,)).fetchone()
        return self._row_to_creator(row)

    def get_creator(self, creator_id: int) -> Optional[Creator]:
        with self._lock, self.connect() as conn:
            row = conn.execute("SELECT * FROM creators WHERE id = ?", (creator_id,)).fetchone()
        return self._row_to_creator(row) if row else None

    def list_creators(self) -> List[Creator]:
        with self._lock, self.connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM creators
                ORDER BY COALESCE(refreshed_at, updated_at) DESC, id DESC
                """
            ).fetchall()
        return [self._row_to_creator(row) for row in rows]

    def update_creator_profile(self, creator_id: int, values: Dict[str, Any]) -> Optional[Creator]:
        now = utc_now()
        allowed = {
            "username",
            "full_name",
            "avatar_url",
            "biography",
            "is_private",
            "is_verified",
            "followers",
            "followees",
            "mediacount",
        }
        clean = {key: values[key] for key in allowed if key in values}
        assignments = ["status = 'ready'", "error = NULL", "updated_at = ?", "refreshed_at = ?"]
        params: List[object] = [now, now]
        for key, value in clean.items():
            assignments.append(f"{key} = ?")
            params.append(int(value) if isinstance(value, bool) else value)
        params.append(creator_id)
        with self._lock, self.connect() as conn:
            conn.execute(f"UPDATE creators SET {', '.join(assignments)} WHERE id = ?", params)
        return self.get_creator(creator_id)

    def mark_creator_error(self, creator_id: int, error: str) -> Optional[Creator]:
        now = utc_now()
        with self._lock, self.connect() as conn:
            conn.execute(
                """
                UPDATE creators
                SET status = 'error', error = ?, updated_at = ?, refreshed_at = ?
                WHERE id = ?
                """,
                (error, now, now, creator_id),
            )
        return self.get_creator(creator_id)

    def delete_creator(self, creator_id: int) -> bool:
        with self._lock, self.connect() as conn:
            cur = conn.execute("DELETE FROM creators WHERE id = ?", (creator_id,))
            return cur.rowcount > 0

    def _ensure_column(self, conn: sqlite3.Connection, table: str, column: str, definition: str) -> None:
        columns = [row["name"] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()]
        if column not in columns:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")

    def create_task(self, data: TaskCreate) -> Task:
        now = utc_now()
        with self._lock, self.connect() as conn:
            cur = conn.execute(
                """
                INSERT INTO tasks
                    (status, target_type, targets_json, options_json, error_code, attempt_count,
                     next_retry_at, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    "queued",
                    data.target_type,
                    json.dumps(data.targets),
                    data.options.model_dump_json(),
                    None,
                    0,
                    None,
                    now,
                    now,
                ),
            )
            task_id = int(cur.lastrowid)
        self.add_event(task_id, "status", "Task queued")
        task = self.get_task(task_id)
        if task is None:
            raise RuntimeError("Created task could not be loaded")
        return task

    def get_task(self, task_id: int) -> Optional[Task]:
        with self._lock, self.connect() as conn:
            row = conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
        return self._row_to_task(row) if row else None

    def list_tasks(self, limit: int = 100) -> List[Task]:
        with self._lock, self.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM tasks ORDER BY id DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [self._row_to_task(row) for row in rows]

    def list_queued_tasks(self) -> List[Task]:
        with self._lock, self.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM tasks WHERE status = 'queued' ORDER BY id ASC"
            ).fetchall()
        return [self._row_to_task(row) for row in rows]

    def claim_next_queued_task(self) -> Optional[Task]:
        now = utc_now()
        with self._lock, self.connect() as conn:
            row = conn.execute(
                """
                SELECT id FROM tasks
                WHERE status = 'queued'
                  AND (next_retry_at IS NULL OR next_retry_at <= ?)
                ORDER BY id ASC
                LIMIT 1
                """,
                (now,),
            ).fetchone()
            if row is None:
                return None
            task_id = int(row["id"])
            conn.execute(
                """
                UPDATE tasks
                SET status = 'running',
                    updated_at = ?,
                    started_at = COALESCE(started_at, ?),
                    attempt_count = attempt_count + 1,
                    next_retry_at = NULL
                WHERE id = ? AND status = 'queued'
                """,
                (now, now, task_id),
            )
            task_row = conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
        return self._row_to_task(task_row) if task_row else None

    def count_running_tasks(self) -> int:
        with self._lock, self.connect() as conn:
            row = conn.execute("SELECT COUNT(*) AS count FROM tasks WHERE status = 'running'").fetchone()
        return int(row["count"])

    def count_tasks(self) -> int:
        with self._lock, self.connect() as conn:
            row = conn.execute("SELECT COUNT(*) AS count FROM tasks").fetchone()
        return int(row["count"])

    def count_queued_tasks(self) -> int:
        with self._lock, self.connect() as conn:
            row = conn.execute("SELECT COUNT(*) AS count FROM tasks WHERE status = 'queued'").fetchone()
        return int(row["count"])

    def get_settings(self, default_download_root: Path) -> AppSettings:
        with self._lock, self.connect() as conn:
            rows = conn.execute("SELECT key, value FROM app_settings").fetchall()
        raw: Dict[str, Any] = {}
        for row in rows:
            try:
                raw[row["key"]] = json.loads(row["value"])
            except json.JSONDecodeError:
                raw[row["key"]] = row["value"]
        raw.setdefault("download_root", str(default_download_root))
        return AppSettings.model_validate(raw)

    def update_settings(self, values: Dict[str, Any], default_download_root: Path) -> AppSettings:
        clean = {
            key: value
            for key, value in values.items()
            if value is not None or key == "default_max_count"
        }
        with self._lock, self.connect() as conn:
            for key, value in clean.items():
                conn.execute(
                    """
                    INSERT INTO app_settings (key, value)
                    VALUES (?, ?)
                    ON CONFLICT(key) DO UPDATE SET value = excluded.value
                    """,
                    (key, json.dumps(value)),
                )
        return self.get_settings(default_download_root)

    def update_task_status(
        self,
        task_id: int,
        status: TaskStatus,
        error: Optional[str] = None,
        error_code: Optional[ErrorCode] = None,
        next_retry_at: Optional[str] = None,
    ) -> Optional[Task]:
        now = utc_now()
        started_at = now if status == "running" else None
        finished_at = now if status in {"cancelled", "failed", "completed"} else None
        assignments = ["status = ?", "updated_at = ?"]
        values: List[object] = [status, now]
        if error is not None:
            assignments.append("error = ?")
            values.append(error)
        if error_code is not None:
            assignments.append("error_code = ?")
            values.append(error_code)
        if next_retry_at is not None or status != "queued":
            assignments.append("next_retry_at = ?")
            values.append(next_retry_at)
        if started_at:
            assignments.append("started_at = COALESCE(started_at, ?)")
            values.append(started_at)
        if finished_at:
            assignments.append("finished_at = ?")
            values.append(finished_at)
        values.append(task_id)
        with self._lock, self.connect() as conn:
            conn.execute(
                f"UPDATE tasks SET {', '.join(assignments)} WHERE id = ?",
                values,
            )
        return self.get_task(task_id)

    def schedule_retry(self, task_id: int, error: str, error_code: ErrorCode, next_retry_at: str) -> Optional[Task]:
        now = utc_now()
        with self._lock, self.connect() as conn:
            conn.execute(
                """
                UPDATE tasks
                SET status = 'queued', error = ?, error_code = ?, next_retry_at = ?,
                    updated_at = ?, finished_at = NULL
                WHERE id = ?
                """,
                (error, error_code, next_retry_at, now, task_id),
            )
        return self.get_task(task_id)

    def retry_task(self, task_id: int) -> Optional[Task]:
        now = utc_now()
        with self._lock, self.connect() as conn:
            conn.execute(
                """
                UPDATE tasks
                SET status = 'queued', error = NULL, error_code = NULL, next_retry_at = NULL,
                    updated_at = ?, started_at = NULL, finished_at = NULL
                WHERE id = ? AND status IN ('failed', 'cancelled', 'completed')
                """,
                (now, task_id),
            )
        self.add_event(task_id, "status", "Task re-queued")
        return self.get_task(task_id)

    def reset_interrupted_tasks(self) -> None:
        now = utc_now()
        with self._lock, self.connect() as conn:
            conn.execute(
                """
                UPDATE tasks
                SET status = 'queued', updated_at = ?, error = 'Server restarted while task was running'
                WHERE status = 'running'
                """,
                (now,),
            )

    def add_event(self, task_id: int, level: str, message: str) -> TaskEvent:
        now = utc_now()
        with self._lock, self.connect() as conn:
            cur = conn.execute(
                """
                INSERT INTO task_events (task_id, level, message, created_at)
                VALUES (?, ?, ?, ?)
                """,
                (task_id, level, message, now),
            )
            event_id = int(cur.lastrowid)
            row = conn.execute("SELECT * FROM task_events WHERE id = ?", (event_id,)).fetchone()
        return self._row_to_event(row)

    def list_events(self, task_id: int, after_id: int = 0, limit: int = 500) -> List[TaskEvent]:
        with self._lock, self.connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM task_events
                WHERE task_id = ? AND id > ?
                ORDER BY id ASC
                LIMIT ?
                """,
                (task_id, after_id, limit),
            ).fetchall()
        return [self._row_to_event(row) for row in rows]

    def latest_events(self, limit: int = 100) -> List[TaskEvent]:
        with self._lock, self.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM task_events ORDER BY id DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [self._row_to_event(row) for row in reversed(rows)]

    def _row_to_task(self, row: sqlite3.Row) -> Task:
        return Task(
            id=row["id"],
            status=row["status"],
            target_type=row["target_type"],
            targets=json.loads(row["targets_json"]),
            options=DownloadOptions.model_validate_json(row["options_json"]),
            error=row["error"],
            error_code=row["error_code"],
            attempt_count=row["attempt_count"],
            next_retry_at=row["next_retry_at"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            started_at=row["started_at"],
            finished_at=row["finished_at"],
        )

    def _row_to_event(self, row: sqlite3.Row) -> TaskEvent:
        return TaskEvent(
            id=row["id"],
            task_id=row["task_id"],
            level=row["level"],
            message=row["message"],
            created_at=row["created_at"],
        )

    def _row_to_creator(self, row: sqlite3.Row) -> Creator:
        return Creator(
            id=row["id"],
            username=row["username"],
            full_name=row["full_name"],
            avatar_url=row["avatar_url"],
            biography=row["biography"],
            is_private=bool(row["is_private"]),
            is_verified=bool(row["is_verified"]),
            followers=row["followers"],
            followees=row["followees"],
            mediacount=row["mediacount"],
            status=row["status"],
            error=row["error"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            refreshed_at=row["refreshed_at"],
        )


def normalize_username(username: str) -> str:
    value = username.strip()
    if not value:
        return ""
    if "://" in value or value.lower().startswith("www.instagram.com/") or value.lower().startswith("instagram.com/"):
        parsed = urlparse(value if "://" in value else f"https://{value}")
        host = parsed.netloc.lower()
        if host not in {"instagram.com", "www.instagram.com"}:
            return ""
        parts = [part for part in parsed.path.split("/") if part]
        if len(parts) != 1 or parts[0].lower() in {"p", "reel", "reels", "stories", "explore"}:
            return ""
        value = parts[0]
    return value.lstrip("@").rstrip("/").lower()
