"""Small standalone windows used by the installer's preview dock.

* ``linux-magnify --about``           – About window
* ``linux-magnify --progress FILE``   – live view of the installer's progress;
  ``install.sh`` writes the current step key into FILE.
"""

from __future__ import annotations

from pathlib import Path

import gi

gi.require_version("Gtk", "4.0")
from gi.repository import Gio, GLib, Gtk  # noqa: E402

from . import __version__  # noqa: E402

STEPS = [
    ("check", "Checking dependencies"),
    ("ask", "Waiting for your answers in the terminal"),
    ("stage", "Preparing files"),
    ("install", "Installing"),
    ("done", "Finished"),
]
STEP_KEYS = [k for k, _ in STEPS]


class AboutApp(Gtk.Application):
    def __init__(self):
        super().__init__(application_id="io.github.linux_magnify.About")

    def do_activate(self):
        win = self.get_active_window()
        if win is None:
            win = Gtk.AboutDialog(
                application=self,
                program_name="Linux Magnify",
                version=__version__,
                comments="A macOS-style magnifying dock for KDE Plasma, Hyprland, Sway, "
                         "niri, XFCE, Cinnamon, MATE and other Linux desktops.",
                website="https://github.com/yeeboein/linux-magnify",
                website_label="Project page",
                license_type=Gtk.License.MIT_X11,
                logo_icon_name="help-about",
            )
            win.connect("close-request", lambda *_: self.quit() or False)
        win.present()


class ProgressApp(Gtk.Application):
    def __init__(self, status_file: Path):
        super().__init__(application_id="io.github.linux_magnify.InstallProgress")
        self.status_file = status_file
        self.rows: list[tuple[Gtk.Stack, Gtk.Spinner, Gtk.Label]] = []
        self.footer: Gtk.Label | None = None
        self._last = None

    def do_activate(self):
        win = self.get_active_window()
        if win is not None:
            win.present()
            return
        win = Gtk.ApplicationWindow(application=self, title="Linux Magnify Installer")
        win.set_default_size(380, -1)
        win.set_resizable(False)

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        for side in ("top", "bottom", "start", "end"):
            getattr(box, f"set_margin_{side}")(20)

        title = Gtk.Label(xalign=0)
        title.set_markup("<span size='large' weight='bold'>Installing Linux Magnify</span>")
        box.append(title)

        for _key, text in STEPS:
            row = Gtk.Box(spacing=10)
            stack = Gtk.Stack()
            spinner = Gtk.Spinner()
            stack.add_named(spinner, "busy")
            stack.add_named(Gtk.Image.new_from_icon_name("object-select-symbolic"), "done")
            stack.add_named(Gtk.Image.new_from_icon_name("process-stop-symbolic"), "failed")
            stack.add_named(Gtk.Box(), "pending")
            stack.set_size_request(16, 16)
            label = Gtk.Label(label=text, xalign=0)
            row.append(stack)
            row.append(label)
            box.append(row)
            self.rows.append((stack, spinner, label))

        self.footer = Gtk.Label(xalign=0, wrap=True)
        self.footer.add_css_class("dim-label")
        box.append(self.footer)

        close = Gtk.Button(label="Close")
        close.set_halign(Gtk.Align.END)
        close.connect("clicked", lambda *_: win.close())
        box.append(close)

        win.set_child(box)
        self._refresh()
        GLib.timeout_add(300, self._refresh)
        win.present()

    def _read(self) -> str:
        try:
            return self.status_file.read_text().strip()
        except OSError:
            return "gone"

    def _refresh(self):
        status = self._read()
        if status == self._last:
            return GLib.SOURCE_CONTINUE
        self._last = status
        failed = status in ("cancelled", "failed", "gone")
        current = STEP_KEYS.index(status) if status in STEP_KEYS else -1
        if failed:
            # Mark the first unfinished step as failed.
            current = next((i for i, (st, _, _) in enumerate(self.rows)
                            if st.get_visible_child_name() != "done"), len(self.rows) - 1)

        for i, (stack, spinner, label) in enumerate(self.rows):
            if status == "done" or i < current:
                state = "done"
            elif i == current:
                state = "failed" if failed else "busy"
            else:
                state = "pending"
            stack.set_visible_child_name(state)
            spinner.set_spinning(state == "busy")
            label.set_opacity(0.5 if state == "pending" else 1.0)

        if status == "done":
            self.footer.set_text("Installed! Run linux-magnify, or log in again if you enabled autostart.")
        elif status == "cancelled":
            self.footer.set_text("Install cancelled. Nothing was changed.")
        elif status in ("failed", "gone"):
            self.footer.set_text("The installer stopped. Check the terminal for details.")
        else:
            self.footer.set_text("The installer is running in your terminal.")
        return GLib.SOURCE_CONTINUE


def run_about() -> int:
    return AboutApp().run([])


def run_progress(status_file: Path) -> int:
    return ProgressApp(status_file).run([])
