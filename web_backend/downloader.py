from __future__ import annotations

import os
import threading
from pathlib import Path
from typing import Callable, Iterable, List

from instaloader import Instaloader, InstaloaderException, Post
from instaloader.__main__ import _main

from .database import normalize_username
from .models import Task


LogFn = Callable[[str, str], None]
CancelFn = Callable[[], bool]


def run_download_task(
    task: Task,
    download_root: Path,
    emit: LogFn,
    is_cancelled: CancelFn,
    session_username: str | None = None,
    session_file: str | None = None,
) -> None:
    target_dir = download_root / f"task-{task.id}"
    target_dir.mkdir(parents=True, exist_ok=True)
    options = task.options
    loader = Instaloader(
        quiet=False,
        dirname_pattern=str(target_dir / "{target}"),
        download_pictures=options.download_pictures,
        download_videos=options.download_videos,
        download_video_thumbnails=options.download_video_thumbnails,
        download_geotags=options.download_geotags,
        download_comments=options.download_comments,
        save_metadata=options.save_metadata,
        compress_json=options.compress_json,
        sanitize_paths=options.sanitize_paths,
    )
    loader.context.raise_all_errors = True
    loader.context.log = lambda *msg, sep="", end="\n", flush=False: emit("info", sep.join(str(item) for item in msg))
    loader.context.error = lambda msg, repeat_at_end=True: emit("error", str(msg))
    if session_username and session_file:
        loader.load_session_from_file(session_username, session_file)
        emit("info", f"Loaded Instagram session for {session_username}")
    old_cwd = Path.cwd()
    try:
        emit("info", f"Saving files under {target_dir}")
        os.chdir(download_root)
        _run_by_target_type(task, loader, is_cancelled)
    finally:
        loader.close()
        os.chdir(old_cwd)


def _run_by_target_type(task: Task, loader: Instaloader, is_cancelled: CancelFn) -> None:
    options = task.options
    targets = _normalize_targets(task.target_type, task.targets)
    if task.target_type in {"profile", "hashtag", "feed", "stories", "saved"}:
        exit_code = _main(
            loader,
            targets,
            download_profile_pic=options.download_profile_pic,
            download_posts=options.download_posts,
            download_stories=options.download_stories,
            download_highlights=options.download_highlights,
            download_tagged=options.download_tagged,
            download_reels=options.download_reels,
            download_igtv=options.download_igtv,
            fast_update=options.fast_update,
            max_count=options.max_count,
        )
        if int(exit_code) not in (0, 1):
            raise InstaloaderException(f"Download exited with code {int(exit_code)}")
        return

    for shortcode in targets:
        _raise_if_cancelled(is_cancelled)
        post = Post.from_shortcode(loader.context, shortcode)
        loader.download_post(post, target=shortcode)


def _normalize_targets(target_type: str, raw_targets: Iterable[str]) -> List[str]:
    targets = [target.strip() for target in raw_targets if target.strip()]
    if target_type == "profile":
        normalized_targets = [normalize_username(target) for target in targets]
        invalid_targets = [target for target, normalized in zip(targets, normalized_targets) if not normalized]
        if invalid_targets:
            raise ValueError(f"Invalid Instagram profile target: {invalid_targets[0]}")
        return normalized_targets
    if target_type == "hashtag":
        return [target if target.startswith("#") else f"#{target}" for target in targets]
    if target_type == "feed":
        return [":feed"]
    if target_type == "stories":
        return [":stories"]
    if target_type == "saved":
        return [":saved"]
    if target_type == "shortcode":
        return [target[1:] if target.startswith("-") else target for target in targets]
    return targets


def _raise_if_cancelled(is_cancelled: CancelFn) -> None:
    if is_cancelled():
        raise InterruptedError("Task cancelled")
