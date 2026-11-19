"""Dopuszczalność wielu Tablic naraz (`evaluate_candidates_for_jobs_with_verdicts`).

„Moje następne kroki” składa do 25 Tablic; dotąd każda pytała osobno
o kandydatów, konflikty, umowy i weto managera. Wariant hurtowy daje dla
każdej rekrutacji dokładnie to, co pojedyncza funkcja, a liczba zapytań nie
rośnie z liczbą rekrutacji. Osoby i firmy są zmyślone.
"""

from __future__ import annotations

import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone

from sqlalchemy import event

import app.models  # noqa: F401  (rejestracja wszystkich mapperów)
from app.core.database import AsyncSessionLocal, engine
from app.core.scheduling import business_today
from app.models.candidate import Candidate, CandidateStatus
from app.models.candidate_conflict import CandidateConflict, ConflictType
from app.models.client import Client
from app.models.contact import Contact
from app.models.contract import Contract, ContractStatus
from app.models.job import Job, JobStatus
from app.models.pipeline_template import PipelineTemplate, RejectionReason, TerminalType
from app.models.recruitment_pipeline import CandidateStage, PipelineStage
from app.services.candidate_job_eligibility import EligibilityReason
from app.services.pipeline_eligibility import (
    evaluate_candidates_for_job_with_verdicts,
    evaluate_candidates_for_jobs_with_verdicts,
)


def _now() -> datetime:
    return datetime.now(timezone.utc)


@contextmanager
def count_statements():
    seen: list[str] = []

    def _on(conn, cursor, statement, parameters, context, executemany):
        seen.append(statement)

    event.listen(engine.sync_engine, "before_cursor_execute", _on)
    try:
        yield seen
    finally:
        event.remove(engine.sync_engine, "before_cursor_execute", _on)


async def _seed() -> dict:
    """Dwaj klienci, jeden manager w trzech rekrutacjach, rekrutacja bez managera.

    * ``nda`` — NDA u klienta A (tylko A),
    * ``hired_b`` — żywa umowa u klienta B (tylko B),
    * ``vetoed`` — odrzucony po rozmowie przez managera w rekrutacji ``source``.
    """
    tag = uuid.uuid4().hex[:8]
    async with AsyncSessionLocal() as db:
        client_a = Client(name=f"HurtA-{tag}")
        client_b = Client(name=f"HurtB-{tag}")
        db.add_all([client_a, client_b])
        await db.flush()
        manager = Contact(client_id=client_a.id, name=f"Anna Hurt-{tag}")
        template = PipelineTemplate(name=f"HurtTpl-{tag}")
        db.add_all([manager, template])
        await db.flush()
        source = Job(
            title=f"Zrodlo-{tag}",
            status=JobStatus.published,
            client_id=client_a.id,
            hiring_manager_contact_id=manager.id,
        )
        job_a = Job(
            title=f"A-{tag}",
            status=JobStatus.published,
            client_id=client_a.id,
            hiring_manager_contact_id=manager.id,
        )
        job_b = Job(
            title=f"B-{tag}",
            status=JobStatus.published,
            client_id=client_b.id,
            hiring_manager_contact_id=manager.id,
        )
        no_manager = Job(
            title=f"BezHM-{tag}", status=JobStatus.published, client_id=client_a.id
        )
        reason = RejectionReason(
            template_id=template.id,
            name=f"Za slaby-{tag}",
            category=TerminalType.rejected,
            disqualifies_person=True,
        )
        people = [
            Candidate(
                name="Ewa",
                lastname=f"{label}-{tag}",
                email=f"{label}-{tag}@example.com",
                status=CandidateStatus.active,
            )
            for label in ("nda", "hiredb", "vetoed", "plain")
        ]
        db.add_all([source, job_a, job_b, no_manager, reason, *people])
        await db.flush()
        nda, hired_b, vetoed, plain = (p.id for p in people)
        db.add_all(
            [
                CandidateConflict(
                    candidate_id=nda,
                    client_id=client_a.id,
                    type=ConflictType.nda,
                    active=True,
                ),
                Contract(
                    candidate_id=hired_b,
                    client_id=client_b.id,
                    start_date=business_today() - timedelta(days=30),
                    status=ContractStatus.active,
                ),
                CandidateStage(
                    candidate_id=vetoed,
                    job_id=source.id,
                    stage=PipelineStage.client_interview,
                    moved_at=_now() - timedelta(days=20),
                ),
                CandidateStage(
                    candidate_id=vetoed,
                    job_id=source.id,
                    stage=PipelineStage.rejected,
                    moved_at=_now() - timedelta(days=19),
                    rejection_reason_id=reason.id,
                ),
            ]
        )
        await db.commit()
        return {
            "source": source.id,
            "a": job_a.id,
            "b": job_b.id,
            "no_manager": no_manager.id,
            "nda": nda,
            "hired_b": hired_b,
            "vetoed": vetoed,
            "plain": plain,
        }


async def _jobs(db, ids: list[int]) -> list[Job]:
    return [await db.get(Job, job_id) for job_id in ids]


async def test_each_job_gets_exactly_what_the_single_call_gives():
    w = await _seed()
    everyone = [w["nda"], w["hired_b"], w["vetoed"], w["plain"]]
    boards = {
        w["a"]: everyone,
        w["b"]: everyone,
        w["no_manager"]: [w["nda"], w["vetoed"]],
        # Weto liczy się z INNEJ rekrutacji — źródło nie wetuje samego siebie.
        w["source"]: [w["vetoed"], w["plain"]],
    }
    async with AsyncSessionLocal() as db:
        jobs = await _jobs(db, list(boards))
        bulk = await evaluate_candidates_for_jobs_with_verdicts(
            db, jobs=jobs, candidate_ids_by_job=boards, now=_now()
        )
        assert set(bulk) == set(boards)
        for job in jobs:
            single = await evaluate_candidates_for_job_with_verdicts(
                db, job=job, candidate_ids=boards[job.id], now=_now()
            )
            assert bulk[job.id] == single, job.title

    def reason(job_id: int, cid: int) -> EligibilityReason:
        return bulk[job_id][0][cid].reason_code

    # NDA u A nie przecieka na Tablicę klienta B, umowa u B nie przecieka na A.
    assert reason(w["a"], w["nda"]) is EligibilityReason.client_nda
    assert reason(w["b"], w["nda"]) is EligibilityReason.eligible
    assert reason(w["b"], w["hired_b"]) is EligibilityReason.client_current_employment
    assert reason(w["a"], w["hired_b"]) is EligibilityReason.eligible
    # Weto managera: w jego rekrutacjach tak, bez managera i w źródle — nie.
    assert set(bulk[w["a"]][1]) == {w["vetoed"]}
    assert set(bulk[w["b"]][1]) == {w["vetoed"]}
    assert bulk[w["no_manager"]][1] == {}
    assert bulk[w["source"]][1] == {}
    # Para spoza wejścia nie trafia do wyniku.
    assert set(bulk[w["no_manager"]][0]) == {w["nda"], w["vetoed"]}
    assert set(bulk[w["source"]][0]) == {w["vetoed"], w["plain"]}


async def test_light_rows_and_empty_boards():
    w = await _seed()
    async with AsyncSessionLocal() as db:
        jobs = await _jobs(db, [w["a"], w["b"]])
        rows = {
            c.id: c
            for c in [
                await db.get(Candidate, w["nda"]),
                await db.get(Candidate, w["plain"]),
            ]
        }
        with count_statements() as seen:
            empty = await evaluate_candidates_for_jobs_with_verdicts(
                db, jobs=jobs, candidate_ids_by_job={}, now=_now()
            )
        assert empty == {w["a"]: ({}, {}), w["b"]: ({}, {})}
        assert seen == []
        # Kandydat spoza `candidates` (lekkich wierszy) po prostu nie ma decyzji.
        out = await evaluate_candidates_for_jobs_with_verdicts(
            db,
            jobs=jobs,
            candidate_ids_by_job={
                w["a"]: [w["nda"], w["vetoed"]],
                w["b"]: [w["plain"]],
            },
            now=_now(),
            candidates=rows,
        )
    assert set(out[w["a"]][0]) == {w["nda"]}
    assert set(out[w["a"]][1]) == {w["vetoed"]}
    assert set(out[w["b"]][0]) == {w["plain"]}


async def test_query_count_does_not_grow_with_jobs():
    w = await _seed()
    everyone = [w["nda"], w["hired_b"], w["vetoed"], w["plain"]]
    async with AsyncSessionLocal() as db:
        jobs = await _jobs(db, [w["a"], w["b"], w["no_manager"]])
        with count_statements() as one:
            await evaluate_candidates_for_jobs_with_verdicts(
                db, jobs=jobs[:1], candidate_ids_by_job={w["a"]: everyone}, now=_now()
            )
        with count_statements() as three:
            await evaluate_candidates_for_jobs_with_verdicts(
                db,
                jobs=jobs,
                candidate_ids_by_job={job.id: everyone for job in jobs},
                now=_now(),
            )
    # Kandydaci, konflikty, umowy, weto — po jednym zapytaniu.
    assert len(one) == 4, one
    assert len(three) == len(one), (len(one), len(three))
