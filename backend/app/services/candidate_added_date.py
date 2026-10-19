"""„W bazie od” — kiedy osoba trafiła do naszej bazy (13.10.2026).

Prośba rekrutera: przy osobie ma być widać, od kiedy jest w bazie, bo świeże
zgłoszenia są najlepsze. `candidates.created_at` to czas wstawienia wiersza do
NEXUSA — dla osób z Traffita dzień importu (16.04 i 04.05.2026 dla 43 tys.
osób), więc sam w sobie kłamie. Datę dodania u źródła trzyma
`source_created_at` (Traffit `created_at`, migracja 0437, naprawa
`traffit_added_dates_repair`).

Reguła, jedna dla API, Tablicy, listy i praktykanta:

- „w bazie od” = wcześniejsza z dwóch dat (`LEAST` pomija NULL). Osoba
  założona w NEXUSIE i później dopasowana do kartoteki z Traffita dostaje
  wcześniejszą z nich.
- Data jest NIEDOKŁADNA, gdy nie znamy daty u źródła, a wiersz pochodzi
  z importu (Traffit, stary import) albo powstał najpóźniej w dniu pierwszego
  importu. Wtedy wiemy tylko „przed tym dniem” — ekran mówi „przed DD.MM.RRRR”
  i nie pokazuje pigułki „Nowy w bazie”.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, Optional
from zoneinfo import ZoneInfo

from sqlalchemy import func

from app.core.scheduling import DEFAULT_TZ

# Dzień pierwszego importu z Traffita (Europe/Warsaw). Wiersze założone do
# tego dnia bez daty u źródła pochodzą z importów startowych.
FIRST_IMPORT_DAY = date(2026, 4, 16)

IMPORTED_EXTERNAL_SOURCES = frozenset({"traffit", "tr_legacy"})

_ZONE = ZoneInfo(DEFAULT_TZ)


@dataclass(frozen=True)
class AddedToBase:
    at: Optional[datetime]
    exact: bool


def added_to_base(
    created_at: Optional[datetime],
    source_created_at: Optional[datetime],
    external_source: Optional[str],
) -> AddedToBase:
    """Data wejścia osoby do bazy i to, czy jest dokładna."""
    if source_created_at is not None:
        at = (
            source_created_at
            if created_at is None
            else min(created_at, source_created_at)
        )
        return AddedToBase(at=at, exact=True)
    if created_at is None:
        return AddedToBase(at=None, exact=False)
    imported = (external_source or "") in IMPORTED_EXTERNAL_SOURCES
    started_with_import = created_at.astimezone(_ZONE).date() <= FIRST_IMPORT_DAY
    return AddedToBase(at=created_at, exact=not (imported or started_with_import))


def added_to_base_of(candidate: Any) -> AddedToBase:
    """To samo dla wiersza `Candidate` (albo obiektu z tymi trzema polami)."""
    return added_to_base(
        getattr(candidate, "created_at", None),
        getattr(candidate, "source_created_at", None),
        getattr(candidate, "external_source", None),
    )


def added_via_label(
    tags: Any, source: Optional[str], external_source: Optional[str]
) -> Optional[str]:
    """„Skąd” osoba trafiła do bazy: źródło z Traffita albo sposób dodania w NEXUSIE."""
    from app.services.candidate_quick_view import _label_source

    for tag in tags if isinstance(tags, list) else []:
        if isinstance(tag, dict) and tag.get("type") == "traffit_source":
            label = _label_source(tag.get("value")) or _label_source(tag.get("domain"))
            if label:
                return f"Traffit · {label}"
    # Wtyczka = rekruter sam dodał osobę z LinkedIna. Etykieta „LinkedIn”
    # (wspólna z kanałem, z którego osoba przyszła) myliła się z linkiem
    # rekrutera wrzuconym na LinkedIna.
    if (source or "").strip().casefold() == "linkedin_extension":
        return "Wtyczka LinkedIn"
    label = _label_source(source)
    if label == _label_source("traffit") or (
        label is None and (external_source or "") in IMPORTED_EXTERNAL_SOURCES
    ):
        return "Traffit"
    return label


def added_to_base_sql(candidate_cls: Any) -> Any:
    """Wyrażenie SQL do sortowania — to samo co indeks `ix_candidates_added_to_base_id`."""
    return func.least(candidate_cls.created_at, candidate_cls.source_created_at)
