"""Audyt 22.09 r2 (INTG-03): rekrutacja bez zmian nie jest przepisywana.

Do 22.09 `_UPSERT_JOB` przepisywał każdą rekrutację z delty (~4,3 tys.),
stemplował `updated_at` i zapisywał tyle samo intencji przeindeksowania —
18 tys. wywołań Voyage w jeden dzień. WHERE w upsercie odrzuca zapis bez
realnej zmiany, a intencja powstaje tylko dla nowej rekrutacji albo zmiany
tytułu/statusu.
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


@pytest.mark.asyncio
async def test_second_import_of_the_same_recruitment_writes_nothing():
    ext = f"u{uuid.uuid4().hex[:12]}"
    raw = {
        "id": ext,
        "name": "Python Developer",
        "status": "active",
        "client": {"id": 7},
        "created_at": "2026-09-01 10:00:00",
    }
    async with AsyncSessionLocal() as db:
        client = Client(name=f"INTG-03 {ext}")
        db.add(client)
        await db.commit()
        job_id = None
        try:
            first = await _import(db, [raw], client.id)
            assert first.inserted == 1
            assert first.index_intents == 1
            job_id = (
                await db.execute(
                    text("SELECT id FROM jobs WHERE external_id = :e"), {"e": ext}
                )
            ).scalar_one()
            stamp = (
                await db.execute(
                    text("SELECT updated_at FROM jobs WHERE id = :i"), {"i": job_id}
                )
            ).scalar_one()

            second = await _import(db, [raw], client.id)
            assert second.unchanged == 1
            assert second.updated == 0
            assert second.index_intents == 0
            assert second.as_dict()["unchanged"] == 1
            again = (
                await db.execute(
                    text("SELECT updated_at FROM jobs WHERE id = :i"), {"i": job_id}
                )
            ).scalar_one()
            assert again == stamp

            # Zmiana tytułu = zapis + intencja przeindeksowania.
            third = await _import(db, [{**raw, "name": "Java Developer"}], client.id)
            assert third.updated == 1
            assert third.index_intents == 1

            # Zmiana samego terminu = zapis, ale bez intencji (nie wchodzi do
            # wektora ani do jego payloadu).
            fourth = await _import(
                db,
                [
                    {
                        **raw,
                        "name": "Java Developer",
                        "closing_date": "2026-12-31 12:00:00",
                    }
                ],
                client.id,
            )
            assert fourth.updated == 1
            assert fourth.index_intents == 0
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
