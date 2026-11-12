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
    geometry: tuple[int, int, int, int] | None = None  # x, y, w, h in global (logical) coordinates
    visible: bool = True  # on the current workspace and not minimised

    def key(self):
        return (self.wid, self.wm_class, self.focused, self.geometry, self.visible)


def overlaps(a: tuple[int, int, int, int], b: tuple[int, int, int, int]) -> bool:
    return a[0] < b[0] + b[2] and b[0] < a[0] + a[2] and a[1] < b[1] + b[3] and b[1] < a[1] + a[3]


def covering(windows: list[Window], rect: tuple[int, int, int, int]) -> bool:
    """True when a visible window overlaps ``rect`` (the dock's area on screen)."""
    return any(w.visible and w.geometry and overlaps(w.geometry, rect) for w in windows)


def _run(cmd: list[str], timeout: float = 1.5) -> str | None:
    try:
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.SubprocessError):
        return None
    return res.stdout if res.returncode == 0 else None


class Backend:
    name = "none"

    def close(self):
        pass

    on_change = None  # optional callback(list[Window]) for push-style backends
    has_geometry = False

    def list_windows(self) -> list[Window]:
        return []

    def focus(self, win: Window) -> bool:
        return False


class HyprlandBackend(Backend):
    name = "hyprland"
    has_geometry = True

    def list_windows(self) -> list[Window]:
        out = _run(["hyprctl", "-j", "clients"])
        if not out:
            return []
        try:
            clients = json.loads(out)
            monitors = json.loads(_run(["hyprctl", "-j", "monitors"]) or "[]")
        except json.JSONDecodeError:
            return []
        active = set()
        for m in monitors:
            for key in ("activeWorkspace", "specialWorkspace"):
                ws = m.get(key) or {}
                if ws.get("id"):
                    active.add(ws["id"])
        wins = []
        for c in clients:
            if not c.get("mapped", True):
                continue
            at, size = c.get("at") or [0, 0], c.get("size") or [0, 0]
            wins.append(Window(
                c["address"], c.get("class") or c.get("initialClass") or "", c.get("title", ""),
                c.get("focusHistoryID") == 0, (at[0], at[1], size[0], size[1]),
                (c.get("workspace") or {}).get("id") in active and not c.get("hidden", False)))
        return wins

    def focus(self, win: Window) -> bool:
        return _run(["hyprctl", "dispatch", "focuswindow", f"address:{win.wid}"]) is not None


class SwayBackend(Backend):
    """Sway and other i3-IPC compositors that ship swaymsg."""

    name = "sway"
    has_geometry = True

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
                r = node.get("rect") or {}
                geom = (r.get("x", 0), r.get("y", 0), r.get("width", 0), r.get("height", 0))
                wins.append(Window(str(node["id"]), cls, node.get("name") or "", node.get("focused", False),
                                   geom, node.get("visible", True)))
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
    has_geometry = True

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
        try:
            cur = self._root.get_full_property(self._atom("_NET_CURRENT_DESKTOP"), X.AnyPropertyType)
            current_desktop = cur.value[0] if cur and len(cur.value) else 0
        except Exception:
            current_desktop = 0
        hidden_atom = self._atom("_NET_WM_STATE_HIDDEN")
        skip_types = {self._atom(f"_NET_WM_WINDOW_TYPE_{t}") for t in ("DOCK", "DESKTOP", "SPLASH", "NOTIFICATION")}
        type_atom, pid_atom = self._atom("_NET_WM_WINDOW_TYPE"), self._atom("_NET_WM_PID")
        me = os.getpid()
        wins = []
        skip = self._atom("_NET_WM_STATE_SKIP_TASKBAR")
        for xid in (prop.value if prop else []):
            try:
                w = d.create_resource_object("window", xid)
                state = w.get_full_property(self._atom("_NET_WM_STATE"), X.AnyPropertyType)
                if state and skip in state.value:
                    continue
                wtype = w.get_full_property(type_atom, X.AnyPropertyType)
                if wtype and skip_types & set(wtype.value):
                    continue
                pid = w.get_full_property(pid_atom, X.AnyPropertyType)
                if pid and len(pid.value) and pid.value[0] == me:
                    continue  # the dock itself
                cls = w.get_wm_class() or ("", "")
                name = w.get_wm_name() or ""
                g = w.get_geometry()
                pos = w.translate_coords(self._root, 0, 0)
                geom = (-pos.x, -pos.y, g.width, g.height)
                desk = w.get_full_property(self._atom("_NET_WM_DESKTOP"), X.AnyPropertyType)
                desk = desk.value[0] if desk and len(desk.value) else current_desktop
                visible = (desk in (current_desktop, 0xFFFFFFFF)
                           and not (state and hidden_atom in state.value))
            except Exception:
                continue
            wins.append(Window(str(xid), cls[1] or cls[0], str(name), xid == active_id, geom, visible))
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


KWIN_REPORT_SCRIPT = r"""
// Loaded into KWin by linux-magnify: reports windows (class, geometry, desktop) over D-Bus.
var SVC = "io.github.linux_magnify.Dock";
function all() { return workspace.windowList ? workspace.windowList() : workspace.clientList(); }
function onDesk(w) {
    if (w.onAllDesktops) return true;
    if (w.desktops !== undefined) return w.desktops.indexOf(workspace.currentDesktop) >= 0;
    return w.desktop == workspace.currentDesktop;
}
function report() {
    var out = [], list = all();
    for (var i = 0; i < list.length; i++) {
        var w = list[i];
        if (!w.normalWindow || w.skipTaskbar) continue;
        var g = w.frameGeometry;
        out.push({id: String(w.internalId), cls: String(w.resourceClass || ""), title: String(w.caption || ""),
                  x: g.x, y: g.y, w: g.width, h: g.height,
                  visible: onDesk(w) && !w.minimized, active: !!w.active});
    }
    callDBus(SVC, "/Dock", SVC, "Windows", JSON.stringify(out));
}
function watch(w) {
    if (w.frameGeometryChanged) w.frameGeometryChanged.connect(report);
    if (w.minimizedChanged) w.minimizedChanged.connect(report);
    if (w.desktopsChanged) w.desktopsChanged.connect(report);
    else if (w.desktopChanged) w.desktopChanged.connect(report);
}
all().forEach(watch);
(workspace.windowAdded || workspace.clientAdded).connect(function (w) { watch(w); report(); });
(workspace.windowRemoved || workspace.clientRemoved).connect(report);
(workspace.windowActivated || workspace.clientActivated).connect(report);
workspace.currentDesktopChanged.connect(report);
report();
"""

KWIN_FOCUS_SCRIPT = r"""
var list = workspace.windowList ? workspace.windowList() : workspace.clientList();
for (var i = 0; i < list.length; i++) {
    if (String(list[i].internalId) == "%s") {
        if (list[i].minimized) list[i].minimized = false;
        if (workspace.activeWindow !== undefined) workspace.activeWindow = list[i];
        else workspace.activeClient = list[i];
    }
}
"""

DOCK_DBUS_XML = """
<node>
  <interface name="io.github.linux_magnify.Dock">
    <method name="Windows"><arg type="s" name="json" direction="in"/></method>
  </interface>
</node>
"""


class KWinBackend(Backend):
    """KDE Plasma (Wayland or X11): a KWin script pushes the window list to us over D-Bus."""

    name = "kwin"
    has_geometry = True
    SCRIPT_NAME = "linux-magnify-windows"

    def __init__(self):
        from gi.repository import Gio, GLib

        from .panels import state_dir

        self._Gio, self._GLib = Gio, GLib
        self._wins: list[Window] = []
        self._bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
        node = Gio.DBusNodeInfo.new_for_xml(DOCK_DBUS_XML)
        self._reg = self._bus.register_object("/Dock", node.interfaces[0], self._on_call, None, None)
        self._owner = Gio.bus_own_name_on_connection(self._bus, "io.github.linux_magnify.Dock",
                                                     Gio.BusNameOwnerFlags.REPLACE, None, None)
        self._dir = state_dir()
        self._dir.mkdir(parents=True, exist_ok=True)
        path = self._dir / "kwin-windows.js"
        path.write_text(KWIN_REPORT_SCRIPT)
        if not self._run_script(str(path), self.SCRIPT_NAME):
            self.close()
            raise RuntimeError("KWin scripting is not available")

    # -- KWin scripting over D-Bus
    def _kwin(self, path: str, iface: str, method: str, args=None, reply=None):
        return self._bus.call_sync("org.kde.KWin", path, iface, method, args,
                                   self._GLib.VariantType(reply) if reply else None,
                                   self._Gio.DBusCallFlags.NONE, 3000, None)

    def _run_script(self, path: str, name: str) -> bool:
        V = self._GLib.Variant
        try:
            loaded = self._kwin("/Scripting", "org.kde.kwin.Scripting", "isScriptLoaded",
                                V("(s)", (name,)), "(b)").unpack()[0]
            if loaded:
                self._kwin("/Scripting", "org.kde.kwin.Scripting", "unloadScript", V("(s)", (name,)), "(b)")
            sid = self._kwin("/Scripting", "org.kde.kwin.Scripting", "loadScript",
                             V("(ss)", (path, name)), "(i)").unpack()[0]
        except Exception as exc:
            print(f"linux-magnify: KWin scripting failed: {exc}")
            return False
        for obj in (f"/Scripting/Script{sid}", f"/{sid}"):  # Plasma 6, Plasma 5
            try:
                self._kwin(obj, "org.kde.kwin.Script", "run")
                return True
            except Exception:
                continue
        return False

    def _on_call(self, _conn, _sender, _path, _iface, method, params, invocation):
        if method == "Windows":
            try:
                data = json.loads(params.unpack()[0])
            except (ValueError, TypeError):
                data = []
            self._wins = [Window(d["id"], d.get("cls", ""), d.get("title", ""), bool(d.get("active")),
                                 (int(d["x"]), int(d["y"]), int(d["w"]), int(d["h"])), bool(d.get("visible", True)))
                          for d in data]
            if self.on_change:
                self.on_change(list(self._wins))
        invocation.return_value(None)

    def list_windows(self) -> list[Window]:
        return list(self._wins)

    def focus(self, win: Window) -> bool:
        path = self._dir / "kwin-focus.js"
        path.write_text(KWIN_FOCUS_SCRIPT % win.wid.replace('"', ""))
        ok = self._run_script(str(path), "linux-magnify-focus")
        self._GLib.timeout_add(1500, self._unload, "linux-magnify-focus")
        return ok

    def _unload(self, name: str):
        try:
            self._kwin("/Scripting", "org.kde.kwin.Scripting", "unloadScript",
                       self._GLib.Variant("(s)", (name,)), "(b)")
        except Exception:
            pass
        return False

    def close(self):
        self._unload(self.SCRIPT_NAME)
        try:
            self._bus.unregister_object(self._reg)
            self._Gio.bus_unown_name(self._owner)
        except Exception:
            pass


def detect(x11_session: bool) -> Backend:
    env = os.environ
    candidates: list[type[Backend]] = []
    if env.get("HYPRLAND_INSTANCE_SIGNATURE") and shutil.which("hyprctl"):
        candidates.append(HyprlandBackend)
    if env.get("SWAYSOCK") and shutil.which("swaymsg"):
        candidates.append(SwayBackend)
    if env.get("NIRI_SOCKET") and shutil.which("niri"):
        candidates.append(NiriBackend)
    kde = "KDE" in env.get("XDG_CURRENT_DESKTOP", "").upper()
    if kde and not x11_session:
        candidates.append(KWinBackend)
    if x11_session:
        candidates.append(X11Backend)
    if kde and shutil.which("kdotool"):
        candidates.append(KdotoolBackend)
    for cls in candidates:
        try:
            return cls()
        except Exception:
            continue
    return Backend()
