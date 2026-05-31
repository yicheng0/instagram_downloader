from __future__ import annotations

import json
import pickle
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from http.cookiejar import Cookie
from pathlib import Path
from typing import Any, Dict, List, Optional

from instaloader import BadCredentialsException, Instaloader, InstaloaderException, LoginException
from instaloader.exceptions import TwoFactorAuthRequiredException

from .models import AccountListResponse, AccountRecord, AccountStatus


ACCOUNT_COOLDOWN_SECONDS = 900
ACCOUNT_FAILURE_THRESHOLD = 2


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _parse_time(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


@dataclass
class PendingLogin:
    username: str
    loader: Instaloader


class AccountManager:
    def __init__(self, session_root: Path):
        self.session_root = session_root
        self.legacy_metadata_path = session_root / "account.json"
        self.accounts_path = session_root / "accounts.json"
        self.pending_login: Optional[PendingLogin] = None
        self.session_root.mkdir(parents=True, exist_ok=True)
        self._migrate_legacy_metadata()

    def status(self) -> AccountStatus:
        record = self.default_account()
        return AccountStatus(
            is_connected=bool(record and record.is_connected),
            username=record.username if record else None,
            session_file=record.session_file if record else None,
            updated_at=record.updated_at if record else None,
            pending_two_factor=self.pending_login is not None,
            message=record.message if record else None,
        )

    def list_accounts(self) -> AccountListResponse:
        records = self._account_records()
        default = next((record for record in records if record.is_default), None)
        return AccountListResponse(
            accounts=records,
            default_username=default.username if default else None,
            available_count=sum(1 for record in records if record.is_connected),
        )

    def has_valid_account(self) -> bool:
        return any(record.is_connected for record in self._account_records())

    def default_account(self) -> Optional[AccountRecord]:
        records = self._account_records()
        if not records:
            return None
        return next((record for record in records if record.is_default), records[0])

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
            return self._status_for_username(username)
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
            return self._status_for_username(username)
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
            return self._status_for_username(detected_username)
        finally:
            loader.close()

    def clear(self) -> AccountStatus:
        record = self.default_account()
        if record:
            self.delete_account(record.username)
        if self.pending_login:
            self.pending_login.loader.close()
        self.pending_login = None
        return self.status()

    def delete_account(self, username: str) -> AccountListResponse:
        data = self._read_accounts()
        accounts = data.get("accounts", {})
        record = accounts.pop(username, None)
        if record:
            session_file = record.get("session_file")
            if session_file:
                target = self.session_root / str(session_file)
                if target.exists():
                    target.unlink()
        if data.get("default_username") == username:
            connected = [
                name for name, raw in sorted(accounts.items())
                if self._is_record_connected(raw)
            ]
            data["default_username"] = connected[0] if connected else (sorted(accounts)[0] if accounts else None)
        data["accounts"] = accounts
        self._write_accounts(data)
        return self.list_accounts()

    def set_default(self, username: str) -> AccountListResponse:
        data = self._read_accounts()
        if username not in data.get("accounts", {}):
            raise ValueError("账号不存在。")
        data["default_username"] = username
        self._write_accounts(data)
        return self.list_accounts()

    def test(self) -> AccountStatus:
        status = self.status()
        if not status.is_connected or not status.username or not status.session_file:
            return AccountStatus(is_connected=False, message="未配置 Instagram session。")
        return self.test_account(status.username)

    def test_account(self, username: str) -> AccountStatus:
        record = self._find_record(username)
        if not record:
            raise ValueError("账号不存在。")
        status = self._test_record(record)
        self._update_account(
            username,
            {
                "last_test_status": "valid" if status.is_connected else "invalid",
                "message": status.message,
                "updated_at": record.updated_at,
            },
        )
        return status

    def session_for_downloads(self, min_interval_seconds: int = 0, guard_enabled: bool = True) -> tuple[Optional[str], Optional[str]]:
        record = self.reserve_account(min_interval_seconds=min_interval_seconds, guard_enabled=guard_enabled)
        if not record:
            return None, None
        return record.username, str((self.session_root / record.session_file).resolve())

    def reserve_account(self, min_interval_seconds: int = 0, guard_enabled: bool = True) -> Optional[AccountRecord]:
        now = datetime.now(timezone.utc)
        records = [
            record
            for record in self._account_records()
            if self._is_record_available(record, now, min_interval_seconds, guard_enabled)
        ]
        if not records:
            return None
        records.sort(key=lambda record: (record.last_used_at or "", record.username.lower()))
        selected = records[0]
        self._update_account(selected.username, {"last_used_at": utc_now(), "message": selected.message})
        return self._find_record(selected.username) or selected

    def next_available_at(self, min_interval_seconds: int = 0, guard_enabled: bool = True) -> Optional[str]:
        if not guard_enabled:
            return None
        now = datetime.now(timezone.utc)
        candidates = []
        for record in self._account_records():
            if not record.is_connected or record.last_test_status == "invalid":
                continue
            candidates.extend(self._record_wait_until(record, now, min_interval_seconds))
        if not candidates:
            return None
        return min(candidates).isoformat()

    def mark_invalid(self, username: str, reason: str) -> AccountListResponse:
        self._update_account(
            username,
            {
                "last_test_status": "invalid",
                "message": reason,
            },
        )
        return self.list_accounts()

    def mark_rate_limited(self, username: str, reason: str, cooldown_seconds: int = ACCOUNT_COOLDOWN_SECONDS) -> AccountListResponse:
        return self._cooldown_account(username, reason, cooldown_seconds)

    def record_failure(
        self,
        username: str,
        error_code: str,
        reason: str,
        threshold: int = ACCOUNT_FAILURE_THRESHOLD,
        cooldown_seconds: int = ACCOUNT_COOLDOWN_SECONDS,
    ) -> AccountListResponse:
        record = self._find_record(username)
        if not record:
            raise ValueError("账号不存在。")
        failure_count = record.failure_count + 1
        updates: Dict[str, Any] = {
            "failure_count": failure_count,
            "last_error": reason,
            "message": f"{error_code}: {reason}",
        }
        if failure_count >= threshold:
            updates["cooldown_until"] = (datetime.now(timezone.utc) + timedelta(seconds=cooldown_seconds)).isoformat()
            updates["message"] = f"{error_code}: {reason}，账号已短暂冷却。"
        self._update_account(username, updates)
        return self.list_accounts()

    def record_success(self, username: str) -> AccountListResponse:
        self._update_account(
            username,
            {
                "failure_count": 0,
                "last_error": None,
                "cooldown_until": None,
                "message": "最近任务完成。",
            },
        )
        return self.list_accounts()

    def _status_for_username(self, username: str) -> AccountStatus:
        record = self._find_record(username)
        if not record:
            return self.status()
        return AccountStatus(
            is_connected=record.is_connected,
            username=record.username,
            session_file=record.session_file,
            updated_at=record.updated_at,
            pending_two_factor=self.pending_login is not None,
            message=record.message,
        )

    def _save_loader_session(self, loader: Instaloader, username: str) -> None:
        self.session_root.mkdir(parents=True, exist_ok=True)
        filename = f"session-{username}"
        target = self.session_root / filename
        loader.save_session_to_file(str(target))
        self._upsert_account(username, filename)

    def _test_record(self, record: AccountRecord) -> AccountStatus:
        loader = Instaloader(quiet=True)
        try:
            loader.load_session_from_file(record.username, str(self.session_root / record.session_file))
            detected_username = loader.test_login()
            if not detected_username:
                return AccountStatus(is_connected=False, username=record.username, session_file=record.session_file, message="Session 已失效。")
            return AccountStatus(
                is_connected=True,
                username=detected_username,
                session_file=record.session_file,
                updated_at=record.updated_at,
                message="Session 有效。",
            )
        except Exception as exc:  # pylint:disable=broad-exception-caught
            return AccountStatus(is_connected=False, username=record.username, session_file=record.session_file, message=str(exc))
        finally:
            loader.close()

    def _account_records(self) -> List[AccountRecord]:
        data = self._read_accounts()
        default_username = data.get("default_username")
        records = []
        for username, raw in sorted(data.get("accounts", {}).items()):
            session_file = str(raw.get("session_file") or f"session-{username}")
            records.append(
                AccountRecord(
                    username=username,
                    session_file=session_file,
                    is_connected=self._is_record_connected(raw),
                    is_default=username == default_username,
                    updated_at=raw.get("updated_at"),
                    last_used_at=raw.get("last_used_at"),
                    last_test_status=raw.get("last_test_status", "unknown"),
                    cooldown_until=raw.get("cooldown_until"),
                    failure_count=int(raw.get("failure_count") or 0),
                    last_error=raw.get("last_error"),
                    message=raw.get("message"),
                )
            )
        if records and not any(record.is_default for record in records):
            records[0].is_default = True
        return records

    def _find_record(self, username: str) -> Optional[AccountRecord]:
        return next((record for record in self._account_records() if record.username == username), None)

    def _upsert_account(self, username: str, session_file: str) -> None:
        data = self._read_accounts()
        accounts = data.setdefault("accounts", {})
        existing = accounts.get(username, {})
        accounts[username] = {
            **existing,
            "username": username,
            "session_file": session_file,
            "updated_at": utc_now(),
            "last_test_status": "valid",
            "cooldown_until": None,
            "failure_count": 0,
            "last_error": None,
            "message": "Session 已保存。",
        }
        if not data.get("default_username"):
            data["default_username"] = username
        self._write_accounts(data)

    def _update_account(self, username: str, updates: Dict[str, Any]) -> None:
        data = self._read_accounts()
        accounts = data.setdefault("accounts", {})
        if username not in accounts:
            raise ValueError("账号不存在。")
        accounts[username].update(updates)
        self._write_accounts(data)

    def _is_record_connected(self, raw: Dict[str, Any]) -> bool:
        session_file = raw.get("session_file")
        return bool(
            raw.get("username")
            and session_file
            and raw.get("last_test_status", "unknown") != "invalid"
            and (self.session_root / str(session_file)).exists()
        )

    def _is_record_available(
        self,
        record: AccountRecord,
        now: datetime,
        min_interval_seconds: int,
        guard_enabled: bool,
    ) -> bool:
        if not record.is_connected or record.last_test_status == "invalid":
            return False
        if not guard_enabled:
            return True
        return not self._record_wait_until(record, now, min_interval_seconds)

    def _record_wait_until(self, record: AccountRecord, now: datetime, min_interval_seconds: int) -> List[datetime]:
        waits = []
        cooldown = _parse_time(record.cooldown_until)
        if cooldown and cooldown > now:
            waits.append(cooldown)
        last_used = _parse_time(record.last_used_at)
        if last_used and min_interval_seconds > 0:
            reusable_at = last_used + timedelta(seconds=min_interval_seconds)
            if reusable_at > now:
                waits.append(reusable_at)
        return waits

    def _cooldown_account(self, username: str, reason: str, cooldown_seconds: int) -> AccountListResponse:
        self._update_account(
            username,
            {
                "cooldown_until": (datetime.now(timezone.utc) + timedelta(seconds=cooldown_seconds)).isoformat(),
                "failure_count": 0,
                "last_error": reason,
                "message": reason,
            },
        )
        return self.list_accounts()

    def _read_accounts(self) -> Dict[str, Any]:
        if not self.accounts_path.exists():
            return {"default_username": None, "accounts": {}}
        try:
            data = json.loads(self.accounts_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {"default_username": None, "accounts": {}}
        if not isinstance(data, dict):
            return {"default_username": None, "accounts": {}}
        accounts = data.get("accounts")
        if not isinstance(accounts, dict):
            data["accounts"] = {}
        data.setdefault("default_username", None)
        return data

    def _write_accounts(self, data: Dict[str, Any]) -> None:
        self.accounts_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    def _write_metadata(self, metadata: Dict[str, str]) -> None:
        """Compatibility helper for tests and old single-account metadata."""
        username = metadata.get("username")
        session_file = metadata.get("session_file")
        self.legacy_metadata_path.write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
        if username and session_file:
            self._write_accounts(
                {
                    "default_username": username,
                    "accounts": {
                        username: {
                            "username": username,
                            "session_file": session_file,
                            "updated_at": metadata.get("updated_at"),
                            "last_used_at": metadata.get("last_used_at"),
                            "last_test_status": metadata.get("last_test_status", "unknown"),
                            "message": metadata.get("message"),
                        }
                    },
                }
            )

    def _migrate_legacy_metadata(self) -> None:
        if self.accounts_path.exists() or not self.legacy_metadata_path.exists():
            return
        try:
            data = json.loads(self.legacy_metadata_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return
        if not isinstance(data, dict) or not data.get("username") or not data.get("session_file"):
            return
        username = str(data["username"])
        self._write_accounts(
            {
                "default_username": username,
                "accounts": {
                    username: {
                        "username": username,
                        "session_file": data["session_file"],
                        "updated_at": data.get("updated_at"),
                        "last_used_at": None,
                        "last_test_status": "unknown",
                        "message": "从旧版单账号配置迁移。",
                    }
                },
            }
        )


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
