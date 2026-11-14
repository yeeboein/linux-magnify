"""linux-magnify's start menu: a Quickshell (QML) layer-shell window that opens above the dock.

The menu runs as a small background process; linux-magnify opens and closes it by
writing a JSON "trigger" file that the QML watches. Works from the dock, the
Meta key (via D-Bus) and ``linux-magnify --menu`` (for compositor keybinds).
"""

from __future__ import annotations

import json
import os
import shutil
import signal
import subprocess
import time
from pathlib import Path

from .control import child_env, runtime_dir

QML_DIR = Path(__file__).resolve().parent / "qml"
_geometry = {"edge": "bottom", "gap": 140}


def quickshell() -> str | None:
    return next((shutil.which(n) for n in ("qs", "quickshell") if shutil.which(n)), None)


def available() -> bool:
    return quickshell() is not None


def trigger_file() -> Path:
    return runtime_dir() / "magdoc-menu.json"


def _pid_file() -> Path:
    return runtime_dir() / "magdoc-menu.pid"


def set_geometry(edge: str, gap: int) -> None:
    """Where the dock is, so the menu opens just clear of it (never cropped by the icons)."""
    _geometry.update(edge=edge, gap=int(gap))


def _running() -> bool:
    try:
        pid = int(_pid_file().read_text())
        return b"menu.qml" in Path(f"/proc/{pid}/cmdline").read_bytes()
    except (OSError, ValueError):
        return False


def _write(action: str, seq: int | None = None) -> None:
    f = trigger_file()
    f.parent.mkdir(parents=True, exist_ok=True)
    try:
        prev = json.loads(f.read_text()).get("seq", 0)
    except (OSError, ValueError):
        prev = 0
    data = dict(_geometry, action=action, seq=prev + 1 if seq is None else seq, time=int(time.time() * 1000))
    tmp = f.with_suffix(".tmp")
    tmp.write_text(json.dumps(data))
    os.replace(tmp, f)


def start() -> bool:
    qs = quickshell()
    if qs is None:
        return False
    if _running():
        return True
    _write("none", seq=0)
    proc = subprocess.Popen([qs, "-p", str(QML_DIR / "menu.qml")], env=child_env(), start_new_session=True,
                            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    _pid_file().write_text(str(proc.pid))
    return True


def toggle(action: str = "toggle") -> bool:
    """Open/close the menu (starting it if needed). False when Quickshell isn't installed."""
    if not start():
        return False
    _write(action)  # a just-started menu acts on triggers written in the last few seconds
    return True


def stop() -> None:
    try:
        pid = int(_pid_file().read_text())
        if b"menu.qml" in Path(f"/proc/{pid}/cmdline").read_bytes():
            os.kill(pid, signal.SIGTERM)
    except (OSError, ValueError):
        pass
    _pid_file().unlink(missing_ok=True)
