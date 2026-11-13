"""The home button: copy the app-launcher icon from the desktop's own panel and
open the desktop's own app menu when clicked."""

from __future__ import annotations

import json
import os
import re
import shlex
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from . import menu
from .panels import _desktop, _gsettings, _run, kde_appletsrc_sources, kde_panel_applets, read_ini

MAGDOC_MENU = "magdoc:menu"

KDE_LAUNCHERS = ("org.kde.plasma.kickoff", "org.kde.plasma.kicker", "org.kde.plasma.kickerdash")
# App launchers for tiling compositors, in order of preference.
GENERIC_COMMANDS = (
    "fuzzel", "wofi --show drun", "rofi -show drun", "walker", "tofi-drun --drun-launch=true",
    "anyrun", "nwg-drawer", "xfce4-appfinder", "krunner", "dmenu_run",
)


@dataclass
class Launcher:
    icon: str          # icon name or absolute path
    command: str       # shell-style command, or "dbus:..." for built-in actions
    source: str        # human-readable description, shown in the settings app


def distro_logo() -> str:
    try:
        for line in Path("/etc/os-release").read_text().splitlines():
            if line.startswith("LOGO="):
                return line[5:].strip().strip('"') or "start-here"
    except OSError:
        pass
    return "start-here"


def _kde_icon() -> str | None:
    # The live layout first, then the backup taken before Magdoc removed the panel.
    for path in kde_appletsrc_sources():
        for _name, _sec, general in kde_panel_applets(read_ini(path), KDE_LAUNCHERS):
            return general.get("icon") or "start-here-kde"
    return None


def _kde_launcher_live() -> bool:
    """Is Plasma's own menu (Kickoff) still in a panel? It isn't once Magdoc removed the panels."""
    return any(True for _ in kde_panel_applets(read_ini(kde_appletsrc_sources()[0]), KDE_LAUNCHERS))


def _xfce() -> tuple[str, str] | None:
    listing = _run(["xfconf-query", "-c", "xfce4-panel", "-l", "-v"])
    if not listing:
        return None
    for m in re.finditer(r"^/plugins/(plugin-\d+)\s+(whiskermenu|applicationsmenu)\s*$", listing, re.M):
        plugin, kind = m.groups()
        icon = None
        for key in ("button-icon",):
            im = re.search(rf"^/plugins/{plugin}/{key}\s+(\S.*)$", listing, re.M)
            if im:
                icon = im.group(1).strip()
        if kind == "whiskermenu":
            return icon or "org.xfce.panel.whiskermenu", "xfce4-popup-whiskermenu"
        return icon or "org.xfce.panel.applicationsmenu", "xfce4-popup-applicationsmenu"
    return None


def _cinnamon_icon() -> str | None:
    base = Path(os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config")) / "cinnamon" / "spices"
    for f in sorted((base / "menu@cinnamon.org").glob("*.json")):
        try:
            data = json.loads(f.read_text())
        except (OSError, ValueError):
            continue
        icon = (data.get("menu-icon") or {}).get("value")
        if (data.get("menu-icon-custom") or {}).get("value") is False:
            icon = None
        return icon or "cinnamon-symbolic"
    return None


def _mate_icon() -> str | None:
    s = _gsettings("org.mate.panel")
    if s is None:
        return None
    for oid in s.get_strv("object-id-list"):
        o = _gsettings("org.mate.panel.object", f"/org/mate/panel/objects/{oid}/")
        if o is not None and o.get_string("object-type") == "menu":
            if o.get_boolean("use-custom-icon") and o.get_string("custom-icon"):
                return o.get_string("custom-icon")
            return "start-here"
    return None


def generic_command() -> str | None:
    for cmd in GENERIC_COMMANDS:
        if shutil.which(shlex.split(cmd)[0]):
            return cmd
    return None


def detect() -> Launcher:
    desk = _desktop()
    if "KDE" in desk:
        icon = _kde_icon()
        if menu.available():
            command = MAGDOC_MENU
        elif _kde_launcher_live():
            command = "dbus:kde-launcher"
        else:
            command = "krunner"  # Kickoff went away with the panel and Quickshell isn't installed
        return Launcher(icon or distro_logo(), command,
                        "Plasma app launcher" if icon else "Plasma (no launcher widget found)")
    if "XFCE" in desk:
        found = _xfce()
        if found:
            return Launcher(found[0], found[1], "Xfce panel menu")
    if "CINNAMON" in desk:
        return Launcher(_cinnamon_icon() or distro_logo(), "dbus:cinnamon-menu", "Cinnamon menu")
    if "GNOME" in desk or "UNITY" in desk or "BUDGIE" in desk:
        return Launcher(distro_logo(), "dbus:gnome-apps", "GNOME app grid")
    if "MATE" in desk:
        return Launcher(_mate_icon() or distro_logo(), generic_command() or "mate-panel --run-dialog", "MATE menu icon")
    if menu.available():
        return Launcher(distro_logo(), MAGDOC_MENU, "Magdoc menu")
    cmd = generic_command()
    return Launcher(distro_logo(), cmd or "", f"{shlex.split(cmd)[0]}" if cmd else "no app launcher found")


def resolve(icon_setting: str, command_setting: str) -> Launcher:
    auto = detect()
    icon = auto.icon if icon_setting in ("", "auto") else icon_setting
    command = auto.command if command_setting in ("", "auto") else command_setting
    return Launcher(icon, command, auto.source)


def _dbus_call(dest: str, path: str, iface: str, method: str, args=None) -> bool:
    try:
        from gi.repository import Gio
        bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
        bus.call_sync(dest, path, iface, method, args, None, Gio.DBusCallFlags.NONE, 3000, None)
        return True
    except Exception as exc:
        print(f"magdoc: home button: {exc}")
        return False


def activate(command: str) -> bool:
    if command == MAGDOC_MENU:
        if menu.toggle():
            return True
        command = "krunner" if "KDE" in _desktop() else (generic_command() or "")
    if command == "dbus:kde-launcher":
        return _dbus_call("org.kde.plasmashell", "/PlasmaShell", "org.kde.PlasmaShell", "activateLauncherMenu")
    if command == "dbus:gnome-apps":
        return _dbus_call("org.gnome.Shell", "/org/gnome/Shell", "org.gnome.Shell", "ShowApplications")
    if command == "dbus:cinnamon-menu":
        # Cinnamon opens its menu on the Super key; simulate it if xdotool is around.
        if shutil.which("xdotool"):
            command = "xdotool key super"
        else:
            command = generic_command() or ""
    if not command:
        return False
    try:
        subprocess.Popen(shlex.split(command), start_new_session=True, stdin=subprocess.DEVNULL,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return True
    except (OSError, ValueError) as exc:
        print(f"magdoc: home button command failed: {exc}")
        return False
