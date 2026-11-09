"""Turning config entries / running windows into dock items."""

from __future__ import annotations

import os
import shlex
import time
from dataclasses import dataclass, field

import gi

gi.require_version("Gtk", "4.0")
from gi.repository import Gio  # noqa: E402

from .config import PinnedApp  # noqa: E402
from .windows import Window  # noqa: E402


@dataclass(eq=False)
class DockItem:
    name: str
    icon: Gio.Icon | None
    app_info: Gio.AppInfo | None
    match_keys: set[str]
    pinned: bool = True
    windows: list[Window] = field(default_factory=list)
    bounce_until: float = 0.0
    scale: float = 1.0  # animated current scale

    @property
    def running(self) -> bool:
        return bool(self.windows)

    def launch(self, display=None) -> bool:
        if not self.app_info:
            return False
        ctx = display.get_app_launch_context() if display else None
        try:
            ok = self.app_info.launch([], ctx)
        except Exception as exc:  # GLib.Error
            print(f"linux-magnify: failed to launch {self.name}: {exc}")
            return False
        if ok:
            self.bounce_until = time.monotonic() + 1.2
        return ok

    def matches(self, wm_class: str) -> bool:
        return wm_class.lower() in self.match_keys


def _keys_for(info: Gio.DesktopAppInfo | None, extra: list[str | None]) -> set[str]:
    keys: set[str] = set()
    if info is not None:
        did = info.get_id() or ""
        if did.endswith(".desktop"):
            did = did[:-8]
        keys.add(did)
        keys.add(did.split(".")[-1])  # org.kde.dolphin -> dolphin
        if info.get_startup_wm_class():
            keys.add(info.get_startup_wm_class())
        exe = info.get_executable()
        if exe:
            keys.add(os.path.basename(exe))
    for e in extra:
        if e:
            keys.add(e)
    return {k.lower() for k in keys if k}


def _desktop_info(desktop_id: str) -> Gio.DesktopAppInfo | None:
    did = desktop_id if desktop_id.endswith(".desktop") else desktop_id + ".desktop"
    try:
        return Gio.DesktopAppInfo.new(did)
    except TypeError:
        return None


def from_pinned(entry: PinnedApp) -> DockItem | None:
    if entry.exec:
        try:
            info = Gio.AppInfo.create_from_commandline(entry.exec, entry.name, Gio.AppInfoCreateFlags.NONE)
        except Exception:
            info = None
        icon = Gio.ThemedIcon.new(entry.icon) if entry.icon else Gio.ThemedIcon.new("application-x-executable")
        if entry.icon and os.path.isabs(entry.icon):
            icon = Gio.FileIcon.new(Gio.File.new_for_path(entry.icon))
        name = entry.name or shlex.split(entry.exec)[0]
        return DockItem(name, icon, info, _keys_for(None, [entry.wm_class, os.path.basename(shlex.split(entry.exec)[0])]))

    if not entry.desktop_id:
        return None
    info = _desktop_info(entry.desktop_id)
    if info is None:
        return None
    icon = info.get_icon()
    if entry.icon:
        icon = Gio.ThemedIcon.new(entry.icon)
    return DockItem(entry.name or info.get_display_name() or entry.desktop_id, icon, info,
                    _keys_for(info, [entry.wm_class]))


_wmclass_index: dict[str, Gio.DesktopAppInfo] | None = None


def _index() -> dict[str, Gio.DesktopAppInfo]:
    global _wmclass_index
    if _wmclass_index is None:
        idx: dict[str, Gio.DesktopAppInfo] = {}
        for info in Gio.AppInfo.get_all():
            if not isinstance(info, Gio.DesktopAppInfo):
                continue
            for key in _keys_for(info, []):
                idx.setdefault(key, info)
        _wmclass_index = idx
    return _wmclass_index


def from_window(win: Window) -> DockItem:
    cls = win.wm_class
    info = _desktop_info(cls) or _desktop_info(cls.lower()) or _index().get(cls.lower())
    if info is not None:
        item = DockItem(info.get_display_name() or cls, info.get_icon(), info, _keys_for(info, [cls]), pinned=False)
    else:
        item = DockItem(cls, Gio.ThemedIcon.new_with_default_fallbacks(cls.lower()), None, {cls.lower()}, pinned=False)
    return item
