"""DynaReporter Admin — Users / Team / DL Clients endpoints.

Łączy 3 sekcje admin panelu:
- **Employees** (Pracownicy i konta) — lista userów + seniority + active toggle
- **Recruitment Team** — sourcer/TAC/recruiter/DL assignments
- **DL Clients** — Delivery Lead ↔ klient assignments

Port `EmployeeManagement.tsx` + `RecruitmentTeamManager.tsx` +
`DLClientManager.tsx` z artur-t-96/InfraReporter.
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import AdminUser
from app.core.database import get_db
from app.models.user import User, UserRole

logger = logging.getLogger("dynareporter.admin_users")

router = APIRouter()


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------


class EmployeeRow(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    email: str
    name: str = ""  # Nexus users.name (single column, nie first/last)
    first_name: str | None = None  # derived split z `name` dla compat z DR
    last_name: str | None = None
    role: str
    department: str | None = None
    is_active: bool = True
    allowed_sections: list[str] = Field(default_factory=list)
    seniority_level: str | None = None
    acceleration_start_date: date | None = None
    senior_since: date | None = None
    expert_since: date | None = None


class SeniorityPayload(BaseModel):
    seniority_level: str = Field(
        pattern=r"^(junior|senior|expert)$",
        description="'junior' | 'senior' | 'expert'",
    )
    acceleration_start_date: date | None = None
    senior_since: date | None = None
    expert_since: date | None = None


class ToggleActivePayload(BaseModel):
    is_active: bool


class TeamMember(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    email: str
    role: str


class TacDlAssignment(BaseModel):
    tac_user_id: int
    delivery_lead_user_id: int
    tac_name: str
    delivery_lead_name: str


class SourcerCategoryAssignment(BaseModel):
    user_id: int
    sourcer_name: str
    category_id: int
    category_name: str
    priority: int


class DLClientAssignment(BaseModel):
    id: int
    delivery_lead_user_id: int
    delivery_lead_name: str
    client_id: int
    client_name: str
    is_head: bool = False


class CompetenceCategoryRow(BaseModel):
    id: int
    name: str
    color: str = "blue"
    sort_order: int = 0
    is_active: bool = True


class TacDlPayload(BaseModel):
    tac_user_id: int
    delivery_lead_user_id: int


class AllowedSectionsPayload(BaseModel):
    allowed_sections: list[str] = Field(default_factory=list)


class SourcerCategoryPayload(BaseModel):
    user_id: int
    category_id: int
    priority: int = 1


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Employees endpoints
# ---------------------------------------------------------------------------


@router.get(
    "/employees",
    response_model=list[EmployeeRow],
    summary="Lista pracowników (users + dr_user_seniority)",
)
async def list_employees(
    current_user: AdminUser,
    db: AsyncSession = Depends(get_db),
) -> list[EmployeeRow]:
    """Lista wszystkich userów + seniority dla acceleration path roles."""
    sql = text(
        """
        SELECT
            u.id,
            u.email,
            u.name,
            u.role::text AS role,
            COALESCE(u.allowed_sections, '[]'::jsonb) AS allowed_sections,
            COALESCE(u.is_active, true) AS is_active,
            s.seniority_level,
            s.acceleration_start_date,
            s.senior_since,
            s.expert_since
        FROM users u
        LEFT JOIN dr_user_seniority s ON s.user_id = u.id
        ORDER BY u.is_active DESC, COALESCE(u.name, ''), u.email
        """
    )
    rows = (await db.execute(sql)).all()
    result: list[EmployeeRow] = []
    for r in rows:
        sections = r.allowed_sections
        if isinstance(sections, str):
            import json

            try:
                sections = json.loads(sections)
            except Exception:
                sections = []
        # Derive first_name/last_name from `name` (compat z DR UI)
        full_name = r.name or ""
        parts = full_name.split(" ", 1)
        first = parts[0] if parts and parts[0] else None
        last = parts[1] if len(parts) > 1 and parts[1] else None
        result.append(
            EmployeeRow(
                id=r.id,
                email=r.email or "",
                name=full_name,
                first_name=first,
                last_name=last,
                role=r.role if r.role else "",
                department=None,  # nie mamy column w nexus.users
                is_active=r.is_active,
                allowed_sections=sections if isinstance(sections, list) else [],
                seniority_level=r.seniority_level,
                acceleration_start_date=r.acceleration_start_date,
                senior_since=r.senior_since,
                expert_since=r.expert_since,
            )
        )
    return result


@router.post(
    "/employees/{user_id}/seniority",
    summary="Ustaw seniority level dla usera (admin only)",
)
async def upsert_seniority(
    user_id: int,
    payload: SeniorityPayload,
    current_user: AdminUser,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Upsert do dr_user_seniority (1:1 z users)."""
    sql = text(
        """
        INSERT INTO dr_user_seniority (
            user_id, seniority_level, acceleration_start_date,
            senior_since, expert_since, updated_at
        ) VALUES (
            :uid, :lvl, :start, :ssin, :esin, CURRENT_TIMESTAMP
        )
        ON CONFLICT (user_id) DO UPDATE SET
            seniority_level = EXCLUDED.seniority_level,
            acceleration_start_date = EXCLUDED.acceleration_start_date,
            senior_since = EXCLUDED.senior_since,
            expert_since = EXCLUDED.expert_since,
            updated_at = CURRENT_TIMESTAMP
        """
    )
    await db.execute(
        sql,
        {
            "uid": user_id,
            "lvl": payload.seniority_level,
            "start": payload.acceleration_start_date,
            "ssin": payload.senior_since,
            "esin": payload.expert_since,
        },
    )
    await db.commit()
    logger.info(
        "Seniority upserted: user=%s level=%s by admin=%s",
        user_id,
        payload.seniority_level,
        current_user.id,
    )
    return {"ok": True}


@router.post(
    "/employees/{user_id}/active",
    summary="Toggle is_active dla usera (admin only)",
)
async def toggle_active(
    user_id: int,
    payload: ToggleActivePayload,
    current_user: AdminUser,
    db: AsyncSession = Depends(get_db),
) -> dict:
    # One atomic statement closes the legacy session-revocation bypass.
    # ``IS DISTINCT FROM`` makes retries/no-ops harmless: the auth version and
    # revocation floor advance exactly once for each real active-state change.
    result = await db.execute(
        text(
            """
            UPDATE users
            SET is_active = :a,
                authorization_version = authorization_version + 1,
                tokens_valid_after = CURRENT_TIMESTAMP
            WHERE id = :uid
              AND is_active IS DISTINCT FROM :a
            RETURNING id
            """
        ),
        {"a": payload.is_active, "uid": user_id},
    )
    changed = result.scalar_one_or_none() is not None
    await db.commit()
    logger.info(
        "User is_active %s: user=%s active=%s by admin=%s",
        "toggled" if changed else "unchanged",
        user_id,
        payload.is_active,
        current_user.id,
    )
    return {"ok": True, "is_active": payload.is_active}


@router.post(
    "/employees/{user_id}/allowed-sections",
    summary="Update allowed_sections JSONB dla usera (admin only)",
)
async def update_allowed_sections(
    user_id: int,
    payload: AllowedSectionsPayload,
    current_user: AdminUser,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Replace user's allowed_sections list. Validates że każda section to
    znana DR section (no arbitrary strings).
    """
    # Whitelist of known DR sections — przeciwko admin przypadkowo dodawał
    # garbage strings. Sync z `DynaReporterSection` type w
    # `frontend/src/store/auth.ts` (DASHES, legacy DR convention) + DB values.
    VALID_SECTIONS = {
        "body-leasing",  # Rekrutacja
        "sales",
        "delivery-lead",
        "przetargi",
        "board",
        "admin",
        "clients-mrr",
        "placements",
        "mindy",
        "competitions",
        "sales-mgmt",
    }
    invalid = [s for s in payload.allowed_sections if s not in VALID_SECTIONS]
    if invalid:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Nieznane sekcje: {invalid}",
        )
    target = await db.scalar(select(User).where(User.id == user_id))
    if target is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="User not found"
        )
    if payload.allowed_sections and target.has_any_role(
        UserRole.finance,
        UserRole.user,
    ):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Finance and Viewer cannot receive legacy DynaReporter sections",
        )
    changed = list(target.allowed_sections or []) != payload.allowed_sections
    if changed:
        target.allowed_sections = list(payload.allowed_sections)
        target.authorization_version += 1
        target.tokens_valid_after = datetime.now(timezone.utc)
    await db.commit()
    logger.info(
        "User allowed_sections updated: user=%s sections=%s by admin=%s",
        user_id,
        payload.allowed_sections,
        current_user.id,
    )
    return {
        "ok": True,
        "changed": changed,
        "allowed_sections": payload.allowed_sections,
    }


# ---------------------------------------------------------------------------
# Recruitment Team endpoints
# ---------------------------------------------------------------------------


@router.get(
    "/team/members",
    response_model=list[TeamMember],
    summary="Recruitment Team — lista członków zespołu rekrutacji",
)
async def list_team_members(
    current_user: AdminUser,
    db: AsyncSession = Depends(get_db),
) -> list[TeamMember]:
    """Lista userów z rolami sourcer/tac/recruiter/delivery_lead."""
    sql = text(
        """
        SELECT
            id,
            COALESCE(NULLIF(name, ''), email) AS name,
            email,
            role::text AS role
        FROM users
        WHERE COALESCE(is_active, true)
          AND role::text IN ('sourcer', 'tac', 'recruiter', 'delivery_lead')
        ORDER BY role::text, COALESCE(name, ''), email
        """
    )
    rows = (await db.execute(sql)).all()
    return [
        TeamMember(id=r.id, name=r.name or r.email, email=r.email, role=r.role)
        for r in rows
    ]


@router.get(
    "/team/tac-dl",
    response_model=list[TacDlAssignment],
    summary="TAC ↔ Delivery Lead assignments",
)
async def list_tac_dl_assignments(
    current_user: AdminUser,
    db: AsyncSession = Depends(get_db),
) -> list[TacDlAssignment]:
    sql = text(
        """
        SELECT
            a.tac_user_id,
            a.delivery_lead_user_id,
            COALESCE(NULLIF(t.name, ''), t.email) AS tac_name,
            COALESCE(NULLIF(d.name, ''), d.email) AS dl_name
        FROM dr_tac_delivery_lead_assignments a
        JOIN users t ON t.id = a.tac_user_id
        JOIN users d ON d.id = a.delivery_lead_user_id
        ORDER BY dl_name, tac_name
        """
    )
    rows = (await db.execute(sql)).all()
    return [
        TacDlAssignment(
            tac_user_id=r.tac_user_id,
            delivery_lead_user_id=r.delivery_lead_user_id,
            tac_name=r.tac_name or "",
            delivery_lead_name=r.dl_name or "",
        )
        for r in rows
    ]


@router.get(
    "/team/sourcer-categories",
    response_model=list[SourcerCategoryAssignment],
    summary="Sourcer ↔ Competence Category assignments",
)
async def list_sourcer_categories(
    current_user: AdminUser,
    db: AsyncSession = Depends(get_db),
) -> list[SourcerCategoryAssignment]:
    sql = text(
        """
        SELECT
            a.user_id,
            COALESCE(NULLIF(u.name, ''), u.email) AS sourcer_name,
            a.category_id,
            c.name AS category_name,
            a.priority
        FROM dr_sourcer_category_assignments a
        JOIN users u ON u.id = a.user_id
        LEFT JOIN dr_competence_categories c ON c.id = a.category_id
        ORDER BY sourcer_name, a.priority, category_name
        """
    )
    rows = (await db.execute(sql)).all()
    return [
        SourcerCategoryAssignment(
            user_id=r.user_id,
            sourcer_name=r.sourcer_name or "",
            category_id=r.category_id,
            category_name=r.category_name or "—",
            priority=r.priority,
        )
        for r in rows
    ]


@router.get(
    "/team/categories",
    response_model=list[CompetenceCategoryRow],
    summary="Competence categories list (read-only)",
)
async def list_competence_categories(
    current_user: AdminUser,
    db: AsyncSession = Depends(get_db),
) -> list[CompetenceCategoryRow]:
    """List wszystkich active competence categories — used dla dropdownów
    w Sourcer-category assignment form.
    """
    sql = text(
        """
        SELECT
            id,
            name,
            COALESCE(color, 'blue') AS color,
            COALESCE(sort_order, 0) AS sort_order,
            COALESCE(is_active, true) AS is_active
        FROM dr_competence_categories
        ORDER BY sort_order, name
        """
    )
    rows = (await db.execute(sql)).all()
    return [
        CompetenceCategoryRow(
            id=r.id,
            name=r.name or "",
            color=r.color or "blue",
            sort_order=r.sort_order or 0,
            is_active=bool(r.is_active),
        )
        for r in rows
    ]


@router.post(
    "/team/tac-dl",
    status_code=status.HTTP_201_CREATED,
    summary="Add TAC ↔ DL assignment (admin only)",
)
async def add_tac_dl_assignment(
    payload: TacDlPayload,
    current_user: AdminUser,
    db: AsyncSession = Depends(get_db),
) -> dict:
    # Constraint to UNIQUE(tac_user_id) — TAC ma dokładnie jednego DL.
    # Re-przypisanie TAC do innego DL = UPDATE (nie duplikat). Wcześniejszy
    # ON CONFLICT (tac_user_id, delivery_lead_user_id) nie pasował do
    # istniejącego ograniczenia i powodował 500 przy każdym dodaniu.
    await db.execute(
        text(
            """
            INSERT INTO dr_tac_delivery_lead_assignments (
                tac_user_id, delivery_lead_user_id
            ) VALUES (:tac, :dl)
            ON CONFLICT (tac_user_id)
            DO UPDATE SET delivery_lead_user_id = EXCLUDED.delivery_lead_user_id
            """
        ),
        {"tac": payload.tac_user_id, "dl": payload.delivery_lead_user_id},
    )
    await db.commit()
    logger.info(
        "TAC-DL assignment added: tac=%s dl=%s by admin=%s",
        payload.tac_user_id,
        payload.delivery_lead_user_id,
        current_user.id,
    )
    return {"ok": True}


@router.delete(
    "/team/tac-dl/{tac_user_id}/{dl_user_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_model=None,
    summary="Remove TAC ↔ DL assignment (admin only)",
)
async def delete_tac_dl_assignment(
    tac_user_id: int,
    dl_user_id: int,
    current_user: AdminUser,
    db: AsyncSession = Depends(get_db),
) -> None:
    await db.execute(
        text(
            "DELETE FROM dr_tac_delivery_lead_assignments "
            "WHERE tac_user_id = :tac AND delivery_lead_user_id = :dl"
        ),
        {"tac": tac_user_id, "dl": dl_user_id},
    )
    await db.commit()
    logger.info(
        "TAC-DL assignment removed: tac=%s dl=%s by admin=%s",
        tac_user_id,
        dl_user_id,
        current_user.id,
    )


@router.post(
    "/team/sourcer-categories",
    status_code=status.HTTP_201_CREATED,
    summary="Add Sourcer ↔ Category assignment (admin only)",
)
async def add_sourcer_category(
    payload: SourcerCategoryPayload,
    current_user: AdminUser,
    db: AsyncSession = Depends(get_db),
) -> dict:
    if payload.priority < 1 or payload.priority > 5:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="priority must be 1-5",
        )
    # Istniejące ograniczenie to UNIQUE(category_id, user_id, priority), które
    # NIE pasuje do ON CONFLICT (user_id, category_id) → poprzednia wersja
    # rzucała 500 przy każdym zapisie. Upsert "jeden priorytet per user+kategoria"
    # realizujemy jako DELETE+INSERT w jednej transakcji.
    await db.execute(
        text(
            "DELETE FROM dr_sourcer_category_assignments "
            "WHERE user_id = :uid AND category_id = :cid"
        ),
        {"uid": payload.user_id, "cid": payload.category_id},
    )
    await db.execute(
        text(
            """
            INSERT INTO dr_sourcer_category_assignments (
                user_id, category_id, priority
            ) VALUES (:uid, :cid, :prio)
            """
        ),
        {
            "uid": payload.user_id,
            "cid": payload.category_id,
            "prio": payload.priority,
        },
    )
    await db.commit()
    logger.info(
        "Sourcer-category assignment upserted: user=%s cat=%s prio=%s by admin=%s",
        payload.user_id,
        payload.category_id,
        payload.priority,
        current_user.id,
    )
    return {"ok": True}


@router.delete(
    "/team/sourcer-categories/{user_id}/{category_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_model=None,
    summary="Remove Sourcer ↔ Category assignment (admin only)",
)
async def delete_sourcer_category(
    user_id: int,
    category_id: int,
    current_user: AdminUser,
    db: AsyncSession = Depends(get_db),
) -> None:
    await db.execute(
        text(
            "DELETE FROM dr_sourcer_category_assignments "
            "WHERE user_id = :uid AND category_id = :cid"
        ),
        {"uid": user_id, "cid": category_id},
    )
    await db.commit()
    logger.info(
        "Sourcer-category assignment removed: user=%s cat=%s by admin=%s",
        user_id,
        category_id,
        current_user.id,
    )


# ---------------------------------------------------------------------------
# DL Clients endpoints
# ---------------------------------------------------------------------------


@router.get(
    "/dl-clients",
    response_model=list[DLClientAssignment],
    summary="Delivery Lead ↔ Klient assignments",
)
async def list_dl_clients(
    current_user: AdminUser,
    db: AsyncSession = Depends(get_db),
) -> list[DLClientAssignment]:
    sql = text(
        """
        SELECT
            a.id,
            a.delivery_lead_user_id,
            COALESCE(NULLIF(u.name, ''), u.email) AS dl_name,
            a.client_id,
            COALESCE(c.name, '—') AS client_name,
            COALESCE(a.is_head, false) AS is_head
        FROM dr_delivery_lead_client_assignments a
        JOIN users u ON u.id = a.delivery_lead_user_id
        LEFT JOIN dr_clients c ON c.id = a.client_id
        ORDER BY dl_name, client_name
        """
    )
    rows = (await db.execute(sql)).all()
    return [
        DLClientAssignment(
            id=r.id,
            delivery_lead_user_id=r.delivery_lead_user_id,
            delivery_lead_name=r.dl_name or "",
            client_id=r.client_id,
            client_name=r.client_name or "—",
            is_head=bool(r.is_head),
        )
        for r in rows
    ]


class DLClientAssignPayload(BaseModel):
    delivery_lead_user_id: int
    client_id: int
    is_head: bool = False


@router.post(
    "/dl-clients",
    summary="Przypisz Delivery Lead do klienta (admin only)",
)
async def add_dl_client(
    payload: DLClientAssignPayload,
    current_user: AdminUser,
    db: AsyncSession = Depends(get_db),
) -> dict:
    sql = text(
        """
        INSERT INTO dr_delivery_lead_client_assignments (
            delivery_lead_user_id, client_id, is_head
        ) VALUES (:dl, :cid, :head)
        RETURNING id
        """
    )
    result = await db.execute(
        sql,
        {
            "dl": payload.delivery_lead_user_id,
            "cid": payload.client_id,
            "head": payload.is_head,
        },
    )
    await db.commit()
    row = result.first()
    assignment_id = row.id if row else None
    logger.info(
        "DL-client assignment added: id=%s dl=%s client=%s is_head=%s by admin=%s",
        assignment_id,
        payload.delivery_lead_user_id,
        payload.client_id,
        payload.is_head,
        current_user.id,
    )
    return {"id": assignment_id, "ok": True}


@router.patch(
    "/dl-clients/{assignment_id}",
    summary="Toggle is_head dla DL-client assignment (admin only)",
)
async def patch_dl_client(
    assignment_id: int,
    payload: dict,
    current_user: AdminUser,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Toggle `is_head` flag dla istniejącego DL-client assignment.

    Payload: {"is_head": bool}. Single-field update, brak innych mutowalnych pól.
    """
    if "is_head" not in payload:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Brak pola 'is_head' w payload",
        )
    is_head = bool(payload["is_head"])
    result = await db.execute(
        text(
            "UPDATE dr_delivery_lead_client_assignments SET is_head = :h "
            "WHERE id = :id RETURNING id"
        ),
        {"h": is_head, "id": assignment_id},
    )
    if not result.first():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Assignment id={assignment_id} nie istnieje",
        )
    await db.commit()
    logger.info(
        "DL-client assignment patched: id=%s is_head=%s by admin=%s",
        assignment_id,
        is_head,
        current_user.id,
    )
    return {"id": assignment_id, "is_head": is_head, "ok": True}


@router.delete(
    "/dl-clients/{assignment_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_model=None,
    summary="Usuń DL-klient assignment (admin only)",
)
async def delete_dl_client(
    assignment_id: int,
    current_user: AdminUser,
    db: AsyncSession = Depends(get_db),
) -> None:
    await db.execute(
        text("DELETE FROM dr_delivery_lead_client_assignments WHERE id = :id"),
        {"id": assignment_id},
    )
    await db.commit()
    logger.info(
        "DL-client assignment deleted: id=%s by admin=%s",
        assignment_id,
        current_user.id,
    )
