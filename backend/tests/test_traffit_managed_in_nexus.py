"""0325: import Traffita honoruje „Rekrutacja prowadzona w NEXUSIE".

Nocny import dopisywał `candidate_stages` dla każdej rekrutacji z Traffita, a
tablica czyta NAJNOWSZY wiersz per (kandydat, oferta) — ruch zrobiony w NEXUSIE
przegrywał nazajutrz z etapem z importu. Flaga `jobs.managed_in_nexus` wyłącza
dla danej oferty: (1) import ruchów etapów (faza `pipelines`, licznik
`skipped_managed`), (2) nadpisywanie `title`/`status`/`closed_at` w `_UPSERT_JOB`.

Testy integracyjne wymagają Postgresa ze schematem jak CI. Baza testowa jest
wspólna i nieczyszczona — asercje wyłącznie na własnych wierszach (uuid).
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any, AsyncIterator, Optional

import pytest
import pytest_asyncio
from sqlalchemy import text

from app.core.database import AsyncSessionLocal
from app.models.candidate import Candidate
from app.models.client import Client
from app.models.job import Job, JobStatus
from app.models.pipeline_template import (
    PipelineStageDef,
    PipelineTemplate,
    StageCategoryEnum,
)

# Relacja `CortexSkillFact` → `Skill` (patrz test_traffit_pipelines_withdrawn_fallback).
from app.models.skill import Skill  # noqa: F401
from app.services.traffit.importer import _UPSERT_JOB, PhaseProgress, TraffitImporter
from app.services.traffit.mappers import traffit_recruitment_to_job
from app.tasks.traffit_sync import _summarize

MOVED_AT = "2026-07-01 10:00:00"


class _FakeTraffit:
    """Stub klienta: `import_pipelines` używa `total_count` + `get_pages`,
    a `build_user_id_map` — `get_paginated`."""

    def __init__(self, records: list[dict[str, Any]]) -> None:
        self._records = records

    async def total_count(self, path: str) -> int:
        return len(self._records)

    async def get_pages(
        self,
        path: str,
        *,
        page_size: int = 100,
        skip_on_5xx: bool = False,
        filter_: Optional[dict] = None,
        start_page: int = 1,
    ) -> AsyncIterator[tuple[int, list[dict[str, Any]]]]:
        if start_page <= 1 and self._records:
            yield 1, list(self._records)

    async def get_paginated(
        self,
        path: str,
        *,
        page_size: int = 100,
        skip_on_5xx: bool = False,
        filter_: Optional[dict] = None,
    ) -> AsyncIterator[dict[str, Any]]:
        for record in self._records:
            yield record


async def _seed_move(*, managed: bool) -> dict[str, Any]:
    unique = uuid.uuid4().hex[:8]
    emp_ext = f"mn-emp-{unique}"
    rec_ext = f"mn-rec-{unique}"
    state_ext = f"mn-state-{unique}"
    history_ext = f"mn-hist-{unique}"

    async with AsyncSessionLocal() as db:
        template = PipelineTemplate(
            name=f"Managed in NEXUS tpl {unique}",
            external_source="traffit",
            external_id=f"mn-tpl-{unique}",
        )
        client = Client(name=f"Managed in NEXUS client {unique}")
        db.add_all([template, client])
        await db.flush()

        stage_def = PipelineStageDef(
            template_id=template.id,
            name=f"Screening {unique}",
            order=1,
            category=StageCategoryEnum.internal,
            legacy_enum_value="screening",
            external_source="traffit",
            external_id=state_ext,
        )
        job = Job(
            title=f"Managed in NEXUS job {unique}",
            client_id=client.id,
            external_source="traffit",
            external_id=rec_ext,
            managed_in_nexus=managed,
        )
        candidate = Candidate(
            name="Przełączony",
            lastname=f"Kandydat-{unique}",
            external_source="traffit",
            external_id=emp_ext,
        )
        db.add_all([stage_def, job, candidate])
        await db.commit()
        return {
            "job_id": job.id,
            "history_ext": history_ext,
            "record": {
                "id": history_ext,
                "employee": {"id": emp_ext},
                "recruitment": {"id": rec_ext},
                "workflow_state": {"id": state_ext},
                "date": MOVED_AT,
            },
        }


async def _count_stage_rows(history_ext: str) -> int:
    async with AsyncSessionLocal() as db:
        return (
            await db.execute(
                text(
                    "SELECT COUNT(*) FROM candidate_stages "
                    "WHERE external_source='traffit' AND external_id = :ext"
                ),
                {"ext": history_ext},
            )
        ).scalar_one()


@pytest_asyncio.fixture
async def managed_move():
    return await _seed_move(managed=True)


@pytest_asyncio.fixture
async def unmanaged_move():
    return await _seed_move(managed=False)


@pytest.mark.asyncio
async def test_pipelines_skip_moves_of_a_job_managed_in_nexus(managed_move):
    async with AsyncSessionLocal() as db:
        progress = await TraffitImporter(
            _FakeTraffit([managed_move["record"]]), db
        ).import_pipelines()

    assert progress.errors == 0, progress.error_samples
    assert progress.inserted == 0
    assert progress.skipped_managed == 1
    # `skipped` to rekordy spoza NEXUSA — pominięcie świadome ma własny licznik.
    assert progress.skipped == 0
    assert progress.as_dict()["skipped_managed"] == 1
    assert await _count_stage_rows(managed_move["history_ext"]) == 0


@pytest.mark.asyncio
async def test_dry_run_counts_managed_skip_the_same_way(managed_move):
    async with AsyncSessionLocal() as db:
        importer = TraffitImporter(
            _FakeTraffit([managed_move["record"]]), db, dry_run=True
        )
        progress = await importer.import_pipelines()

    assert progress.skipped_managed == 1
    assert progress.inserted == 0


@pytest.mark.asyncio
async def test_pipelines_still_import_moves_of_an_unswitched_job(unmanaged_move):
    async with AsyncSessionLocal() as db:
        progress = await TraffitImporter(
            _FakeTraffit([unmanaged_move["record"]]), db
        ).import_pipelines()

    assert progress.errors == 0, progress.error_samples
    assert progress.inserted == 1
    assert progress.skipped_managed == 0
    assert await _count_stage_rows(unmanaged_move["history_ext"]) == 1


def test_skipped_managed_survives_both_stat_whitelists():
    assert PhaseProgress(phase="pipelines").as_dict()["skipped_managed"] == 0
    summary = _summarize({"processed": 5, "skipped_managed": 3})
    assert summary["skipped_managed"] == 3


@pytest.mark.asyncio
@pytest.mark.parametrize("managed", [True, False])
async def test_upsert_job_keeps_nexus_title_status_and_closed_at_when_managed(
    managed,
):
    async with AsyncSessionLocal() as db:
        try:
            external_id = uuid.uuid4().hex
            client = Client(name=f"Managed upsert {external_id}")
            db.add(client)
            await db.flush()
            requirements = {
                "version": 1,
                "reviewed": True,
                "all_of": [],
                "missing_evidence_policy": "review",
            }
            job = Job(
                title="Python Developer (NEXUS)",
                client_id=client.id,
                status=JobStatus.published,
                external_source="traffit",
                external_id=external_id,
                matching_requirements=requirements,
                requirements_reviewed=True,
                managed_in_nexus=managed,
            )
            db.add(job)
            await db.flush()

            payload = traffit_recruitment_to_job(
                {
                    "id": external_id,
                    "name": "Python Developer",
                    "client": {"id": 7},
                    "is_closed": True,
                    "closing_date": "2026-09-01 12:00:00",
                },
                {"7": client.id},
                {},
            )
            payload["custom_fields"] = json.dumps(payload["custom_fields"])
            await db.execute(_UPSERT_JOB, payload)
            await db.refresh(job)

            if managed:
                assert job.title == "Python Developer (NEXUS)"
                assert job.status == JobStatus.published
                assert job.closed_at is None
                assert job.matching_requirements == requirements
                assert job.requirements_reviewed is True
            else:
                assert job.title == "Python Developer"
                assert job.status == JobStatus.closed
                assert job.closed_at == datetime(2026, 9, 1, 12, 0, tzinfo=timezone.utc)
                assert job.matching_requirements is None
                assert job.requirements_reviewed is False
            # Flaga należy do NEXUSA — sync jej nie dotyka.
            assert job.managed_in_nexus is managed
        finally:
            await db.rollback()
