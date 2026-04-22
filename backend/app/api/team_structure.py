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
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentUser, HeadOfRecruitmentPlus
from app.core.database import get_db
from app.models.client import Client
from app.models.competence_category import (
    CompetenceCategory,
    UserCompetenceCategory,
)
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
    SourcerCategoryRow,
    SourcerInCategory,
    TacOfDl,
    TeamStructureSummary,
    UserBrief,
)

router = APIRouter()


def _user_brief(u: User) -> UserBrief:
    return UserBrief(id=u.id, name=u.name, email=u.email)


def _category_brief(c: CompetenceCategory) -> CategoryBrief:
    return CategoryBrief(
        id=c.id, slug=c.slug, name_pl=c.name_pl, name_en=c.name_en
    )


# ─────────────────────────────────────────────────────────────────────────
# 1. Sourcer × Category (rozszerzenie user_competence_categories o priority)
# ─────────────────────────────────────────────────────────────────────────


@router.get("/sourcer-categories", response_model=list[SourcerCategoryRow])
async def list_sourcer_categories(
    _user: CurrentUser,
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
            User.role.in_([UserRole.sourcer, UserRole.tac, UserRole.recruiter]),
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
        elif r.is_primary:
            bucket["first"].append(entry)  # backfill bez priority

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
    cat = (
        await db.execute(
            select(CompetenceCategory).where(
                CompetenceCategory.id == payload.competence_category_id
            )
        )
    ).scalar_one_or_none()
    if cat is None:
        raise HTTPException(404, "Category not found")

    # Upsert na (user_id, competence_category_id).
    existing_q = select(UserCompetenceCategory).where(
        UserCompetenceCategory.user_id == payload.user_id,
        UserCompetenceCategory.competence_category_id == payload.competence_category_id,
    )
    existing = (await db.execute(existing_q)).scalar_one_or_none()
    if existing:
        existing.priority = payload.priority
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
    await db.delete(row)
    await db.commit()
    return {"ok": True}


# ─────────────────────────────────────────────────────────────────────────
# 2. TAC → DL + LinkedIn farming
# ─────────────────────────────────────────────────────────────────────────


@router.get("/tac-delivery-leads", response_model=list[DlWithTacsRow])
async def list_tac_delivery_leads(
    _user: CurrentUser,
    db: AsyncSession = Depends(get_db),
):
    """Zwraca DL-i z listą przypisanych TAC-ów + ich LinkedIn farming kategorie."""
    dls = (
        (
            await db.execute(
                select(User)
                .where(
                    User.role == UserRole.delivery_lead,
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
    if tac is None or tac.role != UserRole.tac:
        raise HTTPException(400, "tac_user_id must reference a user with role=tac")
    dl = (
        await db.execute(
            select(User).where(User.id == payload.delivery_lead_user_id)
        )
    ).scalar_one_or_none()
    if dl is None or dl.role != UserRole.delivery_lead:
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
    _user: CurrentUser,
    db: AsyncSession = Depends(get_db),
):
    dls = (
        (
            await db.execute(
                select(User)
                .where(
                    User.role == UserRole.delivery_lead,
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

    return [
        DlClientsRow(delivery_lead=_user_brief(dl), clients=by_dl.get(dl.id, []))
        for dl in dls
    ]


@router.post("/dl-clients", status_code=status.HTTP_201_CREATED)
async def assign_dl_to_client(
    payload: AssignDlClientPayload,
    _user: HeadOfRecruitmentPlus,
    db: AsyncSession = Depends(get_db),
):
    dl = (
        await db.execute(
            select(User).where(User.id == payload.delivery_lead_user_id)
        )
    ).scalar_one_or_none()
    if dl is None or dl.role != UserRole.delivery_lead:
        raise HTTPException(400, "must reference role=delivery_lead")

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
        existing.is_head = payload.is_head
    else:
        db.add(
            DeliveryLeadClientAssignment(
                delivery_lead_user_id=payload.delivery_lead_user_id,
                client_id=payload.client_id,
                is_head=payload.is_head,
            )
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
        if prev_head:
            prev_head.is_head = False
    row.is_head = not row.is_head
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
    await db.commit()
    return {"ok": True}


# ─────────────────────────────────────────────────────────────────────────
# 4. Summary — wszystko w jednym requeście (dla panelu Head of Recruitment)
# ─────────────────────────────────────────────────────────────────────────


@router.get("/summary", response_model=TeamStructureSummary)
async def team_structure_summary(
    _user: CurrentUser,
    db: AsyncSession = Depends(get_db),
):
    categories = await list_sourcer_categories(_user, db)
    delivery_leads = await list_tac_delivery_leads(_user, db)
    dl_clients = await list_dl_clients(_user, db)

    async def _count(role: Optional[UserRole] = None) -> int:
        q = select(func.count(User.id)).where(User.is_active == True)  # noqa: E712
        if role is not None:
            q = q.where(User.role == role)
        return (await db.execute(q)).scalar() or 0

    totals = {
        "sourcers": await _count(UserRole.sourcer),
        "tacs": await _count(UserRole.tac),
        "recruiters": await _count(UserRole.recruiter),
        "delivery_leads": await _count(UserRole.delivery_lead),
        "head_of_recruitment": await _count(UserRole.head_of_recruitment),
        "clients": (
            await db.execute(select(func.count(Client.id)))
        ).scalar()
        or 0,
    }

    return TeamStructureSummary(
        categories=categories,
        delivery_leads=delivery_leads,
        dl_clients=dl_clients,
        totals=totals,
    )
