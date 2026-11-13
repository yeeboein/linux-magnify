# Magdoc

**Magdoc** (this repo: linux-magnify) is a dock with **macOS-style magnification** for Linux. Move the cursor across it and
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
- **Only Magdoc:** your original panels and docks are hidden all the time while Magdoc is enabled, also across logins, and come back when you turn Magdoc off (see [below](#your-original-panels))
- **Copies your panel:** the pinned apps and the launcher ("home") icon come from your existing panel or dock
- **Start menu:** the home button (and the Meta key on Plasma) opens Magdoc's own start menu, built with Quickshell. It opens just above the dock, so the dock never covers it
- Shows only pinned apps and open apps, with running-app dots
- **Pin your own apps:** right-click any icon to pin or unpin it, or manage the list in Magdoc Settings
- **Hiding modes:** always visible, hide when a window covers the dock, always auto-hide, or the same as your original panel. Push the pointer against the screen edge to bring a hidden dock back.
- **Magdoc Settings** (Quickshell) with an on/off switch: every option, applied live
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

   **Quickshell** (recommended) gives you the Magdoc start menu and the Quickshell settings app.
   On Arch it's `sudo pacman -S quickshell` (or the `quickshell-git` AUR package). Without it,
   the home button opens KRunner on Plasma and the settings open in a GTK window.

2. Install Magdoc:

   ```bash
   ./install.sh
   ```

   This puts the `magdoc` command in `~/.local/bin` (`linux-magnify` still works too),
   writes a starter config, and can enable autostart for desktops that read
   `~/.config/autostart`.

   Or run it straight from the checkout:

   ```bash
   python3 -m linux_magnify
   ```

### Hyprland

Add to `~/.config/hypr/hyprland.conf`:

```ini
exec-once = magdoc
bind = SUPER, SPACE, exec, magdoc --menu   # optional: open the Magdoc start menu

# Optional: blur behind the shelf (layer namespace is "magdoc").
# Rule syntax differs between Hyprland versions; this is the classic form.
layerrule = blur, magdoc
layerrule = ignorezero, magdoc
```

### Sway

```ini
exec magdoc
bindsym $mod+space exec magdoc --menu
```

### KDE Plasma

Run `./install.sh` and answer yes to autostart, or use the switch in Magdoc Settings. Then:

- Your Plasma panels are removed (after backing up their exact configuration), so they can't pop up when you touch a screen edge or open a menu, and they don't flash at login.
- Their pinned apps and launcher icon are copied to Magdoc.
- The **Meta key** opens the Magdoc start menu, since Plasma's own menu (Kickoff) lived in the removed panel.
- Running-app dots, click-to-focus and window dodging use a small KWin script that Magdoc loads itself.

Turning Magdoc off (`magdoc --disable`, or the switch in Magdoc Settings) puts the panels back exactly as they were and restarts plasmashell. Any other desktop changes you made in the meantime, such as your wallpaper or desktop widgets, are kept.

## Magdoc Settings

Open **Magdoc Settings** from your app menu or the start menu, right-click any dock icon and pick **Magdoc Settings…**, or run:

```bash
magdoc --settings
```

It's a Quickshell app that follows your Plasma colour scheme. If Quickshell isn't installed, a GTK version opens instead, and `magdoc --settings --gtk` forces the GTK one.

- **General:** the **Enable Magdoc** switch starts Magdoc and turns on autostart. Turning it off stops Magdoc and brings your original panels back. Also position, monitor, hiding mode, labels, open apps, and which original panels to hide.
- **Appearance:** icon size, magnification, spread, animation speed, spacing and colours.
- **Apps:** pinned apps. Add, remove and reorder them, or copy them from your original panel again.
- **Home button:** show or hide it, and override its icon or command.

Changes apply to the running dock immediately.

## Commands

| Command | What it does |
|---|---|
| `magdoc` | Start the dock |
| `magdoc --settings` | Open Magdoc Settings |
| `magdoc --menu` | Open or close the start menu (bind it to a key on Hyprland/Sway) |
| `magdoc --enable` | Start Magdoc and turn on autostart |
| `magdoc --disable` | Stop Magdoc, turn off autostart and bring your original panels back |
| `magdoc --restore-panels` | Bring the original panels back without turning off autostart |

## Your original panels

While Magdoc is enabled, the desktop's own panels and docks are hidden **all the time**. Quitting the dock (for example at logout) doesn't bring them back; only turning Magdoc off does.

| Desktop | What happens |
|---|---|
| KDE Plasma | Panels are removed after their configuration is backed up, and the Meta key opens the Magdoc menu |
| Cinnamon, MATE, Xfce | Panels switch to auto-hide |
| GNOME / Ubuntu | The Dash to Dock / Ubuntu Dock extension is turned off |
| Plank, Latte, nwg-dock, Cairo-Dock and other docks | Stopped, then started again when Magdoc is turned off |
| Waybar, Polybar, tint2 and other bars | Stopped too (with the default "Every panel and dock") |

Choose **Panels on the dock's edge** or **Don't hide anything** in Magdoc Settings (General → Hide the original panels) to keep some panels.

Everything changed is recorded in `~/.local/state/linux-magnify/` before it's changed, so a crash can't lose your setup. If you ever uninstall Magdoc, or need your panels back, run:

```bash
magdoc --disable
```

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
magdoc --position left --magnification 2.5 --icon-size 56
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
- `linux_magnify/panels.py` also removes and restores Plasma panels: it backs up
  `plasma-org.kde.plasma.desktop-appletsrc` and `plasmashellrc`, and on restore merges
  back only the removed panels' sections before restarting plasmashell.
- `linux_magnify/qml/menu.qml` is the start menu and `linux_magnify/qml/settings.qml`
  the settings app (Quickshell). The settings app reads and writes the config through
  `magdoc --config-json` / `--config-set`; `linux_magnify/settings.py` is the GTK fallback.
- The dock owns the D-Bus name `io.github.linux_magnify.Dock` (`ToggleMenu` for the
  Meta key, `Windows` for the KWin script).

## Tests

```bash
python3 -m unittest discover -s tests
```

## License

MIT
