"""Główny wyłącznik programu „Ludzie w NEXUSIE” (``HR_PROGRAM_ENABLED``).

Artur 18.10.2026: dopóki integracje nie są dopracowane, a moduły nie mają
danych, programu nie widzi nikt — także admin. Wyłączony program:

* trasy modułów odpowiadają 404 (``require_hr_program`` przy każdym routerze
  programu w ``main.py``), poza dwiema sondami, o które pyta każdy ekran
  (``PROBE_PATHS``) — te odpowiadają stanem „zamknięte”,
* przełączniki modułów i podgląd admina są zamknięte (``hr.modules``,
  ``client_invoicing.settings``, ``hr.agreements``),
* pętle w tle nie startują (``tasks.hr_loops.loops_enabled``),
* dostępność z urlopów NEXUSA się nie włącza (``hr.availability_local``),
* kategoria powiadomień i mail „Czas i ludzie” znikają z ustawień.

Front czyta stan z ``GET /api/hr/config`` (pole ``program``).
"""

from __future__ import annotations

from fastapi import HTTPException, Request, status

from app.core.config import settings

#: Sondy wołane z ekranów spoza programu (pasek, profil klienta). Przy
#: wyłączonym programie odpowiadają „wszystko zamknięte” zamiast 404, żeby
#: każdy ekran nie zostawiał w konsoli błędu.
PROBE_PATHS: frozenset[str] = frozenset(
    {"/api/hr/config", "/api/clients/sales-invoices/module"}
)


#: Ślady programu w ustawieniach powiadomień, ukrywane przy wyłączonym:
#: kategoria „Czas i ludzie” i mail o tej samej nazwie.
NOTIFICATION_CATEGORY = "people"
MAIL_KIND = "hr_people"


def program_enabled() -> bool:
    return bool(settings.HR_PROGRAM_ENABLED)


#: Zakresy kluczy API programu (API v1 i roster dla Compassa) — przy
#: wyłączonym programie nie ma ich w pickerze kluczy w Ustawieniach.
API_SCOPES: frozenset[str] = frozenset(
    {"people_roster:read", "absences:read", "equipment:read"}
)


def hides_category(category: str) -> bool:
    return not program_enabled() and category == NOTIFICATION_CATEGORY


def hides_scope(scope: str) -> bool:
    return not program_enabled() and scope in API_SCOPES


async def require_hr_program(request: Request) -> None:
    """Zależność routerów programu: wyłączony program = 404 dla każdego."""

    if program_enabled() or request.url.path in PROBE_PATHS:
        return
    # Ta sama odpowiedź co nieistniejąca trasa — bez śladu, że moduł jest.
    raise HTTPException(status.HTTP_404_NOT_FOUND, "Not Found")
