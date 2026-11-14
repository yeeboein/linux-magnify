"""JSON endpoints used by the Quickshell settings app (and handy in scripts).

They print JSON on stdout and never import GTK, so they work from any process.
"""

from __future__ import annotations

import json
from pathlib import Path

from . import __version__, control
from .config import (DOCK_KEYS, HIDE_MODES, HIDE_PANEL_MODES, HOME_KEYS, POSITIONS, STYLE_KEYS, UPDATE_KEYS,
                     Config, PinnedApp, _coerce, _parse_pinned, load, save)

HOME_ATTRS = tuple(HOME_KEYS.values()) + tuple(UPDATE_KEYS.values())


def _icon_name(gicon) -> str:
    from gi.repository import Gio

    if isinstance(gicon, Gio.ThemedIcon) and gicon.get_names():
        return gicon.get_names()[0]
    if isinstance(gicon, Gio.FileIcon):
        return gicon.get_file().get_path() or ""
    return "application-x-executable"


def _raw(p: PinnedApp) -> dict:
    return {k: v for k, v in (("id", p.desktop_id), ("name", p.name), ("exec", p.exec),
                              ("icon", p.icon), ("wm_class", p.wm_class)) if v}


def config_json(path: Path | None) -> dict:
    from . import apps, home

    cfg = load(path)
    data = {k: getattr(cfg, k) for k in DOCK_KEYS + STYLE_KEYS + HOME_ATTRS}
    data["pinned"] = [_raw(p) for p in cfg.pinned]
    display = []
    for p in cfg.pinned:
        item = apps.from_pinned(p)
        display.append({"name": item.name if item else (p.name or p.desktop_id or p.exec or "?"),
                        "icon": _icon_name(item.icon) if item and item.icon else "dialog-warning",
                        "installed": item is not None})
    data["pinned_display"] = display
    data["pinned_imported"] = cfg.pinned_imported
    launcher = home.detect()
    data["home_detected"] = {
        "icon": launcher.icon, "source": launcher.source,
        "command": ("Magdoc start menu" if launcher.command == home.MAGDOC_MENU
                    else "your desktop's own app menu" if launcher.command.startswith("dbus:")
                    else launcher.command or "none"),
    }
    data["choices"] = {"position": list(POSITIONS), "hide_mode": list(HIDE_MODES),
                       "hide_panels": list(HIDE_PANEL_MODES)}
    data["config_path"] = str(cfg.path)
    data["version"] = __version__
    return data


def config_set(path: Path | None, changes: dict) -> None:
    cfg = load(path)
    defaults = Config()
    for key, value in changes.items():
        if key == "pinned":
            if value == "import":
                from .panels import import_pinned
                ids = import_pinned()
                if not ids:
                    continue
                cfg.pinned = [PinnedApp(desktop_id=i) for i in ids]
            else:
                cfg.pinned = _parse_pinned(value)
            cfg.pinned_imported = False
            cfg.pinned_is_default = False  # type: ignore[attr-defined]
        elif key in DOCK_KEYS or key in STYLE_KEYS or key in HOME_ATTRS:
            setattr(cfg, key, _coerce(getattr(defaults, key), value))
    save(cfg, path)


def apps_json() -> list[dict]:
    from gi.repository import Gio

    out = []
    for info in Gio.AppInfo.get_all():
        if not (info.should_show() and isinstance(info, Gio.DesktopAppInfo)):
            continue
        did = info.get_id() or ""
        out.append({"id": did[:-8] if did.endswith(".desktop") else did,
                    "name": info.get_display_name() or did,
                    "icon": _icon_name(info.get_icon()) if info.get_icon() else "application-x-executable"})
    return sorted(out, key=lambda a: a["name"].lower())


def status_json() -> dict:
    return control.status()


def updates_json(path: Path | None, check: bool) -> dict:
    from . import updates

    cfg = load(path, import_pins=False)
    st = updates.check(cfg.update_branch) if check else dict(updates.read_state())
    st.setdefault("installed", updates.installed_commit())
    st["version"] = __version__
    return st


def dump(obj) -> None:
    print(json.dumps(obj))
