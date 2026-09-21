"""Skrzynka „Propozycje" rekrutacji (migracja 0333).

Ścieżka to ``/api/jobs/{job_id}/proposal-inbox`` — NIE ``…/proposals``: tamten
adres od dawna zwraca historię migawek propozycji (``app/api/proposals.py``,
konsument w ``frontend/src/lib/api.ts``), więc druga trasa GET pod tą samą
ścieżką byłaby martwa albo zepsułaby tamten ekran.

Dostęp: lista jest czytelna jak wyniki pełnego przeglądu bazy
(``_authorized_job`` — odczyt sekcji Pipeline + zakres klient–TAC Delivery
Leada). „Pomiń" zmienia skrzynkę CAŁEGO zespołu (i licznik na liście
rekrutacji), więc wymaga tego, czego wymaga dodanie kandydata do rekrutacji:
``RecruiterPlus`` + członkostwo w zespole. „Pomiń" działa też dla osoby, której
skrzynka nie zna (wyszukiwarka, rekomendacja) — wiersz powstaje od razu jako
pominięty. Pominięta osoba wraca z nową wersją CV albo przez „Cofnij"
(``…/restore``, ta sama bramka). Nie ma znacznika „widziane" per użytkownik.
"""

from datetime import datetime, timezone
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentUser, RecruiterPlus, get_db
from app.api.recruitment_access import ensure_job_membership
from app.api.section_access import PIPELINE_SECTION_DEPENDENCIES
from app.models.candidate import Candidate
from app.services import job_proposals as proposals

router = APIRouter(dependencies=PIPELINE_SECTION_DEPENDENCIES)

# Lustro CHECK-a `ck_job_proposals_source` (`JOB_PROPOSAL_SOURCES`).
ProposalSource = Literal[
    "full_base", "new_cv", "similar_projects", "recommendation", "marketplace"
]


async def _job(db, user, job_id: int):
    from app.api.candidate_search import (  # noqa: PLC0415
        _authorized_job,
        _search_access,
    )

    _search_access(user)
    return await _authorized_job(db, user, job_id)


def _candidate_brief(candidate: Candidate, *, include_finance: bool) -> dict:
    """Tożsamość węższa niż profil — jak wiersz pełnego przeglądu (bez kontaktu)."""
    availability = candidate.availability_status
    rate = candidate.expected_rate_hourly
    return {
        "id": candidate.id,
        "name": candidate.name,
        "lastname": candidate.lastname,
        "title": candidate.linkedin_current_title,
        "city": candidate.city or candidate.location,
        "availability_status": availability.value if availability else None,
        "availability_date": (
            candidate.availability_date.isoformat()
            if candidate.availability_date
            else None
        ),
        # Stawka z profilu (PLN/h) — tylko dla ról z odczytem finansów; klucz
        # zostaje, żeby „—" nie czytało się jak brak pola w odpowiedzi.
        "expected_rate_hourly": (
            float(rate) if include_finance and rate is not None else None
        ),
        "expected_rate_redacted": not include_finance,
    }


@router.get("/jobs/{job_id}/proposal-inbox")
async def list_job_proposals(
    job_id: int,
    user: CurrentUser,
    status: Literal["proposed", "dismissed", "added"] = "proposed",
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
):
    from app.analytics.capabilities import (  # noqa: PLC0415
        AnalyticsCapability,
        user_has_capability,
    )
    from app.services.candidate_job_eligibility import Visibility  # noqa: PLC0415
    from app.services.eligibility_annotation import (  # noqa: PLC0415
        eligibility_annotation,
    )
    from app.services.pipeline_eligibility import (  # noqa: PLC0415
        evaluate_candidates_for_job,
    )

    job = await _job(db, user, job_id)
    rows, total = await proposals.list_for_job(
        db, job_id=job_id, status=status, limit=limit, offset=offset
    )
    ids = [row.candidate_id for row in rows]
    candidates = {
        c.id: c
        for c in (
            (await db.execute(select(Candidate).where(Candidate.id.in_(ids))))
            .scalars()
            .all()
            if ids
            else []
        )
    }
    # Te same bramki widoczności co wyniki przeglądu: globalna czarna lista
    # chowa osobę, konflikt z klientem / weto HM jadą jako plakietka.
    decisions = (
        await evaluate_candidates_for_job(
            db,
            job=job,
            candidate_ids=list(candidates),
            now=datetime.now(timezone.utc),
        )
        if candidates and status == "proposed"
        else {}
    )
    include_finance = user_has_capability(user, AnalyticsCapability.VIEW_FINANCE)
    items = []
    hidden = 0
    for row in rows:
        candidate = candidates.get(row.candidate_id)
        if candidate is None:
            continue
        decision = decisions.get(row.candidate_id)
        if decision is not None and decision.visibility == Visibility.hidden:
            hidden += 1
            continue
        items.append(
            {
                "candidate": _candidate_brief(
                    candidate, include_finance=include_finance
                ),
                "sources": row.sources,
                "score": row.score,
                "evidence": row.evidence,
                "first_seen_at": row.first_seen_at,
                "last_seen_at": row.last_seen_at,
                "is_new": row.is_new,
                "status": row.status,
                "run_id": row.run_id,
                "eligibility": (
                    eligibility_annotation(decision) if decision is not None else None
                ),
            }
        )
    return {
        "job_id": job_id,
        "status": status,
        "items": items,
        "total": total,
        "hidden_on_page": hidden,
        "limit": limit,
        "offset": offset,
        "next_offset": offset + limit if offset + limit < total else None,
    }


class DismissProposalBody(BaseModel):
    """Skąd przyszło „Pomiń" osoby, której skrzynka jeszcze nie zna."""

    source: ProposalSource = "full_base"


async def _writable_pair(db, user, job_id: int, candidate_id: int) -> Candidate:
    """Bramka zapisu skrzynki + istnienie kandydata (404)."""
    await _job(db, user, job_id)
    await ensure_job_membership(db, user, job_id)
    candidate = await db.get(Candidate, candidate_id)
    if candidate is None:
        raise HTTPException(404, "Kandydat nie istnieje")
    return candidate


@router.post("/jobs/{job_id}/proposal-inbox/{candidate_id}/dismiss")
async def dismiss_job_proposal(
    job_id: int,
    candidate_id: int,
    user: RecruiterPlus,
    body: Optional[DismissProposalBody] = None,
    db: AsyncSession = Depends(get_db),
):
    from app.services.auto_match_outbox import candidate_revision  # noqa: PLC0415

    candidate = await _writable_pair(db, user, job_id, candidate_id)
    if await proposals.is_in_pipeline(db, job_id=job_id, candidate_id=candidate_id):
        raise HTTPException(
            409, "Ta osoba jest już w tej rekrutacji — nie można jej pominąć."
        )
    # Wersja CV w chwili „Pomiń": nowa wersja zaproponuje tę osobę ponownie.
    revision = candidate_revision(candidate)
    changed = await proposals.dismiss(
        db,
        job_id=job_id,
        candidate_id=candidate_id,
        user_id=user.id,
        cv_revision=revision,
    )
    if not changed:
        from app.models.job_proposal import JobProposal  # noqa: PLC0415

        known = await db.scalar(
            select(JobProposal.id)
            .where(
                JobProposal.job_id == job_id,
                JobProposal.candidate_id == candidate_id,
            )
            .limit(1)
        )
        if known is None:
            # Osoba spoza skrzynki (wyszukiwarka, rekomendacja): wiersz powstaje
            # od razu jako pominięty. Przegrany wyścig z zapisem przeglądu
            # (konflikt pary+źródła) domyka zwykłe „Pomiń".
            changed = await proposals.dismiss_unlisted(
                db,
                job_id=job_id,
                candidate_id=candidate_id,
                user_id=user.id,
                source=(body or DismissProposalBody()).source,
                cv_revision=revision,
            ) or await proposals.dismiss(
                db,
                job_id=job_id,
                candidate_id=candidate_id,
                user_id=user.id,
                cv_revision=revision,
            )
        # Inaczej idempotentne: druga próba albo wiersze `added` — nic do zrobienia.
    await db.commit()
    return {"job_id": job_id, "candidate_id": candidate_id, "dismissed": changed}


@router.post("/jobs/{job_id}/proposal-inbox/{candidate_id}/restore")
async def restore_job_proposal(
    job_id: int,
    candidate_id: int,
    user: RecruiterPlus,
    db: AsyncSession = Depends(get_db),
):
    """„Cofnij" po „Pomiń" — osoba wraca do skrzynki całego zespołu."""
    await _writable_pair(db, user, job_id, candidate_id)
    restored = await proposals.restore(db, job_id=job_id, candidate_id=candidate_id)
    await db.commit()
    return {"job_id": job_id, "candidate_id": candidate_id, "restored": restored}
