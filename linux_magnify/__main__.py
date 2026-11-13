"""Entry point.

Picks a display backend *before* GTK is imported and, on Wayland, re-executes
itself with ``LD_PRELOAD=libgtk4-layer-shell.so`` because gtk4-layer-shell must
be loaded before libwayland-client (a hard requirement of that library).
"""

from __future__ import annotations

import argparse
import ctypes.util
import os
import sys
from pathlib import Path

from . import __version__
from .config import POSITIONS, default_config_path, load

_PRELOAD_FLAG = "LINUX_MAGNIFY_PRELOADED"


def _find_layer_shell() -> str | None:
    name = ctypes.util.find_library("gtk4-layer-shell")
    if name:
        return name
    for d in ("/usr/lib", "/usr/lib64", "/usr/local/lib", "/usr/local/lib64",
              "/usr/lib/x86_64-linux-gnu", "/usr/lib/aarch64-linux-gnu"):
        p = Path(d) / "libgtk4-layer-shell.so.0"
        if p.exists():
            return str(p)
    return None


def _choose_backend(pref: str) -> None:
    env = os.environ
    if pref == "x11":
        env["GDK_BACKEND"] = "x11"
        return
    if pref == "wayland" or not env.get("WAYLAND_DISPLAY"):
        return
    desktop = env.get("XDG_CURRENT_DESKTOP", "").upper()
    lib = _find_layer_shell()
    if "GNOME" in desktop or lib is None:
        # Mutter has no wlr-layer-shell; without the library we can't use it either.
        # Fall back to XWayland, where the dock is an EWMH _NET_WM_WINDOW_TYPE_DOCK.
        if lib is None:
            print("magdoc: gtk4-layer-shell not found, using XWayland fallback.", file=sys.stderr)
        env["GDK_BACKEND"] = "x11"
        return
    if env.get(_PRELOAD_FLAG):
        return
    new_env = dict(env)
    new_env[_PRELOAD_FLAG] = "1"
    new_env["LD_PRELOAD"] = ":".join(filter(None, [lib, env.get("LD_PRELOAD")]))
    os.execve(sys.executable, [sys.executable, "-m", "linux_magnify", *sys.argv[1:]], new_env)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="magdoc", description="Magdoc: a macOS-style magnifying dock for Linux")
    ap.add_argument("-c", "--config", type=Path, default=None, help=f"config file (default: {default_config_path()})")
    ap.add_argument("-p", "--position", choices=POSITIONS, help="override dock position")
    ap.add_argument("-m", "--magnification", type=float, help="override magnification factor (e.g. 2.0)")
    ap.add_argument("-s", "--icon-size", type=int, help="override resting icon size in px")
    ap.add_argument("--backend", choices=("auto", "wayland", "x11"), help="force display backend")
    ap.add_argument("--settings", action="store_true", help="open Magdoc Settings")
    ap.add_argument("--gtk", action="store_true", help="with --settings: use the GTK app, not Quickshell")
    ap.add_argument("--menu", action="store_true", help="open/close the Magdoc start menu (for keybinds)")
    ap.add_argument("--enable", action="store_true", help="start Magdoc and turn on autostart")
    ap.add_argument("--disable", action="store_true",
                    help="stop Magdoc, turn off autostart and bring back the original panels")
    ap.add_argument("--restore-panels", action="store_true",
                    help="bring back the original panels without disabling autostart")
    ap.add_argument("--status-json", action="store_true", help=argparse.SUPPRESS)
    ap.add_argument("--config-json", action="store_true", help=argparse.SUPPRESS)
    ap.add_argument("--config-set", metavar="JSON", help=argparse.SUPPRESS)
    ap.add_argument("--apps-json", action="store_true", help=argparse.SUPPRESS)
    ap.add_argument("--home", action="store_true", help=argparse.SUPPRESS)
    ap.add_argument("--version", action="version", version=f"magdoc {__version__}")
    args = ap.parse_args(argv)

    if args.settings:
        from . import menu
        qs = menu.quickshell()
        if qs and not args.gtk:
            from .control import child_env
            os.execvpe(qs, [qs, "-p", str(menu.QML_DIR / "settings.qml")], child_env())
        from .settings import run
        return run(args.config)
    if args.menu or args.home:
        from . import home, menu
        cfg = load(args.config)
        menu.set_geometry(cfg.position, int(cfg.margin + cfg.padding + cfg.icon_size * cfg.magnification + 16))
        launcher = home.resolve(cfg.home_icon, cfg.home_command)
        return 0 if home.activate(launcher.command) else 1
    if args.enable or args.disable:
        from . import control
        control.enable() if args.enable else control.disable()
        return 0
    if args.restore_panels:
        from .panels import restore
        restore()
        return 0
    if args.status_json or args.config_json or args.apps_json or args.config_set is not None:
        from . import cli
        if args.config_set is not None:
            import json
            cli.config_set(args.config, json.loads(args.config_set))
        elif args.status_json:
            cli.dump(cli.status_json())
        elif args.config_json:
            cli.dump(cli.config_json(args.config))
        else:
            cli.dump(cli.apps_json())
        return 0

    cfg = load(args.config)
    overrides = {"position": args.position, "magnification": args.magnification,
                 "icon_size": args.icon_size, "backend": args.backend}
    _choose_backend(args.backend or cfg.backend)

    from .app import DockApp

    return DockApp(args.config, {k: v for k, v in overrides.items() if v is not None}).run([])


if __name__ == "__main__":
    sys.exit(main())
