"""Start, stop, enable and disable Magdoc (no GTK needed, so the Quickshell UI can use it)."""

from __future__ import annotations

import os
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path

from . import panels

PACKAGE_PARENT = str(Path(__file__).resolve().parent.parent)
APP_NAME = "Magdoc"


def runtime_dir() -> Path:
    return Path(os.environ.get("XDG_RUNTIME_DIR") or str(panels.state_dir()))


def pid_file() -> Path:
    return runtime_dir() / "magdoc.pid"


def running_pid() -> int | None:
    """PID of the running dock, if any."""
    try:
        pid = int(pid_file().read_text().strip())
        cmdline = Path(f"/proc/{pid}/cmdline").read_bytes()
    except (OSError, ValueError):
        return None
    if b"linux_magnify" in cmdline or b"magdoc" in cmdline or b"linux-magnify" in cmdline:
        if not any(flag in cmdline for flag in (b"--settings", b"--menu", b"--config")):
            return pid
    return None


def child_env() -> dict:
    env = dict(os.environ)
    env["PYTHONPATH"] = os.pathsep.join(filter(None, [PACKAGE_PARENT, env.get("PYTHONPATH")]))
    env["MAGDOC_PYTHON"] = sys.executable
    for var in ("LD_PRELOAD", "LINUX_MAGNIFY_PRELOADED"):
        env.pop(var, None)  # let the child pick its own display backend
    return env


def spawn(*args: str) -> subprocess.Popen:
    """Start another Magdoc process (the dock, the settings app, ...)."""
    return subprocess.Popen([sys.executable, "-m", "linux_magnify", *args], env=child_env(),
                            start_new_session=True, stdin=subprocess.DEVNULL,
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


# ------------------------------------------------------------------ autostart
def _autostart_dir() -> Path:
    base = os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config")
    return Path(base) / "autostart"


def autostart_file() -> Path:
    return _autostart_dir() / "magdoc.desktop"


def autostart_enabled() -> bool:
    return autostart_file().exists() or (_autostart_dir() / "linux-magnify.desktop").exists()


def launch_command() -> str:
    for name in ("magdoc", "linux-magnify"):
        exe = shutil.which(name)
        if exe:
            return exe
    return f"env PYTHONPATH={PACKAGE_PARENT} {sys.executable} -m linux_magnify"


def set_autostart(on: bool) -> None:
    (_autostart_dir() / "linux-magnify.desktop").unlink(missing_ok=True)  # name used by older versions
    f = autostart_file()
    if on:
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(
            f"[Desktop Entry]\nType=Application\nName={APP_NAME}\n"
            "Comment=macOS-style magnifying dock\n"
            f"Exec={launch_command()}\nIcon=preferences-desktop\nTerminal=false\n"
            "X-GNOME-Autostart-enabled=true\nX-KDE-autostart-phase=2\n"
        )
    else:
        f.unlink(missing_ok=True)


# ------------------------------------------------------------- enable/disable
def stop_dock(timeout: float = 5.0) -> None:
    pid = running_pid()
    if pid is None:
        return
    try:
        os.kill(pid, signal.SIGTERM)
    except OSError:
        return
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline and running_pid() == pid:
        time.sleep(0.1)


def enable() -> None:
    set_autostart(True)
    if running_pid() is None:
        spawn()


def disable() -> None:
    """Stop Magdoc, turn off autostart and bring the original panel(s) back."""
    set_autostart(False)
    stop_dock()
    from . import menu
    menu.stop()
    panels.restore()


def status() -> dict:
    return {"running": running_pid() is not None, "autostart": autostart_enabled()}
