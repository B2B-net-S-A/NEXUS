"""„Nowe osoby do ustawienia” — decyzja Artura z 28.10.2026 (0609).

Pierwsze logowanie przez Microsoft zakłada konto „Konsultant/Kontraktor”
(``employee``) i dotąd nikt się o tym nie dowiadywał: konto czekało tygodniami,
a rekruter, któremu ktoś później nadał rolę, zostawał bez kategorii
kompetencji (automat nie dawał mu requestów) albo bez przełożonego.

- ``mark_and_notify`` — po pierwszym logowaniu: znacznik
  ``users.setup_pending_since`` i dzwonek ``new_person_signed_in`` (mail od
  razu) do aktywnych adminów i Head of Recruitment. Nigdy nie blokuje
  logowania.
- ``load_rows_safely`` — lista w „Czeka na Ciebie” (admin i HoR): nowe konta
  do decyzji oraz rekruterzy bez kategorii albo bez przełożonego.

Zapis decyzji: ``api/people_setup.py``.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import exists, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.competence_category import UserCompetenceCategory
from app.models.hr_profile import EmployeeProfile
from app.models.notification import NotificationType
from app.models.user import User, UserRole
from app.services.auto_cc_collaborators import operator_clause
from app.services.hr.program import program_enabled

logger = logging.getLogger(__name__)

MISSING_CATEGORIES = "categories"
MISSING_MANAGER = "manager"

# Osoby prowadzące zespół z rolą rekrutera obok (Olaf: admin + HoR + rekruter)
# nie należą do kategorii — nie stoją na liście jako „bez kategorii”.
_LEADER_ROLES = (UserRole.admin, UserRole.head_of_recruitment)


def setup_link(user_id: int, *, keep: bool = False) -> str:
    """Pulpit z otwartym oknem „Ustaw” — samo okno, decyzja dopiero w nim."""
    query = f"nowa-osoba={user_id}" + ("&zostaw=1" if keep else "")
    return f"/dashboard?{query}#czeka-na-ciebie"


def notification_text(user: User) -> tuple[str, str]:
    title = f"Nowa osoba w NEXUSIE: {user.name}"
    message = (
        f"Pierwsze logowanie przez Microsoft założyło konto „Konsultant/Kontraktor” "
        f"({user.email}). Jeśli to rekruter, nadaj rolę, kategorie kompetencji "
        "i przełożonego. Jeśli konsultant albo back office, zostaw tak, jak jest."
    )
    return title, message


async def recipients(db: AsyncSession) -> list[int]:
    """Aktywni admini i Head of Recruitment (rola główna albo dodatkowa)."""
    return list(
        (
            await db.scalars(
                select(User.id).where(
                    User.is_active.is_(True),
                    or_(
                        User.role.in_(_LEADER_ROLES),
                        *(User.roles.contains([r.value]) for r in _LEADER_ROLES),
                    ),
                )
            )
        ).all()
    )


async def mark_and_notify(
    db: AsyncSession, user: User, *, now: Optional[datetime] = None
) -> int:
    """Nowe konto SSO, które zostało „Konsultantem/Kontraktorem”: znacznik
    i dzwonek do adminów i HoR. Zwraca liczbę wysłanych dzwonków.

    Konto, któremu mapowanie grup AAD dało inną rolę, nie czeka na nikogo.
    Powiadomienie jest dodatkiem: jego awaria idzie do logu, logowanie trwa.
    """
    if [str(r) for r in (user.roles or [])] != [UserRole.employee.value]:
        return 0
    user.setup_pending_since = now or datetime.now(timezone.utc)
    from app.services.notification_triggers import emit  # noqa: PLC0415

    title, message = notification_text(user)
    sent = 0
    try:
        async with db.begin_nested():
            for recipient_id in await recipients(db):
                created = await emit(
                    db,
                    user_id=recipient_id,
                    title=title,
                    message=message,
                    ntype=NotificationType.new_person_signed_in,
                    related_entity_type="user",
                    related_entity_id=user.id,
                    link=setup_link(user.id),
                )
                sent += int(created is not None)
    except Exception:  # noqa: BLE001
        logger.exception(
            "new_person_setup: powiadomienie o koncie %s nie wyszło", user.id
        )
        return 0
    return sent


@dataclass(frozen=True)
class NewPersonRow:
    user_id: int
    name: str
    email: str
    since: datetime
    needs_decision: bool
    missing: tuple[str, ...]

    def as_dict(self) -> dict:
        return {
            "user_id": self.user_id,
            "name": self.name,
            "email": self.email,
            "since": self.since,
            "needs_decision": self.needs_decision,
            "missing": list(self.missing),
        }


def _not_leader():
    return ~or_(
        User.role.in_(_LEADER_ROLES),
        *(User.roles.contains([r.value]) for r in _LEADER_ROLES),
    )


async def load_rows(db: AsyncSession) -> list[NewPersonRow]:
    pending = list(
        (
            await db.scalars(
                select(User).where(
                    User.is_active.is_(True), User.setup_pending_since.is_not(None)
                )
            )
        ).all()
    )
    recruiter_base = (
        User.is_active.is_(True),
        operator_clause(),
        _not_leader(),
        User.setup_pending_since.is_(None),
    )
    no_categories = list(
        (
            await db.scalars(
                select(User).where(
                    *recruiter_base,
                    User.allocation_excluded.is_(False),
                    ~exists().where(UserCompetenceCategory.user_id == User.id),
                )
            )
        ).all()
    )
    no_manager: list[User] = []
    if program_enabled():
        no_manager = list(
            (
                await db.scalars(
                    select(User)
                    .join(EmployeeProfile, EmployeeProfile.user_id == User.id)
                    .where(
                        *recruiter_base,
                        EmployeeProfile.manager_user_id.is_(None),
                        EmployeeProfile.employment_status != "exited",
                    )
                )
            ).all()
        )
    rows: dict[int, NewPersonRow] = {}
    for user in pending:
        rows[user.id] = NewPersonRow(
            user_id=user.id,
            name=user.name,
            email=user.email,
            since=user.setup_pending_since,
            needs_decision=True,
            missing=(),
        )
    missing: dict[int, list[str]] = {}
    people: dict[int, User] = {}
    for kind, users in (
        (MISSING_CATEGORIES, no_categories),
        (MISSING_MANAGER, no_manager),
    ):
        for user in users:
            missing.setdefault(user.id, []).append(kind)
            people[user.id] = user
    for user_id, kinds in missing.items():
        user = people[user_id]
        rows[user_id] = NewPersonRow(
            user_id=user.id,
            name=user.name,
            email=user.email,
            since=user.created_at,
            needs_decision=False,
            missing=tuple(kinds),
        )
    # Decyzje na górze, potem najdłużej czekający.
    return sorted(rows.values(), key=lambda r: (not r.needs_decision, r.since))


async def load_rows_safely(db: AsyncSession) -> Optional[list[NewPersonRow]]:
    """Lista dla pulpitu: awaria = ``None`` + log (nie 500 całej kolejki
    i nie „nic nie czeka”). Savepoint, bo sesja żądania jedzie dalej."""
    try:
        async with db.begin_nested():
            return await load_rows(db)
    except Exception:  # noqa: BLE001
        logger.exception("new_person_setup: nie udało się policzyć listy")
        return None
