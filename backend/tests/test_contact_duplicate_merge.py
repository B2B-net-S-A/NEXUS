"""Scalanie zdublowanych kontaktów z Traffita (25.09.2026).

Zostaje kontakt o niższym id; drugi rekord Traffita dostaje alias, a nocny
import go pomija — inaczej upsert po external_id odtwarzałby duplikat co noc.

Baza testowa wspólna i nieczyszczona — własne wiersze (uuid) i własny marker.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select

from app.core.database import AsyncSessionLocal
from app.models.client import Client
from app.models.contact import Contact
from app.models.job import Job, JobStatus
from app.services.contact_duplicate_merge import (
    MergePair,
    load_traffit_contact_aliases,
    run_contact_duplicate_merge,
)
from app.services.traffit.importer import TraffitImporter


async def _seed(*, duplicate_name: str | None = None) -> dict:
    tag = uuid.uuid4().hex[:8]
    async with AsyncSessionLocal() as db:
        client = Client(name=f"MergeClient-{tag}")
        db.add(client)
        await db.flush()
        survivor = Contact(
            client_id=client.id,
            name=f"Anna Nowak{tag}",
            external_source="traffit",
            external_id=f"s{tag}",
        )
        db.add(survivor)
        await db.flush()
        duplicate = Contact(
            client_id=client.id,
            name=duplicate_name or f"nowak{tag} ANNA",
            email=f"anna{tag}@bank.pl",
            position="Kierownik",
            external_source="traffit",
            external_id=f"d{tag}",
        )
        db.add(duplicate)
        await db.flush()
        job = Job(
            title=f"MergeJob-{tag}",
            status=JobStatus.published,
            client_id=client.id,
            hiring_manager_contact_id=duplicate.id,
        )
        db.add(job)
        await db.commit()
        return {
            "tag": tag,
            "pair": MergePair(
                client_id=client.id,
                survivor_id=survivor.id,
                survivor_external_id=f"s{tag}",
                duplicate_id=duplicate.id,
                duplicate_external_id=f"d{tag}",
            ),
            "job_id": job.id,
        }


@pytest.mark.asyncio
async def test_merge_keeps_the_lower_id_fills_blanks_and_repoints():
    world = await _seed()
    pair = world["pair"]
    marker = f"test_contact_merge_{world['tag']}"
    async with AsyncSessionLocal() as db:
        summary = await run_contact_duplicate_merge(db, targets=[pair], marker=marker)
        await db.commit()
    assert summary is not None and summary["merged"] == 1

    async with AsyncSessionLocal() as db:
        survivor = await db.get(Contact, pair.survivor_id)
        assert await db.get(Contact, pair.duplicate_id) is None
        assert survivor.email == f"anna{world['tag']}@bank.pl"
        assert survivor.position == "Kierownik"
        job = await db.get(Job, world["job_id"])
        assert job.hiring_manager_contact_id == pair.survivor_id
        aliases = await load_traffit_contact_aliases(db)
        assert aliases[pair.duplicate_external_id] == pair.survivor_id

        # Jednorazowo: drugi bieg z tym samym markerem nic nie robi.
        assert (
            await run_contact_duplicate_merge(db, targets=[pair], marker=marker)
        ) is None


@pytest.mark.asyncio
async def test_different_person_is_not_merged():
    world = await _seed(duplicate_name="Jan Kowalski")
    pair = world["pair"]
    async with AsyncSessionLocal() as db:
        summary = await run_contact_duplicate_merge(
            db, targets=[pair], marker=f"test_contact_merge_{world['tag']}"
        )
        await db.commit()
    assert summary["merged"] == 0
    assert summary["results"][0]["skipped"] == "different_person"
    async with AsyncSessionLocal() as db:
        assert await db.get(Contact, pair.duplicate_id) is not None


class _PersonsTraffit:
    def __init__(self, persons: list[dict]):
        self.persons = persons

    async def total_count(self, path):
        return len(self.persons)

    async def get_paginated(self, path, *, page_size=100, filter_=None, **kw):
        for person in self.persons:
            yield person


@pytest.mark.asyncio
async def test_nightly_import_does_not_recreate_a_merged_duplicate():
    world = await _seed()
    pair = world["pair"]
    async with AsyncSessionLocal() as db:
        await run_contact_duplicate_merge(
            db, targets=[pair], marker=f"test_contact_merge_{world['tag']}"
        )
        await db.commit()

    traffit = _PersonsTraffit(
        [{"id": pair.duplicate_external_id, "name": "Anna", "lastname": "Nowak"}]
    )
    async with AsyncSessionLocal() as db:
        progress = await TraffitImporter(
            traffit, db, dry_run=False, batch_size=10
        ).import_contacts()
        assert progress.skipped == 1
        recreated = await db.scalar(
            select(Contact.id).where(
                Contact.external_source == "traffit",
                Contact.external_id == pair.duplicate_external_id,
            )
        )
        assert recreated is None
