from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Callable, Set

from .database import Database
from .downloader import run_download_task
from .models import EventMessage, Task, TaskCreate, TaskEvent
from .stability import StabilityController, classify_error, retry_at, retry_delay_seconds


SessionProvider = Callable[[int, bool], tuple[str | None, str | None]]
SessionInvalidator = Callable[[str, str], None]
SessionCooldown = Callable[[str, str], None]
SessionFailureRecorder = Callable[[str, str, str], None]
SessionSuccessRecorder = Callable[[str], None]
NextSessionAvailability = Callable[[int, bool], str | None]
SettingsProvider = Callable[[], tuple[bool, int]]


class TaskManager:
    def __init__(
        self,
        db: Database,
        download_root: Path,
        max_workers: int = 2,
        session_provider: SessionProvider | None = None,
        session_invalidator: SessionInvalidator | None = None,
        session_cooldown: SessionCooldown | None = None,
        session_failure_recorder: SessionFailureRecorder | None = None,
        session_success_recorder: SessionSuccessRecorder | None = None,
        next_session_availability: NextSessionAvailability | None = None,
        settings_provider: SettingsProvider | None = None,
    ):
        self.db = db
        self.download_root = download_root
        self.max_workers = min(max_workers, 5)
        self._executor = ThreadPoolExecutor(max_workers=5, thread_name_prefix="download-task")
        self._queue_event = asyncio.Event()
        self._stop_event = asyncio.Event()
        self._cancelled: Set[int] = set()
        self._subscribers: Set[asyncio.Queue[EventMessage]] = set()
        self._loop: asyncio.AbstractEventLoop | None = None
        self._dispatcher_task: asyncio.Task[None] | None = None
        self._running_tasks = 0
        self._session_provider = session_provider or (lambda _interval, _enabled: (None, None))
        self._session_invalidator = session_invalidator
        self._session_cooldown = session_cooldown
        self._session_failure_recorder = session_failure_recorder
        self._session_success_recorder = session_success_recorder
        self._next_session_availability = next_session_availability
        self._settings_provider = settings_provider or (lambda: (True, 120))
        self.stability = StabilityController()

    async def start(self) -> None:
        self._loop = asyncio.get_running_loop()
        self.download_root.mkdir(parents=True, exist_ok=True)
        self.db.reset_interrupted_tasks()
        self._dispatcher_task = asyncio.create_task(self._dispatcher())
        self._queue_event.set()

    async def stop(self) -> None:
        self._stop_event.set()
        self._queue_event.set()
        if self._dispatcher_task:
            await self._dispatcher_task
        self._executor.shutdown(wait=False, cancel_futures=True)

    async def create_task(self, data: TaskCreate) -> Task:
        task = self.db.create_task(data)
        await self.publish_task(task)
        self._queue_event.set()
        return task

    async def update_runtime(self, download_root: Path | None = None, max_workers: int | None = None) -> None:
        if download_root is not None:
            self.download_root = download_root
            self.download_root.mkdir(parents=True, exist_ok=True)
        if max_workers is not None:
            self.max_workers = max(1, min(max_workers, 5))
        self._queue_event.set()

    async def cancel_task(self, task_id: int) -> Task | None:
        self._cancelled.add(task_id)
        task = self.db.get_task(task_id)
        if task and task.status == "queued":
            task = self.db.update_task_status(task_id, "cancelled")
            event = self.db.add_event(task_id, "status", "Task cancelled")
            if task:
                await self.publish_task(task)
            await self.publish_event(event)
        elif task and task.status == "running":
            event = self.db.add_event(task_id, "status", "Cancellation requested")
            await self.publish_event(event)
        return self.db.get_task(task_id)

    async def retry_task(self, task_id: int) -> Task | None:
        self._cancelled.discard(task_id)
        task = self.db.retry_task(task_id)
        if task:
            await self.publish_task(task)
            self._queue_event.set()
        return task

    async def subscribe(self) -> asyncio.Queue[EventMessage]:
        queue: asyncio.Queue[EventMessage] = asyncio.Queue(maxsize=500)
        self._subscribers.add(queue)
        return queue

    def unsubscribe(self, queue: asyncio.Queue[EventMessage]) -> None:
        self._subscribers.discard(queue)

    async def publish_task(self, task: Task) -> None:
        await self._publish(EventMessage(type="task", payload=task.model_dump()))

    async def publish_event(self, event: TaskEvent) -> None:
        await self._publish(EventMessage(type="event", payload=event.model_dump()))

    async def _publish(self, message: EventMessage) -> None:
        stale = []
        for queue in self._subscribers:
            try:
                queue.put_nowait(message)
            except asyncio.QueueFull:
                stale.append(queue)
        for queue in stale:
            self.unsubscribe(queue)

    async def _dispatcher(self) -> None:
        while not self._stop_event.is_set():
            await self._queue_event.wait()
            self._queue_event.clear()
            while not self._stop_event.is_set() and self._running_tasks < self.stability.active_worker_limit(self.max_workers):
                task = self.db.claim_next_queued_task()
                if not task:
                    break
                self._running_tasks += 1
                asyncio.create_task(self._run_task(task))

    async def _run_task(self, task: Task) -> None:
        try:
            if task.id in self._cancelled:
                updated = self.db.update_task_status(task.id, "cancelled")
                if updated:
                    await self.publish_task(updated)
                return
            event = self.db.add_event(task.id, "status", "Task started")
            await self.publish_task(task)
            await self.publish_event(event)
            guard_enabled, min_interval_seconds = self._settings_provider()
            session_username, session_file = self._session_provider(min_interval_seconds, guard_enabled)
            if _requires_login(task) and not session_username:
                next_available_at = self._next_session_availability(min_interval_seconds, guard_enabled) if self._next_session_availability else None
                if next_available_at:
                    updated = self.db.schedule_retry(task.id, "Waiting for an account to leave cooldown.", "rate_limit", next_available_at)
                    event = self.db.add_event(task.id, "session", f"All accounts are cooling down. Retrying at {next_available_at}.")
                else:
                    updated = self.db.update_task_status(task.id, "failed", "No valid Instagram account is available.", "login_required")
                    event = self.db.add_event(task.id, "session", "No valid Instagram account is available.")
                if updated:
                    await self.publish_task(updated)
                await self.publish_event(event)
                return
            if session_username:
                event = self.db.add_event(task.id, "session", f"Using Instagram account @{session_username}")
                await self.publish_event(event)
            loop = asyncio.get_running_loop()
            await loop.run_in_executor(
                self._executor,
                run_download_task,
                task,
                self.download_root,
                self._thread_emit(task.id),
                lambda: task.id in self._cancelled,
                session_username,
                session_file,
            )
            if task.id in self._cancelled:
                updated = self.db.update_task_status(task.id, "cancelled")
                event = self.db.add_event(task.id, "status", "Task cancelled")
            else:
                updated = self.db.update_task_status(task.id, "completed")
                event = self.db.add_event(task.id, "status", "Task completed")
                if session_username and self._session_success_recorder:
                    self._session_success_recorder(session_username)
            if updated:
                await self.publish_task(updated)
            await self.publish_event(event)
        except InterruptedError as exc:
            updated = self.db.update_task_status(task.id, "cancelled", str(exc), "cancelled")
            event = self.db.add_event(task.id, "status", "Task cancelled")
            if updated:
                await self.publish_task(updated)
            await self.publish_event(event)
        except Exception as exc:  # pylint:disable=broad-exception-caught
            error_code = classify_error(exc)
            latest = self.db.get_task(task.id) or task
            delay = retry_delay_seconds(error_code, latest.attempt_count)
            if error_code == "rate_limit":
                cooldown_until = self.stability.activate_cooldown(delay or 600, str(exc))
                event = self.db.add_event(task.id, "rate_limit", f"Rate limit detected. Cooling down until {cooldown_until}.")
                await self.publish_event(event)
                if session_username and self._session_cooldown:
                    self._session_cooldown(session_username, str(exc))
            if error_code in {"login_required", "login_expired"} and session_username and self._session_invalidator:
                self._session_invalidator(session_username, str(exc))
                event = self.db.add_event(task.id, "session", f"Instagram account @{session_username} marked invalid: {exc}")
                await self.publish_event(event)
            if error_code in {"network", "timeout"} and session_username and self._session_failure_recorder:
                self._session_failure_recorder(session_username, error_code, str(exc))
            if delay is not None:
                next_retry_at = retry_at(delay)
                updated = self.db.schedule_retry(task.id, str(exc), error_code, next_retry_at)
                event = self.db.add_event(task.id, "retry", f"{error_code} error. Retrying at {next_retry_at}.")
            else:
                updated = self.db.update_task_status(task.id, "failed", str(exc), error_code)
                event = self.db.add_event(task.id, "error", f"{error_code}: {exc}")
            if updated:
                await self.publish_task(updated)
            await self.publish_event(event)
        finally:
            self._running_tasks = max(0, self._running_tasks - 1)
            self._queue_event.set()

    def _thread_emit(self, task_id: int):
        def emit(level: str, message: str) -> None:
            event = self.db.add_event(task_id, level, message)
            if self._loop and not self._loop.is_closed():
                coroutine = self.publish_event(event)
                try:
                    asyncio.run_coroutine_threadsafe(coroutine, self._loop)
                except RuntimeError:
                    coroutine.close()

        return emit


def _requires_login(task: Task) -> bool:
    login_targets = {"feed", "stories", "saved"}
    options = task.options
    return (
        task.target_type in login_targets
        or options.download_stories
        or options.download_highlights
        or options.download_geotags
    )
