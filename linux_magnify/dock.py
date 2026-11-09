"""The dock widget and window."""

from __future__ import annotations

import math
import time

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Gsk", "4.0")
gi.require_version("Graphene", "1.0")
from gi.repository import Gdk, GLib, Graphene, Gsk, Gtk  # noqa: E402

import cairo  # noqa: E402

from . import magnify  # noqa: E402
from .apps import DockItem  # noqa: E402
from .config import Config  # noqa: E402

BOUNCE_SECONDS = 1.2
LABEL_GAP = 10


def _rgba(spec: str) -> Gdk.RGBA:
    c = Gdk.RGBA()
    if not c.parse(spec):
        c.parse("rgba(0,0,0,0.5)")
    return c


def _grect(x, y, w, h) -> Graphene.Rect:
    return Graphene.Rect().init(x, y, w, h)


def _rounded(x, y, w, h, radius) -> Gsk.RoundedRect:
    rr = Gsk.RoundedRect()
    rr.init_from_rect(_grect(x, y, w, h), max(0.0, min(radius, w / 2, h / 2)))
    return rr


class DockView(Gtk.Widget):
    """Draws the shelf and icons and runs the magnification animation."""

    def __init__(self, cfg: Config, on_activate, on_size_changed):
        super().__init__()
        self.cfg = cfg
        self.items: list[DockItem] = []
        self._on_activate = on_activate  # (item, button) -> None
        self._on_size_changed = on_size_changed

        self.hovering = False
        self.cursor: float | None = None  # main-axis pointer position
        self.hovered: int | None = None
        self.frac = 0.5
        self.hide = 1.0 if cfg.autohide else 0.0
        self._hide_timer = 0
        self._tick_id: int | None = None
        self._last_frame: float | None = None
        self._icon_cache: dict = {}
        self._region_key = None
        self._max_extra = 0.0

        motion = Gtk.EventControllerMotion()
        motion.connect("enter", self._on_enter)
        motion.connect("motion", self._on_motion)
        motion.connect("leave", self._on_leave)
        self.add_controller(motion)

        click = Gtk.GestureClick()
        click.set_button(0)
        click.connect("released", self._on_click)
        self.add_controller(click)

        self.connect("notify::scale-factor", lambda *_: self._icon_cache.clear())

    # ------------------------------------------------------------ geometry
    @property
    def params(self) -> magnify.Params:
        c = self.cfg
        return magnify.Params(c.icon_size, c.magnification, c.spread, c.spacing)

    @property
    def shelf_thickness(self) -> float:
        return self.cfg.icon_size + 2 * self.cfg.padding

    @property
    def reserved(self) -> int:
        """Space to reserve at the screen edge (exclusive zone / strut)."""
        return int(self.cfg.margin + self.shelf_thickness)

    def preferred_size(self) -> tuple[int, int]:
        c = self.cfg
        n = max(1, len(self.items))
        p = self.params
        main = magnify.rest_length(n, p) + 2 * self._max_extra + 2 * c.padding + 16
        grown = c.icon_size * max(c.magnification, 1.5)
        label = 0
        if c.show_labels:
            label = LABEL_GAP + 34 if c.horizontal else LABEL_GAP + 240
        cross = c.margin + c.padding + grown + label + 4
        limit = self._monitor_length()
        if limit:
            main = min(main, limit)
        main, cross = int(math.ceil(main)), int(math.ceil(cross))
        return (main, cross) if c.horizontal else (cross, main)

    def _monitor_length(self) -> int | None:
        display = Gdk.Display.get_default()
        monitors = display.get_monitors() if display else None
        if not monitors or monitors.get_n_items() == 0:
            return None
        idx = self.cfg.monitor if 0 <= self.cfg.monitor < monitors.get_n_items() else 0
        g = monitors.get_item(idx).get_geometry()
        return g.width if self.cfg.horizontal else g.height

    def update_size(self):
        self._max_extra = magnify.max_overflow(len(self.items), self.params)
        w, h = self.preferred_size()
        self.set_size_request(w, h)
        self._region_key = None
        self._on_size_changed(w, h)
        self.queue_draw()

    def _main_len(self) -> float:
        return self.get_width() if self.cfg.horizontal else self.get_height()

    def _rest_start(self) -> float:
        return (self._main_len() - magnify.rest_length(len(self.items), self.params)) / 2

    def _rect(self, main, c, mlen, clen):
        """Map (main-axis pos, distance-from-screen-edge, lengths) to x, y, w, h."""
        W, H = self.get_width(), self.get_height()
        pos = self.cfg.position
        if pos == "bottom":
            return main, H - c - clen, mlen, clen
        if pos == "top":
            return main, c, mlen, clen
        if pos == "left":
            return c, main, clen, mlen
        return W - c - clen, main, clen, mlen

    def _hide_offset(self) -> float:
        return self.hide * (self.cfg.margin + self.shelf_thickness + 6)

    def _layout(self):
        return magnify.layout([it.scale for it in self.items], self.params, self._rest_start(), self.frac)

    def _hit(self, x: float, y: float) -> int | None:
        main = x if self.cfg.horizontal else y
        half = self.cfg.spacing / 2
        for i, (start, size) in enumerate(self._layout()):
            if start - half <= main < start + size + half:
                return i
        return None

    # ------------------------------------------------------------ items
    def set_items(self, items: list[DockItem]):
        old_n = len(self.items)
        self.items = items
        live = {id(i) for i in items}
        self._icon_cache = {k: v for k, v in self._icon_cache.items() if k[0] in live}
        if len(items) != old_n:
            self.update_size()
        self.queue_draw()

    def bounce(self, item: DockItem):
        item.bounce_until = time.monotonic() + BOUNCE_SECONDS
        self._ensure_ticking()

    # ------------------------------------------------------------ input
    def _on_enter(self, _ctl, x, y):
        self.hovering = True
        if self._hide_timer:
            GLib.source_remove(self._hide_timer)
            self._hide_timer = 0
        self._on_motion(_ctl, x, y)

    def _on_motion(self, _ctl, x, y):
        if self.hide > 0.5 and self.cfg.autohide:
            # Revealing: don't magnify until the dock is on screen.
            self.hovering = True
            self.cursor = None
            self._ensure_ticking()
            return
        self.hovering = True
        main = x if self.cfg.horizontal else y
        rest_start = self._rest_start()
        self.cursor = main
        self.frac = magnify.anchor_fraction(len(self.items), self.params, rest_start, main)
        hovered = self._hit(x, y)
        if hovered != self.hovered:
            self.hovered = hovered
            self.queue_draw()
        self._ensure_ticking()

    def _on_leave(self, _ctl):
        self.hovering = False
        self.cursor = None
        self.hovered = None
        if self.cfg.autohide:
            if self._hide_timer:
                GLib.source_remove(self._hide_timer)
            self._hide_timer = GLib.timeout_add(self.cfg.autohide_delay_ms, self._autohide_fire)
        self._ensure_ticking()
        self.queue_draw()

    def _autohide_fire(self):
        self._hide_timer = 0
        self._ensure_ticking()
        return GLib.SOURCE_REMOVE

    def _on_click(self, gesture, _n, x, y):
        idx = self._hit(x, y)
        if idx is None or idx >= len(self.items):
            return
        self._on_activate(self.items[idx], gesture.get_current_button())

    # ------------------------------------------------------------ animation
    def _ensure_ticking(self):
        if self._tick_id is None:
            self._last_frame = None
            self._tick_id = self.add_tick_callback(self._tick)

    def _tick(self, _widget, clock):
        now = clock.get_frame_time() / 1e6
        dt = 0.016 if self._last_frame is None else min(now - self._last_frame, 0.1)
        self._last_frame = now
        tau = max(self.cfg.animation_ms, 1) / 1000.0
        k = 1.0 - math.exp(-dt / tau)

        busy = False
        cursor = self.cursor if self.hovering else None
        targets = magnify.target_scales(len(self.items), self.params, self._rest_start(), cursor)
        for item, target in zip(self.items, targets):
            diff = target - item.scale
            if abs(diff) < 0.002:
                item.scale = target
            else:
                item.scale += diff * k
                busy = True

        hide_target = 0.0
        if self.cfg.autohide and not self.hovering and not self._hide_timer:
            hide_target = 1.0
        diff = hide_target - self.hide
        if abs(diff) < 0.003:
            self.hide = hide_target
        else:
            self.hide += diff * min(1.0, k * 1.5)
            busy = True
        if self.cfg.autohide and self.hovering and self.hide < 0.5 and self.cursor is None:
            busy = True  # dock just finished revealing; wait for a motion event

        mono = time.monotonic()
        if any(it.bounce_until > mono for it in self.items):
            busy = True

        self.queue_draw()
        self.update_input_region()
        if not busy:
            self._tick_id = None
            return GLib.SOURCE_REMOVE
        return GLib.SOURCE_CONTINUE

    def _bounce_offset(self, item: DockItem) -> float:
        remaining = item.bounce_until - time.monotonic()
        if remaining <= 0:
            return 0.0
        phase = 1.0 - remaining / BOUNCE_SECONDS
        return abs(math.sin(phase * math.pi * 3)) * self.cfg.icon_size * 0.45 * (1 - 0.6 * phase)

    # ------------------------------------------------------------ input region
    def update_input_region(self):
        native = self.get_native()
        surface = native.get_surface() if native else None
        if surface is None or not self.items:
            return
        c = self.cfg
        rects = self._layout()
        shelf_start = rects[0][0] - c.padding
        shelf_end = rects[-1][0] + rects[-1][1] + c.padding
        boxes = []
        if c.autohide and self.hide > 0.5 and not self.hovering:
            rest_start = self._rest_start()
            boxes.append(self._rect(rest_start - c.padding, 0,
                                    magnify.rest_length(len(self.items), self.params) + 2 * c.padding, 3))
        else:
            off = self._hide_offset()
            boxes.append(self._rect(shelf_start, 0, shelf_end - shelf_start, c.margin + self.shelf_thickness - off))
            if self.hovering:
                half = c.spacing / 2
                for start, size in rects:
                    boxes.append(self._rect(start - half, 0, size + c.spacing,
                                            c.margin + c.padding + size - off))
        ints = tuple(
            (int(math.floor(x)), int(math.floor(y)), int(math.ceil(w)) + 1, int(math.ceil(h)) + 1)
            for x, y, w, h in boxes
        )
        if ints == self._region_key:
            return
        self._region_key = ints
        region = cairo.Region([cairo.RectangleInt(*r) for r in ints])
        surface.set_input_region(region)

    # ------------------------------------------------------------ drawing
    def _paintable(self, item: DockItem):
        size = int(math.ceil(self.cfg.icon_size * self.cfg.magnification))
        scale = self.get_scale_factor()
        key = (id(item), size, scale)
        p = self._icon_cache.get(key)
        if p is None:
            theme = Gtk.IconTheme.get_for_display(self.get_display())
            flags = Gtk.IconLookupFlags(0)
            if item.icon is not None:
                p = theme.lookup_by_gicon(item.icon, size, scale, Gtk.TextDirection.NONE, flags)
            else:
                p = theme.lookup_icon("application-x-executable", None, size, scale,
                                      Gtk.TextDirection.NONE, flags)
            self._icon_cache[key] = p
        return p

    def do_snapshot(self, snap: Gtk.Snapshot):
        if not self.items:
            return
        c = self.cfg
        off = self._hide_offset()
        rects = self._layout()

        # Shelf
        shelf_start = rects[0][0] - c.padding
        shelf_end = rects[-1][0] + rects[-1][1] + c.padding
        x, y, w, h = self._rect(shelf_start, c.margin - off, shelf_end - shelf_start, self.shelf_thickness)
        rr = _rounded(x, y, w, h, c.corner_radius)
        snap.push_rounded_clip(rr)
        snap.append_color(_rgba(c.background), _grect(x, y, w, h))
        snap.pop()
        border = _rgba(c.border)
        if border.alpha > 0:
            snap.append_border(rr, [1, 1, 1, 1], [border] * 4)

        indicator = _rgba(c.indicator)
        for item, (start, size) in zip(self.items, rects):
            lift = self._bounce_offset(item)
            ix, iy, iw, ih = self._rect(start, c.margin + c.padding - off + lift, size, size)
            snap.save()
            snap.translate(Graphene.Point().init(ix, iy))
            self._paintable(item).snapshot(snap, iw, ih)
            snap.restore()

            if item.running:
                dot = 5.0
                dx, dy, _, _ = self._rect(start + size / 2 - dot / 2,
                                          c.margin + c.padding / 2 - dot / 2 - off + 1, dot, dot)
                dr = _rounded(dx, dy, dot, dot, dot / 2)
                snap.push_rounded_clip(dr)
                snap.append_color(indicator, _grect(dx, dy, dot, dot))
                snap.pop()

        if c.show_labels and self.hovered is not None and self.hovered < len(self.items) and self.hide < 0.5:
            self._draw_label(snap, self.items[self.hovered], *rects[self.hovered], off)

    def _draw_label(self, snap, item: DockItem, start: float, size: float, off: float):
        c = self.cfg
        layout = self.create_pango_layout(item.name)
        lw, lh = layout.get_pixel_size()
        pad_x, pad_y = 10, 5
        bw, bh = lw + 2 * pad_x, lh + 2 * pad_y
        mlen, clen = (bw, bh) if c.horizontal else (bh, bw)
        main = start + size / 2 - mlen / 2
        main = max(2, min(main, self._main_len() - mlen - 2))
        cpos = c.margin + c.padding + size + LABEL_GAP - off
        x, y, w, h = self._rect(main, cpos, mlen, clen)
        rr = _rounded(x, y, w, h, 7)
        snap.push_rounded_clip(rr)
        snap.append_color(_rgba(c.label_background), _grect(x, y, w, h))
        snap.pop()
        snap.save()
        snap.translate(Graphene.Point().init(x + pad_x, y + pad_y))
        snap.append_layout(layout, _rgba(c.label_foreground))
        snap.restore()


class DockWindow(Gtk.ApplicationWindow):
    """Top-level surface: wlr-layer-shell on Wayland, a _NET_WM dock on X11."""

    def __init__(self, app, cfg: Config, mode: str, on_activate):
        super().__init__(application=app, title="linux-magnify")
        self.cfg = cfg
        self.mode = mode
        self.set_decorated(False)
        self.set_resizable(False)
        self.add_css_class("linux-magnify")

        css = Gtk.CssProvider()
        css.load_from_data(b"window.linux-magnify, window.linux-magnify > * { background: transparent; box-shadow: none; }")
        Gtk.StyleContext.add_provider_for_display(
            Gdk.Display.get_default(), css, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)

        self._x11 = None
        self.view = DockView(cfg, on_activate, self._on_size_changed)
        self.set_child(self.view)
        if mode == "layer":
            self._setup_layer_shell()
        elif mode == "x11":
            from .x11 import X11Dock
            self._x11 = X11Dock(self)

        self.connect("map", lambda *_: GLib.idle_add(self._after_map))
        self.view.update_size()

    def _after_map(self):
        self.view.update_input_region()
        if self._x11:
            self._x11.place()
        return GLib.SOURCE_REMOVE

    def _monitor(self):
        monitors = Gdk.Display.get_default().get_monitors()
        idx = self.cfg.monitor
        if 0 <= idx < monitors.get_n_items():
            return monitors.get_item(idx)
        return monitors.get_item(0) if monitors.get_n_items() else None

    def _setup_layer_shell(self):
        gi.require_version("Gtk4LayerShell", "1.0")
        from gi.repository import Gtk4LayerShell as LS

        LS.init_for_window(self)
        LS.set_namespace(self, "linux-magnify")
        LS.set_keyboard_mode(self, LS.KeyboardMode.NONE)
        self.apply_layer_config()

    def apply_layer_config(self):
        from gi.repository import Gtk4LayerShell as LS

        cfg = self.cfg
        layers = {"top": LS.Layer.TOP, "overlay": LS.Layer.OVERLAY,
                  "bottom": LS.Layer.BOTTOM, "background": LS.Layer.BACKGROUND}
        LS.set_layer(self, layers.get(cfg.layer, LS.Layer.TOP))
        edges = {"bottom": LS.Edge.BOTTOM, "top": LS.Edge.TOP, "left": LS.Edge.LEFT, "right": LS.Edge.RIGHT}
        for name, edge in edges.items():
            LS.set_anchor(self, edge, name == cfg.position)
            LS.set_margin(self, edge, 0)
        LS.set_exclusive_zone(self, 0 if cfg.autohide else self.view.reserved)
        mon = self._monitor()
        if mon is not None and cfg.monitor > 0:
            LS.set_monitor(self, mon)

    def apply_config(self, cfg: Config):
        self.cfg = cfg
        self.view.cfg = cfg
        self.view._icon_cache.clear()
        self.view.hide = 1.0 if cfg.autohide and not self.view.hovering else 0.0
        if self.mode == "layer":
            self.apply_layer_config()
        self.view.update_size()
        if self._x11:
            self._x11.place()

    def _on_size_changed(self, w: int, h: int):
        self.set_default_size(w, h)
        if self._x11 and self.get_mapped():
            self._x11.place()
