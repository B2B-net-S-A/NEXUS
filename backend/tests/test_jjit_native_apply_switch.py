"""Jednorazowe przełączenie wiszących ogłoszeń JustJoin.IT na formularz portalu."""

from __future__ import annotations

from pathlib import Path

import pytest
import pytest_asyncio
from sqlalchemy import delete, select

from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.models.app_setting import AppSetting
from app.models.job_posting import JobPosting, Portal, PostingStatus
from app.services.job_portals.native_apply_switch import (
    REPAIR_MARKER,
    run_native_apply_switch,
)
from app.services.job_portals.service import ACTION_UPDATE
from tests.test_career_links_api import _seed_job, _seed_user


@pytest_asyncio.fixture(autouse=True)
async def _no_marker():
    async def clear() -> None:
        async with AsyncSessionLocal() as db:
            await db.execute(delete(AppSetting).where(AppSetting.key == REPAIR_MARKER))
            await db.commit()

    await clear()
    yield
    await clear()


async def _posting(**fields) -> int:
    owner_id, _email, _password = await _seed_user("jjit-switch")
    job_id = await _seed_job(owner_id)
    async with AsyncSessionLocal() as db:
        posting = JobPosting(
            job_id=job_id,
            portal=fields.pop("portal", Portal.justjoinit),
            status=fields.pop("status", PostingStatus.published),
            last_error="Portal odrzucił ogłoszenie",
            **fields,
        )
        db.add(posting)
        await db.commit()
        return posting.id


async def _state(posting_id: int) -> tuple:
    async with AsyncSessionLocal() as db:
        row = await db.scalar(select(JobPosting).where(JobPosting.id == posting_id))
        return row.pending_action, row.last_error


async def _run(ids: list[int]):
    async with AsyncSessionLocal() as db:
        summary = await run_native_apply_switch(db, posting_ids=ids)
        await db.commit()
        return summary


async def test_queues_update_once_for_live_jjit_postings(monkeypatch):
    monkeypatch.setattr(settings, "JJIT_APPLY_EMAIL", "praca@example.com")
    monkeypatch.setattr(settings, "JJIT_CONTACT_PHONE", "+48 500 100 200")
    live = await _posting()
    closing = await _posting(pending_action="close")
    other_portal = await _posting(portal=Portal.pracuj_pl)

    assert await _run([live, closing, other_portal]) == {"queued": 1}

    assert await _state(live) == (ACTION_UPDATE, None)
    assert (await _state(closing))[0] == "close"
    assert (await _state(other_portal))[0] is None
    assert await _run([live]) is None


@pytest.mark.parametrize(
    ("apply_email", "phone"),
    [("", "+48 500 100 200"), ("praca@example.com", "  ")],
)
async def test_without_form_or_phone_nothing_changes_and_no_marker(
    monkeypatch, apply_email, phone
):
    """Bez telefonu portal odrzuci ``PUT``, a znacznik zablokowałby kolejne starty."""
    monkeypatch.setattr(settings, "JJIT_APPLY_EMAIL", apply_email)
    monkeypatch.setattr(settings, "JJIT_CONTACT_PHONE", phone)
    live = await _posting()

    assert await _run([live]) is None

    assert (await _state(live))[0] is None
    async with AsyncSessionLocal() as db:
        assert await db.get(AppSetting, REPAIR_MARKER) is None


def test_entrypoint_runs_the_step_under_its_current_marker():
    """Stary znacznik (``queued: 5``) zatrzymałby krok na ``run_unless_marked``."""
    entrypoint = (Path(__file__).resolve().parents[1] / "entrypoint.sh").read_text(
        encoding="utf-8"
    )

    assert f'run_unless_marked "{REPAIR_MARKER}"' in entrypoint
    assert REPAIR_MARKER != "jjit_native_apply_switch_2026_11"
