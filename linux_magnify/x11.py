"""X11 support: turn the GTK window into an EWMH dock and position it.

GTK4 dropped window type hints and window positioning, so we talk to the X
server directly with python-xlib. Works with XFCE, Cinnamon, MATE, Budgie,
KDE Plasma (X11), GNOME on Xorg, i3, Openbox, ...
"""

from __future__ import annotations

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("GdkX11", "4.0")
from gi.repository import Gdk, GdkX11  # noqa: E402


class X11Dock:
    def __init__(self, window):
        self.window = window
        try:
            from Xlib import display
        except ImportError:
            print("linux-magnify: python-xlib is not installed; the dock cannot be positioned on X11.")
            self.dpy = None
            return
        self.dpy = display.Display()
        window.connect("realize", self._on_realize)

    def _xwin(self):
        surface = self.window.get_surface()
        if surface is None or not isinstance(surface, GdkX11.X11Surface):
            return None
        return self.dpy.create_resource_object("window", surface.get_xid())

    def _atom(self, name: str) -> int:
        return self.dpy.intern_atom(name)

    def _on_realize(self, *_):
        from Xlib import Xatom

        w = self._xwin()
        if w is None:
            return
        w.change_property(self._atom("_NET_WM_WINDOW_TYPE"), Xatom.ATOM, 32,
                          [self._atom("_NET_WM_WINDOW_TYPE_DOCK")])
        w.change_property(self._atom("_NET_WM_STATE"), Xatom.ATOM, 32, [
            self._atom("_NET_WM_STATE_ABOVE"), self._atom("_NET_WM_STATE_STICKY"),
            self._atom("_NET_WM_STATE_SKIP_TASKBAR"), self._atom("_NET_WM_STATE_SKIP_PAGER"),
        ])
        w.change_property(self._atom("_NET_WM_DESKTOP"), Xatom.CARDINAL, 32, [0xFFFFFFFF])
        self.dpy.flush()

    def place(self):
        if self.dpy is None:
            return
        from Xlib import Xatom

        w = self._xwin()
        if w is None:
            return
        win = self.window
        cfg = win.cfg
        monitors = Gdk.Display.get_default().get_monitors()
        idx = cfg.monitor if 0 <= cfg.monitor < monitors.get_n_items() else 0
        mon = monitors.get_item(idx)
        if mon is None:
            return
        scale = win.get_surface().get_scale_factor()
        g = mon.get_geometry()
        mx, my, mw, mh = g.x * scale, g.y * scale, g.width * scale, g.height * scale
        ww, wh = (v * scale for v in win.view.preferred_size())

        if cfg.position == "bottom":
            x, y = mx + (mw - ww) // 2, my + mh - wh
        elif cfg.position == "top":
            x, y = mx + (mw - ww) // 2, my
        elif cfg.position == "left":
            x, y = mx, my + (mh - wh) // 2
        else:
            x, y = mx + mw - ww, my + (mh - wh) // 2
        w.configure(x=int(x), y=int(y), width=int(ww), height=int(wh))

        root = self.dpy.screen()
        sw, sh = root.width_in_pixels, root.height_in_pixels
        strut = [0] * 12
        if not cfg.autohide:
            r = win.view.reserved * scale
            if cfg.position == "bottom":
                strut[3] = sh - (my + mh) + r
                strut[10], strut[11] = mx, mx + mw - 1
            elif cfg.position == "top":
                strut[2] = my + r
                strut[8], strut[9] = mx, mx + mw - 1
            elif cfg.position == "left":
                strut[0] = mx + r
                strut[4], strut[5] = my, my + mh - 1
            else:
                strut[1] = sw - (mx + mw) + r
                strut[6], strut[7] = my, my + mh - 1
        w.change_property(self._atom("_NET_WM_STRUT_PARTIAL"), Xatom.CARDINAL, 32, [int(v) for v in strut])
        w.change_property(self._atom("_NET_WM_STRUT"), Xatom.CARDINAL, 32, [int(v) for v in strut[:4]])
        self.dpy.flush()
