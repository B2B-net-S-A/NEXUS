"""Filtr listy kandydatów po rekrutacjach — blok „Rekrutacje” (12.10.2026).

Lista `GET /api/candidates` zadaje o rekrutacje trzy pytania:

* **zakres** — osoba jest (albo jej nie ma) w którejkolwiek ze wskazanych
  rekrutacji; zakres to rekrutacje wybrane z listy (`recruitment_id`) LUB
  wszystkie rekrutacje wskazanych klientów (`recruitment_client_id`), kierunek
  niesie `recruitment_match`;
* **obecność** — osoba była (`ever`) albo nie była (`never`) w jakiejkolwiek
  rekrutacji; to odpowiednik „Nieprzypisany” z Traffita bez wskazywania
  rekrutacji;
* **proces w toku** (`not_in_process`) — osoba nie ma dziś otwartego procesu.

„Jest w rekrutacji” znaczy: ma dowolny wiersz `candidate_stages` tej rekrutacji,
także końcowy. „Proces w toku” to reguła kolumny „W procesie” listy: najnowszy
wiersz pary (osoba, rekrutacja) na rekrutacji niezamkniętej stoi na etapie
innym niż końcowy. Zbiór etapów końcowych kolumna trzyma we froncie
(`candidate-row-format.ts`, `TERMINAL_STAGES`); zgodność obu przypina
`test_candidates_recruitment_filter.py`.
"""

from typing import Any, Optional, Sequence

from sqlalchemy import and_, or_, select

from app.models.candidate import Candidate
from app.models.job import Job, JobStatus
from app.models.recruitment_pipeline import (
    STAGE_CATEGORY,
    CandidateStage,
    PipelineStage,
    StageCategory,
)

TERMINAL_STAGES: tuple[PipelineStage, ...] = tuple(
    stage
    for stage, category in STAGE_CATEGORY.items()
    if category is StageCategory.terminal
)


def job_in_scope(
    job_col: Any,
    recruitment_ids: Optional[Sequence[int]],
    client_ids: Optional[Sequence[int]],
) -> Optional[Any]:
    """Warunek „ta rekrutacja należy do zakresu”; ``None`` = zakres pusty."""
    parts = []
    if recruitment_ids:
        parts.append(job_col.in_(list(recruitment_ids)))
    if client_ids:
        # Cały klient to warunek po `jobs.client_id`, nie lista identyfikatorów:
        # największy klient ma ponad dwa tysiące rekrutacji i dochodzą nowe.
        client_jobs = (
            select(Job.id).where(Job.client_id.in_(list(client_ids))).correlate(None)
        )
        parts.append(job_col.in_(client_jobs))
    if not parts:
        return None
    return parts[0] if len(parts) == 1 else or_(*parts)


def scope_clause(
    recruitment_ids: Optional[Sequence[int]],
    client_ids: Optional[Sequence[int]],
    match: str,
) -> Optional[Any]:
    """Osoba w zakresie (``assigned``) albo poza nim (``not_assigned``)."""
    in_scope = job_in_scope(CandidateStage.job_id, recruitment_ids, client_ids)
    if in_scope is None:
        return None
    in_recruitment = (
        select(1)
        .where(and_(CandidateStage.candidate_id == Candidate.id, in_scope))
        .exists()
    )
    return ~in_recruitment if match == "not_assigned" else in_recruitment


def _in_any_recruitment() -> Any:
    return select(1).where(CandidateStage.candidate_id == Candidate.id).exists()


def _in_process() -> Any:
    latest_per_pair = (
        select(CandidateStage.candidate_id, CandidateStage.stage)
        .join(Job, Job.id == CandidateStage.job_id)
        .where(Job.status != JobStatus.closed)
        .distinct(CandidateStage.candidate_id, CandidateStage.job_id)
        .order_by(
            CandidateStage.candidate_id,
            CandidateStage.job_id,
            CandidateStage.moved_at.desc(),
            CandidateStage.id.desc(),
        )
        .subquery()
    )
    return (
        select(1)
        .select_from(latest_per_pair)
        .where(
            latest_per_pair.c.candidate_id == Candidate.id,
            latest_per_pair.c.stage.notin_(TERMINAL_STAGES),
        )
        .exists()
    )


def presence_clause(presence: Optional[str]) -> Optional[Any]:
    """Warunek `recruitment_presence`; ``None`` = filtr nieustawiony."""
    if presence == "ever":
        return _in_any_recruitment()
    if presence == "never":
        return ~_in_any_recruitment()
    if presence == "not_in_process":
        return ~_in_process()
    return None
