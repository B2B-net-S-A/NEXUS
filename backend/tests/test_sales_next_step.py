"""Krok szansy, ostatni kontakt, zapis rozmowy i wspólna oś firmy i szansy.

Baza testowa jest wspólna dla przebiegu, więc testy patrzą tylko na własne szanse.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

import pytest
from sqlalchemy import select, text

from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.core.scheduling import business_today, local_day_bounds, local_now
from app.models.sales import (
    SalesActivity,
    SalesCompanyContact,
    SalesContact,
    SalesOpportunity,
    SalesPipeline,
    SalesPipelineStage,
)
from app.services.sales.decision_map import with_entries
from tests.test_sales_companies_api import _headers, _user

COMPANIES = "/api/sales/companies"
URL = "/api/sales/opportunities"
TIMELINE = "/api/sales/activities/timeline"


async def _company(app_client: Any, user: Any) -> int:
    resp = await app_client.post(
        COMPANIES,
        json={"name": f"Krok Firma {uuid.uuid4().hex[:10]}"},
        headers=_headers(user),
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


async def _opportunity(
    app_client: Any,
    user: Any,
    company_id: Optional[int] = None,
    pipeline_id: Optional[int] = None,
) -> tuple[int, int]:
    company_id = company_id or await _company(app_client, user)
    resp = await app_client.post(
        URL,
        json={
            "company_id": company_id,
            "title": "Zespół analityków",
            "pipeline_id": pipeline_id,
        },
        headers=_headers(user),
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"], company_id


async def _activity(**fields: Any) -> int:
    async with AsyncSessionLocal() as db:
        activity = SalesActivity(**fields)
        db.add(activity)
        await db.commit()
        return activity.id


async def _get(app_client: Any, user: Any, opportunity_id: int) -> dict[str, Any]:
    resp = await app_client.get(f"{URL}/{opportunity_id}", headers=_headers(user))
    assert resp.status_code == 200, resp.text
    return resp.json()


async def _listed(
    app_client: Any, user: Any, company_id: int, opportunity_id: int
) -> dict[str, Any]:
    resp = await app_client.get(
        URL, params={"company_id": company_id}, headers=_headers(user)
    )
    assert resp.status_code == 200, resp.text
    return next(i for i in resp.json()["items"] if i["id"] == opportunity_id)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _day_start() -> datetime:
    return local_day_bounds(local_now()).start_utc


# ── Definicja kroku ──────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_future_task_is_the_step_in_list_and_card(app_client) -> None:
    rep = await _user("sales_edit")
    opp, company = await _opportunity(app_client, rep)
    due = _now() + timedelta(days=3)
    await _activity(
        kind="task",
        subject="Wysłać ofertę",
        company_id=company,
        opportunity_id=opp,
        due_at=due,
    )
    for body in (
        await _get(app_client, rep, opp),
        await _listed(app_client, rep, company, opp),
    ):
        assert body["next_step"]["kind"] == "task"
        assert body["next_step"]["subject"] == "Wysłać ofertę"
        assert datetime.fromisoformat(body["next_step"]["at"]) == due
        assert body["overdue_step"] is None


@pytest.mark.asyncio
async def test_task_due_earlier_today_is_still_a_step(app_client) -> None:
    rep = await _user("sales_edit")
    opp, company = await _opportunity(app_client, rep)
    await _activity(
        kind="task",
        subject="Dziś",
        company_id=company,
        opportunity_id=opp,
        due_at=_day_start() + timedelta(minutes=1),
    )
    body = await _get(app_client, rep, opp)
    assert body["next_step"]["subject"] == "Dziś"
    assert body["overdue_step"] is None


@pytest.mark.asyncio
async def test_imported_call_without_due_date_is_not_a_step(app_client) -> None:
    rep = await _user("sales_edit")
    opp, company = await _opportunity(app_client, rep)
    await _activity(
        kind="call",
        subject="Rozmowa",
        company_id=company,
        opportunity_id=opp,
        occurred_at=_now() - timedelta(days=2),
        external_source="atlas",
    )
    body = await _get(app_client, rep, opp)
    assert body["next_step"] is None
    assert body["overdue_step"] is None
    assert body["last_contact"]["kind"] == "call"


@pytest.mark.asyncio
async def test_task_without_due_date_is_not_a_step(app_client) -> None:
    rep = await _user("sales_edit")
    opp, company = await _opportunity(app_client, rep)
    await _activity(
        kind="task", subject="Kiedyś", company_id=company, opportunity_id=opp
    )
    assert (await _get(app_client, rep, opp))["next_step"] is None


@pytest.mark.asyncio
async def test_done_task_is_not_a_step(app_client) -> None:
    rep = await _user("sales_edit")
    opp, company = await _opportunity(app_client, rep)
    await _activity(
        kind="task",
        subject="Zrobione",
        company_id=company,
        opportunity_id=opp,
        due_at=_now() + timedelta(days=1),
        done_at=_now(),
    )
    assert (await _get(app_client, rep, opp))["next_step"] is None


@pytest.mark.asyncio
async def test_overdue_is_reported_apart_from_the_step(app_client) -> None:
    rep = await _user("sales_edit")
    opp, company = await _opportunity(app_client, rep)
    due = _day_start() - timedelta(days=30)
    await _activity(
        kind="call",
        subject="Oddzwonić",
        company_id=company,
        opportunity_id=opp,
        due_at=due,
    )
    body = await _get(app_client, rep, opp)
    assert body["next_step"] is None
    assert body["overdue_step"]["subject"] == "Oddzwonić"
    assert datetime.fromisoformat(body["overdue_step"]["at"]) == due


@pytest.mark.asyncio
async def test_company_meeting_is_a_step_unless_cancelled(app_client) -> None:
    rep = await _user("sales_edit")
    opp, company = await _opportunity(app_client, rep)
    at = _now() + timedelta(days=4)
    await _activity(
        kind="meeting",
        subject="Anulowano: przegląd",
        company_id=company,
        occurred_at=at - timedelta(days=2),
    )
    assert (await _get(app_client, rep, opp))["next_step"] is None
    await _activity(
        kind="meeting", subject="Przegląd", company_id=company, occurred_at=at
    )
    body = await _get(app_client, rep, opp)
    assert body["next_step"]["kind"] == "meeting"
    assert body["next_step"]["subject"] == "Przegląd"


@pytest.mark.asyncio
async def test_the_earliest_step_wins(app_client) -> None:
    rep = await _user("sales_edit")
    opp, company = await _opportunity(app_client, rep)
    await _activity(
        kind="task",
        subject="Później",
        company_id=company,
        opportunity_id=opp,
        due_at=_now() + timedelta(days=9),
    )
    await _activity(
        kind="meeting",
        subject="Wcześniej",
        company_id=company,
        occurred_at=_now() + timedelta(days=2),
    )
    assert (await _get(app_client, rep, opp))["next_step"]["subject"] == "Wcześniej"


@pytest.mark.asyncio
async def test_task_of_another_opportunity_does_not_count(app_client) -> None:
    rep = await _user("sales_edit")
    opp, company = await _opportunity(app_client, rep)
    other, _ = await _opportunity(app_client, rep, company_id=company)
    await _activity(
        kind="task",
        subject="Cudze",
        company_id=company,
        opportunity_id=other,
        due_at=_now() + timedelta(days=1),
    )
    await _activity(
        kind="task",
        subject="Cudze zaległe",
        company_id=company,
        opportunity_id=other,
        due_at=_day_start() - timedelta(days=5),
    )
    body = await _get(app_client, rep, opp)
    assert body["next_step"] is None
    assert body["overdue_step"] is None


@pytest.mark.asyncio
async def test_company_level_task_counts_for_each_opportunity(app_client) -> None:
    rep = await _user("sales_edit")
    opp, company = await _opportunity(app_client, rep)
    await _activity(
        kind="task",
        subject="Firmowe",
        company_id=company,
        due_at=_now() + timedelta(days=1),
    )
    assert (await _get(app_client, rep, opp))["next_step"]["subject"] == "Firmowe"


# ── Ostatni kontakt ──────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_last_contact_has_kind_direction_and_date(app_client) -> None:
    rep = await _user("sales_edit")
    opp, company = await _opportunity(app_client, rep)
    at = _now() - timedelta(days=3)
    await _activity(
        kind="email",
        subject="Stary",
        company_id=company,
        direction="out",
        occurred_at=at - timedelta(days=9),
    )
    await _activity(
        kind="email",
        subject="Nowy",
        company_id=company,
        direction="in",
        occurred_at=at,
    )
    body = await _get(app_client, rep, opp)
    assert body["last_contact"]["kind"] == "email"
    assert body["last_contact"]["direction"] == "in"
    assert datetime.fromisoformat(body["last_contact"]["at"]) == at
    assert body["waiting_for_reply"] is True


@pytest.mark.asyncio
async def test_intent_and_system_notes_are_not_a_contact(app_client) -> None:
    rep = await _user("sales_edit")
    opp, company = await _opportunity(app_client, rep)
    await _activity(
        kind="meeting",
        subject="Przyszłe",
        company_id=company,
        occurred_at=_now() + timedelta(days=2),
    )
    await _activity(
        kind="task",
        subject="Otwarte",
        company_id=company,
        opportunity_id=opp,
        due_at=_now() + timedelta(days=2),
    )
    await _activity(
        kind="note",
        body="This deal was converted to a lead. All notes moved.",
        company_id=company,
        external_source="pipedrive_note",
        occurred_at=_now() - timedelta(days=1),
    )
    assert (await _get(app_client, rep, opp))["last_contact"] is None


@pytest.mark.asyncio
async def test_waiting_for_reply_needs_no_step(app_client) -> None:
    rep = await _user("sales_edit")
    opp, company = await _opportunity(app_client, rep)
    await _activity(
        kind="email",
        subject="Pytanie klienta",
        company_id=company,
        direction="in",
        occurred_at=_now() - timedelta(days=1),
    )
    await _activity(
        kind="task",
        subject="Odpisać",
        company_id=company,
        opportunity_id=opp,
        due_at=_now() + timedelta(days=1),
    )
    assert (await _get(app_client, rep, opp))["waiting_for_reply"] is False


# ── Czerwień tylko po wdrożeniu i tylko w lejku Sprzedaż ─────────────────


async def _backdate(opportunity_id: int) -> None:
    async with AsyncSessionLocal() as db:
        await db.execute(
            text(
                "UPDATE sales_opportunities SET created_at = now() - interval '200 days' "
                "WHERE id = :id"
            ),
            {"id": opportunity_id},
        )
        await db.execute(
            text("DELETE FROM sales_opportunity_events WHERE opportunity_id = :id"),
            {"id": opportunity_id},
        )
        await db.commit()


@pytest.mark.asyncio
async def test_alarm_only_after_rollout(app_client, monkeypatch) -> None:
    rep = await _user("sales_edit")
    monkeypatch.setattr(
        settings, "SALES_STEP_RULES_SINCE", business_today() - timedelta(days=10)
    )
    fresh, _ = await _opportunity(app_client, rep)
    old, company = await _opportunity(app_client, rep)
    await _backdate(old)
    assert (await _get(app_client, rep, fresh))["step_alarm"] is True
    assert (await _get(app_client, rep, old))["step_alarm"] is False

    await _activity(
        kind="note",
        body="Ruch na szansie",
        company_id=company,
        opportunity_id=old,
        occurred_at=_now(),
    )
    assert (await _get(app_client, rep, old))["step_alarm"] is True


@pytest.mark.asyncio
async def test_company_mail_does_not_wake_an_old_opportunity(
    app_client, monkeypatch
) -> None:
    rep = await _user("sales_edit")
    monkeypatch.setattr(
        settings, "SALES_STEP_RULES_SINCE", business_today() - timedelta(days=10)
    )
    old, company = await _opportunity(app_client, rep)
    await _backdate(old)
    await _activity(
        kind="email",
        subject="Do firmy",
        company_id=company,
        direction="out",
        occurred_at=_now(),
    )
    assert (await _get(app_client, rep, old))["step_alarm"] is False


@pytest.mark.asyncio
async def test_no_alarm_before_the_date_or_with_a_step(app_client, monkeypatch) -> None:
    rep = await _user("sales_edit")
    monkeypatch.setattr(
        settings, "SALES_STEP_RULES_SINCE", business_today() + timedelta(days=10)
    )
    opp, company = await _opportunity(app_client, rep)
    assert (await _get(app_client, rep, opp))["step_alarm"] is False

    monkeypatch.setattr(
        settings, "SALES_STEP_RULES_SINCE", business_today() - timedelta(days=10)
    )
    await _activity(
        kind="task",
        subject="Krok",
        company_id=company,
        opportunity_id=opp,
        due_at=_now() + timedelta(days=1),
    )
    assert (await _get(app_client, rep, opp))["step_alarm"] is False


@pytest.mark.asyncio
async def test_no_alarm_outside_the_sales_pipeline(app_client, monkeypatch) -> None:
    rep = await _user("sales_edit")
    monkeypatch.setattr(
        settings, "SALES_STEP_RULES_SINCE", business_today() - timedelta(days=10)
    )
    key = f"inny-{uuid.uuid4().hex[:8]}"
    async with AsyncSessionLocal() as db:
        pipeline = SalesPipeline(key=key, name=key)
        db.add(pipeline)
        await db.flush()
        db.add(
            SalesPipelineStage(
                pipeline_id=pipeline.id,
                key=f"{key}-a",
                name="Pierwszy",
                position=1,
                probability=10,
                outcome="open",
            )
        )
        await db.commit()
        pipeline_id = pipeline.id
    opp, _ = await _opportunity(app_client, rep, pipeline_id=pipeline_id)
    assert (await _get(app_client, rep, opp))["step_alarm"] is False


# ── Zapis rozmowy ────────────────────────────────────────────────────────


async def _contact(company_id: Optional[int], name: str = "Jan Testowy") -> int:
    async with AsyncSessionLocal() as db:
        contact = SalesContact(company_id=company_id, full_name=name, phone="500100200")
        db.add(contact)
        await db.commit()
        return contact.id


async def _set_map(opportunity_id: int, entries: list[dict[str, Any]]) -> None:
    async with AsyncSessionLocal() as db:
        opp = await db.get(SalesOpportunity, opportunity_id)
        opp.custom_fields = with_entries(
            opp.custom_fields, entries, user_id=None, now=_now()
        )
        await db.commit()


async def _call_row(opportunity_id: int) -> Any:
    async with AsyncSessionLocal() as db:
        return (
            await db.execute(
                text(
                    "SELECT kind, outcome, subject, body, contact_id, direction, "
                    "done_at, occurred_at FROM sales_activities "
                    "WHERE opportunity_id = :id AND kind = 'call' ORDER BY id DESC"
                ),
                {"id": opportunity_id},
            )
        ).first()


@pytest.mark.parametrize(
    ("outcome", "label"),
    [
        ("connected", "Dodzwoniłem"),
        ("no_answer", "Brak odpowiedzi"),
        ("call_back", "Oddzwonić"),
        ("wants_offer", "Prosi o ofertę"),
        ("not_now", "Nie teraz"),
    ],
)
@pytest.mark.asyncio
async def test_each_outcome_is_saved_on_the_activity(
    app_client, outcome: str, label: str
) -> None:
    rep = await _user("sales_edit")
    opp, company = await _opportunity(app_client, rep)
    contact = await _contact(company)
    resp = await app_client.post(
        f"{URL}/{opp}/calls",
        json={"outcome": outcome, "contact_id": contact, "note": " Ustalone. "},
        headers=_headers(rep),
    )
    assert resp.status_code == 201, resp.text
    row = await _call_row(opp)
    assert row.outcome == outcome
    assert row.subject == f"{label}: Jan Testowy"
    assert row.body == "Ustalone."
    assert row.contact_id == contact
    assert row.direction == "out"
    assert row.done_at is not None and row.occurred_at is not None
    body = resp.json()
    assert body["last_contact"]["kind"] == "call"
    assert body["next_step"] is None


@pytest.mark.asyncio
async def test_call_without_a_person_is_allowed(app_client) -> None:
    rep = await _user("sales_edit")
    opp, _ = await _opportunity(app_client, rep)
    resp = await app_client.post(
        f"{URL}/{opp}/calls", json={"outcome": "no_answer"}, headers=_headers(rep)
    )
    assert resp.status_code == 201, resp.text
    assert (await _call_row(opp)).subject == "Brak odpowiedzi"


@pytest.mark.asyncio
async def test_logging_needs_edit_permission(app_client) -> None:
    rep = await _user("sales_edit")
    viewer = await _user("sales_view")
    opp, _ = await _opportunity(app_client, rep)
    resp = await app_client.post(
        f"{URL}/{opp}/calls", json={"outcome": "no_answer"}, headers=_headers(viewer)
    )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_unknown_outcome_is_refused(app_client) -> None:
    rep = await _user("sales_edit")
    opp, _ = await _opportunity(app_client, rep)
    resp = await app_client.post(
        f"{URL}/{opp}/calls", json={"outcome": "maybe"}, headers=_headers(rep)
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_missing_opportunity_is_404(app_client) -> None:
    rep = await _user("sales_edit")
    resp = await app_client.post(
        f"{URL}/999999999/calls", json={"outcome": "no_answer"}, headers=_headers(rep)
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_contact_of_another_company_is_refused(app_client) -> None:
    rep = await _user("sales_edit")
    opp, _ = await _opportunity(app_client, rep)
    stranger = await _contact(await _company(app_client, rep))
    resp = await app_client.post(
        f"{URL}/{opp}/calls",
        json={"outcome": "connected", "contact_id": stranger},
        headers=_headers(rep),
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_contact_linked_to_the_company_is_accepted(app_client) -> None:
    rep = await _user("sales_edit")
    opp, company = await _opportunity(app_client, rep)
    contact = await _contact(None)
    async with AsyncSessionLocal() as db:
        db.add(SalesCompanyContact(company_id=company, contact_id=contact))
        await db.commit()
    resp = await app_client.post(
        f"{URL}/{opp}/calls",
        json={"outcome": "connected", "contact_id": contact},
        headers=_headers(rep),
    )
    assert resp.status_code == 201, resp.text


@pytest.mark.asyncio
async def test_two_targets_are_refused(app_client) -> None:
    rep = await _user("sales_edit")
    opp, company = await _opportunity(app_client, rep)
    contact = await _contact(company)
    resp = await app_client.post(
        f"{URL}/{opp}/calls",
        json={"outcome": "connected", "contact_id": contact, "person_key": "abc"},
        headers=_headers(rep),
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_objection_is_saved_on_the_contact_without_a_step(app_client) -> None:
    rep = await _user("sales_edit")
    opp, company = await _opportunity(app_client, rep)
    contact = await _contact(company)
    resp = await app_client.post(
        f"{URL}/{opp}/calls",
        json={"outcome": "do_not_contact", "contact_id": contact},
        headers=_headers(rep),
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["next_step"] is None
    assert (await _call_row(opp)).outcome == "do_not_contact"
    async with AsyncSessionLocal() as db:
        row = (
            await db.execute(
                text(
                    "SELECT do_not_contact_at, do_not_contact_by_user_id "
                    "FROM sales_contacts WHERE id = :id"
                ),
                {"id": contact},
            )
        ).first()
    assert row.do_not_contact_at is not None
    assert row.do_not_contact_by_user_id == rep.id
    open_tasks = await _open_items(opp)
    assert open_tasks == 0
    history = await app_client.get(f"{URL}/{opp}/history", headers=_headers(rep))
    assert any(e["field"] == "do_not_contact" for e in history.json())


async def _open_items(opportunity_id: int) -> int:
    async with AsyncSessionLocal() as db:
        rows = await db.scalars(
            select(SalesActivity.id).where(
                SalesActivity.opportunity_id == opportunity_id,
                SalesActivity.kind == "task",
                SalesActivity.done_at.is_(None),
            )
        )
        return len(list(rows))


@pytest.mark.asyncio
async def test_objection_needs_a_person(app_client) -> None:
    rep = await _user("sales_edit")
    opp, _ = await _opportunity(app_client, rep)
    resp = await app_client.post(
        f"{URL}/{opp}/calls", json={"outcome": "do_not_contact"}, headers=_headers(rep)
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_objecting_person_cannot_get_another_call_logged(app_client) -> None:
    rep = await _user("sales_edit")
    opp, company = await _opportunity(app_client, rep)
    contact = await _contact(company)
    url = f"{URL}/{opp}/calls"
    await app_client.post(
        url,
        json={"outcome": "do_not_contact", "contact_id": contact},
        headers=_headers(rep),
    )
    resp = await app_client.post(
        url, json={"outcome": "connected", "contact_id": contact}, headers=_headers(rep)
    )
    assert resp.status_code == 409
    assert "sprzeciw" in resp.json()["detail"].lower()


@pytest.mark.asyncio
async def test_objection_shows_on_contact_opportunity_and_map(app_client) -> None:
    rep = await _user("sales_edit")
    opp, company = await _opportunity(app_client, rep)
    contact = await _contact(company, "Anna Mapowa")
    await app_client.put(
        f"{URL}/{opp}/contacts/{contact}", json={}, headers=_headers(rep)
    )
    await _set_map(opp, [{"name": "Anna Mapowa", "phone": "600700800"}])
    key = (await _get(app_client, rep, opp))["atlas_motion"]["it_factory"][
        "decision_map"
    ][0]["key"]
    assert (
        await app_client.post(
            f"{URL}/{opp}/calls",
            json={"outcome": "do_not_contact", "person_key": key},
            headers=_headers(rep),
        )
    ).status_code == 201
    body = await _get(app_client, rep, opp)
    assert body["contacts"][0]["do_not_contact_at"] is not None
    assert body["atlas_motion"]["it_factory"]["decision_map"][0]["do_not_contact"]
    listed = await app_client.get(
        "/api/sales/contacts", params={"company_id": company}, headers=_headers(rep)
    )
    item = next(i for i in listed.json()["items"] if i["id"] == contact)
    assert item["do_not_contact_at"] is not None


@pytest.mark.asyncio
async def test_map_person_without_contact_keeps_the_objection_on_the_map(
    app_client,
) -> None:
    rep = await _user("sales_edit")
    opp, _ = await _opportunity(app_client, rep)
    await _set_map(opp, [{"name": "Spoza Kontaktów", "phone": "600700801"}])
    key = (await _get(app_client, rep, opp))["atlas_motion"]["it_factory"][
        "decision_map"
    ][0]["key"]
    assert (
        await app_client.post(
            f"{URL}/{opp}/calls",
            json={"outcome": "do_not_contact", "person_key": key},
            headers=_headers(rep),
        )
    ).status_code == 201
    entry = (await _get(app_client, rep, opp))["atlas_motion"]["it_factory"][
        "decision_map"
    ][0]
    assert entry["do_not_contact"] is True
    assert entry["nexus_contact_id"] is None
    row = await _call_row(opp)
    assert row.subject == "Nie kontaktować: Spoza Kontaktów"
    # Numer zostaje w danych, przestaje być klikalny na ekranie.
    assert entry["phone"] == "600700801"
    retry = await app_client.post(
        f"{URL}/{opp}/calls",
        json={"outcome": "connected", "person_key": entry["key"]},
        headers=_headers(rep),
    )
    assert retry.status_code == 409


@pytest.mark.asyncio
async def test_stale_map_key_is_refused(app_client) -> None:
    rep = await _user("sales_edit")
    opp, _ = await _opportunity(app_client, rep)
    await _set_map(opp, [{"name": "Ktoś"}])
    resp = await app_client.post(
        f"{URL}/{opp}/calls",
        json={"outcome": "connected", "person_key": "0000000000000000"},
        headers=_headers(rep),
    )
    assert resp.status_code == 409


# ── Wspólna oś ───────────────────────────────────────────────────────────


async def _timeline(app_client: Any, user: Any, opportunity_id: int) -> dict[str, Any]:
    resp = await app_client.get(
        TIMELINE, params={"opportunity_id": opportunity_id}, headers=_headers(user)
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


@pytest.mark.asyncio
async def test_timeline_labels_where_each_entry_comes_from(app_client) -> None:
    rep = await _user("sales_edit")
    opp, company = await _opportunity(app_client, rep)
    other, _ = await _opportunity(app_client, rep, company_id=company)
    base = _now() - timedelta(days=10)
    here = await _activity(
        kind="note",
        body="Treść przy tej szansie, całkiem inna od pozostałych wpisów.",
        company_id=company,
        opportunity_id=opp,
        occurred_at=base,
    )
    firm = await _activity(
        kind="note",
        body="Notatka o firmie, nie o żadnej konkretnej szansie sprzedaży.",
        company_id=company,
        occurred_at=base - timedelta(days=1),
    )
    foreign = await _activity(
        kind="note",
        body="Notatka przy drugiej szansie tej samej firmy, inna treść.",
        company_id=company,
        opportunity_id=other,
        occurred_at=base - timedelta(days=2),
    )
    data = await _timeline(app_client, rep, opp)
    by_id = {item["id"]: item for item in data["items"]}
    assert by_id[here]["scope"] == "opportunity"
    assert by_id[firm]["scope"] == "company"
    assert by_id[foreign]["scope"] == "other_opportunity"
    assert by_id[foreign]["opportunity"]["id"] == other
    assert data["counts"] == {
        "all": 3,
        "opportunity": 1,
        "company": 1,
        "other_opportunity": 1,
    }


@pytest.mark.asyncio
async def test_timeline_hides_pipedrive_system_entries(app_client) -> None:
    rep = await _user("sales_edit")
    opp, company = await _opportunity(app_client, rep)
    await _activity(
        kind="note",
        body="This deal was converted to a lead. All notes, activities moved.",
        company_id=company,
        external_source="pipedrive_note",
        occurred_at=_now() - timedelta(days=1),
    )
    await _activity(
        kind="note",
        body="Firma X visited the website on: 2025-04-01",
        company_id=company,
        external_source="pipedrive_note",
        occurred_at=_now() - timedelta(days=2),
    )
    human = await _activity(
        kind="note",
        body="This deal was converted to a lead, ale to pisał człowiek w NEXUSIE.",
        company_id=company,
        occurred_at=_now() - timedelta(days=3),
    )
    data = await _timeline(app_client, rep, opp)
    assert [item["id"] for item in data["items"]] == [human]


@pytest.mark.asyncio
async def test_one_meeting_from_two_sources_is_one_row(app_client) -> None:
    rep = await _user("sales_edit")
    opp, company = await _opportunity(app_client, rep)
    at = _now() - timedelta(days=4)
    await _activity(
        kind="meeting",
        subject="Synchro",
        company_id=company,
        external_source="msgraph-event",
        occurred_at=at,
        web_link="https://outlook.example.com/1",
    )
    await _activity(
        kind="meeting",
        subject="Synchro",
        body="Transkrypcja",
        company_id=company,
        opportunity_id=opp,
        external_source="fireflies",
        occurred_at=at + timedelta(minutes=5),
    )
    await _activity(
        kind="note",
        body="📝 **Podsumowanie spotkania (Fireflies.ai)** Ustaliliśmy zakres.",
        company_id=company,
        opportunity_id=opp,
        external_source="atlas",
        occurred_at=at + timedelta(minutes=30),
    )
    data = await _timeline(app_client, rep, opp)
    assert len(data["items"]) == 1
    row = data["items"][0]
    assert row["kind"] == "meeting"
    assert row["scope"] == "opportunity"
    assert set(row["sources"]) == {"msgraph-event", "fireflies", "atlas"}
    assert row["web_link"] == "https://outlook.example.com/1"
    assert "Transkrypcja" in row["body"] and "Ustaliliśmy zakres" in row["body"]


@pytest.mark.asyncio
async def test_meetings_an_hour_apart_stay_separate(app_client) -> None:
    rep = await _user("sales_edit")
    opp, company = await _opportunity(app_client, rep)
    at = _now() - timedelta(days=4)
    await _activity(kind="meeting", subject="A", company_id=company, occurred_at=at)
    await _activity(
        kind="meeting",
        subject="B",
        company_id=company,
        occurred_at=at + timedelta(hours=1),
    )
    assert len((await _timeline(app_client, rep, opp))["items"]) == 2


@pytest.mark.asyncio
async def test_note_copied_from_a_mail_is_one_row(app_client) -> None:
    rep = await _user("sales_edit")
    opp, company = await _opportunity(app_client, rep)
    text_ = (
        "Dzień dobry, dotarła do mnie informacja o zmianie osoby kontaktowej w firmie."
    )
    at = _now() - timedelta(days=4)
    mail = await _activity(
        kind="email",
        subject="ODP: Nowy opiekun",
        body=text_,
        direction="out",
        company_id=company,
        external_source="msgraph-mail",
        occurred_at=at,
    )
    await _activity(
        kind="note",
        body=text_,
        company_id=company,
        opportunity_id=opp,
        external_source="atlas",
        occurred_at=at + timedelta(minutes=4),
    )
    data = await _timeline(app_client, rep, opp)
    assert [item["id"] for item in data["items"]] == [mail]
    assert data["items"][0]["scope"] == "opportunity"


@pytest.mark.asyncio
async def test_open_task_is_never_merged_away(app_client) -> None:
    rep = await _user("sales_edit")
    opp, company = await _opportunity(app_client, rep)
    text_ = (
        "Szanowny Panie, proszę o potwierdzenie terminu spotkania w przyszłym tygodniu."
    )
    at = _now() - timedelta(days=1)
    await _activity(
        kind="email",
        subject="Termin",
        body=text_,
        direction="out",
        company_id=company,
        occurred_at=at,
    )
    task = await _activity(
        kind="task",
        subject="Termin",
        body=text_,
        company_id=company,
        opportunity_id=opp,
        due_at=_now() + timedelta(days=2),
    )
    ids = [item["id"] for item in (await _timeline(app_client, rep, opp))["items"]]
    assert task in ids and len(ids) == 2


@pytest.mark.asyncio
async def test_two_mails_of_one_thread_stay_separate(app_client) -> None:
    rep = await _user("sales_edit")
    opp, company = await _opportunity(app_client, rep)
    at = _now() - timedelta(days=1)
    await _activity(
        kind="email",
        subject="Re: Oferta",
        body="Pierwsza odpowiedź w wątku o ofercie, z konkretnym pytaniem o stawkę.",
        direction="in",
        company_id=company,
        occurred_at=at,
    )
    await _activity(
        kind="email",
        subject="Re: Oferta",
        body="Druga odpowiedź w tym samym wątku, tym razem o terminie startu zespołu.",
        direction="out",
        company_id=company,
        occurred_at=at + timedelta(minutes=30),
    )
    assert len((await _timeline(app_client, rep, opp))["items"]) == 2


# Wiele maili z importu zaczyna się tym samym nagłówkiem adresatów.
MAIL_HEADER = (
    "Od: Zespół sprzedaży Do: Biuro klienta Temat wiadomości zgodny z korespondencją "
    "firmową, poufne "
)


async def _mail(company: int, at: datetime, subject: str, body: str) -> int:
    return await _activity(
        kind="email",
        subject=subject,
        body=body,
        direction="out",
        company_id=company,
        occurred_at=at,
    )


@pytest.mark.asyncio
async def test_mails_with_a_shared_header_and_other_subjects_stay_separate(
    app_client,
) -> None:
    rep = await _user("sales_edit")
    opp, company = await _opportunity(app_client, rep)
    at = _now() - timedelta(days=1)
    await _mail(company, at, "Oferta", MAIL_HEADER + "przesyłam ofertę na zespół.")
    await _mail(
        company, at + timedelta(hours=1), "Umowa NDA", MAIL_HEADER + "przesyłam NDA."
    )
    items = (await _timeline(app_client, rep, opp))["items"]
    assert sorted(item["subject"] for item in items) == ["Oferta", "Umowa NDA"]


@pytest.mark.asyncio
async def test_mails_of_one_thread_with_a_shared_header_stay_separate(
    app_client,
) -> None:
    rep = await _user("sales_edit")
    opp, company = await _opportunity(app_client, rep)
    at = _now() - timedelta(days=1)
    await _mail(company, at, "Oferta", MAIL_HEADER + "pytanie o stawkę.")
    await _mail(company, at + timedelta(hours=1), "Re: Oferta", MAIL_HEADER + "termin.")
    assert len((await _timeline(app_client, rep, opp))["items"]) == 2


@pytest.mark.asyncio
async def test_identical_body_with_another_subject_is_another_mail(app_client) -> None:
    rep = await _user("sales_edit")
    opp, company = await _opportunity(app_client, rep)
    at = _now() - timedelta(days=1)
    body = (
        "Dzień dobry, w załączniku przesyłam dokument, o którym rozmawialiśmy wczoraj."
    )
    await _mail(company, at, "Faktura", body)
    await _mail(company, at + timedelta(hours=2), "Regulamin", body)
    assert len((await _timeline(app_client, rep, opp))["items"]) == 2


@pytest.mark.asyncio
async def test_copy_of_one_mail_from_two_mailboxes_is_one_row(app_client) -> None:
    rep = await _user("sales_edit")
    opp, company = await _opportunity(app_client, rep)
    at = _now() - timedelta(days=1)
    await _mail(company, at, "Oferta", MAIL_HEADER + "ta sama wiadomość.")
    await _mail(company, at, "RE: Oferta", MAIL_HEADER + "ta sama wiadomość.")
    assert len((await _timeline(app_client, rep, opp))["items"]) == 1


@pytest.mark.asyncio
async def test_note_with_a_cut_copy_of_a_mail_is_one_row(app_client) -> None:
    rep = await _user("sales_edit")
    opp, company = await _opportunity(app_client, rep)
    at = _now() - timedelta(days=1)
    whole = (
        MAIL_HEADER
        + "pierwszy akapit wiadomości. Drugi akapit, którego notatka nie ma."
    )
    mail = await _mail(company, at, "Oferta", whole)
    await _activity(
        kind="note",
        body=whole[: len(MAIL_HEADER) + 20],
        company_id=company,
        opportunity_id=opp,
        occurred_at=at + timedelta(minutes=5),
    )
    assert [i["id"] for i in (await _timeline(app_client, rep, opp))["items"]] == [mail]


@pytest.mark.asyncio
async def test_notes_with_a_shared_opening_stay_separate(app_client) -> None:
    rep = await _user("sales_edit")
    opp, company = await _opportunity(app_client, rep)
    at = _now() - timedelta(days=1)
    for ending, minutes in (("uzgodniono zakres.", 0), ("przesunięto termin.", 60)):
        await _activity(
            kind="note",
            body=MAIL_HEADER + ending,
            company_id=company,
            opportunity_id=opp,
            occurred_at=at + timedelta(minutes=minutes),
        )
    assert len((await _timeline(app_client, rep, opp))["items"]) == 2


@pytest.mark.asyncio
async def test_timeline_refuses_without_permission(app_client) -> None:
    rep = await _user("sales_edit")
    outsider = await _user()
    opp, _ = await _opportunity(app_client, rep)
    resp = await app_client.get(
        TIMELINE, params={"opportunity_id": opp}, headers=_headers(outsider)
    )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_timeline_of_missing_opportunity_is_404(app_client) -> None:
    rep = await _user("sales_edit")
    resp = await app_client.get(
        TIMELINE, params={"opportunity_id": 999999999}, headers=_headers(rep)
    )
    assert resp.status_code == 404


# ── Kandydaci na opiekuna ────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_owner_candidates_are_active_accounts_with_sales_edit(app_client) -> None:
    rep = await _user("sales_edit")
    other = await _user("sales_edit")
    gone = await _user("sales_edit")
    viewer = await _user("sales_view")
    plain = await _user()
    async with AsyncSessionLocal() as db:
        await db.execute(
            text("UPDATE users SET is_active = false WHERE id = :id"), {"id": gone.id}
        )
        await db.commit()
    resp = await app_client.get(f"{URL}/owner-candidates", headers=_headers(rep))
    assert resp.status_code == 200, resp.text
    ids = {row["id"] for row in resp.json()}
    assert {rep.id, other.id} <= ids
    assert not ids & {gone.id, viewer.id, plain.id}
    assert all(set(row) == {"id", "name"} for row in resp.json())


@pytest.mark.asyncio
async def test_owner_candidates_refuse_without_sales_edit(app_client) -> None:
    for user in (await _user("sales_view"), await _user()):
        resp = await app_client.get(f"{URL}/owner-candidates", headers=_headers(user))
        assert resp.status_code == 403, resp.text
