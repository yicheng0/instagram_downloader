from __future__ import annotations

import json
import pickle
from dataclasses import dataclass
from datetime import datetime, timezone
from http.cookiejar import Cookie
from pathlib import Path
from typing import Dict, Optional

from instaloader import BadCredentialsException, Instaloader, InstaloaderException, LoginException
from instaloader.exceptions import TwoFactorAuthRequiredException

from .models import AccountStatus


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class PendingLogin:
    username: str
    loader: Instaloader


class AccountManager:
    def __init__(self, session_root: Path):
        self.session_root = session_root
        self.metadata_path = session_root / "account.json"
        self.pending_login: Optional[PendingLogin] = None
        self.session_root.mkdir(parents=True, exist_ok=True)

    def status(self) -> AccountStatus:
        metadata = self._read_metadata()
        session_file = metadata.get("session_file")
        return AccountStatus(
            is_connected=bool(metadata.get("username") and session_file and (self.session_root / session_file).exists()),
            username=metadata.get("username"),
            session_file=session_file,
            updated_at=metadata.get("updated_at"),
            pending_two_factor=self.pending_login is not None,
        )

    def login(self, username: str, password: str) -> AccountStatus:
        loader = Instaloader(quiet=True)
        try:
            loader.login(username, password)
        except TwoFactorAuthRequiredException:
            self.pending_login = PendingLogin(username=username, loader=loader)
            return AccountStatus(
                is_connected=False,
                username=username,
                pending_two_factor=True,
                message="需要两步验证码。",
            )
        except (BadCredentialsException, LoginException, InstaloaderException) as exc:
            loader.close()
            raise ValueError(str(exc)) from exc
        try:
            self._save_loader_session(loader, username)
            return self.status()
        finally:
            loader.close()

    def two_factor(self, username: str, code: str) -> AccountStatus:
        if not self.pending_login or self.pending_login.username != username:
            raise ValueError("没有待验证的两步登录。")
        loader = self.pending_login.loader
        try:
            loader.two_factor_login(code)
            self._save_loader_session(loader, username)
            self.pending_login = None
            return self.status()
        except (BadCredentialsException, LoginException, InstaloaderException) as exc:
            raise ValueError(str(exc)) from exc
        finally:
            loader.close()

    def import_session_file(self, username: str, payload: bytes) -> AccountStatus:
        session_data = pickle.loads(payload)
        if not isinstance(session_data, dict):
            raise ValueError("Session 文件格式无效。")
        return self.import_cookies(username, session_data)

    def import_cookie_text(self, text: str, username: Optional[str] = None) -> AccountStatus:
        cookies = parse_cookie_text(text)
        if not cookies:
            raise ValueError("没有解析到 Instagram Cookie。")
        return self.import_cookies(username, cookies)

    def import_browser_cookies(self, browser: str, cookie_file: Optional[str] = None) -> AccountStatus:
        try:
            import browser_cookie3
        except ImportError as exc:
            raise ValueError("需要安装 browser_cookie3 才能从浏览器导入 Cookie。") from exc
        supported = {
            "brave": browser_cookie3.brave,
            "chrome": browser_cookie3.chrome,
            "chromium": browser_cookie3.chromium,
            "edge": browser_cookie3.edge,
            "firefox": browser_cookie3.firefox,
            "librewolf": browser_cookie3.librewolf,
            "opera": browser_cookie3.opera,
            "opera_gx": browser_cookie3.opera_gx,
            "vivaldi": browser_cookie3.vivaldi,
        }
        loader = supported.get(browser)
        if loader is None:
            raise ValueError("不支持的浏览器。")
        cookies = {
            cookie.name: cookie.value
            for cookie in loader(cookie_file=cookie_file)
            if "instagram" in cookie.domain
        }
        if not cookies:
            raise ValueError("没有从浏览器中找到 Instagram Cookie。")
        return self.import_cookies(None, cookies)

    def import_cookies(self, username: Optional[str], cookies: Dict[str, str]) -> AccountStatus:
        loader = Instaloader(quiet=True)
        try:
            loader.context.update_cookies(cookies)
            detected_username = loader.test_login()
            if not detected_username and username:
                loader.load_session(username, cookies)
                detected_username = loader.test_login()
            if not detected_username:
                raise ValueError("Cookie 无法通过 Instagram 登录校验。")
            loader.context.username = detected_username
            self._save_loader_session(loader, detected_username)
            return self.status()
        finally:
            loader.close()

    def clear(self) -> AccountStatus:
        metadata = self._read_metadata()
        session_file = metadata.get("session_file")
        if session_file:
            target = self.session_root / session_file
            if target.exists():
                target.unlink()
        if self.metadata_path.exists():
            self.metadata_path.unlink()
        if self.pending_login:
            self.pending_login.loader.close()
        self.pending_login = None
        return self.status()

    def test(self) -> AccountStatus:
        status = self.status()
        if not status.is_connected or not status.username or not status.session_file:
            return AccountStatus(is_connected=False, message="未配置 Instagram session。")
        loader = Instaloader(quiet=True)
        try:
            loader.load_session_from_file(status.username, str(self.session_root / status.session_file))
            detected_username = loader.test_login()
            if not detected_username:
                return AccountStatus(is_connected=False, username=status.username, message="Session 已失效。")
            return AccountStatus(
                is_connected=True,
                username=detected_username,
                session_file=status.session_file,
                updated_at=status.updated_at,
                message="Session 有效。",
            )
        except Exception as exc:  # pylint:disable=broad-exception-caught
            return AccountStatus(is_connected=False, username=status.username, message=str(exc))
        finally:
            loader.close()

    def session_for_downloads(self) -> tuple[Optional[str], Optional[str]]:
        status = self.status()
        if not status.is_connected or not status.username or not status.session_file:
            return None, None
        return status.username, str((self.session_root / status.session_file).resolve())

    def _save_loader_session(self, loader: Instaloader, username: str) -> None:
        self.session_root.mkdir(parents=True, exist_ok=True)
        filename = f"session-{username}"
        target = self.session_root / filename
        loader.save_session_to_file(str(target))
        self._write_metadata(
            {
                "username": username,
                "session_file": filename,
                "updated_at": utc_now(),
            }
        )

    def _read_metadata(self) -> Dict[str, str]:
        if not self.metadata_path.exists():
            return {}
        try:
            data = json.loads(self.metadata_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
        return data if isinstance(data, dict) else {}

    def _write_metadata(self, metadata: Dict[str, str]) -> None:
        self.metadata_path.write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")


def parse_cookie_text(text: str) -> Dict[str, str]:
    stripped = text.strip()
    if not stripped:
        return {}
    if stripped.startswith("{"):
        data = json.loads(stripped)
        if isinstance(data, dict):
            return {str(key): str(value) for key, value in data.items()}
        raise ValueError("Cookie JSON 必须是对象。")
    cookies: Dict[str, str] = {}
    for line in stripped.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "\t" in line:
            parts = line.split("\t")
            if len(parts) >= 7 and "instagram" in parts[0]:
                cookies[parts[5]] = parts[6]
            continue
        for chunk in line.split(";"):
            if "=" in chunk:
                key, value = chunk.split("=", 1)
                cookies[key.strip()] = value.strip()
    return cookies


def cookie_to_dict(cookie: Cookie) -> tuple[str, str]:
    return cookie.name, cookie.value
