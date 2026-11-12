import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from linux_magnify import home, panels
from linux_magnify.config import Config, PinnedApp, dumps, load, save
from linux_magnify.windows import Window, covering

APPLETSRC = """
[Containments][1]
plugin=org.kde.desktopcontainment

[Containments][1][Applets][9]
plugin=org.kde.plasma.icontasks

[Containments][1][Applets][9][Configuration][General]
launchers=applications:wrong.desktop

[Containments][2]
plugin=org.kde.panel

[Containments][2][Applets][3]
plugin=org.kde.plasma.kickoff

[Containments][2][Applets][3][Configuration][General]
icon=distributor-logo-devium

[Containments][2][Applets][5]
plugin=org.kde.plasma.icontasks

[Containments][2][Applets][5][Configuration][General]
launchers=applications:org.kde.dolphin.desktop,file:///usr/share/applications/firefox.desktop,file:///missing/app.desktop,applications:org.kde.konsole.desktop
"""


class KdeTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        Path(self.dir.name, "plasma-org.kde.plasma.desktop-appletsrc").write_text(APPLETSRC)
        self.env = mock.patch.dict(os.environ, {"XDG_CONFIG_HOME": self.dir.name,
                                                "XDG_DATA_DIRS": "/usr/share", "XDG_DATA_HOME": "/nonexistent"})
        self.env.start()
        panels._APP_DIRS = None

    def tearDown(self):
        self.env.stop()
        panels._APP_DIRS = None
        self.dir.cleanup()

    def test_pins_come_from_the_panel_task_manager_only(self):
        self.assertEqual(panels._kde_pins(), ["org.kde.dolphin", "firefox", "org.kde.konsole"])

    def test_launcher_icon_is_copied(self):
        self.assertEqual(home._kde_icon(), "distributor-logo-devium")


class RefTest(unittest.TestCase):
    def test_desktop_refs(self):
        panels._APP_DIRS = ["/usr/share/applications"]
        try:
            self.assertEqual(panels.desktop_ref("applications:kitty.desktop"), "kitty")
            self.assertEqual(panels.desktop_ref("file:///usr/share/applications/org.gnome.Nautilus.desktop"),
                             "org.gnome.Nautilus")
            self.assertEqual(panels.desktop_ref("/usr/share/applications/kde4/foo.desktop"), "kde4-foo")
            self.assertIsNone(panels.desktop_ref("/missing/thing.desktop"))
            self.assertEqual(panels.desktop_ref("firefox.desktop"), "firefox")
            self.assertIsNone(panels.desktop_ref(""))
        finally:
            panels._APP_DIRS = None

    def test_xfce_edges(self):
        self.assertEqual(panels.xfce_edge("p=6;x=0;y=0"), "top")
        self.assertEqual(panels.xfce_edge("p=8;x=640;y=700"), "bottom")
        self.assertIsNone(panels.xfce_edge("garbage"))


class ConfigRoundTripTest(unittest.TestCase):
    def test_save_and_load(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "config.toml"
            cfg = Config(path=path)
            cfg.position, cfg.hide_mode, cfg.home_icon = "left", "dodge", "start-here"
            cfg.pinned = [PinnedApp(desktop_id="firefox"),
                          PinnedApp(name="htop", exec='kitty "htop"', icon="utilities-system-monitor")]
            save(cfg)
            back = load(path, import_pins=False)
            self.assertEqual((back.position, back.hide_mode, back.home_icon), ("left", "dodge", "start-here"))
            self.assertEqual(back.pinned[0].desktop_id, "firefox")
            self.assertEqual(back.pinned[1].exec, 'kitty "htop"')

    def test_imported_pins_are_not_frozen_into_the_file(self):
        cfg = Config()
        cfg.pinned = [PinnedApp(desktop_id="firefox")]
        cfg.pinned_imported = True
        self.assertNotIn('"firefox"', dumps(cfg))

    def test_legacy_autohide(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "config.toml"
            path.write_text("[dock]\nautohide = true\n[apps]\npinned = []\n")
            cfg = load(path)
            self.assertEqual(cfg.hide_mode, "always")
            self.assertTrue(cfg.autohide)

    def test_auto_mode_follows_the_panel(self):
        cfg = Config(hide_mode="auto")
        self.assertEqual(cfg.effective_hide_mode, "never")
        cfg.resolved_hide_mode = "dodge"
        self.assertEqual(cfg.effective_hide_mode, "dodge")
        self.assertTrue(cfg.autohide)


class CoveringTest(unittest.TestCase):
    dock = (400, 650, 480, 70)

    def test_overlapping_visible_window_covers(self):
        self.assertTrue(covering([Window("1", "a", geometry=(0, 300, 1280, 400))], self.dock))

    def test_hidden_or_distant_windows_do_not(self):
        wins = [Window("1", "a", geometry=(0, 300, 1280, 400), visible=False),
                Window("2", "b", geometry=(0, 0, 1280, 600)),
                Window("3", "c", geometry=None)]
        self.assertFalse(covering(wins, self.dock))


if __name__ == "__main__":
    unittest.main()
