"""Scoring weight profiles API (Phase D1) + panel „Ranking kandydatów”.

CRUD profili zostaje dla administratora. Profiles are validated so the layers
sum to 100 (six layers; ``champion_fit`` optional and defaults to 0 for
backward-compatible payloads). Scope resolution (user → client → global) is
done by the scoring engine. Każda zmiana profilu trafia do historii
(``scoring_weight_changes``).

Panel (21.10.2026, decyzje Artura D1–D3): Head of Recruitment i admin
zapisują szkic trzech ważności i progu nocnych propozycji; publikacja idzie
przez pomiar na historii. Odczyt panelu ma też Delivery Lead. Bramka sekcji
Insights na routerze: zapis wymaga zapisu w Insights.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.section_access import INSIGHTS_SECTION_DEPENDENCIES
from app.api.deps import HeadOfRecruitmentPlus, require_roles
from app.core.database import get_db
from app.models.scoring_weight_profile import ScoringWeightProfile
from app.models.user import User, UserRole
from app.services import ranking_lab
from app.services import ranking_publish as lab
from app.services import ranking_weights as panel
from app.services.match_score_cache import mark_stale_for_profile

router = APIRouter(dependencies=INSIGHTS_SECTION_DEPENDENCIES)

# Odczyt wag: admin (zawsze), Delivery Lead, Head of Recruitment.
WeightsReader = require_roles(UserRole.head_of_recruitment, UserRole.delivery_lead)


# ── Schemas ──────────────────────────────────────────────────────────────────


class WeightsPayload(BaseModel):
    semantic: int = Field(ge=0, le=100)
    skills: int = Field(ge=0, le=100)
    salary: int = Field(ge=0, le=100)
    location: int = Field(ge=0, le=100)
    availability: int = Field(ge=0, le=100)
    # Sixth engine layer. Optional for backward compatibility: a legacy 5-weight
    # payload (champion_fit defaults to 0) must still sum to 100 exactly as
    # before. New clients send all six. Validated last so the sum sees every
    # layer — this closes the champion-budget-110 gap at the API boundary.
    champion_fit: int = Field(0, ge=0, le=100)

    # `model_validator(mode="after")`, NIE `field_validator("champion_fit")`.
    # Walidator POLA w Pydantic v2 nie odpala się, gdy pola NIE MA w żądaniu
    # i wchodzi wartość domyślna (bez `validate_default=True`) — a `champion_fit`
    # jest opcjonalne właśnie po to, żeby stary, pięciowagowy payload dalej
    # działał. Suma nie była więc sprawdzana DOKŁADNIE w tym przypadku, którego
    # komentarz wyżej broni: `POST /api/scoring-weights` z pięcioma wagami
    # sumującymi się do 99 zwracał 201 i zapisywał profil.
    #
    # To nie jest kosmetyka walidacji: `WeightProfile.from_record` bierze te
    # liczby wprost jako budżety warstw, więc profil o sumie 99 liczy KAŻDY
    # match score względem innego maksimum niż 100, którego oczekują progi
    # i procenty w UI. Bramka API była tu jedynym miejscem, które tego pilnuje.
    @model_validator(mode="after")
    def _sum_to_100(self) -> "WeightsPayload":
        s = (
            self.semantic
            + self.skills
            + self.salary
            + self.location
            + self.availability
            + self.champion_fit
        )
        if s != 100:
            raise ValueError(f"weights must sum to 100, got {s}")
        return self


class ScoringWeightProfileCreate(BaseModel):
    name: str = Field(min_length=2, max_length=80)
    user_id: Optional[int] = None
    client_id: Optional[int] = None
    weights: WeightsPayload
    active: bool = True


class ScoringWeightProfileResponse(BaseModel):
    id: int
    name: str
    user_id: Optional[int]
    client_id: Optional[int]
    weights: dict
    active: bool
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


# ── Endpoints ────────────────────────────────────────────────────────────────


class PanelDraftIn(BaseModel):
    semantic: int
    skills: int
    location: int
    threshold: int

    def to_panel(self) -> panel.PanelWeights:
        return panel.PanelWeights(
            semantic=self.semantic,
            skills=self.skills,
            location=self.location,
            threshold=self.threshold,
        )


def _snapshot(row: ScoringWeightProfile) -> dict:
    return {
        "name": row.name,
        "user_id": row.user_id,
        "client_id": row.client_id,
        "active": row.active,
        "weights": dict(row.weights or {}),
    }


# ── Panel „Ranking kandydatów” ───────────────────────────────────────────────


class PublishIn(BaseModel):
    reason: Optional[str] = Field(default=None, max_length=500)


async def _state(db: AsyncSession, user: User) -> dict:
    state = await panel.panel_state(db)
    state["measurement"] = await lab.measurement_state(db)
    state["can_edit"] = user.has_any_role(UserRole.admin, UserRole.head_of_recruitment)
    return state


def _raise(error: lab.PanelError):
    raise HTTPException(status_code=error.status_code, detail=error.detail) from None


@router.get("/panel")
async def get_panel(
    current_user: User = Depends(WeightsReader),
    db: AsyncSession = Depends(get_db),
):
    """Opublikowane ważności, szkic, próg, pomiar, profile klienta/osoby i historia."""
    return await _state(db, current_user)


@router.get("/panel/measurement")
async def get_panel_measurement(
    current_user: User = Depends(WeightsReader),
    db: AsyncSession = Depends(get_db),
):
    """Lekki odczyt stanu pomiaru do odpytywania w trakcie."""
    return {"measurement": await lab.measurement_state(db)}


@router.post("/panel/measurements", status_code=status.HTTP_202_ACCEPTED)
async def start_panel_measurement(
    current_user: HeadOfRecruitmentPlus,
    db: AsyncSession = Depends(get_db),
):
    """Sprawdza szkic na zamkniętych rekrutacjach w tle (tylko odczyt, ok. 5 min)."""
    try:
        await lab.start(db, actor_id=current_user.id)
    except lab.PanelError as error:
        _raise(error)
    return {"measurement": await lab.measurement_state(db)}


@router.post("/panel/publish")
async def publish_panel(
    payload: PublishIn,
    current_user: HeadOfRecruitmentPlus,
    db: AsyncSession = Depends(get_db),
):
    """Szkic → wagi dla wszystkich rekrutacji. Bez aktualnego pomiaru 409."""
    try:
        await lab.publish(db, actor_id=current_user.id, reason=payload.reason)
    except lab.PanelError as error:
        _raise(error)
    return await _state(db, current_user)


@router.post("/panel/history/{change_id}/restore")
async def restore_panel_change(
    change_id: int,
    current_user: HeadOfRecruitmentPlus,
    db: AsyncSession = Depends(get_db),
):
    """Nowy szkic z wagami tamtej zmiany — też przechodzi pomiar."""
    try:
        await lab.restore(db, change_id, actor_id=current_user.id)
    except lab.PanelError as error:
        _raise(error)
    return await _state(db, current_user)


@router.get("/panel/preview/jobs")
async def get_preview_jobs(
    current_user: User = Depends(WeightsReader),
    db: AsyncSession = Depends(get_db),
):
    """Zamknięte rekrutacje, na których da się podejrzeć zmianę kolejności."""
    return {"jobs": await ranking_lab.preview_jobs(db)}


@router.get("/panel/preview/{job_id}")
async def get_preview(
    job_id: int,
    current_user: User = Depends(WeightsReader),
    db: AsyncSession = Depends(get_db),
):
    """Składniki oceny 200 pierwszych osób — front liczy kolejność sam."""
    payload = await ranking_lab.preview(db, job_id)
    if payload is None:
        raise HTTPException(
            status_code=404,
            detail="Tej rekrutacji nie da się odtworzyć — wybierz inną z listy.",
        )
    return payload


@router.put("/panel/draft")
async def put_panel_draft(
    payload: PanelDraftIn,
    current_user: HeadOfRecruitmentPlus,
    db: AsyncSession = Depends(get_db),
):
    """Szkic nic nie zmienia dla zespołu — obowiązuje dopiero po publikacji."""
    draft = payload.to_panel()
    error = panel.validation_error(draft)
    if error:
        raise HTTPException(status_code=422, detail=error)
    await panel.save_draft(db, draft, actor_id=current_user.id)
    await db.commit()
    return await _state(db, current_user)


@router.delete("/panel/draft", status_code=status.HTTP_204_NO_CONTENT)
async def delete_panel_draft(
    current_user: HeadOfRecruitmentPlus,
    db: AsyncSession = Depends(get_db),
):
    await panel.discard_draft(db)
    await db.commit()


# ── Profile (administrator) ──────────────────────────────────────────────────


@router.get("", response_model=list[ScoringWeightProfileResponse])
async def list_profiles(
    current_user: User = Depends(WeightsReader),
    db: AsyncSession = Depends(get_db),
):
    rows = (
        (
            await db.execute(
                select(ScoringWeightProfile).order_by(ScoringWeightProfile.name.asc())
            )
        )
        .scalars()
        .all()
    )
    return rows


@router.post(
    "", response_model=ScoringWeightProfileResponse, status_code=status.HTTP_201_CREATED
)
async def create_profile(
    payload: ScoringWeightProfileCreate,
    current_user: User = Depends(require_roles(UserRole.admin)),
    db: AsyncSession = Depends(get_db),
):
    if await db.scalar(
        select(ScoringWeightProfile.id).where(ScoringWeightProfile.name == payload.name)
    ):
        raise HTTPException(status_code=409, detail="profile name already exists")
    row = ScoringWeightProfile(
        name=payload.name,
        user_id=payload.user_id,
        client_id=payload.client_id,
        weights=payload.weights.model_dump(),
        active=payload.active,
    )
    db.add(row)
    # The name check above is racy: two concurrent creates both pass it, then
    # the UNIQUE constraint (uq_scoring_weight_profiles_name) rejects the second
    # at flush/commit. Catch it so the loser gets the same 409 as the read
    # path, never a 500.
    try:
        await db.flush()
        await panel.record_change(
            db,
            kind="admin_edit",
            actor_id=current_user.id,
            profile_id=row.id,
            before={},
            after=_snapshot(row),
        )
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(
            status_code=409, detail="profile name already exists"
        ) from None
    await db.refresh(row)
    return row


@router.patch("/{profile_id}", response_model=ScoringWeightProfileResponse)
async def update_profile(
    profile_id: int,
    payload: ScoringWeightProfileCreate,
    current_user: User = Depends(require_roles(UserRole.admin)),
    db: AsyncSession = Depends(get_db),
):
    row = await db.scalar(
        select(ScoringWeightProfile).where(ScoringWeightProfile.id == profile_id)
    )
    if not row:
        raise HTTPException(status_code=404, detail="not found")
    before = _snapshot(row)
    row.name = payload.name
    # Ekran wysyła tylko {name, weights, active}. Przypięcie do osoby albo
    # klienta zmienia się wyłącznie, gdy pole przyszło w żądaniu — inaczej
    # edycja z ekranu po cichu robiła z profilu klienta profil ogólny.
    if "user_id" in payload.model_fields_set:
        row.user_id = payload.user_id
    if "client_id" in payload.model_fields_set:
        row.client_id = payload.client_id
    row.weights = payload.weights.model_dump()
    row.active = payload.active
    # Kolumna nie ma `onupdate` — bez tego „opublikowane” na ekranie
    # pokazywało datę założenia profilu.
    row.updated_at = datetime.now(timezone.utc)
    await panel.record_change(
        db,
        kind="admin_edit",
        actor_id=current_user.id,
        profile_id=row.id,
        before=before,
        after=_snapshot(row),
    )
    # Editing weights in place would otherwise keep serving old-weight cached
    # scores for this profile_id (AI-P0-06 a) — invalidate them in the same txn.
    await mark_stale_for_profile(db, profile_id)
    await db.commit()
    await db.refresh(row)
    return row


@router.delete("/{profile_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_profile(
    profile_id: int,
    current_user: User = Depends(require_roles(UserRole.admin)),
    db: AsyncSession = Depends(get_db),
):
    row = await db.scalar(
        select(ScoringWeightProfile).where(ScoringWeightProfile.id == profile_id)
    )
    if not row:
        raise HTTPException(status_code=404, detail="not found")
    # Drop any cached scores computed under this profile before it disappears
    # (AI-P0-06 a) — otherwise they linger as dead, un-recomputable rows.
    await mark_stale_for_profile(db, profile_id)
    await panel.record_change(
        db,
        kind="admin_edit",
        actor_id=current_user.id,
        profile_id=row.id,
        before=_snapshot(row),
        after={},
    )
    await db.delete(row)
    await db.commit()
