"""Stan formularza CV klienta pary — dla warunków ruchu, Tablicy i bramki QC (PR 3).

U klienta z ``cv_client_document = client_form`` (na start Centrum e-Zdrowia)
do klienta idzie formularz z Plików rekrutacji, nie CV firmowe. Decyzje Artura
26.10.2026: przed „QC CV” tylko przypomnienie o brakach, bez blokady, a QC CV
firmowego tych par nie dotyczy (nie ma czego sprawdzać).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.candidate_client_form import CandidateClientForm
from app.models.client import Client
from app.models.job import Job
from app.models.job_file import JobFile
from app.services.client_form_schema import CLIENT_FORM


@dataclass(frozen=True)
class PairFormState:
    template: Optional[str]  # nazwa pliku wzoru; None = brak wzoru w Plikach
    missing: Optional[int]  # None = jeszcze nie wypełniony


async def job_takes_client_form(db: AsyncSession, job_id: int) -> bool:
    value = await db.scalar(
        select(Client.cv_client_document)
        .join(Job, Job.client_id == Client.id)
        .where(Job.id == job_id)
    )
    return value == CLIENT_FORM


async def client_takes_client_form(db: AsyncSession, client_id: Optional[int]) -> bool:
    if client_id is None:
        return False
    value = await db.scalar(
        select(Client.cv_client_document).where(Client.id == client_id)
    )
    return value == CLIENT_FORM


async def job_states(
    db: AsyncSession, job_id: int, candidate_ids: Iterable[int]
) -> Optional[dict[int, PairFormState]]:
    """Stan formularza każdej osoby rekrutacji; ``None`` = klient bierze CV firmowe."""
    if not await job_takes_client_form(db, job_id):
        return None
    ids = list(candidate_ids)
    template = await db.scalar(
        select(JobFile.filename).where(
            JobFile.job_id == job_id, JobFile.client_form.is_(True)
        )
    )
    missing: dict[int, int] = {}
    if ids:
        rows = await db.execute(
            select(
                CandidateClientForm.candidate_id, CandidateClientForm.missing_count
            ).where(
                CandidateClientForm.job_id == job_id,
                CandidateClientForm.candidate_id.in_(ids),
            )
        )
        missing = {candidate_id: count for candidate_id, count in rows.all()}
    return {
        candidate_id: PairFormState(
            template=template, missing=missing.get(candidate_id)
        )
        for candidate_id in ids
    }
