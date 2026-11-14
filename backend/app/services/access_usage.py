"""Licznik użycia obszarów: osoba × obszar × dzień, do przeglądu dostępów.

Program najmniejszych dostępów (Artur 02.11.2026). Zasady i sposób odczytu:
``docs/claude/uprawnienia/licznik-uzycia-obszarow.md``.

Zapis jest poza ścieżką żądania: middleware dolicza jedynkę w słowniku procesu,
bez ``await`` i bez bazy, a pętla ``access_usage`` co minutę składa to w jeden
UPSERT. Awaria bazy nie dotyka więc odpowiedzi, a liczby czekają w pamięci do
następnej próby. Restart gubi najwyżej ostatnią minutę, co dla pytania
„czy ta osoba wchodzi tu w ogóle” nie ma znaczenia.

Z żądania bierzemy tylko nazwę obszaru z zamkniętej listy, więc identyfikatory
rekordów i parametry zapytań nie mają którędy trafić do tabeli.
"""

from __future__ import annotations

import logging
import time
from collections import Counter
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.core.scheduling import business_today
from app.models.user import User, UserRole
from app.services.action_permissions import (
    ActionAccess,
    ProductAction,
    action_access_for_user,
    has_permission,
)
from app.services.section_permissions import (
    ProductSection,
    SectionAccess,
    section_access_for_user,
)

logger = logging.getLogger(__name__)

KANDYDACI = "kandydaci"
TABLICA = "tablica"
KONTRAKTY = "kontrakty"
FINANSE = "finanse"
INSIGHTS = "insights"
HR = "hr"
SPRZEDAZ = "sprzedaz"
GENERATOR_B2B = "generator_b2b"
EKSPORTY = "eksporty"
ADMINISTRACJA = "administracja"

AREA_LABELS: dict[str, str] = {
    KANDYDACI: "Kandydaci i wyszukiwanie",
    TABLICA: "Rekrutacje i Tablica",
    KONTRAKTY: "Klienci, kontrakty i zamówienia",
    FINANSE: "Finanse",
    INSIGHTS: "Insights i raporty",
    HR: "Kadry, sprzęt i sprawy",
    SPRZEDAZ: "Sprzedaż",
    GENERATOR_B2B: "Generator umów B2B",
    EKSPORTY: "Eksporty",
    ADMINISTRACJA: "Administracja",
}


def _screens(area: str, *screens: str) -> dict[str, str]:
    return dict.fromkeys(screens, area)


#: Ekran (pierwszy człon adresu w przeglądarce) → obszar.
#:
#: Po ekranie, nie po trasie API, bo pomiar na stagingu 02.11.2026 pokazał, że
#: samo wejście na pulpit odpytuje `/api/jobs`, `/api/kpis`, `/api/order-mail`,
#: `/api/finance/...` i `/api/b2b-generator/...`. Licznik po trasach zapisałby
#: każdemu „używa”, a listy „ma dostęp, 0 wejść” by nie było.
AREA_BY_SCREEN: dict[str, str] = {
    **_screens(
        KANDYDACI,
        "applications",
        "candidates",
        "cv-generator",
        "marketplace",
        "seeking",
        "sourcing",
        "talent-radar",
        "talents",
    ),
    # „porcja” — porcja dnia od Nexusa (07.11.2026), karty z Tablicy.
    **_screens(TABLICA, "calendar", "departed-care", "jobs", "manager", "porcja"),
    **_screens(
        KONTRAKTY,
        "back-office",
        "care",
        "clients",
        "contractors",
        "contracts",
        "my-clients",
        "my-relationships",
        "order-mail",
    ),
    # „accounting” — Księgowość (księga NEXUSA, K1, 14.11.2026), bramka sekcji Finanse.
    **_screens(FINANSE, "accounting", "finance"),
    # Podgląd na telefonie stoi za tą samą bramką sekcji co Insights.
    **_screens(INSIGHTS, "insights", "podglad"),
    # „trainings” — szkolenia i biblioteka nagrań (13.11.2026), moduł grupy „Ludzie”.
    **_screens(HR, "equipment", "people", "trainings"),
    **_screens(SPRZEDAZ, "sales"),
    **_screens(GENERATOR_B2B, "contracts/b2b-generator"),
}

#: Ekrany, których nie liczymy: wspólne dla każdego zalogowanego albo poza
#: aplikacją firmy. Nowy ekran trafia tu albo do mapy wyżej — pilnuje
#: ``test_access_usage.py``. ``settings`` sam jest profilem ustawień osoby,
#: a podstrony ``settings/*`` liczą się jako Administracja.
UNTRACKED_SCREENS: frozenset[str] = frozenset(
    {
        # Pulpit odpytuje kilka obszarów sam, więc nic o nich nie mówi.
        "dashboard",
        # Konto osoby, własny czas pracy, pomoc i start.
        "help",
        "my-time",
        "onboarding",
        "profile",
        "settings",
        "start",
        # Umowy klientów: nadawane imiennie, poza sekcjami, które mierzy przegląd.
        "client-contracts",
        # Rekrutacja własna: proces dwóch osób, poza sekcjami, które mierzy przegląd.
        "rekrutacja-wlasna",
        # Logowanie, publiczne strony i dokumenty otwierane z linku.
        "t",
        "apply",
        "auth",
        "cv",
        "engagement",
        "k",
        "kariera",
        "konsultant",
        "login",
        "microsoft365",
        "protocol",
        "register",
        "share",
        "sign",
        "wypis",
        # Wtyczka i harnessy.
        "extension",
        "preview",
        "wtyczka",
        # Programy usunięte 08.11.2026 (`docs/claude/programy/`).
        "academy",
        "trainee",
        "trainees",
    }
)

#: Jedno wejście na obszar najwyżej raz na tyle sekund. Ekran robi po kilka
#: żądań na raz i odpytuje w tle, więc bez tego liczba mówiłaby o ekranie, nie
#: o osobie. Eksporty liczymy co do sztuki: każdy to osobne kliknięcie.
ENTRY_GAP_SECONDS = 1800

#: Skąd się bierze dostęp do obszaru Kadry.
_HR_PERMISSIONS = (
    ProductAction.people_admin,
    ProductAction.payroll,
    ProductAction.equipment,
    ProductAction.cases,
    ProductAction.timesheets,
)

_pending: Counter[tuple[int, str, date]] = Counter()
_last_entry: dict[tuple[int, str], tuple[date, float]] = {}


def _is_export_path(path: str) -> bool:
    """Plik z danymi firmy. Własne dane osoby (``/me/``) się nie liczą."""

    parts = path.split("/")
    if len(parts) < 3 or parts[1] != "api" or "me" in parts:
        return False
    return any(part == "export" or part.startswith("export.") for part in parts[2:])


def area_for_request(screen: str | None, path: str) -> str | None:
    """Obszar żądania albo ``None``, gdy go nie liczymy.

    ``screen`` przychodzi z nagłówka, więc liczy się tylko jako klucz zamkniętej
    mapy: nieznana wartość nie ma którędy trafić do tabeli.
    """

    if _is_export_path(path):
        return EKSPORTY
    if not screen:
        return None
    if screen.startswith("settings/"):
        return ADMINISTRACJA
    return AREA_BY_SCREEN.get(screen) or AREA_BY_SCREEN.get(screen.split("/", 1)[0])


def record_entry(user_id: int, area: str) -> None:
    """Dolicz wejście. Bez I/O, więc nie opóźnia odpowiedzi."""

    today = business_today()
    if area != EKSPORTY:
        now = time.monotonic()
        last = _last_entry.get((user_id, area))
        if last and last[0] == today and now - last[1] < ENTRY_GAP_SECONDS:
            return
        _last_entry[(user_id, area)] = (today, now)
    _pending[(user_id, area, today)] += 1


def _take_pending() -> Counter[tuple[int, str, date]]:
    batch = Counter(_pending)
    _pending.clear()
    return batch


_UPSERT = text(
    """
    INSERT INTO access_usage_daily (user_id, area, day, entries)
    SELECT u.id, CAST(:area AS varchar), CAST(:day AS date), CAST(:entries AS integer)
      FROM users AS u
     WHERE u.id = :user_id
    ON CONFLICT (user_id, area, day) DO UPDATE
       SET entries = access_usage_daily.entries + EXCLUDED.entries
    """
)
_PRUNE = text("DELETE FROM access_usage_daily WHERE day < :cutoff")


async def flush_pending() -> int:
    """Zapisz zebrane liczby. Po błędzie wracają do pamięci na następną próbę.

    ``SELECT`` z ``users`` zamiast ``VALUES``: konto skasowane w ciągu minuty
    odpada samo, zamiast wywracać kluczem obcym całą paczkę przy każdej próbie.
    Kolejność po kluczu, żeby dwa procesy nie zakleszczyły się na tych samych
    wierszach.
    """

    batch = _take_pending()
    if not batch:
        return 0
    params = [
        {"user_id": user_id, "area": area, "day": day, "entries": entries}
        for (user_id, area, day), entries in sorted(batch.items())
    ]
    try:
        async with AsyncSessionLocal() as db:
            await db.execute(_UPSERT, params)
            await db.commit()
    except BaseException:
        _pending.update(batch)
        raise
    return len(params)


async def prune_expired(today: date | None = None) -> int:
    """Skasuj wiersze starsze niż ``ACCESS_USAGE_RETENTION_DAYS``."""

    cutoff = (today or business_today()) - timedelta(
        days=settings.ACCESS_USAGE_RETENTION_DAYS
    )
    async with AsyncSessionLocal() as db:
        result = await db.execute(_PRUNE, {"cutoff": cutoff})
        await db.commit()
    return int(result.rowcount or 0)


def _section_reader(section: ProductSection) -> Callable[[User], bool]:
    def reader(user: User) -> bool:
        return section_access_for_user(user, section) >= SectionAccess.read

    return reader


def _has_hr_permission(user: User) -> bool:
    return any(has_permission(user, permission) for permission in _HR_PERMISSIONS)


def _has_b2b_generator(user: User) -> bool:
    return (
        action_access_for_user(user, ProductAction.b2b_contract_generator)
        >= ActionAccess.view
    )


#: Skąd osoba ma dostęp do obszaru. Eksportów tu nie ma: każdy ma własną bramkę
#: na trasie, więc jednej odpowiedzi „ma dostęp” nie da się uczciwie podać.
_AREA_ACCESS: dict[str, Callable[[User], bool]] = {
    KANDYDACI: _section_reader(ProductSection.sourcing),
    TABLICA: _section_reader(ProductSection.pipeline),
    KONTRAKTY: _section_reader(ProductSection.delivery),
    FINANSE: _section_reader(ProductSection.finance),
    INSIGHTS: _section_reader(ProductSection.insights),
    HR: _has_hr_permission,
    SPRZEDAZ: lambda user: has_permission(user, ProductAction.sales_view),
    GENERATOR_B2B: _has_b2b_generator,
}


def area_access(user: User, area: str) -> bool | None:
    """Czy osoba ma dostęp; ``None``, gdy obszar nie ma jednej bramki."""

    if area == ADMINISTRACJA:
        # Podstrony ustawień mają różne bramki (HoR ma strukturę zespołu),
        # jednoznaczny jest tylko admin.
        return True if user.has_role(UserRole.admin) else None
    resolve = _AREA_ACCESS.get(area)
    return None if resolve is None else resolve(user)


@dataclass(frozen=True)
class AreaUsage:
    entries: int
    active_days: int
    last_day: date | None


@dataclass(frozen=True)
class ReviewRow:
    user_id: int
    full_name: str
    email: str
    roles: tuple[str, ...]
    area: str
    has_access: bool | None
    entries: int
    active_days: int
    last_day: date | None

    @property
    def unused(self) -> bool:
        """Ma dostęp, 0 wejść: kandydat do rozmowy, nie do odebrania z automatu."""

        return self.has_access is True and self.entries == 0


@dataclass(frozen=True)
class Review:
    since: date
    until: date
    collected_days: int
    rows: tuple[ReviewRow, ...]


def build_review_rows(
    users: Iterable[Any], usage: Mapping[tuple[int, str], AreaUsage]
) -> tuple[ReviewRow, ...]:
    """Dla każdej osoby obszary z dostępem albo z wejściami, osoba po osobie.

    Wejścia bez dostępu zostają na liście: to dostęp odebrany w trakcie okresu
    albo trasa z bramką luźniejszą niż sekcja, jedno i drugie warto zobaczyć.
    """

    empty = AreaUsage(entries=0, active_days=0, last_day=None)
    rows: list[ReviewRow] = []
    for user in sorted(users, key=lambda item: item.id):
        roles = tuple(sorted(role.value for role in user.get_all_roles()))
        for area in AREA_LABELS:
            used = usage.get((user.id, area), empty)
            has_access = area_access(user, area)
            if has_access is not True and used.entries == 0:
                continue
            rows.append(
                ReviewRow(
                    user_id=user.id,
                    full_name=user.name,
                    email=user.email,
                    roles=roles,
                    area=area,
                    has_access=has_access,
                    entries=used.entries,
                    active_days=used.active_days,
                    last_day=used.last_day,
                )
            )
    return tuple(rows)


_USAGE_SQL = text(
    """
    SELECT user_id, area, SUM(entries) AS entries, COUNT(*) AS active_days,
           MAX(day) AS last_day
      FROM access_usage_daily
     WHERE day >= :since AND day <= :until
     GROUP BY user_id, area
    """
)
_COLLECTED_DAYS_SQL = text(
    "SELECT COUNT(DISTINCT day) FROM access_usage_daily "
    "WHERE day >= :since AND day <= :until"
)
_INTEGRATION_ACCOUNTS_SQL = text(
    "SELECT acting_user_id FROM oauth_clients WHERE acting_user_id IS NOT NULL"
)


async def load_review(
    db: AsyncSession, *, days: int, today: date | None = None
) -> Review:
    """Lista do przeglądu za ostatnie ``days`` dni, bez zapisu czegokolwiek.

    Tylko aktywne osoby. Konta integracji (scrapery) to nie ludzie, a ich tokeny
    i tak nie są liczone, więc wyszłyby w przeglądzie jako fałszywe zero.
    """

    from app.services.effective_access import resolve_effective_access

    until = today or business_today()
    since = until - timedelta(days=days - 1)
    window = {"since": since, "until": until}
    integration_ids = {
        row[0] for row in (await db.execute(_INTEGRATION_ACCOUNTS_SQL)).all()
    }
    users = [
        user
        for user in (
            await db.execute(select(User).where(User.is_active.is_(True)))
        ).scalars()
        if user.id not in integration_ids
    ]
    await resolve_effective_access(db, users)
    usage = {
        (row.user_id, row.area): AreaUsage(
            entries=int(row.entries),
            active_days=int(row.active_days),
            last_day=row.last_day,
        )
        for row in (await db.execute(_USAGE_SQL, window)).all()
    }
    collected_days = int((await db.execute(_COLLECTED_DAYS_SQL, window)).scalar() or 0)
    return Review(
        since=since,
        until=until,
        collected_days=collected_days,
        rows=build_review_rows(users, usage),
    )
