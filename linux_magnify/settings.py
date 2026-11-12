"""Linux Magnify Settings: a GTK4 app to configure (and enable/disable) the dock.

Every change is written to the config file right away; the running dock
watches that file and applies changes live.
"""

from __future__ import annotations

import os
import shutil
import signal
import sys
from pathlib import Path

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
from gi.repository import Gdk, Gio, GLib, Gtk  # noqa: E402

from . import __version__, apps, home, panels  # noqa: E402
from .app import PACKAGE_PARENT, running_pid, spawn  # noqa: E402
from .config import POSITIONS, Config, PinnedApp, load, save  # noqa: E402

HIDE_MODE_CHOICES = [("auto", "Same as original panel"),
                     ("never", "Always visible"),
                     ("dodge", "Hide when a window covers it"),
                     ("always", "Always auto-hide")]
HIDE_CHOICES = [("dock", "Panels on the same edge, and other docks"),
                ("all", "Every panel and bar"),
                ("none", "Don't hide anything")]
CSS = b"""
.lm-list { border-radius: 10px; }
.lm-list > row { padding: 8px 12px; }
.lm-subtitle { opacity: 0.65; font-size: smaller; }
.lm-heading { font-weight: bold; margin-top: 12px; }
.lm-status-on { color: #2ec27e; font-weight: bold; }
.lm-status-off { opacity: 0.6; font-weight: bold; }
"""


def autostart_file() -> Path:
    base = os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config")
    return Path(base) / "autostart" / "linux-magnify.desktop"


def launch_command() -> str:
    exe = shutil.which("linux-magnify")
    if exe:
        return exe
    return f"env PYTHONPATH={PACKAGE_PARENT} {sys.executable} -m linux_magnify"


def set_autostart(on: bool) -> None:
    f = autostart_file()
    if on:
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(
            "[Desktop Entry]\nType=Application\nName=Linux Magnify Dock\n"
            "Comment=macOS-style magnifying dock\n"
            f"Exec={launch_command()}\nIcon=preferences-desktop\nTerminal=false\n"
            "X-GNOME-Autostart-enabled=true\nX-KDE-autostart-phase=2\n"
        )
    else:
        f.unlink(missing_ok=True)


# ------------------------------------------------------------------ widgets
def _row(title: str, subtitle: str | None, control: Gtk.Widget | None) -> Gtk.ListBoxRow:
    box = Gtk.Box(spacing=12)
    labels = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, hexpand=True, valign=Gtk.Align.CENTER)
    labels.append(Gtk.Label(label=title, xalign=0, wrap=True))
    if subtitle:
        sub = Gtk.Label(label=subtitle, xalign=0, wrap=True)
        sub.add_css_class("lm-subtitle")
        labels.append(sub)
    box.append(labels)
    if control is not None:
        control.set_valign(Gtk.Align.CENTER)
        box.append(control)
    row = Gtk.ListBoxRow(activatable=False, selectable=False)
    row.set_child(box)
    return row


def _list(*rows: Gtk.Widget) -> Gtk.ListBox:
    lb = Gtk.ListBox(selection_mode=Gtk.SelectionMode.NONE)
    lb.add_css_class("boxed-list")
    lb.add_css_class("lm-list")
    lb.add_css_class("frame")
    for r in rows:
        lb.append(r)
    return lb


def _heading(text: str) -> Gtk.Label:
    lbl = Gtk.Label(label=text, xalign=0)
    lbl.add_css_class("lm-heading")
    return lbl


def _page(*children: Gtk.Widget) -> Gtk.ScrolledWindow:
    box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
    for side in ("top", "bottom", "start", "end"):
        getattr(box, f"set_margin_{side}")(18)
    for c in children:
        box.append(c)
    sw = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER, vexpand=True)
    sw.set_child(box)
    return sw


class SettingsWindow(Gtk.ApplicationWindow):
    def __init__(self, app: Gtk.Application, config_path: Path | None):
        super().__init__(application=app, title="Linux Magnify Settings")
        self.set_default_size(720, 620)
        self.config_path = config_path
        self.cfg: Config = load(config_path)
        self._save_id = 0

        provider = Gtk.CssProvider()
        provider.load_from_data(CSS)
        Gtk.StyleContext.add_provider_for_display(Gdk.Display.get_default(), provider,
                                                  Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)

        stack = Gtk.Stack(transition_type=Gtk.StackTransitionType.CROSSFADE, hexpand=True)
        stack.add_titled(self._general_page(), "general", "General")
        stack.add_titled(self._appearance_page(), "appearance", "Appearance")
        stack.add_titled(self._apps_page(), "apps", "Apps")
        stack.add_titled(self._home_page(), "home", "Home Button")
        stack.add_titled(self._about_page(), "about", "About")
        sidebar = Gtk.StackSidebar(stack=stack)
        sidebar.set_size_request(170, -1)
        paned = Gtk.Box()
        paned.append(sidebar)
        paned.append(Gtk.Separator(orientation=Gtk.Orientation.VERTICAL))
        paned.append(stack)
        self.set_child(paned)

        self._refresh_status()
        GLib.timeout_add_seconds(1, self._refresh_status)

    # -------------------------------------------------------------- saving
    def changed(self, apps_changed: bool = False):
        if apps_changed:
            self.cfg.pinned_imported = False
            self.cfg.pinned_is_default = False  # type: ignore[attr-defined]
        if self._save_id:
            GLib.source_remove(self._save_id)
        self._save_id = GLib.timeout_add(300, self._save_now)

    def _save_now(self):
        self._save_id = 0
        try:
            save(self.cfg, self.config_path)
        except OSError as exc:
            self._toast(f"Could not save settings: {exc}")
        return GLib.SOURCE_REMOVE

    def _toast(self, text: str):
        dlg = Gtk.AlertDialog(message=text)
        dlg.show(self)

    # ------------------------------------------------------- control helpers
    def _switch(self, attr: str) -> Gtk.Switch:
        sw = Gtk.Switch(active=getattr(self.cfg, attr))
        sw.connect("notify::active", lambda w, _p: (setattr(self.cfg, attr, w.get_active()), self.changed()))
        return sw

    def _spin(self, attr: str, lo: float, hi: float, step: float, digits: int = 0) -> Gtk.SpinButton:
        sp = Gtk.SpinButton.new_with_range(lo, hi, step)
        sp.set_digits(digits)
        sp.set_value(getattr(self.cfg, attr))
        cast = float if digits else int

        def on_change(w):
            setattr(self.cfg, attr, cast(w.get_value()))
            self.changed()
        sp.connect("value-changed", on_change)
        return sp

    def _scale(self, attr: str, lo: float, hi: float, step: float, digits: int = 1) -> Gtk.Scale:
        sc = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, lo, hi, step)
        sc.set_size_request(220, -1)
        sc.set_digits(digits)
        sc.set_draw_value(True)
        sc.set_value(getattr(self.cfg, attr))
        sc.connect("value-changed", lambda w: (setattr(self.cfg, attr, round(w.get_value(), digits)),
                                               self.changed()))
        return sc

    def _dropdown(self, attr: str, choices: list[tuple[str, str]]) -> Gtk.DropDown:
        dd = Gtk.DropDown.new_from_strings([label for _, label in choices])
        keys = [k for k, _ in choices]
        current = getattr(self.cfg, attr)
        dd.set_selected(keys.index(current) if current in keys else 0)
        dd.connect("notify::selected", lambda w, _p: (setattr(self.cfg, attr, keys[w.get_selected()]),
                                                      self.changed()))
        return dd

    def _color(self, attr: str) -> Gtk.Widget:
        rgba = Gdk.RGBA()
        rgba.parse(getattr(self.cfg, attr))
        btn = Gtk.ColorDialogButton(dialog=Gtk.ColorDialog(with_alpha=True))
        btn.set_rgba(rgba)
        btn.connect("notify::rgba", lambda w, _p: (setattr(self.cfg, attr, w.get_rgba().to_string()),
                                                   self.changed()))
        return btn

    # ---------------------------------------------------------------- pages
    def _general_page(self):
        self.enable_switch = Gtk.Switch()
        self.enable_switch.set_active(running_pid() is not None or autostart_file().exists())
        self.enable_switch.connect("notify::active", self._on_enable)
        self.status_label = Gtk.Label(xalign=0)

        desk = os.environ.get("XDG_CURRENT_DESKTOP", "").upper()
        login_note = ("Hyprland, Sway and other tiling compositors don't use autostart: add "
                      "\"exec-once = linux-magnify\" (Hyprland) or \"exec linux-magnify\" (Sway) "
                      "to your config.") if any(w in desk for w in ("HYPRLAND", "SWAY", "NIRI", "RIVER")) else \
            "Starts the dock now and every time you log in. Turn off to stop it and bring back your original panel."

        return _page(
            _list(_row("Enable Linux Magnify", login_note, self.enable_switch),
                  _row("Status", None, self.status_label)),
            _heading("Dock"),
            _list(
                _row("Position", "Screen edge for the dock", self._dropdown(
                    "position", [(p, p.capitalize()) for p in POSITIONS])),
                _row("Monitor", "0 is the primary monitor", self._spin("monitor", 0, 8, 1)),
                _row("Hiding", "When hidden, push the pointer against the screen edge to show the dock again. "
                     "“Same as original panel” copies your panel's setting.",
                     self._dropdown("hide_mode", HIDE_MODE_CHOICES)),
                _row("Show app names", "Label above the hovered icon", self._switch("show_labels")),
                _row("Show open apps", "Also show running apps that aren't pinned (like the original panel)",
                     self._switch("show_running")),
            ),
            _heading("Original panel"),
            _list(
                _row("Hide the original panel/dock",
                     "Hidden while Linux Magnify runs, brought back when it stops or is disabled.",
                     self._dropdown("hide_panels", HIDE_CHOICES)),
            ),
        )

    def _appearance_page(self):
        return _page(
            _heading("Magnification"),
            _list(
                _row("Icon size", "Resting size in pixels", self._spin("icon_size", 16, 128, 2)),
                _row("Magnification", "How big the icon under the pointer grows (1 = off)",
                     self._scale("magnification", 1.0, 4.0, 0.1)),
                _row("Spread", "How many neighbouring icons grow too", self._scale("spread", 1.0, 6.0, 0.5)),
                _row("Animation speed", "Smoothing time in milliseconds (lower is snappier)",
                     self._spin("animation_ms", 20, 400, 10)),
            ),
            _heading("Layout"),
            _list(
                _row("Spacing", "Gap between icons", self._spin("spacing", 0, 48, 1)),
                _row("Padding", "Space around the icons inside the shelf", self._spin("padding", 0, 48, 1)),
                _row("Margin", "Gap between the shelf and the screen edge", self._spin("margin", 0, 96, 1)),
                _row("Corner radius", None, self._spin("corner_radius", 0, 64, 1)),
            ),
            _heading("Colours"),
            _list(
                _row("Shelf background", None, self._color("background")),
                _row("Shelf border", None, self._color("border")),
                _row("Running indicator", None, self._color("indicator")),
                _row("Label background", None, self._color("label_background")),
                _row("Label text", None, self._color("label_foreground")),
            ),
            self._reset_button(),
        )

    def _reset_button(self):
        btn = Gtk.Button(label="Restore Default Look", halign=Gtk.Align.START, margin_top=12)

        def reset(*_):
            fresh = Config()
            for attr in ("icon_size", "magnification", "spread", "animation_ms", "spacing", "padding",
                         "margin", "corner_radius", "background", "border", "indicator",
                         "label_background", "label_foreground"):
                setattr(self.cfg, attr, getattr(fresh, attr))
            self.changed()
            self._toast("Default look restored. Reopen settings to see the updated values.")
        btn.connect("clicked", reset)
        return btn

    # ----------------------------------------------------------------- apps
    def _apps_page(self):
        self.pinned_list = Gtk.ListBox(selection_mode=Gtk.SelectionMode.NONE)
        self.pinned_list.add_css_class("boxed-list")
        self.pinned_list.add_css_class("frame")
        self.pinned_note = Gtk.Label(xalign=0, wrap=True)
        self.pinned_note.add_css_class("lm-subtitle")

        add = Gtk.Button(label="Add App…")
        add.add_css_class("suggested-action")
        add.connect("clicked", lambda *_: self._choose_app())
        copy = Gtk.Button(label="Copy From Original Panel")
        copy.connect("clicked", self._copy_from_panel)
        buttons = Gtk.Box(spacing=8)
        buttons.append(add)
        buttons.append(copy)

        self._fill_pinned()
        return _page(
            _heading("Pinned apps"),
            self.pinned_note,
            self.pinned_list,
            buttons,
        )

    def _fill_pinned(self):
        while (child := self.pinned_list.get_first_child()) is not None:
            self.pinned_list.remove(child)
        if self.cfg.pinned_imported:
            self.pinned_note.set_text("Copied from your original panel/dock, and kept in sync with it until "
                                      "you change this list. Right-click icons in the dock to pin or unpin too.")
        else:
            self.pinned_note.set_text("Open apps that aren't pinned still show up while they run. "
                                      "You can also right-click icons in the dock to pin or unpin them.")
        if not self.cfg.pinned:
            self.pinned_list.append(_row("No pinned apps", "Use “Add App…” below.", None))
        for i, entry in enumerate(self.cfg.pinned):
            item = apps.from_pinned(entry)
            name = item.name if item else (entry.name or entry.desktop_id or entry.exec or "?")
            sub = None if item else "Not installed"
            img = Gtk.Image.new_from_gicon(item.icon) if item and item.icon else \
                Gtk.Image.new_from_icon_name("dialog-warning-symbolic")
            img.set_pixel_size(32)

            controls = Gtk.Box(spacing=4)
            for icon, tip, delta in (("go-up-symbolic", "Move up", -1), ("go-down-symbolic", "Move down", 1)):
                b = Gtk.Button.new_from_icon_name(icon)
                b.set_tooltip_text(tip)
                b.add_css_class("flat")
                b.set_sensitive(0 <= i + delta < len(self.cfg.pinned))
                b.connect("clicked", lambda _b, i=i, d=delta: self._move(i, d))
                controls.append(b)
            rm = Gtk.Button.new_from_icon_name("user-trash-symbolic")
            rm.set_tooltip_text("Unpin")
            rm.add_css_class("flat")
            rm.connect("clicked", lambda _b, i=i: self._remove(i))
            controls.append(rm)

            row = _row(name, sub, controls)
            row.get_child().prepend(img)
            self.pinned_list.append(row)

    def _move(self, i: int, delta: int):
        p = self.cfg.pinned
        p[i], p[i + delta] = p[i + delta], p[i]
        self.changed(apps_changed=True)
        self._fill_pinned()

    def _remove(self, i: int):
        del self.cfg.pinned[i]
        self.changed(apps_changed=True)
        self._fill_pinned()

    def _copy_from_panel(self, *_):
        ids = panels.import_pinned()
        if not ids:
            self._toast("Couldn't find pinned apps on your original panel or dock.")
            return
        self.cfg.pinned = [PinnedApp(desktop_id=d) for d in ids]
        self.changed(apps_changed=True)
        self._fill_pinned()

    def _choose_app(self):
        dlg = Gtk.Window(title="Add App", modal=True, transient_for=self)
        dlg.set_default_size(420, 520)
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        for side in ("top", "bottom", "start", "end"):
            getattr(box, f"set_margin_{side}")(12)
        search = Gtk.SearchEntry(placeholder_text="Search apps")
        lb = Gtk.ListBox()
        infos = sorted((a for a in Gio.AppInfo.get_all()
                        if a.should_show() and isinstance(a, Gio.DesktopAppInfo)),
                       key=lambda a: (a.get_display_name() or "").lower())
        pinned_ids = {p.desktop_id for p in self.cfg.pinned}
        for info in infos:
            did = info.get_id()[:-8] if info.get_id().endswith(".desktop") else info.get_id()
            row = Gtk.ListBoxRow()
            row.app_id = did
            row.search = f"{info.get_display_name()} {did} {info.get_description() or ''}".lower()
            h = Gtk.Box(spacing=10, margin_top=4, margin_bottom=4, margin_start=4)
            img = Gtk.Image.new_from_gicon(info.get_icon()) if info.get_icon() else Gtk.Image()
            img.set_pixel_size(28)
            h.append(img)
            h.append(Gtk.Label(label=info.get_display_name(), xalign=0, hexpand=True))
            if did in pinned_ids:
                tag = Gtk.Label(label="pinned")
                tag.add_css_class("lm-subtitle")
                h.append(tag)
            row.set_child(h)
            lb.append(row)
        lb.set_filter_func(lambda r: search.get_text().lower() in r.search)
        search.connect("search-changed", lambda *_: lb.invalidate_filter())

        def pick(_lb, row):
            self.cfg.pinned.append(PinnedApp(desktop_id=row.app_id))
            self.changed(apps_changed=True)
            self._fill_pinned()
            dlg.close()
        lb.connect("row-activated", pick)
        sw = Gtk.ScrolledWindow(vexpand=True)
        sw.set_child(lb)
        box.append(search)
        box.append(sw)
        dlg.set_child(box)
        dlg.present()

    # ----------------------------------------------------------------- home
    def _home_page(self):
        detected = home.detect()
        self.home_preview = Gtk.Image(pixel_size=48)
        self._update_home_preview()

        icon_entry = Gtk.Entry(placeholder_text=f"auto ({detected.icon})", hexpand=True)
        if self.cfg.home_icon not in ("", "auto"):
            icon_entry.set_text(self.cfg.home_icon)
        icon_entry.connect("changed", lambda e: self._set_home("home_icon", e.get_text()))
        auto_cmd = ("opens your desktop's own app menu" if detected.command.startswith("dbus:")
                    else detected.command or "no app launcher found")
        cmd_entry = Gtk.Entry(placeholder_text=f"auto ({auto_cmd})", hexpand=True)
        if self.cfg.home_command not in ("", "auto"):
            cmd_entry.set_text(self.cfg.home_command)
        cmd_entry.connect("changed", lambda e: self._set_home("home_command", e.get_text()))
        icon_entry.set_size_request(260, -1)
        cmd_entry.set_size_request(260, -1)

        test = Gtk.Button(label="Test")
        test.connect("clicked", lambda *_: home.activate(
            home.resolve(self.cfg.home_icon, self.cfg.home_command).command))

        return _page(
            _list(
                _row("Show the home button", "First icon on the dock; opens your app menu",
                     self._switch("home_enabled")),
                _row("Icon", f"Copied from: {detected.source}", self.home_preview),
            ),
            _heading("Override (leave empty for automatic)"),
            _list(
                _row("Icon name or file", "e.g. start-here, archlinux-logo, /path/to/logo.svg", icon_entry),
                _row("Command", "Runs when the button is clicked, e.g. rofi -show drun", cmd_entry),
                _row("Try the button", None, test),
            ),
        )

    def _set_home(self, attr: str, value: str):
        setattr(self.cfg, attr, value.strip() or "auto")
        self.changed()
        self._update_home_preview()

    def _update_home_preview(self):
        icon = home.resolve(self.cfg.home_icon, self.cfg.home_command).icon
        if os.path.isabs(icon):
            self.home_preview.set_from_file(icon)
        else:
            self.home_preview.set_from_gicon(Gio.ThemedIcon.new_from_names([icon, "start-here"]))

    # ---------------------------------------------------------------- about
    def _about_page(self):
        title = Gtk.Label(xalign=0)
        title.set_markup(f"<span size='x-large' weight='bold'>Linux Magnify</span>  {__version__}")
        desc = Gtk.Label(xalign=0, wrap=True, label=(
            "A macOS-style magnifying dock for KDE Plasma, Hyprland, Sway, niri, Xfce, Cinnamon, MATE "
            "and other Linux desktops."))
        link = Gtk.LinkButton(uri="https://github.com/yeeboein/linux-magnify", label="Project page",
                              halign=Gtk.Align.START)
        cfg_path = Gtk.Label(xalign=0, selectable=True, wrap=True,
                             label=f"Config file: {self.cfg.path}")
        cfg_path.add_css_class("lm-subtitle")
        return _page(title, desc, link, cfg_path)

    # --------------------------------------------------------- enable/disable
    def _on_enable(self, sw, _p):
        on = sw.get_active()
        set_autostart(on)
        pid = running_pid()
        if on and pid is None:
            spawn()
        elif not on and pid is not None:
            try:
                os.kill(pid, signal.SIGTERM)  # the dock restores the original panel on exit
            except OSError:
                pass
        GLib.timeout_add(800, lambda: self._refresh_status() and False)

    def _refresh_status(self):
        pid = running_pid()
        if pid:
            self.status_label.set_text("Running")
            self.status_label.remove_css_class("lm-status-off")
            self.status_label.add_css_class("lm-status-on")
        else:
            self.status_label.set_text("Stopped")
            self.status_label.remove_css_class("lm-status-on")
            self.status_label.add_css_class("lm-status-off")
        return GLib.SOURCE_CONTINUE


class SettingsApp(Gtk.Application):
    def __init__(self, config_path: Path | None = None):
        super().__init__(application_id="io.github.linux_magnify.Settings")
        self.config_path = config_path

    def do_activate(self):
        win = self.get_active_window() or SettingsWindow(self, self.config_path)
        win.present()


def run(config_path: Path | None = None) -> int:
    return SettingsApp(config_path).run([])
