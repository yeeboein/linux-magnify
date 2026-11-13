"""Magdoc's D-Bus service (io.github.linux_magnify.Dock on the session bus).

* ``Windows(s json)``: the KWin script pushes the window list here.
* ``ToggleMenu()``: opens/closes the start menu; bound to the Meta key on Plasma.
"""

from __future__ import annotations

from gi.repository import Gio

NAME = "io.github.linux_magnify.Dock"
XML = f"""
<node>
  <interface name="{NAME}">
    <method name="Windows"><arg type="s" name="json" direction="in"/></method>
    <method name="ToggleMenu"/>
  </interface>
</node>
"""


class DockService:
    def __init__(self):
        self.handlers: dict = {}
        self.bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
        node = Gio.DBusNodeInfo.new_for_xml(XML)
        self._reg = self.bus.register_object("/Dock", node.interfaces[0], self._on_call, None, None)
        self._owner = Gio.bus_own_name_on_connection(self.bus, NAME, Gio.BusNameOwnerFlags.REPLACE, None, None)

    def _on_call(self, _conn, _sender, _path, _iface, method, params, invocation):
        handler = self.handlers.get(method)
        try:
            if handler is not None:
                handler(*params.unpack())
        except Exception as exc:
            print(f"magdoc: D-Bus {method} failed: {exc}")
        invocation.return_value(None)

    def close(self):
        try:
            self.bus.unregister_object(self._reg)
            Gio.bus_unown_name(self._owner)
        except Exception:
            pass


def start() -> DockService | None:
    try:
        return DockService()
    except Exception as exc:
        print(f"magdoc: no D-Bus session ({exc}); KWin window tracking and the Meta key are off")
        return None
