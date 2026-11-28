"""Akcje zbiorcze w Tabeli Dzwonienia (decyzja Artura 27.11.2026, wariant A).

Usuń z listy (miękko, z „Cofnij”), przypisz osobie, przenieś do kampanii. Usunięty rekord
znika z kolejki, Tabeli, Przypomnień i liczników kampanii, ale bramka importu dalej go
widzi, więc ta sama firma nie wraca z kolejną listą.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any

import pytest

from app.core.scheduling import business_today
from tests.test_sales_calling_import import SOURCE, _csv, _fates, _phone, _post
from tests.test_sales_calling_queue import (
    URL,
    _campaign,
    _company,
    _get_record,
    _queue,
    _record,
    _save,
)
from tests.test_sales_companies_api import _headers, _user


async def _bulk(app_client, user, **payload: Any):
    return await app_client.post(
        f"{URL}/records/bulk", json=payload, headers=_headers(user)
    )


async def _ok(app_client, user, **payload: Any) -> dict[str, Any]:
    resp = await _bulk(app_client, user, **payload)
    assert resp.status_code == 200, resp.text
    return resp.json()


async def _table_ids(app_client, user, **params: Any) -> set[int]:
    resp = await app_client.get(f"{URL}/records", params=params, headers=_headers(user))
    assert resp.status_code == 200, resp.text
    return {item["record_id"] for item in resp.json()["items"]}


def _queue_ids(queue: dict[str, Any]) -> set[int]:
    sections = ("callbacks", "no_answer", "meetings", "new")
    return {item["record_id"] for section in sections for item in queue[section]}


async def _campaign_counts(app_client, user, campaign_id: int) -> dict[str, int]:
    resp = await app_client.get(f"{URL}/campaigns", headers=_headers(user))
    assert resp.status_code == 200, resp.text
    [row] = [row for row in resp.json() if row["id"] == campaign_id]
    return row["counts"]


@pytest.mark.asyncio
async def test_remove_hides_everywhere_and_undo_brings_it_back(app_client) -> None:
    caller = await _user("sales_view", "sales_edit")
    campaign_id = await _campaign()
    fresh = await _record(caller.id, campaign_id, await _company())
    later = await _record(
        caller.id,
        campaign_id,
        await _company(),
        state="call_back",
        callback_on=business_today() + timedelta(days=7),
    )
    kept = await _record(caller.id, campaign_id, await _company())

    body = await _ok(app_client, caller, action="remove", record_ids=[fresh, later])
    assert sorted(body["done"]) == sorted([fresh, later]) and body["skipped"] == {}

    queue = await _queue(app_client, caller, campaign_id=campaign_id)
    assert _queue_ids(queue) == {kept} and queue["counts"]["new"] == 1
    assert await _table_ids(app_client, caller, campaign_id=campaign_id) == {kept}
    reminders = await app_client.get(f"{URL}/reminders", headers=_headers(caller))
    assert later not in {item["record_id"] for item in reminders.json()}
    assert await _campaign_counts(app_client, caller, campaign_id) == {"new": 1}
    # Rekord jest w bazie i nie przyjmuje wyniku, dopóki ktoś go nie przywróci.
    removed = await _get_record(fresh)
    assert removed.removed_at is not None and removed.removed_by_user_id == caller.id
    assert (
        await _save(app_client, caller, fresh, outcome="no_answer")
    ).status_code == 404

    body = await _ok(app_client, caller, action="restore", record_ids=body["done"])
    assert sorted(body["done"]) == sorted([fresh, later])
    assert await _table_ids(app_client, caller, campaign_id=campaign_id) == {
        fresh,
        later,
        kept,
    }
    assert (await _get_record(fresh)).removed_at is None


@pytest.mark.asyncio
async def test_booked_meeting_is_not_removed_nor_moved_but_can_be_assigned(
    app_client,
) -> None:
    caller = await _user("sales_view", "sales_edit")
    other = await _user("sales_view", "sales_edit")
    campaign_id = await _campaign()
    target_id = await _campaign()
    booked = await _record(
        caller.id, campaign_id, await _company(), state="meeting_booked"
    )

    for action, extra in (("remove", {}), ("move", {"campaign_id": target_id})):
        body = await _ok(
            app_client, caller, action=action, record_ids=[booked], **extra
        )
        assert body == {"done": [], "skipped": {"meeting_booked": 1}}
    assert (await _get_record(booked)).removed_at is None

    body = await _ok(
        app_client,
        caller,
        action="assign",
        record_ids=[booked],
        assignee_user_id=other.id,
    )
    assert body["done"] == [booked]
    assert (await _get_record(booked)).assigned_user_id == other.id


@pytest.mark.asyncio
async def test_move_counts_first_and_keeps_companies_already_in_target(
    app_client,
) -> None:
    caller = await _user("sales_view", "sales_edit")
    source_id = await _campaign()
    target_id = await _campaign()
    shared = await _company()
    twice = await _company()
    moving = await _record(caller.id, source_id, await _company())
    blocked = await _record(caller.id, source_id, shared)
    await _record(caller.id, target_id, shared)
    first = await _record(caller.id, source_id, twice)
    second = await _record(caller.id, source_id, twice)
    ids = [moving, blocked, first, second]

    preview = await _ok(
        app_client,
        caller,
        action="move",
        record_ids=ids,
        campaign_id=target_id,
        dry_run=True,
    )
    assert sorted(preview["done"]) == sorted([moving, first])
    assert preview["skipped"] == {"already_in_campaign": 2}
    # Podgląd niczego nie zapisuje.
    assert (await _get_record(moving)).campaign_id == source_id

    body = await _ok(
        app_client, caller, action="move", record_ids=ids, campaign_id=target_id
    )
    assert body == preview
    assert (await _get_record(moving)).campaign_id == target_id
    assert (await _get_record(blocked)).campaign_id == source_id
    assert (await _get_record(second)).campaign_id == source_id

    same = await _ok(
        app_client, caller, action="move", record_ids=[moving], campaign_id=target_id
    )
    assert same == {"done": [], "skipped": {"already_in_campaign": 1}}


@pytest.mark.asyncio
async def test_move_and_assign_refuse_bad_targets(app_client) -> None:
    caller = await _user("sales_view", "sales_edit")
    viewer = await _user("sales_view")
    record_id = await _record(caller.id, await _campaign(), await _company())

    assert (
        await _bulk(app_client, caller, action="move", record_ids=[record_id])
    ).status_code == 422
    assert (
        await _bulk(
            app_client,
            caller,
            action="move",
            record_ids=[record_id],
            campaign_id=999999,
        )
    ).status_code == 422
    assert (
        await _bulk(app_client, caller, action="assign", record_ids=[record_id])
    ).status_code == 422
    # Osoba bez „Sprzedaż: edycja” nie dostaje rekordów do dzwonienia.
    assert (
        await _bulk(
            app_client,
            caller,
            action="assign",
            record_ids=[record_id],
            assignee_user_id=viewer.id,
        )
    ).status_code == 422
    assert (await _get_record(record_id)).assigned_user_id == caller.id


@pytest.mark.asyncio
async def test_bulk_needs_sales_edit_and_skips_records_off_the_list(app_client) -> None:
    caller = await _user("sales_view", "sales_edit")
    viewer = await _user("sales_view")
    campaign_id = await _campaign()
    record_id = await _record(caller.id, campaign_id, await _company())
    objection = await _record(
        caller.id, campaign_id, await _company(), state="do_not_contact"
    )
    without_campaign = await _record(caller.id, None, await _company())

    resp = await _bulk(app_client, viewer, action="remove", record_ids=[record_id])
    assert resp.status_code == 403
    resp = await app_client.get(f"{URL}/record-ids", headers=_headers(viewer))
    assert resp.status_code == 403

    body = await _ok(
        app_client,
        caller,
        action="remove",
        record_ids=[record_id, objection, without_campaign, 999999999],
    )
    assert body == {"done": [record_id], "skipped": {"not_on_list": 3}}
    assert (await _get_record(objection)).removed_at is None


@pytest.mark.asyncio
async def test_select_all_from_filter_returns_table_ids_without_removed(
    app_client,
) -> None:
    caller = await _user("sales_view", "sales_edit")
    campaign_id = await _campaign()
    first = await _record(caller.id, campaign_id, await _company())
    offered = await _record(
        caller.id, campaign_id, await _company(), state="offer_sent"
    )
    gone = await _record(caller.id, campaign_id, await _company())
    await _ok(app_client, caller, action="remove", record_ids=[gone])

    resp = await app_client.get(
        f"{URL}/record-ids",
        params={"campaign_id": campaign_id},
        headers=_headers(caller),
    )
    assert resp.status_code == 200, resp.text
    assert set(resp.json()["ids"]) == {first, offered}
    assert resp.json()["truncated"] is False
    only_offers = await app_client.get(
        f"{URL}/record-ids",
        params={"campaign_id": campaign_id, "state": "offer_sent"},
        headers=_headers(caller),
    )
    assert only_offers.json()["ids"] == [offered]


@pytest.mark.asyncio
async def test_import_does_not_bring_a_removed_company_back(app_client) -> None:
    caller = await _user("sales_view", "sales_edit")
    campaign_id = await _campaign()
    phone = _phone()
    payload = _csv(f"Usunięta Firma {phone};Jan Lista;CTO;{phone};;")
    _, fates = await _fates(app_client, caller, campaign_id, payload, source=SOURCE)
    assert fates[0][0] == "new_company"
    resp = await _post(app_client, caller, campaign_id, payload, preview=False)
    assert resp.status_code == 200 and resp.json()["added"] == 1, resp.text
    [record_id] = await _table_ids(app_client, caller, campaign_id=campaign_id)
    await _ok(app_client, caller, action="remove", record_ids=[record_id])

    _, fates = await _fates(app_client, caller, campaign_id, payload, source=SOURCE)
    assert fates[0][0] == "already_in_campaign"
    assert await _table_ids(app_client, caller, campaign_id=campaign_id) == set()
