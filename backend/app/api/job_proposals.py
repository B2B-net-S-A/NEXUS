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

``…/proposal-inbox/opened`` (07.10.2026) zapisuje otwarcie skrzynki
(``Activity proposal_inbox_opened``, raz na osobę/rekrutację/dzień).

``…/proposal-counts`` (02.10.2026) dzieli otwarte propozycje na świeże
z ogłoszeń (nowe CV, portale) i resztę — te same pary co lista skrzynki.

Od 30.09.2026 (0405) „Pomiń" wymaga powodu (``reason`` ze słownika
``DISMISS_REASONS``, przy „other" także ``note``) — powód trafia do wiersza,
telemetrii ``reject`` i raportu „Propozycje AI" w Insights.
"""

import logging
from datetime import datetime, timedelta, timezone
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentUser, RecruiterPlus, get_db
from app.api.recruitment_access import ensure_job_membership
from app.api.section_access import PIPELINE_SECTION_DEPENDENCIES
from app.models.candidate import Candidate
from app.services import job_proposals as proposals
from app.services.job_proposal_feedback_schema import DISMISS_NOTE_MAX
from app.services.candidate_rate_from import rate_summary

logger = logging.getLogger(__name__)

router = APIRouter(dependencies=PIPELINE_SECTION_DEPENDENCIES)

# Telemetria otwarcia skrzynki (07.10.2026) — ile osób w ogóle patrzy na
# „Propozycje z bazy” (do tego dnia nie wiedzieliśmy, czy brak decyzji to
# złe propozycje, czy nieotwierana zakładka).
PROPOSAL_INBOX_OPENED = "proposal_inbox_opened"

# Lustro CHECK-a `ck_job_proposals_source` (`JOB_PROPOSAL_SOURCES`).
ProposalSource = Literal[
    "full_base",
    "new_cv",
    "similar_projects",
    "recommendation",
    "marketplace",
    "reassign",
    "trainee",
    "job_board",
]


async def _reassign_sources(db, job_id: int, candidate_ids: list[int]) -> dict:
    """Przepięcie: skąd osoba przychodzi (rekrutacja, etap, data wysłania)."""
    from app.models.client import Client  # noqa: PLC0415
    from app.models.job import Job  # noqa: PLC0415
    from app.models.job_proposal import JobProposal  # noqa: PLC0415

    if not candidate_ids:
        return {}
    rows = (
        await db.execute(
            select(JobProposal.candidate_id, JobProposal.evidence).where(
                JobProposal.job_id == job_id,
                JobProposal.source == "reassign",
                JobProposal.candidate_id.in_(candidate_ids),
            )
        )
    ).all()
    info = {
        cid: (ev or {}).get("reassign") or {}
        for cid, ev in rows
        if isinstance((ev or {}).get("reassign"), dict)
    }
    source_ids = {v.get("job_id") for v in info.values() if v.get("job_id")}
    jobs = {}
    if source_ids:
        for jid, title, ref, client in (
            await db.execute(
                select(
                    Job.id,
                    Job.title,
                    Job.reference_number,
                    func.coalesce(Client.display_name, Client.name),
                )
                .outerjoin(Client, Client.id == Job.client_id)
                .where(Job.id.in_(source_ids))
            )
        ).all():
            jobs[jid] = {
                "job_id": jid,
                "title": title,
                "reference_number": ref,
                "client_name": client,
            }
    out = {}
    for cid, value in info.items():
        base = jobs.get(value.get("job_id"))
        if base is None:
            continue
        out[cid] = {
            **base,
            "stage": value.get("stage"),
            "sent_at": value.get("sent_at"),
        }
    return out


async def _trainee_handovers(db, job_id: int, candidate_ids: list[int]) -> dict:
    """0374: kto z praktykantów przekazał osobę i co napisał rekruterowi."""
    from app.models.job_proposal import JobProposal  # noqa: PLC0415
    from app.models.user import User  # noqa: PLC0415

    if not candidate_ids:
        return {}
    rows = (
        await db.execute(
            select(
                JobProposal.candidate_id,
                JobProposal.evidence,
                JobProposal.last_seen_at,
            ).where(
                JobProposal.job_id == job_id,
                JobProposal.source == "trainee",
                JobProposal.candidate_id.in_(candidate_ids),
            )
        )
    ).all()
    info = {
        cid: ((ev or {}).get("trainee") or {}, seen)
        for cid, ev, seen in rows
        if isinstance((ev or {}).get("trainee"), dict)
    }
    user_ids = {v.get("user_id") for v, _ in info.values() if v.get("user_id")}
    names = (
        dict(
            (await db.execute(select(User.id, User.name).where(User.id.in_(user_ids))))
            .tuples()
            .all()
        )
        if user_ids
        else {}
    )
    return {
        cid: {
            "by_name": names.get(value.get("user_id")),
            "note": value.get("note"),
            "at": seen.isoformat() if seen else None,
            # Kandydat deklaruje wyłącznie umowę o pracę — ostrzeżenie, nie blokada.
            "employment_only": bool(value.get("employment_only")),
        }
        for cid, (value, seen) in info.items()
    }


async def _job(db, user, job_id: int):
    from app.api.candidate_search import (  # noqa: PLC0415
        _authorized_job,
        _search_access,
    )

    _search_access(user)
    return await _authorized_job(db, user, job_id)


def _candidate_brief(candidate: Candidate) -> dict:
    """Tożsamość węższa niż profil — jak wiersz pełnego przeglądu (bez kontaktu)."""
    availability = candidate.availability_status
    # „Stawka od” (0414) — ta sama liczba, z którą porównuje plakietka budżetu.
    rate = rate_summary(candidate)["rate_from_hourly"]
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
        # Stawka KANDYDATA (PLN/h) jest jawna dla każdej roli — jak na profilu
        # i liście (decyzja Artura 27.09.2026, R10-N7-10). Stawka DO KLIENTA
        # tu nie występuje. Klucz `expected_rate_redacted` zostaje w kształcie.
        "expected_rate_hourly": float(rate) if rate is not None else None,
        "expected_rate_redacted": False,
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
    reassign_from = await _reassign_sources(db, job_id, ids)
    trainee_handover = await _trainee_handovers(db, job_id, ids)
    # „Z ogłoszeń w ostatnich dniach” — to samo okno co domyślny podział
    # licznika (`…/proposal-counts`), liczone zegarem serwera.
    posting_since = datetime.now(timezone.utc) - timedelta(
        days=proposals.POSTING_RECENT_DAYS
    )
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
                "candidate": _candidate_brief(candidate),
                "sources": row.sources,
                "score": row.score,
                "evidence": row.evidence,
                "first_seen_at": row.first_seen_at,
                "last_seen_at": row.last_seen_at,
                "is_new": row.is_new,
                "posting_seen_at": row.posting_seen_at,
                "posting_recent": (
                    row.posting_seen_at is not None
                    and row.posting_seen_at >= posting_since
                ),
                "status": row.status,
                "run_id": row.run_id,
                "eligibility": (
                    eligibility_annotation(decision) if decision is not None else None
                ),
                "reassign_from": reassign_from.get(row.candidate_id),
                "trainee_handover": trainee_handover.get(row.candidate_id),
            }
        )
    # Runda 10 (R10-N7-1): pominięci znikają ze wszystkich źródeł widoku, nie
    # tylko ze skrzynki — tylko pierwsza strona niesie listę (dalsze pytają
    # o kolejne osoby, a lista jest ta sama).
    dismissed_ids = (
        await proposals.dismissed_candidate_ids(db, job_id=job_id)
        if status == "proposed" and offset == 0
        else []
    )
    return {
        "job_id": job_id,
        "status": status,
        "items": items,
        "dismissed_candidate_ids": dismissed_ids,
        "total": total,
        "hidden_on_page": hidden,
        "limit": limit,
        "offset": offset,
        "next_offset": offset + limit if offset + limit < total else None,
    }


@router.post("/jobs/{job_id}/proposal-inbox/opened")
async def record_proposal_inbox_opened(
    job_id: int,
    user: CurrentUser,
    db: AsyncSession = Depends(get_db),
):
    """Telemetria: osoba otworzyła „Propozycje z bazy” tej rekrutacji (07.10.2026).

    Osobny POST, nie zapis w GET listy — GET zostaje odczytem. Wpis
    ``Activity proposal_inbox_opened`` (encja: rekrutacja) najwyżej raz na
    osobę, rekrutację i dzień w kalendarzu firmy; niezależnie od
    ``AI_MATCH_TELEMETRY_ENABLED``. Tryb „podgląd jako” jest tylko do odczytu
    (zależność odmawia POST-u wcześniej), więc nic się wtedy nie zapisuje.
    Odpowiedź mówi, czy wpis powstał.
    """
    from app.core.scheduling import business_today, local_day_start_utc  # noqa: PLC0415
    from app.models.activity import Activity  # noqa: PLC0415

    await _job(db, user, job_id)
    since = local_day_start_utc(business_today())
    already = await db.scalar(
        select(Activity.id)
        .where(
            Activity.entity_type == "job",
            Activity.entity_id == job_id,
            Activity.action == PROPOSAL_INBOX_OPENED,
            Activity.user_id == user.id,
            Activity.created_at >= since,
        )
        .limit(1)
    )
    if already is not None:
        return {"job_id": job_id, "recorded": False}
    db.add(
        Activity(
            entity_type="job",
            entity_id=job_id,
            action=PROPOSAL_INBOX_OPENED,
            user_id=user.id,
            details={},
        )
    )
    await db.commit()
    return {"job_id": job_id, "recorded": True}


@router.get("/jobs/{job_id}/proposal-counts")
async def job_proposal_counts(
    job_id: int,
    user: CurrentUser,
    days: int = Query(proposals.POSTING_RECENT_DAYS, ge=1, le=30),
    db: AsyncSession = Depends(get_db),
):
    """Liczby do nagłówka „Do przejrzenia” — ta sama bramka co skrzynka.

    ``postings_recent`` + ``base`` = ``total`` skrzynki (otwarte propozycje:
    świeże z ogłoszeń i reszta). ``screened_out`` = lista „Odrzuceni przez AI”
    (ta sama reguła i ta sama bramka co ``…/screened-out``). ``not_searchable_must``
    = pozycje must rekrutacji, których nie da się szukać w CV (zdanie, branża,
    język, rola) — ta sama reguła co ``non_technology_must`` w ``/scores``.
    """
    from app.api.search import _non_technology_must  # noqa: PLC0415
    from app.models.application_screening import (  # noqa: PLC0415
        ApplicationScreening,
    )
    from app.services import application_screening as screening  # noqa: PLC0415
    from app.services.scoring_service import job_skill_requirements  # noqa: PLC0415

    job = await _job(db, user, job_id)
    since = datetime.now(timezone.utc) - timedelta(days=days)
    split = await proposals.open_split_counts(db, job_id=job_id, since=since)
    screened_out = int(
        await db.scalar(
            select(func.count(ApplicationScreening.id)).where(
                ApplicationScreening.job_id == job_id, screening.listed_clause()
            )
        )
        or 0
    )
    # Te same etykiety must, które punktuje `/scores` (`matching_must` +
    # `gap_must` każdej osoby to razem wymagania must rekrutacji).
    must = job_skill_requirements(job).get("must") or []
    return {
        "job_id": job_id,
        "days": days,
        "postings_recent": split["postings_recent"],
        "base": split["base"],
        "screened_out": screened_out,
        "not_searchable_must": _non_technology_must({"job": {"matching_must": must}}),
    }


@router.get("/jobs/{job_id}/proposal-facts")
async def job_proposal_facts(
    job_id: int,
    user: CurrentUser,
    candidate_ids: list[int] = Query([]),
    db: AsyncSession = Depends(get_db),
):
    """Fakty o osobach z propozycji — hurtowo, bez kontaktu.

    Dwa zapytania niezależnie od liczby osób (kandydaci + historia etapów
    u klienta tej rekrutacji). Dostęp jak skrzynka propozycji
    (``_authorized_job``); stawka kandydata jawna jak w wierszu skrzynki.
    """
    from app.models.job import Job  # noqa: PLC0415
    from app.models.recruitment_pipeline import CandidateStage  # noqa: PLC0415
    from app.services import proposal_facts  # noqa: PLC0415

    ids = list(dict.fromkeys(candidate_ids))
    if len(ids) > proposal_facts.MAX_FACT_CANDIDATES:
        raise HTTPException(
            422,
            f"Najwyżej {proposal_facts.MAX_FACT_CANDIDATES} osób w jednym zapytaniu.",
        )
    job = await _job(db, user, job_id)
    if not ids:
        return {"job_id": job_id, "items": []}

    candidates = (
        (await db.execute(select(Candidate).where(Candidate.id.in_(ids))))
        .scalars()
        .all()
    )
    history: dict[int, dict] = {}
    if job.client_id is not None:
        rows = (
            await db.execute(
                select(
                    CandidateStage.candidate_id,
                    CandidateStage.job_id,
                    Job.title,
                    CandidateStage.stage,
                    CandidateStage.moved_at,
                )
                .join(Job, Job.id == CandidateStage.job_id)
                .where(
                    Job.client_id == job.client_id,
                    CandidateStage.job_id != job_id,
                    CandidateStage.candidate_id.in_(ids),
                )
            )
        ).all()
        history = proposal_facts.client_history(
            proposal_facts.StageRow(*row) for row in rows
        )
    by_id = {c.id: c for c in candidates}
    cv_dates = await proposal_facts.main_cv_uploaded_on(db, ids)
    from app.services.candidate_rate_from import this_job_rates  # noqa: PLC0415

    this_job = await this_job_rates(db, job_id, list(by_id))
    return {
        "job_id": job_id,
        "items": [
            {
                **proposal_facts.candidate_facts(by_id[cid], history=history.get(cid)),
                "cv_uploaded_on": cv_dates.get(cid),
                "rate_this_job_hourly": (
                    float(this_job[cid]["amount"]) if cid in this_job else None
                ),
            }
            for cid in ids
            if cid in by_id
        ],
    }


# Lustro `job_proposal_feedback_schema.DISMISS_REASONS` (CHECK z 0405) —
# `test_dismiss_reason_literal_mirrors_the_check` pilnuje zgodności.
DismissReason = Literal[
    "missing_critical",
    "too_expensive",
    "location_office",
    "too_junior",
    "outdated_cv",
    "other",
]

MSG_REASON_REQUIRED = "Wybierz powód pominięcia — bez niego nie wiemy, co poprawić."
MSG_NOTE_REQUIRED = "Przy powodzie „Inne” opisz w jednym zdaniu, dlaczego pomijasz."
MSG_NOTE_TOO_LONG = "Opis powodu może mieć najwyżej 500 znaków."


class DismissProposalBody(BaseModel):
    """„Pomiń": powód (wymagany od 30.09.2026) i źródło osoby spoza skrzynki.

    ``reason`` jest w modelu opcjonalny, żeby brak powodu dał 422 z polskim
    zdaniem (walidacja Pydantica mówi po angielsku) — sprawdza go
    :func:`validated_dismiss_feedback`.
    """

    source: ProposalSource = "full_base"
    reason: Optional[DismissReason] = None
    note: Optional[str] = None


def validated_dismiss_feedback(
    body: Optional[DismissProposalBody],
) -> tuple[str, Optional[str]]:
    """Powód i opis „Pomiń" albo 422 po polsku. Czysta — testowana bez bazy."""
    reason = body.reason if body is not None else None
    if reason is None:
        raise HTTPException(422, MSG_REASON_REQUIRED)
    note = (body.note or "").strip() or None
    if note is not None and len(note) > DISMISS_NOTE_MAX:
        raise HTTPException(422, MSG_NOTE_TOO_LONG)
    if reason == "other" and note is None:
        raise HTTPException(422, MSG_NOTE_REQUIRED)
    return reason, note


async def _emit_reject_outcome(
    db, *, job_id: int, candidate_id: int, reason: str
) -> None:
    """Telemetria `reject` z kodem powodu — nigdy nie wywraca „Pomiń"."""
    from app.services.match_telemetry_service import (  # noqa: PLC0415
        emit_match_outcome,
    )

    try:
        await emit_match_outcome(
            db,
            event_type="reject",
            candidate_id=candidate_id,
            job_id=job_id,
            reason_code=reason,
        )
    except Exception:  # noqa: BLE001 — telemetria nigdy nie psuje decyzji
        logger.warning(
            "[job_proposals] reject telemetry failed job=%s candidate=%s",
            job_id,
            candidate_id,
        )


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

    reason, note = validated_dismiss_feedback(body)
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
        reason=reason,
        note=note,
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
                source=body.source,
                cv_revision=revision,
                reason=reason,
                note=note,
            ) or await proposals.dismiss(
                db,
                job_id=job_id,
                candidate_id=candidate_id,
                user_id=user.id,
                cv_revision=revision,
                reason=reason,
                note=note,
            )
        # Inaczej idempotentne: druga próba albo wiersze `added` — nic do zrobienia.
    await db.commit()
    if changed:
        await _emit_reject_outcome(
            db, job_id=job_id, candidate_id=candidate_id, reason=reason
        )
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


# ── „Praca w tle" — co automaty zrobiły dla tej rekrutacji (21.09.2026) ──────

_BACKGROUND_ENTITY = "job_automation"
_BACKGROUND_KINDS = {
    "auto_full_review_finished": "auto_full_review",
    "auto_match_proposed": "new_cv_proposals",
    "cv_auto_generate_started": "cv_auto_generate",
    "cv_auto_generate_skipped": "cv_auto_generate_skipped",
    "cv_auto_generate_failed": "cv_auto_generate_failed",
    # Awarie: rekruter nie dostaje powiadomienia — wpis z polskim powodem.
    "auto_full_review_failed": "auto_full_review_failed",
    "auto_match_failed": "new_cv_proposals_failed",
}
_DETAIL_KEYS = (
    "run_id",
    "proposals",
    "eligible",
    "count",
    "trigger",
    "reason",
    "message",
)


@router.get("/jobs/{job_id}/background-events")
async def list_job_background_events(
    job_id: int,
    user: CurrentUser,
    limit: int = Query(30, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
):
    """Ostatnie zdarzenia automatów tej rekrutacji — ta sama bramka co skrzynka.

    Źródłem jest ``Activity(entity_type="job_automation", entity_id=job_id)``:
    zakończony automatyczny przegląd bazy (ile propozycji), propozycje z nowych
    CV, auto-CV po „Zweryfikowany" (zakolejkowane / pominięte z powodem).
    Wpisy niosą wyłącznie identyfikatory i kody; imię i nazwisko kandydata jest
    dołączane przy odczycie i tylko dla ról z odczytem kandydatów. Stan auto-CV
    czytamy na żywo z wiersza dokumentu, więc restart w trakcie generacji nie
    zostawia wpisu, który wiecznie mówi „w toku".
    """
    from app.api.candidate_access import CANDIDATE_READ_ROLES  # noqa: PLC0415
    from app.models.activity import Activity  # noqa: PLC0415
    from app.models.cv_generated_document import CvGeneratedDocument  # noqa: PLC0415

    await _job(db, user, job_id)
    rows = (
        (
            await db.scalars(
                select(Activity)
                .where(
                    Activity.entity_type == _BACKGROUND_ENTITY,
                    Activity.entity_id == job_id,
                    Activity.action.in_(list(_BACKGROUND_KINDS)),
                )
                .order_by(Activity.created_at.desc(), Activity.id.desc())
                .limit(limit)
            )
        )
        .unique()
        .all()
    )
    can_read_candidates = user.has_any_role(*CANDIDATE_READ_ROLES)
    candidate_ids = {
        int(cid)
        for row in rows
        if isinstance(cid := (row.details or {}).get("candidate_id"), int)
    }
    names: dict[int, str] = {}
    if candidate_ids and can_read_candidates:
        for cid, name, lastname in (
            await db.execute(
                select(Candidate.id, Candidate.name, Candidate.lastname).where(
                    Candidate.id.in_(candidate_ids)
                )
            )
        ).all():
            names[cid] = " ".join(x for x in (name, lastname) if x).strip()
    generated_ids = {
        int(gid)
        for row in rows
        if isinstance(gid := (row.details or {}).get("generated_id"), int)
    }
    doc_status: dict[int, str] = {}
    if generated_ids:
        doc_status = dict(
            (
                await db.execute(
                    select(CvGeneratedDocument.id, CvGeneratedDocument.status).where(
                        CvGeneratedDocument.id.in_(generated_ids)
                    )
                )
            ).all()
        )
    items = []
    for row in rows:
        details = row.details if isinstance(row.details, dict) else {}
        item = {
            "id": row.id,
            "kind": _BACKGROUND_KINDS[row.action],
            "created_at": row.created_at,
            **{k: details[k] for k in _DETAIL_KEYS if details.get(k) is not None},
        }
        candidate_id = details.get("candidate_id")
        if isinstance(candidate_id, int):
            item["candidate"] = {
                "id": candidate_id,
                "name": names.get(candidate_id) if can_read_candidates else None,
            }
        generated_id = details.get("generated_id")
        if isinstance(generated_id, int):
            item["generated_id"] = generated_id
            # Brak wiersza = rekruter usunął dokument.
            item["document_status"] = doc_status.get(generated_id, "deleted")
        if row.action == "cv_auto_generate_skipped" and details.get("detail"):
            item["detail"] = details["detail"]
        items.append(item)
    return {"job_id": job_id, "items": items, "limit": limit}
