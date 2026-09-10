"""Cykl życia pracownika: COMPASS → NEXUS (Etap 5).

COMPASS jest źródłem prawdy o zatrudnieniu — ``employment_status = 'exited'``
odbiera tam dostęp natychmiast, w trzech warstwach. NEXUS flipuje
``users.is_active`` RĘCZNIE (``/api/admin`` → soft-delete), więc konto osoby,
która odeszła, bywa aktywne jeszcze długo po ostatnim dniu pracy.

Skala jest dziś mała i to jest argument ZA zrobieniem tego teraz: 43 aktywnych,
2 ``offboarding``, 1 ``exited``, wszyscy na ``@b2bnetwork.pl``. Join po e-mailu
jest więc poprawny dla 100% rekordów — ale nie będzie: migracja domenowa jest
w toku (konta ``@inframinds.eu`` już istnieją, dziś nieaktywne). Dlatego sync
raportuje niedopasowanych w OBIE strony, tak jak D5.

CZTERY REGUŁY, KTÓRE TRZYMAJĄ TO BEZPIECZNYM
--------------------------------------------
1. **Tylko ``exited`` deaktywuje.** ``offboarding`` NIE — COMPASS sam
   przepuszcza ten status wszędzie, bo offboarding trwa po ostatnim dniu pracy
   i człowiek wciąż musi się zalogować. Traktowanie go jak odejścia odcięłoby
   ludzi w trakcie przekazywania obowiązków.

2. **Deaktywacja jest JEDNOKIERUNKOWA — nigdy nie włączamy konta z powrotem.**
   Odebranie dostępu na podstawie cudzego feedu jest odwracalne jednym
   kliknięciem admina; NADANIE dostępu automatem na podstawie feedu, który
   może być nieaktualny albo częściowy, jest zupełnie inną klasą zdarzenia.
   Powrót do pracy to decyzja człowieka.

3. **Nie ruszamy rankingów wypłacających nagrody.** Filtr ``is_active`` w
   ``competitions.py`` zostaje: wykluczanie osób, które odeszły, z NAGRÓD jest
   polityką, nie błędem. Historia firmy jest bezpieczna niezależnie —
   ``kpi_team`` od 2026-08-13 zachowuje nieaktywnych z dorobkiem w oknie, więc
   deaktywacja nie kurczy już sum firmowych.

4. **Konta bez odpowiednika w COMPASSIE zostają nietknięte.** Nieobecność
   w feedzie nie jest dowodem odejścia — może znaczyć „inna domena",
   „konto serwisowe człowieka" albo „COMPASS przysłał niepełną listę".
   Deaktywacja wymaga JAWNEGO ``exited``, nie ciszy.

5. **Deaktywujemy przy ZMIANIE statusu, nie przy każdym przebiegu.** Ostatnio
   widziany status każdego dopasowanego konta leży w ``app_settings``
   (``compass_lifecycle_state``). Konto, które COMPASS pokazywał jako
   ``exited`` już poprzednio, a które jest aktywne, admin włączył ŚWIADOMIE
   (np. osoba wróciła na umowę, której COMPASS jeszcze nie odnotował) — do
   09.2026 pętla wyłączała je z powrotem przy każdym starcie kontenera i co
   6 h. Przy pierwszym przebiegu po wdrożeniu (brak zapisanej obserwacji)
   szanujemy ślad admina: ostatnia zmiana ``active_changed`` na ``True``.
   Każda deaktywacja zostawia wpis ``Activity`` (``compass_lifecycle_deactivated``).
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

import httpx
from sqlalchemy import select

from app.core.config import settings
from app.models.activity import Activity
from app.models.app_setting import AppSetting
from app.models.user import User

logger = logging.getLogger(__name__)

_TIMEOUT_SECONDS = 20.0

# Jedyny status, który odbiera dostęp. Lista jest jawna i jednoelementowa
# CELOWO — „wszystko poza active" wciągnęłoby `offboarding`.
_DEACTIVATING_STATUSES = frozenset({"exited"})

# Ostatnio widziany status COMPASSA per konto NEXUSA (klucz: `users.id` jako
# tekst). Wiersz `app_settings`, bez migracji — to stan pętli, nie konfiguracja.
_STATE_KEY = "compass_lifecycle_state"
_STATE_VERSION = 1

# Akcja zapisywana przy każdej deaktywacji — i szukana jako ślad w audycie.
DEACTIVATION_ACTION = "compass_lifecycle_deactivated"


@dataclass
class LifecycleSyncResult:
    """Wynik przebiegu — z jawnym rachunkiem tego, czego NIE zrobiono."""

    people_received: int = 0
    matched_users: int = 0
    deactivated: list[str] = field(default_factory=list)
    already_inactive: int = 0
    # `exited` w COMPASSIE, a konto aktywne, bo admin włączył je ŚWIADOMIE —
    # raportowane z adresem, żeby ktoś mógł to zweryfikować, ale nie ruszane.
    skipped_reenabled: list[str] = field(default_factory=list)
    unmatched_compass_emails: list[str] = field(default_factory=list)
    nexus_users_without_compass: list[str] = field(default_factory=list)
    error: str | None = None

    def as_payload(self) -> dict:
        return {
            "people_received": self.people_received,
            "matched_users": self.matched_users,
            # Adresy, nie tylko liczba: bez nich nie da się naprawić
            # konkretnego przypadku ani sprawdzić, czy deaktywacja była trafna.
            "deactivated": sorted(self.deactivated),
            "already_inactive": self.already_inactive,
            "skipped_reenabled": sorted(self.skipped_reenabled),
            "unmatched_compass_emails": sorted(self.unmatched_compass_emails),
            "nexus_users_without_compass": sorted(self.nexus_users_without_compass),
            "error": self.error,
        }


async def _load_last_seen(db) -> dict[str, str]:
    """Ostatnio widziane statusy z poprzedniego przebiegu (pusty słownik = brak)."""
    row = await db.get(AppSetting, _STATE_KEY)
    value = row.value if row is not None and isinstance(row.value, dict) else {}
    seen = value.get("last_seen")
    if not isinstance(seen, dict):
        return {}
    return {str(k): str(v) for k, v in seen.items() if v is not None}


async def _save_last_seen(db, last_seen: dict[str, str]) -> None:
    payload = {
        "version": _STATE_VERSION,
        "last_seen": last_seen,
        "synced_at": datetime.now(timezone.utc).isoformat(),
    }
    row = await db.get(AppSetting, _STATE_KEY)
    if row is None:
        db.add(AppSetting(key=_STATE_KEY, value=payload))
    else:
        row.value = payload


async def _admin_reenabled(db, user_id: int) -> bool:
    """Czy OSTATNIA ręczna zmiana aktywności tego konta była włączeniem.

    Ślad zostawia `PATCH /api/admin/users/{id}` (`Activity.action =
    "active_changed"`, `details.to`). Używane tylko wtedy, gdy pętla nie ma
    jeszcze własnej obserwacji konta — czyli przy pierwszym przebiegu po
    wdrożeniu reguły „tylko przy zmianie", kiedy konto włączone przez admina
    po wcześniejszej deaktywacji inaczej zostałoby wyłączone jeszcze raz.
    """
    latest: Optional[Activity] = await db.scalar(
        select(Activity)
        .where(
            Activity.entity_type == "user",
            Activity.entity_id == user_id,
            Activity.action == "active_changed",
        )
        .order_by(Activity.created_at.desc(), Activity.id.desc())
        .limit(1)
    )
    details = latest.details if latest is not None else None
    return isinstance(details, dict) and details.get("to") is True


async def fetch_roster() -> dict:
    """Pobiera listę osób z COMPASSA.

    Sekret leci NAGŁÓWKIEM, nigdy w query stringu — te lądują w logach
    dostępowych pośredników, a ten sekret ma żyć długo (lustro decyzji z D5).
    """
    async with httpx.AsyncClient(timeout=_TIMEOUT_SECONDS) as client:
        response = await client.get(
            settings.COMPASS_LIFECYCLE_URL,
            headers={"Authorization": f"Bearer {settings.COMPASS_LIFECYCLE_SECRET}"},
        )
        response.raise_for_status()
        return response.json()


async def sync_user_lifecycle(db) -> LifecycleSyncResult:
    """Deaktywuje w NEXUSIE konta osób, które w COMPASSIE mają ``exited``."""
    result = LifecycleSyncResult()

    if not settings.COMPASS_LIFECYCLE_ENABLED:
        result.error = "disabled"
        return result
    if not (settings.COMPASS_LIFECYCLE_URL and settings.COMPASS_LIFECYCLE_SECRET):
        result.error = "unconfigured"
        return result

    try:
        payload = await fetch_roster()
    except Exception as exc:  # noqa: BLE001 — awaria COMPASSA nie jest nasza
        result.error = f"fetch_failed: {exc}"
        logger.warning("compass_lifecycle fetch failed: %s", exc)
        return result

    people = payload.get("people") or []
    result.people_received = len(people)

    # Pusta lista NIE jest sygnałem „wszyscy odeszli" — jest sygnałem, że coś
    # jest nie tak po drugiej stronie. Bez tego bezpiecznika awaria eksportu
    # w COMPASSIE deaktywowałaby dokładnie zero osób (bo nic nie ma statusu
    # `exited`), ale każdy żywy user trafiłby na listę „bez odpowiednika" —
    # a to jest wtedy szum, nie informacja.
    if not people:
        result.error = "empty_roster"
        return result

    by_email: dict[str, str] = {}
    for person in people:
        email = (person.get("email") or "").strip().lower()
        if email:
            by_email[email] = (person.get("employment_status") or "").strip().lower()

    users = (await db.execute(select(User))).scalars().all()
    nexus_emails = {(u.email or "").strip().lower() for u in users if u.email}

    for email in by_email:
        if email not in nexus_emails:
            result.unmatched_compass_emails.append(email)

    last_seen = await _load_last_seen(db)
    for user in users:
        email = (user.email or "").strip().lower()
        status = by_email.get(email)
        if status is None:
            # Tylko AKTYWNI są raportowani jako „bez odpowiednika" — konto
            # dawno wyłączone nie jest problemem do rozwiązania. Ostatnia
            # obserwacja zostaje: nieobecność w feedzie nie jest statusem.
            if user.is_active:
                result.nexus_users_without_compass.append(email or f"#{user.id}")
            continue

        result.matched_users += 1
        previous = last_seen.get(str(user.id))
        last_seen[str(user.id)] = status
        if status not in _DEACTIVATING_STATUSES:
            continue
        if not user.is_active:
            result.already_inactive += 1
            continue
        if previous in _DEACTIVATING_STATUSES:
            # COMPASS mówił `exited` już poprzednio, a konto jest aktywne —
            # admin włączył je świadomie po naszej deaktywacji. Bez tej
            # gałęzi pętla wyłączała je z powrotem co przebieg.
            result.skipped_reenabled.append(email)
            continue
        if previous is None and await _admin_reenabled(db, user.id):
            # Pierwsza obserwacja po wdrożeniu: stan sprzed reguły „tylko przy
            # zmianie" nie jest zapisany, więc decyduje ślad admina.
            result.skipped_reenabled.append(email)
            continue

        user.is_active = False
        db.add(
            Activity(
                entity_type="user",
                entity_id=user.id,
                action=DEACTIVATION_ACTION,
                user_id=None,
                details={
                    "target_email": email,
                    "compass_status": status,
                    "previous_compass_status": previous,
                    "source": "compass_lifecycle_sync",
                },
            )
        )
        result.deactivated.append(email)

    # Stan zapisujemy przy KAŻDYM udanym przebiegu — to on odróżnia „nowe
    # odejście" od „konto włączone ręcznie mimo `exited`".
    await _save_last_seen(db, last_seen)
    await db.commit()
    if result.deactivated:
        logger.info(
            "compass_lifecycle deactivated=%s emails=%s",
            len(result.deactivated),
            sorted(result.deactivated),
        )
    if result.skipped_reenabled:
        logger.info(
            "compass_lifecycle kept_reenabled=%s emails=%s",
            len(result.skipped_reenabled),
            sorted(result.skipped_reenabled),
        )

    return result


__all__ = [
    "DEACTIVATION_ACTION",
    "LifecycleSyncResult",
    "fetch_roster",
    "sync_user_lifecycle",
]
