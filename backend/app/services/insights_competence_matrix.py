"""Macierz kompetencji w /insights → Rekrutacja: stan na dziś.

Opublikowane rekrutacje całej organizacji pogrupowane po kategorii
kompetencji (``jobs.competence_category_id``) × pięć etapów pulpitu procesów.
Liczniki etapów pochodzą z ``recruitment_operations.dashboard_stage_counts_by_job``
— tej samej funkcji mapowania i tego samego źródła (``analytics_current_pipeline``),
co wiersz procesu na pulpicie rekrutacji. Dwie kopie mapowania „etap → licznik"
rozjechałyby się przy pierwszej zmianie jednej z nich, a oba ekrany pokazują
te same liczby obok siebie.

Zakres ofert to lustro pulpitu w presecie organizacyjnym: ``status =
published`` i klient widoczny (bez technicznego kubła importu, UAT B73).
Bez okna — to migawka „na teraz", więc ``as_of`` mówi, kiedy ją zrobiono.
"""

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.competence_category import CompetenceCategory
from app.models.job import Job, JobStatus
from app.services.client_identity import job_client_listed_clause
from app.services.recruitment_operations import dashboard_stage_counts_by_job
from app.services.request_work_state import FINISHED as FINISHED_WORK_STATE

STAGES: tuple[tuple[str, str], ...] = (
    ("new", "Nowy"),
    ("screening", "Screening"),
    ("cv_sent", "Wysłany do klienta"),
    ("client_interview", "Rozmowa u klienta"),
    ("acceptance", "Umowa"),
)
NO_CATEGORY_NAME = "Bez kategorii"


def _zero_counts() -> dict[str, int]:
    return {key: 0 for key, _ in STAGES}


async def compute_competence_matrix(db: AsyncSession) -> dict:
    job_filters = (
        Job.status == JobStatus.published,
        # „Zakończony” w NEXUSIE nie jest otwarty (runda 7, R7-N9-5).
        Job.work_state != FINISHED_WORK_STATE,
        job_client_listed_clause(Job.client_id),
    )
    job_rows = (
        await db.execute(
            select(
                Job.id,
                Job.competence_category_id,
                CompetenceCategory.name_pl,
            )
            .outerjoin(
                CompetenceCategory,
                CompetenceCategory.id == Job.competence_category_id,
            )
            .where(*job_filters)
        )
    ).all()
    counts_by_job = await dashboard_stage_counts_by_job(
        db, select(Job.id).where(*job_filters)
    )

    categories: dict[int | None, dict] = {}
    for job_id, category_id, category_name in job_rows:
        entry = categories.setdefault(
            category_id,
            {
                "category_id": category_id,
                "name": category_name or NO_CATEGORY_NAME,
                "open_jobs": 0,
                "stage_counts": _zero_counts(),
            },
        )
        entry["open_jobs"] += 1
        job_counts = counts_by_job.get(int(job_id))
        if job_counts is not None:
            for key, _ in STAGES:
                entry["stage_counts"][key] += getattr(job_counts, key)

    # Najwięcej rekrutacji u góry; „Bez kategorii" zawsze na końcu — to luka
    # w danych, nie kategoria konkurująca o miejsce w rankingu.
    ordered = sorted(
        categories.values(),
        key=lambda c: (c["category_id"] is None, -c["open_jobs"], c["name"].lower()),
    )

    totals = {"open_jobs": 0, "stage_counts": _zero_counts()}
    for entry in ordered:
        totals["open_jobs"] += entry["open_jobs"]
        for key, _ in STAGES:
            totals["stage_counts"][key] += entry["stage_counts"][key]

    return {
        "as_of": datetime.now(timezone.utc).isoformat(),
        "stages": [{"key": key, "label": label} for key, label in STAGES],
        "categories": ordered,
        "totals": totals,
    }
