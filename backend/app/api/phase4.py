"""
Phase 4 endpoints:

- CRUD  /api/saved-searches       named filter presets per user
- GET   /api/match-history/{job_id}/{candidate_id}   audit row
- POST  /api/match-history         append audit row (internal-use; optional)
"""

from __future__ import annotations

from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.candidate_access import CandidateSearchAccess, CandidateWriteAccess
from app.api.deps import AdminUser
from app.core.database import get_db
from app.models.saved_search import MatchHistory, SavedSearch
from app.services.candidate_monthly_rate_retirement import (
    RETIRED_MONTHLY_RATE_CODE,
    sanitize_candidate_saved_search,
)

router = APIRouter()


# ── Saved searches ──────────────────────────────────────────────────────────


class SavedSearchCreate(BaseModel):
    name: str = Field(..., max_length=100)
    entity: str = Field(..., max_length=40)
    filters: dict
    shared: bool = False
    description: Optional[str] = Field(None, max_length=255)
    pinned_to_job_id: Optional[int] = None
    # Alert subscription — wymaga ``filters["api"]`` (parametry GET
    # /api/candidates wyliczone przez FE), bo skaner w tle odtwarza search
    # przez realny endpoint. Patrz app/tasks/saved_search_alerts.py.
    notify_new_matches: bool = False


class SavedSearchUpdate(BaseModel):
    name: Optional[str] = None
    filters: Optional[dict] = None
    shared: Optional[bool] = None
    description: Optional[str] = None
    # ``None`` means "no change"; pass ``0`` to clear (special-cased below).
    pinned_to_job_id: Optional[int] = None
    notify_new_matches: Optional[bool] = None
    confirm_reapproval: bool = False
    # Tylko z `confirm_reapproval` dla zapisu wstrzymanego przez migrację
    # semantyki: "accept" (domyślnie) = zatwierdź nowe wyniki; "keep_legacy" =
    # „Zostaw po staremu" — wraca oryginalny ładunek, zapis zostaje przy v1.
    reapproval_choice: Optional[Literal["accept", "keep_legacy"]] = None


class SavedSearchOut(BaseModel):
    id: int
    user_id: int
    name: str
    entity: str
    filters: dict
    shared: bool
    description: Optional[str]
    pinned_to_job_id: Optional[int] = None
    requires_reapproval: bool = False
    created_at: str
    updated_at: str

    model_config = {"from_attributes": True}


def _ss_to_dict(s: SavedSearch) -> dict:
    return {
        "id": s.id,
        "user_id": s.user_id,
        "name": s.name,
        "entity": s.entity,
        "filters": s.filters or {},
        "shared": s.shared,
        "description": s.description,
        "pinned_to_job_id": s.pinned_to_job_id,
        "notify_new_matches": s.notify_new_matches,
        "requires_reapproval": s.requires_reapproval,
        "unseen_count": s.unseen_count or 0,
        "last_viewed_at": s.last_viewed_at.isoformat() if s.last_viewed_at else None,
        "created_at": s.created_at.isoformat() if s.created_at else None,
        "updated_at": s.updated_at.isoformat() if s.updated_at else None,
    }


def _has_api_params(filters: Optional[dict]) -> bool:
    """Czy skaner alertów umie odtworzyć ten zapis przez listę kandydatów:
    legacy `filters.api` albo format v3 bez filtrów, których lista nie zna."""
    from app.tasks.saved_search_alerts import alert_list_params

    return alert_list_params(filters) is not None


def _is_candidate_entity(entity: str) -> bool:
    """Accept the legacy singular spelling while new clients use plural."""

    return entity in {"candidate", "candidates"}


@router.get("/saved-searches")
async def list_saved_searches(
    current_user: CandidateSearchAccess,
    entity: Optional[str] = Query(None),
    pinned_to_job_id: Optional[int] = Query(
        None,
        description=(
            "Filter to searches pinned to this job (plus the user's own global"
            " ones). Used by the 'Wyszukaj manualnie' tab in /jobs/[id]."
        ),
    ),
    only_mine: bool = Query(
        False, description="If true, exclude shared-by-others entries."
    ),
    db: AsyncSession = Depends(get_db),
):
    """List my saved searches + ones shared by others (optionally by entity).

    When ``pinned_to_job_id`` is set, returns the union of:

    * the user's searches with ``pinned_to_job_id == job_id``, plus
    * the user's own global searches (``pinned_to_job_id IS NULL``), plus
    * OTHER users' **shared** searches pinned to this job — this is how the
      DL-approved "rekomendowane wyszukiwanie" (champion profile) reaches
      every recruiter opening the job.

    Pass ``only_mine=true`` for the my-rows-only view in the global list.
    """
    from sqlalchemy import and_, or_

    q = select(SavedSearch)

    if pinned_to_job_id is not None:
        q = q.where(
            or_(
                and_(
                    SavedSearch.user_id == current_user.id,
                    or_(
                        SavedSearch.pinned_to_job_id == pinned_to_job_id,
                        SavedSearch.pinned_to_job_id.is_(None),
                    ),
                ),
                and_(
                    SavedSearch.shared.is_(True),
                    SavedSearch.pinned_to_job_id == pinned_to_job_id,
                ),
            )
        )
    elif only_mine:
        q = q.where(SavedSearch.user_id == current_user.id)
    else:
        q = q.where(
            or_(
                SavedSearch.user_id == current_user.id,
                SavedSearch.shared.is_(True),
            )
        )

    if entity:
        q = q.where(SavedSearch.entity == entity)
    q = q.order_by(SavedSearch.updated_at.desc())
    rows = (await db.execute(q)).scalars().all()
    sanitized_any = False
    for row in rows:
        if not _is_candidate_entity(row.entity):
            continue
        sanitized, retired_criteria_removed = sanitize_candidate_saved_search(
            row.filters or {}
        )
        if not retired_criteria_removed:
            continue
        row.filters = sanitized
        row.notify_new_matches = False
        row.requires_reapproval = True
        sanitized_any = True
    if sanitized_any:
        await db.commit()
    return [_ss_to_dict(r) for r in rows]


@router.post("/saved-searches", status_code=status.HTTP_201_CREATED)
async def create_saved_search(
    data: SavedSearchCreate,
    current_user: CandidateWriteAccess,
    db: AsyncSession = Depends(get_db),
):
    # Soft cap so a single user can't fill the table with thousands of saved
    # filter presets — matches the planning brief constraint.
    SAVED_SEARCH_PER_USER_CAP = 50
    from sqlalchemy import func as _func

    existing_count = (
        await db.execute(
            select(_func.count(SavedSearch.id)).where(
                SavedSearch.user_id == current_user.id
            )
        )
    ).scalar() or 0
    if existing_count >= SAVED_SEARCH_PER_USER_CAP:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"Limit zapisanych wyszukiwań ({SAVED_SEARCH_PER_USER_CAP})"
                " osiągnięty. Usuń któreś, aby utworzyć nowe."
            ),
        )

    filters = data.filters
    retired_criteria_removed = False
    if _is_candidate_entity(data.entity):
        filters, retired_criteria_removed = sanitize_candidate_saved_search(filters)

    ss = SavedSearch(
        user_id=current_user.id,
        name=data.name,
        entity=data.entity,
        filters=filters,
        shared=data.shared,
        description=data.description,
        pinned_to_job_id=data.pinned_to_job_id,
        notify_new_matches=data.notify_new_matches and not retired_criteria_removed,
        requires_reapproval=retired_criteria_removed,
    )
    if retired_criteria_removed:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=RETIRED_MONTHLY_RATE_CODE,
        )
    if data.notify_new_matches:
        if not _has_api_params(data.filters):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    "Alert wymaga parametrów API w filters.api — zapisz"
                    " wyszukiwanie ponownie z aktualnej wersji aplikacji."
                ),
            )
        # V2: leave ``last_scanned_at`` NULL → the scanner's first pass seeds the
        # dedup log with current matchers (no alert) so only genuine transitions
        # into the match set fire later. Anchor the "Nowy" highlight to now so
        # the first notification click highlights exactly the alerted rows.
        from datetime import datetime, timezone

        ss.last_scanned_at = None
        ss.last_viewed_at = datetime.now(timezone.utc)
    db.add(ss)
    await db.commit()
    await db.refresh(ss)
    return _ss_to_dict(ss)


@router.patch("/saved-searches/{search_id}")
async def update_saved_search(
    search_id: int,
    data: SavedSearchUpdate,
    current_user: CandidateWriteAccess,
    db: AsyncSession = Depends(get_db),
):
    ss = await db.scalar(
        select(SavedSearch).where(
            SavedSearch.id == search_id, SavedSearch.user_id == current_user.id
        )
    )
    if not ss:
        raise HTTPException(status_code=404, detail="Search not found")
    payload = data.model_dump(exclude_unset=True)
    confirm_reapproval = bool(payload.pop("confirm_reapproval", False))
    reapproval_choice = payload.pop("reapproval_choice", None) or "accept"
    if "filters" in payload and _is_candidate_entity(ss.entity):
        sanitized, retired_criteria_removed = sanitize_candidate_saved_search(
            payload["filters"]
        )
        if retired_criteria_removed:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=RETIRED_MONTHLY_RATE_CODE,
            )
        payload["filters"] = sanitized
    for k, v in payload.items():
        setattr(ss, k, v)
    if confirm_reapproval:
        _, still_retired = sanitize_candidate_saved_search(ss.filters or {})
        if still_retired:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=RETIRED_MONTHLY_RATE_CODE,
            )
        ss.requires_reapproval = False
        # Zapis wstrzymany przez migrację na wspólną semantykę filtrów
        # (`saved_search_migration`): akceptacja WZNAWIA alert, który był
        # włączony, i zeruje linię bazową — pierwszy przebieg skanera zasieje
        # dziennik aktualnym (nowym) zbiorem bez powiadomienia, więc zmiana
        # semantyki nie kończy się burzą „nowych" kandydatów.
        migration = dict((ss.filters or {}).get("migration") or {})
        if migration:
            from datetime import datetime, timezone

            from app.services.saved_search_payload import restore_legacy_payload

            resume = bool(migration.get("alert_was_on")) and (
                "notify_new_matches" not in payload
            )
            legacy = (
                restore_legacy_payload(ss.filters or {})
                if reapproval_choice == "keep_legacy"
                else None
            )
            if reapproval_choice == "keep_legacy" and legacy is None:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="saved_search_has_no_legacy_payload",
                )
            if legacy is not None:
                # „Zostaw po staremu": wraca oryginał, zapis zostaje przy v1 —
                # zbiór się NIE zmienia, więc linia bazowa alertu zostaje.
                ss.filters = legacy
                if resume:
                    ss.notify_new_matches = True
            else:
                if resume:
                    ss.notify_new_matches = True
                    ss.last_scanned_at = None
                    ss.unseen_count = 0
                migration["alert_was_on"] = False
                migration["reapproved_at"] = datetime.now(timezone.utc).isoformat()
                ss.filters = {**(ss.filters or {}), "migration": migration}
    if payload.get("notify_new_matches") is True and ss.requires_reapproval:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="saved_search_requires_reapproval",
        )
    # Validate only when THIS request turns alerts on — a rename of an old
    # search (filters without `api`) must not 400. A stale enabled search
    # without api params is simply skipped by the scanner.
    if payload.get("notify_new_matches") is True:
        if not _has_api_params(ss.filters):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    "Alert wymaga parametrów API w filters.api — włącz dzwonek"
                    " ponownie z aktualnej wersji aplikacji."
                ),
            )
        # V2: re-baseline on every enable — clear the watermark so the scanner
        # re-seeds the dedup log with current matchers (idempotent: ON CONFLICT
        # DO NOTHING) and never floods about candidates that already match.
        ss.last_scanned_at = None
        if ss.last_viewed_at is None:
            from datetime import datetime, timezone

            ss.last_viewed_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(ss)
    return _ss_to_dict(ss)


@router.post("/saved-searches/{search_id}/viewed")
async def mark_saved_search_viewed(
    search_id: int,
    current_user: CandidateWriteAccess,
    db: AsyncSession = Depends(get_db),
):
    """Owner opened the saved search — reset the unseen badge and roll
    ``last_viewed_at`` forward. Returns the PREVIOUS ``last_viewed_at`` so the
    FE can highlight candidates created after it as "Nowy" (comparing against
    the new value would instantly un-highlight everything)."""
    from datetime import datetime, timezone

    ss = await db.scalar(
        select(SavedSearch).where(
            SavedSearch.id == search_id, SavedSearch.user_id == current_user.id
        )
    )
    if not ss:
        raise HTTPException(status_code=404, detail="Search not found")
    from app.models.saved_search_alert_log import SavedSearchAlertLog

    previous = ss.last_viewed_at.isoformat() if ss.last_viewed_at else None
    # Kto WSZEDŁ do wyniku od ostatniego otwarcia — także osoba, która była w
    # bazie wcześniej, a zaczęła pasować po nowym CV albo notatce (log skanera
    # alertów). Samo `created_at` gubiło właśnie tych ludzi.
    new_rows = select(SavedSearchAlertLog.candidate_id).where(
        SavedSearchAlertLog.saved_search_id == ss.id,
        SavedSearchAlertLog.notified_at.is_not(None),
    )
    if ss.last_viewed_at is not None:
        new_rows = new_rows.where(SavedSearchAlertLog.notified_at > ss.last_viewed_at)
    new_ids = [
        row[0]
        for row in (
            await db.execute(
                new_rows.order_by(SavedSearchAlertLog.notified_at.desc()).limit(500)
            )
        ).all()
    ]
    ss.last_viewed_at = datetime.now(timezone.utc)
    ss.unseen_count = 0
    await db.commit()
    return {"previous_viewed_at": previous, "new_candidate_ids": new_ids}


@router.delete("/saved-searches/{search_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_saved_search(
    search_id: int,
    current_user: CandidateWriteAccess,
    db: AsyncSession = Depends(get_db),
):
    ss = await db.scalar(
        select(SavedSearch).where(
            SavedSearch.id == search_id, SavedSearch.user_id == current_user.id
        )
    )
    if not ss:
        raise HTTPException(status_code=404, detail="Search not found")
    await db.delete(ss)
    await db.commit()


# ── Match history ───────────────────────────────────────────────────────────


@router.get("/match-history/{job_id}/{candidate_id}")
async def get_match_history(
    job_id: int,
    candidate_id: int,
    current_user: CandidateSearchAccess,
    limit: int = Query(10, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
):
    rows = await db.execute(
        select(MatchHistory)
        .where(
            MatchHistory.job_id == job_id,
            MatchHistory.candidate_id == candidate_id,
        )
        .order_by(MatchHistory.created_at.desc())
        .limit(limit)
    )
    return [
        {
            "id": r.id,
            "job_id": r.job_id,
            "candidate_id": r.candidate_id,
            "total_score": r.total_score,
            "breakdown": r.breakdown,
            "triggered_by": r.triggered_by,
            "created_at": r.created_at.isoformat() if r.created_at else None,
        }
        for r in rows.scalars().all()
    ]


class MatchHistoryCreate(BaseModel):
    job_id: int
    candidate_id: int
    total_score: int
    breakdown: Optional[dict] = None


@router.post("/match-history", status_code=status.HTTP_201_CREATED)
async def log_match(
    data: MatchHistoryCreate,
    current_user: CandidateWriteAccess,
    db: AsyncSession = Depends(get_db),
):
    mh = MatchHistory(
        job_id=data.job_id,
        candidate_id=data.candidate_id,
        total_score=data.total_score,
        breakdown=data.breakdown,
        triggered_by=current_user.id,
    )
    db.add(mh)
    await db.commit()
    await db.refresh(mh)
    return {
        "id": mh.id,
        "created_at": mh.created_at.isoformat() if mh.created_at else None,
    }


@router.post("/saved-searches/migrate-semantics")
async def migrate_saved_search_semantics(
    current_user: AdminUser,
    dry_run: bool = Query(
        False,
        description="Policz, ile zapisów zmieniłoby wynik — bez żadnego zapisu.",
    ),
):
    """Migracja zapisanych wyszukiwań kandydatów na wspólną semantykę filtrów.

    Idempotentna (zapis w formacie v3 jest pomijany). Zapisy, których wynik się
    zmienia, dostają `requires_reapproval`, wstrzymany alert i jedno
    powiadomienie dla właściciela. Odpowiedź niesie wyłącznie liczniki i id.
    """
    from app.services.saved_search_migration import (
        migrate_saved_searches,
        write_receipt,
    )

    summary = await migrate_saved_searches(dry_run=dry_run)
    if not dry_run:
        await write_receipt({**summary, "triggered_by": current_user.id})
    return summary
