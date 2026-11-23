"""Klienci Partnera z ostatnich 12 miesięcy przy zwolnieniu z zakazu konkurencji.

Przegląd skrzynki działu umów z 23.11.2026: listę klientów do porozumienia
składano ręcznie. Reguła: ``services/b2b_documents/non_compete_clients.py``,
zdanie w ``notes["non_compete_client_name"]`` prefillu dokumentu.
"""

from __future__ import annotations

import uuid
from datetime import date

import pytest

from app.core.database import AsyncSessionLocal
from app.models.candidate import Candidate
from app.models.client import Client
from app.models.contract import Contract, ContractStatus
from app.services.b2b_documents.non_compete_clients import (
    RecentClient,
    months_back,
    recent_clients,
    recent_clients_note,
)

UNTIL = date(2026, 11, 23)


def test_months_back_keeps_the_day_or_clamps_to_month_end():
    assert months_back(UNTIL, 12) == date(2025, 11, 23)
    assert months_back(date(2026, 3, 31), 1) == date(2026, 2, 28)
    assert months_back(date(2026, 1, 15), 12) == date(2025, 1, 15)


def test_note_lists_each_client_with_its_last_day():
    note = recent_clients_note(
        [
            RecentClient("Klient A S.A.", None, ongoing=True),
            RecentClient("Klient B sp. z o.o.", date(2026, 6, 30), ongoing=False),
            RecentClient("Klient C", None, ongoing=False),
        ],
        until=UNTIL,
    )
    assert note is not None
    assert note.startswith("Klienci tej osoby z kontraktów od 23.11.2025: ")
    assert (
        "Klient A S.A. (trwa), Klient B sp. z o.o. (do 30.06.2026), Klient C (zakończony)"
        in note
    )


def test_no_clients_no_note():
    assert recent_clients_note([], until=UNTIL) is None


async def _seed() -> tuple[int, dict[str, str]]:
    suffix = uuid.uuid4().hex[:8]
    async with AsyncSessionLocal() as db:
        names = {
            key: f"NC {key} {suffix}"
            for key in ("live", "ended_recent", "ended_old", "void", "draft")
        }
        clients = {key: Client(name=name) for key, name in names.items()}
        person = Candidate(name="Jan", lastname=f"Zakaz{suffix}")
        db.add_all([*clients.values(), person])
        await db.flush()
        rows = [
            ("live", ContractStatus.active, date(2025, 3, 1), None),
            ("ended_recent", ContractStatus.ended, date(2024, 1, 1), date(2026, 2, 28)),
            ("ended_old", ContractStatus.ended, date(2023, 1, 1), date(2025, 6, 30)),
            ("void", ContractStatus.void, date(2026, 1, 1), None),
            ("draft", ContractStatus.draft, date(2026, 12, 1), None),
        ]
        for key, status, start, end in rows:
            db.add(
                Contract(
                    candidate_id=person.id,
                    client_id=clients[key].id,
                    start_date=start,
                    end_date=end,
                    status=status,
                )
            )
        await db.commit()
        return person.id, names


@pytest.mark.asyncio
async def test_recent_clients_take_contracts_running_in_the_last_12_months():
    person_id, names = await _seed()
    async with AsyncSessionLocal() as db:
        found = await recent_clients(db, person_id, until=UNTIL)
    assert [(c.name, c.last_day, c.ongoing) for c in found] == [
        (names["live"], None, True),
        (names["ended_recent"], date(2026, 2, 28), False),
    ]
