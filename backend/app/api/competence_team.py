"""Panel „Kategorie kompetencji” w Ustawieniach (24.09.2026).

Artur sam przypisuje ludzi do czterech kategorii zespołu (1. i 2. priorytet),
oznacza konta „Poza przydziałem” i ustawia zasady automatu przydziału.
Z tych danych korzysta ``services/request_allocation``.

Osobny router zamiast poluzowania ``/api/team-structure/sourcer-categories``:
tamte trasy wymagają, żeby osoba z kategorią zawsze miała główną, a panel
musi pozwolić zdjąć kogoś z 1. priorytetu i zostawić go tylko w 2. albo bez
kategorii. Stare trasy i ich testy zostają nietknięte.

Zapis i odczyt: admin + Head of Recruitment (``HeadOfRecruitmentPlus``).
"""

from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import HeadOfRecruitmentPlus
from app.api.section_access import PIPELINE_SECTION_DEPENDENCIES
from app.core.database import get_db
from app.models.activity import Activity
from app.models.competence_category import CompetenceCategory, UserCompetenceCategory
from app.models.job import Job, JobStatus
from app.models.user import User, UserRole
from app.services.request_allocation_rules import (
    load_rules,
    save_rules,
    validate_rules,
)

router = APIRouter(dependencies=PIPELINE_SECTION_DEPENDENCIES)

# Kto może dostać request: role operacyjne, także jako druga rola Delivery
# Leada (decyzja Artura 24.09.2026).
OPERATOR_ROLES = (UserRole.recruiter, UserRole.sourcer, UserRole.tac)


def operator_clause():
    return or_(
        User.role.in_(OPERATOR_ROLES),
        *(User.roles.contains([role.value]) for role in OPERATOR_ROLES),
    )


class TeamPerson(BaseModel):
    user_id: int
    name: str
    roles: list[str]
    allocation_excluded: bool
    assignment_id: Optional[int] = None


class TeamCategory(BaseModel):
    id: int
    slug: str
    name: str
    requests_searching: int
    first: list[TeamPerson]
    second: list[TeamPerson]


class TeamRules(BaseModel):
    sourcer_threshold: int
    review_time: str


class CompetenceTeamResponse(BaseModel):
    categories: list[TeamCategory]
    unassigned: list[TeamPerson]
    excluded: list[TeamPerson]
    people: list[TeamPerson]
    rules: TeamRules


class AssignmentPayload(BaseModel):
    user_id: int = Field(gt=0)
    competence_category_id: int = Field(gt=0)
    priority: Literal[1, 2]


class AllocationPayload(BaseModel):
    excluded: bool


def _roles(user: User) -> list[str]:
    values = {r.value if hasattr(r, "value") else str(r) for r in (user.roles or [])}
    values.add(user.role.value if hasattr(user.role, "value") else str(user.role))
    return sorted(values)


def _person(user: User, assignment_id: Optional[int] = None) -> TeamPerson:
    return TeamPerson(
        user_id=user.id,
        name=user.name,
        roles=_roles(user),
        allocation_excluded=bool(user.allocation_excluded),
        assignment_id=assignment_id,
    )


async def _operators(db: AsyncSession) -> list[User]:
    return list(
        (
            await db.scalars(
                select(User)
                .where(User.is_active.is_(True), operator_clause())
                .order_by(User.name)
            )
        ).all()
    )


@router.get("", response_model=CompetenceTeamResponse)
async def get_competence_team(
    _user: HeadOfRecruitmentPlus, db: AsyncSession = Depends(get_db)
) -> CompetenceTeamResponse:
    categories = list(
        (
            await db.scalars(
                select(CompetenceCategory)
                .where(CompetenceCategory.is_active.is_(True))
                .order_by(CompetenceCategory.display_order, CompetenceCategory.id)
            )
        ).all()
    )
    people = await _operators(db)
    by_id = {p.id: p for p in people}
    rows = (
        await db.execute(
            select(
                UserCompetenceCategory.id,
                UserCompetenceCategory.user_id,
                UserCompetenceCategory.competence_category_id,
                UserCompetenceCategory.priority,
            ).where(UserCompetenceCategory.user_id.in_(list(by_id) or [0]))
        )
    ).all()
    searching = dict(
        (
            await db.execute(
                select(Job.competence_category_id, func.count(Job.id))
                .where(
                    Job.status == JobStatus.published,
                    Job.work_state == "searching",
                    Job.champion_found_at.is_(None),
                )
                .group_by(Job.competence_category_id)
            )
        ).all()
    )
    grouped: dict[int, dict[int, list[TeamPerson]]] = {}
    assigned: set[int] = set()
    for assignment_id, user_id, category_id, priority in rows:
        grouped.setdefault(category_id, {1: [], 2: []})[priority].append(
            _person(by_id[user_id], assignment_id)
        )
        assigned.add(user_id)
    for bucket in grouped.values():
        for people_list in bucket.values():
            people_list.sort(key=lambda p: p.name)
    rules = await load_rules(db)
    return CompetenceTeamResponse(
        categories=[
            TeamCategory(
                id=c.id,
                slug=c.slug,
                name=c.name_pl,
                requests_searching=int(searching.get(c.id, 0)),
                first=grouped.get(c.id, {}).get(1, []),
                second=grouped.get(c.id, {}).get(2, []),
            )
            for c in categories
        ],
        unassigned=[
            _person(p)
            for p in people
            if p.id not in assigned and not p.allocation_excluded
        ],
        excluded=[_person(p) for p in people if p.allocation_excluded],
        people=[_person(p) for p in people],
        rules=TeamRules(**rules.as_dict()),
    )


@router.put("/assignments", status_code=status.HTTP_200_OK)
async def put_assignment(
    payload: AssignmentPayload,
    current_user: HeadOfRecruitmentPlus,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Dodaj osobę do kategorii albo zmień jej priorytet w tej kategorii.

    1. priorytet jest jeden na osobę (częściowy UNIQUE): nadanie go w nowej
    kategorii przenosi dotychczasową główną na 2. priorytet.
    """
    user = await db.scalar(
        select(User).where(User.id == payload.user_id).with_for_update()
    )
    if user is None or not user.is_active:
        raise HTTPException(404, "Nie ma takiej aktywnej osoby.")
    if not user.has_any_role(*OPERATOR_ROLES):
        raise HTTPException(
            422, "Kategorię można nadać tylko rekruterowi, sourcerowi albo TAC."
        )
    category = await db.get(CompetenceCategory, payload.competence_category_id)
    if category is None or not category.is_active:
        raise HTTPException(404, "Nie ma takiej aktywnej kategorii.")

    rows = list(
        (
            await db.scalars(
                select(UserCompetenceCategory)
                .where(UserCompetenceCategory.user_id == user.id)
                .with_for_update()
            )
        ).all()
    )
    existing = next((r for r in rows if r.competence_category_id == category.id), None)
    if payload.priority == 1:
        for row in rows:
            if row is not existing and row.priority == 1:
                row.priority = 2
                row.is_primary = False
        await db.flush()
    if existing is None:
        db.add(
            UserCompetenceCategory(
                user_id=user.id,
                competence_category_id=category.id,
                priority=payload.priority,
                is_primary=payload.priority == 1,
            )
        )
    else:
        existing.priority = payload.priority
        existing.is_primary = payload.priority == 1
    db.add(
        Activity(
            entity_type="user",
            entity_id=user.id,
            action="competence_category_assigned",
            user_id=current_user.id,
            details={
                "competence_category_id": category.id,
                "priority": payload.priority,
            },
        )
    )
    await db.commit()
    return {"ok": True}


@router.delete("/assignments/{assignment_id}")
async def delete_assignment(
    assignment_id: int,
    current_user: HeadOfRecruitmentPlus,
    db: AsyncSession = Depends(get_db),
) -> dict:
    row = await db.get(UserCompetenceCategory, assignment_id, with_for_update=True)
    if row is None:
        raise HTTPException(404, "Nie ma takiego przypisania.")
    db.add(
        Activity(
            entity_type="user",
            entity_id=row.user_id,
            action="competence_category_removed",
            user_id=current_user.id,
            details={
                "competence_category_id": row.competence_category_id,
                "priority": row.priority,
            },
        )
    )
    await db.delete(row)
    await db.commit()
    return {"ok": True}


@router.patch("/people/{user_id}/allocation")
async def set_allocation_excluded(
    user_id: int,
    payload: AllocationPayload,
    current_user: HeadOfRecruitmentPlus,
    db: AsyncSession = Depends(get_db),
) -> dict:
    user = await db.scalar(select(User).where(User.id == user_id).with_for_update())
    if user is None:
        raise HTTPException(404, "Nie ma takiej osoby.")
    if bool(user.allocation_excluded) != payload.excluded:
        user.allocation_excluded = payload.excluded
        db.add(
            Activity(
                entity_type="user",
                entity_id=user.id,
                action="allocation_excluded_changed",
                user_id=current_user.id,
                details={"excluded": payload.excluded},
            )
        )
        await db.commit()
    return {"user_id": user.id, "allocation_excluded": payload.excluded}


@router.put("/rules", response_model=TeamRules)
async def put_rules(
    payload: TeamRules,
    current_user: HeadOfRecruitmentPlus,
    db: AsyncSession = Depends(get_db),
) -> TeamRules:
    try:
        rules = validate_rules(payload.model_dump())
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    await save_rules(db, rules, user_id=current_user.id)
    await db.commit()
    return TeamRules(**rules.as_dict())
