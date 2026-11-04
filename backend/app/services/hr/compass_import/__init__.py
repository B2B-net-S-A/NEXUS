"""Import danych z Compassa do modułów „Ludzi w NEXUSIE”.

Przebieg każdego modułu: paczka (``bundle.parse_bundle``) → na sucho
(``core.dry_run``: partia + raport z liczbami) → zapis (``core.apply``: ta sama
paczka, plan przeliczony na świeżych danych, mapa id). Importery modułów
rejestrują się w ``IMPORTERS`` w kolejności zależności (kartoteki pierwsze).
"""

from __future__ import annotations

from dataclasses import dataclass

from . import care, cases, leave, lifecycle, payroll, profiles, time
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
    leave.MODULE: Importer(
        leave.MODULE, "Wnioski urlopowe i dni nieobecności", leave.plan, leave.apply
    ),
    time.MODULE: Importer(
        time.MODULE, "Timesheety, obecność i opisy", time.plan, time.apply
    ),
    payroll.MODULE: Importer(
        payroll.MODULE, "Stawki i premie", payroll.plan, payroll.apply
    ),
    lifecycle.MODULE: Importer(
        lifecycle.MODULE, "Sprawy wejścia i odejścia", lifecycle.plan, lifecycle.apply
    ),
    cases.MODULE: Importer(
        cases.MODULE, "Sprawy skrzynki administracja@", cases.plan, cases.apply
    ),
    care.MODULE: Importer(
        care.MODULE, "Mapa technologiczna i rozmowy opiekunów", care.plan, care.apply
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
