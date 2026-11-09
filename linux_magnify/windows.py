"""Running-window tracking and focusing, per compositor / desktop.

Each backend returns a list of :class:`Window` objects and can focus one.
Window "classes" are compared case-insensitively against an app's match keys
(desktop id, StartupWMClass, executable name).
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from dataclasses import dataclass


@dataclass
class Window:
    wid: str
    wm_class: str
    title: str = ""
    focused: bool = False


def _run(cmd: list[str], timeout: float = 1.5) -> str | None:
    try:
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.SubprocessError):
        return None
    return res.stdout if res.returncode == 0 else None


class Backend:
    name = "none"

    def list_windows(self) -> list[Window]:
        return []

    def focus(self, win: Window) -> bool:
        return False


class HyprlandBackend(Backend):
    name = "hyprland"

    def list_windows(self) -> list[Window]:
        out = _run(["hyprctl", "-j", "clients"])
        if not out:
            return []
        try:
            clients = json.loads(out)
        except json.JSONDecodeError:
            return []
        return [
            Window(c["address"], c.get("class") or c.get("initialClass") or "",
                   c.get("title", ""), c.get("focusHistoryID") == 0)
            for c in clients if c.get("mapped", True)
        ]

    def focus(self, win: Window) -> bool:
        return _run(["hyprctl", "dispatch", "focuswindow", f"address:{win.wid}"]) is not None


class SwayBackend(Backend):
    """Sway and other i3-IPC compositors that ship swaymsg."""

    name = "sway"

    def list_windows(self) -> list[Window]:
        out = _run(["swaymsg", "-t", "get_tree", "-r"])
        if not out:
            return []
        try:
            tree = json.loads(out)
        except json.JSONDecodeError:
            return []
        wins: list[Window] = []

        def walk(node):
            if node.get("pid") and node.get("type") in ("con", "floating_con"):
                cls = node.get("app_id") or (node.get("window_properties") or {}).get("class") or ""
                wins.append(Window(str(node["id"]), cls, node.get("name") or "", node.get("focused", False)))
            for child in node.get("nodes", []) + node.get("floating_nodes", []):
                walk(child)

        walk(tree)
        return wins

    def focus(self, win: Window) -> bool:
        return _run(["swaymsg", f"[con_id={win.wid}]", "focus"]) is not None


class NiriBackend(Backend):
    name = "niri"

    def list_windows(self) -> list[Window]:
        out = _run(["niri", "msg", "--json", "windows"])
        if not out:
            return []
        try:
            data = json.loads(out)
        except json.JSONDecodeError:
            return []
        return [Window(str(w["id"]), w.get("app_id") or "", w.get("title") or "", w.get("is_focused", False))
                for w in data]

    def focus(self, win: Window) -> bool:
        return _run(["niri", "msg", "action", "focus-window", "--id", win.wid]) is not None


class KdotoolBackend(Backend):
    """KDE Plasma (Wayland) via the third-party ``kdotool`` utility."""

    name = "kdotool"

    def list_windows(self) -> list[Window]:
        out = _run(["kdotool", "search", "--class", "."], timeout=3)
        if not out:
            return []
        wins = []
        for wid in out.split():
            cls = (_run(["kdotool", "getwindowclassname", wid]) or "").strip()
            wins.append(Window(wid, cls))
        return wins

    def focus(self, win: Window) -> bool:
        return _run(["kdotool", "windowactivate", win.wid]) is not None


class X11Backend(Backend):
    """Any EWMH-compliant X11 window manager (XFCE, Cinnamon, MATE, KDE/X11, ...)."""

    name = "x11"

    def __init__(self):
        from Xlib import X, display  # noqa: F401  (import check)
        from Xlib.protocol import event  # noqa: F401

        self._display = display.Display()
        self._root = self._display.screen().root
        self._atom = self._display.intern_atom

    def list_windows(self) -> list[Window]:
        from Xlib import X

        d = self._display
        try:
            prop = self._root.get_full_property(self._atom("_NET_CLIENT_LIST"), X.AnyPropertyType)
            active = self._root.get_full_property(self._atom("_NET_ACTIVE_WINDOW"), X.AnyPropertyType)
        except Exception:
            return []
        active_id = active.value[0] if active and len(active.value) else None
        wins = []
        skip = self._atom("_NET_WM_STATE_SKIP_TASKBAR")
        for xid in (prop.value if prop else []):
            try:
                w = d.create_resource_object("window", xid)
                state = w.get_full_property(self._atom("_NET_WM_STATE"), X.AnyPropertyType)
                if state and skip in state.value:
                    continue
                cls = w.get_wm_class() or ("", "")
                name = w.get_wm_name() or ""
            except Exception:
                continue
            wins.append(Window(str(xid), cls[1] or cls[0], str(name), xid == active_id))
        return wins

    def focus(self, win: Window) -> bool:
        from Xlib import X
        from Xlib.protocol import event

        try:
            w = self._display.create_resource_object("window", int(win.wid))
            ev = event.ClientMessage(window=w, client_type=self._atom("_NET_ACTIVE_WINDOW"),
                                     data=(32, [2, X.CurrentTime, 0, 0, 0]))
            self._root.send_event(ev, event_mask=X.SubstructureRedirectMask | X.SubstructureNotifyMask)
            self._display.flush()
            return True
        except Exception:
            return False


def detect(x11_session: bool) -> Backend:
    env = os.environ
    candidates: list[type[Backend]] = []
    if env.get("HYPRLAND_INSTANCE_SIGNATURE") and shutil.which("hyprctl"):
        candidates.append(HyprlandBackend)
    if env.get("SWAYSOCK") and shutil.which("swaymsg"):
        candidates.append(SwayBackend)
    if env.get("NIRI_SOCKET") and shutil.which("niri"):
        candidates.append(NiriBackend)
    if x11_session:
        candidates.append(X11Backend)
    if "KDE" in env.get("XDG_CURRENT_DESKTOP", "").upper() and shutil.which("kdotool"):
        candidates.append(KdotoolBackend)
    for cls in candidates:
        try:
            return cls()
        except Exception:
            continue
    return Backend()
