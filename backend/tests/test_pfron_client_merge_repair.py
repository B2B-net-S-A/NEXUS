"""Scalenie duplikatu PFRON 58469 → 122 (19.11.2026).

Logika to ta sama korekta co przy Cardifie, więc tu tylko kształt PFRON-u:
duplikat bez kontraktów, z zamkniętą rekrutacją z procesem i kontaktem, ze
wskazanym zakresem portfela. Po korekcie rekrutacja stoi na kliencie
docelowym (stąd jedna pozycja w Radzie), a duplikat jest scalony.
"""

from __future__ import annotations

import pytest
from sqlalchemy import select

from app.core.database import AsyncSessionLocal
from app.models.app_setting import AppSetting
from app.models.client import Client
from app.models.contact import Contact
from app.models.job import Job
from app.models.recruitment_process import RecruitmentProcess
from scripts.repairs.cardif_client_merge_repair import (
    CardifMergeTarget,
    run_cardif_client_merge,
    summarize_for_log,
)
from scripts.repairs.run_repair_pfron_client_merge import MARKER, TARGET
from tests.test_cardif_client_merge_repair import _closed_job, _pair
from tests.test_ezdrowie_client_merge_repair import _process

pytestmark = pytest.mark.asyncio


def test_target_is_pinned_to_the_production_ids():
    assert (TARGET.source_id, TARGET.target_id) == (58469, 122)
    assert TARGET.name_token == "pfron"
    assert TARGET.agreement is None
    assert MARKER == "0738_pfron_client_merge"


async def test_merge_moves_closed_job_with_process_and_contact_then_marks_duplicate():
    canonical, source, token = await _pair()
    job_id = await _closed_job(source)
    process_id = await _process(job_id, source)
    async with AsyncSessionLocal() as db:
        contact = Contact(client_id=source, name="Kontakt Testowy")
        db.add(contact)
        await db.commit()
        contact_id = contact.id

    target = CardifMergeTarget(source_id=source, target_id=canonical, name_token=token)
    marker = f"test_pfron_merge_{token}"
    async with AsyncSessionLocal() as db:
        summary = await run_cardif_client_merge(db, target=target, marker=marker)
        await db.commit()

    assert summary is not None and summary["skipped"] is None
    assert summary["jobs_moved"] == [job_id]
    assert summary["processes_moved"] == 1
    assert summary["merged"] is True and summary["unexpected_references"] == {}
    assert "merged True" in summarize_for_log(summary)

    async with AsyncSessionLocal() as db:
        assert await db.scalar(select(Job.client_id).where(Job.id == job_id)) == (
            canonical
        )
        assert (
            await db.scalar(
                select(RecruitmentProcess.client_id).where(
                    RecruitmentProcess.id == process_id
                )
            )
            == canonical
        )
        assert (await db.get(Contact, contact_id)).client_id == canonical
        duplicate = await db.get(Client, source)
        assert duplicate.merged_into_client_id == canonical
        assert duplicate.archived_at is not None
        assert await db.get(AppSetting, marker) is not None

    # Drugi przebieg niczego nie zmienia.
    async with AsyncSessionLocal() as db:
        assert await run_cardif_client_merge(db, target=target, marker=marker) is None


async def test_name_mismatch_skips_everything():
    """Id zaszyte w korekcie muszą znaczyć na bazie to samo co na produkcji."""

    canonical, source, token = await _pair()
    target = CardifMergeTarget(
        source_id=source, target_id=canonical, name_token="nie-ta-nazwa"
    )
    async with AsyncSessionLocal() as db:
        summary = await run_cardif_client_merge(
            db, target=target, marker=f"test_pfron_identity_{token}"
        )
        await db.commit()
    # Token nazwy nie pasuje → nic nie ruszone (kontrola tożsamości id ↔ nazwa).
    assert summary is not None and summary["skipped"] == "identity_mismatch"
    async with AsyncSessionLocal() as db:
        assert (await db.get(Client, source)).merged_into_client_id is None
