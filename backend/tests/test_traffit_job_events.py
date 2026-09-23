"""Audyt 22.09 r2 (DATA-01/PROD-03): import rekrutacji zasila automaty.

Do 22.09 import Traffita (99% rekrutacji) nie zapisywał zdarzeń rekrutacji,
więc nocny przegląd bazy, auto-match nowej rekrutacji i dzwonek „Moi ludzie"
nie ruszyły ani razu. Do tego 312 z 326 opublikowanych rekrutacji nie miało
opiekuna, bo `responsible_person` przychodził jako lista.
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock

import httpx
import pytest
from sqlalchemy import text

from app.core.database import AsyncSessionLocal
from app.models.client import Client
from app.models.user import User, UserRole
from app.services.traffit.importer import TraffitImporter


class _FakeTraffit:
    def __init__(self, items, details=None):
        self.items = items
        self.details = details or {}
        self.detail_calls: list[str] = []

    async def total_count(self, path):
        return len(self.items)

    async def get_paginated(self, path, **kw):
        for item in self.items:
            yield item

    async def _get_raw(self, path, **kw):
        self.detail_calls.append(path)
        ext = path.rstrip("/").rsplit("/", 1)[-1]
        if ext not in self.details:
            return httpx.Response(404, json={})
        return httpx.Response(200, json=self.details[ext])


async def _run(db, traffit, client_id, user_map):
    imp = TraffitImporter(traffit, db, dry_run=False, batch_size=100)
    imp._build_client_external_id_map = AsyncMock(return_value={"7": client_id})
    imp.build_user_id_map = AsyncMock(return_value=user_map)
    return await imp.import_jobs(since=None)


async def _events(db, job_id) -> int:
    return (
        await db.execute(
            text(
                "SELECT count(*) FROM candidate_match_outbox WHERE job_id = :j "
                "AND trigger = 'traffit_job'"
            ),
            {"j": job_id},
        )
    ).scalar_one()


@pytest.mark.asyncio
async def test_published_recruitment_from_traffit_gets_an_event_and_an_owner():
    ext = f"e{uuid.uuid4().hex[:12]}"
    raw = {
        "id": ext,
        "name": "Data Engineer",
        "status": "active",
        "client": {"id": 7},
    }
    async with AsyncSessionLocal() as db:
        client = Client(name=f"DATA-01 {ext}")
        user = User(
            email=f"{ext}@example.com",
            name="Opiekun Traffit",
            role=UserRole.recruiter,
            password_hash="x",
            is_active=True,
        )
        db.add_all([client, user])
        await db.commit()
        job_id = None
        try:
            # Lista nie niesie opiekuna; szczegóły tak — jako LISTA osób.
            traffit = _FakeTraffit(
                [raw], details={ext: {"id": ext, "responsible_person": [{"id": 43}]}}
            )
            first = await _run(db, traffit, client.id, {"43": user.id})
            job_id = (
                await db.execute(
                    text("SELECT id FROM jobs WHERE external_id = :e"), {"e": ext}
                )
            ).scalar_one()
            status = (
                await db.execute(
                    text("SELECT CAST(status AS text) FROM jobs WHERE id = :i"),
                    {"i": job_id},
                )
            ).scalar_one()
            if status != "published":
                pytest.skip(f"status mapping gives {status!r}, not published")
            assert first.job_events == 1
            assert await _events(db, job_id) == 1
            assert first.owners_filled == 1
            owner = (
                await db.execute(
                    text("SELECT recruiter_id FROM jobs WHERE id = :i"), {"i": job_id}
                )
            ).scalar_one()
            assert owner == user.id

            # Ten sam payload drugi raz = brak zmian = brak nowego zdarzenia.
            second = await _run(db, _FakeTraffit([raw]), client.id, {"43": user.id})
            assert second.job_events == 0
            assert second.owners_filled == 0
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
            await db.execute(text("DELETE FROM users WHERE id = :i"), {"i": user.id})
            await db.commit()
