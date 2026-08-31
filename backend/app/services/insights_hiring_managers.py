"""Ranking hiring managerów — jedna implementacja dla dwóch powierzchni.

`/api/reports/hiring-managers` (admin/HoR/finance) i nowy
`/api/insights/clients/hiring-managers` (D7: każdy zalogowany) muszą pokazywać
TE SAME liczby. Guard i kształt odpowiedzi zostają w routerach — tutaj jest
wyłącznie liczenie.

Dwie rzeczy, które ten moduł rozdziela, bo ich pomylenie zmienia znaczenie
kolumny:

1. **Okno filtruje REKRUTACJE (``Job.created_at``), nie kontrakty.** Kontrakty
   liczone są dla rekrutacji z okna, niezależnie od tego, kiedy same powstały —
   umowę z rekrutacji otwartej w lipcu zwykle podpisuje się później. Legacy woła
   ten serwis BEZ okna (``since=None, until=None``), więc jego liczby się nie
   zmieniają.

2. **``contracts_active`` to MIGAWKA NA DZIŚ**, a nie stan z końca okna.
   ``ContractStatus`` nie ma historii, więc „ilu konsultantów pracowało w maju"
   jest z tych danych nieodtwarzalne. Router mówi to wprost w kopercie —
   liczba migawkowa podana pod etykietą okna czyta się jak stan historyczny
   i nie da się jej odróżnić od prawdziwego.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.client import Client
from app.models.contact import Contact
from app.models.contract import Contract, ContractStatus
from app.models.job import Job, JobStatus
from app.services.client_identity import client_display_name_expression

__all__ = ["HiringManagerRow", "compute_hiring_manager_kpis"]


@dataclass(frozen=True)
class HiringManagerRow:
    contact_id: int
    contact_name: str
    position: str | None
    client_id: int
    client_name: str
    jobs_total: int
    jobs_open: int
    contracts_total: int
    contracts_active: int


def _window(column, since: datetime | None, until: datetime | None) -> list:
    """Predykaty półotwartego okna ``[since, until)``; ``None`` = brak granicy."""
    out = []
    if since is not None:
        out.append(column >= since)
    if until is not None:
        out.append(column < until)
    return out


async def compute_hiring_manager_kpis(
    db: AsyncSession,
    *,
    since: datetime | None = None,
    until: datetime | None = None,
) -> list[HiringManagerRow]:
    """Agregaty per ``Job.hiring_manager_contact_id``, malejąco po ``jobs_total``.

    Args:
        since/until: okno po ``Job.created_at``. Oba ``None`` = całość historii
            (zachowanie legacy).
    """
    job_window = _window(Job.created_at, since, until)

    jobs_total_by_contact: dict[int, int] = {}
    jobs_open_by_contact: dict[int, int] = {}
    job_rows = (
        await db.execute(
            select(
                Job.hiring_manager_contact_id,
                Job.status,
                func.count(Job.id),
            )
            .where(Job.hiring_manager_contact_id.is_not(None), *job_window)
            .group_by(Job.hiring_manager_contact_id, Job.status)
        )
    ).all()
    for contact_id, job_status, count in job_rows:
        jobs_total_by_contact[contact_id] = (
            jobs_total_by_contact.get(contact_id, 0) + count
        )
        # `published` = otwarta rekrutacja. draft/closed nie są otwarte.
        if job_status == JobStatus.published:
            jobs_open_by_contact[contact_id] = (
                jobs_open_by_contact.get(contact_id, 0) + count
            )

    contracts_total_by_contact: dict[int, int] = {}
    contracts_active_by_contact: dict[int, int] = {}
    contract_rows = (
        await db.execute(
            select(
                Job.hiring_manager_contact_id,
                Contract.status,
                func.count(Contract.id),
            )
            .join(Job, Job.id == Contract.job_id)
            .where(Job.hiring_manager_contact_id.is_not(None), *job_window)
            .group_by(Job.hiring_manager_contact_id, Contract.status)
        )
    ).all()
    for contact_id, contract_status, count in contract_rows:
        contracts_total_by_contact[contact_id] = (
            contracts_total_by_contact.get(contact_id, 0) + count
        )
        if contract_status == ContractStatus.active:
            contracts_active_by_contact[contact_id] = (
                contracts_active_by_contact.get(contact_id, 0) + count
            )

    contact_ids = list(jobs_total_by_contact.keys())
    if not contact_ids:
        return []

    contacts = (
        await db.execute(
            select(
                Contact.id,
                Contact.name,
                Contact.position,
                Contact.client_id,
                client_display_name_expression().label("client_name"),
            )
            .join(Client, Client.id == Contact.client_id)
            .where(Contact.id.in_(contact_ids))
        )
    ).all()

    rows = [
        HiringManagerRow(
            contact_id=c.id,
            contact_name=c.name,
            position=c.position,
            client_id=c.client_id,
            client_name=c.client_name,
            jobs_total=jobs_total_by_contact.get(c.id, 0),
            jobs_open=jobs_open_by_contact.get(c.id, 0),
            contracts_total=contracts_total_by_contact.get(c.id, 0),
            contracts_active=contracts_active_by_contact.get(c.id, 0),
        )
        for c in contacts
    ]
    rows.sort(key=lambda r: r.jobs_total, reverse=True)
    return rows
