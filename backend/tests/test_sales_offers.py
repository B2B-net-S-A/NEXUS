"""Sprzedaż → Oferty: kroki po wysłaniu oferty, sekcje „W toku” i „Do decyzji”, „Przejmij”.

Baza testowa jest wspólna dla przebiegu, więc każdy test ma własne konta i patrzy
tylko na własne szanse.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal
from typing import Any, Optional
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import select, update

from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.core.scheduling import DEFAULT_TZ, business_today
from app.models.sales import (
    SalesActivity,
    SalesCompany,
    SalesCompanyBriefing,
    SalesOpportunity,
    SalesOpportunityEvent,
    SalesPipeline,
    SalesPipelineStage,
)
from app.models.user import User
from app.services.sales import offer_steps, offers, signal_targets
from tests.test_sales_companies_api import _headers, _user

OFFERS = "/api/sales/offers"
OPPORTUNITIES = "/api/sales/opportunities"
ACTIVITIES = "/api/sales/activities"
ZONE = ZoneInfo(DEFAULT_TZ)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _noon(day: date) -> datetime:
    """Południe dnia firmy: wiek w dniach nie zależy od pory biegu ani zmiany czasu."""

    return datetime.combine(day, time(12), tzinfo=ZONE)


def _days_ago(days: int) -> datetime:
    return _noon(business_today() - timedelta(days=days))


async def _company() -> int:
    marker = uuid.uuid4().hex[:10]
    async with AsyncSessionLocal() as db:
        company = SalesCompany(
            name=f"Oferty Firma {marker}", normalized_name=f"oferty firma {marker}"
        )
        db.add(company)
        await db.commit()
        return company.id


async def _stage(key: str) -> tuple[int, int]:
    async with AsyncSessionLocal() as db:
        row = (
            await db.execute(
                select(SalesPipelineStage.pipeline_id, SalesPipelineStage.id)
                .join(SalesPipeline, SalesPipeline.id == SalesPipelineStage.pipeline_id)
                .where(SalesPipeline.key == "sales", SalesPipelineStage.key == key)
            )
        ).one()
    return row[0], row[1]


async def _opportunity(
    owner_id: Optional[int],
    *,
    stage: str = "offer-sent",
    age_days: int = 0,
    mrr: Optional[str] = None,
    title: Optional[str] = None,
    **fields: Any,
) -> int:
    """Szansa wpisana wprost do bazy, jak z importu: bez historii i bez kroków."""

    pipeline_id, stage_id = await _stage(stage)
    async with AsyncSessionLocal() as db:
        opportunity = SalesOpportunity(
            company_id=await _company(),
            pipeline_id=pipeline_id,
            stage_id=stage_id,
            title=title or f"Zespół analityków {uuid.uuid4().hex[:8]}",
            owner_user_id=owner_id,
            mrr_value=Decimal(mrr) if mrr else None,
            created_at=_days_ago(age_days) if age_days else _now(),
            **fields,
        )
        db.add(opportunity)
        await db.commit()
        return opportunity.id


async def _activity(**fields: Any) -> int:
    async with AsyncSessionLocal() as db:
        activity = SalesActivity(**fields)
        db.add(activity)
        await db.commit()
        return activity.id


async def _deactivate(user: User) -> None:
    async with AsyncSessionLocal() as db:
        await db.execute(update(User).where(User.id == user.id).values(is_active=False))
        await db.commit()


async def _tasks(opportunity_id: int) -> list[SalesActivity]:
    async with AsyncSessionLocal() as db:
        return list(
            (
                await db.scalars(
                    select(SalesActivity)
                    .where(
                        SalesActivity.opportunity_id == opportunity_id,
                        SalesActivity.kind == "task",
                    )
                    .order_by(SalesActivity.due_at, SalesActivity.id)
                )
            ).all()
        )


async def _owner_events(opportunity_id: int) -> list[SalesOpportunityEvent]:
    async with AsyncSessionLocal() as db:
        return list(
            (
                await db.scalars(
                    select(SalesOpportunityEvent).where(
                        SalesOpportunityEvent.opportunity_id == opportunity_id,
                        SalesOpportunityEvent.field == "owner_user_id",
                    )
                )
            ).all()
        )


async def _owner_of(opportunity_id: int) -> Optional[int]:
    async with AsyncSessionLocal() as db:
        return await db.scalar(
            select(SalesOpportunity.owner_user_id).where(
                SalesOpportunity.id == opportunity_id
            )
        )


async def _move(app_client: Any, user: User, opportunity_id: int, stage: str) -> None:
    _pipeline_id, stage_id = await _stage(stage)
    resp = await app_client.post(
        f"{OPPORTUNITIES}/{opportunity_id}/move",
        json={"stage_id": stage_id},
        headers=_headers(user),
    )
    assert resp.status_code == 200, resp.text


async def _listed(app_client: Any, user: User, **params: Any) -> dict[str, Any]:
    resp = await app_client.get(OFFERS, params=params, headers=_headers(user))
    assert resp.status_code == 200, resp.text
    return resp.json()


def _row(body: dict[str, Any], opportunity_id: int) -> Optional[dict[str, Any]]:
    return next((item for item in body["items"] if item["id"] == opportunity_id), None)


async def _take_over(app_client: Any, user: User, opportunity_id: int) -> Any:
    return await app_client.post(
        f"{OPPORTUNITIES}/{opportunity_id}/take-over", headers=_headers(user)
    )


# ── Kroki po wysłaniu oferty ─────────────────────────────────────────────


@pytest.mark.parametrize(
    ("sent_on", "day", "expected"),
    [
        # Środa + 3 = sobota, więc poniedziałek.
        (date(2026, 11, 4), 3, date(2026, 11, 9)),
        # Niedziela + 3 = 11 listopada (święto), więc czwartek.
        (date(2026, 11, 8), 3, date(2026, 11, 12)),
        (date(2026, 11, 2), 14, date(2026, 11, 16)),
        (date(2026, 11, 2), 30, date(2026, 12, 2)),
    ],
)
def test_step_falls_on_a_business_day_morning(
    sent_on: date, day: int, expected: date
) -> None:
    due = offer_steps.step_due_at(sent_on, day).astimezone(ZONE)
    assert due.date() == expected
    assert (due.hour, due.minute) == (offer_steps.STEP_HOUR, 0)


@pytest.mark.asyncio
async def test_entering_offer_stage_sets_three_steps_for_the_owner(app_client) -> None:
    rep = await _user("sales_edit")
    opp = await _opportunity(rep.id, stage="qualified")
    await _move(app_client, rep, opp, "offer-sent")

    tasks = await _tasks(opp)
    today = business_today()
    assert [task.subject for task in tasks] == [
        step.subject for step in offer_steps.STEPS
    ]
    assert [task.due_at for task in tasks] == [
        offer_steps.step_due_at(today, step.day) for step in offer_steps.STEPS
    ]
    for task in tasks:
        assert task.assignee_user_id == rep.id
        assert task.created_by_user_id == rep.id
        assert task.external_source == offer_steps.OFFER_STEP_SOURCE
        assert task.done_at is None

    row = _row(await _listed(app_client, rep, scope="mine"), opp)
    assert row is not None
    assert row["section"] == "in_progress"
    assert row["step"]["subject"] == offer_steps.STEPS[0].subject
    assert row["step"]["activity_id"] == tasks[0].id
    assert row["step"]["overdue"] is False


@pytest.mark.asyncio
async def test_steps_go_to_the_owner_who_can_change_and_delete_them(app_client) -> None:
    owner = await _user("sales_edit")
    mover = await _user("sales_edit")
    opp = await _opportunity(owner.id, stage="qualified")
    await _move(app_client, mover, opp, "offer-sent")

    tasks = await _tasks(opp)
    assert {task.assignee_user_id for task in tasks} == {owner.id}
    assert {task.created_by_user_id for task in tasks} == {owner.id}

    later = (_now() + timedelta(days=5)).isoformat()
    changed = await app_client.patch(
        f"{ACTIVITIES}/{tasks[0].id}", json={"due_at": later}, headers=_headers(owner)
    )
    assert changed.status_code == 200, changed.text
    removed = await app_client.delete(
        f"{ACTIVITIES}/{tasks[1].id}", headers=_headers(owner)
    )
    assert removed.status_code == 204, removed.text
    assert len(await _tasks(opp)) == 2


@pytest.mark.asyncio
async def test_inactive_owner_leaves_steps_with_the_person_who_moved(
    app_client,
) -> None:
    gone = await _user("sales_edit")
    mover = await _user("sales_edit")
    opp = await _opportunity(gone.id, stage="qualified")
    await _deactivate(gone)
    await _move(app_client, mover, opp, "offer-sent")
    assert {task.assignee_user_id for task in await _tasks(opp)} == {mover.id}


@pytest.mark.asyncio
async def test_opportunity_created_on_offer_stage_gets_steps(app_client) -> None:
    rep = await _user("sales_edit")
    pipeline_id, stage_id = await _stage("offer-sent")
    resp = await app_client.post(
        OPPORTUNITIES,
        json={
            "company_id": await _company(),
            "title": "Oferta od razu",
            "pipeline_id": pipeline_id,
            "stage_id": stage_id,
        },
        headers=_headers(rep),
    )
    assert resp.status_code == 201, resp.text
    assert len(await _tasks(resp.json()["id"])) == len(offer_steps.STEPS)


@pytest.mark.asyncio
async def test_other_stages_and_tenders_get_no_steps(app_client) -> None:
    rep = await _user("sales_edit")
    opp = await _opportunity(rep.id, stage="lead")
    await _move(app_client, rep, opp, "qualified")
    assert await _tasks(opp) == []

    async with AsyncSessionLocal() as db:
        tender = await db.get(SalesOpportunity, opp)
        added = await offer_steps.schedule_on_entry(
            db, tender, "tender-submitted", user_id=rep.id, now=_now()
        )
        await db.commit()
    assert added == 0
    assert await _tasks(opp) == []


@pytest.mark.asyncio
async def test_offer_already_on_the_stage_gets_no_steps_backwards(app_client) -> None:
    rep = await _user("sales_edit")
    opp = await _opportunity(rep.id, age_days=5)
    row = _row(await _listed(app_client, rep, scope="mine"), opp)
    assert row is not None
    assert row["step"] is None
    assert await _tasks(opp) == []


@pytest.mark.asyncio
async def test_coming_back_to_the_stage_does_not_duplicate_open_steps(
    app_client,
) -> None:
    rep = await _user("sales_edit")
    opp = await _opportunity(rep.id, stage="qualified")
    await _move(app_client, rep, opp, "offer-sent")
    await _move(app_client, rep, opp, "qualified")
    await _move(app_client, rep, opp, "offer-sent")
    assert len(await _tasks(opp)) == len(offer_steps.STEPS)

    # Wszystkie odhaczone: kolejna oferta to nowy komplet kroków.
    for task in await _tasks(opp):
        done = await app_client.post(
            f"{ACTIVITIES}/{task.id}/done", headers=_headers(rep)
        )
        assert done.status_code == 200, done.text
    await _move(app_client, rep, opp, "qualified")
    await _move(app_client, rep, opp, "offer-sent")
    tasks = await _tasks(opp)
    assert len(tasks) == 2 * len(offer_steps.STEPS)
    assert sum(1 for task in tasks if task.done_at is None) == len(offer_steps.STEPS)


# ── Sekcje ───────────────────────────────────────────────────────────────

TODAY = date(2026, 11, 10)


@pytest.mark.parametrize(
    ("owner_left", "idle_days", "keep_open_until", "expected"),
    [
        (False, 0, None, ("in_progress", None)),
        (False, 30, None, ("in_progress", None)),
        (False, 31, None, ("to_decide", "idle")),
        # Odłożona: data w przyszłości trzyma w toku, dzisiejsza i miniona już nie.
        (False, 90, TODAY + timedelta(days=1), ("in_progress", None)),
        (False, 90, TODAY, ("to_decide", "idle")),
        (False, 90, TODAY - timedelta(days=1), ("to_decide", "idle")),
        (False, 5, TODAY - timedelta(days=1), ("in_progress", None)),
        # Bez opiekuna w Sprzedaży odłożenie niczego nie zmienia.
        (True, 0, None, ("to_decide", "owner_left")),
        (True, 90, TODAY + timedelta(days=30), ("to_decide", "owner_left")),
    ],
)
def test_section_rules(
    owner_left: bool,
    idle_days: int,
    keep_open_until: Optional[date],
    expected: tuple[str, Optional[str]],
) -> None:
    assert (
        offers.decide_section(
            owner_left=owner_left,
            idle_days=idle_days,
            keep_open_until=keep_open_until,
            today=TODAY,
        )
        == expected
    )


@pytest.mark.asyncio
async def test_exactly_thirty_idle_days_is_in_progress_and_one_more_waits(
    app_client,
) -> None:
    rep = await _user("sales_edit")
    edge = await _opportunity(rep.id, age_days=30)
    over = await _opportunity(rep.id, age_days=31)
    body = await _listed(app_client, rep, scope="mine")

    assert _row(body, edge)["section"] == "in_progress"
    assert _row(body, edge)["idle_days"] == 30
    assert _row(body, over)["section"] == "to_decide"
    assert _row(body, over)["reason"] == "idle"
    assert _row(body, over)["idle_days"] == 31


@pytest.mark.asyncio
async def test_postponed_offer_is_in_progress_until_the_date(app_client) -> None:
    rep = await _user("sales_edit")
    today = business_today()
    future = await _opportunity(
        rep.id, age_days=60, keep_open_until=today + timedelta(days=7)
    )
    due_today = await _opportunity(rep.id, age_days=60, keep_open_until=today)
    past = await _opportunity(
        rep.id, age_days=60, keep_open_until=today - timedelta(days=3)
    )
    body = await _listed(app_client, rep, scope="mine")

    assert _row(body, future)["section"] == "in_progress"
    assert _row(body, future)["postponed"] is True
    assert _row(body, past)["postponed"] is False
    assert (
        _row(body, future)["keep_open_until"] == (today + timedelta(days=7)).isoformat()
    )
    assert _row(body, due_today)["section"] == "to_decide"
    assert _row(body, past)["section"] == "to_decide"


@pytest.mark.asyncio
async def test_postponing_moves_the_offer_back_and_stays_in_history(app_client) -> None:
    rep = await _user("sales_edit")
    opp = await _opportunity(rep.id, age_days=45)
    assert (
        _row(await _listed(app_client, rep, scope="mine"), opp)["section"]
        == "to_decide"
    )

    until = (business_today() + timedelta(days=14)).isoformat()
    resp = await app_client.patch(
        f"{OPPORTUNITIES}/{opp}", json={"keep_open_until": until}, headers=_headers(rep)
    )
    assert resp.status_code == 200, resp.text

    row = _row(await _listed(app_client, rep, scope="mine"), opp)
    assert row["section"] == "in_progress"
    # Odłożenie nie jest ruchem: dni bez ruchu liczą się dalej.
    assert row["idle_days"] == 45
    history = await app_client.get(
        f"{OPPORTUNITIES}/{opp}/history", headers=_headers(rep)
    )
    event = next(e for e in history.json() if e["field"] == "keep_open_until")
    assert (event["old_value"], event["new_value"]) == (None, until)


@pytest.mark.asyncio
async def test_sending_the_offer_counts_as_movement(app_client) -> None:
    rep = await _user("sales_edit")
    opp = await _opportunity(rep.id, stage="qualified", age_days=90)
    await _move(app_client, rep, opp, "offer-sent")
    row = _row(await _listed(app_client, rep, scope="mine"), opp)
    assert row["section"] == "in_progress"
    assert row["idle_days"] == 0


@pytest.mark.asyncio
async def test_touch_and_done_step_reset_idle_days(app_client) -> None:
    rep = await _user("sales_edit")
    touched = await _opportunity(rep.id, age_days=90)
    async with AsyncSessionLocal() as db:
        company_id = (await db.get(SalesOpportunity, touched)).company_id
    await _activity(
        kind="note",
        body="Rozmowa o ofercie",
        company_id=company_id,
        opportunity_id=touched,
        occurred_at=_days_ago(2),
    )
    stepped = await _opportunity(rep.id, age_days=90)
    step = await _activity(
        kind="task",
        subject="Zapytać o decyzję",
        opportunity_id=stepped,
        due_at=_now() + timedelta(days=1),
        assignee_user_id=rep.id,
    )
    body = await _listed(app_client, rep, scope="mine")
    assert (_row(body, touched)["section"], _row(body, touched)["idle_days"]) == (
        "in_progress",
        2,
    )
    # Sam zaplanowany krok ruchem nie jest: oferta czeka na decyzję dalej.
    assert _row(body, stepped)["section"] == "to_decide"

    done = await app_client.post(f"{ACTIVITIES}/{step}/done", headers=_headers(rep))
    assert done.status_code == 200, done.text
    row = _row(await _listed(app_client, rep, scope="mine"), stepped)
    assert (row["section"], row["idle_days"], row["step"]) == ("in_progress", 0, None)


@pytest.mark.asyncio
async def test_overdue_step_comes_before_the_planned_one(app_client) -> None:
    rep = await _user("sales_edit")
    opp = await _opportunity(rep.id, age_days=10)
    late = await _activity(
        kind="task",
        subject="Potwierdzić odbiór",
        opportunity_id=opp,
        due_at=_days_ago(4),
        assignee_user_id=rep.id,
    )
    await _activity(
        kind="task",
        subject="Zapytać o decyzję",
        opportunity_id=opp,
        due_at=_now() + timedelta(days=4),
        assignee_user_id=rep.id,
    )
    step = _row(await _listed(app_client, rep, scope="mine"), opp)["step"]
    assert (step["activity_id"], step["overdue"]) == (late, True)


@pytest.mark.asyncio
async def test_owner_outside_sales_puts_any_stage_into_to_decide(app_client) -> None:
    rep = await _user("sales_edit")
    inactive = await _user("sales_edit")
    without_rights = await _user()
    viewer = await _user("sales_view")
    fresh_offer = await _opportunity(inactive.id)
    lead = await _opportunity(inactive.id, stage="lead")
    no_rights_lead = await _opportunity(without_rights.id, stage="qualifying-meeting")
    viewer_lead = await _opportunity(viewer.id, stage="lead")
    viewer_offer = await _opportunity(viewer.id)
    own_lead = await _opportunity(rep.id, stage="lead")
    await _deactivate(inactive)

    body = await _listed(app_client, rep, scope="all")
    for opportunity_id, is_offer in (
        (fresh_offer, True),
        (lead, False),
        (no_rights_lead, False),
    ):
        row = _row(body, opportunity_id)
        assert row is not None
        assert (row["section"], row["reason"]) == ("to_decide", "owner_left")
        assert row["owner_in_sales"] is False
        assert row["is_offer"] is is_offer
    # Konto z samym podglądem nadal pracuje w Sprzedaży.
    assert _row(body, viewer_lead) is None
    assert _row(body, viewer_offer)["owner_in_sales"] is True
    assert _row(body, viewer_offer)["section"] == "in_progress"
    # Szansa spoza etapu oferty z opiekunem ze Sprzedaży tu nie trafia.
    assert _row(body, own_lead) is None

    unowned = await _listed(app_client, rep, scope="unowned")
    assert _row(unowned, lead) is not None
    assert _row(unowned, viewer_offer) is None


@pytest.mark.asyncio
async def test_offer_without_owner_is_unowned_and_follows_idle_days(app_client) -> None:
    rep = await _user("sales_edit")
    fresh = await _opportunity(None)
    stale = await _opportunity(None, age_days=40)
    body = await _listed(app_client, rep, scope="unowned")
    assert _row(body, fresh)["section"] == "in_progress"
    assert _row(body, fresh)["owner_in_sales"] is False
    assert _row(body, stale)["section"] == "to_decide"


@pytest.mark.asyncio
async def test_closed_and_archived_offers_are_not_listed(app_client) -> None:
    rep = await _user("sales_edit")
    lost = await _opportunity(rep.id, status="lost")
    archived = await _opportunity(rep.id, archived_at=_now())
    body = await _listed(app_client, rep, scope="mine")
    assert _row(body, lost) is None
    assert _row(body, archived) is None


@pytest.mark.asyncio
async def test_scopes_carry_counters_and_mrr_of_each_section(app_client) -> None:
    rep = await _user("sales_edit")
    await _opportunity(rep.id, mrr="1000.00")
    await _opportunity(rep.id, mrr="2500.50")
    small = await _opportunity(rep.id, age_days=40, mrr="400.00")
    big = await _opportunity(rep.id, age_days=35, mrr="9000.00")
    await _opportunity(rep.id, age_days=50)

    body = await _listed(app_client, rep)
    # Bez parametru: osoba z własnymi pozycjami dostaje „Moje”.
    assert body["scope"] == "mine"
    mine = body["totals"]["mine"]
    assert mine["in_progress"] == {"count": 2, "mrr": "3500.50"}
    assert mine["to_decide"] == {"count": 3, "mrr": "9400.00"}
    assert body["totals"]["all"]["to_decide"]["count"] >= 3
    # „Do decyzji” od największej kwoty, pozycja bez kwoty na końcu.
    waiting = [item["id"] for item in body["items"] if item["section"] == "to_decide"]
    assert waiting[:2] == [big, small]
    assert [item["section"] for item in body["items"]] == sorted(
        item["section"] for item in body["items"]
    )


@pytest.mark.asyncio
async def test_person_without_own_offers_starts_on_all(app_client) -> None:
    viewer = await _user("sales_view")
    body = await _listed(app_client, viewer)
    assert body["scope"] == "all"
    assert body["totals"]["mine"]["in_progress"]["count"] == 0
    assert body["totals"]["mine"]["to_decide"]["count"] == 0


@pytest.mark.asyncio
async def test_default_scope_does_not_follow_the_search(app_client) -> None:
    rep = await _user("sales_edit")
    colleague = await _user("sales_edit")
    await _opportunity(rep.id)
    tag = uuid.uuid4().hex[:10]
    theirs = await _opportunity(colleague.id, title=f"Migracja chmury {tag}")
    # Fraza trafia tylko w cudzą ofertę: zakres zostaje „Moje”, a licznik mówi, gdzie szukać.
    body = await _listed(app_client, rep, q=tag)
    assert body["scope"] == "mine"
    assert body["items"] == []
    assert body["totals"]["all"]["in_progress"]["count"] == 1
    assert _row(await _listed(app_client, rep, scope="all", q=tag), theirs) is not None


@pytest.mark.asyncio
async def test_search_narrows_rows_and_counters(app_client) -> None:
    rep = await _user("sales_edit")
    tag = uuid.uuid4().hex[:10]
    wanted = await _opportunity(rep.id, title=f"Hurtownia danych {tag}")
    other = await _opportunity(rep.id)
    body = await _listed(app_client, rep, scope="mine", q=tag)
    assert [item["id"] for item in body["items"]] == [wanted]
    assert body["totals"]["mine"]["in_progress"]["count"] == 1
    assert _row(await _listed(app_client, rep, scope="mine"), other) is not None


@pytest.mark.asyncio
async def test_offers_need_sales_view(app_client) -> None:
    stranger = await _user()
    resp = await app_client.get(OFFERS, headers=_headers(stranger))
    assert resp.status_code == 403
    assert (await app_client.get(OFFERS)).status_code == 401


# ── „Przejmij” ───────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_take_over_from_inactive_owner_moves_owner_history_and_tasks(
    app_client,
) -> None:
    gone = await _user("sales_edit")
    colleague = await _user("sales_edit")
    rep = await _user("sales_edit")
    opp = await _opportunity(gone.id, stage="qualified")
    await _move(app_client, gone, opp, "offer-sent")
    someone_elses = await _activity(
        kind="task",
        subject="Umowa ramowa",
        opportunity_id=opp,
        due_at=_now() + timedelta(days=2),
        assignee_user_id=colleague.id,
        created_by_user_id=gone.id,
    )
    finished = await _activity(
        kind="task",
        subject="Wysłać ofertę",
        opportunity_id=opp,
        due_at=_days_ago(1),
        done_at=_days_ago(1),
        assignee_user_id=gone.id,
        created_by_user_id=gone.id,
    )
    await _deactivate(gone)

    resp = await _take_over(app_client, rep, opp)
    assert resp.status_code == 200, resp.text
    assert resp.json() == {"id": opp, "owner": {"id": rep.id, "name": rep.name}}
    assert await _owner_of(opp) == rep.id

    events = await _owner_events(opp)
    assert [(e.old_value, e.new_value, e.user_id) for e in events] == [
        (str(gone.id), str(rep.id), rep.id)
    ]
    tasks = {task.id: task for task in await _tasks(opp)}
    steps = [
        t for t in tasks.values() if t.external_source == offer_steps.OFFER_STEP_SOURCE
    ]
    assert len(steps) == len(offer_steps.STEPS)
    for step in steps:
        assert (step.assignee_user_id, step.created_by_user_id) == (rep.id, rep.id)
    assert tasks[someone_elses].assignee_user_id == colleague.id
    assert tasks[finished].assignee_user_id == gone.id

    # Po przejęciu to zwykła oferta przejmującego.
    row = _row(await _listed(app_client, rep, scope="mine"), opp)
    assert (row["section"], row["owner_in_sales"]) == ("in_progress", True)


@pytest.mark.asyncio
async def test_take_over_from_owner_without_sales_permissions(app_client) -> None:
    moved_on = await _user()
    rep = await _user("sales_edit")
    opp = await _opportunity(moved_on.id, stage="lead")
    resp = await _take_over(app_client, rep, opp)
    assert resp.status_code == 200, resp.text
    assert await _owner_of(opp) == rep.id
    # Szansa spoza etapu oferty wraca do zwykłej pracy i znika z zakładki.
    assert _row(await _listed(app_client, rep, scope="all"), opp) is None


@pytest.mark.asyncio
async def test_take_over_of_offer_without_owner(app_client) -> None:
    rep = await _user("sales_edit")
    opp = await _opportunity(None, age_days=40)
    resp = await _take_over(app_client, rep, opp)
    assert resp.status_code == 200, resp.text
    events = await _owner_events(opp)
    assert [(e.old_value, e.new_value) for e in events] == [(None, str(rep.id))]


@pytest.mark.asyncio
@pytest.mark.parametrize("grant", ["sales_edit", "sales_view"])
async def test_take_over_refused_while_owner_works_in_sales(app_client, grant) -> None:
    owner = await _user(grant)
    rep = await _user("sales_edit")
    opp = await _opportunity(owner.id, age_days=60)
    resp = await _take_over(app_client, rep, opp)
    assert resp.status_code == 409
    assert resp.json()["detail"] == offers.OWNED_DETAIL
    assert await _owner_of(opp) == owner.id
    assert await _owner_events(opp) == []


@pytest.mark.asyncio
async def test_take_over_needs_sales_edit(app_client) -> None:
    gone = await _user("sales_edit")
    viewer = await _user("sales_view")
    stranger = await _user()
    opp = await _opportunity(gone.id)
    await _deactivate(gone)
    for user in (viewer, stranger):
        resp = await _take_over(app_client, user, opp)
        assert resp.status_code == 403, resp.text
    assert await _owner_of(opp) == gone.id


@pytest.mark.asyncio
async def test_take_over_refuses_closed_archived_and_missing(app_client) -> None:
    gone = await _user("sales_edit")
    rep = await _user("sales_edit")
    lost = await _opportunity(gone.id, status="lost")
    archived = await _opportunity(gone.id, archived_at=_now())
    await _deactivate(gone)
    for opportunity_id in (lost, archived):
        resp = await _take_over(app_client, rep, opportunity_id)
        assert resp.status_code == 409
        assert resp.json()["detail"] == offers.CLOSED_DETAIL
        assert await _owner_of(opportunity_id) == gone.id
    assert (await _take_over(app_client, rep, 2_000_000_000)).status_code == 404


@pytest.mark.asyncio
async def test_take_over_by_the_owner_changes_nothing(app_client) -> None:
    rep = await _user("sales_edit")
    opp = await _opportunity(rep.id)
    resp = await _take_over(app_client, rep, opp)
    assert resp.status_code == 200, resp.text
    assert await _owner_events(opp) == []


# ── Punkty bota przy „Do decyzji” ────────────────────────────────────────


async def _company_of(opportunity_id: int) -> int:
    async with AsyncSessionLocal() as db:
        return await db.scalar(
            select(SalesOpportunity.company_id).where(
                SalesOpportunity.id == opportunity_id
            )
        )


async def _briefing(opportunity_id: int, points: list[dict[str, Any]], **fields) -> int:
    company_id = await _company_of(opportunity_id)
    async with AsyncSessionLocal() as db:
        db.add(
            SalesCompanyBriefing(
                company_id=company_id, mode="ongoing", points=points, **fields
            )
        )
        await db.commit()
    return company_id


POINT = {
    "text": "Nowy program w banku",
    "url": "https://e.com/a",
    "published": "2026-11-02",
}


@pytest.mark.asyncio
async def test_to_decide_rows_carry_bot_points_only_with_the_channel_on(
    app_client, monkeypatch
) -> None:
    rep = await _user("sales_edit")
    with_points = await _opportunity(rep.id, age_days=40)
    nothing_new = await _opportunity(rep.id, age_days=40)
    never_checked = await _opportunity(rep.id, age_days=40)
    in_progress = await _opportunity(rep.id)
    await _briefing(with_points, [POINT])
    await _briefing(nothing_new, [])
    await _briefing(in_progress, [POINT])

    monkeypatch.setattr(settings, "SALES_SIGNALS_ENABLED", True)
    body = await _listed(app_client, rep, scope="mine")
    points = _row(body, with_points)["bot_points"]
    assert points["points"] == [POINT]
    assert points["generated_at"]
    assert _row(body, nothing_new)["bot_points"]["points"] == []
    assert _row(body, never_checked)["bot_points"] is None
    # „W toku” punktów nie dostaje: tam jest krok, a punkty są na karcie szansy.
    assert _row(body, in_progress)["bot_points"] is None

    monkeypatch.setattr(settings, "SALES_SIGNALS_ENABLED", False)
    body = await _listed(app_client, rep, scope="mine")
    assert _row(body, with_points)["bot_points"] is None


@pytest.mark.asyncio
async def test_to_decide_firms_go_to_the_bot_unless_their_points_are_fresh() -> None:
    rep = await _user("sales_edit")
    # Duża kwota: wspólna baza testowa ma inne pozycje, a lista idzie od największego MRR.
    no_points = await _opportunity(rep.id, age_days=40, mrr="9000000.00")
    stale = await _opportunity(rep.id, age_days=40, mrr="9000000.00")
    fresh = await _opportunity(rep.id, age_days=40, mrr="9000000.00")
    in_progress = await _opportunity(rep.id, mrr="9000000.00")
    await _briefing(stale, [POINT], generated_at=_now() - timedelta(days=8))
    await _briefing(fresh, [POINT], generated_at=_now() - timedelta(days=1))

    async with AsyncSessionLocal() as db:
        chosen = await signal_targets.to_decide_company_ids(db, now=_now())
    assert await _company_of(no_points) in chosen
    assert await _company_of(stale) in chosen
    assert await _company_of(fresh) not in chosen
    assert await _company_of(in_progress) not in chosen
