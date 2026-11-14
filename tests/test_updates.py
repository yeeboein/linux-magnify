import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from linux_magnify import updates
from linux_magnify.config import Config, load, save


class UpdateCheckTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.env = mock.patch.dict(os.environ, {"XDG_STATE_HOME": self.dir.name})
        self.env.start()
        self.installed = Path(self.dir.name) / "INSTALLED.json"
        self.installed.write_text(json.dumps({"commit": "a" * 40}))
        self.pin = mock.patch.object(updates, "installed_file", lambda: self.installed)
        self.pin.start()

    def tearDown(self):
        self.pin.stop()
        self.env.stop()
        self.dir.cleanup()

    def fake_github(self, sha, message="Add a thing"):
        body = json.dumps({"sha": sha, "commit": {"message": message + "\n\nmore", "committer": {"date": "2026-11-14T10:00:00Z"}}})
        return mock.patch.object(updates, "_get", lambda url, timeout=15: body.encode())

    def test_new_version_is_detected(self):
        with self.fake_github("b" * 40):
            st = updates.check("main")
        self.assertTrue(st["available"])
        self.assertEqual(st["message"], "Add a thing")
        self.assertFalse(updates.due())  # just checked

    def test_same_version_is_up_to_date(self):
        with self.fake_github("a" * 40):
            self.assertFalse(updates.check("main")["available"])

    def test_network_error_is_reported_not_raised(self):
        def boom(url, timeout=15):
            raise OSError("offline")
        with mock.patch.object(updates, "_get", boom):
            st = updates.check("main")
        self.assertFalse(st["available"])
        self.assertIn("offline", st["error"])

    def test_notified_version_is_remembered(self):
        with self.fake_github("b" * 40):
            updates.check("main")
        updates.mark_notified("b" * 40)
        with self.fake_github("b" * 40):
            st = updates.check("main")
        self.assertEqual(st["notified"], st["latest"])  # the dock won't notify twice


class UpdateConfigTest(unittest.TestCase):
    def test_round_trip(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "config.toml"
            cfg = Config(path=path)
            cfg.update_notify = False
            save(cfg)
            self.assertIn("[updates]", path.read_text())
            self.assertFalse(load(path, import_pins=False).update_notify)


if __name__ == "__main__":
    unittest.main()
