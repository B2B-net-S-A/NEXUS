"""Wysłani do klienta a to, co pokazał system (decyzja Artura z 02.11.2026).

Makiety i pierwszy pomiar: https://claude.ai/artifact/8x6AxqnTihmecy2uw3Dhoh.
Pula dopełniania jest co noc nadpisywana, a wynik CV zmienia się po rozmowie, więc
uczciwie policzyć to da się tylko w chwili dodania. Przy dodaniu przez człowieka
zapisujemy w ``entry_meta["system_view"]``, gdzie osoba stała u systemu; przy
wysyłce nic już nie liczymy. Migawka nigdy nie blokuje dodania.
"""

from __future__ import annotations

import logging
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any, Optional, Sequence

from sqlalchemy import func, select

from app.models.job import Job
from app.models.job_autofill_pool import JobAutofillPool
from app.models.recruitment_pipeline import CandidateStage, PipelineStage
from app.models.recruitment_process import RecruitmentProcess
from app.services import candidate_claim

logger = logging.getLogger(__name__)

META_KEY = "system_view"
# Migawka istnieje od wdrożenia. Starsze karty idą do „Sprzed pomiaru” niezależnie
# od źródła: inaczej do mianownika wchodziłyby dawne karty od systemu, a dawne
# ręczne nie, i pierwszego dnia sekcja mówiłaby „system pokazał 100%”.
MEASURED_SINCE = datetime(2026, 11, 3, tzinfo=timezone.utc)
OUTSIDE_BASE_DAYS = 7
TOP_N = 20
NEXT_N = 40

SHOWN = ("system", "proposal", "reassign")
MISSED = (
    "top20",
    "r21_40",
    "r41_150",
    "below_pool",
    "hidden_gate",
    "cut_rules",
    "no_pool",
)
LABELS = {
    "system": "System dodał sam",
    "proposal": "Wzięte z Propozycji",
    "reassign": "Przepięte z podobnej",
    "outside_base": "Spoza bazy",
    "top20": "Ręcznie, choć w top 20",
    "r21_40": "Ręcznie, miejsce 21–40",
    "r41_150": "Ręcznie, miejsce 41–150",
    "below_pool": "Poniżej puli 150",
    "hidden_gate": "Ukryci przez bramkę",
    "cut_rules": "Odcięci regułami",
    "no_pool": "Rekrutacja bez puli",
    "no_snapshot": "Sprzed pomiaru",
}
_ORDER = (*SHOWN, "outside_base", *MISSED, "no_snapshot")


def _view_for_position(position: int) -> str:
    if position <= TOP_N:
        return "top20"
    return "r21_40" if position <= NEXT_N else "r41_150"


async def _hidden_by_gate(db, job, candidates: Sequence, now: datetime) -> set[int]:
    from app.api.matching import _gate_and_dealbreakers
    from app.services.requirement_contract import search_dealbreaker_inputs

    reasons: dict[int, str] = {}
    kept, *_ = await _gate_and_dealbreakers(
        db,
        job=job,
        ordered=list(candidates),
        now=now,
        inputs=search_dealbreaker_inputs(job),
        exclusion_reasons=reasons,
    )
    visible = {c.id for c in kept}
    return {c.id for c in candidates if c.id not in visible}


async def _cut_by_rules(db, job, candidate_ids: Sequence[int]) -> set[int]:
    from app.services.new_column_autofill import Pick, _by_rules

    picks = [
        Pick(candidate_id=cid, score=0.0, run_id=None, matched_must=(), missing_must=())
        for cid in candidate_ids
    ]
    kept = {p.candidate_id for p in await _by_rules(db, job, picks)}
    return set(candidate_ids) - kept


async def system_views(
    db, job, candidates: Sequence, *, now: datetime
) -> dict[int, dict]:
    """Gdzie każda osoba stała u systemu, zanim dodał ją człowiek."""
    from app.services.known_queue_points import facts_for

    if not candidates:
        return {}
    pool = (
        await db.execute(
            select(JobAutofillPool.candidate_id, JobAutofillPool.score).where(
                JobAutofillPool.job_id == job.id
            )
        )
    ).all()
    wanted = [c.id for c in candidates]
    facts = await facts_for(
        db,
        job_id=job.id,
        client_id=job.client_id,
        candidate_ids=sorted({int(cid) for cid, _ in pool} | set(wanted)),
        now=now,
    )
    value = {
        int(cid): float(score) + (facts[int(cid)].points if int(cid) in facts else 0)
        for cid, score in pool
    }
    # Miejsce wśród osób, których jeszcze nie ma w tej rekrutacji — tak jak
    # ``ranked_picks``; dodawana osoba z definicji jeszcze w niej nie jest.
    in_job = set(
        (
            await db.scalars(
                select(CandidateStage.candidate_id).where(
                    CandidateStage.job_id == job.id
                )
            )
        ).all()
    )
    competing = sorted(
        (v, -cid) for cid, v in value.items() if cid not in in_job or cid in wanted
    )
    competing.reverse()
    positions = {-cid: index + 1 for index, (_, cid) in enumerate(competing)}
    views: dict[int, dict] = {}
    outside_pool = []
    for candidate in candidates:
        created_at = getattr(candidate, "created_at", None)
        if created_at is not None and created_at >= now - timedelta(
            days=OUTSIDE_BASE_DAYS
        ):
            views[candidate.id] = {"view": "outside_base"}
        elif not pool:
            views[candidate.id] = {"view": "no_pool"}
        elif candidate.id in positions:
            position = positions[candidate.id]
            views[candidate.id] = {
                "view": _view_for_position(position),
                "position": position,
                "pool_size": len(competing),
            }
        else:
            outside_pool.append(candidate)
    if outside_pool:
        hidden = await _hidden_by_gate(db, job, outside_pool, now)
        rest = [c.id for c in outside_pool if c.id not in hidden]
        cut = await _cut_by_rules(db, job, rest)
        for candidate in outside_pool:
            view = (
                "hidden_gate"
                if candidate.id in hidden
                else "cut_rules"
                if candidate.id in cut
                else "below_pool"
            )
            views[candidate.id] = {"view": view, "pool_size": len(competing)}
    return views


async def snapshot_for_add(
    db, job, candidates: Sequence, *, now: datetime
) -> dict[int, dict]:
    """Migawka przy dodaniu; awaria zostawia dodanie bez migawki."""
    try:
        async with db.begin_nested():
            return await system_views(db, job, candidates, now=now)
    except Exception:  # noqa: BLE001 — pomiar nie może zablokować dodania osoby
        logger.warning("system view snapshot failed for job %s", job.id, exc_info=True)
        return {}


def with_system_view(
    entry_meta: Optional[dict], view: Optional[dict]
) -> Optional[dict]:
    if not view:
        return entry_meta
    return {**(entry_meta or {}), META_KEY: view}


def category(
    entry_source: Optional[str], entry_meta: Any, opened_at: Optional[datetime]
) -> str:
    if opened_at is None or opened_at < MEASURED_SINCE:
        return "no_snapshot"
    if entry_source == candidate_claim.ENTRY_SYSTEM:
        return "system"
    if entry_source == candidate_claim.ENTRY_PROPOSAL:
        return "proposal"
    if entry_source == candidate_claim.ENTRY_REASSIGN:
        return "reassign"
    view = entry_meta.get(META_KEY) if isinstance(entry_meta, dict) else None
    code = view.get("view") if isinstance(view, dict) else None
    return code if code in LABELS and code not in SHOWN else "no_snapshot"


def _share(part: int, whole: int) -> Optional[float]:
    return round(100.0 * part / whole, 1) if whole else None


def summarize(rows: Sequence[tuple[int, str]], titles: dict[int, str]) -> dict:
    """``rows`` = (rekrutacja, kategoria) każdej wysłanej pary."""
    counts = Counter(code for _, code in rows)
    per_job: dict[int, Counter] = defaultdict(Counter)
    for job_id, code in rows:
        per_job[job_id][code] += 1
    measured = len(rows) - counts["no_snapshot"]
    shown = sum(counts[c] for c in SHOWN)
    missed = sum(counts[c] for c in MISSED)
    worst = sorted(
        (
            (sum(c[m] for m in MISSED), job_id, c)
            for job_id, c in per_job.items()
            if any(c[m] for m in MISSED)
        ),
        key=lambda item: (-item[0], item[1]),
    )[:5]
    return {
        "total": len(rows),
        "jobs": len(per_job),
        "measured": measured,
        "shown": shown,
        "outside_base": counts["outside_base"],
        "missed": missed,
        "no_snapshot": counts["no_snapshot"],
        "shown_pct": _share(shown, measured),
        "outside_base_pct": _share(counts["outside_base"], measured),
        "missed_pct": _share(missed, measured),
        "segments": [
            {"key": code, "label": LABELS[code], "count": counts[code]}
            for code in _ORDER
            if counts[code]
        ],
        "worst_jobs": [
            {
                "job_id": job_id,
                "job_title": titles.get(job_id, ""),
                "sent": sum(c.values()),
                "missed": missed_count,
                "reasons": [
                    {"key": m, "label": LABELS[m], "count": c[m]}
                    for m in MISSED
                    if c[m]
                ],
            }
            for missed_count, job_id, c in worst
        ],
    }


async def sent_vs_system(db, *, since: datetime, until: datetime) -> dict:
    """Pary z pierwszą wysyłką do klienta w oknie ``[since, until)``."""
    from app.services.job_working_title import job_display_title_expr

    first_sent = (
        select(
            CandidateStage.job_id,
            CandidateStage.candidate_id,
            func.min(CandidateStage.moved_at).label("sent_at"),
        )
        .where(CandidateStage.stage == PipelineStage.cv_sent)
        .group_by(CandidateStage.job_id, CandidateStage.candidate_id)
        .subquery()
    )
    pairs = (
        await db.execute(
            select(first_sent.c.job_id, first_sent.c.candidate_id).where(
                first_sent.c.sent_at >= since, first_sent.c.sent_at < until
            )
        )
    ).all()
    if not pairs:
        return summarize([], {})
    job_ids = sorted({int(job_id) for job_id, _ in pairs})
    latest = (
        select(
            RecruitmentProcess.job_id,
            RecruitmentProcess.candidate_id,
            RecruitmentProcess.entry_source,
            RecruitmentProcess.entry_meta,
            RecruitmentProcess.opened_at,
        )
        .where(
            RecruitmentProcess.job_id.in_(job_ids),
            RecruitmentProcess.voided_at.is_(None),
        )
        .order_by(
            RecruitmentProcess.job_id,
            RecruitmentProcess.candidate_id,
            RecruitmentProcess.opened_at.desc().nulls_last(),
        )
        .distinct(RecruitmentProcess.job_id, RecruitmentProcess.candidate_id)
    )
    processes = {
        (row.job_id, row.candidate_id): row for row in (await db.execute(latest)).all()
    }
    rows = []
    for job_id, candidate_id in pairs:
        process = processes.get((job_id, candidate_id))
        rows.append(
            (
                int(job_id),
                category(
                    getattr(process, "entry_source", None),
                    getattr(process, "entry_meta", None),
                    getattr(process, "opened_at", None),
                ),
            )
        )
    titles = {
        int(job_id): title
        for job_id, title in (
            await db.execute(
                select(Job.id, job_display_title_expr()).where(Job.id.in_(job_ids))
            )
        ).all()
    }
    return summarize(rows, titles)
