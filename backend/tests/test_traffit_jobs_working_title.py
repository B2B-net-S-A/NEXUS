"""Runda 9 (R9-N15-7): import Traffita przelicza tytuł dla rekrutera.

`working_title` rekrutacji bez roli w Championie składa się z nazwy od klienta
(`jobs.title`). Import nadpisywał `title`, ale tytułu dla rekrutera nie
przeliczał, więc ekrany wewnętrzne pokazywały starą nazwę. Tytuł wpisany ręcznie
(`working_title_auto = false`) zostaje nietknięty.
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import text

from app.core.database import AsyncSessionLocal
from app.models.client import Client
from app.services.traffit.importer import TraffitImporter


class _FakeTraffit:
    def __init__(self, items):
        self.items = items

    async def total_count(self, path):
        return len(self.items)

    async def get_paginated(self, path, **kw):
        for item in self.items:
            yield item


async def _import(db, items, client_id):
    imp = TraffitImporter(_FakeTraffit(items), db, dry_run=False, batch_size=100)
    imp._build_client_external_id_map = AsyncMock(return_value={"7": client_id})
    return await imp.import_jobs(since=None)


async def _titles(db, ext):
    return (
        await db.execute(
            text(
                "SELECT id, working_title, working_title_auto FROM jobs "
                "WHERE external_id = :e"
            ),
            {"e": ext},
        )
    ).one()


@pytest.mark.asyncio
async def test_import_recomputes_working_title_after_title_change():
    ext = f"wt{uuid.uuid4().hex[:12]}"
    raw = {
        "id": ext,
        "name": "Python Developer",
        "status": "active",
        "client": {"id": 7},
        "created_at": "2026-09-01 10:00:00",
    }
    async with AsyncSessionLocal() as db:
        client = Client(name=f"R9-N15-7 {ext}")
        db.add(client)
        await db.commit()
        job_id = None
        try:
            first = await _import(db, [raw], client.id)
            assert first.inserted == 1
            job_id, working, auto = await _titles(db, ext)
            assert auto is True
            assert working == "Python Developer"

            second = await _import(db, [{**raw, "name": "Java Developer"}], client.id)
            assert second.updated == 1
            assert second.working_titles == 1
            _, working, _ = await _titles(db, ext)
            assert working == "Java Developer"

            # Tytuł wpisany ręcznie wyłącza automat — import go nie rusza.
            await db.execute(
                text(
                    "UPDATE jobs SET working_title = 'Mój tytuł', "
                    "working_title_auto = false WHERE id = :i"
                ),
                {"i": job_id},
            )
            await db.commit()
            third = await _import(db, [{**raw, "name": "Go Developer"}], client.id)
            assert third.updated == 1
            assert third.working_titles == 0
            _, working, auto = await _titles(db, ext)
            assert (working, auto) == ("Mój tytuł", False)
        finally:
            if job_id is not None:
                await db.execute(
                    text("DELETE FROM candidate_match_outbox WHERE job_id = :j"),
                    {"j": job_id},
                )
                await db.execute(
                    text(
                        "DELETE FROM match_index_outbox "
                        "WHERE entity_type = 'job' AND entity_id = :i"
                    ),
                    {"i": job_id},
                )
                await db.execute(text("DELETE FROM jobs WHERE id = :i"), {"i": job_id})
            await db.execute(
                text("DELETE FROM clients WHERE id = :i"), {"i": client.id}
            )
            await db.commit()
