from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field


TaskStatus = Literal["queued", "running", "cancelled", "failed", "completed"]
CreatorStatus = Literal["pending", "ready", "error"]
ErrorCode = Literal[
    "network",
    "timeout",
    "rate_limit",
    "login_required",
    "login_expired",
    "not_found",
    "private_no_access",
    "disk_error",
    "cancelled",
    "unknown",
]
TargetType = Literal["profile", "hashtag", "shortcode", "feed", "stories", "saved"]


class DownloadOptions(BaseModel):
    download_pictures: bool = True
    download_videos: bool = True
    download_video_thumbnails: bool = True
    download_profile_pic: bool = True
    download_posts: bool = True
    download_stories: bool = False
    download_highlights: bool = False
    download_tagged: bool = False
    download_reels: bool = False
    download_igtv: bool = False
    download_comments: bool = False
    download_geotags: bool = False
    save_metadata: bool = True
    compress_json: bool = True
    fast_update: bool = False
    max_count: Optional[int] = Field(default=None, ge=1)
    sanitize_paths: bool = True


class TaskCreate(BaseModel):
    target_type: TargetType = "profile"
    targets: List[str] = Field(min_length=1)
    options: DownloadOptions = Field(default_factory=DownloadOptions)


class Task(BaseModel):
    id: int
    status: TaskStatus
    target_type: TargetType
    targets: List[str]
    options: DownloadOptions
    error: Optional[str] = None
    error_code: Optional[ErrorCode] = None
    attempt_count: int = 0
    next_retry_at: Optional[str] = None
    created_at: str
    updated_at: str
    started_at: Optional[str] = None
    finished_at: Optional[str] = None


class BatchTaskResponse(BaseModel):
    tasks: List[Task]
    created_count: int


class CreatorCreate(BaseModel):
    username: str = Field(min_length=1, max_length=64)


class Creator(BaseModel):
    id: int
    username: str
    full_name: Optional[str] = None
    avatar_url: Optional[str] = None
    biography: Optional[str] = None
    is_private: bool = False
    is_verified: bool = False
    followers: Optional[int] = None
    followees: Optional[int] = None
    mediacount: Optional[int] = None
    status: CreatorStatus = "pending"
    error: Optional[str] = None
    created_at: str
    updated_at: str
    refreshed_at: Optional[str] = None


class TaskEvent(BaseModel):
    id: int
    task_id: int
    level: Literal["info", "error", "status", "session", "retry", "rate_limit", "health"]
    message: str
    created_at: str


class FileItem(BaseModel):
    path: str
    name: str
    size: int
    modified_at: str
    is_dir: bool = False


class MediaItem(BaseModel):
    path: str
    name: str
    size: int
    modified_at: str
    media_type: Literal["image", "video"]
    mime_type: str


class AppConfig(BaseModel):
    max_concurrent_tasks: int
    download_root: str
    data_root: str


class AppSettings(BaseModel):
    max_concurrent_tasks: int = Field(default=2, ge=1, le=5)
    download_root: str
    default_max_count: Optional[int] = Field(default=1000, ge=1)
    show_debug_logs: bool = True
    desktop_notifications: bool = True
    theme: Literal["light", "dark", "system"] = "light"
    stability_guard_enabled: bool = True
    account_min_interval_seconds: int = Field(default=120, ge=0, le=3600)


class AppSettingsUpdate(BaseModel):
    max_concurrent_tasks: Optional[int] = Field(default=None, ge=1, le=5)
    download_root: Optional[str] = None
    default_max_count: Optional[int] = Field(default=None, ge=1)
    show_debug_logs: Optional[bool] = None
    desktop_notifications: Optional[bool] = None
    theme: Optional[Literal["light", "dark", "system"]] = None
    stability_guard_enabled: Optional[bool] = None
    account_min_interval_seconds: Optional[int] = Field(default=None, ge=0, le=3600)


class SystemInfo(BaseModel):
    engine_version: str
    database_size: int
    storage_used: int
    data_root: str
    download_root: str
    max_concurrent_tasks: int
    running_tasks: int
    total_tasks: int


class AccountStatus(BaseModel):
    is_connected: bool = False
    username: Optional[str] = None
    session_file: Optional[str] = None
    updated_at: Optional[str] = None
    pending_two_factor: bool = False
    message: Optional[str] = None


class AccountRecord(BaseModel):
    username: str
    session_file: str
    is_connected: bool = False
    is_default: bool = False
    updated_at: Optional[str] = None
    last_used_at: Optional[str] = None
    last_test_status: Optional[Literal["unknown", "valid", "invalid"]] = "unknown"
    cooldown_until: Optional[str] = None
    failure_count: int = 0
    last_error: Optional[str] = None
    message: Optional[str] = None


class AccountListResponse(BaseModel):
    accounts: List[AccountRecord] = Field(default_factory=list)
    default_username: Optional[str] = None
    available_count: int = 0


class LoginRequest(BaseModel):
    username: str
    password: str


class TwoFactorRequest(BaseModel):
    username: str
    code: str


class CookieImportRequest(BaseModel):
    username: Optional[str] = None
    cookies: str


class BrowserCookieImportRequest(BaseModel):
    browser: Literal["brave", "chrome", "chromium", "edge", "firefox", "librewolf", "opera", "opera_gx", "vivaldi"]
    cookie_file: Optional[str] = None


class HealthStatus(BaseModel):
    ok: bool
    database_writable: bool
    download_root_writable: bool
    free_disk_bytes: int
    session: AccountStatus
    running_tasks: int
    queued_tasks: int
    cooling_down: bool = False
    cooldown_until: Optional[str] = None
    message: Optional[str] = None


class TaskResponse(BaseModel):
    task: Task
    events: List[TaskEvent] = Field(default_factory=list)


class EventMessage(BaseModel):
    type: Literal["task", "event", "health"]
    payload: Dict[str, Any]
