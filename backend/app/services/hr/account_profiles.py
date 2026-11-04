"""Kartoteka idzie za kontem NEXUSA (decyzja Artura 19.10.2026: „Konto decyduje + lista rozjazdów”).

* **Każde aktywne konto pracownicze ma kartotekę.** Brakującą zakłada
  ``ensure_profile`` — przy zakładaniu konta (admin, pierwsze logowanie SSO)
  i w „Wyrównaj wg konta” — jako „aktywny”, z formą i przełożonym „do
  uzupełnienia” (``employment_type_pending``, ``created_from_account``).
  Konto pracownicze = ``people.is_staff_account`` (bez „Automatyzacji”,
  starego podglądu, niepotwierdzonej rejestracji i kont integracji OAuth —
  ``oauth_clients.acting_user_id``; konta serwisowe kluczy API to osobna
  tabela ``service_accounts``, nie ``users``).
* **Status kartoteki idzie za kontem.** Wyłączenie konta → „zakończył
  współpracę” (``exited``) z ostatnim dniem pracy = dzień wyłączenia, chyba że
  kartoteka ma wcześniejszy; ponowne włączenie → stan sprzed wyłączenia
  (np. odejście w toku z jego ostatnim dniem), a gdy kartotekę ktoś w tym
  czasie zmienił albo zamknął ją ręcznie — „aktywny” bez ostatniego dnia
  (decyzja Artura 21.10.2026). Konto zmienia się w dziewięciu miejscach (Osoby
  i role, usunięcie konta, SSO bez roli, synchronizacja grup AAD, sprawa
  odejścia…), więc pilnuje tego jeden listener ``after_flush`` na
  ``users.is_active``, w tej samej transakcji co zmiana konta. Ślad:
  ``hr_audit_events`` ``profile_follows_account`` (``source: account``).
* **Lista rozjazdów** (``mismatches``) w „Ludzie → Katalog” dla admina,
  Finansów i Kadr i „Wyrównaj wg konta” (``align``) — dla stanu sprzed tej
  zmiany i dla tego, co ominie listener (zapis surowym SQL-em).
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Any, Optional
from zoneinfo import ZoneInfo

from sqlalchemy import event, func, inspect, select, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from app.core.scheduling import DEFAULT_TZ, business_today, local_now
from app.models.activity import Activity
from app.models.hr_profile import EmployeeProfile
from app.models.user import User
from app.services.hr import audit
from app.services.hr.people import integration_account_ids, is_staff_account
from app.services.hr.program import program_enabled
from app.services.hr_foundation_schema import EmploymentStatus, EmploymentType

logger = logging.getLogger(__name__)

FOLLOW_ACTION = "profile_follows_account"
CREATED_ACTION = "profile_created_from_account"

#: Wpisy ``activities``, którymi ścieżki wyłączające konto zostawiają ślad —
#: z nich (a bez nich z ``tokens_valid_after``) bierze się dzień wyłączenia.
DEACTIVATION_ACTIONS: tuple[str, ...] = (
    "user_deactivated",
    "hr_lifecycle_deactivated",
    "compass_lifecycle_deactivated",
    "sso_aad_role_denied",
    "admin_aad_role_denied",
    "m365_account_gone_deactivated",
)

#: Statusy, które konto wyłączone zamyka (odejście w toku też — decyzja Artura).
_OPEN_STATUSES: tuple[str, ...] = tuple(
    status for status in EmploymentStatus if status != EmploymentStatus.exited
)

_EXIT_SQL = text(
    """
    WITH target AS (
        SELECT id, employment_status AS before, last_working_day AS before_day
        FROM employee_profiles
        WHERE user_id = :user_id AND employment_status <> 'exited'
        FOR UPDATE
    )
    UPDATE employee_profiles p
    SET employment_status = 'exited',
        exited_at = now(),
        last_working_day = LEAST(COALESCE(p.last_working_day, :day), :day),
        updated_at = now()
    FROM target
    WHERE p.id = target.id
    RETURNING p.id, target.before, target.before_day, p.last_working_day
    """
)

#: Powrót konta. Kartoteka wraca do stanu sprzed wyłączenia (status i ostatni
#: dzień ze śladu ``profile_follows_account``), gdy wyłączenie zamknęło ją samo
#: — ślad z tej samej transakcji co ``exited_at`` — a ostatni dzień od tamtej
#: pory się nie zmienił. Inaczej (ręczne zakończenie, poprawka Kadr) „aktywny”
#: bez ostatniego dnia, jak dotąd. Decyzja Artura 21.10.2026: pomyłkowe
#: wyłączenie konta nie kasuje odejścia w toku.
_RETURN_SQL = text(
    """
    WITH target AS (
        SELECT id, last_working_day AS before_day, exited_at
        FROM employee_profiles
        WHERE user_id = :user_id AND employment_status = 'exited'
        FOR UPDATE
    ),
    prev AS (
        SELECT DISTINCT ON (e.entity_id) e.entity_id, e.details
        FROM hr_audit_events e
        JOIN target t ON e.entity_id = t.id::text
        WHERE e.entity_type = 'employee_profile'
          AND e.action = 'profile_follows_account'
          AND e.details ->> 'to' = 'exited'
          AND e.details ->> 'source' = 'account'
          AND e.created_at = t.exited_at
        ORDER BY e.entity_id, e.id DESC
    ),
    restore AS (
        SELECT t.id,
               t.before_day,
               prev.details ->> 'from' AS status,
               (prev.details ->> 'previous_last_working_day')::date AS day
        FROM target t
        LEFT JOIN prev ON prev.entity_id = t.id::text
        WHERE prev.details ->> 'from' IN ('pending', 'onboarding', 'active', 'offboarding')
          AND prev.details ->> 'last_working_day' IS NOT DISTINCT FROM t.before_day::text
    )
    UPDATE employee_profiles p
    SET employment_status = COALESCE(restore.status, 'active'),
        exited_at = NULL,
        last_working_day = restore.day,
        updated_at = now()
    FROM target
    LEFT JOIN restore ON restore.id = target.id
    WHERE p.id = target.id
    RETURNING p.id, target.before_day, p.employment_status, p.last_working_day
    """
)

_AUDIT_SQL = text(
    """
    INSERT INTO hr_audit_events
        (actor_user_id, subject_user_id, entity_type, entity_id, action,
         sensitivity, details)
    VALUES (NULL, :user_id, 'employee_profile', :entity_id, :action, 'general',
            CAST(:details AS JSONB))
    """
)


def _iso(value: Optional[date]) -> Optional[str]:
    return value.isoformat() if value is not None else None


# ── Listener: status kartoteki idzie za ``users.is_active`` ───────────────────


def _account_switches(session: Session) -> list[tuple[int, bool]]:
    switches: list[tuple[int, bool]] = []
    for obj in session.dirty:
        if not isinstance(obj, User) or obj.id is None:
            continue
        history = inspect(obj).attrs.is_active.history
        if not history.has_changes():
            continue
        before = bool(history.deleted[0]) if history.deleted else None
        after = bool(obj.is_active)
        if before is not None and before != after:
            switches.append((obj.id, after))
    return switches


def _follow(session: Session, user_id: int, active: bool) -> None:
    connection = session.connection()
    if active:
        rows = connection.execute(_RETURN_SQL, {"user_id": user_id}).all()
        details = [
            {
                "from": "exited",
                "to": status,
                "previous_last_working_day": _iso(before_day),
                "last_working_day": _iso(day),
            }
            for _, before_day, status, day in rows
        ]
    else:
        rows = connection.execute(
            _EXIT_SQL, {"user_id": user_id, "day": business_today()}
        ).all()
        details = [
            {
                "from": before,
                "to": "exited",
                "previous_last_working_day": _iso(before_day),
                "last_working_day": _iso(day),
            }
            for _, before, before_day, day in rows
        ]
    for (profile_id, *_), detail in zip(rows, details):
        connection.execute(
            _AUDIT_SQL,
            {
                "user_id": user_id,
                "entity_id": str(profile_id),
                "action": FOLLOW_ACTION,
                "details": json.dumps({**detail, "source": "account"}),
            },
        )
    if rows:
        session.info.setdefault("hr_profiles_followed", set()).add(user_id)


@event.listens_for(Session, "after_flush")
def _profile_follows_account(session: Session, _context: Any) -> None:
    # W ``after_flush`` historia atrybutów jest jeszcze sprzed flusha. Zapis idzie
    # przez połączenie sesji: wycofanie zmiany konta wycofuje i kartotekę.
    for user_id, active in _account_switches(session):
        _follow(session, user_id, active)


@event.listens_for(Session, "after_flush_postexec")
def _expire_followed_profiles(session: Session, _context: Any) -> None:
    followed = session.info.pop("hr_profiles_followed", None)
    if not followed:
        return
    for obj in list(session.identity_map.values()):
        if isinstance(obj, EmployeeProfile) and obj.user_id in followed:
            session.expire(obj)


# ── Zakładanie brakującej kartoteki ───────────────────────────────────────────


async def ensure_profile(
    db: AsyncSession, user: User, *, actor_id: Optional[int], source: str
) -> Optional[EmployeeProfile]:
    """Kartoteka dla aktywnego konta pracowniczego, które jej nie ma.

    „Aktywny”, forma B2B tylko jako wartość domyślna z ``employment_type_pending``
    („do uzupełnienia”), bez przełożonego (``created_from_account`` = przełożony
    do uzupełnienia). ``None``, gdy nie ma czego zakładać.
    """

    if not user.is_active or not is_staff_account(
        user, integration_ids=await integration_account_ids(db)
    ):
        return None
    existing = await db.scalar(
        select(EmployeeProfile.id).where(EmployeeProfile.user_id == user.id)
    )
    if existing is not None:
        return None
    profile = EmployeeProfile(
        user_id=user.id,
        employment_status=EmploymentStatus.active,
        employment_type=EmploymentType.b2b,
        employment_type_pending=True,
        created_from_account=True,
        updated_by=actor_id,
    )
    db.add(profile)
    await db.flush()
    audit.record(
        db,
        actor_user_id=actor_id,
        subject_user_id=user.id,
        entity_type="employee_profile",
        entity_id=profile.id,
        action=CREATED_ACTION,
        details={"source": source},
    )
    return profile


async def ensure_profile_on_account(
    db: AsyncSession, user: User, *, actor_id: Optional[int], source: str
) -> None:
    """``ensure_profile`` przy zakładaniu konta i logowaniu SSO.

    Działa przy włączonym programie „Ludzie”; w savepoincie — kartoteka nie może
    zablokować logowania ani założenia konta (błąd idzie do logu, a brak
    kartoteki pokaże lista rozjazdów).
    """

    if not program_enabled():
        return
    try:
        async with db.begin_nested():
            await ensure_profile(db, user, actor_id=actor_id, source=source)
    except SQLAlchemyError:
        logger.warning(
            "hr profile from account failed: user_id=%s source=%s",
            user.id,
            source,
            exc_info=True,
        )


# ── Lista rozjazdów i „Wyrównaj wg konta” ─────────────────────────────────────


@dataclass(frozen=True)
class Mismatch:
    user_id: int
    name: str
    email: str
    account_active: bool
    #: ``None`` = brak kartoteki.
    employment_status: Optional[str]
    proposed_status: str
    last_working_day: Optional[date]
    proposed_last_working_day: Optional[date]
    #: ``exit`` (konto wyłączone), ``return`` (konto włączone, kartoteka
    #: zamknięta), ``missing`` (aktywne konto bez kartoteki).
    kind: str
    #: Podwładni z kartoteką (≠ ``exited``) — przy ``exit`` trzeba ich przepiąć
    #: w „Strukturze”: sprawy odejścia dla zamkniętej kartoteki się nie zakłada
    #: (decyzja Artura 19.10.2026), więc przekazanie nie zrobi się samo.
    reports: int = 0

    def payload(self) -> dict[str, Any]:
        return {
            "user_id": self.user_id,
            "name": self.name,
            "email": self.email,
            "account_active": self.account_active,
            "employment_status": self.employment_status,
            "proposed_status": self.proposed_status,
            "last_working_day": _iso(self.last_working_day),
            "proposed_last_working_day": _iso(self.proposed_last_working_day),
            "kind": self.kind,
            "reports": self.reports,
        }


async def switched_off_on(db: AsyncSession, user: User) -> date:
    """Dzień wyłączenia konta (kalendarz firmy): ślad w ``activities``,
    potem ``tokens_valid_after``, a bez obu — dziś."""

    at: Optional[datetime] = await db.scalar(
        select(func.max(Activity.created_at)).where(
            Activity.entity_type == "user",
            Activity.entity_id == user.id,
            Activity.action.in_(DEACTIVATION_ACTIONS),
        )
    )
    at = at or user.tokens_valid_after
    if at is None:
        return business_today()
    if at.tzinfo is None:
        at = at.replace(tzinfo=timezone.utc)
    return at.astimezone(ZoneInfo(DEFAULT_TZ)).date()


async def mismatches(db: AsyncSession) -> list[Mismatch]:
    rows = (
        await db.execute(
            select(User, EmployeeProfile)
            .outerjoin(EmployeeProfile, EmployeeProfile.user_id == User.id)
            .where(EmployeeProfile.id.is_not(None) | User.is_active.is_(True))
            .order_by(User.name, User.id)
        )
    ).all()
    reports = dict(
        (
            await db.execute(
                select(EmployeeProfile.manager_user_id, func.count())
                .where(
                    EmployeeProfile.manager_user_id.is_not(None),
                    EmployeeProfile.employment_status != EmploymentStatus.exited,
                )
                .group_by(EmployeeProfile.manager_user_id)
            )
        ).all()
    )
    integration_ids = await integration_account_ids(db)
    found: list[Mismatch] = []
    for user, profile in rows:
        if profile is None:
            if user.is_active and is_staff_account(
                user, integration_ids=integration_ids
            ):
                found.append(
                    Mismatch(
                        user_id=user.id,
                        name=user.name,
                        email=user.email,
                        account_active=True,
                        employment_status=None,
                        proposed_status=EmploymentStatus.active,
                        last_working_day=None,
                        proposed_last_working_day=None,
                        kind="missing",
                    )
                )
            continue
        if not user.is_active and profile.employment_status in _OPEN_STATUSES:
            off = await switched_off_on(db, user)
            current = profile.last_working_day
            found.append(
                Mismatch(
                    user_id=user.id,
                    name=user.name,
                    email=user.email,
                    account_active=False,
                    employment_status=profile.employment_status,
                    proposed_status=EmploymentStatus.exited,
                    last_working_day=current,
                    proposed_last_working_day=min(current, off) if current else off,
                    kind="exit",
                    reports=reports.get(user.id, 0),
                )
            )
        elif user.is_active and profile.employment_status == EmploymentStatus.exited:
            found.append(
                Mismatch(
                    user_id=user.id,
                    name=user.name,
                    email=user.email,
                    account_active=True,
                    employment_status=profile.employment_status,
                    proposed_status=EmploymentStatus.active,
                    last_working_day=profile.last_working_day,
                    proposed_last_working_day=None,
                    kind="return",
                )
            )
    return found


async def align(
    db: AsyncSession,
    *,
    actor: User,
    user_ids: Optional[set[int]] = None,
    skip_user_ids: frozenset[int] | set[int] = frozenset(),
) -> dict[str, int]:
    """„Wyrównaj wg konta” — wszystkie rozjazdy albo tylko ``user_ids``.

    ``skip_user_ids`` — kartoteki, których wołający nie rusza („nie sobie”).
    Wołający commituje. Zwraca liczby (bez nazwisk — wynik trafia też do logów
    przebiegu na produkcji).
    """

    counts = {"exit": 0, "return": 0, "missing": 0}
    now = local_now()
    for item in await mismatches(db):
        if user_ids is not None and item.user_id not in user_ids:
            continue
        if item.user_id in skip_user_ids:
            continue
        if item.kind == "missing":
            user = await db.get(User, item.user_id)
            if user is not None and await ensure_profile(
                db, user, actor_id=actor.id, source="align"
            ):
                counts["missing"] += 1
            continue
        profile = await db.scalar(
            select(EmployeeProfile)
            .where(EmployeeProfile.user_id == item.user_id)
            .with_for_update()
        )
        if profile is None:
            continue
        before_status = profile.employment_status
        before_day = profile.last_working_day
        profile.employment_status = item.proposed_status
        profile.last_working_day = item.proposed_last_working_day
        profile.exited_at = now if item.kind == "exit" else None
        profile.updated_by = actor.id
        audit.record(
            db,
            actor_user_id=actor.id,
            subject_user_id=item.user_id,
            entity_type="employee_profile",
            entity_id=profile.id,
            action=FOLLOW_ACTION,
            details={
                "from": before_status,
                "to": item.proposed_status,
                "previous_last_working_day": _iso(before_day),
                "last_working_day": _iso(item.proposed_last_working_day),
                "source": "align",
            },
        )
        counts[item.kind] += 1
    await db.flush()
    return counts


async def pending_counts(db: AsyncSession) -> dict[str, int]:
    """Licznik „do uzupełnienia” w katalogu (Kadry, Finanse, admin)."""

    working = EmployeeProfile.employment_status != EmploymentStatus.exited
    form = await db.scalar(
        select(func.count())
        .select_from(EmployeeProfile)
        .where(working, EmployeeProfile.employment_type_pending)
    )
    manager = await db.scalar(
        select(func.count())
        .select_from(EmployeeProfile)
        .where(
            working,
            EmployeeProfile.created_from_account,
            EmployeeProfile.manager_user_id.is_(None),
        )
    )
    return {"employment_type": int(form or 0), "manager": int(manager or 0)}


__all__ = [
    "CREATED_ACTION",
    "FOLLOW_ACTION",
    "Mismatch",
    "align",
    "ensure_profile",
    "ensure_profile_on_account",
    "mismatches",
    "pending_counts",
    "switched_off_on",
]
