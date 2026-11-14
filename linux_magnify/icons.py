"""Use the desktop's icon theme (icon pack) in the dock, start menu and settings.

GTK and Quickshell apps don't read KDE's icon setting on their own, so without
this they fall back to the default icons, which makes your icon pack look like
it disappeared. This reads the theme the desktop uses and hands it to GTK
(``gtk-icon-theme-name``) and Quickshell (``QS_ICON_THEME``).
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

from .panels import _desktop, _gsettings, read_ini


def _config_home() -> Path:
    return Path(os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config"))


def kdeglobals() -> Path:
    return _config_home() / "kdeglobals"


def icon_dirs() -> list[Path]:
    data_home = os.environ.get("XDG_DATA_HOME") or os.path.expanduser("~/.local/share")
    dirs = [Path(data_home) / "icons", Path(os.path.expanduser("~/.icons"))]
    dirs += [Path(d) / "icons" for d in (os.environ.get("XDG_DATA_DIRS") or "/usr/local/share:/usr/share").split(":") if d]
    dirs.append(Path("/usr/share/pixmaps"))
    return dirs


def installed_themes() -> list[str]:
    """Icon themes on this system (folders with an index.theme that list icon directories)."""
    found: dict[str, str] = {}
    for base in icon_dirs():
        try:
            entries = list(base.iterdir())
        except OSError:
            continue
        for d in entries:
            index = d / "index.theme"
            if d.name in found or d.name in ("hicolor", "locolor", "default") or not index.is_file():
                continue
            ini = read_ini(index).get("Icon Theme", {})
            if ini.get("Directories") and ini.get("Hidden", "false").lower() != "true":
                found[d.name] = ini.get("Name", d.name)
    return sorted(found, key=str.lower)


def theme_exists(name: str) -> bool:
    return any((d / name / "index.theme").is_file() for d in icon_dirs())


def _gtk_settings_theme() -> str | None:
    for ver in ("gtk-4.0", "gtk-3.0"):
        value = read_ini(_config_home() / ver / "settings.ini").get("Settings", {}).get("gtk-icon-theme-name")
        if value:
            return value.strip().strip('"')
    return None


def desktop_theme() -> str | None:
    """The icon theme the desktop is using right now, if it can be found."""
    desk = _desktop()
    candidates: list[str | None] = []
    if "KDE" in desk:
        # System Settings -> Colors & Themes -> Icons. Plasma's default is breeze.
        candidates.append(read_ini(kdeglobals()).get("Icons", {}).get("Theme") or "breeze")
    for schema, key, wanted in (("org.cinnamon.desktop.interface", "icon-theme", "CINNAMON"),
                                ("org.mate.interface", "icon-theme", "MATE"),
                                ("org.gnome.desktop.interface", "icon-theme", "")):
        if wanted and wanted not in desk:
            continue
        s = _gsettings(schema)
        if s is not None:
            candidates.append(s.get_string(key))
    if "XFCE" in desk:
        try:
            out = subprocess.run(["xfconf-query", "-c", "xsettings", "-p", "/Net/IconThemeName"],
                                 capture_output=True, text=True, timeout=3).stdout.strip()
            candidates.insert(0, out or None)
        except (OSError, subprocess.SubprocessError):
            pass
    candidates.append(_gtk_settings_theme())
    for name in candidates:
        if name and theme_exists(name):
            return name
    return None


def resolve(setting: str) -> str | None:
    """``setting`` is "auto" (follow the desktop) or an icon theme name."""
    if setting and setting != "auto" and theme_exists(setting):
        return setting
    return desktop_theme()


def apply_to_gtk(setting: str) -> str | None:
    """Make GTK (the dock and the GTK settings app) use the theme. Returns the theme used."""
    theme = resolve(setting)
    if theme:
        from gi.repository import Gtk

        settings = Gtk.Settings.get_default()
        if settings is not None and settings.get_property("gtk-icon-theme-name") != theme:
            settings.set_property("gtk-icon-theme-name", theme)
    return theme


def watch(callback):
    """Call ``callback()`` when the desktop's icon theme may have changed (KDE: kdeglobals)."""
    from gi.repository import Gio

    monitors = []
    for path in (kdeglobals(), _config_home() / "gtk-4.0" / "settings.ini", _config_home() / "gtk-3.0" / "settings.ini"):
        try:
            m = Gio.File.new_for_path(str(path)).monitor_file(Gio.FileMonitorFlags.NONE, None)
        except Exception:
            continue
        m.connect("changed", lambda *_: callback())
        monitors.append(m)
    s = _gsettings("org.gnome.desktop.interface")
    if s is not None:
        s.connect("changed::icon-theme", lambda *_: callback())
        monitors.append(s)
    return monitors  # keep a reference, or the monitors stop
