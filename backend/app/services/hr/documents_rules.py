"""Słownik e-teczki: rodzaje dokumentów, domyślny krąg widzących, retencja.

* Rodzaje i etykiety — lustro we froncie (``frontend/src/lib/api/hr-documents.ts``,
  test ``tests/test_hr_documents_labels_mirror.py``).
* Domyślny krąg (Kadry i admin widzą zawsze): umowy, aneksy, oświadczenia
  i zaświadczenia — osoba i Płace; protokół — osoba i recepcja; potwierdzenie
  nieobecności (załącznik wniosku urlopowego, ``leave_proofs``) i inne —
  osoba. Kadry zmieniają go przy wgraniu.
* Retencja po odejściu: lata na rodzaj w ``app_settings['hr_document_retention']``,
  liczone od końca roku kalendarzowego, w którym osoba odeszła (ostatni dzień
  pracy). Wartość domyślna to 10 lat dla każdego rodzaju, także „inne”
  (okres dokumentacji pracowniczej i dokumentów płatnika składek; decyzja
  Artura 19.10.2026); Kadry zmieniają ją w Ustawieniach bez wdrożenia. Termin tylko wpisuje dokument na
  listę „do usunięcia po terminie” — usuwa człowiek.
"""

from __future__ import annotations

import logging
from datetime import date
from typing import Any

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.app_setting import AppSetting
from app.services.hr_documents_schema import DOCUMENT_KINDS, RETENTION_SETTING

logger = logging.getLogger(__name__)

KIND_LABELS: dict[str, str] = {
    "contract": "umowa",
    "annex": "aneks",
    "statement": "oświadczenie",
    "certificate": "zaświadczenie",
    "protocol": "protokół",
    "absence_proof": "potwierdzenie nieobecności",
    "other": "inne",
}
PURPOSE_LABELS: dict[str, str] = {
    "student_status": "status ucznia lub studenta",
}
#: Krąg poza Kadrami: (osoba, Płace, recepcja).
DEFAULT_AUDIENCE: dict[str, tuple[bool, bool, bool]] = {
    "contract": (True, True, False),
    "annex": (True, True, False),
    "statement": (True, True, False),
    "certificate": (True, True, False),
    "protocol": (True, False, True),
    "absence_proof": (True, False, False),
    "other": (True, False, False),
}
DEFAULT_RETENTION_YEARS: dict[str, int] = {
    "contract": 10,
    "annex": 10,
    "statement": 10,
    "certificate": 10,
    "protocol": 10,
    "absence_proof": 10,
    "other": 10,
}
RETENTION_MIN_YEARS = 10  # decyzja Artura 19.10.2026: e-teczka co najmniej 10 lat
RETENTION_MAX_YEARS = 50


class RetentionSettingsError(ValueError):
    pass


def parse_retention(raw: Any) -> dict[str, int]:
    """``{"contract": 10, …}`` → komplet rodzajów; brakujący rodzaj = domyślny."""

    if not isinstance(raw, dict):
        raise RetentionSettingsError(
            "Okresy przechowywania to lista: rodzaj i liczba lat."
        )
    unknown = sorted(set(raw) - set(DOCUMENT_KINDS))
    if unknown:
        raise RetentionSettingsError(
            f"Nieznany rodzaj dokumentu: {', '.join(unknown)}."
        )
    out = dict(DEFAULT_RETENTION_YEARS)
    for kind, value in raw.items():
        if isinstance(value, bool) or not isinstance(value, (int, str)):
            raise RetentionSettingsError(
                f"Okres dla „{KIND_LABELS[kind]}” podaje się w pełnych latach."
            )
        try:
            years = int(value)
        except ValueError:
            raise RetentionSettingsError(
                f"Okres dla „{KIND_LABELS[kind]}” podaje się w pełnych latach."
            ) from None
        if not RETENTION_MIN_YEARS <= years <= RETENTION_MAX_YEARS:
            raise RetentionSettingsError(
                f"Okres dla „{KIND_LABELS[kind]}”: od {RETENTION_MIN_YEARS} "
                f"do {RETENTION_MAX_YEARS} lat."
            )
        out[kind] = years
    return out


async def load_retention(db: AsyncSession) -> dict[str, int]:
    """Okresy z Ustawień; brak albo zepsuty wpis = wartości domyślne."""

    raw = await db.scalar(
        select(AppSetting.value).where(AppSetting.key == RETENTION_SETTING)
    )
    if raw is None:
        return dict(DEFAULT_RETENTION_YEARS)
    try:
        return parse_retention(raw)
    except RetentionSettingsError:
        logger.warning("[hr_documents] zepsute %s — okresy domyślne", RETENTION_SETTING)
        return dict(DEFAULT_RETENTION_YEARS)


async def save_retention(
    db: AsyncSession, raw: Any, *, actor_id: int
) -> dict[str, int]:
    """Waliduje i zapisuje okresy (bez commita)."""

    years = parse_retention(raw)
    statement = insert(AppSetting).values(
        key=RETENTION_SETTING, value=years, updated_by=actor_id
    )
    await db.execute(
        statement.on_conflict_do_update(
            index_elements=[AppSetting.key],
            set_={"value": statement.excluded.value, "updated_by": actor_id},
        )
    )
    return years


def delete_from(last_day: date, years: int) -> date:
    """Pierwszy dzień, od którego dokument można usunąć.

    Okres liczy się od końca roku kalendarzowego odejścia: odejście w marcu
    2026 i 10 lat = do 31.12.2036, usunąć można od 01.01.2037.
    """

    return date(last_day.year + years + 1, 1, 1)


def retention_payload(years: dict[str, int]) -> list[dict[str, Any]]:
    return [
        {
            "kind": kind,
            "label": KIND_LABELS[kind],
            "years": years[kind],
            "default_years": DEFAULT_RETENTION_YEARS[kind],
        }
        for kind in DOCUMENT_KINDS
    ]


__all__ = [
    "DEFAULT_AUDIENCE",
    "DEFAULT_RETENTION_YEARS",
    "KIND_LABELS",
    "PURPOSE_LABELS",
    "RetentionSettingsError",
    "delete_from",
    "load_retention",
    "parse_retention",
    "retention_payload",
    "save_retention",
]
