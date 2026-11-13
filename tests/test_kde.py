import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from linux_magnify import menu, panels

ROOT = Path(__file__).resolve().parent.parent


class MergeTest(unittest.TestCase):
    def test_only_the_panel_sections_are_put_back(self):
        backup = ("[Containments][1]\nplugin=desktop\nwall=a\n\n[Containments][2]\nplugin=org.kde.panel\n\n"
                  "[Containments][2][Applets][3]\nplugin=kickoff\n\n[Containments][20]\nplugin=other\n")
        current = "[Containments][1]\nplugin=desktop\nwall=b\n\n[Containments][20]\nplugin=changed\n"
        applets, _views = panels.panel_section_filters(["2"])
        merged = panels.merge_sections(current, backup, applets)
        self.assertIn("wall=b", merged)            # live change kept
        self.assertNotIn("wall=a", merged)
        self.assertIn("[Containments][2]\nplugin=org.kde.panel", merged)
        self.assertIn("[Containments][2][Applets][3]", merged)
        self.assertIn("plugin=changed", merged)    # [Containments][20] is not panel 2
        self.assertEqual(merged.count("[Containments][20]"), 1)

    def test_view_filter(self):
        _applets, views = panels.panel_section_filters(["2"])
        self.assertTrue(views("PlasmaViews][Panel 2"))
        self.assertTrue(views("PlasmaViews][Panel 2][Defaults"))
        self.assertFalse(views("PlasmaViews][Panel 21"))


class MetaKeyTest(unittest.TestCase):
    def test_bind_and_restore(self):
        calls = []

        def fake_run(cmd, timeout=5):
            calls.append(cmd)
            return "org.kde.plasmashell,/PlasmaShell,org.kde.PlasmaShell,activateLauncherMenu\n" \
                if cmd[0].startswith("kread") else ""

        with tempfile.TemporaryDirectory() as d, \
                mock.patch.dict(os.environ, {"XDG_STATE_HOME": d}), \
                mock.patch.object(panels, "_run", fake_run), \
                mock.patch.object(panels, "_kconfig_tool", lambda kind: f"k{kind}config6"), \
                mock.patch.object(panels, "_kwin_reconfigure", lambda: None):
            state: list = []
            panels._bind_meta_key(state)
            self.assertEqual(calls[-1][-1], panels.META_SHORTCUT)
            panels._restore_meta_key(state[0])
            self.assertEqual(calls[-1][-1], "org.kde.plasmashell,/PlasmaShell,org.kde.PlasmaShell,activateLauncherMenu")


class MenuTriggerTest(unittest.TestCase):
    def test_toggle_starts_quickshell_and_writes_trigger(self):
        with tempfile.TemporaryDirectory() as d:
            fake_qs = Path(d) / "qs"
            fake_qs.write_text("#!/bin/sh\nsleep 30\n")  # keeps "-p .../menu.qml" in its cmdline, like qs
            fake_qs.chmod(0o755)
            env = {"XDG_RUNTIME_DIR": d, "PATH": f"{d}:{os.environ['PATH']}"}
            with mock.patch.dict(os.environ, env):
                menu.set_geometry("bottom", 150)
                try:
                    self.assertTrue(menu.toggle())
                    first = json.loads(menu.trigger_file().read_text())
                    self.assertTrue(menu.toggle())
                    second = json.loads(menu.trigger_file().read_text())
                    self.assertEqual((first["action"], first["edge"], first["gap"]), ("toggle", "bottom", 150))
                    self.assertEqual(second["seq"], first["seq"] + 1)
                finally:
                    menu.stop()


class CliTest(unittest.TestCase):
    def run_cli(self, *args, env):
        return subprocess.run([sys.executable, "-m", "linux_magnify", *args], cwd=ROOT, env=env,
                              capture_output=True, text=True, check=True).stdout

    def test_config_json_and_set(self):
        with tempfile.TemporaryDirectory() as d:
            env = dict(os.environ, XDG_CONFIG_HOME=d, XDG_STATE_HOME=d, XDG_CURRENT_DESKTOP="none",
                       PYTHONPATH=str(ROOT))
            self.run_cli("--config-set", json.dumps({"position": "left", "magnification": 2.5,
                                                     "pinned": [{"id": "firefox"}]}), env=env)
            data = json.loads(self.run_cli("--config-json", env=env))
            self.assertEqual((data["position"], data["magnification"], data["hide_panels"]), ("left", 2.5, "all"))
            self.assertEqual(data["pinned"], [{"id": "firefox"}])
            self.assertEqual(len(data["pinned_display"]), 1)
            status = json.loads(self.run_cli("--status-json", env=env))
            self.assertEqual(set(status), {"running", "autostart"})


if __name__ == "__main__":
    unittest.main()
