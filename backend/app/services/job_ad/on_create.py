"""Ogłoszenie gotowe zaraz po „Utwórz” (wariant 1 „Porządki”, 23.11.2026).

Pomiar na kopii produkcji z 23.11.2026: treść ogłoszenia powstawała dopiero
w pętli nocnej albo po ręcznym „Przygotuj”, a publikacja na portalu miała
medianę 23 h po utworzeniu rekrutacji (789217: JustJoin.IT +3 dni, Pracuj.pl
+6 dni). Decyzja Artura: treść pisze się przy tworzeniu, a DL ląduje od razu
w kroku „Ogłoszenie” (``/jobs/{id}?ogloszenie=nowa``).

- :func:`prepare_after_create` — efekt po commicie tworzenia (zadanie w tle
  żądania, własna sesja). Tylko wynik modelu, PL albo EN z „Języka pracy”;
  awaria modelu = nic się nie zapisuje i zostaje dzisiejsza droga (noc,
  „Przygotuj” w oknie). Nigdy nie wywraca tworzenia.
- :func:`recent_channels` — kanały, które zaznacza krok „Ogłoszenie”: te,
  których klient używał w większości ostatnich rekrutacji z ogłoszeniem.

Reguły: ``docs/claude/rekrutacja-tworzenie/ogloszenie-przy-utworzeniu.md``.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import AsyncSessionLocal
from app.models.activity import Activity
from app.models.job import Job
from app.models.job_ad_publication import JobAdPublication
from app.models.job_posting import JobPosting, Portal
from app.models.job_public_profile import JobPublicProfile
from app.services.job_ad import pracuj_mail, prepare

logger = logging.getLogger(__name__)

# Ile ostatnich rekrutacji klienta z jakimkolwiek ogłoszeniem decyduje.
RECENT_JOBS = 5
# Ile ostatnich rekrutacji klienta w ogóle przeglądamy, żeby je znaleźć.
_SCAN_JOBS = 40
CHANNELS = ("kariera", "jjit", "pracuj")


async def prepare_after_create(job_id: int, user_id: Optional[int]) -> None:
    """Treść ogłoszenia nowej rekrutacji — po commicie, we własnej sesji.

    ``INSERT … ON CONFLICT DO NOTHING`` (``prepare.prepare_one``): ogłoszenie
    przygotowane w tym czasie przez człowieka zostaje.
    """
    try:
        async with AsyncSessionLocal() as db:
            written = await prepare.prepare_one(
                db, job_id, on_create=True, user_id=user_id
            )
            await db.commit()
        logger.info("job ad on create: job=%s written=%s", job_id, written)
    except Exception:  # noqa: BLE001 — dodatek po utworzeniu nigdy nie wywraca żądania
        logger.exception("job ad on create: job=%s failed", job_id)


@dataclass(frozen=True)
class RecentChannels:
    channels: list[str]
    # Na ilu rekrutacjach klienta oparto zaznaczenie (0 = klient bez historii).
    jobs: int
    # Kategoria JustJoin.IT z ostatniej publikacji w tej samej kategorii kompetencji.
    jjit_category: Optional[str] = None

    def as_dict(self) -> dict:
        return {
            "channels": self.channels,
            "jobs": self.jobs,
            "jjit_category": self.jjit_category,
        }


async def _used_channels(db: AsyncSession, job_ids: list[int]) -> dict[int, set[str]]:
    used: dict[int, set[str]] = {job_id: set() for job_id in job_ids}
    if not job_ids:
        return used
    for job_id in await db.scalars(
        select(JobPublicProfile.job_id).where(
            JobPublicProfile.job_id.in_(job_ids),
            JobPublicProfile.approved_at.is_not(None),
        )
    ):
        used[job_id].add("kariera")
    for job_id, portal in (
        await db.execute(
            select(JobAdPublication.job_id, JobAdPublication.portal).where(
                JobAdPublication.job_id.in_(job_ids)
            )
        )
    ).all():
        used[job_id].add(portal)
    for job_id in await db.scalars(
        select(Activity.entity_id).where(
            Activity.entity_type == "job",
            Activity.entity_id.in_(job_ids),
            Activity.action == pracuj_mail.ACTION,
        )
    ):
        used[job_id].add("pracuj")
    return used


async def _jjit_category(db: AsyncSession, job: Job) -> Optional[str]:
    if job.competence_category_id is None:
        return None
    return await db.scalar(
        select(JobPosting.options["category"].astext)
        .join(Job, Job.id == JobPosting.job_id)
        .where(
            Job.competence_category_id == job.competence_category_id,
            Job.id != job.id,
            JobPosting.portal == Portal.justjoinit,
            JobPosting.options["category"].astext.is_not(None),
        )
        .order_by(JobPosting.id.desc())
        .limit(1)
    )


async def recent_channels(db: AsyncSession, job: Job) -> RecentChannels:
    """Kanały z większości ostatnich :data:`RECENT_JOBS` rekrutacji klienta,
    które miały jakiekolwiek ogłoszenie. Klient bez historii = wszystkie."""
    others = list(
        await db.scalars(
            select(Job.id)
            .where(Job.client_id == job.client_id, Job.id != job.id)
            .order_by(Job.created_at.desc(), Job.id.desc())
            .limit(_SCAN_JOBS)
        )
    )
    used = await _used_channels(db, others)
    recent = [used[job_id] for job_id in others if used[job_id]][:RECENT_JOBS]
    category = await _jjit_category(db, job)
    if not recent:
        return RecentChannels(channels=list(CHANNELS), jobs=0, jjit_category=category)
    channels = [c for c in CHANNELS if 2 * sum(c in u for u in recent) >= len(recent)]
    return RecentChannels(channels=channels, jobs=len(recent), jjit_category=category)
