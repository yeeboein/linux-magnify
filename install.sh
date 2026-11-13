#!/usr/bin/env bash
# Installs Magdoc for the current user and (optionally) enables autostart.
set -euo pipefail
cd "$(dirname "$0")"

missing=()
python3 -c 'import gi; gi.require_version("Gtk", "4.0"); from gi.repository import Gtk' 2>/dev/null || missing+=("GTK4 + PyGObject")
python3 -c 'import cairo' 2>/dev/null || missing+=("pycairo (python3-gi-cairo)")
if [[ -n "${WAYLAND_DISPLAY:-}" ]]; then
  python3 -c 'import gi; gi.require_version("Gtk4LayerShell", "1.0")' 2>/dev/null || missing+=("gtk4-layer-shell")
fi
if [[ -n "${DISPLAY:-}" && -z "${WAYLAND_DISPLAY:-}" ]]; then
  python3 -c 'import Xlib' 2>/dev/null || missing+=("python-xlib")
fi
if (( ${#missing[@]} )); then
  echo "Missing dependencies: ${missing[*]}"
  echo
  echo "  Arch / Manjaro / EndeavourOS:  sudo pacman -S gtk4 gtk4-layer-shell python-gobject python-cairo python-xlib"
  echo "  Fedora:                        sudo dnf install gtk4 gtk4-layer-shell python3-gobject python3-cairo python3-xlib"
  echo "  Debian 13 / Ubuntu 24.10+:     sudo apt install gir1.2-gtk-4.0 gir1.2-gtk4layershell-1.0 python3-gi python3-gi-cairo python3-xlib"
  echo "  openSUSE:                      sudo zypper install typelib-1_0-Gtk-4_0 typelib-1_0-Gtk4LayerShell-1_0 python3-gobject-cairo python3-xlib"
  echo
  read -rp "Continue anyway? [y/N] " ans; [[ "$ans" == [yY]* ]] || exit 1
fi
if ! command -v qs >/dev/null && ! command -v quickshell >/dev/null; then
  echo "Optional: install Quickshell for the Magdoc start menu and the Quickshell settings app"
  echo "  (Arch: sudo pacman -S quickshell, or the quickshell-git AUR package)."
  echo "  Without it, Magdoc uses KRunner as the start menu on Plasma and a GTK settings app."
  echo
fi

bin="$HOME/.local/bin"
share="$HOME/.local/share/linux-magnify"
apps="$HOME/.local/share/applications"
conf="$HOME/.config/linux-magnify"
autostart="$HOME/.config/autostart"

# Ask everything up front, before touching anything.
read -rp "Start Magdoc automatically on login? [Y/n] " ans
want_autostart=1; [[ "$ans" == [nN]* ]] && want_autostart=0

# --- Stage: build everything in a temp dir. Interrupting here changes nothing.
mkdir -p "$HOME/.local/share"
stage="$(mktemp -d "$HOME/.local/share/.magdoc-install.XXXXXX")"
trap 'rm -rf "$stage"' EXIT
trap 'echo; echo "Install cancelled. Nothing was changed."; exit 130' INT TERM HUP

cp -r linux_magnify "$stage/linux_magnify"
find "$stage/linux_magnify" -name __pycache__ -prune -exec rm -rf {} +
cat > "$stage/launcher" <<SH
#!/bin/sh
export PYTHONPATH="$share\${PYTHONPATH:+:\$PYTHONPATH}"
exec python3 -m linux_magnify "\$@"
SH
chmod +x "$stage/launcher"
sed "s|^Exec=.*|Exec=$bin/magdoc|" data/magdoc.desktop > "$stage/app.desktop"
sed "s|^Exec=.*|Exec=$bin/magdoc --settings|" data/magdoc-settings.desktop > "$stage/settings.desktop"
cp "$stage/app.desktop" "$stage/autostart.desktop"
cp data/config.example.toml "$stage/config.toml"

# --- Commit: a handful of quick renames. Signals are ignored only for this
# fraction of a second so the install can't be left half-done.
trap '' INT TERM HUP
mkdir -p "$bin" "$share" "$apps" "$conf"
[[ -d "$share/linux_magnify" ]] && mv "$share/linux_magnify" "$stage/old"
mv "$stage/linux_magnify" "$share/linux_magnify"
mv -f "$stage/launcher" "$bin/magdoc"
ln -sfn magdoc "$bin/linux-magnify"   # the old command name keeps working
mv -f "$stage/app.desktop" "$apps/magdoc.desktop"
mv -f "$stage/settings.desktop" "$apps/magdoc-settings.desktop"
rm -f "$apps/linux-magnify.desktop" "$apps/linux-magnify-settings.desktop"   # old names
wrote_config=0
if [[ ! -f "$conf/config.toml" ]]; then
  mv "$stage/config.toml" "$conf/config.toml"; wrote_config=1
fi
rm -f "$autostart/linux-magnify.desktop"   # old name; don't start twice
if (( want_autostart )); then
  mkdir -p "$autostart"
  mv -f "$stage/autostart.desktop" "$autostart/magdoc.desktop"
fi
trap - INT TERM HUP

(( wrote_config )) && echo "Wrote ~/.config/linux-magnify/config.toml."
if (( want_autostart )); then
  echo "Autostart enabled (KDE, GNOME, XFCE, Cinnamon, MATE, LXQt...)."
  echo "Hyprland/Sway don't read ~/.config/autostart. See the README for the exec-once line."
fi
echo "Installed. Run: magdoc"
echo "Settings: open \"Magdoc Settings\" from your app menu, or run: magdoc --settings"
echo "To turn Magdoc off and get your original panels back: magdoc --disable"
