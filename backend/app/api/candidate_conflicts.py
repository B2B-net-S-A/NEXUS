"""Rejestr konfliktów kandydat↔klient (blacklist / NDA / konkurencja / zatrudnienie).

Przeniesione z ``phase5.py`` (ścieżki bez zmian) i rozbudowane 17.09.2026:

* ``GET  /api/candidates/{candidate_id}/conflicts`` — konflikty jednego kandydata;
* ``POST /api/candidates/{candidate_id}/conflicts`` — dopisanie konfliktu;
* ``PATCH /api/conflicts/{conflict_id}/deactivate`` — zdjęcie konfliktu z powodem;
* ``GET  /api/conflicts`` — rejestr: „kto ma konflikt u klienta X", „co wygasa".

**Bramka odczytu to ``CandidateSearchAccess``, nie Finance.** Delivery Lead ma
domyślnie ``finance=none``, więc przy dawnej ``CandidateFinanceReadAccess`` mógł
konflikt DODAĆ, a lista w widżecie zwracała mu 403. Konflikt mówi o
dopuszczalności kandydata, nie o pieniądzach. Zapis bez zmian:
``require_candidate_write`` + ``ManagerOrAdmin``.

**Wygaśnięcie jest stanem przy odczycie** (``CandidateConflict.state_at``):
wiersz z ``expires_at`` w przeszłości zostaje ``active`` jako historia, a
jednorazową kartę DL wystawia ``rule_candidate_conflict_expired``.

**Dezaktywacja zostawia ślad** na wierszu (``deactivated_*``) i w ``activities``.
Wpisy ``activities`` NIE niosą imion i nazwisk — tylko identyfikatory.
"""

from datetime import datetime, timedelta, timezone
from typing import Annotated, Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import func, not_, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.api.candidate_access import CandidateSearchAccess, require_candidate_write
from app.api.deps import ManagerOrAdmin
from app.core.database import get_db
from app.models.activity import Activity
from app.models.candidate import Candidate
from app.services.match_score_cache import mark_stale_for_candidate
from app.models.candidate_conflict import (
    CONFLICT_TYPE_LABELS,
    CandidateConflict,
    ConflictType,
    active_unexpired_clause,
)
from app.models.client import Client
from app.models.user import User
from app.services.access_scope import (
    assert_delivery_lead_client_visible,
    resolve_delivery_lead_client_ids,
)
from app.services.client_identity import client_display_name_expression
from app.services.polish_ilike import polish_folded_ilike
from app.services.client_access import assert_client_assignable

router = APIRouter()

DUPLICATE_ACTIVE_DETAIL = (
    "Ten kandydat ma już aktywny konflikt tego typu u tego klienta"
)
SUPERSEDED_AFTER_EXPIRY_REASON = "Zastąpiony nowym wpisem po wygaśnięciu"
NDA_REQUIRES_EXPIRY_DETAIL = "NDA wymaga daty wygaśnięcia."
EXPIRY_IN_PAST_DETAIL = "Data wygaśnięcia musi być w przyszłości."
ALREADY_INACTIVE_DETAIL = "Ten konflikt jest już nieaktywny."


# ── Schematy ────────────────────────────────────────────────────────────────


class ConflictCreate(BaseModel):
    client_id: int
    type: ConflictType
    reason: Optional[str] = Field(default=None, max_length=2000)
    expires_at: Optional[datetime] = None

    @field_validator("reason")
    @classmethod
    def _strip_reason(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        return value.strip() or None

    @field_validator("expires_at")
    @classmethod
    def _to_utc(cls, value: Optional[datetime]) -> Optional[datetime]:
        if value is None:
            return None
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)


class ConflictDeactivate(BaseModel):
    reason: str = Field(max_length=2000)

    @field_validator("reason")
    @classmethod
    def _reason_min_length(cls, value: str) -> str:
        stripped = value.strip()
        if len(stripped) < 3:
            raise ValueError("Powód dezaktywacji musi mieć co najmniej 3 znaki.")
        return stripped


# ── Odczyt z nazwami ────────────────────────────────────────────────────────

_Creator = aliased(User)
_Deactivator = aliased(User)


def _enriched_select():
    return (
        select(
            CandidateConflict,
            client_display_name_expression().label("client_name"),
            _Creator.name.label("created_by_name"),
            _Deactivator.name.label("deactivated_by_name"),
            Candidate.name.label("candidate_first_name"),
            Candidate.lastname.label("candidate_last_name"),
        )
        .join(Candidate, Candidate.id == CandidateConflict.candidate_id)
        .outerjoin(Client, Client.id == CandidateConflict.client_id)
        .outerjoin(_Creator, _Creator.id == CandidateConflict.created_by)
        .outerjoin(_Deactivator, _Deactivator.id == CandidateConflict.deactivated_by)
    )


def _iso(value: Optional[datetime]) -> Optional[str]:
    return value.isoformat() if value else None


def _conflict_to_dict(
    row: Any,
    *,
    now: datetime,
    include_candidate: bool = False,
) -> dict:
    c: CandidateConflict = row[0]
    out = {
        "id": c.id,
        "candidate_id": c.candidate_id,
        "client_id": c.client_id,
        "client_name": row.client_name,
        "type": c.type.value,
        "type_label": CONFLICT_TYPE_LABELS.get(c.type.value, c.type.value),
        "reason": c.reason,
        "active": c.active,
        "state": c.state_at(now),
        "expires_at": _iso(c.expires_at),
        "created_by": c.created_by,
        "created_by_name": row.created_by_name,
        "created_at": _iso(c.created_at),
        "deactivated_at": _iso(c.deactivated_at),
        "deactivated_by": c.deactivated_by,
        "deactivated_by_name": row.deactivated_by_name,
        "deactivation_reason": c.deactivation_reason,
    }
    if include_candidate:
        first = (row.candidate_first_name or "").strip()
        last = (row.candidate_last_name or "").strip()
        out["candidate_name"] = f"{first} {last}".strip() or None
    return out


async def _load_one(db: AsyncSession, conflict_id: int, now: datetime) -> dict:
    row = (
        await db.execute(_enriched_select().where(CandidateConflict.id == conflict_id))
    ).first()
    if row is None:  # pragma: no cover — wiersz dopiero co zapisany
        raise HTTPException(status_code=404, detail="Conflict not found")
    return _conflict_to_dict(row, now=now)


# ── Konflikty kandydata ─────────────────────────────────────────────────────


@router.get("/candidates/{candidate_id}/conflicts")
async def list_conflicts(
    candidate_id: int,
    current_user: CandidateSearchAccess,
    active_only: bool = True,
    db: AsyncSession = Depends(get_db),
):
    """``active_only=true`` (domyślnie) = wyłącznie stan ``active`` (bez
    wygasłych); ``false`` = pełna historia z ``state`` przy każdym wierszu."""
    now = datetime.now(timezone.utc)
    stmt = _enriched_select().where(CandidateConflict.candidate_id == candidate_id)
    if active_only:
        stmt = stmt.where(active_unexpired_clause(now))
    stmt = stmt.order_by(
        CandidateConflict.created_at.desc(), CandidateConflict.id.desc()
    )
    rows = (await db.execute(stmt)).all()
    return [_conflict_to_dict(row, now=now) for row in rows]


@router.post(
    "/candidates/{candidate_id}/conflicts",
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_candidate_write)],
)
async def create_conflict(
    candidate_id: int,
    data: ConflictCreate,
    current_user: ManagerOrAdmin,
    db: AsyncSession = Depends(get_db),
):
    cand = await db.scalar(select(Candidate.id).where(Candidate.id == candidate_id))
    if not cand:
        raise HTTPException(status_code=404, detail="Candidate not found")
    client = await db.scalar(select(Client.id).where(Client.id == data.client_id))
    if not client:
        raise HTTPException(status_code=404, detail="Klient nie istnieje.")
    # Runda 7 (R7-X5-4, bliźniak): konflikt z usuniętym albo scalonym klientem
    # nie działałby na żadnej rekrutacji — wskaż rekord główny.
    await assert_client_assignable(db, data.client_id)

    now = datetime.now(timezone.utc)
    if data.type == ConflictType.nda and data.expires_at is None:
        raise HTTPException(status_code=422, detail=NDA_REQUIRES_EXPIRY_DETAIL)
    if data.expires_at is not None and data.expires_at <= now:
        raise HTTPException(status_code=422, detail=EXPIRY_IN_PAST_DETAIL)

    # Wygasły wpis tego samego typu nadal zajmuje indeks unikalności
    # (`active = true` zostaje jako historia). Nowy wpis po wygaśnięciu to
    # odnowienie — wygasły zamykamy z powodem, zamiast odmawiać 409 osobie,
    # która w widżecie widzi „Brak aktywnych konfliktów".
    superseded = (
        (
            await db.execute(
                select(CandidateConflict)
                .where(
                    CandidateConflict.candidate_id == candidate_id,
                    CandidateConflict.client_id == data.client_id,
                    CandidateConflict.type == data.type,
                    CandidateConflict.active.is_(True),
                    CandidateConflict.expires_at.isnot(None),
                    CandidateConflict.expires_at <= now,
                )
                .with_for_update()
            )
        )
        .scalars()
        .all()
    )
    for old in superseded:
        old.active = False
        old.deactivated_at = now
        old.deactivated_by = current_user.id
        old.deactivation_reason = SUPERSEDED_AFTER_EXPIRY_REASON
        db.add(
            Activity(
                entity_type="candidate",
                entity_id=candidate_id,
                action="conflict_deactivated",
                user_id=current_user.id,
                details={
                    "conflict_id": old.id,
                    "client_id": old.client_id,
                    "type": old.type.value,
                    "superseded": True,
                },
            )
        )
    if superseded:
        await db.flush()

    conflict = CandidateConflict(
        candidate_id=candidate_id,
        client_id=data.client_id,
        type=data.type,
        reason=data.reason,
        expires_at=data.expires_at,
        created_by=current_user.id,
    )
    db.add(conflict)
    try:
        await db.flush()
        db.add(
            Activity(
                entity_type="candidate",
                entity_id=candidate_id,
                action="conflict_added",
                user_id=current_user.id,
                details={
                    "conflict_id": conflict.id,
                    "client_id": data.client_id,
                    "type": data.type.value,
                    "expires_at": _iso(data.expires_at),
                },
            )
        )
        # Scoring czyta konflikty (ostrzeżenie w `breakdown.warnings`) — cache
        # wyników tego kandydata musi się przeliczyć.
        await mark_stale_for_candidate(db, candidate_id)
        await db.commit()
    except IntegrityError:
        # Jedyny realny przypadek: aktywny wpis (kandydat, klient, typ) już jest
        # (klient i kandydat sprawdzeni wyżej). Treść wyjątku NIE wychodzi — to
        # surowy SQL z nazwami indeksów.
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=DUPLICATE_ACTIVE_DETAIL
        ) from None
    return await _load_one(db, conflict.id, now)


@router.patch(
    "/conflicts/{conflict_id}/deactivate",
    dependencies=[Depends(require_candidate_write)],
)
async def deactivate_conflict(
    conflict_id: int,
    data: ConflictDeactivate,
    current_user: ManagerOrAdmin,
    db: AsyncSession = Depends(get_db),
):
    conflict = await db.scalar(
        select(CandidateConflict)
        .where(CandidateConflict.id == conflict_id)
        .with_for_update()
    )
    if not conflict:
        raise HTTPException(status_code=404, detail="Conflict not found")
    if not conflict.active:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=ALREADY_INACTIVE_DETAIL
        )
    now = datetime.now(timezone.utc)
    conflict.active = False
    conflict.deactivated_at = now
    conflict.deactivated_by = current_user.id
    conflict.deactivation_reason = data.reason
    db.add(
        Activity(
            entity_type="candidate",
            entity_id=conflict.candidate_id,
            action="conflict_deactivated",
            user_id=current_user.id,
            details={
                "conflict_id": conflict.id,
                "client_id": conflict.client_id,
                "type": conflict.type.value,
            },
        )
    )
    await mark_stale_for_candidate(db, conflict.candidate_id)
    await db.commit()
    payload = await _load_one(db, conflict_id, now)
    return {"ok": True, **payload}


# ── Rejestr ─────────────────────────────────────────────────────────────────

_STATES = ("active", "expired", "inactive", "all")


@router.get("/conflicts")
async def list_conflict_registry(
    current_user: CandidateSearchAccess,
    client_id: Optional[int] = None,
    candidate_id: Optional[int] = None,
    type: Optional[ConflictType] = None,
    active: bool = True,
    state: Annotated[
        Optional[str],
        Query(
            description=(
                "active | expired | inactive | all — nadpisuje ``active`` "
                "(``active=true`` = stan active, ``false`` = expired + inactive)."
            )
        ),
    ] = None,
    expiring_within_days: Annotated[Optional[int], Query(ge=1, le=365)] = None,
    q: Annotated[Optional[str], Query(max_length=200)] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
    db: AsyncSession = Depends(get_db),
):
    if state is not None and state not in _STATES:
        raise HTTPException(
            status_code=422,
            detail=f"Nieznany stan: {state}. Dozwolone: {', '.join(_STATES)}.",
        )
    # Ta sama granica co profil klienta: od 25.09.2026 DL widzi rejestr
    # wyłącznie klientów ze swojego portfela (także bez filtra klienta).
    delivery_client_ids = await resolve_delivery_lead_client_ids(current_user, db)
    if client_id is not None:
        assert_delivery_lead_client_visible(client_id, delivery_client_ids)

    now = datetime.now(timezone.utc)
    unexpired = active_unexpired_clause(now)
    filters = []
    if client_id is not None:
        filters.append(CandidateConflict.client_id == client_id)
    elif delivery_client_ids is not None:
        filters.append(
            CandidateConflict.client_id.in_(sorted(delivery_client_ids) or [-1])
        )
    if candidate_id is not None:
        filters.append(CandidateConflict.candidate_id == candidate_id)
    if type is not None:
        filters.append(CandidateConflict.type == type)

    effective_state = state or ("active" if active else "not_active")
    if expiring_within_days is not None:
        # „Wygasa w N dni" ma sens wyłącznie dla konfliktów jeszcze aktywnych.
        if state not in (None, "active", "all"):
            raise HTTPException(
                status_code=422,
                detail="Filtr „wygasa w N dni” dotyczy tylko aktywnych konfliktów.",
            )
        effective_state = "active"
        filters.append(
            CandidateConflict.expires_at <= now + timedelta(days=expiring_within_days)
        )
    if effective_state == "active":
        filters.append(unexpired)
    elif effective_state == "expired":
        filters.append(CandidateConflict.active.is_(True))
        filters.append(CandidateConflict.expires_at <= now)
    elif effective_state == "inactive":
        filters.append(CandidateConflict.active.is_(False))
    elif effective_state == "not_active":
        filters.append(not_(unexpired))

    if q and q.strip():
        term = q.strip()
        full_name = func.concat(Candidate.name, " ", Candidate.lastname)
        filters.append(
            or_(
                polish_folded_ilike(full_name, term),
                polish_folded_ilike(client_display_name_expression(), term),
            )
        )

    base = _enriched_select().where(*filters)
    total = await db.scalar(
        select(func.count())
        .select_from(CandidateConflict)
        .join(Candidate, Candidate.id == CandidateConflict.candidate_id)
        .outerjoin(Client, Client.id == CandidateConflict.client_id)
        .where(*filters)
    )
    if expiring_within_days is not None:
        order = (CandidateConflict.expires_at.asc(), CandidateConflict.id.asc())
    else:
        order = (CandidateConflict.created_at.desc(), CandidateConflict.id.desc())
    rows = (await db.execute(base.order_by(*order).limit(limit).offset(offset))).all()
    return {
        "items": [
            _conflict_to_dict(row, now=now, include_candidate=True) for row in rows
        ],
        "total": int(total or 0),
        "limit": limit,
        "offset": offset,
        "type_labels": dict(CONFLICT_TYPE_LABELS),
    }
