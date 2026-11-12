"""The desktop's own panel/dock: hide it while linux-magnify runs, restore it
afterwards, and copy its pinned apps.

Everything that gets changed is written to a state file *before* it is
changed, so ``restore()`` works even after a crash or a reboot
(``linux-magnify --restore-panels``).
"""

from __future__ import annotations

import json
import os
import re
import shutil
import signal
import subprocess
import time
from pathlib import Path
from urllib.parse import unquote, urlparse

# Stand-alone docks: stopped in "dock" and "all" mode.
DOCK_PROCESSES = ("plank", "latte-dock", "cairo-dock", "nwg-dock-hyprland", "nwg-dock", "docky",
                  "dockx", "crystal-dock")
# Bars/panels that are separate programs: stopped only in "all" mode.
BAR_PROCESSES = ("waybar", "polybar", "tint2", "ironbar", "sfwbar", "hyprpanel", "lxpanel")
DOCK_EXTENSIONS = ("dash-to-dock@micxgx.gmail.com", "ubuntu-dock@ubuntu.com",
                   "dash2dock-lite@icedman.github.com", "dash-to-dock-cosmic-@halfmexicanhalfamazing@gmail.com")
PANEL_EXTENSIONS = ("dash-to-panel@jderose9.github.com",)

# xfce4-panel "p=" snap positions -> screen edge
_XFCE_EDGES = {1: "right", 2: "top", 3: "right", 4: "bottom", 5: "left", 6: "top", 7: "left",
               8: "bottom", 9: "top", 10: "top", 11: "bottom", 12: "bottom"}


def _desktop() -> str:
    return os.environ.get("XDG_CURRENT_DESKTOP", "").upper()


def state_dir() -> Path:
    base = os.environ.get("XDG_STATE_HOME") or os.path.expanduser("~/.local/state")
    return Path(base) / "linux-magnify"


def _state_file() -> Path:
    return state_dir() / "hidden-panels.json"


def _run(cmd: list[str], timeout: float = 5) -> str | None:
    try:
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.SubprocessError):
        return None
    return res.stdout if res.returncode == 0 else None


# --------------------------------------------------------------------- ini
def read_ini(path: Path) -> dict[str, dict[str, str]]:
    """Tiny KDE/XDG ini reader that keeps section names like
    ``Containments][2][Applets][5`` intact and keys case-sensitive."""
    sections: dict[str, dict[str, str]] = {}
    cur: dict[str, str] | None = None
    try:
        text = path.read_text(errors="replace")
    except OSError:
        return sections
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith(("#", ";")):
            continue
        if line.startswith("[") and line.endswith("]"):
            cur = sections.setdefault(line[1:-1], {})
        elif "=" in line and cur is not None:
            k, v = line.split("=", 1)
            cur[k.strip()] = v.strip()
    return sections


def _gio():
    import gi

    from gi.repository import Gio, GLib
    return Gio, GLib


def _gsettings(schema: str, path: str | None = None):
    Gio, _ = _gio()
    src = Gio.SettingsSchemaSource.get_default()
    if src is None or src.lookup(schema, True) is None:
        return None
    return Gio.Settings.new_with_path(schema, path) if path else Gio.Settings.new(schema)


# ===================================================================== KDE
def _kde_appletsrc() -> Path:
    base = os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config")
    return Path(base) / "plasma-org.kde.plasma.desktop-appletsrc"


def kde_panel_applets(ini: dict[str, dict[str, str]], plugins: tuple[str, ...]):
    """Yield (applet_section, applet_dict, general_config) for applets with one of
    ``plugins`` that live in a panel, in file order."""
    for name, sec in ini.items():
        m = re.fullmatch(r"Containments\]\[(\d+)\]\[Applets\]\[(\d+)", name)
        if not m or sec.get("plugin") not in plugins:
            continue
        cont = ini.get(f"Containments][{m.group(1)}", {})
        if cont.get("plugin") != "org.kde.panel":
            continue
        general = ini.get(f"{name}][Configuration][General", {})
        yield name, sec, general


def _plasma_eval(script: str) -> str | None:
    try:
        Gio, GLib = _gio()
        bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
        res = bus.call_sync("org.kde.plasmashell", "/PlasmaShell", "org.kde.PlasmaShell",
                            "evaluateScript", GLib.Variant("(s)", (script,)),
                            GLib.VariantType("(s)"), Gio.DBusCallFlags.NONE, 8000, None)
        return res.unpack()[0]
    except Exception as exc:
        print(f"linux-magnify: plasmashell scripting failed: {exc}")
        return None


_KDE_MODES = {"none": "never", "autohide": "always", "dodgewindows": "dodge",
              "windowsgobelow": "never", "windowscover": "never"}


def _hide_kde(edge: str, mode: str, state: list, dry: bool = False):
    out = _plasma_eval("var o = []; panels().forEach(function (p) {"
                       " o.push(p.id + '|' + p.hiding + '|' + p.location); }); print(o.join(';'));")
    if not out or not out.strip():
        return
    found = [item.split("|") for item in out.strip().split(";") if item.count("|") == 2]
    edge_modes = [_KDE_MODES.get(h, "never") for _id, h, loc in found if loc == edge]
    targets = {pid: h for pid, h, loc in found if mode == "all" or loc == edge}
    if not targets and not edge_modes:
        return
    _push(state, {"kind": "kde", "panels": targets, "modes": edge_modes}, dry)
    if dry or not targets:
        return
    ids = json.dumps([int(t) for t in targets])
    _plasma_eval(f"var ids = {ids}; panels().forEach(function (p) {{"
                 " if (ids.indexOf(p.id) >= 0) p.hiding = 'autohide'; });")


def _restore_kde(entry: dict):
    if not entry.get("panels"):
        return
    mapping = json.dumps(entry["panels"])
    _plasma_eval(
        f"var m = {mapping};"
        "panels().forEach(function (p) { if (m[p.id] !== undefined) p.hiding = m[p.id]; });"
    )


# ================================================================ Cinnamon
_CINNAMON_MODES = {"false": "never", "true": "always", "intel": "dodge"}


def _hide_cinnamon(edge: str, mode: str, state: list, dry: bool = False):
    s = _gsettings("org.cinnamon")
    if s is None:
        return
    enabled = list(s.get_strv("panels-enabled"))  # "id:monitor:position"
    autohide = list(s.get_strv("panels-autohide"))  # "id:true|false|intel"
    values = {a.split(":")[0]: a.split(":")[-1] for a in autohide if ":" in a}
    parts = [e.split(":") for e in enabled if len(e.split(":")) >= 3]
    edge_modes = [_CINNAMON_MODES.get(values.get(p[0], "false"), "never") for p in parts if p[2] == edge]
    targets = [p[0] for p in parts if mode == "all" or p[2] == edge]
    if not targets and not edge_modes:
        return
    _push(state, {"kind": "cinnamon", "panels-autohide": autohide, "modes": edge_modes}, dry)
    if dry or not targets:
        return
    current = {a.split(":")[0]: a for a in autohide}
    for pid in targets:
        current[pid] = f"{pid}:true"
    s.set_strv("panels-autohide", list(current.values()))
    s.sync()


def _restore_cinnamon(entry: dict):
    s = _gsettings("org.cinnamon")
    if s is not None:
        s.set_strv("panels-autohide", entry["panels-autohide"])
        s.sync()


# ==================================================================== MATE
def _hide_mate(edge: str, mode: str, state: list, dry: bool = False):
    s = _gsettings("org.mate.panel")
    if s is None:
        return
    changed, edge_modes = {}, []
    for tid in s.get_strv("toplevel-id-list"):
        t = _gsettings("org.mate.panel.toplevel", f"/org/mate/panel/toplevels/{tid}/")
        if t is None:
            continue
        on_edge = t.get_string("orientation") == edge
        if on_edge:
            edge_modes.append("always" if t.get_boolean("auto-hide") else "never")
        if mode == "all" or on_edge:
            changed[tid] = t.get_boolean("auto-hide")
    if not changed and not edge_modes:
        return
    _push(state, {"kind": "mate", "auto-hide": changed, "modes": edge_modes}, dry)
    if dry:
        return
    for tid in changed:
        t = _gsettings("org.mate.panel.toplevel", f"/org/mate/panel/toplevels/{tid}/")
        t.set_boolean("auto-hide", True)
    _gio()[0].Settings.sync()


def _restore_mate(entry: dict):
    for tid, value in entry.get("auto-hide", {}).items():
        t = _gsettings("org.mate.panel.toplevel", f"/org/mate/panel/toplevels/{tid}/")
        if t is not None:
            t.set_boolean("auto-hide", bool(value))
    _gio()[0].Settings.sync()


# ==================================================================== XFCE
def xfce_edge(position: str) -> str | None:
    m = re.search(r"p=(\d+)", position or "")
    return _XFCE_EDGES.get(int(m.group(1))) if m else None


_XFCE_MODES = {"": "never", "0": "never", "1": "dodge", "2": "always"}


def _hide_xfce(edge: str, mode: str, state: list, dry: bool = False):
    listing = _run(["xfconf-query", "-c", "xfce4-panel", "-l"])
    if not listing:
        return
    ids = sorted({int(m) for m in re.findall(r"^/panels/panel-(\d+)/", listing, re.M)})
    changed, edge_modes = {}, []
    for pid in ids:
        base = f"/panels/panel-{pid}"
        pos = (_run(["xfconf-query", "-c", "xfce4-panel", "-p", f"{base}/position"]) or "").strip()
        old = (_run(["xfconf-query", "-c", "xfce4-panel", "-p", f"{base}/autohide-behavior"]) or "").strip()
        if xfce_edge(pos) == edge:
            edge_modes.append(_XFCE_MODES.get(old, "never"))
        if mode == "all" or xfce_edge(pos) == edge:
            changed[str(pid)] = old  # "" = the property didn't exist
    if not changed and not edge_modes:
        return
    _push(state, {"kind": "xfce", "autohide-behavior": changed, "modes": edge_modes}, dry)
    if dry:
        return
    for pid in changed:
        _run(["xfconf-query", "-c", "xfce4-panel", "-p", f"/panels/panel-{pid}/autohide-behavior",
              "-n", "-t", "uint", "-s", "2"])


def _restore_xfce(entry: dict):
    for pid, old in entry.get("autohide-behavior", {}).items():
        prop = f"/panels/panel-{pid}/autohide-behavior"
        if old == "":
            _run(["xfconf-query", "-c", "xfce4-panel", "-p", prop, "-r"])
        else:
            _run(["xfconf-query", "-c", "xfce4-panel", "-p", prop, "-n", "-t", "uint", "-s", old])


# =================================================================== GNOME
def _hide_gnome(mode: str, state: list):
    if not shutil.which("gnome-extensions"):
        return
    enabled = set((_run(["gnome-extensions", "list", "--enabled"]) or "").split())
    targets = [u for u in DOCK_EXTENSIONS + (PANEL_EXTENSIONS if mode == "all" else ()) if u in enabled]
    if not targets:
        return
    _push(state, {"kind": "gnome-ext", "uuids": targets})
    for uuid in targets:
        _run(["gnome-extensions", "disable", uuid])


def _restore_gnome(entry: dict):
    for uuid in entry.get("uuids", []):
        _run(["gnome-extensions", "enable", uuid])


# =============================================================== processes
def _systemd_unit(pid: int) -> str | None:
    try:
        cg = Path(f"/proc/{pid}/cgroup").read_text()
    except OSError:
        return None
    last = cg.strip().split("/")[-1]
    if last.endswith(".service") and not last.startswith(("app-", "user@", "session-")):
        return last
    return None


def _find_processes(names: tuple[str, ...]):
    me = os.getuid()
    for d in Path("/proc").iterdir():
        if not d.name.isdigit():
            continue
        try:
            if d.stat().st_uid != me:
                continue
            argv = (d / "cmdline").read_bytes().split(b"\0")
        except OSError:
            continue
        argv = [a.decode(errors="replace") for a in argv if a]
        if argv and os.path.basename(argv[0]) in names:
            yield int(d.name), argv


def _hide_processes(names: tuple[str, ...], state: list):
    for pid, argv in list(_find_processes(names)):
        unit = _systemd_unit(pid)
        _push(state, {"kind": "process", "argv": argv, "unit": unit})
        if unit:
            _run(["systemctl", "--user", "stop", unit])
        else:
            try:
                os.kill(pid, signal.SIGTERM)
            except OSError:
                pass


def _restore_process(entry: dict):
    if entry.get("unit"):
        _run(["systemctl", "--user", "start", entry["unit"]])
        return
    argv = entry.get("argv") or []
    if not argv or any(True for _ in _find_processes((os.path.basename(argv[0]),))):
        return  # already running again
    try:
        subprocess.Popen(argv, start_new_session=True, stdin=subprocess.DEVNULL,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except OSError as exc:
        print(f"linux-magnify: could not restart {argv[0]}: {exc}")


# =================================================================== state
def _push(state: list, entry: dict, dry: bool = False):
    state.append(entry)
    if dry:
        return
    path = _state_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, indent=1))
    os.replace(tmp, path)


def has_hidden() -> bool:
    return _state_file().exists()


def hide(edge: str, mode: str) -> None:
    """Hide the original panel(s) / dock. ``mode`` is "dock", "all" or "none"."""
    restore()  # never stack on top of an earlier, unrestored session
    if mode == "none":
        return
    state: list = []
    desk = _desktop()
    try:
        if "KDE" in desk:
            _hide_kde(edge, mode, state)
        if "X-CINNAMON" in desk or "CINNAMON" in desk:
            _hide_cinnamon(edge, mode, state)
        if "MATE" in desk:
            _hide_mate(edge, mode, state)
        if "XFCE" in desk:
            _hide_xfce(edge, mode, state)
        if "GNOME" in desk or "UNITY" in desk:
            _hide_gnome(mode, state)
        _hide_processes(DOCK_PROCESSES + (BAR_PROCESSES if mode == "all" else ()), state)
    except Exception as exc:
        print(f"linux-magnify: error while hiding panels: {exc}")
    if state:
        print(f"linux-magnify: hid original panel(s): {', '.join(e['kind'] for e in state)}")


def original_mode(edge: str) -> str | None:
    """How the desktop's own panel on ``edge`` hides: "never", "always" or "dodge".

    Uses the values recorded before linux-magnify hid the panel, or reads them
    live when nothing is hidden."""
    state: list = []
    try:
        state = json.loads(_state_file().read_text())
    except (OSError, ValueError):
        state = []
    if not any(e.get("modes") for e in state):
        state = []
        desk = _desktop()
        try:
            if "KDE" in desk:
                _hide_kde(edge, "dock", state, dry=True)
            if "CINNAMON" in desk:
                _hide_cinnamon(edge, "dock", state, dry=True)
            if "MATE" in desk:
                _hide_mate(edge, "dock", state, dry=True)
            if "XFCE" in desk:
                _hide_xfce(edge, "dock", state, dry=True)
        except Exception:
            pass
    for entry in state:
        if entry.get("modes"):
            return entry["modes"][0]
    return None


def restore() -> None:
    path = _state_file()
    if not path.exists():
        return
    try:
        state = json.loads(path.read_text())
    except (OSError, ValueError):
        state = []
    restorers = {"kde": _restore_kde, "cinnamon": _restore_cinnamon, "mate": _restore_mate,
                 "xfce": _restore_xfce, "gnome-ext": _restore_gnome, "process": _restore_process}
    for entry in reversed(state):
        try:
            restorers.get(entry.get("kind"), lambda e: None)(entry)
        except Exception as exc:
            print(f"linux-magnify: error restoring {entry.get('kind')}: {exc}")
    path.unlink(missing_ok=True)
    if state:
        time.sleep(0.2)
        print("linux-magnify: restored original panel(s)")


# ============================================================ pinned apps
_APP_DIRS = None


def _app_dirs() -> list[str]:
    global _APP_DIRS
    if _APP_DIRS is None:
        data_home = os.environ.get("XDG_DATA_HOME") or os.path.expanduser("~/.local/share")
        dirs = [data_home] + (os.environ.get("XDG_DATA_DIRS") or "/usr/local/share:/usr/share").split(":")
        _APP_DIRS = [os.path.join(d, "applications") for d in dirs if d]
    return _APP_DIRS


def desktop_ref(value: str) -> str | None:
    """Turn a launcher reference (file URL, path, KDE ``applications:x.desktop``,
    ``preferred://browser``) into a desktop id, or an absolute .desktop path."""
    value = value.strip()
    if not value:
        return None
    if value.startswith("preferred://"):
        kind = value[len("preferred://"):]
        mime = {"browser": "x-scheme-handler/https", "filemanager": "inode/directory",
                "mail": "x-scheme-handler/mailto"}.get(kind)
        if not mime:
            return None
        try:
            Gio, _ = _gio()
            info = Gio.AppInfo.get_default_for_type(mime, False)
        except Exception:
            return None
        return info.get_id()[:-8] if info and info.get_id() and info.get_id().endswith(".desktop") else None
    if value.startswith("applications:"):
        value = value[len("applications:"):]
    if value.startswith("file://"):
        value = unquote(urlparse(value).path)
    if value.startswith("/"):
        for d in _app_dirs():
            if value.startswith(d.rstrip("/") + "/"):
                rel = value[len(d.rstrip("/")) + 1:]
                return rel.replace("/", "-")[:-8] if rel.endswith(".desktop") else None
        return value if value.endswith(".desktop") and os.path.exists(value) else None
    return value[:-8] if value.endswith(".desktop") else value


def _kde_pins() -> list[str]:
    ini = read_ini(_kde_appletsrc())
    best: list[str] | None = None
    for _name, sec, general in kde_panel_applets(ini, ("org.kde.plasma.icontasks", "org.kde.plasma.taskmanager")):
        raw = general.get("launchers")
        if raw is None:
            raw = "preferred://filemanager,preferred://browser"  # Plasma's built-in default
        pins = [r for r in (desktop_ref(x) for x in raw.split(",")) if r]
        if best is None or sec.get("plugin") == "org.kde.plasma.icontasks":
            best = pins
            if sec.get("plugin") == "org.kde.plasma.icontasks":
                break
    return best or []


def _gnome_pins() -> list[str]:
    s = _gsettings("org.gnome.shell")
    return [r for r in (desktop_ref(x) for x in s.get_strv("favorite-apps"))] if s else []


def _cinnamon_pins() -> list[str]:
    base = Path(os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config")) / "cinnamon" / "spices"
    for applet, key in (("grouped-window-list@cinnamon.org", "pinned-apps"),
                        ("panel-launchers@cinnamon.org", "launcherList")):
        for f in sorted((base / applet).glob("*.json")):
            try:
                value = json.loads(f.read_text()).get(key, {}).get("value")
            except (OSError, ValueError):
                continue
            if value:
                return [r for r in (desktop_ref(x) for x in value) if r]
    return []


def _xfce_pins() -> list[str]:
    base = Path(os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config")) / "xfce4" / "panel"
    pins: list[str] = []
    for rc in sorted(base.glob("docklike-*.rc")):
        for line in rc.read_text(errors="replace").splitlines():
            if line.startswith("pinned="):
                pins += [r for r in (desktop_ref(x) for x in line[7:].split(";")) if r]
    if pins:
        return pins

    def num(p: Path) -> int:
        m = re.search(r"(\d+)$", p.name)
        return int(m.group(1)) if m else 0

    for d in sorted(base.glob("launcher-*"), key=num):
        pins += [str(f) for f in sorted(d.glob("*.desktop"))]
    return pins


def _plank_pins() -> list[str]:
    base = Path(os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config")) / "plank"
    pins = []
    for f in sorted(base.glob("*/launchers/*.dockitem")):
        for line in f.read_text(errors="replace").splitlines():
            if line.startswith("Launcher="):
                ref = desktop_ref(line[9:])
                if ref:
                    pins.append(ref)
    return pins


def _nwg_pins() -> list[str]:
    f = Path(os.environ.get("XDG_CACHE_HOME") or os.path.expanduser("~/.cache")) / "nwg-dock-pinned"
    try:
        return [r for r in (desktop_ref(x) for x in f.read_text().split()) if r]
    except OSError:
        return []


def import_pinned() -> list[str]:
    """Pinned apps of the desktop's own panel/dock (desktop ids or .desktop paths)."""
    desk = _desktop()
    sources = []
    if "KDE" in desk:
        sources.append(_kde_pins)
    if "CINNAMON" in desk:
        sources.append(_cinnamon_pins)
    if "XFCE" in desk:
        sources.append(_xfce_pins)
    if "GNOME" in desk or "UNITY" in desk:
        sources.append(_gnome_pins)
    sources += [_plank_pins, _nwg_pins]
    for src in sources:
        try:
            pins = src()
        except Exception:
            pins = []
        seen, out = set(), []
        for p in pins:
            if p and p not in seen:
                seen.add(p)
                out.append(p)
        if out:
            return out
    return []
