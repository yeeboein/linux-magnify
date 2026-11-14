import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from linux_magnify import icons

INDEX = "[Icon Theme]\nName={name}\nInherits=hicolor\nDirectories=scalable/apps\n\n[scalable/apps]\nSize=48\nType=Scalable\n"


class IconThemeTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        root = Path(self.dir.name)
        for name in ("Papirus-Dark", "breeze"):
            (root / "data" / "icons" / name).mkdir(parents=True)
            (root / "data" / "icons" / name / "index.theme").write_text(INDEX.format(name=name))
        (root / "cfg").mkdir()
        self.cfg = root / "cfg"
        self.env = mock.patch.dict(os.environ, {"XDG_DATA_HOME": str(root / "data"), "XDG_DATA_DIRS": str(root / "none"),
                                                "XDG_CONFIG_HOME": str(self.cfg), "HOME": str(root),
                                                "XDG_CURRENT_DESKTOP": "KDE"})
        self.env.start()

    def tearDown(self):
        self.env.stop()
        self.dir.cleanup()

    def test_kde_icon_pack_is_followed(self):
        (self.cfg / "kdeglobals").write_text("[General]\nfoo=1\n\n[Icons]\nTheme=Papirus-Dark\n")
        self.assertEqual(icons.desktop_theme(), "Papirus-Dark")
        self.assertEqual(icons.resolve("auto"), "Papirus-Dark")

    def test_plasma_default_is_breeze(self):
        self.assertEqual(icons.desktop_theme(), "breeze")

    def test_missing_theme_is_ignored(self):
        (self.cfg / "kdeglobals").write_text("[Icons]\nTheme=Uninstalled\n")
        self.assertIsNone(icons.desktop_theme())  # nothing installed matches -> leave GTK's default alone

    def test_explicit_choice_wins(self):
        (self.cfg / "kdeglobals").write_text("[Icons]\nTheme=Papirus-Dark\n")
        self.assertEqual(icons.resolve("breeze"), "breeze")

    def test_installed_themes(self):
        self.assertEqual(icons.installed_themes(), ["breeze", "Papirus-Dark"])


if __name__ == "__main__":
    unittest.main()
