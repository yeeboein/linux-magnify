#!/usr/bin/env bash
# Installs linux-magnify for the current user and (optionally) enables autostart.
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

bin="$HOME/.local/bin"
share="$HOME/.local/share/linux-magnify"
mkdir -p "$bin" "$share" "$HOME/.config/linux-magnify"
rm -rf "$share/linux_magnify"
cp -r linux_magnify "$share/"
cat > "$bin/linux-magnify" <<SH
#!/bin/sh
export PYTHONPATH="$share\${PYTHONPATH:+:\$PYTHONPATH}"
exec python3 -m linux_magnify "\$@"
SH
chmod +x "$bin/linux-magnify"

if [[ ! -f "$HOME/.config/linux-magnify/config.toml" ]]; then
  cp data/config.example.toml "$HOME/.config/linux-magnify/config.toml"
  echo "Wrote ~/.config/linux-magnify/config.toml (edit 'pinned' to taste)."
fi

mkdir -p "$HOME/.local/share/applications"
sed "s|^Exec=.*|Exec=$bin/linux-magnify|" data/linux-magnify.desktop > "$HOME/.local/share/applications/linux-magnify.desktop"

read -rp "Start the dock automatically on login? [Y/n] " ans
if [[ "$ans" != [nN]* ]]; then
  mkdir -p "$HOME/.config/autostart"
  cp "$HOME/.local/share/applications/linux-magnify.desktop" "$HOME/.config/autostart/"
  echo "Autostart enabled (KDE, GNOME, XFCE, Cinnamon, MATE, LXQt...)."
  echo "Hyprland/Sway don't read ~/.config/autostart — see README for the exec-once line."
fi
echo "Installed. Run: linux-magnify"
