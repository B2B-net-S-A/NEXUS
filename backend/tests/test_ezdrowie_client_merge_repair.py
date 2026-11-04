"""Dokończenie scalenia klienta (E-Zdrowie 37721 → 115, 25.09.2026).

Dwie rzeczy:

- import Traffita kieruje dane klienta scalonego na klienta kanonicznego
  (bez tego nocny sync przypinał rekrutacje do ukrytego duplikatu);
- jednorazowa korekta przenosi rekrutacje i kontrakty (z zamówieniem) na
  klienta kanonicznego, a drugi bieg nic nie robi.

Baza testowa wspólna i nieczyszczona — własni klienci i własny marker.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy import select, update

from app.core.database import AsyncSessionLocal
from app.models.candidate import Candidate
from app.models.client import Client
from app.models.client_order import ClientOrder, ClientOrderStatus
from app.models.contract import Contract, ContractStatus
from app.models.job import Job, JobStatus
from app.models.recruitment_process import ProcessStatus, RecruitmentProcess
from app.services.ezdrowie_client_merge_repair import (
    ClientMergeTarget,
    run_ezdrowie_client_merge,
    run_ezdrowie_process_client_sync,
)
from app.services.traffit.importer import TraffitImporter, _canonical_client_id
from tests.test_client_deletion import _client, _contract

pytestmark = pytest.mark.asyncio


def test_canonical_client_follows_chain_and_survives_cycle():
    assert _canonical_client_id(1, {}) == 1
    assert _canonical_client_id(1, {1: 2, 2: 3}) == 3
    # Cykl w danych nie wiesza importu — zatrzymuje się na ostatnim nowym.
    assert _canonical_client_id(1, {1: 2, 2: 1}) == 2


async def _merged_pair() -> tuple[int, int, str]:
    ext = f"ez{uuid.uuid4().hex[:8]}"
    canonical = await _client("merge-canonical")
    duplicate = await _client("merge-duplicate", external_id=ext)
    async with AsyncSessionLocal() as db:
        await db.execute(
            update(Client)
            .where(Client.id == duplicate)
            .values(merged_into_client_id=canonical)
        )
        await db.commit()
    return canonical, duplicate, ext


async def test_traffit_client_map_points_merged_record_at_canonical():
    canonical, duplicate, ext = await _merged_pair()
    async with AsyncSessionLocal() as db:
        client_map = await TraffitImporter(
            None,
            db,  # type: ignore[arg-type]
        )._build_client_external_id_map()
    assert client_map[ext] == canonical


async def test_repair_moves_jobs_and_contracts_once():
    canonical, duplicate, ext = await _merged_pair()
    contract_id, order_id = await _contract(
        duplicate,
        status=ContractStatus.active,
        order_status=ClientOrderStatus.active,
    )
    async with AsyncSessionLocal() as db:
        job = Job(
            title=f"MergeJob-{ext}", status=JobStatus.published, client_id=duplicate
        )
        db.add(job)
        await db.commit()
        job_id = job.id
    process_id = await _process(job_id, duplicate)

    target = ClientMergeTarget(
        duplicate_id=duplicate, duplicate_external_id=ext, canonical_id=canonical
    )
    marker = f"test_client_merge_{ext}"
    async with AsyncSessionLocal() as db:
        summary = await run_ezdrowie_client_merge(db, target=target, marker=marker)
        await db.commit()

    assert summary is not None and summary["skipped"] is None
    assert summary["jobs_moved"] == [job_id]
    assert summary["processes_moved"] == 1
    assert summary["contracts_moved"] == [contract_id]
    assert summary["contracts_blocked"] == []
    async with AsyncSessionLocal() as db:
        assert await db.scalar(select(Job.client_id).where(Job.id == job_id)) == (
            canonical
        )
        assert (
            await db.scalar(
                select(Contract.client_id).where(Contract.id == contract_id)
            )
            == canonical
        )
        assert (
            await db.scalar(
                select(RecruitmentProcess.client_id).where(
                    RecruitmentProcess.id == process_id
                )
            )
            == canonical
        )
        if order_id is not None:
            assert (
                await db.scalar(
                    select(ClientOrder.client_id).where(ClientOrder.id == order_id)
                )
                == canonical
            )

    async with AsyncSessionLocal() as db:
        again = await run_ezdrowie_client_merge(db, target=target, marker=marker)
        await db.commit()
    assert again is None


async def test_repair_skips_when_duplicate_is_not_merged():
    canonical = await _client("merge-canonical")
    ext = f"ez{uuid.uuid4().hex[:8]}"
    duplicate = await _client("merge-unmerged", external_id=ext)
    async with AsyncSessionLocal() as db:
        job = Job(
            title=f"MergeJob-{ext}", status=JobStatus.published, client_id=duplicate
        )
        db.add(job)
        await db.commit()
        job_id = job.id
    target = ClientMergeTarget(
        duplicate_id=duplicate, duplicate_external_id=ext, canonical_id=canonical
    )
    async with AsyncSessionLocal() as db:
        summary = await run_ezdrowie_client_merge(
            db, target=target, marker=f"test_client_merge_{ext}"
        )
        await db.commit()
    assert summary is not None
    assert summary["skipped"] == "not_merged_into_canonical"
    async with AsyncSessionLocal() as db:
        assert await db.scalar(select(Job.client_id).where(Job.id == job_id)) == (
            duplicate
        )


async def _process(job_id: int, client_id: int) -> int:
    async with AsyncSessionLocal() as db:
        candidate = Candidate(
            name="Jan",
            lastname=f"Proces-{uuid.uuid4().hex[:6]}",
            email=f"proc-{uuid.uuid4().hex[:8]}@example.com",
        )
        db.add(candidate)
        await db.flush()
        process = RecruitmentProcess(
            candidate_id=candidate.id,
            job_id=job_id,
            client_id=client_id,
            status=ProcessStatus.open,
            opened_at=datetime.now(timezone.utc),
        )
        db.add(process)
        await db.commit()
        return process.id


async def test_process_sync_moves_process_copy_of_job_client():
    """Pierwszy bieg korekty przeniósł rekrutacje bez ich procesów."""

    canonical, duplicate, ext = await _merged_pair()
    async with AsyncSessionLocal() as db:
        job = Job(
            title=f"ProcJob-{ext}", status=JobStatus.published, client_id=canonical
        )
        db.add(job)
        await db.commit()
        job_id = job.id
    process_id = await _process(job_id, duplicate)

    target = ClientMergeTarget(
        duplicate_id=duplicate, duplicate_external_id=ext, canonical_id=canonical
    )
    marker = f"test_process_sync_{ext}"
    async with AsyncSessionLocal() as db:
        summary = await run_ezdrowie_process_client_sync(
            db, target=target, marker=marker
        )
        await db.commit()
    assert summary is not None and summary["processes_moved"] == 1
    async with AsyncSessionLocal() as db:
        assert (
            await db.scalar(
                select(RecruitmentProcess.client_id).where(
                    RecruitmentProcess.id == process_id
                )
            )
            == canonical
        )
        again = await run_ezdrowie_process_client_sync(db, target=target, marker=marker)
    assert again is None
