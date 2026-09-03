"""Cortex — widok „Jakość danych": fill-rates, świeżość faktów, stan procesów.

Uczciwościowa strona modułu: zanim ktoś uwierzy heatmapie, ma zobaczyć na
jakim procencie bazy stoi i ile faktów ma nieznaną datę. Liczby celowo
podpisujemy „rekordy, nie osoby" (duplikaty kandydatów — discovery §3.6).
"""

from __future__ import annotations

from typing import Optional

from sqlalchemy import case, distinct, func, literal, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.candidate import AvailabilityStatus, Candidate
from app.models.contract import Contract, ContractStatus
from app.models.cortex import CortexSkillFact, CortexUnmatchedTerm
from app.models.job import Job, JobStatus

FRESHNESS_ORDER = ["lt_1y", "y1_3", "gt_3y", "unknown"]


async def _scalar(db: AsyncSession, stmt) -> int:
    return (await db.execute(stmt)).scalar() or 0


async def compute_coverage(db: AsyncSession) -> dict:
    candidates_total = await _scalar(db, select(func.count(Candidate.id)))

    with_cv_file = await _scalar(
        db,
        select(func.count(Candidate.id)).where(
            (Candidate.cv_storage_key.is_not(None))
            | (Candidate.cv_filename.is_not(None))
        ),
    )
    with_raw_cv_text = await _scalar(
        db,
        select(func.count(Candidate.id)).where(
            func.coalesce(Candidate.raw_cv_text, "") != ""
        ),
    )
    with_traffit_tech = await _scalar(
        db,
        select(func.count(Candidate.id)).where(
            func.coalesce(
                Candidate.cv_extracted_data.op("->>")("traffit_technologie"), ""
            )
            != ""
        ),
    )
    availability_known = await _scalar(
        db,
        select(func.count(Candidate.id)).where(
            Candidate.availability_status != AvailabilityStatus.unknown
        ),
    )

    # Fakty per źródło: wiersze + unikalni kandydaci.
    fact_rows = (
        await db.execute(
            select(
                CortexSkillFact.source,
                func.count(CortexSkillFact.id),
                func.count(distinct(CortexSkillFact.candidate_id)),
            ).group_by(CortexSkillFact.source)
        )
    ).all()
    facts_by_source = {
        src: {"facts": facts, "candidates": cands} for src, facts, cands in fact_rows
    }
    candidates_with_any_fact = await _scalar(
        db, select(func.count(distinct(CortexSkillFact.candidate_id)))
    )

    # Świeżość: kiedy fakt był prawdziwy (observed_at); NULL = uczciwe „unknown".
    freshness_bucket = case(
        (CortexSkillFact.observed_at.is_(None), literal("unknown")),
        (
            CortexSkillFact.observed_at >= func.now() - text("interval '1 year'"),
            literal("lt_1y"),
        ),
        (
            CortexSkillFact.observed_at >= func.now() - text("interval '3 years'"),
            literal("y1_3"),
        ),
        else_=literal("gt_3y"),
    ).label("bucket")
    freshness_rows = (
        await db.execute(
            select(freshness_bucket, func.count(CortexSkillFact.id)).group_by(
                freshness_bucket
            )
        )
    ).all()
    freshness = {bucket: 0 for bucket in FRESHNESS_ORDER}
    freshness.update({bucket: cnt for bucket, cnt in freshness_rows})

    # Procesy zbierania powodów (wymuszenia wchodzą w PR3 — tu tylko licznik).
    jobs_closed = await _scalar(
        db, select(func.count(Job.id)).where(Job.status == JobStatus.closed)
    )
    jobs_closed_with_reason = await _scalar(
        db,
        select(func.count(Job.id)).where(
            Job.status == JobStatus.closed, Job.close_reason.is_not(None)
        ),
    )
    contracts_ended = await _scalar(
        db,
        select(func.count(Contract.id)).where(
            Contract.status.in_([ContractStatus.ended, ContractStatus.ending])
        ),
    )
    contracts_ended_with_reason = await _scalar(
        db,
        select(func.count(Contract.id)).where(
            Contract.status.in_([ContractStatus.ended, ContractStatus.ending]),
            Contract.termination_reason.is_not(None),
        ),
    )
    contracts_natural_expiry = await _scalar(
        db,
        select(func.count(Contract.id)).where(
            Contract.status.in_([ContractStatus.ended, ContractStatus.ending]),
            Contract.termination_reason.is_(None),
            Contract.end_date.is_not(None),
            Contract.end_date < func.current_date(),
        ),
    )

    unmatched_rows = (
        await db.execute(
            select(
                CortexUnmatchedTerm.id,
                CortexUnmatchedTerm.term,
                CortexUnmatchedTerm.occurrences,
                CortexUnmatchedTerm.status,
                CortexUnmatchedTerm.last_seen_at,
            )
            .where(CortexUnmatchedTerm.status == "new")
            .order_by(CortexUnmatchedTerm.occurrences.desc())
            .limit(50)
        )
    ).all()

    # „Dane na dzień" — najświeższy fakt (discovery: nie udawaj bieżących liczb).
    data_as_of = (
        await db.execute(select(func.max(CortexSkillFact.extracted_at)))
    ).scalar()

    def pct(part: int, whole: int) -> Optional[float]:
        """Odsetek albo ``None`` — zerowy mianownik to brak podstawy do oceny.

        Dawne `0.0` mówiło „zero procent pokrycia" także wtedy, gdy nie było
        ANI JEDNEGO wiersza do pokrycia — czyli malowało na czerwono brak
        danych. To ta sama reguła co `insights_clients.ratio_pct`
        i `services/job_data_trust`.
        """
        return round(part / whole * 100, 1) if whole else None

    return {
        "data_as_of": data_as_of.isoformat() if data_as_of else None,
        "candidates": {
            "total": candidates_total,
            "with_cv_file": with_cv_file,
            "with_cv_file_pct": pct(with_cv_file, candidates_total),
            "with_raw_cv_text": with_raw_cv_text,
            "with_raw_cv_text_pct": pct(with_raw_cv_text, candidates_total),
            "with_traffit_tech": with_traffit_tech,
            "with_traffit_tech_pct": pct(with_traffit_tech, candidates_total),
            "with_any_fact": candidates_with_any_fact,
            "with_any_fact_pct": pct(candidates_with_any_fact, candidates_total),
            "availability_known": availability_known,
            "availability_known_pct": pct(availability_known, candidates_total),
        },
        "facts": {
            "by_source": facts_by_source,
            "freshness": freshness,
        },
        "processes": {
            "jobs_closed": jobs_closed,
            "jobs_closed_with_reason": jobs_closed_with_reason,
            "jobs_close_reason_pct": pct(jobs_closed_with_reason, jobs_closed),
            "contracts_ended": contracts_ended,
            "contracts_ended_with_reason": contracts_ended_with_reason,
            "contracts_natural_expiry": contracts_natural_expiry,
        },
        "unmatched_terms": [
            {
                "id": tid,
                "term": term,
                "occurrences": occurrences,
                "status": status,
                "last_seen_at": last_seen_at.isoformat() if last_seen_at else None,
            }
            for tid, term, occurrences, status, last_seen_at in unmatched_rows
        ],
    }
