from __future__ import annotations

import tempfile
import unittest
import os
from pathlib import Path

from web_backend.account import AccountManager, parse_cookie_text
from web_backend.database import Database
from web_backend.files import list_media, safe_resolve


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
            self.assertFalse((Path(temp_dir) / "account.json").exists())


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


if __name__ == "__main__":
    unittest.main()
