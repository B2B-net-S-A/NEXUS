"""Kartoteka z katalogu Microsoft 365 — raz dziennie od 6:00 (Warszawa).

Dla każdej osoby z kartoteką w katalogu „Ludzi” (``onboarding`` / ``active``
/ ``offboarding``) z aktywnym kontem czytamy konto w Entra ID
(``directory.GraphDirectoryOps``) i przepisujemy pola, które kartoteka już
ma: stanowisko, dział, telefon służbowy. Lokalizacji biura z katalogu nie
przenosimy — kartoteka ma tylko domyślne miejsce pracy (biuro / zdalnie),
a to ustalają Kadry.

Reguła pierwszeństwa (Kadry przed katalogiem). Pole zmienione ręcznie
w NEXUSIE (``profile_created`` / ``profile_updated`` w ``hr_audit_events``,
także kreator wejścia) PO ostatnim zapisie tego pola z Microsoft 365 jest
przypięte — synchronizacja go nie nadpisuje, nawet gdy katalog się zmieni.
Kadry odpinają pole, czyszcząc je: puste pole kartoteki zawsze wypełnia
katalog. Pusty atrybut w katalogu niczego w kartotece nie kasuje. Wartości
z importu Compassa nie są ręczne (Compass sam co tydzień kopiował katalog),
więc pierwsza synchronizacja je odświeża. Compass nadpisywał ręczne zmiany
Kadr przy każdym przebiegu — tu ten błąd jest naprawiony.

Tryby (``HR_M365_MODE``): ``off`` — nic; ``simulate`` — żądania budowane
jak w ``live``, ale do Graph nic nie wychodzi, a kartoteka zostaje bez zmian
(wynik mówi, ile kont i jakim żądaniem byśmy przeczytali); ``live`` —
prawdziwy odczyt, tylko konta z ``HR_M365_MAILBOX_ALLOWLIST`` (pusta =
wszystkie), jak przy zapisie w skrzynkach.

Przełożony z katalogu (etap 2, D7): po koncie czytamy
``GET /users/{upn}/manager?$select=userPrincipalName`` i w trybie ``live``
zapisujemy UPN w ``m365_manager_upn`` (404 = bez przełożonego → pusto).
``manager_user_id`` NIE zmienia się nigdy — rozjazd pokazuje „Ludzie →
Struktura” z „Przyjmij” dla Kadr. Błąd tego odczytu (poza odmową dla całej
rejestracji) zostawia poprzednią podpowiedź i liczy się w ``manager_errors``.
Zmiana podpowiedzi nie jest zmianą kartoteki — bez śladu, licznik
``manager_changed``.

Odczyt: 404 = konto spoza tenanta albo bez skrzynki → pomijamy i liczymy;
403 albo brak tokenu = rejestracja bez ``User.Read.All`` → przebieg kończy się
``failed`` (sonda ``hr_m365`` i ``hr_jobs`` degraded) i wraca przy następnym
obrocie pętli. Ślad w ``hr_audit_events`` tylko przy zmianie (nazwy pól,
bez wartości); ``m365_synced_at`` stempluje każdy udany odczyt.

Rezerwacja w ``hr_job_runs`` (``kind = hr_m365_profile_sync``, klucz = dzień).
Zapis każdej osoby we własnej transakcji pod blokadą wiersza kartoteki —
równoległa edycja w Kadrach albo zostaje przed nami (i przypina pole), albo
po nas.
"""

from __future__ import annotations

import logging
from collections import Counter
from collections.abc import Collection, Iterable
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.hr_ops import HrAuditEvent
from app.models.hr_profile import EmployeeProfile
from app.models.user import User
from app.services.hr import audit
from app.services.hr.m365 import runs
from app.services.hr.m365.directory import (
    FIELDS,
    MANAGER_SELECT,
    USER_SELECT,
    DirectoryOps,
    GraphDirectoryOps,
    SimulatedDirectoryOps,
    account_disabled,
    profile_values,
)
from app.services.hr.m365.executor import (
    allowlist,
    current_mode,
    mailbox_address,
    mailbox_allowed,
    utc_now,
    warsaw_hour,
    warsaw_today,
)
from app.services.hr.m365.ops import MailboxError
from app.services.hr.modules import load_modules
from app.services.hr.people import DIRECTORY_STATUSES

logger = logging.getLogger(__name__)

JOB_KIND = "hr_m365_profile_sync"
SYNC_HOUR = 6
#: Górna granica kont na przebieg (zespół to dziś kilkadziesiąt osób).
MAX_PROFILES = 500

SYNC_ACTION = "profile_m365_synced"
MANUAL_ACTIONS: tuple[str, ...] = ("profile_created", "profile_updated")
#: Odmowa dla całej rejestracji — kolejne konta dostałyby to samo.
ABORT_CATEGORIES = frozenset({"forbidden", "auth"})
REQUEST_TEMPLATE = f"GET /users/{{upn}}?$select={USER_SELECT}"
MANAGER_REQUEST_TEMPLATE = f"GET /users/{{upn}}/manager?$select={MANAGER_SELECT}"


@dataclass(frozen=True)
class Target:
    user_id: int
    upn: Optional[str]


def manual_fields(events: Iterable[tuple[str, Any, datetime]]) -> set[str]:
    """Pola przypięte ręcznie: ostatnia zmiana Kadr nowsza niż ostatni zapis z M365.

    ``events`` = (akcja, szczegóły, chwila) ze śladu kartoteki osoby.
    """

    manual: dict[str, datetime] = {}
    synced: dict[str, datetime] = {}
    for action, details, moment in events:
        fields = details.get("fields") if isinstance(details, dict) else None
        if not isinstance(fields, list):
            continue
        target = synced if action == SYNC_ACTION else manual
        for field in fields:
            if field in FIELDS and (field not in target or moment > target[field]):
                target[field] = moment
    return {
        field
        for field, moment in manual.items()
        if field not in synced or moment > synced[field]
    }


def plan_changes(
    current: dict[str, Optional[str]],
    remote: dict[str, Optional[str]],
    pinned: Collection[str],
) -> tuple[dict[str, str], list[str]]:
    """Zmiany do zapisu i pola zostawione, bo Kadry zmieniły je ręcznie."""

    changes: dict[str, str] = {}
    kept: list[str] = []
    for field in FIELDS:
        value = remote.get(field)
        if value is None or value == current.get(field):
            continue
        if current.get(field) and field in pinned:
            kept.append(field)
            continue
        changes[field] = value
    return changes, kept


async def _targets(
    db: AsyncSession, user_ids: Optional[Collection[int]]
) -> list[Target]:
    query = (
        select(EmployeeProfile.user_id, User)
        .join(User, User.id == EmployeeProfile.user_id)
        .where(
            EmployeeProfile.employment_status.in_(DIRECTORY_STATUSES),
            User.is_active.is_(True),
        )
    )
    if user_ids is not None:
        query = query.where(EmployeeProfile.user_id.in_(list(user_ids)))
    rows = (
        await db.execute(query.order_by(EmployeeProfile.user_id).limit(MAX_PROFILES))
    ).all()
    return [
        Target(user_id=user_id, upn=mailbox_address(user)) for user_id, user in rows
    ]


async def _pinned(db: AsyncSession, user_id: int) -> set[str]:
    rows = await db.execute(
        select(
            HrAuditEvent.action, HrAuditEvent.details, HrAuditEvent.created_at
        ).where(
            HrAuditEvent.subject_user_id == user_id,
            HrAuditEvent.entity_type == "employee_profile",
            HrAuditEvent.action.in_((*MANUAL_ACTIONS, SYNC_ACTION)),
        )
    )
    return manual_fields(rows.all())


async def _apply(
    db: AsyncSession,
    user_id: int,
    remote: dict[str, Optional[str]],
    now: datetime,
    manager: Optional[str] = None,
    *,
    manager_read: bool = False,
) -> tuple[str, int, bool]:
    """Zapis jednej kartoteki: (etykieta licznika, przypięte pola, nowa podpowiedź
    przełożonego). ``manager_read=False`` — odczyt przełożonego się nie udał,
    podpowiedź zostaje jak była."""

    profile = await db.scalar(
        select(EmployeeProfile)
        .where(
            EmployeeProfile.user_id == user_id,
            EmployeeProfile.employment_status.in_(DIRECTORY_STATUSES),
        )
        .with_for_update()
    )
    if profile is None:
        await db.rollback()
        return "missing", 0, False
    current = {field: getattr(profile, field) for field in FIELDS}
    changes, kept = plan_changes(current, remote, await _pinned(db, user_id))
    for field, value in changes.items():
        setattr(profile, field, value)
    profile.m365_synced_at = now
    manager_changed = manager_read and profile.m365_manager_upn != manager
    if manager_changed:
        profile.m365_manager_upn = manager
    if changes:
        audit.record(
            db,
            actor_user_id=None,
            subject_user_id=user_id,
            entity_type="employee_profile",
            entity_id=profile.id,
            action=SYNC_ACTION,
            details={"fields": sorted(changes)},
        )
    await db.commit()
    return ("updated" if changes else "unchanged"), len(kept), manager_changed


async def _sync(
    db: AsyncSession,
    directory: DirectoryOps,
    mode: str,
    now: datetime,
    user_ids: Optional[Collection[int]],
) -> tuple[dict[str, Any], Optional[str]]:
    """Liczniki przebiegu i kategoria błędu, który go przerwał (albo ``None``)."""

    targets = await _targets(db, user_ids)
    # Bez otwartej transakcji na czas odczytów z Graph.
    await db.commit()
    counts: Counter[str] = Counter(profiles=len(targets))
    allowed = allowlist()
    for target in targets:
        if target.upn is None:
            counts["no_address"] += 1
            continue
        if mode == "live" and not mailbox_allowed(target.upn, allowed):
            counts["not_allowlisted"] += 1
            continue
        try:
            data = await directory.get_user(target.upn)
        except MailboxError as exc:
            if exc.category in ABORT_CATEGORIES:
                return dict(counts), exc.category
            counts["not_found" if exc.status == 404 else "errors"] += 1
            continue
        counts["read"] += 1
        if account_disabled(data):
            counts["account_disabled"] += 1
        manager: Optional[str] = None
        manager_read = False
        try:
            manager = await directory.get_manager(target.upn)
            manager_read = True
        except MailboxError as exc:
            if exc.category in ABORT_CATEGORIES:
                return dict(counts), exc.category
            counts["manager_errors"] += 1
        if mode != "live":
            continue
        label, kept, manager_changed = await _apply(
            db,
            target.user_id,
            profile_values(data),
            now,
            manager,
            manager_read=manager_read,
        )
        counts[label] += 1
        if kept:
            counts["kept_manual"] += kept
        if manager_changed:
            counts["manager_changed"] += 1
    if counts["errors"] and not counts["read"] and not counts["not_found"]:
        return dict(counts), "all_reads_failed"
    return dict(counts), None


async def run_once(
    db: AsyncSession,
    *,
    ops: Optional[DirectoryOps] = None,
    mode: Optional[str] = None,
    now: Optional[datetime] = None,
    user_ids: Optional[Collection[int]] = None,
) -> dict[str, Any]:
    """Jeden przebieg dziennie od 6:00; wcześniej i powtórnie — nic.

    ``user_ids`` zawęża przebieg do wskazanych osób (testy).
    """

    mode = mode or current_mode()
    if mode == "off":
        return {"mode": "off"}
    now = now or utc_now()
    if warsaw_hour(now) < SYNC_HOUR:
        return {"mode": mode, "skipped": "before_06"}
    if not (await load_modules(db)).get("people"):
        return {"mode": mode, "skipped": "module_off"}
    if mode == "live" and ops is None:
        from app.services.hr.m365.auth import credentials_configured

        if not credentials_configured():
            return {"mode": mode, "skipped": "no_credentials"}

    run_id = await runs.claim(db, JOB_KIND, warsaw_today(now).isoformat(), now)
    if run_id is None:
        return {"mode": mode, "skipped": "already_ran"}

    own_ops = ops is None
    directory: DirectoryOps = ops or (
        SimulatedDirectoryOps() if mode == "simulate" else GraphDirectoryOps()
    )
    try:
        counts, error = await _sync(db, directory, mode, now, user_ids)
    except Exception as exc:  # noqa: BLE001 — przebieg do ponowienia, nie cichy sukces
        logger.exception("hr_m365_profile_sync failed")
        await db.rollback()
        await runs.finish(
            db, run_id, status="failed", counts={"mode": mode}, error=type(exc).__name__
        )
        return {"mode": mode, "failed": type(exc).__name__}
    finally:
        if own_ops:
            await directory.aclose()

    counts = {"mode": mode, **counts}
    if mode == "simulate":
        counts["request"] = REQUEST_TEMPLATE
        counts["manager_request"] = MANAGER_REQUEST_TEMPLATE
    if error is not None:
        logger.warning("hr_m365_profile_sync stopped: %s", error)
        await runs.finish(db, run_id, status="failed", counts=counts, error=error)
        return {**counts, "failed": error}
    await runs.finish(db, run_id, status="done", counts=counts)
    return counts
