from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from web_backend.account import AccountManager, parse_cookie_text
from web_backend.database import Database


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


if __name__ == "__main__":
    unittest.main()
