"""„Pasuje też do” — inne rekrutacje, do których pasuje osoba dodana właśnie do A.

Decyzja Artura 14.10.2026 (D1): ta sama reguła co automaty i „Moi ludzie”.
Pula to rekrutacje opublikowane w pracy (``IN_WORK_STATES``), w których tej
osoby jeszcze nie ma — ani w toku, ani z zamkniętą kartą. Pulę zawęża Qdrant
(tekst kandydata względem wektorów rekrutacji, filtr po id). Ocena każdej
z najbliższych rekrutacji to :func:`my_people_matching.fits_for_job`, czyli
kanoniczny fit, kwalifikowalność (weto HM, czarna lista) i dealbreakery
z bramką „Wymagane (krytyczne)”. Zostaje najwyżej
:data:`ALSO_FITS_LIMIT` rekrutacji z wynikiem co najmniej
:data:`ALSO_FITS_MIN_SCORE` — ta sama liczba, którą rekrutacja B pokazuje
w „Szukaj w bazie”.

Awaria wyszukiwania wektorowego nie jest „nic nie pasuje”: wynik ma status
``unavailable`` i ekran mówi, że nie udało się sprawdzić.

Nasz konsultant wracający na rynek (makieta R2, 22.10.2026): osoba z decyzją
„przekaż do front office” (znacznik ``returns_to_market`` z
``employment_marker``) ma w bloku źródło „nasz konsultant” i „Wraca na rynek
DD.MM” (:func:`returning_consultant`). Bez kwot — znacznik ich nie niesie.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date
from types import SimpleNamespace
from typing import Iterable, Optional

from sqlalchemy import func, or_, select
from sqlalchemy.orm import aliased
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement

from app.models.candidate import Candidate
from app.models.client import Client
from app.models.job import Job, JobStatus
from app.models.recruitment_pipeline import CandidateStage, PipelineStage
from app.models.user import User
from app.services.client_identity import client_display_name_expression
from app.services.polish_ilike import polish_folded_ilike
from app.services.request_work_state import IN_WORK_STATES

logger = logging.getLogger(__name__)

ALSO_FITS_LIMIT = 3
ALSO_FITS_MIN_SCORE = 70
# Ile najbliższych wektorowo rekrutacji dostaje pełną ocenę. Każda to dowody
# z CV i notatek + kanoniczny fit (osobny wektor zapytania rekrutacji).
ALSO_FITS_PREFILTER = 8
MATCHING_CHIPS = 3
GAP_CHIPS = 2


@dataclass(frozen=True)
class AlsoFitsJob:
    job_id: int
    title: str
    client_name: Optional[str]
    score: int
    matching_must: tuple[str, ...] = ()
    gap_must: tuple[str, ...] = ()
    # Numer u klienta przed nazwą, jak w nagłówku rekrutacji (16.10.2026).
    client_reference: Optional[str] = None


@dataclass(frozen=True)
class AlsoFitsResult:
    status: str  # "ok" | "unavailable"
    jobs: tuple[AlsoFitsJob, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class Scored:
    """Wynik oceny jednej rekrutacji — wejście czystej selekcji."""

    job_id: int
    score: Optional[int]
    measurement: str
    hidden: bool
    assignment_allowed: bool


def select_also_fits(
    scored: Iterable[Scored],
    *,
    limit: int = ALSO_FITS_LIMIT,
    min_score: int = ALSO_FITS_MIN_SCORE,
) -> list[Scored]:
    """Które rekrutacje pokazać: zmierzone, niewidoczne-nie, dozwolone, ≥ progu.

    Niezmierzony wynik (brak wektora, nieświeży indeks) to „nie wiemy”, nie
    „nie pasuje” — nie trafia na listę. Remis rozstrzyga niższe id (stabilnie).
    """
    kept = [
        s
        for s in scored
        if s.measurement == "measured"
        and s.score is not None
        and s.score >= min_score
        and not s.hidden
        and s.assignment_allowed
    ]
    kept.sort(key=lambda s: (-int(s.score or 0), s.job_id))
    return kept[: max(0, limit)]


async def open_pool_job_ids(
    db: AsyncSession,
    *,
    candidate_id: int,
    from_job_id: int,
    scope_clause: Optional[ColumnElement] = None,
) -> list[int]:
    """Rekrutacje w pracy, w których tej osoby nie ma (żadnego wiersza etapu)."""
    in_job = (
        select(CandidateStage.id)
        .where(
            CandidateStage.job_id == Job.id,
            CandidateStage.candidate_id == candidate_id,
        )
        .exists()
    )
    stmt = select(Job.id).where(
        Job.status == JobStatus.published,
        Job.work_state.in_(IN_WORK_STATES),
        Job.id != from_job_id,
        ~in_job,
    )
    if scope_clause is not None:
        stmt = stmt.where(scope_clause)
    return [int(j) for j in (await db.scalars(stmt)).all()]


async def also_fits_for_candidate(
    db: AsyncSession,
    *,
    candidate: Candidate,
    from_job_id: int,
    profile_user_id: Optional[int],
    scope_clause: Optional[ColumnElement] = None,
    limit: int = ALSO_FITS_LIMIT,
) -> AlsoFitsResult:
    from app.services.auto_match_service import AutoMatchUnavailable, scoped_similarity
    from app.services.embedding_service import _build_candidate_text
    from app.services.job_working_title import display_title
    from app.services.my_people_matching import fits_for_job, warm_job_queries

    pool = await open_pool_job_ids(
        db,
        candidate_id=candidate.id,
        from_job_id=from_job_id,
        scope_clause=scope_clause,
    )
    if not pool:
        return AlsoFitsResult(status="ok")
    try:
        similarity = await scoped_similarity(
            _build_candidate_text(candidate), jobs_collection=True, ids=pool
        )
    except AutoMatchUnavailable as exc:
        logger.warning(
            "[also_fits] wyszukiwanie wektorowe niedostępne (kandydat %s): %s",
            candidate.id,
            exc,
        )
        return AlsoFitsResult(status="unavailable")
    nearest = sorted(similarity, key=lambda jid: (-similarity[jid], jid))[
        : max(ALSO_FITS_PREFILTER, limit)
    ]
    if not nearest:
        return AlsoFitsResult(status="ok")

    rows = (
        await db.execute(
            select(Job, client_display_name_expression())
            .outerjoin(Client, Client.id == Job.client_id)
            .where(Job.id.in_(nearest))
        )
    ).all()
    jobs = {job.id: (job, client_name) for job, client_name in rows}
    # Każda rekrutacja ma własny wektor zapytania: jedno wywołanie Voyage na
    # wszystkie zamiast ośmiu po kolei (85–95% czasu trasy, pomiar 27.10.2026).
    await warm_job_queries(
        db,
        jobs=[jobs[job_id][0] for job_id in nearest if job_id in jobs],
        profile_user_id=profile_user_id,
    )

    scored: list[Scored] = []
    details: dict[int, object] = {}
    for job_id in nearest:
        if job_id not in jobs:
            continue
        job, _ = jobs[job_id]
        fits = await fits_for_job(
            db, job=job, candidates=[candidate], profile_user_id=profile_user_id
        )
        if not fits:
            continue
        fit = fits[0]
        decision = fit.decision
        scored.append(
            Scored(
                job_id=job_id,
                score=fit.score,
                measurement=fit.measurement,
                hidden=fit.hidden,
                assignment_allowed=bool(
                    decision is None or getattr(decision, "assignment_allowed", True)
                ),
            )
        )
        details[job_id] = fit.breakdown

    out: list[AlsoFitsJob] = []
    for s in select_also_fits(scored, limit=limit):
        job, client_name = jobs[s.job_id]
        breakdown = details.get(s.job_id)
        out.append(
            AlsoFitsJob(
                job_id=s.job_id,
                title=display_title(job),
                client_name=client_name,
                score=int(s.score or 0),
                matching_must=tuple(
                    (getattr(breakdown, "matching_must", None) or [])[:MATCHING_CHIPS]
                ),
                gap_must=tuple(
                    (getattr(breakdown, "gap_must", None) or [])[:GAP_CHIPS]
                ),
                client_reference=job.client_reference,
            )
        )
    return AlsoFitsResult(status="ok", jobs=tuple(out))


#: Źródło osoby w bloku: nasz konsultant wracający na rynek.
SOURCE_OUR_CONSULTANT = "our_consultant"


@dataclass(frozen=True)
class ReturningConsultant:
    """Nasz konsultant przekazany do front office — „Wraca na rynek DD.MM”."""

    returns_on: Optional[date]


async def returning_consultant(
    db: AsyncSession, candidate_id: int, *, today: date
) -> Optional[ReturningConsultant]:
    """Znacznik „Wraca na rynek” osoby albo ``None``.

    Ta sama reguła co znacznik „Pracuje u nas” na Tablicy, w panelu i na
    profilu (``employment_marker.mark_returning``). Awaria = ``None``: blok
    „Pasuje też do” działa bez tej informacji.
    """

    from app.services.employment_marker import load_employment_markers

    try:
        async with db.begin_nested():
            markers = await load_employment_markers(db, [candidate_id], today=today)
    except Exception:  # noqa: BLE001 — dodatek do bloku, nie jego warunek
        logger.exception("[also_fits] znacznik „Wraca na rynek” nie policzony")
        return None
    marker = markers.get(candidate_id)
    if marker is None or not getattr(marker, "returns_to_market", False):
        return None
    return ReturningConsultant(returns_on=marker.returns_to_market_on)


OTHER_OPEN_JOBS_LIMIT = 5
# Etapy (legacy enum), które Tablica kładzie w „Nowych”/„Screeningu”
# (`board_stage_badges._COLUMN_BY_ENUM`; odznaki z nazwy nigdy tam nie trafiają).
# Zawężenie w SQL — dokładną kolumnę liczy potem `board_column_for`.
SCREENING_ENTRY_STAGES = ("posting", "new", "prep_call", "screening")


async def other_open_jobs_for_candidates(
    db: AsyncSession,
    *,
    candidate_ids: Iterable[int],
    exclude_job_id: int,
    scope_clause: Optional[ColumnElement] = None,
) -> dict[int, list[dict]]:
    """Gdzie jeszcze osoby z Tablicy czekają w „Nowych”/„Screeningu” (karta A2).

    Najnowszy wiersz etapu per (osoba, rekrutacja), rekrutacja niezamknięta,
    kolumna liczona tą samą regułą co Tablica (``board_column_for``). Jedno
    zapytanie na całą Tablicę; najwyżej :data:`OTHER_OPEN_JOBS_LIMIT` na osobę,
    od najświeższego ruchu.
    """
    from app.models.pipeline_template import PipelineStageDef
    from app.services.board_stage_badges import CLAIM_COLUMNS, board_column_for
    from app.services.job_working_title import display_title

    ids = sorted({int(c) for c in candidate_ids})
    if not ids:
        return {}
    latest = (
        select(
            CandidateStage.candidate_id,
            CandidateStage.job_id,
            CandidateStage.stage,
            CandidateStage.stage_def_id,
            CandidateStage.moved_at,
        )
        .where(
            CandidateStage.candidate_id.in_(ids),
            CandidateStage.job_id != exclude_job_id,
        )
        .distinct(CandidateStage.candidate_id, CandidateStage.job_id)
        .order_by(
            CandidateStage.candidate_id,
            CandidateStage.job_id,
            CandidateStage.moved_at.desc(),
            CandidateStage.id.desc(),
        )
        .subquery()
    )
    stmt = (
        select(
            latest.c.candidate_id,
            latest.c.job_id,
            latest.c.stage,
            latest.c.moved_at,
            Job.title,
            Job.working_title,
            client_display_name_expression().label("client_name"),
            PipelineStageDef.name,
            PipelineStageDef.category,
            PipelineStageDef.terminal_type,
        )
        .select_from(latest)
        .join(Job, Job.id == latest.c.job_id)
        .outerjoin(Client, Client.id == Job.client_id)
        .outerjoin(PipelineStageDef, PipelineStageDef.id == latest.c.stage_def_id)
        .where(
            Job.status != JobStatus.closed,
            latest.c.stage.in_([PipelineStage(v) for v in SCREENING_ENTRY_STAGES]),
        )
    )
    if scope_clause is not None:
        stmt = stmt.where(scope_clause)
    rows = (await db.execute(stmt)).all()

    out: dict[int, list[tuple]] = {}
    for (
        cid,
        job_id,
        stage,
        moved_at,
        title,
        working_title,
        client_name,
        name,
        category,
        terminal,
    ) in rows:
        column = board_column_for(
            name,
            getattr(stage, "value", stage),
            category=getattr(category, "value", category),
            terminal_type=getattr(terminal, "value", terminal),
        )
        if column not in CLAIM_COLUMNS:
            continue
        out.setdefault(int(cid), []).append(
            (
                moved_at,
                {
                    "job_id": int(job_id),
                    "title": display_title(
                        SimpleNamespace(title=title, working_title=working_title)
                    ),
                    "client_name": client_name,
                    "column": column,
                },
            )
        )
    return {
        cid: [
            item
            for _, item in sorted(
                entries,
                key=lambda e: (e[0] is not None, e[0]),
                reverse=True,
            )[:OTHER_OPEN_JOBS_LIMIT]
        ]
        for cid, entries in out.items()
    }


#: „+ Dodaj inną rekrutację” w „Screening dla” (29.10.2026): ile znaków
#: frazy zanim szukamy i ile rekrutacji pokazujemy (lustro DL-a, ``dl_match``).
SEARCH_MIN_CHARS = 2
SEARCH_LIMIT = 8
# Z bazy bierzemy więcej, bo zespół rekrutera idzie na górę dopiero po
# sprawdzeniu członkostwa (reguła trasy, nie SQL).
SEARCH_FETCH = 20


@dataclass(frozen=True)
class ManualJobHit:
    job_id: int
    title: str
    client_name: Optional[str]
    client_reference: Optional[str]
    delivery_lead_name: Optional[str]


async def search_open_jobs(
    db: AsyncSession,
    *,
    candidate_id: int,
    from_job_id: int,
    phrase: str,
    scope_clause: Optional[ColumnElement] = None,
) -> tuple[ManualJobHit, ...]:
    """„+ Dodaj inną rekrutację” rekrutera (zgłoszenie Michała 29.10.2026).

    „Pasuje też do” pokazuje najwyżej 3 rekrutacje ≥ 70 z 8 najbliższych
    wektorowo, więc rekrutacja, o której rekruter chce porozmawiać z osobą
    („Fullstack też na backend”), potrafi z niej wypaść. Ta sama pula co
    podpowiedź (:func:`open_pool_job_ids`: w pracy, bez żadnego wiersza tej
    osoby), szukana po nazwie, numerze u klienta, kliencie i id — jak
    ``dl_match.search_targets`` DL-a. Bez oceny dopasowania: rekruter wie,
    czemu dodaje.
    """
    from app.services.job_working_title import display_title

    phrase = phrase.strip()
    if len(phrase) < SEARCH_MIN_CHARS:
        return ()
    in_job = (
        select(CandidateStage.id)
        .where(
            CandidateStage.job_id == Job.id,
            CandidateStage.candidate_id == candidate_id,
        )
        .exists()
    )
    text = or_(
        polish_folded_ilike(Job.title, phrase),
        polish_folded_ilike(func.coalesce(Job.working_title, ""), phrase),
        polish_folded_ilike(func.coalesce(Job.client_reference, ""), phrase),
        polish_folded_ilike(client_display_name_expression(), phrase),
    )
    if phrase.isdigit():
        text = or_(text, Job.id == int(phrase))
    lead = aliased(User)
    stmt = (
        select(Job, client_display_name_expression(), lead.name)
        .outerjoin(Client, Client.id == Job.client_id)
        .outerjoin(lead, lead.id == Job.delivery_lead_id)
        .where(
            Job.id != from_job_id,
            Job.status == JobStatus.published,
            Job.work_state.in_(IN_WORK_STATES),
            ~in_job,
            text,
        )
        .order_by(Job.id.desc())
        .limit(SEARCH_FETCH)
    )
    if scope_clause is not None:
        stmt = stmt.where(scope_clause)
    return tuple(
        ManualJobHit(
            job_id=int(job.id),
            title=display_title(job),
            client_name=client_name,
            client_reference=job.client_reference,
            delivery_lead_name=lead_name,
        )
        for job, client_name, lead_name in (await db.execute(stmt)).all()
    )


def bell_message(
    *,
    actor_name: str,
    candidate_name: str,
    job_title: str,
    origin_title: Optional[str],
    manual: bool = False,
) -> str:
    where = f" Znaleziony przy rekrutacji „{origin_title}”." if origin_title else ""
    how = "dodane ręcznie przy rozmowie" if manual else "podpowiedź „Pasuje też do”"
    return (
        f"{actor_name} dodał(a) {candidate_name} do Twojej rekrutacji „{job_title}”"
        f" — {how}.{where} Rezerwacja 12 h u osoby, która dodała."
    )


async def record_also_fits_added(
    db: AsyncSession,
    *,
    job: Job,
    candidate_ids: list[int],
    actor_id: int,
    origin_job_id: Optional[int],
    manual: bool = False,
) -> int:
    """Po „+ Dodaj” z „Pasuje też do”: wpis w historii i dzwonek do rekruterów B.

    ``manual`` — rekrutacja wskazana ręcznie („+ Dodaj inną rekrutację”,
    29.10.2026): ten sam wpis i dzwonek, inne słowa i ``via`` w historii.

    Decyzja Artura 14.10.2026 (D2): rekruter rekrutacji B wie, że ktoś dodał mu
    osobę — kto i skąd. Bez osoby, która dodała. Wołane PO zapisie dodania;
    nigdy nie rzuca (dzwonek nie może cofnąć dodania). Zwraca liczbę dzwonków.
    """
    from app.models.activity import Activity
    from app.models.notification import NotificationType
    from app.models.user import User
    from app.services.job_team import recruiters_for_jobs, working
    from app.services.job_working_title import display_title
    from app.services.notification_triggers import emit

    if not candidate_ids:
        return 0
    job_id = int(job.id)
    sent = 0
    try:
        job_title = display_title(job)
        origin_title: Optional[str] = None
        if origin_job_id and origin_job_id != job_id:
            origin = await db.get(Job, origin_job_id)
            origin_title = display_title(origin) if origin is not None else None
        actor = await db.get(User, actor_id)
        actor_name = (actor.name if actor is not None else None) or "Ktoś z zespołu"
        names = {
            int(cid): " ".join(p for p in (name, lastname) if p) or f"#{cid}"
            for cid, name, lastname in (
                await db.execute(
                    select(Candidate.id, Candidate.name, Candidate.lastname).where(
                        Candidate.id.in_(sorted({int(c) for c in candidate_ids}))
                    )
                )
            ).all()
        }
        # Klucz dzwonka = nowy wiersz etapu pary w B: indeks `ix_notif_dedup_daily`
        # (user, typ, encja, dzień) zjadałby drugi dzwonek, gdyby kluczem była
        # osoba dodana tego samego dnia do dwóch rekrutacji jednego rekrutera.
        stage_ids = {
            int(cid): int(stage_id)
            for cid, stage_id in (
                await db.execute(
                    select(CandidateStage.candidate_id, func.max(CandidateStage.id))
                    .where(
                        CandidateStage.job_id == job_id,
                        CandidateStage.candidate_id.in_(sorted(names)),
                    )
                    .group_by(CandidateStage.candidate_id)
                )
            ).all()
        }
        recipients = sorted(
            {
                p.user_id
                for p in working(
                    (await recruiters_for_jobs(db, [job_id])).get(job_id, [])
                )
                if p.user_id != actor_id
            }
        )
        for cid in sorted(names):
            db.add(
                Activity(
                    entity_type="candidate",
                    entity_id=cid,
                    action="also_fits_added",
                    user_id=actor_id,
                    details={
                        "job_id": job_id,
                        "from_job_id": origin_job_id,
                        **({"via": "manual"} if manual else {}),
                    },
                )
            )
            for user_id in recipients:
                try:
                    async with db.begin_nested():
                        created = await emit(
                            db,
                            user_id=user_id,
                            title="Nowa osoba w Twojej rekrutacji",
                            message=bell_message(
                                actor_name=actor_name,
                                candidate_name=names[cid],
                                job_title=job_title,
                                origin_title=origin_title,
                                manual=manual,
                            ),
                            ntype=NotificationType.also_fits_added,
                            related_entity_type=(
                                "candidate_stage" if cid in stage_ids else "candidate"
                            ),
                            related_entity_id=stage_ids.get(cid, cid),
                            link=f"/jobs/{job_id}?candidate={cid}",
                        )
                    sent += int(created is not None)
                except Exception:  # noqa: BLE001 — jeden odbiorca nie blokuje reszty
                    logger.exception(
                        "[also_fits] dzwonek nie wyszedł job=%s user=%s",
                        job_id,
                        user_id,
                    )
        await db.commit()
    except Exception:  # noqa: BLE001 — dodanie już zapisane
        logger.exception("[also_fits] wpis po dodaniu nie wyszedł job=%s", job_id)
        await db.rollback()
    return sent


__all__ = [
    "ALSO_FITS_LIMIT",
    "ALSO_FITS_MIN_SCORE",
    "ALSO_FITS_PREFILTER",
    "AlsoFitsJob",
    "AlsoFitsResult",
    "ManualJobHit",
    "Scored",
    "also_fits_for_candidate",
    "bell_message",
    "open_pool_job_ids",
    "other_open_jobs_for_candidates",
    "record_also_fits_added",
    "search_open_jobs",
    "select_also_fits",
]
