"""Router `/api/team-structure/*` — macierze organizacyjne zespołu rekrutacji.

Ported pattern z InfraReportera:
  - sourcerzy × kategoria kompetencji (1st/2nd priority)
  - TAC → DL (1:1) + LinkedIn farming (M:N)
  - DL → klienci (M:N z flagą Head)

CUD wymaga `HeadOfRecruitmentPlus` (admin + head_of_recruitment).
GET dostępne dla `CurrentUser` (wszyscy zalogowani).
"""

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import OperationalUser, CurrentUser, HeadOfRecruitmentPlus
from app.core.database import get_db
from app.models.client import Client
from app.models.competence_category import (
    CompetenceCategory,
    UserCompetenceCategory,
)
from app.models.job import Job, JobStatus
from app.models.recruitment_pipeline import CandidateStage, PipelineStage
from app.models.team_structure import (
    DeliveryLeadClientAssignment,
    TacDeliveryLeadAssignment,
    TacLinkedInFarming,
)
from app.models.user import User, UserRole
from app.schemas.team_structure import (
    AssignDlClientPayload,
    AssignSourcerPayload,
    AssignTacLinkedInFarmingPayload,
    AssignTacToDlPayload,
    CategoryBrief,
    ClientOfDl,
    DlClientsRow,
    DlWithTacsRow,
    MyTeamRow,
    OperatorCompetencesUpdate,
    SourcerCategoryRow,
    SourcerInCategory,
    TacOfDl,
    TeamStructureSummary,
    UserBrief,
)
from app.services.authorization_invalidation import (
    invalidate_delivery_lead_scope_for_users,
)

router = APIRouter()

_COMPETENCE_OPERATOR_ROLES = {
    UserRole.sourcer,
    UserRole.tac,
    UserRole.recruiter,
}


def _has_any_role_clause(*roles: UserRole):
    """SQL equivalent of ``User.has_any_role`` for hybrid-role listings."""

    return or_(
        User.role.in_(roles),
        *(User.roles.contains([role.value]) for role in roles),
    )


def _user_brief(u: User) -> UserBrief:
    return UserBrief(id=u.id, name=u.name, email=u.email)


def _category_brief(c: CompetenceCategory) -> CategoryBrief:
    return CategoryBrief(id=c.id, slug=c.slug, name_pl=c.name_pl, name_en=c.name_en)


# ─────────────────────────────────────────────────────────────────────────
# 1. Sourcer × Category (rozszerzenie user_competence_categories o priority)
# ─────────────────────────────────────────────────────────────────────────


@router.get("/sourcer-categories", response_model=list[SourcerCategoryRow])
async def list_sourcer_categories(
    _user: OperationalUser,
    db: AsyncSession = Depends(get_db),
):
    """Zwraca listę: [kategoria → {1st priority sourcers, 2nd priority sourcers}]."""
    cats_q = (
        select(CompetenceCategory)
        .where(CompetenceCategory.is_active == True)  # noqa: E712
        .order_by(CompetenceCategory.display_order, CompetenceCategory.name_pl)
    )
    cats = (await db.execute(cats_q)).scalars().all()

    rows_q = (
        select(
            UserCompetenceCategory.competence_category_id,
            UserCompetenceCategory.priority,
            UserCompetenceCategory.is_primary,
            User.id,
            User.name,
            User.email,
            User.role,
        )
        .join(User, UserCompetenceCategory.user_id == User.id)
        .where(
            User.is_active == True,  # noqa: E712
            _has_any_role_clause(*_COMPETENCE_OPERATOR_ROLES),
        )
    )
    rows = (await db.execute(rows_q)).all()

    by_category: dict[int, dict[str, list[SourcerInCategory]]] = {}
    for r in rows:
        bucket = by_category.setdefault(
            r.competence_category_id, {"first": [], "second": []}
        )
        entry = SourcerInCategory(
            user_id=r.id,
            name=r.name,
            email=r.email,
            priority=r.priority,
            is_primary=r.is_primary,
        )
        if r.priority == 1:
            bucket["first"].append(entry)
        elif r.priority == 2:
            bucket["second"].append(entry)

    return [
        SourcerCategoryRow(
            category=_category_brief(c),
            first_priority=by_category.get(c.id, {}).get("first", []),
            second_priority=by_category.get(c.id, {}).get("second", []),
        )
        for c in cats
    ]


@router.post(
    "/sourcer-categories",
    status_code=status.HTTP_201_CREATED,
)
async def assign_sourcer_to_category(
    payload: AssignSourcerPayload,
    _user: HeadOfRecruitmentPlus,
    db: AsyncSession = Depends(get_db),
):
    user = (
        await db.execute(select(User).where(User.id == payload.user_id))
    ).scalar_one_or_none()
    if user is None:
        raise HTTPException(404, "User not found")
    if not user.is_active or not user.has_any_role(*_COMPETENCE_OPERATOR_ROLES):
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "User must be an active Sourcer, TAC or Recruiter",
        )
    cat = (
        await db.execute(
            select(CompetenceCategory).where(
                CompetenceCategory.id == payload.competence_category_id
            )
        )
    ).scalar_one_or_none()
    if cat is None:
        raise HTTPException(404, "Category not found")
    if not cat.is_active:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Category is inactive")

    assignments = list(
        (
            await db.execute(
                select(UserCompetenceCategory)
                .where(UserCompetenceCategory.user_id == payload.user_id)
                .order_by(UserCompetenceCategory.id)
                .with_for_update()
            )
        )
        .scalars()
        .all()
    )

    # Upsert na (user_id, competence_category_id).
    existing = next(
        (
            row
            for row in assignments
            if row.competence_category_id == payload.competence_category_id
        ),
        None,
    )

    if payload.priority == 1:
        for row in assignments:
            if row is not existing and row.priority == 1:
                row.priority = 2
                row.is_primary = False
        # Flush demotion before promotion to satisfy the partial unique index.
        await db.flush()
    elif existing is not None and existing.priority == 1:
        if any(row is not existing for row in assignments):
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                "Promote another competence atomically before demoting the primary",
            )
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "An active operator must retain one primary competence",
        )
    elif not any(row.priority == 1 for row in assignments):
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "Select a primary competence before adding secondary competences",
        )

    if existing:
        existing.priority = payload.priority
        existing.is_primary = payload.priority == 1
    else:
        db.add(
            UserCompetenceCategory(
                user_id=payload.user_id,
                competence_category_id=payload.competence_category_id,
                priority=payload.priority,
                is_primary=(payload.priority == 1),
            )
        )
    await db.commit()
    return {"ok": True}


@router.put("/operators/{user_id}/competences")
async def replace_operator_competences(
    user_id: int,
    payload: OperatorCompetencesUpdate,
    _user: HeadOfRecruitmentPlus,
    db: AsyncSession = Depends(get_db),
):
    """Replace primary and secondary slots in one locked transaction."""

    secondary_ids = list(dict.fromkeys(payload.secondary_competence_category_ids))
    primary_id = payload.primary_competence_category_id
    if primary_id in secondary_ids:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "Primary competence cannot also be secondary",
        )

    user = (
        await db.execute(select(User).where(User.id == user_id).with_for_update())
    ).scalar_one_or_none()
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "User not found")
    if not user.is_active or not user.has_any_role(*_COMPETENCE_OPERATOR_ROLES):
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "User must be an active Sourcer, TAC or Recruiter",
        )

    requested_ids = [primary_id, *secondary_ids]
    categories = list(
        (
            await db.execute(
                select(CompetenceCategory).where(
                    CompetenceCategory.id.in_(requested_ids),
                    CompetenceCategory.is_active.is_(True),
                )
            )
        )
        .scalars()
        .all()
    )
    if {category.id for category in categories} != set(requested_ids):
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "Every selected competence must exist and be active",
        )

    existing_rows = list(
        (
            await db.execute(
                select(UserCompetenceCategory)
                .where(UserCompetenceCategory.user_id == user_id)
                .order_by(UserCompetenceCategory.id)
                .with_for_update()
            )
        )
        .scalars()
        .all()
    )
    by_category = {row.competence_category_id: row for row in existing_rows}

    # Demote first so the partial unique index is never transiently violated.
    for row in existing_rows:
        row.priority = 2
        row.is_primary = False
    await db.flush()

    wanted = set(requested_ids)
    for row in existing_rows:
        if row.competence_category_id not in wanted:
            await db.delete(row)

    primary_row = by_category.get(primary_id)
    if primary_row is None:
        primary_row = UserCompetenceCategory(
            user_id=user_id,
            competence_category_id=primary_id,
            priority=1,
            is_primary=True,
        )
        db.add(primary_row)
    else:
        primary_row.priority = 1
        primary_row.is_primary = True

    for category_id in secondary_ids:
        row = by_category.get(category_id)
        if row is None:
            db.add(
                UserCompetenceCategory(
                    user_id=user_id,
                    competence_category_id=category_id,
                    priority=2,
                    is_primary=False,
                )
            )
        else:
            row.priority = 2
            row.is_primary = False

    await db.commit()
    return {
        "ok": True,
        "user_id": user_id,
        "primary_competence_category_id": primary_id,
        "secondary_competence_category_ids": secondary_ids,
    }


@router.delete("/sourcer-categories/{assignment_id}")
async def remove_sourcer_from_category(
    assignment_id: int,
    _user: HeadOfRecruitmentPlus,
    db: AsyncSession = Depends(get_db),
):
    row = (
        await db.execute(
            select(UserCompetenceCategory).where(
                UserCompetenceCategory.id == assignment_id
            )
        )
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(404, "Assignment not found")
    if row.priority == 1:
        other = await db.scalar(
            select(UserCompetenceCategory.id).where(
                UserCompetenceCategory.user_id == row.user_id,
                UserCompetenceCategory.id != row.id,
            )
        )
        if other is not None:
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                "Promote another competence before removing the primary",
            )
    await db.delete(row)
    await db.commit()
    return {"ok": True}


# ─────────────────────────────────────────────────────────────────────────
# 2. TAC → DL + LinkedIn farming
# ─────────────────────────────────────────────────────────────────────────


@router.get("/tac-delivery-leads", response_model=list[DlWithTacsRow])
async def list_tac_delivery_leads(
    _user: OperationalUser,
    db: AsyncSession = Depends(get_db),
):
    """Zwraca DL-i z listą przypisanych TAC-ów + ich LinkedIn farming kategorie."""
    dls = (
        (
            await db.execute(
                select(User)
                .where(
                    _has_any_role_clause(UserRole.delivery_lead),
                    User.is_active == True,  # noqa: E712
                )
                .order_by(User.name)
            )
        )
        .scalars()
        .all()
    )

    # Wszystkie przypisania TAC → DL
    tac_rows = (
        await db.execute(
            select(
                TacDeliveryLeadAssignment.delivery_lead_user_id,
                User.id,
                User.name,
                User.email,
            ).join(User, TacDeliveryLeadAssignment.tac_user_id == User.id)
        )
    ).all()

    # LinkedIn farming per TAC
    farm_rows = (
        await db.execute(
            select(
                TacLinkedInFarming.tac_user_id,
                CompetenceCategory.id,
                CompetenceCategory.slug,
                CompetenceCategory.name_pl,
                CompetenceCategory.name_en,
            ).join(
                CompetenceCategory,
                TacLinkedInFarming.competence_category_id == CompetenceCategory.id,
            )
        )
    ).all()
    farm_map: dict[int, list[CategoryBrief]] = {}
    for fr in farm_rows:
        farm_map.setdefault(fr.tac_user_id, []).append(
            CategoryBrief(
                id=fr.id, slug=fr.slug, name_pl=fr.name_pl, name_en=fr.name_en
            )
        )

    by_dl: dict[int, list[TacOfDl]] = {}
    for tr in tac_rows:
        by_dl.setdefault(tr.delivery_lead_user_id, []).append(
            TacOfDl(
                user_id=tr.id,
                name=tr.name,
                email=tr.email,
                linkedin_farming=farm_map.get(tr.id, []),
            )
        )

    return [
        DlWithTacsRow(delivery_lead=_user_brief(dl), tacs=by_dl.get(dl.id, []))
        for dl in dls
    ]


@router.post("/tac-delivery-leads", status_code=status.HTTP_201_CREATED)
async def assign_tac_to_dl(
    payload: AssignTacToDlPayload,
    _user: HeadOfRecruitmentPlus,
    db: AsyncSession = Depends(get_db),
):
    tac = (
        await db.execute(select(User).where(User.id == payload.tac_user_id))
    ).scalar_one_or_none()
    if tac is None or not tac.has_role(UserRole.tac):
        raise HTTPException(400, "tac_user_id must reference a user with role=tac")
    dl = (
        await db.execute(select(User).where(User.id == payload.delivery_lead_user_id))
    ).scalar_one_or_none()
    if dl is None or not dl.has_role(UserRole.delivery_lead):
        raise HTTPException(
            400,
            "delivery_lead_user_id must reference a user with role=delivery_lead",
        )

    existing = (
        await db.execute(
            select(TacDeliveryLeadAssignment).where(
                TacDeliveryLeadAssignment.tac_user_id == payload.tac_user_id
            )
        )
    ).scalar_one_or_none()
    if existing:
        existing.delivery_lead_user_id = payload.delivery_lead_user_id
    else:
        db.add(
            TacDeliveryLeadAssignment(
                tac_user_id=payload.tac_user_id,
                delivery_lead_user_id=payload.delivery_lead_user_id,
            )
        )
    await db.commit()
    return {"ok": True}


@router.delete("/tac-delivery-leads/{tac_user_id}")
async def unassign_tac_from_dl(
    tac_user_id: int,
    _user: HeadOfRecruitmentPlus,
    db: AsyncSession = Depends(get_db),
):
    row = (
        await db.execute(
            select(TacDeliveryLeadAssignment).where(
                TacDeliveryLeadAssignment.tac_user_id == tac_user_id
            )
        )
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(404, "Assignment not found")
    await db.delete(row)
    await db.commit()
    return {"ok": True}


@router.post("/tac-linkedin-farming", status_code=status.HTTP_201_CREATED)
async def assign_tac_linkedin_farming(
    payload: AssignTacLinkedInFarmingPayload,
    _user: HeadOfRecruitmentPlus,
    db: AsyncSession = Depends(get_db),
):
    existing = (
        await db.execute(
            select(TacLinkedInFarming).where(
                TacLinkedInFarming.tac_user_id == payload.tac_user_id,
                TacLinkedInFarming.competence_category_id
                == payload.competence_category_id,
            )
        )
    ).scalar_one_or_none()
    if existing:
        return {"ok": True, "already_exists": True}
    db.add(
        TacLinkedInFarming(
            tac_user_id=payload.tac_user_id,
            competence_category_id=payload.competence_category_id,
        )
    )
    await db.commit()
    return {"ok": True}


@router.delete("/tac-linkedin-farming/{assignment_id}")
async def remove_tac_linkedin_farming(
    assignment_id: int,
    _user: HeadOfRecruitmentPlus,
    db: AsyncSession = Depends(get_db),
):
    row = (
        await db.execute(
            select(TacLinkedInFarming).where(TacLinkedInFarming.id == assignment_id)
        )
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(404, "Assignment not found")
    await db.delete(row)
    await db.commit()
    return {"ok": True}


# ─────────────────────────────────────────────────────────────────────────
# 3. DL → Clients (z flagą is_head)
# ─────────────────────────────────────────────────────────────────────────


@router.get("/dl-clients", response_model=list[DlClientsRow])
async def list_dl_clients(
    _user: OperationalUser,
    db: AsyncSession = Depends(get_db),
):
    """Return active DLs with their client assignments.

    Deduplication: each person may have two active accounts after the
    @b2bnetwork.pl → @inframinds.eu domain migration (legacy + SSO).
    Group by normalized name, prefer the account with more client
    assignments (tie-break: higher user_id = newer @inframinds.eu account),
    and merge client lists across duplicates so no assignment is lost.
    """
    dls = (
        (
            await db.execute(
                select(User)
                .where(
                    _has_any_role_clause(UserRole.delivery_lead),
                    User.is_active == True,  # noqa: E712
                )
                .order_by(User.name)
            )
        )
        .scalars()
        .all()
    )

    rows = (
        await db.execute(
            select(
                DeliveryLeadClientAssignment.delivery_lead_user_id,
                DeliveryLeadClientAssignment.is_head,
                Client.id,
                Client.name,
            )
            .join(Client, DeliveryLeadClientAssignment.client_id == Client.id)
            .order_by(Client.name)
        )
    ).all()

    by_dl: dict[int, list[ClientOfDl]] = {}
    for r in rows:
        by_dl.setdefault(r.delivery_lead_user_id, []).append(
            ClientOfDl(id=r.id, name=r.name, is_head=r.is_head)
        )

    def _norm_name(name: str) -> str:
        # Strip "(DL)"/"(TAC)" suffix tags that some @inframinds.eu names carry
        # then case-fold so "Marlena Rosol" == "Marlena Rosół (DL)".
        cleaned = name.split("(")[0].strip().lower()
        # Drop Polish diacritics so display variants merge (rosol == rosół).
        translate = str.maketrans("ąćęłńóśźż", "acelnoszz")
        return cleaned.translate(translate)

    # Group candidates by normalized name; pick the canonical row.
    groups: dict[str, list[User]] = {}
    for dl in dls:
        groups.setdefault(_norm_name(dl.name), []).append(dl)

    deduped: list[DlClientsRow] = []
    for siblings in groups.values():
        # Canonical row = the one with most clients (ties broken by highest
        # id, which is the newer @inframinds.eu account post-migration).
        canonical = max(
            siblings,
            key=lambda u: (len(by_dl.get(u.id, [])), u.id),
        )
        # Merge clients across all siblings, dedup by client.id.
        merged: dict[int, ClientOfDl] = {}
        for sib in siblings:
            for c in by_dl.get(sib.id, []):
                # Preserve is_head=True if any sibling marks it as head.
                if c.id in merged:
                    merged[c.id] = ClientOfDl(
                        id=c.id,
                        name=c.name,
                        is_head=merged[c.id].is_head or c.is_head,
                    )
                else:
                    merged[c.id] = c
        deduped.append(
            DlClientsRow(
                delivery_lead=_user_brief(canonical),
                clients=sorted(merged.values(), key=lambda c: c.name),
            )
        )

    deduped.sort(key=lambda r: r.delivery_lead.name)
    return deduped


@router.post("/dl-clients", status_code=status.HTTP_201_CREATED)
async def assign_dl_to_client(
    payload: AssignDlClientPayload,
    _user: HeadOfRecruitmentPlus,
    db: AsyncSession = Depends(get_db),
):
    dl = (
        await db.execute(select(User).where(User.id == payload.delivery_lead_user_id))
    ).scalar_one_or_none()
    if dl is None or not dl.has_role(UserRole.delivery_lead):
        raise HTTPException(400, "must reference role=delivery_lead")

    changed_delivery_lead_ids: set[int] = set()

    # Jeśli is_head=True, zabezpieczamy przed wieloma headami na klienta.
    if payload.is_head:
        existing_head = (
            await db.execute(
                select(DeliveryLeadClientAssignment).where(
                    DeliveryLeadClientAssignment.client_id == payload.client_id,
                    DeliveryLeadClientAssignment.is_head == True,  # noqa: E712
                    DeliveryLeadClientAssignment.delivery_lead_user_id
                    != payload.delivery_lead_user_id,
                )
            )
        ).scalar_one_or_none()
        if existing_head:
            existing_head.is_head = False
            changed_delivery_lead_ids.add(existing_head.delivery_lead_user_id)

    existing = (
        await db.execute(
            select(DeliveryLeadClientAssignment).where(
                DeliveryLeadClientAssignment.delivery_lead_user_id
                == payload.delivery_lead_user_id,
                DeliveryLeadClientAssignment.client_id == payload.client_id,
            )
        )
    ).scalar_one_or_none()
    if existing:
        if existing.is_head != payload.is_head:
            existing.is_head = payload.is_head
            changed_delivery_lead_ids.add(existing.delivery_lead_user_id)
    else:
        db.add(
            DeliveryLeadClientAssignment(
                delivery_lead_user_id=payload.delivery_lead_user_id,
                client_id=payload.client_id,
                is_head=payload.is_head,
            )
        )
        changed_delivery_lead_ids.add(payload.delivery_lead_user_id)
    if changed_delivery_lead_ids:
        await invalidate_delivery_lead_scope_for_users(
            db,
            changed_delivery_lead_ids,
        )
    await db.commit()
    return {"ok": True}


@router.put("/dl-clients/{assignment_id}/toggle-head")
async def toggle_dl_client_head(
    assignment_id: int,
    _user: HeadOfRecruitmentPlus,
    db: AsyncSession = Depends(get_db),
):
    row = (
        await db.execute(
            select(DeliveryLeadClientAssignment).where(
                DeliveryLeadClientAssignment.id == assignment_id
            )
        )
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(404, "Assignment not found")

    if not row.is_head:
        # Odznacz poprzedniego heada dla tego klienta.
        prev_head = (
            await db.execute(
                select(DeliveryLeadClientAssignment).where(
                    DeliveryLeadClientAssignment.client_id == row.client_id,
                    DeliveryLeadClientAssignment.is_head == True,  # noqa: E712
                    DeliveryLeadClientAssignment.id != assignment_id,
                )
            )
        ).scalar_one_or_none()
        changed_delivery_lead_ids = {row.delivery_lead_user_id}
        if prev_head:
            prev_head.is_head = False
            changed_delivery_lead_ids.add(prev_head.delivery_lead_user_id)
    else:
        changed_delivery_lead_ids = {row.delivery_lead_user_id}
    row.is_head = not row.is_head
    await invalidate_delivery_lead_scope_for_users(db, changed_delivery_lead_ids)
    await db.commit()
    return {"ok": True, "is_head": row.is_head}


@router.delete("/dl-clients/{assignment_id}")
async def remove_dl_client(
    assignment_id: int,
    _user: HeadOfRecruitmentPlus,
    db: AsyncSession = Depends(get_db),
):
    row = (
        await db.execute(
            select(DeliveryLeadClientAssignment).where(
                DeliveryLeadClientAssignment.id == assignment_id
            )
        )
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(404, "Assignment not found")
    await db.delete(row)
    await invalidate_delivery_lead_scope_for_users(
        db,
        {row.delivery_lead_user_id},
    )
    await db.commit()
    return {"ok": True}


# ─────────────────────────────────────────────────────────────────────────
# 4. Summary — wszystko w jednym requeście (dla panelu Head of Recruitment)
# ─────────────────────────────────────────────────────────────────────────


@router.get("/summary", response_model=TeamStructureSummary)
async def team_structure_summary(
    _user: OperationalUser,
    db: AsyncSession = Depends(get_db),
):
    categories = await list_sourcer_categories(_user, db)
    delivery_leads = await list_tac_delivery_leads(_user, db)
    dl_clients = await list_dl_clients(_user, db)

    async def _count(role: Optional[UserRole] = None) -> int:
        q = select(func.count(User.id)).where(User.is_active == True)  # noqa: E712
        if role is not None:
            q = q.where(_has_any_role_clause(role))
        return (await db.execute(q)).scalar() or 0

    totals = {
        "sourcers": await _count(UserRole.sourcer),
        "tacs": await _count(UserRole.tac),
        "recruiters": await _count(UserRole.recruiter),
        "delivery_leads": await _count(UserRole.delivery_lead),
        "head_of_recruitment": await _count(UserRole.head_of_recruitment),
        "clients": (await db.execute(select(func.count(Client.id)))).scalar() or 0,
    }

    return TeamStructureSummary(
        categories=categories,
        delivery_leads=delivery_leads,
        dl_clients=dl_clients,
        totals=totals,
    )


# ─────────────────────────────────────────────────────────────────────────
# 5. My Team — DL Hub PR 2
# ─────────────────────────────────────────────────────────────────────────


_TERMINAL_STAGES = (
    PipelineStage.hired,
    PipelineStage.rejected,
    PipelineStage.withdrawn,
)


@router.get("/my-team", response_model=list[MyTeamRow])
async def list_my_team(
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
):
    """Lista TAC-ów raportujących do current Delivery Lead z metrykami.

    Filter: `tac_delivery_lead_assignments.delivery_lead_user_id == current_user.id`.
    Dla non-DL (recruiter/sourcer/...) zwraca pustą listę — graceful, nie 403,
    bo widok DL Hub kieruje requesty niezależnie od roli i pusta lista to
    naturalna odpowiedź dla "nie masz przypisanego zespołu".

    Metryki:
    - `active_jobs`: COUNT(distinct Job.id) gdzie tac_id=TAC AND status=published
    - `active_candidates`: COUNT(distinct candidate_id) gdzie najnowszy
      CandidateStage na jakimkolwiek aktywnym jobie TAC NIE jest terminalny
      (hired/rejected/withdrawn).
    """
    if not current_user.has_any_role(UserRole.delivery_lead, UserRole.admin):
        return []

    # 1. Wszystkie TAC-i przypisane do current DL
    assignments = (
        await db.execute(
            select(
                TacDeliveryLeadAssignment.tac_user_id,
                TacDeliveryLeadAssignment.created_at,
                User.name,
                User.email,
            )
            .join(User, User.id == TacDeliveryLeadAssignment.tac_user_id)
            .where(
                TacDeliveryLeadAssignment.delivery_lead_user_id == current_user.id,
                User.is_active == True,  # noqa: E712
            )
            .order_by(User.name)
        )
    ).all()

    if not assignments:
        return []

    tac_ids = [a.tac_user_id for a in assignments]

    # 2. Active jobs per TAC (single GROUP BY query, no N+1)
    active_jobs_rows = (
        await db.execute(
            select(Job.tac_id, func.count(Job.id).label("n"))
            .where(
                Job.tac_id.in_(tac_ids),
                Job.status == JobStatus.published,
            )
            .group_by(Job.tac_id)
        )
    ).all()
    active_jobs_map: dict[int, int] = {r.tac_id: int(r.n) for r in active_jobs_rows}

    # 3. Active candidates per TAC.
    #
    # "Active" = latest stage per (candidate, job) is non-terminal.
    # Strategia: per (candidate_id, job_id) bierzemy MAX(id) jako proxy dla
    # "latest" (id rośnie wraz z moved_at — wstawiany sekwencyjnie). Następnie
    # filtrujemy po stage != terminal i grupujemy po Job.tac_id.
    latest_per_cj = (
        select(func.max(CandidateStage.id).label("latest_id"))
        .group_by(CandidateStage.candidate_id, CandidateStage.job_id)
        .subquery()
    )
    active_cand_rows = (
        await db.execute(
            select(
                Job.tac_id,
                func.count(func.distinct(CandidateStage.candidate_id)).label("n"),
            )
            .join(Job, Job.id == CandidateStage.job_id)
            .where(
                Job.tac_id.in_(tac_ids),
                CandidateStage.id.in_(select(latest_per_cj.c.latest_id)),
                CandidateStage.stage.notin_(_TERMINAL_STAGES),
            )
            .group_by(Job.tac_id)
        )
    ).all()
    active_cand_map: dict[int, int] = {r.tac_id: int(r.n) for r in active_cand_rows}

    return [
        MyTeamRow(
            tac_user_id=a.tac_user_id,
            tac_name=a.name,
            tac_email=a.email,
            active_jobs=active_jobs_map.get(a.tac_user_id, 0),
            active_candidates=active_cand_map.get(a.tac_user_id, 0),
            assignment_created_at=a.created_at,
        )
        for a in assignments
    ]
