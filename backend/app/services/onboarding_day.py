"""Dzień onboardingu — pierwszy dzień nowej osoby poza normami (decyzja Artura 14.11.2026).

Nowa osoba pierwszego dnia przechodzi Poligon NEXUSA (``/poligon``), który
blokuje resztę ekranów, dopóki go nie skończy. Ten dzień nie może jej obniżać
statystyk: nie jest dniem pracy w mianowniku „na dzień”, w celach i tempie
KPI, w progu Wyścigu Rekomendacji ani w Porcji dnia. Weryfikacje
i rekomendacje zrobione mimo to tego dnia liczą się normalnie — to prawdziwa
praca, a zdjęcie jej z wyników tylko by osobie zaszkodziło.

* **Ścieżka per rola** (15.11.2026): rekruter, Delivery Lead i TCM mają własne
  ćwiczenia (``roles`` ćwiczenia), osoba przechodzi ćwiczenia każdej swojej
  roli (``poligon_exercises``).
* **Wymagany od nadania roli, nie od założenia konta** (Artur, 15.11.2026).
  Pierwsze logowanie SSO zakłada konto „Pracownik” (``employee``), które
  poligonu nie ma; rolę z poligonem nadaje potem ktoś w „Osoby i role”.
  Wymagane są ćwiczenia ścieżki obecnych ról, których nie obejmowała ścieżka
  ról osoby z dnia ``required_since`` (``PoligonRequirement``). Role z tego
  dnia odtwarzamy wstecz z historii zmian ról (``activities``: ``role_changed``,
  ``roles_changed``, ``sso_aad_*``, ``admin_aad_*``); konto założone później
  nie miało żadnej. Zmiana roli = tylko ćwiczenia nowej roli, których osoba
  jeszcze nie zaliczyła (wspólne moduły liczą się raz); powrót do roli, którą
  już przeszła, i rola bez ścieżki nie wymagają niczego.
* **Dzień onboardingu** = dzień (kalendarz firmy) pierwszego ćwiczenia
  z wymaganej listy zaliczonego po nadaniu roli — przy założeniu konta z rolą
  i przy każdej zmianie, która wnosi rolę z ``required_roles``. Obecni, którzy
  zajrzą na poligon z ciekawości, nie dostają przez to wolnego dnia.
* Bez migracji: wszystko wynika z istniejących wierszy postępu i historii.
"""

from __future__ import annotations

import json
from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date, datetime, time, timezone
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.scheduling import DEFAULT_TZ
from app.data.novelties import PoligonPlan, load_poligon

POLIGON_ID_PREFIX = "poligon-"

#: Zmiana pełnej listy ról (``from`` i ``to`` to listy).
_LIST_ACTIONS = ("roles_changed", "sso_aad_roles_updated", "admin_aad_roles_resynced")
#: Zmiana roli głównej (``from`` i ``to`` to napisy, czasem z ``all_roles``).
_PRIMARY_ACTIONS = ("role_changed", "sso_aad_role_assigned", "admin_aad_role_resynced")
#: Dawne role, które od 02.10.2026 są rekruterem.
_ROLE_ALIASES = {"tac": "recruiter", "sourcer": "recruiter"}


def _role_values(user: Any) -> set[str]:
    try:
        return {getattr(r, "value", str(r)) for r in user.get_all_roles()}
    except Exception:  # noqa: BLE001 — rola główna wystarcza jako zapas
        return {getattr(user.role, "value", str(user.role))}


def _aware(moment: datetime) -> datetime:
    return moment if moment.tzinfo is not None else moment.replace(tzinfo=timezone.utc)


def _local_day(moment: datetime) -> date:
    return _aware(moment).astimezone(ZoneInfo(DEFAULT_TZ)).date()


def _since_moment(plan: PoligonPlan) -> datetime:
    """Początek dnia ``required_since`` w kalendarzu firmy."""
    return datetime.combine(plan.required_since, time.min, tzinfo=ZoneInfo(DEFAULT_TZ))


def poligon_may_be_required(user: Any, plan: PoligonPlan | None = None) -> bool:
    """Czy poligon MOŻE być wymagany — bez zapytania do bazy.

    Ścieżki KPI biegną co minutę dla każdego, więc o dzień onboardingu pytają
    bazę tylko u osób, które przechodzą ten filtr: rola z ``required_roles``
    i konto założone od ``required_since`` albo onboarding roli zrobiony
    (lub jeszcze niezrobiony) od tego dnia — zmiana roli rekrutera i DL-a
    zeruje ``profile_completed_at``. Rozstrzyga ``poligon_requirement``."""
    plan = plan or load_poligon()
    if not _role_values(user) & set(plan.required_roles):
        return False
    created = getattr(user, "created_at", None)
    if created is None:
        return False
    if _local_day(created) >= plan.required_since:
        return True
    completed = getattr(user, "profile_completed_at", None)
    return completed is None or _local_day(completed) >= plan.required_since


def poligon_open(user: Any, plan: PoligonPlan | None = None) -> bool:
    """Czy osoba może przechodzić poligon i zapisywać postęp."""
    return bool(_role_values(user) & set((plan or load_poligon()).roles))


def poligon_exercises(user: Any, plan: PoligonPlan | None = None) -> list[str]:
    """Id ćwiczeń ścieżki osoby (ćwiczenia każdej jej roli)."""
    plan = plan or load_poligon()
    return [e.id for e in plan.exercises_for(_role_values(user))]


def poligon_replaces(user: Any, plan: PoligonPlan | None = None) -> set[str]:
    """Przeklikania Startu, które poligon zastępuje tej osobie."""
    plan = plan or load_poligon()
    return plan.replaced_for(_role_values(user) & set(plan.required_roles))


# ── Historia ról ───────────────────────────────────────────────────────────


def _roles_of(value: Any) -> set[str]:
    if isinstance(value, str):
        values = [value]
    elif isinstance(value, list):
        values = [v for v in value if isinstance(v, str)]
    else:
        values = []
    return {_ROLE_ALIASES.get(v, v) for v in values if v}


@dataclass(frozen=True)
class RoleChange:
    """Zmiana zbioru ról w jednej transakcji (wiersze z tym samym ``created_at``)."""

    at: datetime
    removed: frozenset[str]
    added: frozenset[str]


def role_changes(rows: Iterable[tuple[str, Any, datetime]]) -> list[RoleChange]:
    """Zmiany ról z wierszy ``activities`` (``action``, ``details``, ``created_at``).

    Lista ról niesie pełny zbiór, więc rozstrzyga ona. Sama zmiana roli głównej
    bez wiersza listy to zamiana w obrębie tej samej listy (rola główna zawsze
    w niej jest) — chyba że wiersz niesie ``all_roles`` (resynchronizacja
    z grup Entra pisze wtedy tylko wiersz roli głównej)."""
    groups: dict[datetime, list[tuple[str, dict[str, Any]]]] = defaultdict(list)
    for action, details, at in rows:
        if isinstance(details, str):
            try:
                details = json.loads(details)
            except ValueError:
                details = {}
        groups[_aware(at)].append(
            (action, details if isinstance(details, dict) else {})
        )
    changes: list[RoleChange] = []
    for at in sorted(groups):
        lists = [d for a, d in groups[at] if a in _LIST_ACTIONS]
        primaries = [d for a, d in groups[at] if a in _PRIMARY_ACTIONS]
        if lists:
            before = set().union(*(_roles_of(d.get("from")) for d in lists))
            after = set().union(*(_roles_of(d.get("to")) for d in lists))
        else:
            with_all = [d for d in primaries if d.get("all_roles")]
            if not with_all:
                continue
            after = set().union(
                *(
                    _roles_of(d.get("all_roles")) | _roles_of(d.get("to"))
                    for d in with_all
                )
            )
            before = set().union(
                *(
                    _roles_of(d.get("from"))
                    | (_roles_of(d.get("all_roles")) - _roles_of(d.get("to")))
                    for d in with_all
                )
            )
        if before != after:
            changes.append(
                RoleChange(at, frozenset(before - after), frozenset(after - before))
            )
    return changes


@dataclass(frozen=True)
class PoligonRequirement:
    """Co poligon wymaga od osoby i od kiedy."""

    #: Ćwiczenia wymagane (kolejność rejestru); puste = poligon nie blokuje.
    exercise_ids: tuple[str, ...]
    #: Chwile nadania roli z ``required_roles`` od ``required_since`` (założenie
    #: konta z rolą albo zmiana) — od nich liczy się dzień onboardingu.
    granted_at: tuple[datetime, ...]

    @property
    def required(self) -> bool:
        return bool(self.exercise_ids)


def requirement_for(
    *,
    roles: set[str],
    created_at: datetime | None,
    changes: list[RoleChange],
    plan: PoligonPlan,
) -> PoligonRequirement:
    """Wymagane ćwiczenia osoby z obecnych ról, daty konta i zmian ról."""
    required_roles = set(plan.required_roles)
    if not roles & required_roles or created_at is None:
        return PoligonRequirement((), ())
    since = _since_moment(plan)
    later = [c for c in changes if c.at >= since]
    created_later = _aware(created_at) >= since
    # Role z dnia `required_since`: obecne, cofnięte o późniejsze zmiany.
    known: set[str] = set()
    if not created_later:
        known = set(roles)
        for change in reversed(later):
            known = (known - change.added) | change.removed
    known_ids = {e.id for e in plan.exercises_for(known)}
    exercise_ids = tuple(
        e.id for e in plan.exercises_for(roles) if e.id not in known_ids
    )
    granted: list[datetime] = []
    if created_later:
        granted.append(_aware(created_at))
    granted += [c.at for c in later if c.added & required_roles]
    return PoligonRequirement(exercise_ids, tuple(granted))


async def _role_change_rows(
    db: AsyncSession, user_ids: list[int], since: datetime
) -> dict[int, list[tuple[str, Any, datetime]]]:
    rows = (
        await db.execute(
            text(
                """
                SELECT entity_id, action, details, created_at
                FROM activities
                WHERE entity_type = 'user'
                  AND entity_id = ANY(:ids)
                  AND action = ANY(:actions)
                  AND created_at >= :since
                """
            ),
            {
                "ids": user_ids,
                "actions": list(_LIST_ACTIONS + _PRIMARY_ACTIONS),
                "since": since,
            },
        )
    ).all()
    out: dict[int, list[tuple[str, Any, datetime]]] = defaultdict(list)
    for row in rows:
        out[int(row.entity_id)].append((row.action, row.details, row.created_at))
    return out


async def poligon_requirement(
    db: AsyncSession, user: Any, plan: PoligonPlan | None = None
) -> PoligonRequirement:
    """Wymagane ćwiczenia jednej osoby (jedno zapytanie o historię ról)."""
    plan = plan or load_poligon()
    if not poligon_may_be_required(user, plan):
        return PoligonRequirement((), ())
    since = _since_moment(plan)
    history = await _role_change_rows(db, [int(user.id)], since)
    return requirement_for(
        roles=_role_values(user),
        created_at=getattr(user, "created_at", None),
        changes=role_changes(history.get(int(user.id), [])),
        plan=plan,
    )


async def onboarding_days(
    db: AsyncSession, user_ids: Iterable[int], start: date, end: date
) -> dict[int, frozenset[date]]:
    """Dni onboardingu osób w ``[start, end]``: ``{user_id: {dzień, …}}``.

    Dzień = pierwsze ćwiczenie z wymaganej listy zaliczone po nadaniu roli;
    zmiana roli może dać osobie drugi taki dzień."""
    ids = sorted({int(uid) for uid in user_ids})
    if not ids:
        return {}
    plan = load_poligon()
    since = _since_moment(plan)
    done_rows = (
        await db.execute(
            text(
                """
                SELECT p.user_id, p.novelty_id, p.completed_at,
                       u.role::text AS role, u.roles, u.created_at
                FROM novelty_progress p
                JOIN users u ON u.id = p.user_id
                WHERE p.novelty_id LIKE :prefix
                  AND p.completed_at IS NOT NULL
                  AND p.completed_at >= :since
                  AND p.user_id = ANY(:ids)
                """
            ),
            {"prefix": f"{POLIGON_ID_PREFIX}%", "ids": ids, "since": since},
        )
    ).all()
    if not done_rows:
        return {}
    done: dict[int, list[tuple[str, datetime]]] = defaultdict(list)
    people: dict[int, tuple[set[str], datetime]] = {}
    for row in done_rows:
        uid = int(row.user_id)
        done[uid].append((row.novelty_id, _aware(row.completed_at)))
        roles = _roles_of(row.role) | _roles_of(
            row.roles if not isinstance(row.roles, str) else json.loads(row.roles)
        )
        people[uid] = (roles, row.created_at)
    history = await _role_change_rows(db, sorted(people), since)
    out: dict[int, frozenset[date]] = {}
    for uid, (roles, created_at) in people.items():
        need = requirement_for(
            roles=roles,
            created_at=created_at,
            changes=role_changes(history.get(uid, [])),
            plan=plan,
        )
        if not need.required:
            continue
        wanted = set(need.exercise_ids)
        completions = sorted(at for eid, at in done[uid] if eid in wanted)
        days = {
            _local_day(first)
            for granted in need.granted_at
            if (first := next((at for at in completions if at >= granted), None))
        }
        in_range = frozenset(d for d in days if start <= d <= end)
        if in_range:
            out[uid] = in_range
    return out
