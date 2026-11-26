"""Wynik zamkniętej rekrutacji na liście — ta sama reguła co hit ratio.

Prośba Delivery Leada z 26.11.2026: w „Zamkniętych projektach” klienta od razu
widać, które projekty wygraliśmy. Decyzja Artura z 26.11.2026: „wygrana” znaczy
to samo co w Lidze DL i Insights (`hit_ratio_closures.closure_group`), bo
zielony wiersz, który nie zgadza się z liczbą w górnym pasku, rodzi pytanie,
który ekran kłamie.

Kolejność jest ważna i powtarza `closure_group`:

1. powód z grupy „nie liczy się” → ``neutral`` (nawet z zatrudnieniem);
2. ktoś z nas na „Zatrudniony” w bieżącym otwarciu, bez wykluczonego
   placementu (`job_fill.filled_in_opening_sql`) → ``won``;
3. brak powodu albo „Inny” → ``unreviewed`` (w hit ratio liczy się dziś jak
   przegrana, dopóki ktoś go nie uzupełni);
4. reszta → ``lost``, także „Obsadzone przez nas” bez zatrudnienia w NEXUSIE.

Samego powodu zamknięcia nie da się użyć: 26.11.2026 na kopii produkcji
4198 z 4410 zamkniętych rekrutacji nie miało powodu, a 663 miały zatrudnienie
bez powodu „Obsadzone przez nas”.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence
from typing import Literal

from sqlalchemy import String, and_, case, cast, exists, func, null, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.models.candidate import Candidate
from app.models.job import Job, JobStatus
from app.models.recruitment_pipeline import CandidateStage, PipelineStage
from app.services.metric_definitions import (
    HIT_RATIO_LOST_CLOSE_REASONS,
    HIT_RATIO_NEUTRAL_CLOSE_REASONS,
    HIT_RATIO_WON_CLOSE_REASONS,
)
from app.services.placement_exclusions import not_excluded_placement

JobOutcome = Literal["won", "lost", "neutral", "unreviewed"]
JOB_OUTCOMES: tuple[JobOutcome, ...] = ("won", "lost", "neutral", "unreviewed")


def _hired_in_opening(stage) -> list:
    """Warunki wiersza `candidate_stages`: zatrudnienie, które zajmuje wakat."""
    return [
        stage.job_id == Job.id,
        stage.stage == PipelineStage.hired,
        or_(Job.cycle_started_at.is_(None), stage.moved_at >= Job.cycle_started_at),
        not_excluded_placement(stage.candidate_id, stage.job_id),
    ]


def job_outcome_expr():
    """``won / lost / neutral / unreviewed`` dla zamkniętej, NULL dla reszty."""
    stage = aliased(CandidateStage)
    hired = exists().where(and_(*_hired_in_opening(stage)))
    reason = cast(Job.close_reason, String)
    counted = sorted(HIT_RATIO_WON_CLOSE_REASONS | HIT_RATIO_LOST_CLOSE_REASONS)
    return case(
        (Job.status != JobStatus.closed, null()),
        (reason.in_(sorted(HIT_RATIO_NEUTRAL_CLOSE_REASONS)), "neutral"),
        (hired, "won"),
        (or_(Job.close_reason.is_(None), reason.not_in(counted)), "unreviewed"),
        else_="lost",
    )


async def hired_names_by_job(
    db: AsyncSession, job_ids: Sequence[int]
) -> dict[int, list[str]]:
    """Kogo zatrudniliśmy w bieżącym otwarciu — do plakietki „Wygrana”."""
    if not job_ids:
        return {}
    full_name = func.concat_ws(" ", Candidate.name, Candidate.lastname)
    rows = await db.execute(
        select(CandidateStage.job_id, full_name)
        .join(Job, Job.id == CandidateStage.job_id)
        .join(Candidate, Candidate.id == CandidateStage.candidate_id)
        .where(
            CandidateStage.job_id.in_(list(job_ids)),
            *_hired_in_opening(CandidateStage),
        )
        .distinct()
        .order_by(CandidateStage.job_id, full_name)
    )
    names: dict[int, list[str]] = defaultdict(list)
    for job_id, name in rows.all():
        names[int(job_id)].append(name)
    return dict(names)


__all__ = ["JOB_OUTCOMES", "JobOutcome", "hired_names_by_job", "job_outcome_expr"]
