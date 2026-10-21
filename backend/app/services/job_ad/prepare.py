"""Treść ogłoszeń dla otwartych rekrutacji bez ogłoszenia — w nocy (21.10.2026).

21.10.2026 203 z 205 otwartych rekrutacji nie miało strony kariery. Decyzja
Artura: treść przygotowuje NEXUS w nocy, a rano rekruter albo Delivery Lead
czyta ją w kolejce „Strona kariery do uzupełnienia” i klika „Opublikuj
i następna” — każdą treść widzi człowiek, nic nie wychodzi na stronę samo.

Zapis jak pierwsze „Przygotuj” w oknie: model, a bez niego złożenie z pól
rekrutacji (``source="template"``, okno to mówi); ``INSERT … ON CONFLICT DO
NOTHING`` — ogłoszenia przygotowanego w tym czasie przez człowieka nie
zastępujemy. ``generated_by`` puste = przygotował NEXUS.

Reguły: ``docs/claude/rekrutacja-tworzenie/ogloszenie-jedna-tresc-strona-kariery.md``.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from sqlalchemy import exists, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.job import Job, JobStatus
from app.models.job_ad import JobAd
from app.models.job_public_profile import JobPublicProfile
from app.services import job_public_profile as jpp
from app.services.job_ad import generate, material, render

logger = logging.getLogger(__name__)


async def missing_job_ids(db: AsyncSession, *, limit: int) -> list[int]:
    """Otwarte rekrutacje bez ogłoszenia, od najnowszej."""
    rows = await db.scalars(
        select(Job.id)
        .where(
            Job.status == JobStatus.published,
            ~exists().where(JobAd.job_id == Job.id),
        )
        .order_by(Job.opened_at.desc().nulls_last(), Job.id.desc())
        .limit(limit)
    )
    return list(rows)


async def prepare_one(db: AsyncSession, job_id: int) -> bool:
    """Przygotowuje i zapisuje pierwszą wersję ogłoszenia. ``False`` = ktoś
    zdążył je przygotować, rekrutacja nie jest już otwarta albo model i
    złożenie zawiodły (wtedy spróbujemy następnej nocy)."""
    job = await db.get(Job, job_id)
    if job is None or job.status != JobStatus.published:
        return False
    profile = await db.get(JobPublicProfile, job.id)
    _default, title = await jpp.public_titles(db, job, profile)
    mat = material.build_material(job, title)
    try:
        content, source = await generate.generate_content(
            db,
            mat,
            lang="pl",
            user_id=None,
            log_ref=f"job={job_id} nightly",
            allow_template=True,
        )
    except generate.AdGenerationFailed:
        return False
    now = datetime.now(timezone.utc)
    written = (
        await db.execute(
            pg_insert(JobAd)
            .values(
                job_id=job_id,
                lang="pl",
                content=content,
                tech=render.tech_from_material(mat),
                source=source,
                material_hash=material.material_hash(mat),
                generated_by=None,
                generated_at=now,
                updated_by=None,
                updated_at=now,
            )
            .on_conflict_do_nothing(index_elements=[JobAd.job_id])
        )
    ).rowcount
    return bool(written)
