"""Typy kafelków własnego pulpitu: backend i front mówią tym samym słownikiem.

Serwer odrzuca nieznany typ przy zapisie (422), a przy odczycie go pomija.
Typ dodany tylko na froncie dałby więc kafelek, którego nie da się zapisać;
typ dodany tylko tu — kafelek zapisany, którego front nie umie narysować.
"""

from __future__ import annotations

import re
from pathlib import Path

from app.services.dashboard_tiles import TILE_TYPES

REPO = Path(__file__).resolve().parents[2]
FRONT_TYPES = REPO / "frontend" / "src" / "lib" / "api" / "userDashboard.ts"
FRONT_CATALOG = REPO / "frontend" / "src" / "lib" / "dashboard-tiles" / "catalog.ts"


def _front_tile_types() -> list[str]:
    src = FRONT_TYPES.read_text()
    block = src[src.index("export const TILE_TYPES = [") :]
    block = block[: block.index("] as const")]
    return re.findall(r'"([a-z_]+)"', block)


def test_front_and_back_declare_the_same_tile_types():
    assert sorted(_front_tile_types()) == sorted(TILE_TYPES)


def test_every_tile_type_has_a_catalog_definition():
    catalog = FRONT_CATALOG.read_text()
    for tile_type in TILE_TYPES:
        assert re.search(rf"\n  {tile_type}: {{\n    type: \"{tile_type}\"", catalog), (
            tile_type
        )
