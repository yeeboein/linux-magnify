# linux-magnify

A dock with **macOS-style magnification** for Linux. Move the cursor across it and
the icons swell smoothly, with neighbours tapering off on a cosine curve and the
point under the cursor staying put, like the macOS Dock.

It is one standalone dock that runs on many desktops, so it does not depend on any
single DE's panel:

| Desktop / compositor | How it attaches | Running-app indicators & focus |
|---|---|---|
| **KDE Plasma 6 (Wayland)** | wlr-layer-shell | ✅ (built-in KWin script) |
| **KDE Plasma (X11)** | EWMH dock window | ✅ |
| **Hyprland** | wlr-layer-shell | ✅ (`hyprctl`) |
| **Sway / SwayFX** | wlr-layer-shell | ✅ (`swaymsg`) |
| **niri** | wlr-layer-shell | ✅ (`niri msg`) |
| river, Wayfire, labwc, COSMIC, other wlroots | wlr-layer-shell | launch only |
| **XFCE, Cinnamon, MATE, Budgie, LXQt, i3, Openbox** (X11) | EWMH dock window | ✅ |
| **GNOME** | GNOME Wayland has no layer-shell, so the dock uses XWayland automatically. It works best on "GNOME on Xorg" | ✅ on Xorg |

## Features

- Smooth, frame-synced magnification (cosine falloff, configurable size and spread)
- **Replaces your original panel or dock:** it's hidden while Linux Magnify runs and comes back when the dock stops or you disable it (see [below](#your-original-panel))
- **Copies your panel:** the pinned apps and the app-launcher ("home") icon come from your existing panel or dock, and clicking the home button opens your desktop's own app menu
- Shows only pinned apps and open apps, with running-app dots
- **Pin your own apps:** right-click any icon to pin or unpin it, or manage the list in the settings app
- **Hiding modes:** always visible, hide when a window covers the dock, always auto-hide, or the same as your original panel. Push the pointer against the screen edge to bring a hidden dock back.
- **Settings app** with an on/off switch: every option, applied live
- Position on the bottom, top, left or right edge, any monitor
- App-name label above the hovered icon, and a bounce when an app launches
- Clicking a running app focuses it, and clicking again cycles its windows. Middle-click opens a new instance.
- Input passes through the transparent part of the dock, so only the shelf and icons take clicks

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

Run `./install.sh` and answer yes to autostart, or use the switch in the settings app.
The Plasma panel on the dock's edge is hidden automatically, and its pinned apps and
launcher icon are copied to the dock. Running-app dots, click-to-focus and window
dodging use a small KWin script that the dock loads and unloads itself.

## Settings app

Open **Linux Magnify Settings** from your app menu, right-click any dock icon and pick **Dock Settings…**, or run:

```bash
linux-magnify --settings
```

- **General:** the **Enable Linux Magnify** switch starts or stops the dock and turns autostart on or off; stopping it brings your original panel back. Also position, monitor, hiding mode, labels, open apps, and how much of the original panel to hide.
- **Appearance:** icon size, magnification, spread, animation speed, spacing and colours.
- **Apps:** pinned apps. Add, remove and reorder them, or copy them from your original panel again.
- **Home button:** show or hide it, and override its icon or command.

Changes apply to the running dock immediately.

## Your original panel

While the dock runs, Linux Magnify hides the desktop's own panel or dock, and restores it when the dock stops:

| Desktop | What happens |
|---|---|
| KDE Plasma | Panels on the dock's edge switch to auto-hide (plasmashell scripting) |
| Cinnamon, MATE, Xfce | Panels on the dock's edge switch to auto-hide |
| GNOME / Ubuntu | The Dash to Dock / Ubuntu Dock extension is turned off |
| Plank, Latte, nwg-dock, Cairo-Dock and other docks | Stopped, then started again afterwards |
| Waybar, Polybar, tint2 and other bars | Stopped only when "Every panel and bar" is selected |

Everything changed is recorded in `~/.local/state/linux-magnify/hidden-panels.json` before it's changed, so a crash can't lose your setup. If the dock is ever killed without cleaning up, this brings your panel back:

```bash
linux-magnify --restore-panels
```

On Plasma the original panel is set to auto-hide rather than removed, so pushing the pointer hard against that screen edge can briefly reveal it.

The pinned apps are copied from the Plasma task manager, the Cinnamon, Xfce or GNOME favourites, Plank or nwg-dock. They stay in sync with your panel until you change the list yourself.

## Hiding

`hide_mode` (General → Hiding in the settings app):

- **Same as original panel** (`auto`): copies your panel's setting, read before the panel is hidden
- **Always visible** (`never`): reserves space so maximised windows stop above the dock
- **Hide when a window covers it** (`dodge`)
- **Always auto-hide** (`always`)

When the dock is hidden, push the pointer against the screen edge to show it. Dodging needs window positions, which come from KWin (Plasma, through a small KWin script the dock loads), Hyprland, Sway, or any X11 window manager.

## Configure

Edit `~/.config/linux-magnify/config.toml`. The dock reloads it when you save.
See [`data/config.example.toml`](data/config.example.toml) for every option.

```toml
[dock]
position = "bottom"
icon_size = 48
magnification = 2.0   # 1.0 disables the effect
spread = 3.0          # icons affected on each side
hide_mode = "auto"    # auto | never | dodge | always

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
- `linux_magnify/windows.py` gets the open windows and their positions from the
  compositor (a KWin script on Plasma, hyprctl, swaymsg, niri, or EWMH on X11) and
  matches them to icons by desktop id, `StartupWMClass` or executable name.
- `linux_magnify/panels.py` hides and restores the original panel and copies its
  pinned apps; `linux_magnify/home.py` finds its launcher icon and menu.
- `linux_magnify/settings.py` is the settings app. It writes the config file,
  which the dock watches.

## Tests

```bash
python3 -m unittest discover -s tests
```

## License

MIT
