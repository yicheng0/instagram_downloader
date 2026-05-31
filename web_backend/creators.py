from __future__ import annotations

import re
import shutil
import subprocess
import sys
import threading
from pathlib import Path
from typing import Any, Dict

from instaloader import Instaloader, Profile


ANONYMOUS_PROFILE_UNAVAILABLE = "匿名识别暂时受限，请稍后重试或在账号池添加账号。"
_BROWSER_TIMEOUT_MS = 60_000
_CHROMIUM_INSTALL_LOCK = threading.Lock()
_chromium_install_attempted = False
_chromium_install_error: str | None = None


class CreatorProfileNotFound(Exception):
    pass


class AnonymousProfileUnavailable(Exception):
    pass


def fetch_creator_profile(username: str, session: tuple[str | None, str | None] = (None, None)) -> Dict[str, Any]:
    try:
        return _fetch_creator_profile_with_instaloader(username, session)
    except Exception:  # pylint:disable=broad-exception-caught
        try:
            return fetch_public_profile_with_browser(username)
        except CreatorProfileNotFound:
            raise
        except AnonymousProfileUnavailable as browser_error:
            raise AnonymousProfileUnavailable(ANONYMOUS_PROFILE_UNAVAILABLE) from browser_error


def _fetch_creator_profile_with_instaloader(
    username: str,
    session: tuple[str | None, str | None] = (None, None),
) -> Dict[str, Any]:
    loader = Instaloader(quiet=True, sleep=False, max_connection_attempts=1, request_timeout=15.0)
    session_username, session_file = session
    try:
        if session_username and session_file:
            loader.load_session_from_file(session_username, session_file)
        profile = Profile.from_username(loader.context, username)
        return {
            "username": profile.username,
            "full_name": profile.full_name,
            "avatar_url": profile.profile_pic_url,
            "biography": profile.biography,
            "is_private": profile.is_private,
            "is_verified": profile.is_verified,
            "followers": profile.followers,
            "followees": profile.followees,
            "mediacount": profile.mediacount,
        }
    finally:
        loader.close()


def fetch_public_profile_with_browser(username: str) -> Dict[str, Any]:
    try:
        sync_playwright = _load_sync_playwright()
        with sync_playwright() as playwright:
            browser = _launch_browser(playwright)
            try:
                context = browser.new_context(locale="en-US")
                try:
                    page = context.new_page()
                    page.goto(
                        f"https://www.instagram.com/{username}/",
                        wait_until="domcontentloaded",
                        timeout=_BROWSER_TIMEOUT_MS,
                    )
                    page.wait_for_function(
                        """
                        () => document.title.toLowerCase().includes("profile isn't available")
                          || document.querySelector('meta[property="og:title"]')
                        """,
                        timeout=2_000,
                    )
                    title = page.title()
                    metadata = page.locator("meta").evaluate_all(
                        """
                        (elements) => Object.fromEntries(
                          elements
                            .map((element) => [
                              element.getAttribute("property") || element.getAttribute("name"),
                              element.getAttribute("content")
                            ])
                            .filter(([key, value]) => key && value)
                        )
                        """
                    )
                finally:
                    context.close()
            finally:
                browser.close()
    except CreatorProfileNotFound:
        raise
    except Exception as exc:  # pylint:disable=broad-exception-caught
        raise AnonymousProfileUnavailable(str(exc)) from exc
    return _parse_public_profile_metadata(username, title, metadata)


def _load_sync_playwright():
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        raise AnonymousProfileUnavailable("Playwright 未安装，请重启 Web 服务完成依赖安装。") from exc
    return sync_playwright


def _launch_browser(playwright):
    chrome_path = _find_local_chrome()
    if chrome_path:
        try:
            return playwright.chromium.launch(headless=True, executable_path=str(chrome_path))
        except Exception:  # pylint:disable=broad-exception-caught
            pass
    try:
        return playwright.chromium.launch(headless=True)
    except Exception:  # pylint:disable=broad-exception-caught
        _install_chromium_once()
    try:
        return playwright.chromium.launch(headless=True)
    except Exception as exc:  # pylint:disable=broad-exception-caught
        raise AnonymousProfileUnavailable("无法启动 Chrome 或 Playwright Chromium。") from exc


def _find_local_chrome() -> Path | None:
    executable = shutil.which("chrome") or shutil.which("google-chrome") or shutil.which("chromium")
    if executable:
        return Path(executable)
    candidates = [
        Path("C:/Program Files/Google/Chrome/Application/chrome.exe"),
        Path("C:/Program Files (x86)/Google/Chrome/Application/chrome.exe"),
        Path.home() / "AppData/Local/Google/Chrome/Application/chrome.exe",
        Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"),
    ]
    return next((candidate for candidate in candidates if candidate.exists()), None)


def _install_chromium_once() -> None:
    global _chromium_install_attempted, _chromium_install_error  # pylint:disable=global-statement
    with _CHROMIUM_INSTALL_LOCK:
        if _chromium_install_attempted:
            if _chromium_install_error:
                raise AnonymousProfileUnavailable(_chromium_install_error)
            return
        _chromium_install_attempted = True
        try:
            subprocess.run(
                [sys.executable, "-m", "playwright", "install", "chromium"],
                check=True,
                capture_output=True,
                text=True,
                timeout=600,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            _chromium_install_error = "自动安装 Playwright Chromium 失败。"
            raise AnonymousProfileUnavailable(_chromium_install_error) from exc


def _parse_public_profile_metadata(username: str, title: str, metadata: Dict[str, str]) -> Dict[str, Any]:
    if "profile isn't available" in title.lower():
        raise CreatorProfileNotFound(f"Profile {username} does not exist.")
    og_title = metadata.get("og:title", "")
    title_match = re.match(r"^(.*?) \(@([A-Za-z0-9._]+)\)", og_title)
    if not title_match or title_match.group(2).lower() != username.lower():
        raise AnonymousProfileUnavailable("Instagram 公开页没有返回可识别的博主资料。")

    description = metadata.get("description", "")
    stats_description = metadata.get("og:description", "") or description
    result: Dict[str, Any] = {
        "username": title_match.group(2),
        "full_name": title_match.group(1).strip(),
    }
    if metadata.get("og:image"):
        result["avatar_url"] = metadata["og:image"]
    stats_match = re.search(
        r"([\d,.]+[KMB]?) Followers,\s*([\d,.]+[KMB]?) Following,\s*([\d,.]+[KMB]?) Posts",
        stats_description,
        re.IGNORECASE,
    )
    if stats_match:
        result.update(
            {
                "followers": _parse_compact_number(stats_match.group(1)),
                "followees": _parse_compact_number(stats_match.group(2)),
                "mediacount": _parse_compact_number(stats_match.group(3)),
            }
        )
    biography_match = re.search(r'on Instagram:\s*["“](.*?)["”]\s*$', description, re.DOTALL)
    if biography_match:
        result["biography"] = biography_match.group(1)
    return result


def _parse_compact_number(value: str) -> int:
    normalized = value.replace(",", "").strip().upper()
    multiplier = 1
    if normalized.endswith("K"):
        multiplier = 1_000
    elif normalized.endswith("M"):
        multiplier = 1_000_000
    elif normalized.endswith("B"):
        multiplier = 1_000_000_000
    if multiplier != 1:
        normalized = normalized[:-1]
    return int(float(normalized) * multiplier)
