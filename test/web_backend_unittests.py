from __future__ import annotations

import tempfile
import unittest
import os
import asyncio
from pathlib import Path
from unittest.mock import patch

from web_backend.account import AccountManager, parse_cookie_text
from web_backend.database import Database
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


class TaskManagerAccountPoolTest(unittest.TestCase):
    def test_login_failure_marks_selected_account_invalid(self) -> None:
        async def run_case() -> None:
            with tempfile.TemporaryDirectory() as temp_dir:
                root = Path(temp_dir)
                database = Database(root / "app.sqlite3")
                manager = TaskManager(
                    database,
                    root / "downloads",
                    session_provider=lambda: ("account-a", str(root / "session-a")),
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


if __name__ == "__main__":
    unittest.main()
