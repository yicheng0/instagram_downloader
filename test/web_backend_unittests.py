from __future__ import annotations

import tempfile
import unittest
import os
import asyncio
import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

from web_backend.account import AccountManager, parse_cookie_text
from web_backend.creators import (
    ANONYMOUS_PROFILE_UNAVAILABLE,
    AnonymousProfileUnavailable,
    CreatorProfileNotFound,
    _install_chromium_once,
    _launch_browser,
    _parse_compact_number,
    _parse_public_profile_metadata,
    fetch_creator_profile,
)
from web_backend.database import Database
from web_backend.downloader import _normalize_targets
from web_backend.files import list_media, safe_resolve
from web_backend.main import app
from web_backend.models import TaskCreate
from web_backend.task_manager import TaskManager
from fastapi.testclient import TestClient


class SettingsPersistenceTest(unittest.TestCase):
    def test_settings_are_persisted(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            db = Database(root / "app.sqlite3")
            default_download_root = root / "downloads"

            settings = db.update_settings(
                {
                    "max_concurrent_tasks": 5,
                    "download_root": str(root / "custom"),
                    "default_max_count": 123,
                    "show_debug_logs": False,
                    "desktop_notifications": False,
                    "theme": "system",
                    "stability_guard_enabled": False,
                    "account_min_interval_seconds": 60,
                },
                default_download_root,
            )

            self.assertEqual(settings.max_concurrent_tasks, 5)
            self.assertEqual(settings.download_root, str(root / "custom"))
            reloaded = db.get_settings(default_download_root)
            self.assertEqual(reloaded.default_max_count, 123)
            self.assertFalse(reloaded.show_debug_logs)
            self.assertFalse(reloaded.desktop_notifications)
            self.assertEqual(reloaded.theme, "system")
            self.assertFalse(reloaded.stability_guard_enabled)
            self.assertEqual(reloaded.account_min_interval_seconds, 60)


class CookieParserTest(unittest.TestCase):
    def test_parse_cookie_json(self) -> None:
        self.assertEqual(parse_cookie_text('{"sessionid": "abc", "csrftoken": "def"}')["sessionid"], "abc")

    def test_parse_netscape_cookie_text(self) -> None:
        text = ".instagram.com\tTRUE\t/\tTRUE\t0\tsessionid\tabc"
        self.assertEqual(parse_cookie_text(text), {"sessionid": "abc"})

    def test_parse_header_cookie_text(self) -> None:
        self.assertEqual(parse_cookie_text("sessionid=abc; csrftoken=def")["csrftoken"], "def")


class AccountManagerTest(unittest.TestCase):
    def test_clear_removes_saved_metadata_and_session(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            manager = AccountManager(Path(temp_dir))
            session_file = Path(temp_dir) / "session-test"
            session_file.write_bytes(b"data")
            manager._write_metadata(  # pylint:disable=protected-access
                {"username": "test", "session_file": "session-test", "updated_at": "now"}
            )

            status = manager.clear()

            self.assertFalse(status.is_connected)
            self.assertFalse(session_file.exists())
            self.assertEqual(manager.list_accounts().accounts, [])

    def test_legacy_account_metadata_is_migrated(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            session_file = root / "session-test"
            session_file.write_bytes(b"data")
            (root / "account.json").write_text(
                '{"username": "test", "session_file": "session-test", "updated_at": "now"}',
                encoding="utf-8",
            )

            manager = AccountManager(root)
            accounts = manager.list_accounts()

            self.assertEqual(accounts.default_username, "test")
            self.assertEqual(accounts.available_count, 1)
            self.assertEqual(accounts.accounts[0].username, "test")

    def test_delete_default_account_selects_next_available(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "session-a").write_bytes(b"a")
            (root / "session-b").write_bytes(b"b")
            manager = AccountManager(root)
            manager._write_accounts(  # pylint:disable=protected-access
                {
                    "default_username": "a",
                    "accounts": {
                        "a": {"username": "a", "session_file": "session-a"},
                        "b": {"username": "b", "session_file": "session-b"},
                    },
                }
            )

            accounts = manager.delete_account("a")

            self.assertEqual(accounts.default_username, "b")
            self.assertFalse((root / "session-a").exists())

    def test_reserve_account_rotates_by_last_used(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "session-a").write_bytes(b"a")
            (root / "session-b").write_bytes(b"b")
            manager = AccountManager(root)
            manager._write_accounts(  # pylint:disable=protected-access
                {
                    "default_username": "a",
                    "accounts": {
                        "a": {"username": "a", "session_file": "session-a", "last_used_at": "2024-01-02T00:00:00+00:00"},
                        "b": {"username": "b", "session_file": "session-b", "last_used_at": "2024-01-01T00:00:00+00:00"},
                    },
                }
            )

            reserved = manager.reserve_account()

            self.assertIsNotNone(reserved)
            self.assertEqual(reserved.username, "b")
            updated = {account.username: account for account in manager.list_accounts().accounts}
            self.assertIsNotNone(updated["b"].last_used_at)

    def test_mark_invalid_excludes_account_from_rotation(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "session-a").write_bytes(b"a")
            (root / "session-b").write_bytes(b"b")
            manager = AccountManager(root)
            manager._write_accounts(  # pylint:disable=protected-access
                {
                    "default_username": "a",
                    "accounts": {
                        "a": {"username": "a", "session_file": "session-a", "last_test_status": "valid"},
                        "b": {"username": "b", "session_file": "session-b", "last_test_status": "valid"},
                    },
                }
            )

            accounts = manager.mark_invalid("a", "login expired")
            reserved = manager.reserve_account()

            self.assertEqual(accounts.available_count, 1)
            self.assertIsNotNone(reserved)
            self.assertEqual(reserved.username, "b")
            records = {account.username: account for account in manager.list_accounts().accounts}
            self.assertFalse(records["a"].is_connected)
            self.assertEqual(records["a"].last_test_status, "invalid")

    def test_cooldown_and_min_interval_exclude_account_from_rotation(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "session-a").write_bytes(b"a")
            manager = AccountManager(root)
            manager._write_accounts(  # pylint:disable=protected-access
                {
                    "default_username": "a",
                    "accounts": {
                        "a": {"username": "a", "session_file": "session-a", "last_test_status": "valid"},
                    },
                }
            )

            reserved = manager.reserve_account(min_interval_seconds=120, guard_enabled=True)
            self.assertIsNotNone(reserved)
            self.assertIsNone(manager.reserve_account(min_interval_seconds=120, guard_enabled=True))
            self.assertIsNotNone(manager.next_available_at(min_interval_seconds=120, guard_enabled=True))

            manager.mark_rate_limited("a", "429")
            self.assertIsNone(manager.reserve_account(min_interval_seconds=0, guard_enabled=True))
            self.assertIsNotNone(manager.next_available_at(min_interval_seconds=0, guard_enabled=True))

    def test_failure_threshold_cools_account_and_success_clears_state(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "session-a").write_bytes(b"a")
            manager = AccountManager(root)
            manager._write_accounts(  # pylint:disable=protected-access
                {
                    "default_username": "a",
                    "accounts": {
                        "a": {"username": "a", "session_file": "session-a", "last_test_status": "valid"},
                    },
                }
            )

            manager.record_failure("a", "network", "temporary", threshold=2, cooldown_seconds=120)
            self.assertEqual(manager.list_accounts().accounts[0].failure_count, 1)
            manager.record_failure("a", "timeout", "slow", threshold=2, cooldown_seconds=120)
            account = manager.list_accounts().accounts[0]
            self.assertEqual(account.failure_count, 2)
            self.assertIsNotNone(account.cooldown_until)
            self.assertIsNone(manager.reserve_account(min_interval_seconds=0, guard_enabled=True))

            manager.record_success("a")
            account = manager.list_accounts().accounts[0]
            self.assertEqual(account.failure_count, 0)
            self.assertIsNone(account.cooldown_until)


class TaskManagerAccountPoolTest(unittest.TestCase):
    def test_login_failure_marks_selected_account_invalid(self) -> None:
        async def run_case() -> None:
            with tempfile.TemporaryDirectory() as temp_dir:
                root = Path(temp_dir)
                database = Database(root / "app.sqlite3")
                manager = TaskManager(
                    database,
                    root / "downloads",
                    session_provider=lambda _interval, _enabled: ("account-a", str(root / "session-a")),
                    session_invalidator=lambda username, reason: invalidated.append((username, reason)),
                )
                task = database.create_task(TaskCreate(target_type="profile", targets=["profile"]))

                invalidated: list[tuple[str, str]] = []
                with patch("web_backend.task_manager.run_download_task", side_effect=RuntimeError("login required")):
                    await manager._run_task(database.claim_next_queued_task() or task)  # pylint:disable=protected-access

                self.assertEqual(invalidated, [("account-a", "login required")])
                events = database.list_events(task.id)
                self.assertTrue(any("marked invalid" in event.message for event in events))

        asyncio.run(run_case())

    def test_required_login_task_waits_when_accounts_are_cooling_down(self) -> None:
        async def run_case() -> None:
            with tempfile.TemporaryDirectory() as temp_dir:
                root = Path(temp_dir)
                database = Database(root / "app.sqlite3")
                manager = TaskManager(
                    database,
                    root / "downloads",
                    session_provider=lambda _interval, _enabled: (None, None),
                    next_session_availability=lambda _interval, _enabled: "2099-01-01T00:00:00+00:00",
                    settings_provider=lambda: (True, 120),
                )
                task = database.create_task(TaskCreate(target_type="stories", targets=["stories"]))

                await manager._run_task(database.claim_next_queued_task() or task)  # pylint:disable=protected-access

                updated = database.get_task(task.id)
                self.assertIsNotNone(updated)
                self.assertEqual(updated.status, "queued")
                self.assertEqual(updated.next_retry_at, "2099-01-01T00:00:00+00:00")

        asyncio.run(run_case())

    def test_success_and_transient_failure_update_account_state(self) -> None:
        async def run_case() -> None:
            with tempfile.TemporaryDirectory() as temp_dir:
                root = Path(temp_dir)
                database = Database(root / "app.sqlite3")
                successes: list[str] = []
                failures: list[tuple[str, str, str]] = []
                manager = TaskManager(
                    database,
                    root / "downloads",
                    session_provider=lambda _interval, _enabled: ("account-a", str(root / "session-a")),
                    session_success_recorder=successes.append,
                    session_failure_recorder=lambda username, code, reason: failures.append((username, code, reason)),
                )
                task = database.create_task(TaskCreate(target_type="profile", targets=["profile"]))
                with patch("web_backend.task_manager.run_download_task", return_value=None):
                    await manager._run_task(database.claim_next_queued_task() or task)  # pylint:disable=protected-access
                self.assertEqual(successes, ["account-a"])

                failed_task = database.create_task(TaskCreate(target_type="profile", targets=["profile"]))
                with patch("web_backend.task_manager.run_download_task", side_effect=TimeoutError("timed out")):
                    await manager._run_task(database.claim_next_queued_task() or failed_task)  # pylint:disable=protected-access
                self.assertEqual(failures, [("account-a", "timeout", "timed out")])

        asyncio.run(run_case())


class TaskBatchApiTest(unittest.TestCase):
    def test_batch_task_api_creates_one_task_per_target(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            temp_db = Database(root / "app.sqlite3")
            import web_backend.main as main_module

            old_db = main_module.db
            old_manager = main_module.manager
            old_download_root = main_module.DOWNLOAD_ROOT
            main_module.db = temp_db
            main_module.DOWNLOAD_ROOT = root / "downloads"

            class StubManager:
                async def create_task(self, payload: TaskCreate):
                    return temp_db.create_task(payload)

            main_module.manager = StubManager()
            try:
                response = TestClient(app).post(
                    "/api/tasks/batch",
                    json={"target_type": "profile", "targets": ["one", "two", "three"], "options": {}},
                )
            finally:
                main_module.db = old_db
                main_module.manager = old_manager
                main_module.DOWNLOAD_ROOT = old_download_root

            self.assertEqual(response.status_code, 200)
            data = response.json()
            self.assertEqual(data["created_count"], 3)
            self.assertEqual([task["targets"] for task in data["tasks"]], [["one"], ["two"], ["three"]])
            self.assertEqual(len(temp_db.list_tasks()), 3)

    def test_batch_required_login_rejects_without_valid_account(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            temp_db = Database(root / "app.sqlite3")
            import web_backend.main as main_module

            old_db = main_module.db
            old_download_root = main_module.DOWNLOAD_ROOT
            old_account_manager = main_module.account_manager
            main_module.db = temp_db
            main_module.DOWNLOAD_ROOT = root / "downloads"

            class StubAccountManager:
                def has_valid_account(self) -> bool:
                    return False

            main_module.account_manager = StubAccountManager()
            try:
                response = TestClient(app).post(
                    "/api/tasks/batch",
                    json={"target_type": "stories", "targets": ["stories"], "options": {}},
                )
            finally:
                main_module.db = old_db
                main_module.DOWNLOAD_ROOT = old_download_root
                main_module.account_manager = old_account_manager

            self.assertEqual(response.status_code, 400)
            self.assertIn("需要先连接", response.json()["detail"])


class MediaFileTest(unittest.TestCase):
    def test_list_media_filters_sorts_and_limits(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            nested = root / "task-1" / "profile"
            nested.mkdir(parents=True)
            older = nested / "older.jpg"
            newest = nested / "newest.mp4"
            ignored = nested / "metadata.json"
            older.write_bytes(b"jpg")
            newest.write_bytes(b"mp4")
            ignored.write_text("{}", encoding="utf-8")

            older_time = 1_700_000_000
            newest_time = 1_700_000_100
            older.touch()
            newest.touch()
            ignored.touch()
            os.utime(older, (older_time, older_time))
            os.utime(newest, (newest_time, newest_time))
            os.utime(ignored, (newest_time + 1, newest_time + 1))

            media = list_media(root, "task-1", limit=1)

            self.assertEqual(len(media), 1)
            self.assertEqual(media[0].name, "newest.mp4")
            self.assertEqual(media[0].media_type, "video")
            self.assertEqual(media[0].path, "task-1/profile/newest.mp4")

    def test_list_media_rejects_paths_outside_root(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            with self.assertRaises(ValueError):
                list_media(Path(temp_dir), "../outside")

    def test_safe_resolve_allows_root_itself(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            self.assertEqual(safe_resolve(root, ""), root.resolve())


class CreatorDatabaseTest(unittest.TestCase):
    def test_creator_username_is_normalized_and_deduplicated(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            database = Database(Path(temp_dir) / "app.sqlite3")

            first = database.create_or_get_creator("@Profile_Name/")
            second = database.create_or_get_creator("profile_name")

            self.assertEqual(first.id, second.id)
            self.assertEqual(second.username, "profile_name")
            self.assertEqual(len(database.list_creators()), 1)

    def test_creator_homepage_url_is_normalized(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            database = Database(Path(temp_dir) / "app.sqlite3")

            first = database.create_or_get_creator("https://www.instagram.com/mancity/")
            second = database.create_or_get_creator("https://instagram.com/mancity/?hl=en")

            self.assertEqual(first.id, second.id)
            self.assertEqual(second.username, "mancity")
            self.assertEqual(len(database.list_creators()), 1)

    def test_creator_post_url_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            database = Database(Path(temp_dir) / "app.sqlite3")

            with self.assertRaises(ValueError):
                database.create_or_get_creator("https://www.instagram.com/p/abc123/")

    def test_creator_profile_update_and_error_status(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            database = Database(Path(temp_dir) / "app.sqlite3")
            creator = database.create_or_get_creator("profile")

            updated = database.update_creator_profile(
                creator.id,
                {
                    "username": "profile",
                    "full_name": "Profile Name",
                    "avatar_url": "https://example.com/avatar.jpg",
                    "biography": "bio",
                    "is_private": False,
                    "is_verified": True,
                    "followers": 10,
                    "followees": 2,
                    "mediacount": 3,
                },
            )
            self.assertIsNotNone(updated)
            self.assertEqual(updated.status, "ready")
            self.assertEqual(updated.avatar_url, "https://example.com/avatar.jpg")
            self.assertTrue(updated.is_verified)

            errored = database.mark_creator_error(creator.id, "rate limited")
            self.assertIsNotNone(errored)
            self.assertEqual(errored.status, "error")
            self.assertEqual(errored.error, "rate limited")
            self.assertEqual(errored.avatar_url, "https://example.com/avatar.jpg")


class CreatorProfileFallbackTest(unittest.TestCase):
    def test_fast_profile_fetch_does_not_use_browser(self) -> None:
        expected = {"username": "profile", "full_name": "Profile Name"}
        with (
            patch("web_backend.creators._fetch_creator_profile_with_instaloader", return_value=expected),
            patch("web_backend.creators.fetch_public_profile_with_browser") as browser_fetch,
        ):
            self.assertEqual(fetch_creator_profile("profile"), expected)
        browser_fetch.assert_not_called()

    def test_failed_fast_profile_fetch_uses_browser(self) -> None:
        expected = {"username": "mancity", "full_name": "Manchester City"}
        with (
            patch("web_backend.creators._fetch_creator_profile_with_instaloader", side_effect=RuntimeError("blocked")),
            patch("web_backend.creators.fetch_public_profile_with_browser", return_value=expected) as browser_fetch,
        ):
            self.assertEqual(fetch_creator_profile("mancity"), expected)
        browser_fetch.assert_called_once_with("mancity")

    def test_browser_unavailable_is_reported_as_anonymous_limit(self) -> None:
        with (
            patch("web_backend.creators._fetch_creator_profile_with_instaloader", side_effect=RuntimeError("blocked")),
            patch(
                "web_backend.creators.fetch_public_profile_with_browser",
                side_effect=AnonymousProfileUnavailable("chrome failed"),
            ),
        ):
            with self.assertRaisesRegex(AnonymousProfileUnavailable, ANONYMOUS_PROFILE_UNAVAILABLE):
                fetch_creator_profile("mancity")

    def test_parse_compact_number(self) -> None:
        self.assertEqual(_parse_compact_number("774"), 774)
        self.assertEqual(_parse_compact_number("1,234"), 1234)
        self.assertEqual(_parse_compact_number("43K"), 43_000)
        self.assertEqual(_parse_compact_number("1.2M"), 1_200_000)
        self.assertEqual(_parse_compact_number("1.5B"), 1_500_000_000)

    def test_parse_public_profile_metadata_returns_only_known_fields(self) -> None:
        profile = _parse_public_profile_metadata(
            "mancity",
            "Manchester City (@mancity) • Instagram photos and videos",
            {
                "og:title": "Manchester City (@mancity) • Instagram photos and videos",
                "og:image": "https://example.com/avatar.jpg",
                "og:description": "56M Followers, 774 Following, 43K Posts - See Instagram photos and videos from Manchester City (@mancity)",
                "description": '56M Followers, 774 Following, 43K Posts - Manchester City (@mancity) on Instagram: "Est. 1894"',
            },
        )

        self.assertEqual(
            profile,
            {
                "username": "mancity",
                "full_name": "Manchester City",
                "avatar_url": "https://example.com/avatar.jpg",
                "followers": 56_000_000,
                "followees": 774,
                "mediacount": 43_000,
                "biography": "Est. 1894",
            },
        )
        self.assertNotIn("is_private", profile)
        self.assertNotIn("is_verified", profile)

    def test_parse_public_profile_metadata_recognizes_missing_profile(self) -> None:
        with self.assertRaisesRegex(CreatorProfileNotFound, "Profile missing does not exist"):
            _parse_public_profile_metadata("missing", "Profile isn't available • Instagram", {})

    def test_parse_public_profile_metadata_rejects_generic_shell(self) -> None:
        with self.assertRaisesRegex(AnonymousProfileUnavailable, "没有返回可识别"):
            _parse_public_profile_metadata("mancity", "Instagram", {})

    def test_partial_browser_profile_preserves_existing_boolean_fields(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            database = Database(Path(temp_dir) / "app.sqlite3")
            creator = database.create_or_get_creator("profile")
            database.update_creator_profile(
                creator.id,
                {
                    "username": "profile",
                    "full_name": "Old Name",
                    "is_private": True,
                    "is_verified": True,
                },
            )

            updated = database.update_creator_profile(creator.id, {"username": "profile", "full_name": "New Name"})

            self.assertEqual(updated.full_name, "New Name")
            self.assertTrue(updated.is_private)
            self.assertTrue(updated.is_verified)

    def test_chromium_install_runs_only_once_after_success(self) -> None:
        import web_backend.creators as creators_module

        old_attempted = creators_module._chromium_install_attempted  # pylint:disable=protected-access
        old_error = creators_module._chromium_install_error  # pylint:disable=protected-access
        creators_module._chromium_install_attempted = False  # pylint:disable=protected-access
        creators_module._chromium_install_error = None  # pylint:disable=protected-access
        try:
            with patch("web_backend.creators.subprocess.run") as run:
                _install_chromium_once()
                _install_chromium_once()
            run.assert_called_once()
        finally:
            creators_module._chromium_install_attempted = old_attempted  # pylint:disable=protected-access
            creators_module._chromium_install_error = old_error  # pylint:disable=protected-access

    def test_chromium_install_failure_is_reused(self) -> None:
        import web_backend.creators as creators_module

        old_attempted = creators_module._chromium_install_attempted  # pylint:disable=protected-access
        old_error = creators_module._chromium_install_error  # pylint:disable=protected-access
        creators_module._chromium_install_attempted = False  # pylint:disable=protected-access
        creators_module._chromium_install_error = None  # pylint:disable=protected-access
        try:
            with patch("web_backend.creators.subprocess.run", side_effect=subprocess.CalledProcessError(1, "install")) as run:
                with self.assertRaisesRegex(AnonymousProfileUnavailable, "自动安装"):
                    _install_chromium_once()
                with self.assertRaisesRegex(AnonymousProfileUnavailable, "自动安装"):
                    _install_chromium_once()
            run.assert_called_once()
        finally:
            creators_module._chromium_install_attempted = old_attempted  # pylint:disable=protected-access
            creators_module._chromium_install_error = old_error  # pylint:disable=protected-access

    def test_browser_launch_installs_chromium_then_retries(self) -> None:
        playwright = MagicMock()
        browser = MagicMock()
        playwright.chromium.launch.side_effect = [RuntimeError("missing"), browser]
        with patch("web_backend.creators._find_local_chrome", return_value=None), patch("web_backend.creators._install_chromium_once") as install:
            self.assertIs(_launch_browser(playwright), browser)
        install.assert_called_once_with()
        self.assertEqual(playwright.chromium.launch.call_count, 2)


class DownloadTargetNormalizationTest(unittest.TestCase):
    def test_profile_homepage_url_is_normalized(self) -> None:
        self.assertEqual(
            _normalize_targets("profile", ["https://www.instagram.com/mancity/", "https://instagram.com/ManCity/?hl=en"]),
            ["mancity", "mancity"],
        )

    def test_profile_username_is_normalized(self) -> None:
        self.assertEqual(_normalize_targets("profile", ["@Profile_Name/"]), ["profile_name"])

    def test_profile_post_url_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            _normalize_targets("profile", ["https://www.instagram.com/p/abc123/"])


class CreatorApiTest(unittest.TestCase):
    def test_create_creator_refreshes_profile(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_db = Database(Path(temp_dir) / "app.sqlite3")
            import web_backend.main as main_module

            old_db = main_module.db
            main_module.db = temp_db
            try:
                with patch(
                    "web_backend.main.fetch_creator_profile",
                    return_value={
                        "username": "profile",
                        "full_name": "Profile Name",
                        "avatar_url": "https://example.com/avatar.jpg",
                        "biography": "bio",
                        "is_private": False,
                        "is_verified": False,
                        "followers": 10,
                        "followees": 2,
                        "mediacount": 3,
                    },
                ):
                    response = TestClient(app).post("/api/creators", json={"username": "@profile"})
                self.assertEqual(response.status_code, 200)
                data = response.json()
                self.assertEqual(data["username"], "profile")
                self.assertEqual(data["avatar_url"], "https://example.com/avatar.jpg")
                self.assertEqual(data["status"], "ready")
            finally:
                main_module.db = old_db

    def test_refresh_creator_returns_error_record_on_fetch_failure(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_db = Database(Path(temp_dir) / "app.sqlite3")
            creator = temp_db.create_or_get_creator("profile")
            import web_backend.main as main_module

            old_db = main_module.db
            main_module.db = temp_db
            try:
                with patch("web_backend.main.fetch_creator_profile", side_effect=RuntimeError("blocked")):
                    response = TestClient(app).post(f"/api/creators/{creator.id}/refresh")
                self.assertEqual(response.status_code, 200)
                data = response.json()
                self.assertEqual(data["status"], "error")
                self.assertEqual(data["error"], "blocked")
            finally:
                main_module.db = old_db


class BrowserLoginApiTest(unittest.TestCase):
    def test_open_browser_login_uses_temporary_chrome_profile(self) -> None:
        import web_backend.main as main_module

        with tempfile.TemporaryDirectory() as temp_dir:
            profile = Path(temp_dir) / "chrome-profile"
            old_profile = main_module.CHROME_AUTH_PROFILE
            main_module.CHROME_AUTH_PROFILE = profile
            try:
                with patch("web_backend.main._find_chrome_executable", return_value="chrome.exe"), patch("web_backend.main.subprocess.Popen") as popen:
                    response = TestClient(app).post("/api/session/open-browser-login")
            finally:
                main_module.CHROME_AUTH_PROFILE = old_profile

        self.assertEqual(response.status_code, 200)
        command = popen.call_args.args[0]
        self.assertIn(f"--user-data-dir={profile}", command)
        self.assertIn("https://www.instagram.com/accounts/login/", command)

    def test_open_browser_login_returns_error_when_chrome_is_missing(self) -> None:
        with patch("web_backend.main._find_chrome_executable", return_value=None):
            response = TestClient(app).post("/api/session/open-browser-login")

        self.assertEqual(response.status_code, 400)
        self.assertIn("没有找到 Chrome", response.json()["detail"])

    def test_import_browser_auth_requires_cookie_file(self) -> None:
        import web_backend.main as main_module

        with tempfile.TemporaryDirectory() as temp_dir:
            old_profile = main_module.CHROME_AUTH_PROFILE
            main_module.CHROME_AUTH_PROFILE = Path(temp_dir) / "chrome-profile"
            try:
                response = TestClient(app).post("/api/session/import-browser-auth")
            finally:
                main_module.CHROME_AUTH_PROFILE = old_profile

        self.assertEqual(response.status_code, 400)
        self.assertIn("还没有找到授权 Chrome", response.json()["detail"])

    def test_import_browser_auth_uses_profile_cookie_and_key_files(self) -> None:
        import web_backend.main as main_module

        with tempfile.TemporaryDirectory() as temp_dir:
            profile = Path(temp_dir) / "chrome-profile"
            cookies = profile / "Default" / "Network" / "Cookies"
            key_file = profile / "Local State"
            cookies.parent.mkdir(parents=True)
            cookies.write_bytes(b"sqlite")
            key_file.write_text("{}", encoding="utf-8")
            old_profile = main_module.CHROME_AUTH_PROFILE
            old_account_manager = main_module.account_manager
            main_module.CHROME_AUTH_PROFILE = profile

            class StubAccountManager:
                def import_browser_cookies(self, browser: str, cookie_file: str, key_file: str):
                    calls.append((browser, cookie_file, key_file))
                    return {"is_connected": True, "username": "profile", "session_file": "session-profile", "updated_at": None, "pending_two_factor": False, "message": None}

            calls: list[tuple[str, str, str]] = []
            main_module.account_manager = StubAccountManager()
            try:
                response = TestClient(app).post("/api/session/import-browser-auth")
            finally:
                main_module.CHROME_AUTH_PROFILE = old_profile
                main_module.account_manager = old_account_manager

        self.assertEqual(response.status_code, 200)
        self.assertEqual(calls, [("chrome", str(cookies), str(key_file))])


if __name__ == "__main__":
    unittest.main()
