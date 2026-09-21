"""Kształt układu własnego pulpitu (0336) — jedno źródło prawdy po stronie API.

Lista ``TILE_TYPES`` MUSI zgadzać się z rejestrem kafelków na froncie
(``frontend/src/lib/api/userDashboard.ts`` i katalog
``frontend/src/lib/dashboard-tiles/catalog.ts``) — pilnuje tego
``tests/test_dashboard_tile_types_mirror.py``. Nowy kafelek = wpis tu
i w rejestrze.

Walidacja jest świadomie ścisła przy ZAPISIE (422 z polskim zdaniem) i łagodna
przy ODCZYCIE: kafelek typu, którego już nie ma (usunięty z katalogu), jest
pomijany i zgłaszany w ``dropped_tiles`` — pulpit się otwiera, zamiast
wywrócić cały ekran startowy z powodu jednego starego kafelka.
"""

from __future__ import annotations

import json
from typing import Any, Literal, Optional, get_args
from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationError,
    field_validator,
    model_validator,
)

from app.services.custom_metrics.definition import MetricDefinition

GRID_COLUMNS = 12
MAX_TILES = 40
MAX_CONFIG_BYTES = 16_000
MAX_TILE_HEIGHT = 12

METRIC_TILE_TYPES = frozenset({"metric_number", "metric_chart", "metric_funnel"})

TileType = Literal[
    "my_tasks",
    "my_next_steps",
    "my_contact_queue",
    "my_priority_queue",
    "my_people",
    "my_kpis_today",
    "my_onboarding",
    "my_recruitments",
    "recruitment_activity",
    "recruitment_competence",
    "team_workload",
    "team_allocation",
    "contact_oversight",
    "my_clients_alerts",
    "dl_alerts",
    "calendar_today",
    "metric_number",
    "metric_chart",
    "metric_funnel",
    "note",
]


# Jedna lista: Literal waliduje zapis, krotka służy testowi lustra frontu.
TILE_TYPES: tuple[str, ...] = get_args(TileType)


class NoteLink(BaseModel):
    model_config = ConfigDict(extra="forbid")

    label: str = Field(min_length=1, max_length=80)
    url: str = Field(min_length=1, max_length=500)

    @field_validator("url")
    @classmethod
    def _safe_url(cls, value: str) -> str:
        # Link w notatce renderuje się jako <a href>. `javascript:` i podobne
        # schematy byłyby XSS-em zapisanym na koncie — dopuszczamy wyłącznie
        # adresy https i ścieżki wewnątrz aplikacji.
        if value.startswith("https://") or (
            value.startswith("/") and not value.startswith("//")
        ):
            return value
        raise ValueError("Link musi zaczynać się od https:// albo / (strona NEXUS).")


class TileConfig(BaseModel):
    """Wspólne pola + pola konkretnych typów. Nieznany klucz = 422."""

    model_config = ConfigDict(extra="forbid")

    title: Optional[str] = Field(default=None, max_length=80)
    metric: Optional[MetricDefinition] = None
    chart: Optional[Literal["bars", "line", "table"]] = None
    text: Optional[str] = Field(default=None, max_length=2000)
    links: list[NoteLink] = Field(default_factory=list, max_length=10)
    link_to: Optional[str] = Field(default=None, max_length=300)

    @field_validator("link_to")
    @classmethod
    def _internal_link(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return value
        if value.startswith("/") and not value.startswith("//"):
            return value
        raise ValueError("Kliknięcie w kafelek może prowadzić tylko do strony NEXUS.")


class DashboardTile(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: UUID
    type: TileType
    x: int = Field(ge=0, lt=GRID_COLUMNS)
    y: int = Field(ge=0, le=1000)
    w: int = Field(ge=1, le=GRID_COLUMNS)
    h: int = Field(ge=1, le=MAX_TILE_HEIGHT)
    config: TileConfig = Field(default_factory=TileConfig)

    @model_validator(mode="after")
    def _fits_and_matches(self) -> "DashboardTile":
        if self.x + self.w > GRID_COLUMNS:
            raise ValueError("Kafelek wychodzi poza siatkę 12 kolumn.")
        if self.type in METRIC_TILE_TYPES and self.config.metric is None:
            raise ValueError("Kafelek metryki wymaga definicji metryki.")
        if self.type not in METRIC_TILE_TYPES and self.config.metric is not None:
            raise ValueError("Tylko kafelek metryki może nieść definicję metryki.")
        if self.type == "metric_funnel" and self.config.metric is not None:
            m = self.config.metric
            if m.source != "pipeline_moves" or m.group_by != "stage":
                raise ValueError("Lejek liczy ruchy w pipeline z podziałem po etapach.")
        if (
            len(self.config.model_dump_json(exclude_none=True).encode())
            > MAX_CONFIG_BYTES
        ):
            raise ValueError("Ustawienia kafelka są za duże.")
        return self


class DashboardLayout(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tiles: list[DashboardTile] = Field(default_factory=list, max_length=MAX_TILES)

    @model_validator(mode="after")
    def _unique_ids(self) -> "DashboardLayout":
        ids = [t.id for t in self.tiles]
        if len(ids) != len(set(ids)):
            raise ValueError("Dwa kafelki mają ten sam identyfikator.")
        return self

    def to_storage(self) -> dict[str, Any]:
        return json.loads(self.model_dump_json(exclude_none=True))


def load_layout(raw: Any) -> tuple[DashboardLayout, list[dict[str, Any]]]:
    """Odczyt łagodny: zły kafelek odpada i trafia do listy pominiętych."""
    tiles_raw = raw.get("tiles") if isinstance(raw, dict) else None
    good: list[DashboardTile] = []
    dropped: list[dict[str, Any]] = []
    seen: set[UUID] = set()
    for item in tiles_raw if isinstance(tiles_raw, list) else []:
        try:
            tile = DashboardTile.model_validate(item)
        except ValidationError:
            dropped.append(
                {
                    "id": str(item.get("id")) if isinstance(item, dict) else None,
                    "type": item.get("type") if isinstance(item, dict) else None,
                }
            )
            continue
        if tile.id in seen:
            continue
        seen.add(tile.id)
        good.append(tile)
    return DashboardLayout(tiles=good[:MAX_TILES]), dropped
