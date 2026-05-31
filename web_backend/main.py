from __future__ import annotations

import json
from pathlib import Path
from typing import AsyncIterator

from fastapi import FastAPI, File, Form, HTTPException, Query, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse

from instaloader import __version__ as instaloader_version

from .account import AccountManager
from .database import Database
from .files import list_files, safe_resolve
from .models import (
    AccountStatus,
    AppConfig,
    AppSettings,
    AppSettingsUpdate,
    BrowserCookieImportRequest,
    CookieImportRequest,
    HealthStatus,
    LoginRequest,
    SystemInfo,
    TaskCreate,
    TaskResponse,
    TwoFactorRequest,
)
from .stability import health_status, validate_preflight
from .task_manager import TaskManager


ROOT = Path(__file__).resolve().parents[1]
DATA_ROOT = ROOT / "web_data"
DOWNLOAD_ROOT = DATA_ROOT / "downloads"
DB_PATH = DATA_ROOT / "app.sqlite3"
MAX_CONCURRENT_TASKS = 2

db = Database(DB_PATH)
account_manager = AccountManager(DATA_ROOT / "sessions")
initial_settings = db.get_settings(DOWNLOAD_ROOT)
manager = TaskManager(
    db,
    Path(initial_settings.download_root),
    max_workers=initial_settings.max_concurrent_tasks,
    session_provider=account_manager.session_for_downloads,
)

app = FastAPI(title="Instagram Downloader Web GUI")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
async def startup() -> None:
    await manager.start()


@app.on_event("shutdown")
async def shutdown() -> None:
    await manager.stop()


@app.get("/api/config", response_model=AppConfig)
def get_config() -> AppConfig:
    settings = db.get_settings(DOWNLOAD_ROOT)
    return AppConfig(
        max_concurrent_tasks=settings.max_concurrent_tasks,
        download_root=settings.download_root,
        data_root=str(DATA_ROOT),
    )


@app.post("/api/tasks")
async def create_task(payload: TaskCreate):
    settings = db.get_settings(DOWNLOAD_ROOT)
    try:
        validate_preflight(db, Path(settings.download_root))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if _requires_login(payload) and not account_manager.status().is_connected:
        raise HTTPException(status_code=400, detail="该任务需要先连接 Instagram 账号。")
    task = await manager.create_task(payload)
    return task


@app.get("/api/settings", response_model=AppSettings)
def get_settings() -> AppSettings:
    return db.get_settings(DOWNLOAD_ROOT)


@app.patch("/api/settings", response_model=AppSettings)
async def update_settings(payload: AppSettingsUpdate) -> AppSettings:
    values = payload.model_dump(exclude_unset=True)
    if "download_root" in values and values["download_root"]:
        values["download_root"] = str(Path(values["download_root"]).expanduser().resolve())
    settings = db.update_settings(values, DOWNLOAD_ROOT)
    await manager.update_runtime(Path(settings.download_root), settings.max_concurrent_tasks)
    return settings


@app.get("/api/system", response_model=SystemInfo)
def system_info() -> SystemInfo:
    settings = db.get_settings(DOWNLOAD_ROOT)
    download_root = Path(settings.download_root)
    return SystemInfo(
        engine_version=f"v{instaloader_version}",
        database_size=DB_PATH.stat().st_size if DB_PATH.exists() else 0,
        storage_used=_folder_size(download_root),
        data_root=str(DATA_ROOT),
        download_root=str(download_root),
        max_concurrent_tasks=settings.max_concurrent_tasks,
        running_tasks=db.count_running_tasks(),
        total_tasks=db.count_tasks(),
    )


@app.get("/api/account", response_model=AccountStatus)
def account_status() -> AccountStatus:
    return account_manager.status()


@app.get("/api/session/status", response_model=AccountStatus)
def session_status() -> AccountStatus:
    return account_manager.status()


@app.post("/api/session/test", response_model=AccountStatus)
def session_test() -> AccountStatus:
    return account_manager.test()


@app.post("/api/account/login", response_model=AccountStatus)
def account_login(payload: LoginRequest) -> AccountStatus:
    try:
        return account_manager.login(payload.username.strip(), payload.password)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/account/2fa", response_model=AccountStatus)
def account_two_factor(payload: TwoFactorRequest) -> AccountStatus:
    try:
        return account_manager.two_factor(payload.username.strip(), payload.code.strip())
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/account/session-file", response_model=AccountStatus)
async def account_session_file(username: str = Form(...), file: UploadFile = File(...)) -> AccountStatus:
    try:
        return account_manager.import_session_file(username.strip(), await file.read())
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/account/cookies", response_model=AccountStatus)
def account_cookies(payload: CookieImportRequest) -> AccountStatus:
    try:
        return account_manager.import_cookie_text(payload.cookies, payload.username)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/session/import-cookies", response_model=AccountStatus)
def session_import_cookies(payload: CookieImportRequest) -> AccountStatus:
    return account_cookies(payload)


@app.post("/api/session/import-browser", response_model=AccountStatus)
def session_import_browser(payload: BrowserCookieImportRequest) -> AccountStatus:
    try:
        return account_manager.import_browser_cookies(payload.browser, payload.cookie_file)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.delete("/api/account/session", response_model=AccountStatus)
def account_logout() -> AccountStatus:
    return account_manager.clear()


@app.get("/api/health", response_model=HealthStatus)
def health() -> HealthStatus:
    settings = db.get_settings(DOWNLOAD_ROOT)
    return health_status(
        db,
        Path(settings.download_root),
        DATA_ROOT,
        account_manager.status(),
        cooling_down=manager.stability.is_cooling_down(),
        cooldown_until=manager.stability.cooldown_until,
    )


@app.get("/api/tasks")
def list_tasks():
    return db.list_tasks()


@app.get("/api/tasks/{task_id}", response_model=TaskResponse)
def get_task(task_id: int):
    task = db.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    return TaskResponse(task=task, events=db.list_events(task_id))


@app.post("/api/tasks/{task_id}/cancel")
async def cancel_task(task_id: int):
    task = await manager.cancel_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    return task


@app.post("/api/tasks/{task_id}/retry")
async def retry_task(task_id: int):
    task = await manager.retry_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    return task


@app.get("/api/events")
async def events() -> StreamingResponse:
    async def stream() -> AsyncIterator[str]:
        for event in db.latest_events(50):
            yield f"data: {json.dumps({'type': 'event', 'payload': event.model_dump()})}\n\n"
        queue = await manager.subscribe()
        try:
            while True:
                message = await queue.get()
                yield f"data: {message.model_dump_json()}\n\n"
        finally:
            manager.unsubscribe(queue)

    return StreamingResponse(stream(), media_type="text/event-stream")


@app.get("/api/files")
def files(path: str = Query(default="")):
    settings = db.get_settings(DOWNLOAD_ROOT)
    try:
        return list_files(Path(settings.download_root), path)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/files/download")
def download_file(path: str):
    settings = db.get_settings(DOWNLOAD_ROOT)
    try:
        target = safe_resolve(Path(settings.download_root), path)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not target.exists() or not target.is_file():
        raise HTTPException(status_code=404, detail="File not found")
    return FileResponse(target, filename=target.name)


def _requires_login(payload: TaskCreate) -> bool:
    login_targets = {"feed", "stories", "saved"}
    login_options = payload.options.download_stories or payload.options.download_highlights or payload.options.download_geotags
    return payload.target_type in login_targets or login_options


def _folder_size(path: Path) -> int:
    if not path.exists():
        return 0
    total = 0
    for item in path.rglob("*"):
        if item.is_file():
            total += item.stat().st_size
    return total
