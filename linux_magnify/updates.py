"""Magdoc updates: check GitHub for a newer version, notify, and install it.

The installer writes ``INSTALLED.json`` (the commit it installed) next to the
package. Magdoc compares that with the latest commit of the configured branch
on GitHub, shows one desktop notification per new version, and
``magdoc --update`` downloads that version and re-runs its installer.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tarfile
import tempfile
import time
import urllib.request
from pathlib import Path

from .control import PACKAGE_PARENT, child_env, running_pid, spawn, stop_dock
from .panels import state_dir

REPO = "yeeboein/linux-magnify"
CHECK_EVERY = 6 * 3600
USER_AGENT = "magdoc-update-check"


def installed_file() -> Path:
    return Path(PACKAGE_PARENT) / "INSTALLED.json"


def _state_file() -> Path:
    return state_dir() / "updates.json"


def installed_commit() -> str:
    """The commit this copy of Magdoc came from ("" when unknown)."""
    try:
        return json.loads(installed_file().read_text()).get("commit", "")
    except (OSError, ValueError):
        pass
    if (Path(PACKAGE_PARENT) / ".git").exists():  # running from a git checkout
        try:
            return subprocess.run(["git", "-C", PACKAGE_PARENT, "rev-parse", "HEAD"], capture_output=True,
                                  text=True, timeout=5).stdout.strip()
        except (OSError, subprocess.SubprocessError):
            pass
    return ""


def _get(url: str, timeout: float = 15) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/vnd.github+json"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read()


def read_state() -> dict:
    try:
        return json.loads(_state_file().read_text())
    except (OSError, ValueError):
        return {}


def _write_state(data: dict) -> None:
    f = _state_file()
    f.parent.mkdir(parents=True, exist_ok=True)
    tmp = f.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=1))
    os.replace(tmp, f)


def check(branch: str = "main") -> dict:
    """Ask GitHub for the latest commit. Returns (and saves) the update status."""
    status = dict(read_state())
    status.update(installed=installed_commit(), branch=branch, checked=int(time.time()), error="")
    try:
        data = json.loads(_get(f"https://api.github.com/repos/{REPO}/commits/{branch}"))
        status.update(latest=data["sha"],
                      message=(data.get("commit", {}).get("message") or "").split("\n")[0],
                      date=data.get("commit", {}).get("committer", {}).get("date", ""))
    except Exception as exc:
        status["error"] = str(exc)
    status["available"] = bool(status.get("latest") and status.get("installed")
                               and status["latest"] != status["installed"])
    _write_state(status)
    return status


def due() -> bool:
    return time.time() - read_state().get("checked", 0) >= CHECK_EVERY


def mark_notified(sha: str) -> None:
    st = read_state()
    st["notified"] = sha
    _write_state(st)


def update(branch: str = "main") -> int:
    """Download the latest Magdoc, install it, and restart the dock if it was running."""
    status = check(branch)
    if status.get("error"):
        print(f"magdoc: could not check for updates: {status['error']}", file=sys.stderr)
        return 1
    if not status.get("available") and status.get("installed"):
        print("magdoc: already up to date")
        return 0
    sha = status["latest"]
    _write_state(dict(read_state(), updating=True))
    try:
        with tempfile.TemporaryDirectory(prefix="magdoc-update-") as tmp:
            archive = Path(tmp) / "magdoc.tar.gz"
            archive.write_bytes(_get(f"https://codeload.github.com/{REPO}/tar.gz/{sha}", timeout=120))
            src = Path(tmp) / "src"
            src.mkdir()
            with tarfile.open(archive) as tar:
                try:
                    tar.extractall(src, filter="data")
                except TypeError:  # Python without extraction filters
                    for m in tar.getmembers():
                        if m.name.startswith("/") or ".." in Path(m.name).parts or not (m.isfile() or m.isdir()):
                            raise RuntimeError(f"unsafe path in update archive: {m.name}")
                    tar.extractall(src)
            top = next(p for p in src.iterdir() if p.is_dir())
            was_running = running_pid() is not None
            res = subprocess.run(["bash", str(top / "install.sh"), "--yes", "--commit", sha],
                                 env=child_env(), capture_output=True, text=True, timeout=300)
            if res.returncode != 0:
                print(res.stdout + res.stderr, file=sys.stderr)
                return 1
        if was_running:
            stop_dock()
            launcher = shutil.which("magdoc")
            if launcher:
                subprocess.Popen([launcher], start_new_session=True, stdin=subprocess.DEVNULL,
                                 stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            else:
                spawn()
        print(f"magdoc: updated to {sha[:7]}")
        return 0
    finally:
        st = read_state()
        st.pop("updating", None)
        if st.get("latest") == sha:
            st.update(installed=sha, available=False)
        _write_state(st)


# ---------------------------------------------------------------- notifications
_bus = None  # GIO only weakly caches the session bus: keep it alive so action clicks arrive


def notify(title: str, body: str, actions: list[str], on_action=None) -> None:
    """Desktop notification through org.freedesktop.Notifications (Plasma, GNOME, mako, dunst, ...)."""
    try:
        from gi.repository import Gio, GLib

        global _bus
        bus = _bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
        sent: dict = {}

        def invoked(*args):  # (conn, sender, path, iface, signal, params[, user_data])
            got_id, key = args[5].unpack()
            if on_action is not None and got_id == sent.get("id"):
                on_action(key)
        # Subscribe first, so even an instant click on the notification isn't missed.
        if on_action is not None:
            bus.signal_subscribe("org.freedesktop.Notifications", "org.freedesktop.Notifications",
                                 "ActionInvoked", "/org/freedesktop/Notifications", None,
                                 Gio.DBusSignalFlags.NONE, invoked)
        res = bus.call_sync("org.freedesktop.Notifications", "/org/freedesktop/Notifications",
                            "org.freedesktop.Notifications", "Notify",
                            GLib.Variant("(susssasa{sv}i)", ("Magdoc", 0, "software-update-available", title,
                                                             body, actions, {}, 0)),
                            GLib.VariantType("(u)"), Gio.DBusCallFlags.NONE, 5000, None)
        sent["id"] = res.unpack()[0]
    except Exception as exc:
        print(f"magdoc: could not show a notification: {exc}", file=sys.stderr)
