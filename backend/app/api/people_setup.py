"""Okno „Ustaw nową osobę” — decyzje Artura z 28.10.2026 (0609).

Head of Recruitment i admin decydują o koncie po pierwszym logowaniu przez
Microsoft i uzupełniają rekruterowi, czego mu brakuje — w jednym zapisie:

- rola: Head of Recruitment może tylko zmienić „Konsultanta/Kontraktora” na
  Rekrutera (zmiana idzie tą samą ścieżką co w „Osoby i role”: onboarding,
  wylogowanie, wpis w historii); Delivery Leada i inne role nadaje admin
  w „Osoby i role”,
- kategorie kompetencji (1. priorytet jeden, 2. dowolnie),
- przełożony w „Ludziach w NEXUSIE”: HoR wskazuje siebie albo innego
  kierownika rekrutacji, admin — dowolną osobę.

Lista do ustawienia: ``services/new_person_setup.py`` (w ``/api/board-tasks``).
"""

from datetime import datetime, timezone
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api import admin as admin_api
from app.api.competence_team import assign_category
from app.api.deps import HeadOfRecruitmentPlus
from app.api.section_access import PIPELINE_SECTION_DEPENDENCIES
from app.core.database import get_db
from app.models.activity import Activity
from app.models.hr_profile import EmployeeProfile
from app.models.user import User, UserRole
from app.services.hr import account_profiles, people
from app.services.hr import structure as hr_structure
from app.services.hr.program import program_enabled

router = APIRouter(dependencies=PIPELINE_SECTION_DEPENDENCIES)

_SET_BY_ADMIN = "Tę osobę ustawia admin w „Osoby i role”."
_LEADER_ROLES = (UserRole.admin, UserRole.head_of_recruitment)


class ManagerOption(BaseModel):
    id: int
    name: str


class SetupOptions(BaseModel):
    # Przełożony żyje w „Ludziach w NEXUSIE” — bez programu kroku nie ma.
    manager_enabled: bool
    managers: list[ManagerOption]


class SetupPayload(BaseModel):
    decision: Literal["recruiter", "employee"]
    first_category_id: Optional[int] = Field(None, gt=0)
    second_category_ids: list[int] = Field(default_factory=list, max_length=20)
    manager_user_id: Optional[int] = Field(None, gt=0)


def _leader_clause():
    return or_(
        User.role == UserRole.head_of_recruitment,
        User.roles.contains([UserRole.head_of_recruitment.value]),
    )


@router.get("/options", response_model=SetupOptions)
async def setup_options(
    current_user: HeadOfRecruitmentPlus, db: AsyncSession = Depends(get_db)
) -> SetupOptions:
    leaders = list(
        (
            await db.scalars(
                select(User)
                .where(User.is_active.is_(True), _leader_clause())
                .order_by(User.name)
            )
        ).all()
    )
    if all(u.id != current_user.id for u in leaders):
        leaders.insert(0, current_user)
    return SetupOptions(
        manager_enabled=program_enabled(),
        managers=[ManagerOption(id=u.id, name=u.name) for u in leaders],
    )


async def _set_manager(
    db: AsyncSession, *, actor: User, target: User, manager_user_id: int
) -> None:
    if not program_enabled():
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "„Ludzie w NEXUSIE” są wyłączone — przełożonego nie da się ustawić.",
        )
    if not actor.has_role(UserRole.admin) and manager_user_id != actor.id:
        manager = await db.get(User, manager_user_id)
        if manager is None or not manager.has_role(UserRole.head_of_recruitment):
            raise HTTPException(
                status.HTTP_403_FORBIDDEN,
                "Jako przełożonego wskaż siebie albo innego kierownika rekrutacji.",
            )
    profile = await account_profiles.ensure_profile(
        db, target, actor_id=actor.id, source="people_setup"
    )
    if profile is None:
        profile = await db.scalar(
            select(EmployeeProfile).where(EmployeeProfile.user_id == target.id)
        )
    # Przegląd kodu 28.10.2026: HoR ustawia przełożonego tylko osobie, która
    # go nie ma (albo nowej) — przejęcie cudzego zespołu dawałoby wgląd
    # w godziny i premie (`hr/payroll_access.py`); przepięcia robi Kadry/admin.
    if (
        not actor.has_role(UserRole.admin)
        and target.setup_pending_since is None
        and profile is not None
        and profile.manager_user_id is not None
    ):
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "Ta osoba ma już przełożonego — zmienia go Kadry albo admin w „Strukturze”.",
        )
    try:
        await hr_structure.reassign(
            db, user_ids=[target.id], manager_user_id=manager_user_id, actor=actor
        )
    except people.HrPeopleError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc
    except LookupError as exc:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "Ta osoba nie ma kartoteki w „Ludziach w NEXUSIE” — ustaw przełożonego w „Strukturze”.",
        ) from exc


@router.post("/{user_id}")
async def apply_setup(
    user_id: int,
    payload: SetupPayload,
    current_user: HeadOfRecruitmentPlus,
    db: AsyncSession = Depends(get_db),
) -> dict:
    if user_id == current_user.id:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY, "Swojego konta tu nie ustawiasz."
        )
    target = await db.scalar(select(User).where(User.id == user_id).with_for_update())
    if target is None or not target.is_active:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Nie ma takiej aktywnej osoby.")
    employee_only = [str(r) for r in (target.roles or [])] == [UserRole.employee.value]
    if not current_user.has_role(UserRole.admin):
        # Przegląd kodu 28.10.2026: HoR decyduje o NOWYM koncie i uzupełnia
        # rekrutera — nie promuje konsultanta, którego ktoś świadomie zostawił,
        # i nie rusza kont adminów ani innych kierowników.
        if target.has_any_role(*_LEADER_ROLES):
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, _SET_BY_ADMIN)
        if employee_only and target.setup_pending_since is None:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, _SET_BY_ADMIN)

    if payload.decision == "employee":
        if not employee_only:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, _SET_BY_ADMIN)
        target.setup_pending_since = None
        db.add(
            Activity(
                entity_type="user",
                entity_id=target.id,
                action="new_person_setup_decided",
                user_id=current_user.id,
                details={"decision": "employee", "target_email": target.email},
            )
        )
        await db.commit()
        return {"ok": True, "decision": "employee"}

    if employee_only:
        # Ta sama ścieżka co „Osoby i role”: onboarding rekrutera, nowa wersja
        # uprawnień (wylogowanie), wpisy role_changed / roles_changed.
        await admin_api.update_user(
            user_id=target.id,
            data=admin_api.AdminUserUpdate(
                role=UserRole.recruiter, roles=[UserRole.recruiter]
            ),
            _admin=current_user,
            db=db,
        )
    elif not target.has_role(UserRole.recruiter):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, _SET_BY_ADMIN)

    categories: list[tuple[int, Literal[1, 2]]] = []
    if payload.first_category_id:
        categories.append((payload.first_category_id, 1))
    for category_id in dict.fromkeys(payload.second_category_ids):
        if category_id != payload.first_category_id:
            categories.append((category_id, 2))
    for category_id, priority in categories:
        await assign_category(
            db,
            user_id=target.id,
            category_id=category_id,
            priority=priority,
            actor=current_user,
        )
    if payload.manager_user_id is not None:
        await _set_manager(
            db,
            actor=current_user,
            target=target,
            manager_user_id=payload.manager_user_id,
        )

    target.setup_pending_since = None
    db.add(
        Activity(
            entity_type="user",
            entity_id=target.id,
            action="new_person_setup_decided",
            user_id=current_user.id,
            details={
                "decision": "recruiter",
                "role_granted": employee_only,
                "categories": [
                    {"competence_category_id": c, "priority": p} for c, p in categories
                ],
                "manager_user_id": payload.manager_user_id,
                "decided_at": datetime.now(timezone.utc).isoformat(),
                "target_email": target.email,
            },
        )
    )
    await db.commit()
    return {"ok": True, "decision": "recruiter", "role_granted": employee_only}
