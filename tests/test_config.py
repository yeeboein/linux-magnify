import tempfile
import unittest
from pathlib import Path

from linux_magnify.config import load


class ConfigTest(unittest.TestCase):
    def test_defaults_when_missing(self):
        cfg = load(Path("/nonexistent/config.toml"), import_pins=False)
        self.assertEqual(cfg.position, "bottom")
        self.assertEqual(cfg.pinned, [])  # pins are imported from the panel only when asked
        self.assertEqual(cfg.hide_mode, "auto")

    def test_parse(self):
        with tempfile.NamedTemporaryFile("w", suffix=".toml", delete=False) as fh:
            fh.write('[dock]\nposition = "left"\nicon_size = 64\nmagnification = 9\n'
                     '[style]\ncorner_radius = 4\n'
                     '[apps]\npinned = ["firefox", { name = "Htop", exec = "kitty htop", icon = "utilities-system-monitor" }]\n')
        cfg = load(Path(fh.name))
        self.assertEqual(cfg.position, "left")
        self.assertEqual(cfg.icon_size, 64)
        self.assertEqual(cfg.magnification, 4.0)  # clamped
        self.assertEqual(cfg.corner_radius, 4.0)
        self.assertEqual(cfg.pinned[0].desktop_id, "firefox")
        self.assertEqual(cfg.pinned[1].exec, "kitty htop")
        Path(fh.name).unlink()


if __name__ == "__main__":
    unittest.main()
