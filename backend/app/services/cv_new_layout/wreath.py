"""Wieniec laurowy wyróżnika pod nazwiskiem (W8: liście na przemian czerwone
i ciemnoczerwone, w środku krótki znak). Od 25.11.2026 tylko tu — Edukacja bez wieńca."""

from __future__ import annotations

import math

from app.services.cv_new_layout.styles import BRAND, BRAND_DEEP, INK
from app.services.cv_new_layout.text import esc

BOX = 32.0
CX, CY, RADIUS = 16.0, 15.2, 9.6


def _branch(side: int, n: int = 30, step: float = 4.4, start: float = 95) -> str:
    def ang(k: int) -> float:
        return (
            math.radians(start + k * step)
            if side < 0
            else math.radians(180 - start - k * step)
        )

    stem = [
        (CX + RADIUS * math.cos(ang(k)), CY + RADIUS * math.sin(ang(k)))
        for k in range(n + 1)
    ]
    parts = [
        '<path d="M'
        + " L".join(f"{x:.2f},{y:.2f}" for x, y in stem)
        + f'" fill="none" stroke="{BRAND}" stroke-width=".26"/>'
    ]
    colors = (BRAND, BRAND_DEEP)
    for k in range(2, n + 1, 2):
        a = ang(k)
        x, y = CX + RADIUS * math.cos(a), CY + RADIUS * math.sin(a)
        tang = math.degrees(a) + (90 if side < 0 else -90)
        size = 1.0 + 0.5 * (1 - abs(k - n / 2) / (n / 2))
        for j, io in enumerate((-1, 1)):
            an = tang + io * 38 * (1 if side < 0 else -1)
            ox = math.cos(math.radians(an)) * size * 1.3
            oy = math.sin(math.radians(an)) * size * 1.3
            col = colors[(k // 2 + j) % 2]
            parts.append(
                f'<ellipse cx="{x + ox:.2f}" cy="{y + oy:.2f}" rx="{size * 1.45:.2f}" ry="{size * 0.52:.2f}" '
                f'transform="rotate({an:.1f} {x + ox:.2f} {y + oy:.2f})" fill="{col}" '
                f'opacity="{0.95 if io > 0 else 0.78}"/>'
            )
    return "".join(parts)


def wreath_badge_svg(token: str, size_mm: float = 22.0) -> str:
    """Wieniec wyróżnika (Artur 25.11.2026): w środku krótki znak („PKO BP”, „2015”),
    bez znaku — sam wieniec."""
    center = ""
    if token:
        size = 4.4 if len(token) <= 4 else 3.1 if len(token) <= 6 else 2.6
        center = (
            f'<text x="{CX}" y="{CY + 1.5}" text-anchor="middle" font-family="Poppins" font-weight="700" '
            f'font-size="{size}" fill="{INK}">{esc(token)}</text>'
        )
    return (
        f'<svg class="hlw" viewBox="0 0 {BOX} {BOX}" width="{size_mm}mm" height="{size_mm}mm" '
        f'xmlns="http://www.w3.org/2000/svg">{_branch(-1)}{_branch(1)}{center}</svg>'
    )
