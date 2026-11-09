"""Pure magnification math (no GTK), so it can be unit tested.

Model: icons sit on a line ("main axis"). Each icon has a resting size
``icon_size``. When the cursor is at main-axis position ``cursor``, every icon
whose *resting* centre is within ``spread`` icon-widths of the cursor grows
following a raised-cosine curve, peaking at ``magnification`` right under the
cursor. Distances are measured against the resting layout so the effect never
feeds back on itself (no jitter).

The grown row is then anchored so the point under the cursor stays put, the
same way the macOS Dock behaves: extra length is split between the left and
right of the row in proportion to where the cursor sits.
"""

from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass(frozen=True)
class Params:
    icon_size: float = 48.0
    magnification: float = 2.0
    spread: float = 3.0  # in icon widths, each side of the cursor
    spacing: float = 8.0


def scale_for_distance(distance: float, p: Params) -> float:
    """Scale factor (>= 1) for an icon whose centre is ``distance`` px away."""
    radius = p.spread * (p.icon_size + p.spacing)
    if radius <= 0 or p.magnification <= 1.0:
        return 1.0
    d = abs(distance)
    if d >= radius:
        return 1.0
    curve = (math.cos(math.pi * d / radius) + 1.0) / 2.0  # 1 at centre, 0 at edge
    return 1.0 + (p.magnification - 1.0) * curve


def rest_length(n: int, p: Params) -> float:
    if n <= 0:
        return 0.0
    return n * p.icon_size + (n - 1) * p.spacing


def rest_centers(n: int, p: Params, rest_start: float) -> list[float]:
    step = p.icon_size + p.spacing
    return [rest_start + i * step + p.icon_size / 2 for i in range(n)]


def target_scales(n: int, p: Params, rest_start: float, cursor: float | None) -> list[float]:
    if cursor is None:
        return [1.0] * n
    return [scale_for_distance(c - cursor, p) for c in rest_centers(n, p, rest_start)]


def anchor_fraction(n: int, p: Params, rest_start: float, cursor: float) -> float:
    total = rest_length(n, p)
    if total <= 0:
        return 0.5
    return min(1.0, max(0.0, (cursor - rest_start) / total))


def layout(scales: list[float], p: Params, rest_start: float, frac: float) -> list[tuple[float, float]]:
    """Return ``(start, size)`` along the main axis for every icon."""
    n = len(scales)
    sizes = [p.icon_size * s for s in scales]
    total = sum(sizes) + max(0, n - 1) * p.spacing
    extra = total - rest_length(n, p)
    pos = rest_start - extra * frac
    out = []
    for size in sizes:
        out.append((pos, size))
        pos += size + p.spacing
    return out


def max_overflow(n: int, p: Params) -> float:
    """Largest distance the grown row can stick out past either end of the
    resting row, over every cursor position inside the row."""
    if n <= 0:
        return 0.0
    total = rest_length(n, p)
    best = 0.0
    steps = max(64, n * 16)
    for i in range(steps + 1):
        cursor = total * i / steps
        scales = target_scales(n, p, 0.0, cursor)
        extra = sum(p.icon_size * (s - 1.0) for s in scales)
        frac = anchor_fraction(n, p, 0.0, cursor)
        best = max(best, extra * frac, extra * (1.0 - frac))
    return best
