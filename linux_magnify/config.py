"""Configuration loading (TOML)."""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

POSITIONS = ("bottom", "top", "left", "right")

DEFAULT_PINNED = [
    # The first entries that are actually installed get pinned by default.
    "org.kde.dolphin", "org.gnome.Nautilus", "thunar", "nemo", "pcmanfm",
    "firefox", "org.mozilla.firefox", "chromium", "google-chrome", "brave-browser",
    "org.kde.konsole", "org.gnome.Console", "kitty", "Alacritty", "foot", "org.wezfurlong.wezterm",
    "xfce4-terminal",
    "code", "org.kde.kate", "org.gnome.TextEditor",
    "thunderbird", "org.mozilla.Thunderbird",
    "spotify", "vlc", "org.kde.elisa",
    "systemsettings", "org.gnome.Settings",
]


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
    autohide: bool = False
    autohide_delay_ms: int = 400
    show_labels: bool = True
    show_running: bool = True
    animation_ms: int = 90
    monitor: int = 0
    layer: str = "top"
    backend: str = "auto"  # auto | wayland | x11

    background: str = "rgba(28, 28, 32, 0.55)"
    border: str = "rgba(255, 255, 255, 0.18)"
    corner_radius: float = 18.0
    indicator: str = "rgba(255, 255, 255, 0.9)"
    label_background: str = "rgba(20, 20, 24, 0.85)"
    label_foreground: str = "rgba(255, 255, 255, 1.0)"

    pinned: list[PinnedApp] = field(default_factory=list)
    path: Path | None = None

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


def load(path: Path | None = None) -> Config:
    path = path or default_config_path()
    cfg = Config(path=path)
    data: dict = {}
    if path.exists():
        with open(path, "rb") as fh:
            data = tomllib.load(fh)

    dock = data.get("dock", {})
    style = data.get("style", {})
    for section in (dock, style):
        for key, value in section.items():
            if key in ("pinned", "path") or not hasattr(cfg, key):
                continue
            default = getattr(cfg, key)
            if isinstance(default, bool):
                value = bool(value)
            elif isinstance(default, int):
                value = int(value)
            elif isinstance(default, float):
                value = float(value)
            setattr(cfg, key, value)

    if cfg.position not in POSITIONS:
        cfg.position = "bottom"
    cfg.magnification = max(1.0, min(cfg.magnification, 4.0))
    cfg.icon_size = max(16, min(cfg.icon_size, 256))
    cfg.spread = max(0.5, cfg.spread)

    apps = data.get("apps", {})
    if "pinned" in apps:
        cfg.pinned = _parse_pinned(apps["pinned"])
    else:
        cfg.pinned = [PinnedApp(desktop_id=d) for d in DEFAULT_PINNED]
        cfg.pinned_is_default = True  # type: ignore[attr-defined]
    return cfg
