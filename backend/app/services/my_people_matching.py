"""„Moi ludzie" × rekrutacja: kto z listy rekrutera pasuje do tej rekrutacji.

Dwa konsumenty jednej oceny:

- zakładka „Do tej rekrutacji" panelu (``GET /api/my-people/for-job/{id}``),
  liczona na żądanie dla osoby, która patrzy;
- dzwonek po publikacji rekrutacji (:func:`run_for_job`, wołane z workera
  auto-matcha) — jeden wpis na (odbiorca, rekrutacja).

Liczba to KANONICZNY FIT (``canonical_fit.score_candidates``), czyli ta sama,
którą rekruter widzi na ekranach C2 i w kolumnie „Dopasowanie" wyszukiwarki.
Niezmierzony wynik (brak wektora, awaria dostawcy) jest ``None`` — nigdy 0
i nigdy nie trafia do powiadomienia. Pulę zawęża najpierw Qdrant (filtr po
id), bo pełny fit dla setek osób byłby drogi, a awaria Qdranta rzuca
``AutoMatchUnavailable`` — worker ponowi zdarzenie zamiast raportować
„nikt nie pasuje".
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Iterable, Optional

from sqlalchemy import select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.scheduling import business_today
from app.models.candidate import Candidate, CandidateStatus
from app.models.job import Job, JobStatus
from app.models.my_people import MyPeopleJobMatch
from app.models.recruitment_pipeline import CandidateStage
from app.services.auto_match_service import AutoMatchUnavailable, scoped_similarity
from app.services.candidate_job_eligibility import Visibility
from app.services.current_employment import current_employment_client_ids
from app.services.eligibility_annotation import eligibility_annotation

logger = logging.getLogger(__name__)

YIELD_EVERY = 32


@dataclass
class ScoredPerson:
    candidate_id: int
    score: Optional[int]
    measurement: str
    eligibility: Optional[dict]
    hidden: bool = False


async def candidates_in_job(
    db: AsyncSession, job_id: int, ids: Iterable[int]
) -> set[int]:
    wanted = sorted({int(i) for i in ids})
    if not wanted:
        return set()
    rows = await db.scalars(
        select(CandidateStage.candidate_id)
        .where(CandidateStage.job_id == job_id, CandidateStage.candidate_id.in_(wanted))
        .distinct()
    )
    return {int(r) for r in rows.all()}


async def last_sent_to_client(
    db: AsyncSession, client_id: Optional[int], ids: Iterable[int]
) -> dict[int, datetime]:
    """Kiedy osoba ostatnio poszła do TEGO klienta (ktokolwiek wysłał)."""
    wanted = sorted({int(i) for i in ids})
    if not wanted or client_id is None:
        return {}
    rows = await db.execute(
        text(
            """
            SELECT cs.candidate_id, MAX(cs.moved_at)
            FROM candidate_stages cs
            JOIN jobs j ON j.id = cs.job_id
            WHERE cs.stage = 'cv_sent' AND j.client_id = :client_id
              AND cs.candidate_id = ANY(:ids)
            GROUP BY cs.candidate_id
            """
        ),
        {"client_id": client_id, "ids": wanted},
    )
    return {int(cid): moved for cid, moved in rows.all()}


async def score_people_for_job(
    db: AsyncSession,
    *,
    job: Job,
    candidate_ids: Iterable[int],
    profile_user_id: Optional[int],
    pool_limit: int,
) -> list[ScoredPerson]:
    """Kanoniczny fit + kwalifikowalność dla wskazanych osób w tej rekrutacji.

    Zawęża pulę do ``pool_limit`` najbliższych wektorowo. Osoby spoza tej
    części puli nie dostają wyniku (``measurement="not_in_pool"``) — to
    „nie liczyliśmy", nie „nie pasuje".
    """
    from app.services.canonical_fit import display_score, score_candidates
    from app.services.embedding_service import _build_job_text
    from app.services.pipeline_eligibility import evaluate_candidates_for_job
    from app.services.request_matching_context import build_request_context
    from app.services.scoring_service import resolve_active_profile

    ids = sorted({int(i) for i in candidate_ids})
    if not ids:
        return []
    similarity = await scoped_similarity(
        _build_job_text(job), jobs_collection=False, ids=ids
    )
    ranked = sorted(similarity, key=lambda cid: similarity[cid], reverse=True)
    pool = ranked[: max(1, pool_limit)]

    candidates = (
        list((await db.scalars(select(Candidate).where(Candidate.id.in_(pool)))).all())
        if pool
        else []
    )
    profile = await resolve_active_profile(
        db, user_id=profile_user_id, client_id=job.client_id
    )
    context = build_request_context(job, profile)
    fits = await score_candidates(db, context, candidates) if candidates else []
    decisions = await evaluate_candidates_for_job(
        db,
        job=job,
        candidate_ids=[c.id for c in candidates],
        now=datetime.now(timezone.utc),
    )

    out: list[ScoredPerson] = []
    for i, fit in enumerate(fits):
        cid = int(fit.breakdown.candidate_id)
        decision = decisions.get(cid)
        out.append(
            ScoredPerson(
                candidate_id=cid,
                score=display_score(fit.fit_score),
                measurement=fit.measurement,
                eligibility=eligibility_annotation(decision),
                hidden=bool(decision and decision.visibility is Visibility.hidden),
            )
        )
        if (i + 1) % YIELD_EVERY == 0:
            await asyncio.sleep(0)
    scored_ids = {p.candidate_id for p in out}
    out.extend(
        ScoredPerson(
            candidate_id=cid, score=None, measurement="not_in_pool", eligibility=None
        )
        for cid in ids
        if cid not in scored_ids
    )
    return out


async def run_for_job(db: AsyncSession, job: Job) -> dict:
    """Publikacja rekrutacji → dzwonek do rekruterów, których ludzie pasują.

    Idempotentne: dopasowanie jest zapisywane raz (UNIQUE na trójce), a dzwonek
    idzie tylko przy NOWYCH dopasowaniach — istotna zmiana rekrutacji, która
    odpala zdarzenie drugi raz, nie budzi rekrutera tymi samymi nazwiskami.
    """
    from app.models.notification import NotificationType
    from app.models.user import User
    from app.services.my_people import owners_by_candidate
    from app.services.notification_triggers import emit

    if not settings.MY_PEOPLE_MATCH_ENABLED:
        return {"skipped": "disabled"}
    if job.status != JobStatus.published:
        return {"skipped": "job_not_published"}

    owners = await owners_by_candidate(db)
    if not owners:
        return {"pool": 0}
    active_users = {
        int(u)
        for u in (
            await db.scalars(
                select(User.id).where(
                    User.id.in_({uid for users in owners.values() for uid in users}),
                    User.is_active.is_(True),
                )
            )
        ).all()
    }
    owners = {
        cid: users & active_users
        for cid, users in owners.items()
        if users & active_users
    }
    ids = set(owners)
    ids -= await candidates_in_job(db, job.id, ids)
    blacklisted = (
        set(
            (
                await db.scalars(
                    select(Candidate.id).where(
                        Candidate.id.in_(sorted(ids)),
                        Candidate.status == CandidateStatus.blacklisted,
                    )
                )
            ).all()
        )
        if ids
        else set()
    )
    ids -= blacklisted
    employment = await current_employment_client_ids(db, ids, today=business_today())
    ids = {cid for cid in ids if not employment.get(cid)}
    if not ids:
        return {"pool": 0}

    scored = await score_people_for_job(
        db,
        job=job,
        candidate_ids=ids,
        profile_user_id=None,
        pool_limit=settings.MY_PEOPLE_MATCH_POOL,
    )
    good = {
        p.candidate_id: p
        for p in scored
        if p.score is not None
        and not p.hidden
        and p.score >= settings.MY_PEOPLE_MATCH_MIN_SCORE
    }
    if not good:
        return {"pool": len(ids), "matched": 0}

    names = {
        c.id: f"{c.name or ''} {c.lastname or ''}".strip()
        for c in (
            await db.scalars(select(Candidate).where(Candidate.id.in_(sorted(good))))
        ).all()
    }
    per_user: dict[int, list[ScoredPerson]] = {}
    for cid, person in good.items():
        for uid in owners.get(cid, ()):
            per_user.setdefault(uid, []).append(person)

    notified = 0
    stored = 0
    for uid, people in per_user.items():
        people.sort(key=lambda p: p.score or 0, reverse=True)
        people = people[: settings.MY_PEOPLE_MATCH_MAX_PER_USER]
        inserted = (
            (
                await db.execute(
                    pg_insert(MyPeopleJobMatch)
                    .values(
                        [
                            {
                                "user_id": uid,
                                "job_id": job.id,
                                "candidate_id": p.candidate_id,
                                "score": p.score,
                            }
                            for p in people
                        ]
                    )
                    .on_conflict_do_nothing(
                        constraint="uq_my_people_job_matches_user_job_candidate"
                    )
                    .returning(MyPeopleJobMatch.candidate_id)
                )
            )
            .scalars()
            .all()
        )
        stored += len(inserted)
        if not inserted:
            continue
        fresh = [p for p in people if p.candidate_id in set(inserted)]
        top = ", ".join(
            f"{names.get(p.candidate_id) or 'kandydat'} ({p.score})" for p in fresh[:3]
        )
        more = f" i {len(fresh) - 3} więcej" if len(fresh) > 3 else ""
        try:
            created = await emit(
                db,
                user_id=uid,
                title=f"Nowa rekrutacja: {job.title} — {_people_phrase(len(fresh))} pasuje",
                message=f"Z Twojej listy „Moi ludzie”: {top}{more}.",
                ntype=NotificationType.my_people_match,
                related_entity_type="job",
                related_entity_id=job.id,
                link=f"/jobs/{job.id}?people=1",
            )
            notified += int(created is not None)
        except Exception as exc:  # noqa: BLE001 — jeden odbiorca nie psuje reszty
            logger.warning(
                "[my_people] notify failed user=%s job=%s: %s", uid, job.id, exc
            )
    return {
        "pool": len(ids),
        "matched": len(good),
        "stored": stored,
        "notified": notified,
    }


def _people_phrase(n: int) -> str:
    """„1 z Twoich ludzi", „3 z Twoich ludzi" — podmiot w liczbie pojedynczej."""
    return f"{n} z Twoich ludzi"


__all__ = [
    "AutoMatchUnavailable",
    "ScoredPerson",
    "candidates_in_job",
    "last_sent_to_client",
    "run_for_job",
    "score_people_for_job",
]
