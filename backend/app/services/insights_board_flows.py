"""Insights → Firma: ruch konsultantów i popyt (22.10.2026).

Prośba Artura przy przebudowie Insights: „318 konsultantów” nie mówi, czy
firma rośnie. Widok Firma dostaje więc obok kwot:

* **ruch w okresie** — ilu konsultantów zaczęło (start kontraktu), ilu
  odeszło (zejście, z tego rezygnacje) i netto; tymi samymi funkcjami co API
  integracyjne i tabele rok do roku (`integration_insights.contract_flows`,
  `departure_day`), więc liczby zgadzają się z „Rokiem do roku”;
* **kończące się w 30 dni bez kontynuacji** — kontrakty, których zamówienie
  okresowe kończy się w 30 dniach i nic go nie przedłuża; ta sama reguła co
  pigułka „Kończące się 30d” w module Kontrakty (`ending_without_successor`);
* **popyt** — opublikowane rekrutacje dziś i nowe rekrutacje w oknie.

Okres w toku porównujemy z tym samym odcinkiem poprzedniego okresu
(`previous_matching_window`), jak kafle Zespołu. Kwot tu nie ma — bramka
trasy i tak jest bramką kwot (`BoardReader`), bo ruch kontraktów to dane
Delivery, nie rekrutacji.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.analytics.periods import Period
from app.models.contract import Contract, ContractStatus
from app.models.job import Job, JobStatus
from app.services.insights_team_signals import previous_matching_window
from app.services.integration_insights import contract_flows, load_contracts
from app.services.order_continuation import (
    ENDING_WITHOUT_CONTINUATION_DAYS,
    ending_without_successor,
)

# Kontrakt „żywy” — tylko taki może się kończyć bez kontynuacji.
_LIVE_STATUSES = (ContractStatus.active, ContractStatus.ending)


def _flows_payload(contracts: list, first: date, last: date) -> dict[str, int]:
    flows = contract_flows(contracts, first, last)
    return {
        "starts": flows.starts,
        "ends": flows.ends,
        "resignations": flows.resignations,
        "net": flows.starts - flows.ends,
    }


async def _ending_without_continuation(db: AsyncSession, *, today: date) -> int:
    contracts = (
        (
            await db.execute(
                select(Contract)
                .where(Contract.status.in_(_LIVE_STATUSES))
                .options(selectinload(Contract.client_orders))
            )
        )
        .scalars()
        .all()
    )
    return sum(
        1
        for contract in contracts
        if ending_without_successor(
            contract.client_orders, today=today, days=ENDING_WITHOUT_CONTINUATION_DAYS
        )
        is not None
    )


async def _jobs(db: AsyncSession, start: datetime, end: datetime) -> dict[str, int]:
    open_jobs, open_clients = (
        await db.execute(
            select(func.count(Job.id), func.count(func.distinct(Job.client_id))).where(
                Job.status == JobStatus.published
            )
        )
    ).one()
    new_jobs = await db.scalar(
        select(func.count(Job.id)).where(
            Job.created_at >= start,
            Job.created_at < end,
            Job.status != JobStatus.draft,
        )
    )
    return {
        "open": int(open_jobs or 0),
        "open_clients": int(open_clients or 0),
        "new": int(new_jobs or 0),
    }


async def compute_board_flows(
    db: AsyncSession, period: Period, *, today: date, now: datetime
) -> dict[str, Any]:
    # Okno w toku kończy się dziś — zejścia z datą w przyszłości (wypowiedzenie
    # na koniec miesiąca) nie są jeszcze zejściem.
    first = period.start.date()
    last = min((period.end - timedelta(days=1)).date(), today)
    prev_start, prev_end = previous_matching_window(period, now)
    prev_first = prev_start.date()
    prev_last = (prev_end - timedelta(days=1)).date()
    contracts = await load_contracts(db, first=min(first, prev_first), last=last)
    new_jobs_end = min(period.end, now)
    jobs = await _jobs(db, period.start, new_jobs_end)
    previous_jobs = await _jobs(db, prev_start, prev_end)
    return {
        "period": period.as_payload(),
        "window": {"from": first.isoformat(), "to": last.isoformat()},
        "previous_window": {
            "from": prev_first.isoformat(),
            "to": prev_last.isoformat(),
        },
        "consultants": _flows_payload(contracts, first, last),
        "previous_consultants": _flows_payload(contracts, prev_first, prev_last),
        "ending_without_continuation": {
            "days": ENDING_WITHOUT_CONTINUATION_DAYS,
            "contracts": await _ending_without_continuation(db, today=today),
        },
        "jobs": {
            "open": jobs["open"],
            "open_clients": jobs["open_clients"],
            "new": jobs["new"],
            "previous_new": previous_jobs["new"],
        },
    }
