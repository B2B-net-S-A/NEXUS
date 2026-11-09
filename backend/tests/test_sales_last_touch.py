"""Ostatni dotyk szansy (``services/sales/touch.py``) i automat archiwizacji w cieniu.

Baza testowa jest wspólna dla przebiegu, więc testy patrzą tylko na własne szanse
(po id), nigdy na liczby globalne.
"""

from __future__ import annotations

import logging
import re
import uuid
from datetime import date, datetime, timedelta, timezone
from typing import Any, Optional

import pytest
from sqlalchemy import func, select

from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.models.sales import (
    SalesActivity,
    SalesCompany,
    SalesOpportunity,
    SalesPipeline,
    SalesPipelineStage,
)
from app.services.sales.atlas_import import PROTECTED
from app.services.sales.decision_map import IT_FACTORIES_PIPELINE_KEY
from app.services.sales.summary import build_summary
from app.services.sales.touch import last_touch_at
from app.tasks import sales_archive_shadow as shadow
from tests.test_sales_companies_api import _headers, _user

NOW = datetime(2026, 11, 9, 12, 0, tzinfo=timezone.utc)
TODAY = date(2026, 11, 9)
CREATED = NOW - timedelta(days=400)
#: Godzina zapisu joba Atlasa na kopii produkcji: 06:20:00 UTC z ułamkiem sekundy.
JOB_TRACE = datetime(2026, 9, 5, 6, 20, 0, 39967, tzinfo=timezone.utc)
TENDERS_KEY = "atlas-tenders"


async def _pipeline(key: str = "sales") -> tuple[int, int]:
    """(id lejka, id otwartego etapu); lejki z importu zakłada, gdy ich brak."""

    async with AsyncSessionLocal() as db:
        pipeline = await db.scalar(
            select(SalesPipeline).where(SalesPipeline.key == key)
        )
        if pipeline is None:
            pipeline = SalesPipeline(key=key, name=f"Lejek {key}")
            db.add(pipeline)
            await db.flush()
            db.add(
                SalesPipelineStage(
                    pipeline_id=pipeline.id,
                    key=f"{key}-first",
                    name="Pierwszy kontakt",
                    position=1,
                    probability=10,
                    outcome="open",
                )
            )
            await db.commit()
        stage_id = await db.scalar(
            select(SalesPipelineStage.id)
            .where(
                SalesPipelineStage.pipeline_id == pipeline.id,
                SalesPipelineStage.outcome == "open",
            )
            .order_by(SalesPipelineStage.position)
            .limit(1)
        )
        return pipeline.id, int(stage_id)


async def _company() -> int:
    async with AsyncSessionLocal() as db:
        name = f"Dotyk Firma {uuid.uuid4().hex[:10]}"
        company = SalesCompany(name=name, normalized_name=name.lower())
        db.add(company)
        await db.commit()
        return company.id


async def _opportunity(
    company_id: Optional[int] = None,
    *,
    pipeline_key: str = "sales",
    created_at: datetime = CREATED,
    **fields: Any,
) -> tuple[int, int]:
    """(id szansy, id firmy)."""

    company_id = company_id or await _company()
    pipeline_id, stage_id = await _pipeline(pipeline_key)
    async with AsyncSessionLocal() as db:
        opportunity = SalesOpportunity(
            company_id=company_id,
            pipeline_id=pipeline_id,
            stage_id=stage_id,
            title="Szansa testowa",
            created_at=created_at,
            **fields,
        )
        db.add(opportunity)
        await db.commit()
        return opportunity.id, company_id


async def _activity(
    kind: str,
    *,
    opportunity_id: Optional[int] = None,
    company_id: Optional[int] = None,
    created_at: datetime = CREATED,
    **fields: Any,
) -> None:
    async with AsyncSessionLocal() as db:
        db.add(
            SalesActivity(
                kind=kind,
                opportunity_id=opportunity_id,
                company_id=company_id,
                created_at=created_at,
                **fields,
            )
        )
        await db.commit()


async def _touch(opportunity_id: int, now: datetime = NOW) -> datetime:
    async with AsyncSessionLocal() as db:
        return await db.scalar(
            select(last_touch_at(now)).where(SalesOpportunity.id == opportunity_id)
        )


async def _classified() -> dict[int, str]:
    async with AsyncSessionLocal() as db:
        return await shadow.classify_open_opportunities(db, now=NOW, today=TODAY)


# ── Definicja dotyku ─────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_atlas_job_trace_is_not_a_touch() -> None:
    opportunity_id, _ = await _opportunity(
        last_activity_at=JOB_TRACE, external_ref=f"deals:{uuid.uuid4().hex}"
    )

    assert await _touch(opportunity_id) == CREATED


@pytest.mark.asyncio
async def test_imported_last_activity_outside_the_job_minute_is_a_touch() -> None:
    human = datetime(2026, 9, 5, 10, 7, 12, tzinfo=timezone.utc)
    opportunity_id, _ = await _opportunity(
        last_activity_at=human, external_ref=f"deals:{uuid.uuid4().hex}"
    )

    assert await _touch(opportunity_id) == human


@pytest.mark.asyncio
async def test_same_hour_at_a_later_second_is_a_human_touch() -> None:
    """Na kopii produkcji są pojedyncze zapisy o 06:20:11, to nie job."""

    human = datetime(2026, 9, 5, 6, 20, 11, tzinfo=timezone.utc)
    opportunity_id, _ = await _opportunity(
        last_activity_at=human, external_ref=f"deals:{uuid.uuid4().hex}"
    )

    assert await _touch(opportunity_id) == human


@pytest.mark.asyncio
async def test_job_minute_on_a_row_born_in_nexus_is_a_touch() -> None:
    opportunity_id, _ = await _opportunity(last_activity_at=JOB_TRACE)

    assert await _touch(opportunity_id) == JOB_TRACE


@pytest.mark.asyncio
async def test_last_activity_in_the_future_is_not_a_touch() -> None:
    opportunity_id, _ = await _opportunity(last_activity_at=NOW + timedelta(days=3))

    assert await _touch(opportunity_id) == CREATED


@pytest.mark.asyncio
async def test_future_meeting_is_not_a_touch_but_a_held_one_is() -> None:
    opportunity_id, _ = await _opportunity()
    await _activity(
        "meeting",
        opportunity_id=opportunity_id,
        occurred_at=NOW + timedelta(days=2),
    )
    assert await _touch(opportunity_id) == CREATED

    held = NOW - timedelta(days=5)
    await _activity("meeting", opportunity_id=opportunity_id, occurred_at=held)
    assert await _touch(opportunity_id) == held


@pytest.mark.asyncio
async def test_cancelled_meeting_is_not_a_touch() -> None:
    opportunity_id, _ = await _opportunity()
    await _activity(
        "meeting",
        opportunity_id=opportunity_id,
        occurred_at=NOW - timedelta(days=5),
        subject="Anulowano: rozmowa o współpracy",
    )

    assert await _touch(opportunity_id) == CREATED


@pytest.mark.asyncio
async def test_open_task_is_not_a_touch_but_a_done_one_counts_at_done_at() -> None:
    opportunity_id, _ = await _opportunity()
    await _activity(
        "task",
        opportunity_id=opportunity_id,
        due_at=NOW - timedelta(days=1),
        occurred_at=NOW - timedelta(days=1),
        created_at=NOW - timedelta(days=2),
    )
    assert await _touch(opportunity_id) == CREATED

    done = NOW - timedelta(days=3)
    await _activity("task", opportunity_id=opportunity_id, due_at=done, done_at=done)
    assert await _touch(opportunity_id) == done


@pytest.mark.asyncio
async def test_planned_call_is_not_a_touch_but_a_logged_one_is() -> None:
    opportunity_id, _ = await _opportunity()
    await _activity(
        "call",
        opportunity_id=opportunity_id,
        due_at=NOW - timedelta(days=1),
        created_at=NOW - timedelta(days=2),
    )
    assert await _touch(opportunity_id) == CREATED

    logged = NOW - timedelta(days=4)
    await _activity("call", opportunity_id=opportunity_id, occurred_at=logged)
    assert await _touch(opportunity_id) == logged


@pytest.mark.asyncio
async def test_open_call_with_a_deadline_and_occurred_at_is_not_a_touch() -> None:
    """Import zapisuje planowanemu telefonowi ``occurred_at = created_at`` i termin."""

    opportunity_id, _ = await _opportunity()
    await _activity(
        "call",
        opportunity_id=opportunity_id,
        due_at=NOW + timedelta(days=21),
        occurred_at=NOW - timedelta(days=10),
        created_at=NOW - timedelta(days=10),
    )

    assert await _touch(opportunity_id) == CREATED


@pytest.mark.asyncio
async def test_imported_call_without_a_deadline_is_a_touch() -> None:
    """Telefon bez terminu to wpis historii, także bez ``done_at``."""

    opportunity_id, _ = await _opportunity()
    logged = NOW - timedelta(days=10)
    await _activity(
        "call", opportunity_id=opportunity_id, occurred_at=logged, created_at=logged
    )

    assert await _touch(opportunity_id) == logged


@pytest.mark.asyncio
async def test_finished_call_with_a_deadline_is_a_touch() -> None:
    opportunity_id, _ = await _opportunity()
    done = NOW - timedelta(days=10)
    await _activity(
        "call",
        opportunity_id=opportunity_id,
        due_at=done,
        occurred_at=done,
        done_at=done,
    )

    assert await _touch(opportunity_id) == done


@pytest.mark.asyncio
async def test_email_both_directions_and_note_are_touches() -> None:
    for kind, fields, when in (
        ("email", {"direction": "in"}, NOW - timedelta(days=6)),
        ("email", {"direction": "out"}, NOW - timedelta(days=7)),
        ("note", {}, NOW - timedelta(days=8)),
    ):
        opportunity_id, _ = await _opportunity()
        await _activity(kind, opportunity_id=opportunity_id, occurred_at=when, **fields)
        assert await _touch(opportunity_id) == when


@pytest.mark.asyncio
async def test_company_activity_is_a_touch_of_its_opportunity() -> None:
    opportunity_id, company_id = await _opportunity()
    when = NOW - timedelta(days=9)
    await _activity("note", company_id=company_id, occurred_at=when)

    assert await _touch(opportunity_id) == when


@pytest.mark.asyncio
async def test_updated_at_is_not_a_touch() -> None:
    opportunity_id, _ = await _opportunity(updated_at=NOW - timedelta(days=1))

    assert await _touch(opportunity_id) == CREATED


@pytest.mark.asyncio
async def test_created_at_is_the_lower_bound_of_the_touch() -> None:
    created = NOW - timedelta(days=10)
    opportunity_id, _ = await _opportunity(created_at=created)
    await _activity(
        "note", opportunity_id=opportunity_id, occurred_at=created - timedelta(days=30)
    )

    assert await _touch(opportunity_id) == created


# ── API i Podsumowanie ───────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_list_and_detail_return_the_same_last_touch(app_client) -> None:
    rep = await _user("sales_view")
    now = datetime.now(timezone.utc)
    when = now - timedelta(days=11)
    opportunity_id, company_id = await _opportunity(
        last_activity_at=JOB_TRACE, external_ref=f"deals:{uuid.uuid4().hex}"
    )
    await _activity("note", company_id=company_id, occurred_at=when)

    listed = await app_client.get(
        "/api/sales/opportunities",
        params={"company_id": company_id},
        headers=_headers(rep),
    )
    assert listed.status_code == 200, listed.text
    detail = await app_client.get(
        f"/api/sales/opportunities/{opportunity_id}", headers=_headers(rep)
    )
    assert detail.status_code == 200, detail.text

    item = listed.json()["items"][0]
    assert datetime.fromisoformat(item["last_touch_at"]) == when
    assert detail.json()["last_touch_at"] == item["last_touch_at"]


@pytest.mark.asyncio
async def test_summary_stale_count_uses_the_same_definition() -> None:
    owner = await _user()
    now = datetime.now(timezone.utc)
    await _opportunity(
        owner_user_id=owner.id,
        created_at=now - timedelta(days=200),
        updated_at=now,
        last_activity_at=now.replace(hour=6, minute=20, second=0, microsecond=31644)
        - timedelta(days=2),
        external_ref=f"deals:{uuid.uuid4().hex}",
    )
    touched_id, _ = await _opportunity(
        owner_user_id=owner.id, created_at=now - timedelta(days=200)
    )
    await _activity(
        "note", opportunity_id=touched_id, occurred_at=now - timedelta(days=1)
    )

    async with AsyncSessionLocal() as db:
        pipeline = await db.scalar(
            select(SalesPipeline).where(SalesPipeline.key == "sales")
        )
        summary = await build_summary(
            db, pipeline, period="all", today=now.date(), now=now
        )

    row = next(o for o in summary.by_owner if o.owner_id == owner.id)
    assert (row.open, row.stale) == (2, 1)


# ── Import ───────────────────────────────────────────────────────────────


def test_second_import_keeps_decisions_made_in_nexus() -> None:
    assert {"keep_open_until", "archived_reason"} <= PROTECTED["sales_opportunities"]
    assert "kind" in PROTECTED["sales_activities"]


# ── Tryb cienia ──────────────────────────────────────────────────────────

OLD = NOW - timedelta(days=91)


@pytest.mark.asyncio
async def test_shadow_marks_an_old_opportunity_without_a_step() -> None:
    opportunity_id, _ = await _opportunity(created_at=OLD)

    assert (await _classified())[opportunity_id] == "candidate"


@pytest.mark.asyncio
@pytest.mark.parametrize("key", [IT_FACTORIES_PIPELINE_KEY, TENDERS_KEY])
async def test_shadow_skips_excluded_pipelines(key: str) -> None:
    opportunity_id, _ = await _opportunity(pipeline_key=key, created_at=OLD)

    assert (await _classified())[opportunity_id] == "excluded_pipeline"


@pytest.mark.asyncio
async def test_shadow_skips_top22_and_keep_open_in_the_future() -> None:
    top22, _ = await _opportunity(created_at=OLD, tags=["top22", "CLOUD"])
    kept, _ = await _opportunity(
        created_at=OLD, keep_open_until=TODAY + timedelta(days=30)
    )
    lapsed, _ = await _opportunity(
        created_at=OLD, keep_open_until=TODAY - timedelta(days=1)
    )

    classified = await _classified()
    assert classified[top22] == "top22"
    assert classified[kept] == "keep_open"
    assert classified[lapsed] == "candidate"


@pytest.mark.asyncio
async def test_shadow_treats_future_task_and_company_meeting_as_a_step() -> None:
    with_task, _ = await _opportunity(created_at=OLD)
    await _activity(
        "task",
        opportunity_id=with_task,
        due_at=NOW + timedelta(days=2),
        created_at=OLD,
    )
    with_call, _ = await _opportunity(created_at=OLD)
    await _activity(
        "call",
        opportunity_id=with_call,
        due_at=NOW + timedelta(days=2),
        created_at=OLD,
    )
    with_meeting, company_id = await _opportunity(created_at=OLD)
    await _activity(
        "meeting", company_id=company_id, occurred_at=NOW + timedelta(days=2)
    )
    overdue_task, _ = await _opportunity(created_at=OLD)
    await _activity(
        "task",
        opportunity_id=overdue_task,
        due_at=NOW - timedelta(days=2),
        created_at=OLD,
    )

    classified = await _classified()
    assert classified[with_task] == "has_step"
    assert classified[with_call] == "has_step"
    assert classified[with_meeting] == "has_step"
    assert classified[overdue_task] == "candidate"


@pytest.mark.asyncio
async def test_shadow_keeps_recently_touched_and_ignores_closed_ones() -> None:
    fresh, _ = await _opportunity(created_at=OLD)
    await _activity("note", opportunity_id=fresh, occurred_at=NOW - timedelta(days=89))
    won, _ = await _opportunity(created_at=OLD, status="won")
    archived, _ = await _opportunity(
        created_at=OLD, archived_at=NOW - timedelta(days=1)
    )

    classified = await _classified()
    assert classified[fresh] == "fresh"
    assert won not in classified
    assert archived not in classified


@pytest.mark.asyncio
async def test_shadow_run_writes_nothing_and_logs_only_numbers(caplog) -> None:
    opportunity_id, _ = await _opportunity(created_at=OLD)
    async with AsyncSessionLocal() as db:
        before = await db.scalar(
            select(func.count())
            .select_from(SalesOpportunity)
            .where(SalesOpportunity.archived_at.is_not(None))
        )
        row_before = await db.scalar(
            select(SalesOpportunity.updated_at).where(
                SalesOpportunity.id == opportunity_id
            )
        )

    with caplog.at_level(logging.INFO, logger=shadow.logger.name):
        await shadow.run_once()

    async with AsyncSessionLocal() as db:
        opportunity = await db.get(SalesOpportunity, opportunity_id)
        after = await db.scalar(
            select(func.count())
            .select_from(SalesOpportunity)
            .where(SalesOpportunity.archived_at.is_not(None))
        )
    assert (opportunity.archived_at, opportunity.archived_reason) == (None, None)
    assert opportunity.updated_at == row_before
    assert after == before

    lines = [
        record.getMessage()
        for record in caplog.records
        if record.name == shadow.logger.name
    ]
    assert len(lines) == 1
    assert re.fullmatch(r"sales_archive_shadow( [a-z0-9_]+=\d+)+", lines[0])


@pytest.mark.asyncio
async def test_shadow_session_cannot_write(monkeypatch) -> None:
    """Tryb cienia odmawia zapisu na poziomie transakcji, nie tylko z dobrej woli."""

    async def write_during_count(db, *, now, today):
        await db.execute(
            SalesOpportunity.__table__.update().values(archived_reason="shadow")
        )
        return {}

    monkeypatch.setattr(shadow, "classify_open_opportunities", write_during_count)
    with pytest.raises(Exception, match="read-only"):
        await shadow.run_once()


@pytest.mark.asyncio
async def test_shadow_loop_stops_on_the_kill_switch(monkeypatch) -> None:
    monkeypatch.setattr(settings, "SALES_ARCHIVE_SHADOW_ENABLED", False)

    assert await shadow.sales_archive_shadow_loop() is None
