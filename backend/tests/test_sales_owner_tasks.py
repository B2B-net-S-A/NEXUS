"""Sprzedaż: otwarte zadania przy szansie idą za zmianą jej opiekuna.

Baza testowa jest wspólna dla przebiegu, więc każdy test ma własne konta i patrzy
tylko na własne szanse.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any, Optional

import pytest
from sqlalchemy import select

from app.core.database import AsyncSessionLocal
from app.models.sales import SalesActivity, SalesOpportunity
from app.models.user import User
from app.services.sales import offer_steps
from tests.test_sales_companies_api import _headers, _user
from tests.test_sales_handoff import _book, _booked, _verdict
from tests.test_sales_offers import (
    ACTIVITIES,
    OPPORTUNITIES,
    _activity,
    _days_ago,
    _listed,
    _move,
    _now,
    _opportunity,
    _owner_events,
    _owner_of,
    _row,
    _tasks,
)

MY_DAY = "/api/sales/my-day"


async def _change_owner(
    app_client: Any, user: User, opportunity_id: int, owner_id: Optional[int]
) -> Any:
    return await app_client.patch(
        f"{OPPORTUNITIES}/{opportunity_id}",
        json={"owner_user_id": owner_id},
        headers=_headers(user),
    )


async def _my_tasks(app_client: Any, user: User) -> set[int]:
    resp = await app_client.get(
        f"{ACTIVITIES}/tasks", params={"scope": "mine"}, headers=_headers(user)
    )
    assert resp.status_code == 200, resp.text
    return {item["id"] for item in resp.json()["items"]}


async def _my_overdue(app_client: Any, user: User) -> set[int]:
    resp = await app_client.get(MY_DAY, headers=_headers(user))
    assert resp.status_code == 200, resp.text
    return {row["activity_id"] for row in resp.json()["overdue"]}


async def _company_of(opportunity_id: int) -> int:
    async with AsyncSessionLocal() as db:
        return await db.scalar(
            select(SalesOpportunity.company_id).where(
                SalesOpportunity.id == opportunity_id
            )
        )


async def _people(*activity_ids: int) -> dict[int, tuple[Optional[int], Optional[int]]]:
    """Wykonawca i autor każdej pozycji."""

    async with AsyncSessionLocal() as db:
        rows = await db.execute(
            select(
                SalesActivity.id,
                SalesActivity.assignee_user_id,
                SalesActivity.created_by_user_id,
            ).where(SalesActivity.id.in_(activity_ids))
        )
        return {row.id: (row.assignee_user_id, row.created_by_user_id) for row in rows}


@pytest.mark.asyncio
async def test_changing_the_owner_hands_offer_steps_to_the_new_owner(
    app_client,
) -> None:
    owner = await _user("sales_edit")
    successor = await _user("sales_edit")
    opp = await _opportunity(owner.id, stage="qualified")
    await _move(app_client, owner, opp, "offer-sent")

    resp = await _change_owner(app_client, owner, opp, successor.id)
    assert resp.status_code == 200, resp.text
    assert resp.json()["owner"]["id"] == successor.id

    steps = await _tasks(opp)
    assert len(steps) == len(offer_steps.STEPS)
    # Nowy opiekun widzi krok w „Co dalej” zakładki Oferty…
    row = _row(await _listed(app_client, successor, scope="mine"), opp)
    assert row["step"]["activity_id"] == steps[0].id
    # …więc ma go też na swojej liście zadań i może go usunąć jak własny.
    for step in steps:
        assert (step.assignee_user_id, step.created_by_user_id) == (
            successor.id,
            successor.id,
        )
    assert {step.id for step in steps} <= await _my_tasks(app_client, successor)
    assert not {step.id for step in steps} & await _my_tasks(app_client, owner)
    removed = await app_client.delete(
        f"{ACTIVITIES}/{steps[-1].id}", headers=_headers(successor)
    )
    assert removed.status_code == 204, removed.text
    later = (_now() + timedelta(days=5)).isoformat()
    changed = await app_client.patch(
        f"{ACTIVITIES}/{steps[0].id}",
        json={"due_at": later},
        headers=_headers(successor),
    )
    assert changed.status_code == 200, changed.text


@pytest.mark.asyncio
async def test_only_open_items_of_the_previous_owner_follow_the_opportunity(
    app_client,
) -> None:
    owner = await _user("sales_edit")
    successor = await _user("sales_edit")
    colleague = await _user("sales_edit")
    opp = await _opportunity(owner.id, stage="qualified")
    company_id = await _company_of(opp)
    other_opp = await _opportunity(owner.id, stage="qualified")
    own = {"assignee_user_id": owner.id, "created_by_user_id": owner.id}
    here = {"opportunity_id": opp, "company_id": company_id}

    overdue_task = await _activity(
        kind="task",
        subject="Umowa ramowa",
        due_at=_days_ago(3),
        assignee_user_id=owner.id,
        created_by_user_id=colleague.id,
        **here,
    )
    planned_call = await _activity(
        kind="call",
        subject="Oddzwonić",
        due_at=_now() + timedelta(days=2),
        **own,
        **here,
    )
    someone_elses = await _activity(
        kind="task",
        subject="Referencje",
        due_at=_now() + timedelta(days=2),
        assignee_user_id=colleague.id,
        created_by_user_id=owner.id,
        **here,
    )
    finished = await _activity(
        kind="task",
        subject="Wysłać ofertę",
        due_at=_days_ago(2),
        done_at=_days_ago(2),
        **own,
        **here,
    )
    # Telefon bez terminu to wpis historii, nie zadanie.
    history_call = await _activity(
        kind="call", subject="Rozmowa", occurred_at=_days_ago(5), **own, **here
    )
    elsewhere = await _activity(
        kind="task",
        subject="Inna szansa",
        due_at=_days_ago(1),
        opportunity_id=other_opp,
        company_id=await _company_of(other_opp),
        **own,
    )
    at_company = await _activity(
        kind="task",
        subject="Firma bez szansy",
        due_at=_days_ago(1),
        company_id=company_id,
        **own,
    )

    resp = await _change_owner(app_client, owner, opp, successor.id)
    assert resp.status_code == 200, resp.text

    people = await _people(
        overdue_task,
        planned_call,
        someone_elses,
        finished,
        history_call,
        elsewhere,
        at_company,
    )
    # Wykonawca się zmienia, autor zwykłego zadania zostaje.
    assert people[overdue_task] == (successor.id, colleague.id)
    assert people[planned_call] == (successor.id, owner.id)
    assert people[someone_elses] == (colleague.id, owner.id)
    for untouched in (finished, history_call, elsewhere, at_company):
        assert people[untouched] == (owner.id, owner.id)

    assert overdue_task in await _my_overdue(app_client, successor)
    assert await _my_overdue(app_client, owner) == {elsewhere, at_company}


@pytest.mark.asyncio
async def test_other_edits_and_the_same_owner_leave_tasks_alone(app_client) -> None:
    owner = await _user("sales_edit")
    colleague = await _user("sales_edit")
    opp = await _opportunity(owner.id, stage="qualified")
    await _move(app_client, owner, opp, "offer-sent")

    edited = await app_client.patch(
        f"{OPPORTUNITIES}/{opp}",
        json={"campaign": "Jesień"},
        headers=_headers(colleague),
    )
    assert edited.status_code == 200, edited.text
    same = await _change_owner(app_client, owner, opp, owner.id)
    assert same.status_code == 200, same.text
    # Cudzej szansy nie da się przejąć zwykłą edycją, więc zadania też zostają.
    refused = await _change_owner(app_client, colleague, opp, colleague.id)
    assert refused.status_code == 403

    assert await _owner_events(opp) == []
    for step in await _tasks(opp):
        assert (step.assignee_user_id, step.created_by_user_id) == (owner.id, owner.id)


@pytest.mark.asyncio
async def test_removing_the_owner_keeps_tasks_and_a_new_owner_takes_none(
    app_client,
) -> None:
    owner = await _user("sales_edit")
    successor = await _user("sales_edit")
    opp = await _opportunity(owner.id, stage="qualified")
    await _move(app_client, owner, opp, "offer-sent")

    # Bez następcy nie ma komu dać zadań.
    removed = await _change_owner(app_client, owner, opp, None)
    assert removed.status_code == 200, removed.text
    assert await _owner_of(opp) is None
    assert {step.assignee_user_id for step in await _tasks(opp)} == {owner.id}

    # Szansa bez opiekuna nie ma poprzednika, po którym zadania by przeszły.
    taken = await _change_owner(app_client, successor, opp, successor.id)
    assert taken.status_code == 200, taken.text
    assert await _owner_of(opp) == successor.id
    assert {step.assignee_user_id for step in await _tasks(opp)} == {owner.id}


@pytest.mark.asyncio
async def test_booking_a_meeting_with_another_host_hands_tasks_over(app_client) -> None:
    caller = await _user("sales_edit")
    host = await _user("sales_edit")
    next_host = await _user("sales_edit")
    booked = await _booked(app_client, caller, host)
    opp = booked["opportunity"]["id"]
    # „Nie teraz” zostawia prowadzącemu zadanie powrotu do rozmowy.
    verdict = await _verdict(app_client, host, opp, kind="not_now")
    assert verdict.status_code == 200, verdict.text
    [come_back] = await _tasks(opp)
    assert come_back.assignee_user_id == host.id
    callers_task = await _activity(
        kind="task",
        subject="Potwierdzić termin",
        opportunity_id=opp,
        due_at=_now() + timedelta(days=1),
        assignee_user_id=caller.id,
        created_by_user_id=caller.id,
    )

    rebooked = await _book(
        app_client, host, opportunity_id=opp, host_user_id=next_host.id
    )
    assert rebooked.status_code == 201, rebooked.text
    assert await _owner_of(opp) == next_host.id

    people = await _people(come_back.id, callers_task)
    assert people[come_back.id][0] == next_host.id
    # Zadanie osoby, która umówiła, jest jej, nie opiekuna.
    assert people[callers_task] == (caller.id, caller.id)
