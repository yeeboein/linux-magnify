# linux-magnify

A dock with **macOS-style magnification** for Linux. Move the cursor across it and
the icons swell smoothly, with neighbours tapering off on a cosine curve and the
point under the cursor staying put, like the macOS Dock.

It is one standalone dock that runs on many desktops, so it does not depend on any
single DE's panel:

| Desktop / compositor | How it attaches | Running-app indicators & focus |
|---|---|---|
| **KDE Plasma 6 (Wayland)** | wlr-layer-shell | with [`kdotool`](https://github.com/jinliu/kdotool) installed |
| **KDE Plasma (X11)** | EWMH dock window | ✅ |
| **Hyprland** | wlr-layer-shell | ✅ (`hyprctl`) |
| **Sway / SwayFX** | wlr-layer-shell | ✅ (`swaymsg`) |
| **niri** | wlr-layer-shell | ✅ (`niri msg`) |
| river, Wayfire, labwc, COSMIC, other wlroots | wlr-layer-shell | launch only |
| **XFCE, Cinnamon, MATE, Budgie, LXQt, i3, Openbox** (X11) | EWMH dock window | ✅ |
| **GNOME** | GNOME Wayland has no layer-shell, so the dock uses XWayland automatically. It works best on "GNOME on Xorg" | ✅ on Xorg |

## Features

- Smooth, frame-synced magnification (cosine falloff, configurable size and spread)
- Position on the bottom, top, left or right edge, any monitor
- App-name label above the hovered icon
- Bounce animation when an app launches
- Running-app dots. Clicking a running app focuses it, and clicking again cycles its windows. Middle-click opens a new instance.
- Shows running apps that aren't pinned (optional)
- Auto-hide (optional), or reserves screen space so maximised windows don't cover it
- Input passes through the transparent part of the dock, so only the shelf and icons take clicks
- Uses your icon theme and `.desktop` files. Custom commands are supported too.
- Reloads the config file as soon as you save it

## Install

1. Install the dependencies. Package names vary a little between distro releases.

   ```bash
   # Arch / Manjaro / EndeavourOS
   sudo pacman -S gtk4 gtk4-layer-shell python-gobject python-cairo python-xlib
   ```
   ```bash
   # Fedora
   sudo dnf install gtk4 gtk4-layer-shell python3-gobject python3-cairo python3-xlib
   ```
   ```bash
   # Debian 13 / Ubuntu 24.10+
   sudo apt install gir1.2-gtk-4.0 gir1.2-gtk4layershell-1.0 python3-gi python3-gi-cairo python3-xlib
   ```
   ```bash
   # openSUSE Tumbleweed
   sudo zypper install typelib-1_0-Gtk-4_0 typelib-1_0-Gtk4LayerShell-1_0 python3-gobject-cairo python3-xlib
   ```

   `gtk4-layer-shell` is needed on Wayland and `python-xlib` on X11.

2. Install the dock:

   ```bash
   ./install.sh
   ```

   This puts `linux-magnify` in `~/.local/bin`, writes a starter config, and can
   enable autostart for DEs that read `~/.config/autostart`.

   Or run it straight from the checkout:

   ```bash
   python3 -m linux_magnify
   ```

### Hyprland

Add to `~/.config/hypr/hyprland.conf`:

```ini
exec-once = linux-magnify

# Optional: blur behind the shelf (layer namespace is "linux-magnify").
# Rule syntax differs between Hyprland versions; this is the classic form.
layerrule = blur, linux-magnify
layerrule = ignorezero, linux-magnify
```

### Sway

```ini
exec linux-magnify
```

### KDE Plasma

Run `./install.sh` and answer yes to autostart, or add it under *System Settings → Autostart*.
You'll probably want to remove or auto-hide the default Plasma panel (or move it
to the top) so the two don't overlap. For running-app dots on Plasma Wayland,
install `kdotool`.

## Configure

Edit `~/.config/linux-magnify/config.toml`. The dock reloads it when you save.
See [`data/config.example.toml`](data/config.example.toml) for every option.

```toml
[dock]
position = "bottom"
icon_size = 48
magnification = 2.0   # 1.0 disables the effect
spread = 3.0          # icons affected on each side
autohide = false

[apps]
pinned = ["org.kde.dolphin", "firefox", "org.kde.konsole",
          { name = "htop", exec = "kitty htop", icon = "utilities-system-monitor" }]
```

Command-line overrides:

```bash
linux-magnify --position left --magnification 2.5 --icon-size 56
```

Use `--backend x11` to force XWayland, for example on a compositor without layer-shell.

## How it works

- `linux_magnify/magnify.py` holds the pure math, which is unit tested. Each icon's
  scale comes from its distance to the cursor, measured against the *resting*
  layout so there's no feedback jitter. The grown row is then shifted so the
  cursor's relative position along it stays fixed.
- `linux_magnify/dock.py` is a GTK4 widget. It draws the shelf and icons with
  `GtkSnapshot`, animates in a frame-clock tick callback (it only runs while
  something is moving), and updates the surface's input region every frame.
- On Wayland the window becomes a `wlr-layer-shell` surface anchored to a screen
  edge. The program re-execs itself with `LD_PRELOAD=libgtk4-layer-shell.so`,
  which that library requires. On X11 it is marked `_NET_WM_WINDOW_TYPE_DOCK`
  with struts and positioned through python-xlib.
- `linux_magnify/windows.py` polls the compositor (hyprctl, swaymsg, niri, kdotool,
  or EWMH) for open windows and matches them to icons by desktop id,
  `StartupWMClass` or executable name.

## Tests

```bash
python3 -m unittest discover -s tests
```

## License

MIT
