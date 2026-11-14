"""Configuration loading (TOML)."""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

POSITIONS = ("bottom", "top", "left", "right")

# Used only when nothing can be imported from the desktop's own panel or dock.
FALLBACK_PINNED = [
    "org.kde.dolphin", "org.gnome.Nautilus", "thunar", "nemo", "pcmanfm",
    "firefox", "org.mozilla.firefox", "chromium", "google-chrome", "brave-browser",
    "org.kde.konsole", "org.gnome.Console", "kitty", "Alacritty", "foot",
    "xfce4-terminal", "systemsettings", "org.gnome.Settings",
]
HIDE_PANEL_MODES = ("dock", "all", "none")
# never | always | dodge (hide while a window overlaps the dock) | auto (copy the original panel)
HIDE_MODES = ("auto", "never", "always", "dodge")


@dataclass
class PinnedApp:
    """A pinned entry: a desktop-file id, or a custom command."""

    desktop_id: str | None = None
    name: str | None = None
    exec: str | None = None
    icon: str | None = None
    wm_class: str | None = None


@dataclass
class Config:
    position: str = "bottom"
    icon_size: int = 48
    magnification: float = 2.0
    spread: float = 3.0
    spacing: int = 8
    padding: int = 8
    margin: int = 8
    hide_mode: str = "auto"
    autohide_delay_ms: int = 400
    show_labels: bool = True
    show_running: bool = True
    animation_ms: int = 90
    monitor: int = 0
    layer: str = "top"
    backend: str = "auto"  # auto | wayland | x11
    # Hide the desktop's own panels/docks while linux-magnify is enabled (24/7, also across logins):
    # "all" = every panel, dock and bar (only magdoc), "dock" = the dock's edge + other docks, "none".
    hide_panels: str = "all"

    home_enabled: bool = True
    home_icon: str = "auto"      # "auto" copies the launcher icon from the original panel
    home_command: str = "auto"   # "auto" opens the desktop's own app menu

    update_notify: bool = True    # notify when a new linux-magnify version is on GitHub
    update_branch: str = "main"

    background: str = "rgba(28, 28, 32, 0.55)"
    border: str = "rgba(255, 255, 255, 0.18)"
    corner_radius: float = 18.0
    indicator: str = "rgba(255, 255, 255, 0.9)"
    label_background: str = "rgba(20, 20, 24, 0.85)"
    label_foreground: str = "rgba(255, 255, 255, 1.0)"

    pinned: list[PinnedApp] = field(default_factory=list)
    pinned_imported: bool = False  # True when pins were copied from the original panel
    path: Path | None = None

    # Filled in at runtime when hide_mode is "auto" (from the original panel); not saved.
    resolved_hide_mode: str | None = None

    @property
    def effective_hide_mode(self) -> str:
        if self.hide_mode == "auto":
            return self.resolved_hide_mode or "never"
        return self.hide_mode

    @property
    def autohide(self) -> bool:
        """True when the dock may slide away (always, or when dodging windows)."""
        return self.effective_hide_mode in ("always", "dodge")

    @property
    def horizontal(self) -> bool:
        return self.position in ("bottom", "top")


def config_dir() -> Path:
    base = os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config")
    return Path(base) / "linux-magnify"


def default_config_path() -> Path:
    return config_dir() / "config.toml"


def _parse_pinned(raw) -> list[PinnedApp]:
    out: list[PinnedApp] = []
    for item in raw or []:
        if isinstance(item, str):
            out.append(PinnedApp(desktop_id=item))
        elif isinstance(item, dict):
            out.append(PinnedApp(
                desktop_id=item.get("id"),
                name=item.get("name"),
                exec=item.get("exec"),
                icon=item.get("icon"),
                wm_class=item.get("wm_class"),
            ))
    return out


DOCK_KEYS = ("position", "icon_size", "magnification", "spread", "spacing", "padding", "margin",
             "hide_mode", "autohide_delay_ms", "show_labels", "show_running", "animation_ms",
             "monitor", "layer", "backend", "hide_panels")
STYLE_KEYS = ("background", "border", "corner_radius", "indicator", "label_background",
              "label_foreground")
HOME_KEYS = {"enabled": "home_enabled", "icon": "home_icon", "command": "home_command"}
UPDATE_KEYS = {"notify": "update_notify", "branch": "update_branch"}


def _coerce(default, value):
    if isinstance(default, bool):
        return bool(value)
    if isinstance(default, int):
        return int(value)
    if isinstance(default, float):
        return float(value)
    return str(value)


def load(path: Path | None = None, import_pins: bool = True) -> Config:
    path = path or default_config_path()
    cfg = Config(path=path)
    data: dict = {}
    if path.exists():
        with open(path, "rb") as fh:
            data = tomllib.load(fh)

    for section, keys in (("dock", DOCK_KEYS), ("style", STYLE_KEYS)):
        for key, value in data.get(section, {}).items():
            if key in keys:
                setattr(cfg, key, _coerce(getattr(cfg, key), value))
    dock = data.get("dock", {})
    if "hide_mode" not in dock and "autohide" in dock:  # config files from before hide_mode
        cfg.hide_mode = "always" if dock["autohide"] else "never"
    for section, keys in (("home", HOME_KEYS), ("updates", UPDATE_KEYS)):
        for key, value in data.get(section, {}).items():
            if key in keys:
                attr = keys[key]
                setattr(cfg, attr, _coerce(getattr(cfg, attr), value))

    if cfg.position not in POSITIONS:
        cfg.position = "bottom"
    if cfg.hide_mode not in HIDE_MODES:
        cfg.hide_mode = "auto"
    if cfg.hide_panels not in HIDE_PANEL_MODES:
        cfg.hide_panels = "all"
    cfg.magnification = max(1.0, min(cfg.magnification, 4.0))
    cfg.icon_size = max(16, min(cfg.icon_size, 256))
    cfg.spread = max(0.5, cfg.spread)

    apps = data.get("apps", {})
    if "pinned" in apps:
        cfg.pinned = _parse_pinned(apps["pinned"])
    elif import_pins:
        from .panels import import_pinned  # local import: panels is optional at config time

        ids = import_pinned()
        cfg.pinned = [PinnedApp(desktop_id=d) for d in (ids or FALLBACK_PINNED)]
        cfg.pinned_imported = bool(ids)
        cfg.pinned_is_default = not ids  # type: ignore[attr-defined]
    return cfg


def _toml_value(v) -> str:
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (int, float)):
        return repr(v)
    s = str(v).replace("\\", "\\\\").replace('"', '\\"')
    return f'"{s}"'


def _pinned_toml(p: PinnedApp) -> str:
    if p.desktop_id and not (p.exec or p.name or p.icon or p.wm_class):
        return _toml_value(p.desktop_id)
    parts = []
    for key, val in (("id", p.desktop_id), ("name", p.name), ("exec", p.exec),
                     ("icon", p.icon), ("wm_class", p.wm_class)):
        if val:
            parts.append(f"{key} = {_toml_value(val)}")
    return "{ " + ", ".join(parts) + " }"


def dumps(cfg: Config) -> str:
    lines = ["# linux-magnify configuration. Written by linux-magnify Settings; the dock reloads it on save.", ""]
    lines.append("[dock]")
    lines += [f"{k} = {_toml_value(getattr(cfg, k))}" for k in DOCK_KEYS]
    lines += ["", "[style]"]
    lines += [f"{k} = {_toml_value(getattr(cfg, k))}" for k in STYLE_KEYS]
    lines += ["", "[home]"]
    lines += [f"{k} = {_toml_value(getattr(cfg, a))}" for k, a in HOME_KEYS.items()]
    lines += ["", "[updates]"]
    lines += [f"{k} = {_toml_value(getattr(cfg, a))}" for k, a in UPDATE_KEYS.items()]
    lines += ["", "[apps]"]
    if cfg.pinned_imported or getattr(cfg, "pinned_is_default", False):
        # Not customised yet: keep copying the pinned apps from the original panel.
        lines += ["# pinned = [ ... ]  (unset: copied from your desktop's own panel/dock)", ""]
    else:
        lines += ["pinned = ["] + [f"  {_pinned_toml(p)}," for p in cfg.pinned] + ["]", ""]
    return "\n".join(lines)


def save(cfg: Config, path: Path | None = None) -> Path:
    """Write the config atomically (the dock watches this file)."""
    path = path or cfg.path or default_config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".toml.tmp")
    tmp.write_text(dumps(cfg))
    os.replace(tmp, path)
    return path
