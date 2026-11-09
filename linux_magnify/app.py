"""Gtk.Application: wires config, dock window and window-tracking backend."""

from __future__ import annotations

import os
import sys
import threading
from pathlib import Path

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
from gi.repository import Gdk, Gio, GLib, Gtk  # noqa: E402

from . import apps, windows  # noqa: E402
from .config import Config, load  # noqa: E402
from .dock import DockWindow  # noqa: E402

POLL_SECONDS = 1.0


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
        super().__init__(application_id="io.github.linux_magnify.Dock",
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
        self.hold()
        mode = _display_mode()
        self.window = DockWindow(self, self.cfg, mode, self._activate_item)
        self._build_pinned()
        self._refresh_items()
        self.window.present()

        self.backend = windows.detect(x11_session=(mode == "x11"))
        print(f"linux-magnify: surface={mode} window-tracking={self.backend.name}", file=sys.stderr)
        if self.backend.name != "none":
            threading.Thread(target=self._poll_loop, daemon=True).start()
        self._watch_config()

    def do_shutdown(self):
        self._stop.set()
        Gtk.Application.do_shutdown(self)

    # --------------------------------------------------------------- items
    def _build_pinned(self):
        items = []
        for entry in self.cfg.pinned:
            item = apps.from_pinned(entry)
            if item is not None:
                items.append(item)
        if getattr(self.cfg, "pinned_is_default", False):
            items = items[:8]
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
            self._stop.wait(POLL_SECONDS)

    def _set_windows(self, wins):
        key = [(w.wid, w.wm_class, w.focused) for w in wins]
        if key != [(w.wid, w.wm_class, w.focused) for w in self._windows]:
            self._windows = wins
            self._refresh_items()
        return GLib.SOURCE_REMOVE

    def _activate_item(self, item: apps.DockItem, button: int):
        display = Gdk.Display.get_default()
        if button == Gdk.BUTTON_MIDDLE or not item.windows:
            if item.launch(display):
                self.window.view.bounce(item)
            return
        # Cycle through the app's windows, starting after the focused one.
        wins = item.windows
        idx = next((i for i, w in enumerate(wins) if w.focused), -1)
        target = wins[(idx + 1) % len(wins)]
        threading.Thread(target=self.backend.focus, args=(target,), daemon=True).start()

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
        return GLib.SOURCE_REMOVE
