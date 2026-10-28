"""Bliźniacze rekrutacje (0615, decyzje Artura z 28.10.2026).

Makiety: https://claude.ai/artifact/83ybsjjmstNhKAzHYNraFw. Bliźniak to
podobna rekrutacja o tym samym profilu kandydata: osobę weryfikuje się raz,
w jednej rozmowie, pod wszystkie bliźniaki naraz („Screening dla” z kłódką),
a potem każda rekrutacja idzie osobno.

* **Kto łączy:** Delivery Lead — swoje otwarte rekrutacje, także u różnych
  klientów; Head of Recruitment i admin — dowolne otwarte (:func:`can_link`).
* **Zapis:** ``job_similar_links.kind = 'twin'`` w obu kierunkach, z parami
  pytań (``question_pairs``) potwierdzonymi w oknie łączenia. Rozłączenie
  wraca do ``similar`` — nikogo nie zdejmuje.
* **Bez kopiowania:** osoby zweryfikowane przed połączeniem zostają tam, gdzie
  są; połączenie działa od teraz.
* **Weryfikacja liczy się osobno w każdej rekrutacji** (KPI bez zmian).
* **Bramka ruchu** (:func:`assert_twin_screening`): wejście na „Zweryfikowany”
  wymaga screeningu pary także w każdym bliźniaku albo jawnego pominięcia
  z powodem.
* **Stawka** (:func:`assert_rate_within_budget`): w rekrutacji z bliźniakiem
  stawka kandydata ponad budżet się nie zapisze.

Żadna funkcja tutaj nie commituje — transakcja należy do wołającego.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Iterable, Mapping, Optional, Sequence

from fastapi import HTTPException
from sqlalchemy import and_, or_, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.job import Job, JobPriority, JobStatus
from app.models.job_similar_link import JobSimilarLink, JobTwinDismissal
from app.models.user import User

logger = logging.getLogger(__name__)

KIND_SIMILAR = "similar"
KIND_TWIN = "twin"
# Kotwica + 3 bliźniaki = najwięcej, ile mieści jedna rozmowa w „Screening dla”
# (`JOINT_MAX_OTHERS`, trasa grup pytań przyjmuje 2–4 rekrutacje).
MAX_TWINS = 3
LINK_ALL_ROLES = ("admin", "head_of_recruitment")
# Propozycje dla HoR: kosinus wektorów rekrutacji. Na stagingu 28.10.2026
# przy 0,80 było 46 par u tego samego klienta i 7 między klientami.
SUGGESTION_MIN_COSINE = 0.80
SUGGESTION_LIMIT = 40
_SUGGESTION_TTL_SECONDS = 300
OPEN_SIMILAR_LIMIT = 8
# Pary pytań: wspólne słowa treści (``prior_screening.content_words``).
# Na parze ZOB-2947 ↔ ZOB-2964 próg 0,2 daje dokładnie trzy pary, które
# zespół uznał za „to samo pytanie” (DDD, stack, OpenShift); najbliższa
# nietrafiona para miała 0,095.
QUESTION_PAIR_MIN_SCORE = 0.2
P1_PRIORITIES = (JobPriority.urgent, JobPriority.high)
SKIP_REASON_MAX = 300

SKIP_REASONS = {
    "client_rejected": "Odrzucona przez klienta bliźniaka",
    "client_conflict": "Konflikt u klienta bliźniaka",
    "candidate_declined": "Kandydat nie chce tej rekrutacji",
    "other": "Inny powód",
}


def _work_states() -> tuple[str, ...]:
    from app.services.request_work_state import IN_WORK_STATES  # noqa: PLC0415

    return tuple(IN_WORK_STATES)


def is_open(job: Job) -> bool:
    return job.status != JobStatus.closed


# ── Uprawnienia ────────────────────────────────────────────────────────────


async def leads_job(db: AsyncSession, user: User, job: Job) -> bool:
    """Delivery Lead tej rekrutacji (ta sama reguła co decyzja o stawce)."""
    from app.services.candidate_rate_change import job_delivery_leads  # noqa: PLC0415

    if not user.has_any_role("delivery_lead"):
        return False
    return user.id in await job_delivery_leads(db, job)


async def can_link(db: AsyncSession, user: User, job: Job, other: Job) -> bool:
    if user.has_any_role(*LINK_ALL_ROLES):
        return True
    return await leads_job(db, user, job) and await leads_job(db, user, other)


async def can_manage(db: AsyncSession, user: User, job: Job) -> bool:
    """Łączenie z tej rekrutacji w ogóle (przycisk „⇄ Połącz bliźniaka”)."""
    if user.has_any_role(*LINK_ALL_ROLES):
        return True
    return await leads_job(db, user, job)


async def can_unlink(db: AsyncSession, user: User, job: Job, other: Job) -> bool:
    """Rozłączyć może DL którejkolwiek strony, HoR i admin."""
    if user.has_any_role(*LINK_ALL_ROLES):
        return True
    return await leads_job(db, user, job) or await leads_job(db, user, other)


# ── Odczyt ─────────────────────────────────────────────────────────────────


async def twin_links(
    db: AsyncSession, job_ids: Sequence[int]
) -> dict[int, list[JobSimilarLink]]:
    """Wiersze bliźniaków z perspektywy każdej rekrutacji (``job_id`` = ona)."""
    if not job_ids:
        return {}
    rows = (
        await db.execute(
            select(JobSimilarLink)
            .where(
                JobSimilarLink.job_id.in_(list(job_ids)),
                JobSimilarLink.kind == KIND_TWIN,
            )
            .order_by(JobSimilarLink.created_at, JobSimilarLink.id)
        )
    ).scalars()
    out: dict[int, list[JobSimilarLink]] = {}
    for row in rows:
        out.setdefault(row.job_id, []).append(row)
    return out


async def twin_ids(db: AsyncSession, job_id: int) -> list[int]:
    return [
        row.similar_job_id for row in (await twin_links(db, [job_id])).get(job_id, [])
    ]


def question_texts(job: Job) -> dict[str, str]:
    from app.services import screening_sheets  # noqa: PLC0415

    return screening_sheets.question_texts(job.champion_profile)


def suggest_question_pairs(
    own: Mapping[str, str], other: Mapping[str, str]
) -> list[dict[str, Any]]:
    """Podpowiedź par „to samo pytanie” — DL ją potwierdza albo poprawia.

    Ten sam tekst (po złożeniu) zawsze; inaczej wspólne słowa treści
    ≥ :data:`QUESTION_PAIR_MIN_SCORE`, jeden do jednego, od najlepszej pary.
    Pytania o stawkę, dostępność i tryb pracy łączymy tylko po tym samym
    tekście (jak ``screening_question_groups``)."""
    from app.services.prior_screening import (  # noqa: PLC0415
        content_words,
        has_own_layer,
        jaccard,
    )
    from app.services.screening_question_groups import _normalized  # noqa: PLC0415

    scored: list[tuple[float, str, str]] = []
    for own_id, own_text in own.items():
        for other_id, other_text in other.items():
            if _normalized(own_text) and _normalized(own_text) == _normalized(
                other_text
            ):
                scored.append((2.0, own_id, other_id))
                continue
            if has_own_layer(own_text) or has_own_layer(other_text):
                continue
            score = jaccard(content_words(own_text), content_words(other_text))
            if score >= QUESTION_PAIR_MIN_SCORE:
                scored.append((score, own_id, other_id))
    scored.sort(key=lambda item: (-item[0], item[1], item[2]))
    used_own: set[str] = set()
    used_other: set[str] = set()
    out: list[dict[str, Any]] = []
    for score, own_id, other_id in scored:
        if own_id in used_own or other_id in used_other:
            continue
        used_own.add(own_id)
        used_other.add(other_id)
        out.append(
            {"own": own_id, "other": other_id, "score": round(min(score, 1.0), 2)}
        )
    return out


def validate_question_pairs(
    pairs: Iterable[Mapping[str, Any]],
    own: Mapping[str, str],
    other: Mapping[str, str],
) -> list[dict[str, str]]:
    """Pary z okna łączenia: istniejące pytania, każde najwyżej raz (422)."""
    out: list[dict[str, str]] = []
    used_own: set[str] = set()
    used_other: set[str] = set()
    for pair in pairs:
        own_id = str(pair.get("own") or "").strip()
        other_id = str(pair.get("other") or "").strip()
        if own_id not in own or other_id not in other:
            raise HTTPException(
                status_code=422,
                detail={
                    "code": "twin_question_unknown",
                    "message": "Para wskazuje pytanie, którego nie ma w Profilu Championa.",
                },
            )
        if own_id in used_own or other_id in used_other:
            raise HTTPException(
                status_code=422,
                detail={
                    "code": "twin_question_repeated",
                    "message": "Każde pytanie może być w jednej parze.",
                },
            )
        used_own.add(own_id)
        used_other.add(other_id)
        out.append({"own": own_id, "other": other_id})
    return out


def mirrored(pairs: Optional[Sequence[Mapping[str, str]]]) -> list[dict[str, str]]:
    return [{"own": p["other"], "other": p["own"]} for p in pairs or []]


def explicit_question_groups(
    links: Mapping[int, Sequence[JobSimilarLink]], job_ids: Sequence[int]
) -> list[tuple[tuple[int, str], tuple[int, str]]]:
    """Pary pytań bliźniaków wśród wybranych rekrutacji — dla grup pytań
    wspólnego screeningu (``screening_question_groups.group_questions``)."""
    chosen = set(job_ids)
    out: list[tuple[tuple[int, str], tuple[int, str]]] = []
    for job_id in job_ids:
        for link in links.get(job_id, []):
            other = link.similar_job_id
            if other not in chosen or other < job_id:
                continue
            for pair in link.question_pairs or []:
                out.append(((job_id, pair["own"]), (other, pair["other"])))
    return out


# ── Zapis ──────────────────────────────────────────────────────────────────


async def _lock_jobs(db: AsyncSession, job_ids: Sequence[int]) -> dict[int, Job]:
    """Blokada obu wierszy w stałej kolejności — dwa równoległe połączenia
    nie przekroczą limitu bliźniaków."""
    jobs = {
        job.id: job
        for job in (
            await db.execute(
                select(Job)
                .where(Job.id.in_(sorted(set(job_ids))))
                .order_by(Job.id)
                .with_for_update()
            )
        ).scalars()
    }
    return jobs


def _refuse(status: int, code: str, message: str) -> HTTPException:
    return HTTPException(status_code=status, detail={"code": code, "message": message})


async def link(
    db: AsyncSession,
    *,
    user: User,
    job_id: int,
    other_id: int,
    question_pairs: Sequence[Mapping[str, Any]],
) -> bool:
    """Połącz bliźniaki (oba kierunki). Zwraca ``True``, gdy połączenie jest nowe.

    Istniejące połączenie „podobne” staje się bliźniakiem; istniejący bliźniak
    dostaje nowe pary pytań. Nikogo nie dodaje i nie przepina."""
    if job_id == other_id:
        raise _refuse(422, "twin_self", "Rekrutacji nie da się połączyć z nią samą.")
    jobs = await _lock_jobs(db, [job_id, other_id])
    job, other = jobs.get(job_id), jobs.get(other_id)
    if job is None or other is None:
        raise _refuse(404, "twin_job_missing", "Nie ma takiej rekrutacji.")
    if not await can_link(db, user, job, other):
        raise _refuse(
            403,
            "twin_forbidden",
            "Delivery Lead łączy tylko swoje rekrutacje. "
            "Rekrutacje innych DL-i łączy Head of Recruitment albo admin.",
        )
    if not is_open(job) or not is_open(other):
        raise _refuse(
            422, "twin_closed", "Bliźniakiem może być tylko otwarta rekrutacja."
        )
    links = await twin_links(db, [job_id, other_id])
    already = any(row.similar_job_id == other_id for row in links.get(job_id, []))
    if not already:
        for side, jid in ((job, job_id), (other, other_id)):
            if len(links.get(jid, [])) >= MAX_TWINS:
                raise _refuse(
                    422,
                    "twin_limit",
                    f"Rekrutacja {side.reference_number or side.id} ma już "
                    f"{MAX_TWINS} bliźniaki — tyle mieści jedna rozmowa.",
                )
    pairs = validate_question_pairs(
        question_pairs, question_texts(job), question_texts(other)
    )
    for own, sim_id, own_pairs in (
        (job_id, other_id, pairs),
        (other_id, job_id, mirrored(pairs)),
    ):
        await db.execute(
            pg_insert(JobSimilarLink)
            .values(
                job_id=own,
                similar_job_id=sim_id,
                created_by=user.id,
                kind=KIND_TWIN,
                question_pairs=own_pairs,
            )
            .on_conflict_do_update(
                constraint="uq_job_similar_links_pair",
                set_={"kind": KIND_TWIN, "question_pairs": own_pairs},
            )
        )
    from app.models.activity import Activity  # noqa: PLC0415

    for own, sim_id in ((job_id, other_id), (other_id, job_id)):
        db.add(
            Activity(
                entity_type="job",
                entity_id=own,
                action="job_twin_linked" if not already else "job_twin_pairs_changed",
                user_id=user.id,
                details={"twin_job_id": sim_id, "question_pairs": len(pairs)},
            )
        )
    await db.flush()
    return not already


async def unlink(db: AsyncSession, *, user: User, job_id: int, other_id: int) -> bool:
    """Rozłącz bliźniaki: połączenie wraca do „podobnych”, nikt nie znika."""
    jobs = await _lock_jobs(db, [job_id, other_id])
    job, other = jobs.get(job_id), jobs.get(other_id)
    if job is None or other is None:
        raise _refuse(404, "twin_job_missing", "Nie ma takiej rekrutacji.")
    if not await can_unlink(db, user, job, other):
        raise _refuse(
            403,
            "twin_forbidden",
            "Rozłączyć może Delivery Lead jednej z rekrutacji, Head of Recruitment albo admin.",
        )
    result = await db.execute(
        update(JobSimilarLink)
        .where(
            JobSimilarLink.kind == KIND_TWIN,
            or_(
                and_(
                    JobSimilarLink.job_id == job_id,
                    JobSimilarLink.similar_job_id == other_id,
                ),
                and_(
                    JobSimilarLink.job_id == other_id,
                    JobSimilarLink.similar_job_id == job_id,
                ),
            ),
        )
        .values(kind=KIND_SIMILAR, question_pairs=None)
    )
    if not result.rowcount:
        return False
    from app.models.activity import Activity  # noqa: PLC0415

    for own, sim_id in ((job_id, other_id), (other_id, job_id)):
        db.add(
            Activity(
                entity_type="job",
                entity_id=own,
                action="job_twin_unlinked",
                user_id=user.id,
                details={"twin_job_id": sim_id},
            )
        )
    await db.flush()
    return True


async def dismiss(db: AsyncSession, *, user: User, job_id: int, other_id: int) -> None:
    """„To nie bliźniak” z listy HoR — para nie wraca na listę."""
    if not user.has_any_role(*LINK_ALL_ROLES):
        raise _refuse(
            403, "twin_forbidden", "Propozycje bliźniaków odrzuca HoR albo admin."
        )
    low, high = sorted((job_id, other_id))
    if low == high:
        raise _refuse(422, "twin_self", "Wskaż dwie różne rekrutacje.")
    await db.execute(
        pg_insert(JobTwinDismissal)
        .values(job_low_id=low, job_high_id=high, dismissed_by=user.id)
        .on_conflict_do_nothing(constraint="uq_job_twin_dismissals_pair")
    )
    reset_suggestion_cache()


async def notify_linked(
    db: AsyncSession, *, job: Job, other: Job, actor_id: int
) -> None:
    """Dzwonek do rekruterów i DL-i obu rekrutacji. Nieudany nie cofa zapisu."""
    from app.models.notification import NotificationType  # noqa: PLC0415
    from app.services.job_champions import recipients  # noqa: PLC0415
    from app.services.job_working_title import display_title  # noqa: PLC0415
    from app.services.notification_triggers import emit  # noqa: PLC0415

    sent: set[int] = set()
    for own, twin in ((job, other), (other, job)):
        message = (
            f"{display_title(own)} ma bliźniaka: {display_title(twin)}"
            f"{' (' + twin.reference_number + ')' if twin.reference_number else ''}. "
            "Screening robisz od teraz pod obie rekrutacje naraz."
        )
        for user_id in await recipients(db, own, actor_id=actor_id):
            if user_id in sent:
                continue
            sent.add(user_id)
            try:
                async with db.begin_nested():
                    await emit(
                        db,
                        user_id=user_id,
                        title="Bliźniacza rekrutacja",
                        message=message,
                        ntype=NotificationType.job_twin_linked,
                        related_entity_type="job",
                        related_entity_id=None,
                        link=f"/jobs/{own.id}",
                    )
            except Exception:  # noqa: BLE001 — dzwonek nie może cofnąć połączenia
                logger.exception(
                    "[job_twins] dzwonek nie wyszedł job=%s user=%s", own.id, user_id
                )


# ── Otwarte podobne i propozycje dla HoR ───────────────────────────────────


async def _open_job_ids(db: AsyncSession) -> list[int]:
    return [
        int(job_id)
        for job_id in (
            await db.execute(
                select(Job.id).where(
                    Job.status != JobStatus.closed, Job.work_state.in_(_work_states())
                )
            )
        ).scalars()
    ]


async def _nearest(
    refs: Sequence[int], candidates: Sequence[int], *, limit: int
) -> Optional[dict[int, list[tuple[int, float]]]]:
    from app.services import embedding_service  # noqa: PLC0415

    try:
        return await embedding_service.nearest_jobs_for_job_ids(
            list(refs), list(candidates), limit=limit
        )
    except Exception:  # noqa: BLE001 — podpowiedź, nie warunek
        logger.warning("job twins: vector ranking unavailable", exc_info=True)
        return None


async def open_similar(db: AsyncSession, job: Job) -> list[tuple[int, int]]:
    """Otwarte rekrutacje podobne do ``job``: ``[(job_id, podobieństwo %)]``.

    Kolejność: P1 na górze, potem podobieństwo. Bez wektora albo przy awarii
    Qdranta — zapas leksykalny z puli ``job_similarity`` (próg 55)."""
    from app.services import job_similarity as sim  # noqa: PLC0415

    open_ids = [jid for jid in await _open_job_ids(db) if jid != job.id]
    if not open_ids:
        return []
    hits = await _nearest([job.id], open_ids, limit=OPEN_SIMILAR_LIMIT * 3)
    ranked: list[tuple[int, int]]
    if hits is not None and job.id in hits:
        ranked = [
            (jid, max(0, min(100, round(cos * 100)))) for jid, cos in hits[job.id]
        ]
    else:
        pool = await sim._load_pool(db)  # noqa: SLF001 — ta sama pula co „Podobne”
        allowed = set(open_ids)
        ranked = [
            (item[0], item[1])
            for item in sim._lexical_ranked(pool, sim._as_pool_job(job), ())  # noqa: SLF001
            if item[0] in allowed
        ]
    ranked = ranked[:OPEN_SIMILAR_LIMIT]
    if not ranked:
        return []
    p1 = set(
        (
            await db.execute(
                select(Job.id).where(
                    Job.id.in_([jid for jid, _ in ranked]),
                    Job.priority.in_(P1_PRIORITIES),
                )
            )
        ).scalars()
    )
    return sorted(ranked, key=lambda item: (item[0] not in p1, -item[1], item[0]))


@dataclass(frozen=True)
class Suggestion:
    job_id: int
    other_id: int
    similarity: int


_suggestion_cache: dict[str, Any] = {"at": 0.0, "items": None}


def reset_suggestion_cache() -> None:
    _suggestion_cache["at"] = 0.0
    _suggestion_cache["items"] = None


async def _raw_suggestions(db: AsyncSession) -> list[Suggestion]:
    if (
        _suggestion_cache["items"] is not None
        and time.monotonic() - _suggestion_cache["at"] < _SUGGESTION_TTL_SECONDS
    ):
        return _suggestion_cache["items"]
    open_ids = await _open_job_ids(db)
    hits = await _nearest(open_ids, open_ids, limit=10)
    if hits is None:
        return []
    best: dict[tuple[int, int], float] = {}
    for ref, neighbours in hits.items():
        for other, cosine in neighbours:
            if cosine < SUGGESTION_MIN_COSINE or other == ref:
                continue
            key = (min(ref, other), max(ref, other))
            best[key] = max(best.get(key, 0.0), cosine)
    items = [
        Suggestion(job_id=a, other_id=b, similarity=round(cos * 100))
        for (a, b), cos in sorted(best.items(), key=lambda kv: (-kv[1], kv[0]))
    ]
    _suggestion_cache["items"] = items
    _suggestion_cache["at"] = time.monotonic()
    return items


async def suggestions(db: AsyncSession) -> list[Suggestion]:
    """Możliwe bliźniaki dla HoR: otwarte pary z różnymi Delivery Leadami
    (DL nie widzi cudzych requestów), jeszcze nie połączone jako bliźniaki
    i nie odrzucone („To nie bliźniak”)."""
    raw = await _raw_suggestions(db)
    if not raw:
        return []
    ids = sorted({s.job_id for s in raw} | {s.other_id for s in raw})
    jobs = {
        job.id: job
        for job in (await db.execute(select(Job).where(Job.id.in_(ids)))).scalars()
    }
    twins = {
        (row.job_id, row.similar_job_id)
        for rows in (await twin_links(db, ids)).values()
        for row in rows
    }
    dismissed = {
        (row.job_low_id, row.job_high_id)
        for row in (
            await db.execute(
                select(JobTwinDismissal).where(JobTwinDismissal.job_low_id.in_(ids))
            )
        ).scalars()
    }
    out: list[Suggestion] = []
    for item in raw:
        a, b = jobs.get(item.job_id), jobs.get(item.other_id)
        if a is None or b is None or not is_open(a) or not is_open(b):
            continue
        if (item.job_id, item.other_id) in twins or (
            item.job_id,
            item.other_id,
        ) in dismissed:
            continue
        if a.delivery_lead_id is not None and a.delivery_lead_id == b.delivery_lead_id:
            continue
        out.append(item)
        if len(out) >= SUGGESTION_LIMIT:
            break
    return out


# ── Bramka ruchu i stawka ──────────────────────────────────────────────────


async def _pair_done_in_twin(
    db: AsyncSession, *, candidate_id: int, twin: Job, user: User
) -> bool:
    """Czy osoba ma już screening pod bliźniaka (albo nie ma czego robić).

    Tak, gdy w bliźniaku: stoi na „Zweryfikowanym” albo dalej, jej karta jest
    zamknięta (odrzucenie, rezygnacja), ma zapisany screening tej próby,
    albo ma u klienta bliźniaka aktywny konflikt (czarna lista, NDA)."""
    from app.models.candidate import Candidate  # noqa: PLC0415
    from app.services import move_requirements  # noqa: PLC0415
    from app.services.pipeline_move_rules import gate_stage_row  # noqa: PLC0415

    if not is_open(twin):
        return True
    from app.models.recruitment_pipeline import CandidateStage  # noqa: PLC0415
    from app.services.candidate_claim import stage_column  # noqa: PLC0415

    latest = await db.scalar(
        select(CandidateStage)
        .where(
            CandidateStage.candidate_id == candidate_id,
            CandidateStage.job_id == twin.id,
        )
        .order_by(CandidateStage.moved_at.desc(), CandidateStage.id.desc())
        .limit(1)
    )
    if latest is not None and await stage_column(db, latest) == "closed":
        return True
    # Para bez wierszy stoi w „new” — osobę trzeba dodać i zrobić screening.
    _row, column = await gate_stage_row(db, candidate_id=candidate_id, job_id=twin.id)
    if column not in ("new", "screening"):
        return True
    candidate = await db.get(Candidate, candidate_id)
    if candidate is None:
        return True
    facts = await move_requirements.load_pair_facts(
        db, candidate=candidate, job=twin, user=user
    )
    _key, met = move_requirements.screening_requirement(facts)
    if met:
        return True
    return await _client_conflict(
        db, candidate_id=candidate_id, client_id=twin.client_id
    )


async def _client_conflict(
    db: AsyncSession, *, candidate_id: int, client_id: int
) -> bool:
    from datetime import datetime, timezone  # noqa: PLC0415

    from app.models.candidate_conflict import (  # noqa: PLC0415
        CandidateConflict,
        ConflictType,
        active_unexpired_clause,
    )

    row = await db.scalar(
        select(CandidateConflict.id)
        .where(
            CandidateConflict.candidate_id == candidate_id,
            CandidateConflict.client_id == client_id,
            CandidateConflict.type.in_((ConflictType.blacklist, ConflictType.nda)),
            active_unexpired_clause(datetime.now(timezone.utc)),
        )
        .limit(1)
    )
    return row is not None


async def missing_twin_screenings(
    db: AsyncSession, *, candidate_id: int, job: Job, user: User
) -> list[Job]:
    """Bliźniaki, w których osoba nie ma jeszcze screeningu.

    Tylko te, w których patrzący jest w zespole: poza zespołem nie zapisze
    ani nie przesunie osoby (``ensure_job_membership``). Zespoły bliźniaków
    zwykle się pokrywają (staging 28.10: ZOB-2947/2964/2904 — te same osoby)."""
    from app.api.recruitment_access import ensure_job_membership  # noqa: PLC0415

    twins = await twin_ids(db, job.id)
    if not twins:
        return []
    jobs = list(
        (
            await db.execute(select(Job).where(Job.id.in_(twins)).order_by(Job.id))
        ).scalars()
    )
    out: list[Job] = []
    for twin in jobs:
        try:
            await ensure_job_membership(db, user, twin.id)
        except HTTPException:
            continue
        if not await _pair_done_in_twin(
            db, candidate_id=candidate_id, twin=twin, user=user
        ):
            out.append(twin)
    return out


async def assert_twin_screening(
    db: AsyncSession,
    *,
    candidate_id: int,
    job: Job,
    user: User,
    target_column: str,
    skips: Optional[Mapping[int, str]] = None,
) -> list[dict[str, Any]]:
    """409 ``TWIN_SCREENING_REQUIRED`` — „Zweryfikowany” bez screeningu pod
    bliźniaka. Pominięcie z powodem (``skips``: rekrutacja → kod powodu)
    przepuszcza i wraca do wołającego jako ślad ruchu."""
    from app.services.pipeline_move_rules import (  # noqa: PLC0415
        VERIFIED_GATE_FROM_COLUMNS,
        VERIFIED_GATE_TARGETS,
        gate_stage_row,
    )

    if target_column not in VERIFIED_GATE_TARGETS or not await twin_ids(db, job.id):
        return []
    _row, column = await gate_stage_row(db, candidate_id=candidate_id, job_id=job.id)
    if column not in VERIFIED_GATE_FROM_COLUMNS:
        return []
    missing = await missing_twin_screenings(
        db, candidate_id=candidate_id, job=job, user=user
    )
    skips = skips or {}
    skipped = [
        {"job_id": twin.id, "reason": skips[twin.id]}
        for twin in missing
        if skips.get(twin.id) in SKIP_REASONS
    ]
    blocking = [twin for twin in missing if skips.get(twin.id) not in SKIP_REASONS]
    if not blocking:
        return skipped
    from app.services.job_working_title import display_title  # noqa: PLC0415

    names = ", ".join(twin.reference_number or display_title(twin) for twin in blocking)
    raise HTTPException(
        status_code=409,
        detail={
            "code": "TWIN_SCREENING_REQUIRED",
            "message": (
                f"Ta osoba idzie też do bliźniaka: {names}. Zrób screening razem "
                "(„Screening dla”) albo pomiń bliźniaka z powodem."
            ),
            "twins": [
                {
                    "job_id": twin.id,
                    "reference_number": twin.reference_number,
                    "title": display_title(twin),
                }
                for twin in blocking
            ],
            "skip_reasons": SKIP_REASONS,
        },
    )


async def assert_rate_within_budget(
    db: AsyncSession,
    *,
    job: Job,
    amount: Any,
    unit: Optional[str],
    currency: Optional[str],
) -> None:
    """W rekrutacji z bliźniakiem stawka kandydata ponad budżet się nie zapisze
    (decyzja Artura 28.10.2026). Bez budżetu — bez limitu. Waluta inna niż PLN
    albo nieprzeliczalna jednostka — bez porównania, jak w ostrzeżeniu."""
    from app.services.candidate_rate_observations import hourly_from_unit  # noqa: PLC0415
    from app.services.dealbreaker_filters import resolve_job_budget_hourly  # noqa: PLC0415

    if amount is None or not await twin_ids(db, job.id):
        return
    budget = resolve_job_budget_hourly(job)
    if budget is None:
        return
    hourly = hourly_from_unit(amount, unit, currency)
    if hourly is None or hourly <= Decimal(str(budget)):
        return
    raise HTTPException(
        status_code=422,
        detail={
            "code": "twin_rate_over_budget",
            "message": (
                f"Najwyżej {Decimal(str(budget)).normalize():f} zł/h — tyle wynosi budżet "
                f"{job.reference_number or 'tej rekrutacji'}. Zaproponuj stawkę "
                "w budżecie albo niższą."
            ),
            "budget_hourly": float(budget),
        },
    )
