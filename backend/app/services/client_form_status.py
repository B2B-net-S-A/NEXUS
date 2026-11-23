"""Stan formularza CV klienta pary — dla warunków ruchu, Tablicy i bramki QC (PR 3).

U klienta z ``cv_client_document = client_form`` (na start Centrum e-Zdrowia)
do klienta idzie formularz z Plików rekrutacji, nie CV firmowe. QC CV
firmowego tych par nie dotyczy (nie ma czego sprawdzać, decyzja 26.10.2026).
Od 23.11.2026 (prośba DL CEZ, decyzja Artura) na „QC CV” rekruter przesuwa
dopiero z formularzem i tabelą punktową, gdy rekrutacja ma ich wzory
(`missing_before_qc`); puste pola dalej tylko przypominają.
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
from app.services.client_form_schema import CLIENT_FORM, KIND_FORM, KIND_SCORE

# Klucze braków przed „QC CV” — te same w 409, liście wymagań i śladzie ruchu.
MISSING_FORM = "client_form"
MISSING_SCORE = "client_score"


@dataclass(frozen=True)
class PairFormState:
    template: Optional[str]  # nazwa pliku wzoru; None = brak wzoru w Plikach
    missing: Optional[int]  # None = jeszcze nie wypełniony
    # Tabela punktowa (Excel, 0525) — tylko gdy rekrutacja ma jej wzór.
    score_template: Optional[str] = None
    score_missing: Optional[int] = None
    # 0756: plik wypełniony poza NEXUSEM, wgrany z dysku — gotowy (0 braków).
    uploaded: bool = False
    score_uploaded: bool = False


def missing_before_qc(state: Optional[PairFormState]) -> list[str]:
    """Dokumenty klienta, których brakuje przed „QC CV” (23.11.2026).

    Liczy się wypełnienie (wiersz pary), nie puste pola — pola, które słusznie
    zostają puste (numer certyfikatu, którego osoba nie ma), nie mogą trzymać
    karty. Brak wzoru w Plikach nie blokuje rekrutera: wzór dodaje Delivery
    Lead, a lista wymagań mówi o nim osobno.
    """

    if state is None:
        return []
    missing: list[str] = []
    if state.template is not None and state.missing is None:
        missing.append(MISSING_FORM)
    if state.score_template is not None and state.score_missing is None:
        missing.append(MISSING_SCORE)
    return missing


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
    templates = {
        kind: filename
        for kind, filename in (
            await db.execute(
                select(JobFile.client_form_kind, JobFile.filename).where(
                    JobFile.job_id == job_id,
                    JobFile.client_form.is_(True),
                    JobFile.client_form_kind.in_((KIND_FORM, KIND_SCORE)),
                )
            )
        ).all()
    }
    missing: dict[tuple[int, str], int] = {}
    uploaded: set[tuple[int, str]] = set()
    if ids:
        rows = await db.execute(
            select(
                CandidateClientForm.candidate_id,
                CandidateClientForm.kind,
                CandidateClientForm.missing_count,
                CandidateClientForm.uploaded_file_key.is_not(None),
            ).where(
                CandidateClientForm.job_id == job_id,
                CandidateClientForm.kind.in_((KIND_FORM, KIND_SCORE)),
                CandidateClientForm.candidate_id.in_(ids),
            )
        )
        for cid, kind, count, has_upload in rows.all():
            # Wgrany plik idzie do QC i do klienta zamiast pól z NEXUSA, więc
            # jego puste pola nie są brakami (0756).
            missing[(cid, kind)] = 0 if has_upload else count
            if has_upload:
                uploaded.add((cid, kind))
    return {
        candidate_id: PairFormState(
            template=templates.get(KIND_FORM),
            missing=missing.get((candidate_id, KIND_FORM)),
            score_template=templates.get(KIND_SCORE),
            score_missing=missing.get((candidate_id, KIND_SCORE)),
            uploaded=(candidate_id, KIND_FORM) in uploaded,
            score_uploaded=(candidate_id, KIND_SCORE) in uploaded,
        )
        for candidate_id in ids
    }
