"""Po co oddzwaniamy: powód przy przypomnieniu (zgłoszenie dzwoniących, 23.11.2026)."""

from __future__ import annotations

from datetime import timedelta

import pytest

from app.core.scheduling import business_today
from app.services.sales.calling_reasons import REASON_CHARS, excel_comment
from tests.test_sales_calling_queue import _campaign, _company, _queue, _record, _save
from tests.test_sales_companies_api import _headers, _user

URL = "/api/sales/calling"


async def _reminders(app_client, user) -> dict[int, dict]:
    resp = await app_client.get(f"{URL}/reminders", headers=_headers(user))
    assert resp.status_code == 200, resp.text
    return {item["record_id"]: item for item in resp.json()}


def test_excel_comment_is_the_comment_before_the_remarks() -> None:
    assert excel_comment(
        "Z Excela: Urlop. Przyszły tydzień · LinkedIn 24.10: potwierdzone"
    ) == ("Urlop. Przyszły tydzień")
    assert excel_comment("Z Excela:   oddzwoni  ") == "oddzwoni"
    assert excel_comment("Typ usługi: automatyzacje") is None
    assert excel_comment(None) is None
    assert excel_comment("Z Excela: ") is None
    long = excel_comment("Z Excela: " + "x" * (REASON_CHARS + 50))
    assert long is not None and len(long) == REASON_CHARS and long.endswith("…")


@pytest.mark.asyncio
async def test_reminder_and_queue_show_why_we_call_back(app_client) -> None:
    caller = await _user("sales_view", "sales_edit")
    campaign_id = await _campaign()
    today = business_today()
    later = await _record(caller.id, campaign_id, await _company())
    now = await _record(caller.id, campaign_id, await _company())

    resp = await _save(
        app_client,
        caller,
        later,
        outcome="call_back",
        callback_on=(today + timedelta(days=3)).isoformat(),
        note="  Prosi o telefon po urlopie:\n budżet na Q1 ",
    )
    assert resp.status_code == 200, resp.text
    resp = await _save(
        app_client,
        caller,
        now,
        outcome="offer_sent",
        callback_on=today.isoformat(),
        note="Sprawdzić, czy oferta doszła",
    )
    assert resp.status_code == 200, resp.text

    reminders = await _reminders(app_client, caller)
    reason = reminders[later]["callback_reason"]
    assert reason["text"] == "Prosi o telefon po urlopie: budżet na Q1"
    assert reason["author_name"] == caller.name
    assert reason["noted_on"] == today.isoformat()
    assert reason["from_excel"] is False

    queue = await _queue(app_client, caller)
    due = {item["record_id"]: item for item in queue["callbacks"]}
    assert due[now]["callback_reason"]["text"] == "Sprawdzić, czy oferta doszła"
    assert later not in due


@pytest.mark.asyncio
async def test_reason_belongs_to_the_latest_call_only(app_client) -> None:
    caller = await _user("sales_view", "sales_edit")
    campaign_id = await _campaign()
    day = (business_today() + timedelta(days=2)).isoformat()
    record_id = await _record(caller.id, campaign_id, await _company())

    for note in ("Zadzwonić po zarządzie", None):
        payload = {"outcome": "call_back", "callback_on": day}
        if note:
            payload["note"] = note
        resp = await _save(app_client, caller, record_id, **payload)
        assert resp.status_code == 200, resp.text

    # Drugi telefon bez notatki: stary powód mógł już nie obowiązywać.
    assert (await _reminders(app_client, caller))[record_id]["callback_reason"] is None


@pytest.mark.asyncio
async def test_excel_record_without_calls_takes_the_excel_comment(app_client) -> None:
    caller = await _user("sales_view", "sales_edit")
    campaign_id = await _campaign()
    today = business_today()
    from_excel = await _record(
        caller.id,
        campaign_id,
        await _company(),
        state="call_back",
        callback_on=today,
        note="Z Excela: Urlop / za tydzień kontakt · LinkedIn 24.10: potwierdzone",
    )
    plain = await _record(
        caller.id,
        campaign_id,
        await _company(),
        state="call_back",
        callback_on=today,
        note="Typ usługi: automatyzacje",
    )

    reminders = await _reminders(app_client, caller)
    reason = reminders[from_excel]["callback_reason"]
    assert reason["text"] == "Urlop / za tydzień kontakt"
    assert reason["author_name"] is None
    assert reason["from_excel"] is True
    assert reminders[plain]["callback_reason"] is None
