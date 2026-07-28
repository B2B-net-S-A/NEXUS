"""Deterministyczny backfill RecruitmentProcess z legacy CandidateStage (PR-06).

Reguły (sekcja 14.2 planu + decyzje Artura):

1. Grupowanie par ``(candidate_id, job_id)``; porządek eventów pary ZAWSZE
   ``(moved_at ASC, id ASC)`` — zamrożona definicja.
2. Jedna para = JEDEN proces, ``attempt_no=1`` (decyzja §20.2: reopen = ten
   sam proces; nowy attempt tylko przyszłą jawną komendą). Zero zgadywania
   granic historycznych podejść.
3. Current pointer = latest legacy row (``moved_at DESC, id DESC``).
4. ``status``: ``closed`` gdy latest jest terminalny (stage_def.is_terminal
   LUB legacy enum ∈ {hired, rejected, withdrawn}); inaczej ``open``.
5. Semantyka: latest.stage_def → StageRevision (bridge ``source_stage_def_id``
   w OPUBLIKOWANEJ rewizji) → semantic_key; fallback legacy enum →
   ``LEGACY_TO_SEMANTIC``; brak → ``unmapped`` (kwarantanna, nie zgadujemy).
6. Idempotencja: pary z istniejącym procesem są pomijane (insert-only).
   Opcjonalny ``resync_stale=True`` aktualizuje procesy backfillowe, których
   latest legacy się zmienił (legacy wciąż jest authority do PR-08) —
   deterministyczna funkcja źródła, więc rerun na niezmienionych danych
   niczego nie zmienia (AC planu).

Wydajność: keyset-pagination po parach + zbiorczy fetch eventów batcha
(tuple IN) + mapy stage_def→revision i template→published-revision liczone
raz na start. 79 581 par (baseline PR-00) ≈ kilkaset batchy po 500.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy import exists, func, select, tuple_
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.candidate import Candidate
from app.models.job import Job
from app.models.pipeline_template import PipelineStageDef
from app.models.recruitment_pipeline import (
    CandidateStage,
    PipelineStage,
    VerificationStatus,
)
from app.models.recruitment_priority import (
    PriorityOriginKind,
    RecruitmentPriorityState,
)
from app.models.recruitment_process import ProcessStatus, RecruitmentProcess
from app.models.workflow_revision import (
    StageRevision,
    WorkflowDefinition,
    WorkflowRevision,
    WorkflowRevisionStatus,
)
from app.services.semantic_states import LEGACY_TO_SEMANTIC

logger = logging.getLogger(__name__)

_TERMINAL_LEGACY = {"hired", "rejected", "withdrawn"}
BATCH_PAIRS = 500


async def _build_lookup_maps(
    db: AsyncSession,
) -> tuple[dict[int, tuple[int, str, int]], dict[int, int], Optional[int]]:
    """(stage_def→(stage_rev, semantic, wf_rev), template→wf_rev, default_tpl)."""
    rows = (
        await db.execute(
            select(
                StageRevision.source_stage_def_id,
                StageRevision.id,
                StageRevision.semantic_key,
                StageRevision.workflow_revision_id,
            )
            .join(
                WorkflowRevision,
                WorkflowRevision.id == StageRevision.workflow_revision_id,
            )
            .where(
                WorkflowRevision.status == WorkflowRevisionStatus.published,
                StageRevision.source_stage_def_id.is_not(None),
            )
        )
    ).all()
    stage_def_map = {sd: (sr, sem, wr) for sd, sr, sem, wr in rows if sd is not None}

    tpl_rows = (
        await db.execute(
            select(WorkflowDefinition.template_id, WorkflowRevision.id)
            .join(
                WorkflowRevision,
                WorkflowRevision.workflow_id == WorkflowDefinition.id,
            )
            .where(
                WorkflowRevision.status == WorkflowRevisionStatus.published,
                WorkflowDefinition.template_id.is_not(None),
            )
        )
    ).all()
    template_map = {tpl: wr for tpl, wr in tpl_rows}

    from app.models.pipeline_template import PipelineTemplate

    default_tpl = await db.scalar(
        select(PipelineTemplate.id).where(PipelineTemplate.is_default.is_(True))
    )
    return stage_def_map, template_map, default_tpl


def _is_terminal_row(row: CandidateStage, stage_def_terminal: dict[int, bool]) -> bool:
    if row.stage_def_id is not None and stage_def_terminal.get(row.stage_def_id):
        return True
    return row.stage.value in _TERMINAL_LEGACY


async def backfill_recruitment_processes(
    db: AsyncSession,
    *,
    limit_pairs: Optional[int] = None,
    resync_stale: bool = False,
    progress: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    """Insert-only backfill (+ opcjonalny resync stale). Caller NIE commituje —
    funkcja commituje per batch (79k par w jednej transakcji = bez sensu)."""
    prog = progress if progress is not None else {}
    prog.setdefault("pairs_seen", 0)
    prog.setdefault("created", 0)
    prog.setdefault("skipped_existing", 0)
    prog.setdefault("resynced", 0)
    prog.setdefault("unmapped_semantic", 0)

    stage_def_map, template_map, default_tpl = await _build_lookup_maps(db)

    # Terminalność stage_defów — jedna mapa (unikamy N zapytań).
    sd_terminal = dict(
        (
            await db.execute(select(PipelineStageDef.id, PipelineStageDef.is_terminal))
        ).all()
    )
    # Job → (template, client, recruiter) — do effective template i denormów.
    job_info: dict[int, tuple[Optional[int], Optional[int], Optional[int]]] = {}

    prog["total_pairs"] = (
        await db.scalar(
            select(
                func.count(
                    func.distinct(
                        tuple_(CandidateStage.candidate_id, CandidateStage.job_id)
                    )
                )
            )
        )
    ) or 0

    last_pair: tuple[int, int] = (0, 0)
    processed = 0
    while True:
        if limit_pairs is not None and processed >= limit_pairs:
            break
        batch_cap = BATCH_PAIRS
        if limit_pairs is not None:
            batch_cap = min(batch_cap, limit_pairs - processed)

        pair_query = (
            select(CandidateStage.candidate_id, CandidateStage.job_id)
            .where(
                tuple_(CandidateStage.candidate_id, CandidateStage.job_id) > last_pair
            )
            .group_by(CandidateStage.candidate_id, CandidateStage.job_id)
            .order_by(CandidateStage.candidate_id, CandidateStage.job_id)
            .limit(batch_cap)
        )
        if not resync_stale:
            # Every bounded rerun advances naturally: already reconciled pairs
            # are excluded before LIMIT instead of consuming the same first
            # page forever.  Resync deliberately scans all pairs because it
            # must compare existing pointers.
            pair_query = pair_query.where(
                ~exists(
                    select(RecruitmentProcess.id).where(
                        RecruitmentProcess.candidate_id == CandidateStage.candidate_id,
                        RecruitmentProcess.job_id == CandidateStage.job_id,
                    )
                )
            )
        pairs = (await db.execute(pair_query)).all()
        if not pairs:
            break
        last_pair = (pairs[-1][0], pairs[-1][1])
        processed += len(pairs)
        prog["pairs_seen"] = processed

        pair_keys = [(c, j) for c, j in pairs]

        # Match the command service's lock hierarchy. Lock candidate ids first
        # so a live transition cannot race this batch's stage/process snapshot.
        candidate_ids = sorted({candidate_id for candidate_id, _ in pair_keys})
        await db.execute(
            select(Candidate.id)
            .where(Candidate.id.in_(candidate_ids))
            .order_by(Candidate.id)
            .with_for_update()
        )

        # Select and lock every attempt deterministically, then retain the
        # newest attempt for each pair. A plain dict comprehension over an
        # unordered result could mutate an arbitrary historical attempt.
        process_rows = (
            (
                await db.execute(
                    select(RecruitmentProcess)
                    .where(
                        tuple_(
                            RecruitmentProcess.candidate_id,
                            RecruitmentProcess.job_id,
                        ).in_(pair_keys)
                    )
                    .order_by(
                        RecruitmentProcess.candidate_id,
                        RecruitmentProcess.job_id,
                        RecruitmentProcess.attempt_no.desc(),
                        RecruitmentProcess.id.desc(),
                    )
                    .with_for_update()
                )
            )
            .scalars()
            .all()
        )
        existing: dict[tuple[int, int], RecruitmentProcess] = {}
        for process in process_rows:
            existing.setdefault(
                (process.candidate_id, process.job_id),
                process,
            )

        # Wszystkie eventy batcha, kanoniczny porządek.
        events = (
            (
                await db.execute(
                    select(CandidateStage)
                    .where(
                        tuple_(CandidateStage.candidate_id, CandidateStage.job_id).in_(
                            pair_keys
                        )
                    )
                    .order_by(
                        CandidateStage.candidate_id,
                        CandidateStage.job_id,
                        CandidateStage.moved_at.asc(),
                        CandidateStage.id.asc(),
                    )
                )
            )
            .scalars()
            .all()
        )
        grouped: dict[tuple[int, int], list[CandidateStage]] = {}
        for ev in events:
            grouped.setdefault((ev.candidate_id, ev.job_id), []).append(ev)

        # Joby batcha (template/client/recruiter).
        missing_jobs = {j for _, j in pair_keys if j not in job_info}
        if missing_jobs:
            for jid, tpl, cli, rec in (
                await db.execute(
                    select(
                        Job.id,
                        Job.pipeline_template_id,
                        Job.client_id,
                        Job.recruiter_id,
                    ).where(Job.id.in_(missing_jobs))
                )
            ).all():
                job_info[jid] = (tpl, cli, rec)

        for key in pair_keys:
            history = grouped.get(key)
            if not history:
                continue  # defensywnie — para bez eventów nie istnieje
            earliest, latest = history[0], history[-1]
            tpl_id, client_id, recruiter_id = job_info.get(key[1], (None, None, None))
            effective_tpl = tpl_id or default_tpl

            mapped = (
                stage_def_map.get(latest.stage_def_id)
                if latest.stage_def_id is not None
                else None
            )
            if mapped is not None:
                stage_rev_id, semantic, wf_rev_id = mapped
            else:
                stage_rev_id = None
                semantic = LEGACY_TO_SEMANTIC.get(latest.stage.value, "unmapped")
                wf_rev_id = template_map.get(effective_tpl) if effective_tpl else None
            if semantic == "unmapped":
                prog["unmapped_semantic"] += 1

            is_closed = _is_terminal_row(latest, sd_terminal)
            status = ProcessStatus.closed if is_closed else ProcessStatus.open
            first_accepted_verification = next(
                (
                    event
                    for event in history
                    if event.stage == PipelineStage.verified
                    and event.verification_status == VerificationStatus.active
                    and event.moved_by is not None
                ),
                None,
            )
            legacy_credit_user_id = (
                first_accepted_verification.moved_by
                if first_accepted_verification is not None
                else None
            )

            current = existing.get(key)
            if current is not None:
                provenance_changed = False
                # Origin is immutable provenance, not write authority. A
                # legacy-origin process may already have advanced through the
                # live command layer, so only rows still owned by this
                # backfill may be repaired/resynchronised here.
                backfill_owned = current.source_authority == "backfill"
                if backfill_owned and current.origin_kind is None:
                    current.origin_kind = PriorityOriginKind.legacy
                    provenance_changed = True
                if (
                    backfill_owned
                    and current.credit_user_id is None
                    and legacy_credit_user_id is not None
                ):
                    current.credit_user_id = legacy_credit_user_id
                    provenance_changed = True
                if backfill_owned and current.owner_user_id is None:
                    current.owner_user_id = (
                        legacy_credit_user_id or earliest.moved_by or recruiter_id
                    )
                    provenance_changed = current.owner_user_id is not None
                # Rerun: nie ruszamy, chyba że jawny resync i latest się zmienił
                # (legacy = authority do PR-08).
                if (
                    resync_stale
                    and backfill_owned
                    and current.legacy_current_candidate_stage_id != latest.id
                ):
                    current.legacy_current_candidate_stage_id = latest.id
                    current.current_stage_revision_id = stage_rev_id
                    current.current_semantic_state = semantic
                    current.workflow_revision_id = (
                        wf_rev_id or current.workflow_revision_id
                    )
                    current.status = status
                    current.closed_at = latest.moved_at if is_closed else None
                    current.state_version = current.state_version + 1
                    prog["resynced"] += 1
                elif provenance_changed:
                    current.state_version = current.state_version + 1
                    prog["resynced"] += 1
                else:
                    prog["skipped_existing"] += 1
                continue

            db.add(
                RecruitmentProcess(
                    candidate_id=key[0],
                    job_id=key[1],
                    client_id=client_id,
                    attempt_no=1,
                    workflow_revision_id=wf_rev_id,
                    current_stage_revision_id=stage_rev_id,
                    current_semantic_state=semantic,
                    legacy_current_candidate_stage_id=latest.id,
                    state_version=1,
                    status=status,
                    owner_user_id=(
                        legacy_credit_user_id or earliest.moved_by or recruiter_id
                    ),
                    credit_user_id=legacy_credit_user_id,
                    origin_kind=PriorityOriginKind.legacy,
                    # NULL is intentional: historical pairs retain the legacy
                    # KPI fallback, while origin_kind marks them reconciled.
                    kpi_eligible=None,
                    kpi_eligibility_reason="LEGACY_BACKFILL",
                    source_authority="backfill",
                    opened_at=earliest.moved_at,
                    closed_at=latest.moved_at if is_closed else None,
                )
            )
            prog["created"] += 1

        await db.commit()

    priority_state = await db.scalar(
        select(RecruitmentPriorityState).where(RecruitmentPriorityState.id == 1)
    )
    if priority_state is not None:
        priority_state.last_reconciled_at = datetime.now(timezone.utc)
        priority_state.row_version += 1
        await db.commit()

    return dict(prog)


async def compare_shadow_state(
    db: AsyncSession, *, sample_limit: int = 20
) -> dict[str, Any]:
    """Komparator shadow: proces vs faktyczny latest legacy row pary.

    Mismatch = legacy poszedł dalej po backfillu (runtime wciąż pisze
    CandidateStage) albo para nie ma jeszcze procesu. Miara lagu przed
    przejęciem authority w PR-07/08.
    """
    latest_sql = """
        WITH latest AS (
            SELECT DISTINCT ON (candidate_id, job_id)
                candidate_id, job_id, id
            FROM candidate_stages
            ORDER BY candidate_id, job_id, moved_at DESC, id DESC
        )
        SELECT
            (SELECT COUNT(*) FROM latest) AS pairs_total,
            (SELECT COUNT(*) FROM recruitment_processes) AS processes_total,
            (
                SELECT COUNT(*)
                FROM latest l
                LEFT JOIN recruitment_processes p
                  ON p.candidate_id = l.candidate_id AND p.job_id = l.job_id
                WHERE p.id IS NULL
            ) AS pairs_without_process,
            (
                SELECT COUNT(*)
                FROM recruitment_processes p
                JOIN latest l
                  ON l.candidate_id = p.candidate_id AND l.job_id = p.job_id
                WHERE p.legacy_current_candidate_stage_id IS DISTINCT FROM l.id
            ) AS stale_pointers,
            (
                SELECT COUNT(*) FROM recruitment_processes
                WHERE current_semantic_state = 'unmapped'
            ) AS unmapped_semantic,
            (
                SELECT COUNT(*) FROM recruitment_processes WHERE status = 'open'
            ) AS open_processes
    """
    from sqlalchemy import text as sa_text

    totals = dict((await db.execute(sa_text(latest_sql))).mappings().one())

    sample_sql = """
        WITH latest AS (
            SELECT DISTINCT ON (candidate_id, job_id)
                candidate_id, job_id, id
            FROM candidate_stages
            ORDER BY candidate_id, job_id, moved_at DESC, id DESC
        )
        SELECT p.candidate_id, p.job_id,
               p.legacy_current_candidate_stage_id AS process_pointer,
               l.id AS actual_latest
        FROM recruitment_processes p
        JOIN latest l
          ON l.candidate_id = p.candidate_id AND l.job_id = p.job_id
        WHERE p.legacy_current_candidate_stage_id IS DISTINCT FROM l.id
        ORDER BY p.candidate_id DESC
        LIMIT :lim
    """
    sample = [
        dict(r)
        for r in (
            await db.execute(sa_text(sample_sql), {"lim": sample_limit})
        ).mappings()
    ]
    return {
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        **{k: int(v) for k, v in totals.items()},
        "stale_sample": sample,
    }
