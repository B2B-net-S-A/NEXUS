"""Podobne rekrutacje, przepięcia i „Mamy championa" (migracja 0341).

* ``GET  /api/jobs/{id}/similar`` — połączone rekrutacje + sugestie systemu.
* ``POST /api/jobs/{id}/similar`` — połącz (oba kierunki) i od razu przepnij
  osoby wysłane wcześniej do klienta do „Do przejrzenia".
* ``GET  /api/jobs/{id}/similar/people?job_ids=`` — osoby wysłane do klienta
  w wybranych rekrutacjach (panel przepięć, 25.09.2026).
* ``GET  /api/jobs/{id}/similar/search?q=`` — wyszukiwarka rekrutacji do
  połączenia (także zamkniętych i z archiwum), z liczbą wysłanych.
* ``POST /api/jobs/{id}/similar/reassign`` — połącz i od razu dodaj wskazane
  osoby do „Nowych" (jeden klik zamiast „Biorę" przy każdej).
* ``DELETE /api/jobs/{id}/similar/{other_id}`` — rozłącz (propozycje zostają).
* ``POST /api/job-similarity/preview`` — sugestie dla rekrutacji jeszcze
  niezapisanej (strona „Nowa rekrutacja").
* ``POST /api/jobs/{id}/champion-found`` — Delivery Lead: „Mamy championa"
  (albo cofnięcie). Do tej chwili status requestu to „Szukamy".

Uwaga: moduł bez ``from __future__ import annotations`` — slowapi/FastAPI
czytają adnotacje ciała w czasie rejestracji trasy.
"""

from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import RecruiterPlus, get_db
from app.api.recruitment_access import ensure_job_membership
from app.api.section_access import PIPELINE_SECTION_DEPENDENCIES
from app.models.activity import Activity
from app.models.client import Client
from app.models.job import Job
from app.models.user import UserRole
from app.services import candidate_claim
from app.services import job_similarity as sim
from app.services.recruitment_allocation import allocation_lock
from app.services.request_allocation import restore_after_champion_removed

router = APIRouter(dependencies=PIPELINE_SECTION_DEPENDENCIES)

MAX_LINKS_PER_CALL = 20


async def _job(db: AsyncSession, user, job_id: int) -> Job:
    from app.api.candidate_search import (  # noqa: PLC0415
        _authorized_job,
        _search_access,
    )

    _search_access(user)
    return await _authorized_job(db, user, job_id)


async def _job_briefs(db: AsyncSession, job_ids: list[int]) -> dict[int, dict]:
    if not job_ids:
        return {}
    rows = (
        await db.execute(
            select(
                Job.id,
                Job.title,
                Job.reference_number,
                Job.status,
                Job.closed_at,
                func.coalesce(Client.display_name, Client.name),
            )
            .outerjoin(Client, Client.id == Job.client_id)
            .where(Job.id.in_(job_ids))
        )
    ).all()
    return {
        row[0]: {
            "id": row[0],
            "title": row[1],
            "reference_number": row[2],
            "status": row[3].value if hasattr(row[3], "value") else row[3],
            "closed_at": row[4],
            "client_name": row[5],
        }
        for row in rows
    }


async def _payload(db: AsyncSession, job: Job) -> dict:
    linked_ids = (await sim.linked_job_ids(db, [job.id])).get(job.id, [])
    suggestions = await sim.suggestions_for_job(db, job, exclude=linked_ids)
    ids = list({*linked_ids, *(p.id for p, _ in suggestions)})
    briefs = await _job_briefs(db, ids)
    sent = await sim.sent_counts(db, ids)
    scores = {p.id: score for p, score in suggestions}
    reassigned = (await sim.reassign_counts(db, [job.id])).get(job.id, 0)
    suggested_ids = [p.id for p, _ in suggestions]
    reassignable, reassignable_people = await sim.reassignable_counts(
        db, job.id, suggested_ids
    )

    def item(job_id: int, linked: bool) -> Optional[dict]:
        brief = briefs.get(job_id)
        if brief is None:
            return None
        return {
            **brief,
            "similarity": scores.get(job_id),
            "sent_count": sent.get(job_id, 0),
            "reassignable_count": reassignable.get(job_id, 0),
            "linked": linked,
        }

    return {
        "job_id": job.id,
        "reassigned_count": reassigned,
        # Różne osoby do przepięcia z niepołączonych podpowiedzi — nagłówek,
        # pasek w „Nowych” i „Najbliższy krok”.
        "reassignable_people": reassignable_people,
        "linked": [x for x in (item(i, True) for i in linked_ids) if x],
        "suggestions": [x for x in (item(p.id, False) for p, _ in suggestions) if x],
    }


@router.get("/jobs/{job_id}/similar")
async def get_similar_jobs(
    job_id: int, user: RecruiterPlus, db: AsyncSession = Depends(get_db)
):
    job = await _job(db, user, job_id)
    return await _payload(db, job)


class LinkSimilarBody(BaseModel):
    job_ids: list[int] = Field(..., min_length=1, max_length=MAX_LINKS_PER_CALL)


@router.post("/jobs/{job_id}/similar")
async def link_similar_jobs(
    job_id: int,
    body: LinkSimilarBody,
    user: RecruiterPlus,
    db: AsyncSession = Depends(get_db),
):
    job = await _job(db, user, job_id)
    await ensure_job_membership(db, user, job_id)
    wanted = sorted({i for i in body.job_ids if i != job_id})
    known = set((await db.execute(select(Job.id).where(Job.id.in_(wanted)))).scalars())
    missing = [i for i in wanted if i not in known]
    if missing:
        raise HTTPException(404, f"Nie ma rekrutacji: {', '.join(map(str, missing))}")
    # audyt 22.09 r2 (SEC-05): połączenie przepina osoby wysłane do klienta
    # w OBU kierunkach, więc wymaga dostępu także do drugiej rekrutacji —
    # inaczej rekruter spoza jej zespołu dostawał wgląd w jej wysłanych.
    for other_id in wanted:
        await _job(db, user, other_id)
        await ensure_job_membership(db, user, other_id)
    linked, reassigned = await sim.link_jobs(db, job_id, wanted, user_id=user.id)
    db.add(
        Activity(
            entity_type="job",
            entity_id=job_id,
            action="similar_jobs_linked",
            user_id=user.id,
            details={"job_ids": wanted, "reassigned": reassigned},
        )
    )
    await db.commit()
    payload = await _payload(db, job)
    return {**payload, "linked_now": linked, "reassigned_now": reassigned}


async def _other_jobs(
    db: AsyncSession, user, job_id: int, job_ids: list[int]
) -> list[int]:
    """Rekrutacje do połączenia: istnieją i są dostępne dla wołającego.

    Ta sama bramka co przy łączeniu (SEC-05) — lista osób wysłanych do
    klienta to wgląd w tamtą rekrutację."""
    wanted = list(dict.fromkeys(i for i in job_ids if i != job_id))
    if len(wanted) > MAX_LINKS_PER_CALL:
        raise HTTPException(422, f"Najwyżej {MAX_LINKS_PER_CALL} rekrutacji naraz.")
    known = set((await db.execute(select(Job.id).where(Job.id.in_(wanted)))).scalars())
    missing = [i for i in wanted if i not in known]
    if missing:
        raise HTTPException(404, f"Nie ma rekrutacji: {', '.join(map(str, missing))}")
    for other_id in wanted:
        await _job(db, user, other_id)
        await ensure_job_membership(db, user, other_id)
    return wanted


def _person_out(person: dict) -> dict:
    return {
        k: v for k, v in person.items() if k not in ("reassign_stage", "reassign_at")
    }


@router.get("/jobs/{job_id}/similar/people")
async def similar_jobs_people(
    job_id: int,
    user: RecruiterPlus,
    job_ids: list[int] = Query(..., min_length=1),
    db: AsyncSession = Depends(get_db),
):
    """Osoby wysłane do klienta w wybranych rekrutacjach — per rekrutacja."""
    await _job(db, user, job_id)
    wanted = await _other_jobs(db, user, job_id, job_ids)
    people = await sim.sent_people(db, job_id, wanted)
    return {
        "job_id": job_id,
        "jobs": [
            {"job_id": oid, "people": [_person_out(p) for p in people.get(oid, [])]}
            for oid in wanted
        ],
    }


_SEARCH_LIMIT = 10


def _like(term: str) -> str:
    escaped = term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


@router.get("/jobs/{job_id}/similar/search")
async def search_jobs_to_link(
    job_id: int,
    user: RecruiterPlus,
    q: str = Query("", max_length=120),
    db: AsyncSession = Depends(get_db),
):
    """Rekrutacje po tytule, kliencie albo numerze — także zamknięte i z
    archiwum Traffita (tam są osoby już wysłane), z liczbą wysłanych."""
    await _job(db, user, job_id)
    terms = [t for t in q.split() if t.strip()]
    if len(q.strip()) < 2 or not terms:
        return {"items": []}
    client_name = func.coalesce(Client.display_name, Client.name)
    conditions = [
        or_(
            Job.title.ilike(_like(term), escape="\\"),
            Job.reference_number.ilike(_like(term), escape="\\"),
            client_name.ilike(_like(term), escape="\\"),
        )
        for term in terms[:6]
    ]
    ids = list(
        (
            await db.execute(
                select(Job.id)
                .outerjoin(Client, Client.id == Job.client_id)
                .where(Job.id != job_id, and_(*conditions))
                .order_by(Job.created_at.desc().nulls_last(), Job.id.desc())
                .limit(_SEARCH_LIMIT)
            )
        ).scalars()
    )
    briefs = await _job_briefs(db, ids)
    sent = await sim.sent_counts(db, ids)
    linked = set((await sim.linked_job_ids(db, [job_id])).get(job_id, []))
    return {
        "items": [
            {
                **briefs[i],
                "similarity": None,
                "sent_count": sent.get(i, 0),
                "linked": i in linked,
            }
            for i in ids
            if i in briefs
        ]
    }


class ReassignBody(BaseModel):
    job_ids: list[int] = Field(..., min_length=1, max_length=MAX_LINKS_PER_CALL)
    candidate_ids: list[int] = Field(default_factory=list, max_length=100)


@router.post("/jobs/{job_id}/similar/reassign")
async def reassign_from_similar_jobs(
    job_id: int,
    body: ReassignBody,
    user: RecruiterPlus,
    db: AsyncSession = Depends(get_db),
):
    """Połącz rekrutacje i od razu przepnij wskazane osoby do „Nowych".

    Osoby muszą pochodzić z listy wysłanych do klienta w tych rekrutacjach
    (``selectable``) — tą trasą nie da się dodać nikogo spoza niej. Dodanie
    idzie tą samą ścieżką co „Biorę" (weto HM, czarna lista, blokada 12 h
    dla klikającego); pusta lista osób = samo połączenie.
    """
    from app.api.proposals_bulk import (  # noqa: PLC0415
        BulkProposalsResponse,
        add_candidates_to_job,
    )
    from app.services.pipeline_realtime import (  # noqa: PLC0415
        broadcast_pipeline_changed,
    )

    job = await _job(db, user, job_id)
    await ensure_job_membership(db, user, job_id)
    wanted = await _other_jobs(db, user, job_id, body.job_ids)
    if not wanted:
        raise HTTPException(422, "Wybierz rekrutację inną niż ta.")
    chosen = list(dict.fromkeys(body.candidate_ids))

    selected: list[dict] = []
    if chosen:
        people = await sim.sent_people(db, job_id, wanted)
        by_candidate: dict[int, dict] = {}
        for oid in wanted:
            for person in people.get(oid, []):
                if person["selectable"] and person["candidate_id"] not in by_candidate:
                    by_candidate[person["candidate_id"]] = {
                        **person,
                        "source_job_id": oid,
                    }
        refused = [cid for cid in chosen if cid not in by_candidate]
        if refused:
            raise HTTPException(
                422,
                "Tych osób nie da się przepiąć z wybranych rekrutacji "
                "(nie były wysłane do klienta, są zatrudnione albo już są "
                f"w tej rekrutacji): {', '.join(map(str, refused))}",
            )
        selected = [by_candidate[cid] for cid in chosen]

    linked_before = set((await sim.linked_job_ids(db, [job_id])).get(job_id, []))
    await sim.link_jobs(db, job_id, wanted, user_id=user.id)
    await sim.propose_selected(db, job_id, selected)
    result = None
    if selected:
        result = await add_candidates_to_job(
            db,
            job=job,
            candidate_ids=[p["candidate_id"] for p in selected],
            actor_user_id=user.id,
            initial_stage_legacy="new",
            entry_source=candidate_claim.ENTRY_ADDED_MANUAL,
            claim=True,
        )
    added = result.added if result else []
    db.add(
        Activity(
            entity_type="job",
            entity_id=job_id,
            action="similar_jobs_reassigned",
            user_id=user.id,
            details={
                "job_ids": wanted,
                "added": added,
                "skipped": [row.candidate_id for row in result.skipped]
                if result
                else [],
            },
        )
    )
    await db.commit()
    if added:
        await broadcast_pipeline_changed(db, job_id, user.id)
    response = BulkProposalsResponse(
        added=added,
        skipped=result.skipped if result else [],
        warnings=result.warnings if result else [],
        total_added=len(added),
        total_skipped=len(result.skipped) if result else 0,
    )
    return {
        **response.model_dump(),
        "linked_now": [oid for oid in wanted if oid not in linked_before],
    }


@router.delete("/jobs/{job_id}/similar/{other_id}")
async def unlink_similar_job(
    job_id: int,
    other_id: int,
    user: RecruiterPlus,
    db: AsyncSession = Depends(get_db),
):
    job = await _job(db, user, job_id)
    await ensure_job_membership(db, user, job_id)
    removed = await sim.unlink_jobs(db, job_id, other_id)
    if removed:
        db.add(
            Activity(
                entity_type="job",
                entity_id=job_id,
                action="similar_jobs_unlinked",
                user_id=user.id,
                details={"job_id": other_id},
            )
        )
    await db.commit()
    return await _payload(db, job)


class SimilarPreviewBody(BaseModel):
    title: str = Field("", max_length=300)
    must_skills: list[str] = Field(default_factory=list, max_length=60)
    competence_category_id: Optional[int] = None


class _Draft:
    """Rekrutacja jeszcze niezapisana — tyle, ile potrzebuje miara podobieństwa."""

    def __init__(self, body: SimilarPreviewBody) -> None:
        self.id = 0
        self.title = body.title
        self.must_skills = [s for s in body.must_skills if s.strip()]
        self.competence_category_id = body.competence_category_id
        self.client_id = None
        self.reference_number = None
        self.status = None
        self.created_at = None


@router.post("/job-similarity/preview")
async def preview_similar_jobs(
    body: SimilarPreviewBody,
    user: RecruiterPlus,
    db: AsyncSession = Depends(get_db),
):
    if not body.title.strip() and not body.must_skills:
        return {"suggestions": []}
    suggestions = await sim.suggestions_for_job(db, _Draft(body))
    ids = [p.id for p, _ in suggestions]
    briefs = await _job_briefs(db, ids)
    sent = await sim.sent_counts(db, ids)
    return {
        "suggestions": [
            {
                **briefs[p.id],
                "similarity": score,
                "sent_count": sent.get(p.id, 0),
                "linked": False,
            }
            for p, score in suggestions
            if p.id in briefs
        ]
    }


class ChampionFoundBody(BaseModel):
    found: bool = True


_CHAMPION_ROLES = (UserRole.admin, UserRole.delivery_lead, UserRole.head_of_recruitment)


@router.post("/jobs/{job_id}/champion-found")
async def set_champion_found(
    job_id: int,
    body: ChampionFoundBody,
    user: RecruiterPlus,
    db: AsyncSession = Depends(get_db),
):
    if not user.has_any_role(*_CHAMPION_ROLES):
        raise HTTPException(
            403,
            "„Mamy championa” oznacza Delivery Lead (albo admin / Head of Recruitment).",
        )
    await _job(db, user, job_id)
    await ensure_job_membership(db, user, job_id)
    # Kolejność blokad jak na pulpicie: przydział → rekrutacja.
    await allocation_lock(db)
    job = await db.get(Job, job_id, with_for_update=True)
    if job is None:
        raise HTTPException(404, "Rekrutacja nie istnieje")
    changed = (job.champion_found_at is not None) != body.found
    if changed:
        now = datetime.now(timezone.utc)
        champion_since = job.champion_found_at
        job.champion_found_at = now if body.found else None
        job.champion_found_by = user.id if body.found else None
        # Runda 8 (R8-N7-5): „Mamy championa” to widoczna zmiana stanu
        # requestu — ręczne zdjęcia sprzed niej przestają blokować powrót
        # osoby, a jego zdjęcie przywraca ludzi dodanych ręcznie.
        job.work_state_changed_at = now
        if not body.found:
            await restore_after_champion_removed(
                db, job_id=job_id, champion_since=champion_since, now=now
            )
        db.add(
            Activity(
                entity_type="job",
                entity_id=job_id,
                action="champion_found_changed",
                user_id=user.id,
                details={"found": body.found},
            )
        )
    await db.commit()
    return {
        "job_id": job_id,
        "champion_found": job.champion_found_at is not None,
        "champion_found_at": job.champion_found_at,
        "changed": changed,
    }
