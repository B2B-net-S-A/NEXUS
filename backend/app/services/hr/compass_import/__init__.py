"""Import danych z Compassa do modułów „Ludzi w NEXUSIE”.

Przebieg każdego modułu: paczka (``bundle.parse_bundle``) → na sucho
(``core.dry_run``: partia + raport z liczbami) → zapis (``core.apply``: ta sama
paczka, plan przeliczony na świeżych danych, mapa id). Importery modułów
rejestrują się w ``IMPORTERS`` w kolejności zależności (kartoteki pierwsze).
"""

from __future__ import annotations

from dataclasses import dataclass

from . import profiles
from .bundle import Bundle, BundleError, parse_bundle
from .core import Applier, ImportFlowError, ModulePlan, Planner, apply, dry_run


@dataclass(frozen=True)
class Importer:
    module: str
    label: str
    plan: Planner
    apply: Applier


IMPORTERS: dict[str, Importer] = {
    profiles.MODULE: Importer(
        profiles.MODULE, "Kartoteki i pule urlopowe", profiles.plan, profiles.apply
    ),
}

__all__ = [
    "IMPORTERS",
    "Bundle",
    "BundleError",
    "ImportFlowError",
    "Importer",
    "ModulePlan",
    "apply",
    "dry_run",
    "parse_bundle",
]
