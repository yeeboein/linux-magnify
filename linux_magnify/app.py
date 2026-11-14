"""Gtk.Application: wires config, dock window and window-tracking backend."""

from __future__ import annotations

import os
import signal
import sys
import threading
from pathlib import Path

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
from gi.repository import Gdk, Gio, GLib, Gtk  # noqa: E402

from . import apps, control, home, magnify, menu, panels, service, updates, windows  # noqa: E402
from .config import Config, PinnedApp, load, save  # noqa: E402
from .dock import DockWindow  # noqa: E402

POLL_SECONDS = 1.0
from .control import pid_file, running_pid, spawn  # noqa: E402  (re-exported for older imports)


def _display_mode() -> str:
    display = Gdk.Display.get_default()
    kind = type(display).__name__
    if "Wayland" in kind:
        try:
            gi.require_version("Gtk4LayerShell", "1.0")
            from gi.repository import Gtk4LayerShell as LS
            if LS.is_supported():
                return "layer"
            print("linux-magnify: compositor lacks wlr-layer-shell; showing a normal window.", file=sys.stderr)
        except (ValueError, ImportError):
            print("linux-magnify: Gtk4LayerShell typelib missing; showing a normal window.", file=sys.stderr)
        return "window"
    if "X11" in kind:
        return "x11"
    return "window"


class DockApp(Gtk.Application):
    def __init__(self, config_path: Path | None, overrides: dict):
        super().__init__(application_id="io.github.linux_magnify.linux-magnify",
                         flags=Gio.ApplicationFlags.NON_UNIQUE)
        self.config_path = config_path
        self.overrides = overrides
        self.cfg: Config = self._load()
        self.window: DockWindow | None = None
        self.backend: windows.Backend = windows.Backend()
        self.pinned: list[apps.DockItem] = []
        self.transient: dict[str, apps.DockItem] = {}
        self._windows: list[windows.Window] = []
        self._monitor = None
        self._reload_id = 0
        self._stop = threading.Event()
        self._hidden_for: tuple[str, str] | None = None
        self.service = None

    def _load(self) -> Config:
        cfg = load(self.config_path)
        for k, v in self.overrides.items():
            setattr(cfg, k, v)
        return cfg

    # --------------------------------------------------------------- lifecycle
    def do_activate(self):
        if self.window:
            self.window.present()
            return
        other = running_pid()
        if other and other != os.getpid():
            print(f"linux-magnify: linux-magnify magdoc is already running (pid {other}).", file=sys.stderr)
            return
        pid_file().parent.mkdir(parents=True, exist_ok=True)
        pid_file().write_text(str(os.getpid()))
        for sig in (signal.SIGTERM, signal.SIGINT, signal.SIGHUP):
            GLib.unix_signal_add(GLib.PRIORITY_DEFAULT, sig, self._on_signal)

        self.hold()
        mode = _display_mode()
        self.window = DockWindow(self, self.cfg, mode, self._activate_item)
        self._build_pinned()
        self._refresh_items()
        self.window.present()
        GLib.idle_add(self._apply_panel_hiding)

        self.service = service.start()
        if self.service is not None:
            self.service.handlers["ToggleMenu"] = self._toggle_menu
        self._update_menu_geometry()
        if self.cfg.home_enabled and home.resolve(self.cfg.home_icon, self.cfg.home_command).command == home.MAGDOC_MENU:
            menu.start()  # warm it up so the first click opens instantly
        self.backend = windows.detect(x11_session=(mode == "x11"), service=self.service)
        self.backend.on_change = lambda wins: GLib.idle_add(self._set_windows, wins)
        print(f"linux-magnify: surface={mode} window-tracking={self.backend.name}", file=sys.stderr)
        if self.backend.name not in ("none", "kwin"):  # kwin pushes updates itself
            threading.Thread(target=self._poll_loop, daemon=True).start()
        self._watch_config()
        # Look for a new linux-magnify a minute after start, then every few hours.
        GLib.timeout_add_seconds(60, self._update_tick)
        GLib.timeout_add_seconds(1800, self._update_tick)

    def do_shutdown(self):
        self._stop.set()
        self.backend.close()
        menu.stop()
        if self.service is not None:
            self.service.close()
        # The original panel stays hidden when the dock merely exits (logout, restart):
        # it only comes back when linux-magnify is disabled (control.disable / --restore-panels).
        if self.window is not None:
            try:
                if running_pid() == os.getpid():
                    pid_file().unlink()
            except OSError:
                pass
        Gtk.Application.do_shutdown(self)

    def _on_signal(self):
        self.quit()
        return GLib.SOURCE_REMOVE

    def _apply_panel_hiding(self):
        want = (self.cfg.hide_panels, self.cfg.position)
        if want != self._hidden_for:
            if self.cfg.hide_panels == "none":
                panels.restore()
            else:
                panels.hide(self.cfg.position, self.cfg.hide_panels)
            self._hidden_for = want
        if self.cfg.hide_mode == "auto":
            # Copy how the original panel hid itself (recorded before we hid it).
            self.cfg.resolved_hide_mode = panels.original_mode(self.cfg.position) or "never"
            print(f"linux-magnify: hide mode copied from the original panel: {self.cfg.resolved_hide_mode}",
                  file=sys.stderr)
            self.window.apply_config(self.cfg)
        self._update_covered()
        return GLib.SOURCE_REMOVE

    # --------------------------------------------------------------- updates
    def _update_tick(self):
        if self.cfg.update_notify and updates.due():
            threading.Thread(target=self._check_updates, daemon=True).start()
        return GLib.SOURCE_CONTINUE

    def _check_updates(self):
        st = updates.check(self.cfg.update_branch)
        if st.get("available") and st.get("latest") != st.get("notified"):
            GLib.idle_add(self._notify_update, st)

    def _notify_update(self, st):
        updates.mark_notified(st["latest"])
        body = f"A new version of linux-magnify is ready ({st['latest'][:7]})."
        if st.get("message"):
            body += f"\n{st['message']}"

        def on_action(key):
            if key == "update":
                control.spawn("--update")
            else:
                control.spawn("--settings")
        updates.notify("linux-magnify update available", body, ["update", "Update now", "default", "Details"], on_action)
        return GLib.SOURCE_REMOVE

    # --------------------------------------------------------------- start menu
    def _update_menu_geometry(self):
        c = self.cfg
        # Open clear of the magnified icons, so the menu is never cropped by the dock.
        menu.set_geometry(c.position, int(c.margin + c.padding + c.icon_size * c.magnification + 16))

    def _toggle_menu(self):
        """Meta key / D-Bus: do what the home button does."""
        launcher = home.resolve(self.cfg.home_icon, self.cfg.home_command)
        home.activate(launcher.command)

    # --------------------------------------------------------------- dodge
    def _dock_rect(self) -> tuple[int, int, int, int] | None:
        """The dock's resting area in global screen coordinates."""
        mon = self.window._monitor() if self.window else None
        if mon is None:
            return None
        g = mon.get_geometry()
        view = self.window.view
        length = int(magnify.rest_length(len(view.items), view.params) + 2 * self.cfg.padding)
        t = view.reserved
        pos = self.cfg.position
        if pos == "bottom":
            return g.x + (g.width - length) // 2, g.y + g.height - t, length, t
        if pos == "top":
            return g.x + (g.width - length) // 2, g.y, length, t
        if pos == "left":
            return g.x, g.y + (g.height - length) // 2, t, length
        return g.x + g.width - t, g.y + (g.height - length) // 2, t, length

    def _update_covered(self):
        if self.window is None:
            return
        covered = False
        if self.cfg.effective_hide_mode == "dodge":
            rect = self._dock_rect()
            covered = bool(rect) and windows.covering(self._windows, rect)
        self.window.view.set_covered(covered)

    # --------------------------------------------------------------- items
    def _build_pinned(self):
        old = {(i.kind, i.pin_id or i.name): i.scale for i in self.pinned}
        items = []
        if self.cfg.home_enabled:
            launcher = home.resolve(self.cfg.home_icon, self.cfg.home_command)
            items.append(apps.home_item(launcher.icon, lambda cmd=launcher.command: home.activate(cmd)))
        for index, entry in enumerate(self.cfg.pinned):
            item = apps.from_pinned(entry)
            if item is not None:
                item.entry_index = index  # type: ignore[attr-defined]
                items.append(item)
        if getattr(self.cfg, "pinned_is_default", False):
            items = items[:9]
        for item in items:
            item.scale = old.get((item.kind, item.pin_id or item.name), 1.0)
        self.pinned = items

    def _refresh_items(self):
        for item in self.pinned:
            item.windows = []
        unmatched: dict[str, list[windows.Window]] = {}
        for w in self._windows:
            if not w.wm_class or w.wm_class.lower() == "linux-magnify":
                continue
            owner = next((i for i in self.pinned if i.matches(w.wm_class)), None)
            if owner:
                owner.windows.append(w)
            else:
                unmatched.setdefault(w.wm_class.lower(), []).append(w)

        transient = {}
        if self.cfg.show_running:
            for key, wins in unmatched.items():
                item = self.transient.get(key) or apps.from_window(wins[0])
                item.windows = wins
                transient[key] = item
        self.transient = transient
        if self.window:
            self.window.view.set_items(self.pinned + list(transient.values()))

    def _poll_loop(self):
        while not self._stop.is_set():
            try:
                wins = self.backend.list_windows()
            except Exception as exc:
                print(f"linux-magnify: window backend error: {exc}", file=sys.stderr)
                wins = []
            GLib.idle_add(self._set_windows, wins)
            fast = self.cfg.effective_hide_mode == "dodge" and self.backend.has_geometry
            self._stop.wait(0.35 if fast else POLL_SECONDS)

    def _set_windows(self, wins):
        old = [w.key() for w in self._windows]
        new = [w.key() for w in wins]
        if new != old:
            classes_changed = [k[:3] for k in new] != [k[:3] for k in old]
            self._windows = wins
            if classes_changed:
                self._refresh_items()
            self._update_covered()
        return GLib.SOURCE_REMOVE

    def _activate_item(self, item: apps.DockItem, button: int, idx: int = -1):
        display = Gdk.Display.get_default()
        if button == Gdk.BUTTON_SECONDARY:
            self._show_menu(item, idx)
            return
        if item.kind == "home":
            item.launch(display)
            return
        if button == Gdk.BUTTON_MIDDLE or not item.windows:
            if item.launch(display):
                self.window.view.bounce(item)
            return
        # Cycle through the app's windows, starting after the focused one.
        wins = item.windows
        idx = next((i for i, w in enumerate(wins) if w.focused), -1)
        target = wins[(idx + 1) % len(wins)]
        threading.Thread(target=self.backend.focus, args=(target,), daemon=True).start()

    # --------------------------------------------------------------- menu
    def _show_menu(self, item: apps.DockItem, idx: int):
        menu = Gio.Menu()
        group = Gio.SimpleActionGroup()
        top = Gio.Menu()

        def add(section: Gio.Menu, label: str, name: str, cb):
            action = Gio.SimpleAction.new(name, None)
            action.connect("activate", lambda *_: cb())
            group.add_action(action)
            section.append(label, f"item.{name}")

        if item.kind == "app" and item.app_info is not None:
            add(top, "New Window", "new", lambda: item.launch(Gdk.Display.get_default())
                and self.window.view.bounce(item))
        if item.kind == "app" and item.pin_id:
            if item.pinned:
                add(top, "Unpin from Dock", "unpin", lambda: self._set_pinned(item, False))
            else:
                add(top, "Pin to Dock", "pin", lambda: self._set_pinned(item, True))
        if item.kind == "home":
            add(top, "Hide This Button", "hidehome", self._hide_home)
        # One section, no separator: on X11, GTK caps a dock window's popover height,
        # and a separator pushes the last item out of view.
        add(top, "linux-magnify Settings…", "settings", lambda: spawn("--settings"))
        if item.kind == "home":  # (app icons already have 3 items; more don't fit on X11)
            add(top, "Turn Off magdoc", "disable", lambda: spawn("--disable"))
        menu.append_section(None, top)
        self.window.view.show_menu(idx, menu, group)

    def _file_config(self) -> Config:
        """The config as stored on disk (without command-line overrides)."""
        return load(self.config_path)

    def _set_pinned(self, item: apps.DockItem, pin: bool):
        cfg = self._file_config()
        cfg.pinned_imported = False
        cfg.pinned_is_default = False  # type: ignore[attr-defined]
        if pin:
            cfg.pinned.append(PinnedApp(desktop_id=item.pin_id))
        else:
            index = getattr(item, "entry_index", None)
            if index is not None and index < len(cfg.pinned):
                del cfg.pinned[index]
            else:
                cfg.pinned = [p for p in cfg.pinned if p.desktop_id != item.pin_id]
        save(cfg)  # the file monitor reloads the dock

    def _hide_home(self):
        cfg = self._file_config()
        cfg.home_enabled = False
        save(cfg)

    # --------------------------------------------------------------- config
    def _watch_config(self):
        path = self.cfg.path
        if path is None:
            return
        path.parent.mkdir(parents=True, exist_ok=True)
        self._monitor = Gio.File.new_for_path(str(path)).monitor_file(Gio.FileMonitorFlags.NONE, None)
        self._monitor.connect("changed", self._on_config_changed)

    def _on_config_changed(self, *_):
        if self._reload_id:
            GLib.source_remove(self._reload_id)
        self._reload_id = GLib.timeout_add(250, self._reload)

    def _reload(self):
        self._reload_id = 0
        try:
            self.cfg = self._load()
        except Exception as exc:
            print(f"linux-magnify: config error, keeping old config: {exc}", file=sys.stderr)
            return GLib.SOURCE_REMOVE
        print("linux-magnify: config reloaded", file=sys.stderr)
        self._build_pinned()
        self.transient = {}
        self.window.apply_config(self.cfg)
        self._refresh_items()
        self.window.view.update_size()
        self._update_menu_geometry()
        self._apply_panel_hiding()
        return GLib.SOURCE_REMOVE
