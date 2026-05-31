from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import List

from .models import FileItem


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
