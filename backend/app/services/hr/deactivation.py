"""Wyłączenie konta osoby, która odeszła (dzień po ostatnim dniu pracy).

Zasady przejęte z ``app/services/compass_lifecycle.py`` (przepływ COMPASS →
NEXUS, który ten moduł zastępuje):

1. **Tylko jawna decyzja wyłącza.** Konto wyłącza wyłącznie sprawa odejścia
   prowadzona przez Kadry, w dniu ``deactivate_on`` — nie brak osoby na
   liście ani status kartoteki.
2. **Raz na sprawę.** Sprawa pamięta, że konto zamknęła (``account_closed_at``);
   admin, który włączy konto z powrotem (powrót na umowę), nie zostanie
   nadpisany przez następny przebieg — tak jak „przywrócenie w tym epizodzie
   odejścia” w przepływie Compassa.
3. **Admina wyłącza człowiek.** Konto z rolą admin zostaje włączone
   (``skipped_admin``) — admin jest jedyną osobą, która cofnie błędną
   deaktywację.
4. **Żadnej masowej deaktywacji.** Przebieg, który miałby wyłączyć więcej niż
   ``MAX_DEACTIVATIONS_PER_RUN`` kont, nie wyłącza żadnego
   (``mass_exit_suspected``); Kadry wyłączają je wtedy po jednym z ekranu
   odejścia („Wyłącz konto teraz”).
5. **Ślad.** ``Activity`` ``hr_lifecycle_deactivated`` (jak
   ``compass_lifecycle_deactivated``) i wiersz w ``hr_audit_events``.

Samo wyłączenie powtarza to, co robi ``DELETE /api/admin/users/{id}``: koniec
sesji (``authorization_version``, ``tokens_valid_after``) i unieważnienie
stałego linku kariery rekrutera.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal, Optional

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.activity import Activity
from app.models.hr_lifecycle import LifecycleCase
from app.models.hr_profile import EmployeeProfile
from app.models.invite_link import CandidateInviteLink
from app.models.user import User, UserRole
from app.services.hr import audit

#: Bezpiecznik masowego odejścia (lustro ``MASS_EXIT_MAX_PEOPLE`` Compassa).
MAX_DEACTIVATIONS_PER_RUN = 5
MASS_EXIT_ERROR = "mass_exit_suspected"
DEACTIVATION_ACTION = "hr_lifecycle_deactivated"

CloseResult = Literal["deactivated", "already_inactive", "skipped_admin"]


def mass_exit_suspected(planned: int) -> bool:
    return planned > MAX_DEACTIVATIONS_PER_RUN


async def close_account(
    db: AsyncSession,
    case: LifecycleCase,
    *,
    now: datetime,
    actor_id: Optional[int] = None,
) -> CloseResult:
    """Wyłącza konto osoby ze sprawy odejścia i zamyka kartotekę (``exited``).

    Wołający trzyma blokadę wiersza sprawy i commituje. Sprawa, która już
    zamknęła konto, nie robi tego drugi raz.
    """

    assert case.kind == "offboarding" and case.user_id is not None
    if case.account_close_result is not None:
        return case.account_close_result  # type: ignore[return-value]
    user = await db.scalar(
        select(User).where(User.id == case.user_id).with_for_update()
    )
    assert user is not None
    result: CloseResult
    if user.has_role(UserRole.admin):
        result = "skipped_admin"
    elif not user.is_active:
        result = "already_inactive"
    else:
        user.is_active = False
        user.authorization_version += 1
        user.tokens_valid_after = now
        await db.execute(
            update(CandidateInviteLink)
            .where(
                CandidateInviteLink.created_by == user.id,
                CandidateInviteLink.kind == "recruiter",
            )
            .values(revoked=True)
        )
        db.add(
            Activity(
                entity_type="user",
                entity_id=user.id,
                action=DEACTIVATION_ACTION,
                user_id=actor_id,
                details={
                    "lifecycle_case_id": case.id,
                    "last_working_day": case.last_working_day.isoformat()
                    if case.last_working_day
                    else None,
                    "source": "hr_lifecycle",
                },
            )
        )
        result = "deactivated"

    if result != "skipped_admin":
        profile = await db.scalar(
            select(EmployeeProfile).where(EmployeeProfile.user_id == user.id)
        )
        if profile is not None:
            profile.employment_status = "exited"
            profile.exited_at = now
            profile.last_working_day = case.last_working_day
            if actor_id is not None:
                profile.updated_by = actor_id
    case.account_closed_at = now
    case.account_close_result = result
    audit.record(
        db,
        actor_user_id=actor_id,
        subject_user_id=user.id,
        entity_type="lifecycle_case",
        entity_id=case.id,
        action="account_closed",
        details={"result": result},
    )
    await db.flush()
    return result
