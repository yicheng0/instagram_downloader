from __future__ import annotations

import os
import shutil
import socket
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

from instaloader import (
    BadCredentialsException,
    ConnectionException,
    LoginException,
    LoginRequiredException,
    PrivateProfileNotFollowedException,
    ProfileNotExistsException,
    QueryReturnedNotFoundException,
    TooManyRequestsException,
)
from requests import Timeout
from requests.exceptions import RequestException

from .database import Database, utc_now
from .models import AccountStatus, ErrorCode, HealthStatus, Task


class CoolingDown(Exception):
    pass


class StabilityController:
    def __init__(self) -> None:
        self.cooldown_until: Optional[str] = None
        self.cooldown_reason: Optional[str] = None

    def active_worker_limit(self, configured_limit: int) -> int:
        if self.is_cooling_down():
            return 1
        return configured_limit

    def is_cooling_down(self) -> bool:
        if not self.cooldown_until:
            return False
        return datetime.fromisoformat(self.cooldown_until) > datetime.now(timezone.utc)

    def ensure_can_start(self) -> None:
        if self.is_cooling_down():
            raise CoolingDown(self.cooldown_reason or "Rate limit cooldown is active")

    def activate_cooldown(self, seconds: int, reason: str) -> str:
        until = datetime.now(timezone.utc) + timedelta(seconds=seconds)
        self.cooldown_until = until.isoformat()
        self.cooldown_reason = reason
        return self.cooldown_until


def classify_error(exc: Exception) -> ErrorCode:
    text = str(exc).lower()
    if isinstance(exc, InterruptedError):
        return "cancelled"
    if isinstance(exc, TooManyRequestsException) or "429" in text or "too many requests" in text:
        return "rate_limit"
    if isinstance(exc, (BadCredentialsException, LoginException)) or "login" in text and "required" not in text:
        return "login_expired"
    if isinstance(exc, LoginRequiredException) or "login required" in text:
        return "login_required"
    if isinstance(exc, PrivateProfileNotFollowedException) or "private" in text and "follow" in text:
        return "private_no_access"
    if isinstance(exc, (ProfileNotExistsException, QueryReturnedNotFoundException)) or "not found" in text:
        return "not_found"
    if isinstance(exc, (Timeout, socket.timeout)) or "timeout" in text or "timed out" in text:
        return "timeout"
    if isinstance(exc, (ConnectionException, RequestException, OSError)) and not isinstance(exc, (PermissionError, FileNotFoundError)):
        return "network"
    if isinstance(exc, (PermissionError, FileNotFoundError)) or "no space" in text or "disk" in text:
        return "disk_error"
    return "unknown"


def retry_delay_seconds(error_code: ErrorCode, attempt_count: int) -> Optional[int]:
    if error_code == "network":
        return _bounded_backoff(attempt_count, base=30, maximum=300, retries=3)
    if error_code == "timeout":
        return _bounded_backoff(attempt_count, base=45, maximum=360, retries=2)
    if error_code == "rate_limit":
        return _bounded_backoff(attempt_count, base=600, maximum=3600, retries=3)
    return None


def retry_at(seconds: int) -> str:
    return (datetime.now(timezone.utc) + timedelta(seconds=seconds)).isoformat()


def _bounded_backoff(attempt_count: int, base: int, maximum: int, retries: int) -> Optional[int]:
    if attempt_count >= retries:
        return None
    return min(maximum, base * (2 ** max(0, attempt_count - 1)))


def health_status(db: Database, download_root: Path, data_root: Path, session: AccountStatus,
                  cooling_down: bool = False, cooldown_until: Optional[str] = None) -> HealthStatus:
    database_writable = _database_writable(db)
    download_root_writable = _path_writable(download_root)
    free_disk_bytes = shutil.disk_usage(download_root if download_root.exists() else data_root).free
    ok = database_writable and download_root_writable and free_disk_bytes > 100 * 1024 * 1024
    message = None if ok else "Health check found a storage or database issue."
    return HealthStatus(
        ok=ok,
        database_writable=database_writable,
        download_root_writable=download_root_writable,
        free_disk_bytes=free_disk_bytes,
        session=session,
        running_tasks=db.count_running_tasks(),
        queued_tasks=db.count_queued_tasks(),
        cooling_down=cooling_down,
        cooldown_until=cooldown_until,
        message=message,
    )


def validate_preflight(db: Database, download_root: Path) -> None:
    status = health_status(db, download_root, download_root.parent, AccountStatus())
    if not status.database_writable:
        raise ValueError("数据库不可写，无法创建任务。")
    if not status.download_root_writable:
        raise ValueError("下载目录不可写，无法创建任务。")
    if status.free_disk_bytes <= 100 * 1024 * 1024:
        raise ValueError("磁盘空间不足，剩余空间低于 100MB。")


def _database_writable(db: Database) -> bool:
    try:
        with db.connect() as conn:
            conn.execute("SELECT 1").fetchone()
        return True
    except Exception:
        return False


def _path_writable(path: Path) -> bool:
    try:
        path.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(dir=path, delete=True):
            pass
        return True
    except Exception:
        return False
