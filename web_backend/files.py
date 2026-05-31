from __future__ import annotations

import mimetypes
from datetime import datetime, timezone
from pathlib import Path
from typing import List

from .models import FileItem, MediaItem


IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp"}
VIDEO_EXTENSIONS = {".mp4", ".mov", ".m4v", ".webm"}
MEDIA_EXTENSIONS = IMAGE_EXTENSIONS | VIDEO_EXTENSIONS


def safe_resolve(root: Path, relative_path: str) -> Path:
    root = root.resolve()
    target = (root / relative_path).resolve()
    if root != target and root not in target.parents:
        raise ValueError("Path is outside download root")
    return target


def list_files(root: Path, relative_path: str = "") -> List[FileItem]:
    base = safe_resolve(root, relative_path)
    if not base.exists():
        return []
    if base.is_file():
        entries = [base]
    else:
        entries = sorted(base.iterdir(), key=lambda item: (not item.is_dir(), item.name.lower()))
    items: List[FileItem] = []
    for entry in entries:
        stat = entry.stat()
        rel = entry.relative_to(root.resolve()).as_posix()
        items.append(
            FileItem(
                path=rel,
                name=entry.name,
                size=stat.st_size,
                modified_at=datetime.fromtimestamp(stat.st_mtime, timezone.utc).isoformat(),
                is_dir=entry.is_dir(),
            )
        )
    return items


def list_media(root: Path, relative_path: str = "", limit: int = 60) -> List[MediaItem]:
    base = safe_resolve(root, relative_path)
    if not base.exists():
        return []
    entries = [base] if base.is_file() else [item for item in base.rglob("*") if item.is_file()]
    media_entries = [item for item in entries if item.suffix.lower() in MEDIA_EXTENSIONS]
    media_entries.sort(key=lambda item: item.stat().st_mtime, reverse=True)
    items: List[MediaItem] = []
    for entry in media_entries[:limit]:
        stat = entry.stat()
        rel = entry.relative_to(root.resolve()).as_posix()
        suffix = entry.suffix.lower()
        media_type = "image" if suffix in IMAGE_EXTENSIONS else "video"
        items.append(
            MediaItem(
                path=rel,
                name=entry.name,
                size=stat.st_size,
                modified_at=datetime.fromtimestamp(stat.st_mtime, timezone.utc).isoformat(),
                media_type=media_type,
                mime_type=mimetypes.guess_type(entry.name)[0] or ("image/jpeg" if media_type == "image" else "video/mp4"),
            )
        )
    return items
