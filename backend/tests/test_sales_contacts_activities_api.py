"""Sprzedaż → Kontakty i aktywności: imię i nazwisko, oś czasu, zadania, autor."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import update

from app.core.database import AsyncSessionLocal
from app.models.sales import SalesOpportunity
from app.models.user import User
from tests.test_sales_companies_api import _headers, _user
from tests.test_sales_opportunities_api import _company

CONTACTS = "/api/sales/contacts"
ACTIVITIES = "/api/sales/activities"
OPPS = "/api/sales/opportunities"


@pytest.mark.asyncio
async def test_contact_name_comes_from_parts_and_email_is_checked(app_client) -> None:
    rep = await _user("sales_edit")
    company_id = await _company(app_client, rep)
    created = await app_client.post(
        CONTACTS,
        json={
            "company_id": company_id,
            "first_name": " Łucja ",
            "last_name": "Kowalska",
            "email": "Lucja.K@Example.com",
            "is_executive": True,
        },
        headers=_headers(rep),
    )
    assert created.status_code == 201, created.text
    body = created.json()
    assert (body["full_name"], body["email"]) == (
        "Łucja Kowalska",
        "lucja.k@example.com",
    )

    found = await app_client.get(
        CONTACTS, params={"q": "lucja", "company_id": company_id}, headers=_headers(rep)
    )
    assert [c["id"] for c in found.json()["items"]] == [body["id"]]

    bad = await app_client.post(
        CONTACTS, json={"full_name": "X", "email": "nie-mail"}, headers=_headers(rep)
    )
    assert bad.status_code == 422
    nameless = await app_client.post(
        CONTACTS, json={"title": "CTO"}, headers=_headers(rep)
    )
    assert nameless.status_code == 422


@pytest.mark.asyncio
async def test_activity_on_opportunity_belongs_to_its_company_and_touches_it(
    app_client,
) -> None:
    rep = await _user("sales_edit")
    company_id = await _company(app_client, rep)
    opp = (
        await app_client.post(
            OPPS, json={"company_id": company_id, "title": "Oś"}, headers=_headers(rep)
        )
    ).json()
    call = await app_client.post(
        ACTIVITIES,
        json={"kind": "call", "opportunity_id": opp["id"], "subject": "Rozmowa z CTO"},
        headers=_headers(rep),
    )
    assert call.status_code == 201, call.text
    assert call.json()["company"]["id"] == company_id

    timeline = (
        await app_client.get(
            ACTIVITIES, params={"company_id": company_id}, headers=_headers(rep)
        )
    ).json()
    assert [a["subject"] for a in timeline] == ["Rozmowa z CTO"]
    touched = (
        await app_client.get(f"{OPPS}/{opp['id']}", headers=_headers(rep))
    ).json()
    assert touched["last_activity_at"] is not None

    empty_note = await app_client.post(
        ACTIVITIES,
        json={"kind": "note", "company_id": company_id, "subject": "   "},
        headers=_headers(rep),
    )
    assert empty_note.status_code == 422


@pytest.mark.asyncio
async def test_tasks_buckets_and_only_author_deletes(app_client) -> None:
    rep = await _user("sales_edit")
    other = await _user("sales_edit")
    company_id = await _company(app_client, rep)
    past = (datetime.now(timezone.utc) - timedelta(days=2)).isoformat()
    future = (datetime.now(timezone.utc) + timedelta(days=5)).isoformat()
    late = (
        await app_client.post(
            ACTIVITIES,
            json={
                "kind": "task",
                "company_id": company_id,
                "subject": "Oddzwonić",
                "due_at": past,
            },
            headers=_headers(rep),
        )
    ).json()
    await app_client.post(
        ACTIVITIES,
        json={
            "kind": "task",
            "company_id": company_id,
            "subject": "Oferta",
            "due_at": future,
        },
        headers=_headers(rep),
    )
    assert late["overdue"] is True and late["assignee"]["id"] == rep.id

    overdue = (
        await app_client.get(
            f"{ACTIVITIES}/tasks", params={"bucket": "overdue"}, headers=_headers(rep)
        )
    ).json()["items"]
    assert [t["subject"] for t in overdue] == ["Oddzwonić"]
    mine_open = (
        await app_client.get(f"{ACTIVITIES}/tasks", headers=_headers(rep))
    ).json()["items"]
    assert [t["subject"] for t in mine_open] == ["Oddzwonić", "Oferta"]
    assert (
        await app_client.get(f"{ACTIVITIES}/tasks", headers=_headers(other))
    ).json() == {"items": [], "total": 0}

    done = (
        await app_client.post(f"{ACTIVITIES}/{late['id']}/done", headers=_headers(rep))
    ).json()
    assert done["done_at"] is not None and done["overdue"] is False

    refused = await app_client.delete(
        f"{ACTIVITIES}/{late['id']}", headers=_headers(other)
    )
    assert refused.status_code == 403
    deleted = await app_client.delete(
        f"{ACTIVITIES}/{late['id']}", headers=_headers(rep)
    )
    assert deleted.status_code == 204


async def _opportunity_of(app_client, owner) -> dict:
    company_id = await _company(app_client, owner)
    resp = await app_client.post(
        OPPS,
        json={"company_id": company_id, "title": "Szansa opiekuna"},
        headers=_headers(owner),
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


async def _task(app_client, author, **fields) -> dict:
    resp = await app_client.post(
        ACTIVITIES,
        json={"kind": "task", "subject": "Oddzwonić", **fields},
        headers=_headers(author),
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


@pytest.mark.asyncio
async def test_task_on_opportunity_goes_to_its_owner_not_the_author(
    app_client,
) -> None:
    owner = await _user("sales_edit")
    author = await _user("sales_edit")
    opp = await _opportunity_of(app_client, owner)

    task = await _task(app_client, author, opportunity_id=opp["id"])

    assert task["assignee"]["id"] == owner.id
    assert task["author"]["id"] == author.id
    owner_tasks = (
        await app_client.get(f"{ACTIVITIES}/tasks", headers=_headers(owner))
    ).json()
    assert [t["id"] for t in owner_tasks["items"]] == [task["id"]]
    author_tasks = (
        await app_client.get(f"{ACTIVITIES}/tasks", headers=_headers(author))
    ).json()
    assert author_tasks == {"items": [], "total": 0}


@pytest.mark.asyncio
async def test_call_with_due_date_on_opportunity_goes_to_its_owner(app_client) -> None:
    owner = await _user("sales_edit")
    author = await _user("sales_edit")
    opp = await _opportunity_of(app_client, owner)
    due = (datetime.now(timezone.utc) + timedelta(days=1)).isoformat()

    call = await app_client.post(
        ACTIVITIES,
        json={
            "kind": "call",
            "opportunity_id": opp["id"],
            "subject": "Telefon",
            "due_at": due,
        },
        headers=_headers(author),
    )

    assert call.status_code == 201, call.text
    assert call.json()["assignee"]["id"] == owner.id


@pytest.mark.asyncio
async def test_explicit_assignee_wins_over_opportunity_owner(app_client) -> None:
    owner = await _user("sales_edit")
    author = await _user("sales_edit")
    chosen = await _user("sales_edit")
    opp = await _opportunity_of(app_client, owner)

    task = await _task(
        app_client, author, opportunity_id=opp["id"], assignee_user_id=chosen.id
    )

    assert task["assignee"]["id"] == chosen.id


@pytest.mark.asyncio
async def test_task_without_opportunity_stays_with_the_author(app_client) -> None:
    owner = await _user("sales_edit")
    author = await _user("sales_edit")
    company_id = await _company(app_client, owner)

    task = await _task(app_client, author, company_id=company_id)

    assert task["assignee"]["id"] == author.id


@pytest.mark.asyncio
async def test_task_on_opportunity_without_owner_stays_with_the_author(
    app_client,
) -> None:
    owner = await _user("sales_edit")
    author = await _user("sales_edit")
    opp = await _opportunity_of(app_client, owner)
    async with AsyncSessionLocal() as db:
        await db.execute(
            update(SalesOpportunity)
            .where(SalesOpportunity.id == opp["id"])
            .values(owner_user_id=None)
        )
        await db.commit()

    task = await _task(app_client, author, opportunity_id=opp["id"])

    assert task["assignee"]["id"] == author.id


@pytest.mark.asyncio
async def test_task_on_opportunity_of_inactive_owner_stays_with_the_author(
    app_client,
) -> None:
    owner = await _user("sales_edit")
    author = await _user("sales_edit")
    opp = await _opportunity_of(app_client, owner)
    async with AsyncSessionLocal() as db:
        await db.execute(
            update(User).where(User.id == owner.id).values(is_active=False)
        )
        await db.commit()

    task = await _task(app_client, author, opportunity_id=opp["id"])

    assert task["assignee"]["id"] == author.id


@pytest.mark.asyncio
async def test_cleared_assignee_on_opportunity_task_returns_to_its_owner(
    app_client,
) -> None:
    owner = await _user("sales_edit")
    author = await _user("sales_edit")
    chosen = await _user("sales_edit")
    opp = await _opportunity_of(app_client, owner)
    task = await _task(
        app_client, author, opportunity_id=opp["id"], assignee_user_id=chosen.id
    )

    patched = await app_client.patch(
        f"{ACTIVITIES}/{task['id']}",
        json={"assignee_user_id": None},
        headers=_headers(author),
    )

    assert patched.status_code == 200, patched.text
    assert patched.json()["assignee"]["id"] == owner.id


async def _meeting(app_client, user, company_id: int, **fields) -> int:
    resp = await app_client.post(
        ACTIVITIES,
        json={"kind": "meeting", "company_id": company_id, **fields},
        headers=_headers(user),
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


async def _meetings(app_client, user, **params) -> dict:
    resp = await app_client.get(
        f"{ACTIVITIES}/meetings",
        params={"limit": 500, **params},
        headers=_headers(user),
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


@pytest.mark.asyncio
async def test_meetings_list_filters_and_shortens_the_note(app_client) -> None:
    rep = await _user("sales_edit")
    company_id = await _company(app_client, rep)
    opp = await app_client.post(
        OPPS,
        json={"company_id": company_id, "title": "Szansa ze spotkaniem"},
        headers=_headers(rep),
    )
    assert opp.status_code == 201, opp.text
    subject = f"Warsztat {company_id}"
    at_opportunity = await _meeting(
        app_client,
        rep,
        company_id,
        opportunity_id=opp.json()["id"],
        subject=subject,
        body="x" * 5000,
        occurred_at="2026-03-01T23:30:00+00:00",
    )
    at_company = await _meeting(
        app_client,
        rep,
        company_id,
        subject=f"Inne {company_id}",
        occurred_at="2026-03-01T10:00:00+00:00",
    )
    note = await app_client.post(
        ACTIVITIES,
        json={"kind": "note", "company_id": company_id, "subject": subject},
        headers=_headers(rep),
    )
    assert note.status_code == 201, note.text

    found = await _meetings(app_client, rep, q=str(company_id))
    assert [item["id"] for item in found["items"]] == [at_opportunity, at_company]
    assert found["total"] == 2
    assert len(found["items"][0]["body"]) == 300

    linked = await _meetings(app_client, rep, q=str(company_id), linked="opportunity")
    assert [item["id"] for item in linked["items"]] == [at_opportunity]
    company_only = await _meetings(app_client, rep, q=str(company_id), linked="company")
    assert [item["id"] for item in company_only["items"]] == [at_company]

    # 23:30 UTC 01.03 to już 02.03 w Warszawie.
    next_day = await _meetings(
        app_client, rep, q=str(company_id), date_from="2026-03-02", date_to="2026-03-02"
    )
    assert [item["id"] for item in next_day["items"]] == [at_opportunity]


@pytest.mark.asyncio
async def test_meetings_list_requires_sales_view(app_client) -> None:
    outsider = await _user()
    resp = await app_client.get(f"{ACTIVITIES}/meetings", headers=_headers(outsider))
    assert resp.status_code == 403
