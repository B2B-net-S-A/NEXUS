"""Sprzedaż → Dzwonienie: kolejność kolejki, każdy wynik rozmowy i ścieżki odmowy.

Baza testowa jest wspólna dla przebiegu, więc każdy test ma własnego dzwoniącego
i patrzy tylko na jego kolejkę. Dane są fikcyjne.
"""

from __future__ import annotations

import re
import uuid
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from typing import Any, Optional
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import select

from app.core.database import AsyncSessionLocal
from app.core.scheduling import DEFAULT_TZ, business_today
from app.models.client import Client
from app.models.sales import (
    SalesActivity,
    SalesCallCampaign,
    SalesCallRecord,
    SalesCompany,
    SalesContact,
    SalesOpportunity,
    SalesOpportunityEvent,
    SalesPipeline,
    SalesPipelineStage,
)
from app.services import sales_schema as schema
from app.services.company_names import normalize_company_name
from app.services.sales import calling, merge
from app.services.sales.calls import OUTCOME_LABELS
from tests.test_sales_companies_api import _headers, _user

URL = "/api/sales/calling"
ROOT = Path(__file__).resolve().parents[1]
ZONE = ZoneInfo(DEFAULT_TZ)


def _noon(day: date) -> datetime:
    return datetime.combine(day, time(12), tzinfo=ZONE)


async def _company(name: str = "Kolejka", **fields: Any) -> int:
    full = f"{name} {uuid.uuid4().hex[:10]}"
    async with AsyncSessionLocal() as db:
        company = SalesCompany(
            name=full, normalized_name=normalize_company_name(full), **fields
        )
        db.add(company)
        await db.commit()
        return company.id


async def _contact(company_id: int, **fields: Any) -> int:
    async with AsyncSessionLocal() as db:
        contact = SalesContact(
            company_id=company_id,
            full_name=fields.pop("full_name", "Jan Testowy"),
            phone=fields.pop("phone", "600 100 200"),
            **fields,
        )
        db.add(contact)
        await db.commit()
        return contact.id


async def _campaign(name: str = "Kampania", script: Optional[str] = None) -> int:
    async with AsyncSessionLocal() as db:
        campaign = SalesCallCampaign(
            name=f"{name} {uuid.uuid4().hex[:8]}",
            service="Usługa testowa",
            script=script,
        )
        db.add(campaign)
        await db.commit()
        return campaign.id


async def _record(
    user_id: int, campaign_id: Optional[int], company_id: int, **fields: Any
) -> int:
    async with AsyncSessionLocal() as db:
        record = SalesCallRecord(
            campaign_id=campaign_id,
            company_id=company_id,
            assigned_user_id=user_id,
            phone=fields.pop("phone", "600 100 200"),
            **fields,
        )
        db.add(record)
        await db.commit()
        return record.id


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
    owner_id: int,
    company_id: int,
    *,
    stage: str = "lead",
    created: Optional[datetime] = None,
    contact_id: Optional[int] = None,
    description: Optional[str] = None,
) -> int:
    pipeline_id, stage_id = await _stage(stage)
    async with AsyncSessionLocal() as db:
        opp = SalesOpportunity(
            company_id=company_id,
            pipeline_id=pipeline_id,
            stage_id=stage_id,
            title="Oferta ogólna wysłana",
            description=description,
            owner_user_id=owner_id,
            created_by_user_id=owner_id,
            primary_contact_id=contact_id,
            created_at=created or datetime.now(timezone.utc),
        )
        db.add(opp)
        await db.commit()
        return opp.id


async def _queue(app_client, user, **params: Any) -> dict[str, Any]:
    resp = await app_client.get(f"{URL}/queue", params=params, headers=_headers(user))
    assert resp.status_code == 200, resp.text
    return resp.json()


async def _save(app_client, user, record_id: int, **payload: Any):
    return await app_client.post(
        f"{URL}/records/{record_id}/outcome", json=payload, headers=_headers(user)
    )


async def _get_record(record_id: int) -> SalesCallRecord:
    async with AsyncSessionLocal() as db:
        return await db.get(SalesCallRecord, record_id)


async def _calls(company_id: int) -> list[SalesActivity]:
    async with AsyncSessionLocal() as db:
        return list(
            (
                await db.execute(
                    select(SalesActivity)
                    .where(
                        SalesActivity.company_id == company_id,
                        SalesActivity.kind == "call",
                    )
                    .order_by(SalesActivity.id)
                )
            ).scalars()
        )


# ── Schemat ───────────────────────────────────────────────────────────────


def test_migration_and_entrypoint_read_the_shared_ddl() -> None:
    # Numer nadaje pas migracji przy przepięciu, więc szukamy po nazwie.
    [path] = (ROOT / "alembic/versions").glob("*_sales_call_campaigns.py")
    migration = path.read_text(encoding="utf-8")
    assert "for stmt in schema.CALLING_DDL:" in migration
    assert "for stmt in schema.CALLING_DOWNGRADE_DDL:" in migration
    entry = (ROOT / "entrypoint.sh").read_text(encoding="utf-8")
    assert "*_sales_schema.CALLING_DDL," in entry


@pytest.mark.parametrize(
    ("table", "model"),
    [
        ("sales_call_campaigns", SalesCallCampaign),
        ("sales_call_records", SalesCallRecord),
    ],
)
def test_models_match_the_ddl(table: str, model: Any) -> None:
    ddl = next(
        statement
        for statement in schema.CALLING_DDL
        if f"CREATE TABLE IF NOT EXISTS {table} (" in statement
    )
    declared = set(re.findall(r"^\s+([a-z_0-9]+) [A-Z]", ddl, re.MULTILINE))
    assert set(model.__table__.columns.keys()) == declared
    named = {c.name for c in model.__table__.constraints if c.name}
    assert set(re.findall(r"CONSTRAINT (\w+)", ddl)) <= named
    indexes = {index.name for index in model.__table__.indexes}
    for statement in schema.CALLING_DDL:
        if statement.startswith(("CREATE INDEX", "CREATE UNIQUE INDEX")) and (
            f"ON {table} " in statement
        ):
            assert re.search(r"IF NOT EXISTS (\w+)", statement).group(1) in indexes


def test_queue_outcomes_share_the_call_dictionary() -> None:
    assert set(schema.CALL_QUEUE_OUTCOMES) <= set(schema.CALL_OUTCOMES)
    assert set(schema.CALL_OUTCOMES) == set(OUTCOME_LABELS)
    assert schema.CALL_RECORD_STATES == ("new", *schema.CALL_QUEUE_OUTCOMES)


# ── Kolejka ───────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_queue_and_outcome_follow_sales_permissions(app_client) -> None:
    outsider = await _user()
    viewer = await _user("sales_view")
    record_id = await _record(viewer.id, await _campaign(), await _company())
    denied = await app_client.get(f"{URL}/queue", headers=_headers(outsider))
    assert denied.status_code == 403
    assert denied.json()["detail"]["code"] == "permission_denied"
    assert (await _queue(app_client, viewer))["counts"]["new"] == 1
    # Podgląd czyta własną kolejkę, ale wyniku nie zapisze.
    assert (
        await _save(app_client, viewer, record_id, outcome="no_answer")
    ).status_code == 403
    assert (await _get_record(record_id)).state == "new"


@pytest.mark.asyncio
async def test_queue_keeps_a_fixed_order_of_sections(app_client) -> None:
    caller = await _user("sales_edit")
    campaign_id = await _campaign()
    today = business_today()
    overdue = await _record(
        caller.id,
        campaign_id,
        await _company(),
        state="offer_sent",
        callback_on=today - timedelta(days=2),
    )
    due_today = await _record(
        caller.id, campaign_id, await _company(), state="not_now", callback_on=today
    )
    await _record(
        caller.id,
        campaign_id,
        await _company(),
        state="call_back",
        callback_on=today + timedelta(days=3),
    )
    fresh = await _record(caller.id, campaign_id, await _company())
    await _record(caller.id, campaign_id, await _company(), state="do_not_contact")
    old_lead = await _opportunity(
        caller.id, await _company(), created=_noon(today - timedelta(days=90))
    )
    fresh_lead = await _opportunity(
        caller.id, await _company(), created=_noon(today - timedelta(days=20))
    )
    await _opportunity(caller.id, await _company())
    no_date = await _opportunity(
        caller.id, await _company(), stage="qualifying-meeting"
    )
    with_meeting_company = await _company()
    with_meeting = await _opportunity(
        caller.id, with_meeting_company, stage="qualifying-meeting"
    )
    async with AsyncSessionLocal() as db:
        db.add(
            SalesActivity(
                kind="meeting",
                company_id=with_meeting_company,
                subject="Spotkanie kwalifikujące",
                occurred_at=datetime.now(timezone.utc) + timedelta(days=2),
            )
        )
        await db.commit()

    queue = await _queue(app_client, caller)
    # Ustalone oddzwonienia od najstarszego terminu, potem szanse bez rozmowy
    # z kolejki od najnowszej.
    assert [item["key"] for item in queue["callbacks"]] == [
        f"r:{overdue}",
        f"r:{due_today}",
        f"o:{fresh_lead}",
        f"o:{old_lead}",
    ]
    assert [item["key"] for item in queue["meetings"]] == [f"o:{no_date}"]
    assert f"o:{with_meeting}" not in {item["key"] for item in queue["meetings"]}
    assert [item["key"] for item in queue["new"]] == [f"r:{fresh}"]
    # Jutrzejsze oddzwonienie i dzisiejsza szansa wracają same w swoim dniu.
    assert queue["counts"] == {
        "callbacks": 4,
        "no_answer": 0,
        "meetings": 1,
        "new": 1,
        "later": 2,
    }
    assert queue["today"] == today.isoformat()
    assert [c["id"] for c in queue["campaigns"]] == [campaign_id]

    only = await _queue(app_client, caller, campaign_id=campaign_id)
    assert [item["key"] for item in only["callbacks"]] == [
        f"r:{overdue}",
        f"r:{due_today}",
    ]
    assert only["meetings"] == []


@pytest.mark.asyncio
async def test_queue_is_own_by_default_and_shows_another_caller_on_request(
    app_client,
) -> None:
    """Decyzja Artura 13.11.2026: kolejka z wyborem osoby (podział Bianca / Marcel)."""

    caller = await _user("sales_edit")
    other = await _user("sales_edit")
    campaign_id = await _campaign()
    theirs = await _record(other.id, campaign_id, await _company())
    lead = await _opportunity(
        other.id, await _company(), created=_noon(business_today() - timedelta(days=20))
    )
    queue = await _queue(app_client, caller)
    assert queue["counts"] == {
        "callbacks": 0,
        "no_answer": 0,
        "meetings": 0,
        "new": 0,
        "later": 0,
    }
    # Stary parametr ``user_id`` niczego nie przełącza; wybór osoby to ``caller_id``.
    assert (await _queue(app_client, caller, user_id=other.id))["new"] == []
    assert other.id in {person["id"] for person in queue["callers"]}
    shown = await _queue(app_client, caller, caller_id=other.id)
    assert [item["key"] for item in shown["new"]] == [f"r:{theirs}"]
    assert [item["key"] for item in shown["callbacks"]] == [f"o:{lead}"]
    # Licznik „Dziś” zostaje osoby, która patrzy.
    assert shown["today_counts"]["calls"] == 0


# ── Wynik rozmowy: rekord kampanii ────────────────────────────────────────


@pytest.mark.parametrize(
    ("outcome", "requested_days", "expected"),
    [
        ("no_answer", None, lambda today: calling.workdays_after(today, 1)),
        ("call_back", 5, lambda today: today + timedelta(days=5)),
        ("call_back", None, lambda today: calling.workdays_after(today, 1)),
        ("call_back", 45, lambda today: today + timedelta(days=45)),
        ("offer_sent", None, lambda today: calling.workdays_after(today, 3)),
        ("offer_sent", 10, lambda today: today + timedelta(days=10)),
    ],
)
@pytest.mark.asyncio
async def test_returning_outcomes_set_the_callback_day(
    app_client, outcome: str, requested_days: Optional[int], expected: Any
) -> None:
    caller = await _user("sales_edit")
    company_id = await _company()
    contact_id = await _contact(company_id)
    record_id = await _record(
        caller.id,
        await _campaign(),
        company_id,
        contact_id=contact_id,
        person_name="Jan Testowy",
    )
    today = business_today()
    payload: dict[str, Any] = {"outcome": outcome, "note": " Ustalone. "}
    if requested_days is not None:
        payload["callback_on"] = (today + timedelta(days=requested_days)).isoformat()
    resp = await _save(app_client, caller, record_id, **payload)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["state"] == outcome
    assert body["callback_on"] == expected(today).isoformat()
    assert body["opportunity_id"] is None

    record = await _get_record(record_id)
    assert (record.state, record.attempts) == (outcome, 1)
    assert record.last_outcome_at is not None
    [call] = await _calls(company_id)
    assert call.outcome == outcome
    assert call.subject == f"{OUTCOME_LABELS[outcome]}: Jan Testowy"
    assert call.body == "Ustalone."
    assert (call.contact_id, call.opportunity_id) == (contact_id, None)
    assert call.direction == "out" and call.done_at is not None
    queue = await _queue(app_client, caller)
    if outcome == "no_answer":
        # „Nie odebrał” stoi w swojej zakładce bez względu na datę (13.11.2026).
        assert [item["record_id"] for item in queue["no_answer"]] == [record_id]
        assert queue["counts"]["later"] == 0 and queue["callbacks"] == []
        return
    # Rekord wraca sam w swoim dniu, a dziś znika z listy.
    assert queue["counts"]["later"] == 1 and queue["callbacks"] == []


@pytest.mark.asyncio
async def test_callback_in_the_past_is_refused(app_client) -> None:
    caller = await _user("sales_edit")
    record_id = await _record(caller.id, await _campaign(), await _company())
    resp = await _save(
        app_client,
        caller,
        record_id,
        outcome="call_back",
        callback_on=(business_today() - timedelta(days=1)).isoformat(),
    )
    assert resp.status_code == 422
    assert resp.json()["detail"] == calling.PAST_DATE_DETAIL
    assert (await _get_record(record_id)).state == "new"


@pytest.mark.asyncio
async def test_do_not_contact_marks_the_person_and_closes_the_record(
    app_client,
) -> None:
    caller = await _user("sales_edit")
    company_id = await _company()
    contact_id = await _contact(company_id)
    campaign_id = await _campaign()
    record_id = await _record(caller.id, campaign_id, company_id, contact_id=contact_id)
    sibling = await _record(
        caller.id, campaign_id, company_id, contact_id=contact_id, phone="600 100 201"
    )
    resp = await _save(app_client, caller, record_id, outcome="do_not_contact")
    assert resp.status_code == 200, resp.text
    assert resp.json()["callback_on"] is None
    async with AsyncSessionLocal() as db:
        contact = await db.get(SalesContact, contact_id)
        assert contact.do_not_contact_at is not None
        assert contact.do_not_contact_by_user_id == caller.id
    # Zamknięty rekord nie przyjmuje kolejnego wyniku, a sprzeciw osoby blokuje
    # rozmowę także z drugiego rekordu.
    again = await _save(app_client, caller, record_id, outcome="no_answer")
    assert (again.status_code, again.json()["detail"]) == (409, calling.CLOSED_DETAIL)
    blocked = await _save(app_client, caller, sibling, outcome="no_answer")
    assert (blocked.status_code, blocked.json()["detail"]) == (
        409,
        calling.OBJECTION_DETAIL,
    )
    card = (
        await app_client.get(f"{URL}/records/{sibling}", headers=_headers(caller))
    ).json()
    assert card["do_not_contact"] is True
    # Drugi rekord tej osoby znika z kolejki razem z numerem.
    assert (await _queue(app_client, caller))["counts"]["new"] == 0


@pytest.mark.asyncio
async def test_objection_recorded_elsewhere_removes_the_position_from_the_queue(
    app_client,
) -> None:
    caller = await _user("sales_edit")
    campaign_id = await _campaign()
    objected_company = await _company()
    objected = await _contact(
        objected_company, do_not_contact_at=datetime.now(timezone.utc)
    )
    await _record(caller.id, campaign_id, objected_company, contact_id=objected)
    await _record(caller.id, campaign_id, await _company(status="do_not_contact"))
    await _opportunity(
        caller.id,
        objected_company,
        created=_noon(business_today() - timedelta(days=20)),
        contact_id=objected,
    )
    await _opportunity(
        caller.id, objected_company, stage="qualifying-meeting", contact_id=objected
    )
    kept = await _record(caller.id, campaign_id, await _company())
    queue = await _queue(app_client, caller)
    assert [item["key"] for item in queue["new"]] == [f"r:{kept}"]
    assert queue["counts"] == {
        "callbacks": 0,
        "no_answer": 0,
        "meetings": 0,
        "new": 1,
        "later": 0,
    }


@pytest.mark.asyncio
async def test_meeting_booked_needs_the_opportunity_of_the_same_company(
    app_client,
) -> None:
    caller = await _user("sales_edit")
    company_id = await _company()
    record_id = await _record(caller.id, await _campaign(), company_id)
    missing = await _save(app_client, caller, record_id, outcome="meeting_booked")
    assert (missing.status_code, missing.json()["detail"]) == (
        422,
        calling.MEETING_NEEDS_OPPORTUNITY,
    )
    foreign = await _opportunity(caller.id, await _company(), stage="offer-sent")
    wrong = await _save(
        app_client, caller, record_id, outcome="meeting_booked", opportunity_id=foreign
    )
    assert (wrong.status_code, wrong.json()["detail"]) == (
        422,
        calling.OTHER_COMPANY_OPPORTUNITY,
    )
    lost = await _opportunity(caller.id, company_id, stage="qualifying-meeting")
    async with AsyncSessionLocal() as db:
        (await db.get(SalesOpportunity, lost)).status = "lost"
        await db.commit()
    closed_opp = await _save(
        app_client, caller, record_id, outcome="meeting_booked", opportunity_id=lost
    )
    assert (closed_opp.status_code, closed_opp.json()["detail"]) == (
        422,
        calling.CLOSED_OPPORTUNITY,
    )
    assert (await _get_record(record_id)).state == "new"

    opp_id = await _opportunity(caller.id, company_id, stage="qualifying-meeting")
    saved = await _save(
        app_client, caller, record_id, outcome="meeting_booked", opportunity_id=opp_id
    )
    assert saved.status_code == 200, saved.text
    assert saved.json() == {
        "record_id": record_id,
        "state": "meeting_booked",
        "callback_on": None,
        "opportunity_id": opp_id,
    }
    [call] = await _calls(company_id)
    assert (call.outcome, call.opportunity_id) == ("meeting_booked", opp_id)
    queue = await _queue(app_client, caller)
    # Rekord zniknął z kolejki, a szansa czeka w „spotkaniach bez terminu”.
    assert queue["new"] == [] and queue["callbacks"] == []
    assert [item["key"] for item in queue["meetings"]] == [f"o:{opp_id}"]
    # Karta szansy z umówionego spotkania zna skrypt kampanii, z której przyszła.
    card = await app_client.get(
        f"{URL}/opportunities/{opp_id}", headers=_headers(caller)
    )
    assert card.json()["service"] == "Usługa testowa"
    closed = await _save(app_client, caller, record_id, outcome="no_answer")
    assert closed.status_code == 409


@pytest.mark.asyncio
async def test_any_sales_editor_saves_in_someone_elses_queue(app_client) -> None:
    """Decyzja Artura 13.11.2026: wynik w cudzej kolejce zapisuje każdy z edycją,
    a telefon liczy się temu, kto kliknął."""

    owner = await _user("sales_edit")
    stand_in = await _user("sales_edit")
    viewer = await _user("sales_view")
    company_id = await _company()
    record_id = await _record(owner.id, await _campaign(), company_id)
    card = (
        await app_client.get(f"{URL}/records/{record_id}", headers=_headers(viewer))
    ).json()
    assert card["can_save"] is False
    assert (
        await _save(app_client, viewer, record_id, outcome="no_answer")
    ).status_code == 403
    card = (
        await app_client.get(f"{URL}/records/{record_id}", headers=_headers(stand_in))
    ).json()
    assert card["can_save"] is True
    saved = await _save(app_client, stand_in, record_id, outcome="no_answer")
    assert saved.status_code == 200, saved.text
    record = await _get_record(record_id)
    assert (record.attempts, record.assigned_user_id) == (1, owner.id)
    [call] = await _calls(company_id)
    assert call.created_by_user_id == stand_in.id
    missing = await _save(app_client, owner, 2_000_000_000, outcome="no_answer")
    assert missing.status_code == 404


@pytest.mark.asyncio
async def test_client_company_is_handed_to_the_delivery_lead(app_client) -> None:
    caller = await _user("sales_edit")
    tag = uuid.uuid4().hex[:8]
    name = f"Bocian Logistyka {tag}"
    async with AsyncSessionLocal() as db:
        db.add(Client(name=name))
        await db.commit()
    async with AsyncSessionLocal() as db:
        company = SalesCompany(name=name, normalized_name=normalize_company_name(name))
        db.add(company)
        await db.commit()
        company_id = company.id
    record_id = await _record(caller.id, await _campaign(), company_id)
    opp_id = await _opportunity(caller.id, company_id, stage="qualifying-meeting")
    card = (
        await app_client.get(f"{URL}/records/{record_id}", headers=_headers(caller))
    ).json()
    assert name in card["client_refusal"]
    resp = await _save(
        app_client, caller, record_id, outcome="meeting_booked", opportunity_id=opp_id
    )
    assert resp.status_code == 409
    assert "klient NEXUSA" in resp.json()["detail"]
    assert (await _get_record(record_id)).state == "new"
    # Zwykły wynik rozmowy przechodzi: bramka dotyczy tylko zakładania szansy.
    assert (
        await _save(app_client, caller, record_id, outcome="call_back")
    ).status_code == 200


@pytest.mark.asyncio
async def test_card_shows_script_source_and_what_already_happened(app_client) -> None:
    caller = await _user("sales_edit")
    company_id = await _company(domain="kolejka-test.example")
    campaign_id = await _campaign(script="Otwarcie: jedno zdanie o usłudze.")
    record_id = await _record(
        caller.id,
        campaign_id,
        company_id,
        contact_source="Lista z targów",
        note="Branża: logistyka",
        email="jan@kolejka-test.example",
    )
    await _save(app_client, caller, record_id, outcome="no_answer")
    async with AsyncSessionLocal() as db:
        db.add(
            SalesActivity(
                kind="task",
                company_id=company_id,
                subject="Otwarte zadanie to zamiar, nie historia",
                due_at=datetime.now(timezone.utc) + timedelta(days=1),
            )
        )
        await db.commit()
    resp = await app_client.get(f"{URL}/records/{record_id}", headers=_headers(caller))
    assert resp.status_code == 200, resp.text
    card = resp.json()
    assert card["script"] == "Otwarcie: jedno zdanie o usłudze."
    assert card["service"] == "Usługa testowa"
    assert (card["contact_source"], card["note"]) == (
        "Lista z targów",
        "Branża: logistyka",
    )
    assert (card["domain"], card["email"]) == (
        "kolejka-test.example",
        "jan@kolejka-test.example",
    )
    assert card["can_save"] is True and card["client_refusal"] is None
    assert [(h["kind"], h["outcome"]) for h in card["history"]] == [
        ("call", "no_answer")
    ]
    missing = await app_client.get(
        f"{URL}/records/2000000000", headers=_headers(caller)
    )
    assert missing.status_code == 404


# ── Wynik rozmowy: szansa z etapu „Lead” ──────────────────────────────────


async def _save_opportunity(app_client, user, opportunity_id: int, **payload: Any):
    return await app_client.post(
        f"{URL}/opportunities/{opportunity_id}/outcome",
        json=payload,
        headers=_headers(user),
    )


@pytest.mark.asyncio
async def test_first_outcome_gives_the_lead_opportunity_one_queue_record(
    app_client,
) -> None:
    caller = await _user("sales_edit")
    company_id = await _company()
    contact_id = await _contact(company_id, title="Dyrektor IT")
    opp_id = await _opportunity(
        caller.id,
        company_id,
        created=_noon(business_today() - timedelta(days=20)),
        contact_id=contact_id,
        description="  Kierownik IT, prosi o kontakt po 15.  ",
    )
    [item] = (await _queue(app_client, caller))["callbacks"]
    assert (item["key"], item["record_id"], item["state"]) == (
        f"o:{opp_id}",
        None,
        "new",
    )
    assert (item["person_name"], item["person_title"], item["phone"]) == (
        "Jan Testowy",
        "Dyrektor IT",
        "600 100 200",
    )
    card = await app_client.get(
        f"{URL}/opportunities/{opp_id}", headers=_headers(caller)
    )
    assert card.status_code == 200 and card.json()["can_save"] is True
    # Osoba i numer bywają tylko w opisie szansy założonej po telefonie.
    assert card.json()["note"] == "Kierownik IT, prosi o kontakt po 15."

    first = await _save_opportunity(app_client, caller, opp_id, outcome="offer_sent")
    assert first.status_code == 200, first.text
    record_id = first.json()["record_id"]
    assert first.json()["opportunity_id"] == opp_id
    queue = await _queue(app_client, caller)
    assert queue["callbacks"] == [] and queue["counts"]["later"] == 1

    second = await _save_opportunity(
        app_client,
        caller,
        opp_id,
        outcome="call_back",
        callback_on=business_today().isoformat(),
    )
    assert second.json()["record_id"] == record_id
    record = await _get_record(record_id)
    assert (record.campaign_id, record.attempts, record.contact_id) == (
        None,
        2,
        contact_id,
    )
    calls = await _calls(company_id)
    # Telefon ląduje w dzienniku szansy: tym samym, który liczy karta szansy.
    assert [(c.outcome, c.opportunity_id) for c in calls] == [
        ("offer_sent", opp_id),
        ("call_back", opp_id),
    ]
    [item] = (await _queue(app_client, caller))["callbacks"]
    assert (item["key"], item["record_id"], item["attempts"]) == (
        f"o:{opp_id}",
        record_id,
        2,
    )


@pytest.mark.asyncio
async def test_meeting_booked_moves_the_lead_opportunity_to_the_meeting_stage(
    app_client,
) -> None:
    caller = await _user("sales_edit")
    opp_id = await _opportunity(
        caller.id,
        await _company(),
        created=_noon(business_today() - timedelta(days=20)),
    )
    resp = await _save_opportunity(app_client, caller, opp_id, outcome="meeting_booked")
    assert resp.status_code == 200, resp.text
    _pipeline, meeting_stage = await _stage("qualifying-meeting")
    async with AsyncSessionLocal() as db:
        opp = await db.get(SalesOpportunity, opp_id)
        assert (opp.stage_id, opp.status) == (meeting_stage, "open")
        events = (
            await db.execute(
                select(
                    SalesOpportunityEvent.field, SalesOpportunityEvent.new_value
                ).where(
                    SalesOpportunityEvent.opportunity_id == opp_id,
                    SalesOpportunityEvent.field == "stage_id",
                )
            )
        ).all()
    assert (("stage_id", str(meeting_stage))) in [tuple(row) for row in events]
    queue = await _queue(app_client, caller)
    assert queue["callbacks"] == []
    assert [item["key"] for item in queue["meetings"]] == [f"o:{opp_id}"]
    # Dzwoniący ustala jeszcze termin: „oddzwonić jutro” chowa pozycję do jutra.
    later = await _save_opportunity(app_client, caller, opp_id, outcome="call_back")
    assert later.status_code == 200, later.text
    assert (await _queue(app_client, caller))["meetings"] == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "payload",
    [
        {"outcome": "bad_contact"},
        {"outcome": "offer_sent", "never": True},
    ],
)
async def test_meeting_without_date_leaves_the_queue_after_a_final_outcome(
    app_client, payload: dict[str, Any]
) -> None:
    """Audyt 12.11 (S6): „Zły numer” i „Nigdy” zamykają pozycję jak w leadach.

    Wracająca pozycja dawała kolejne naciśnięcia, które zawyżały „Dziś”
    i Skuteczność.
    """

    caller = await _user("sales_edit")
    opp_id = await _opportunity(caller.id, await _company(), stage="qualifying-meeting")
    assert [i["key"] for i in (await _queue(app_client, caller))["meetings"]] == [
        f"o:{opp_id}"
    ]
    saved = await _save_opportunity(app_client, caller, opp_id, **payload)
    assert saved.status_code == 200, saved.text
    queue = await _queue(app_client, caller)
    assert queue["meetings"] == [] and queue["counts"]["meetings"] == 0


@pytest.mark.asyncio
async def test_outcome_follows_the_current_contact_of_the_opportunity(
    app_client,
) -> None:
    caller = await _user("sales_edit")
    company_id = await _company()
    opp_id = await _opportunity(
        caller.id, company_id, created=_noon(business_today() - timedelta(days=20))
    )
    first = await _save_opportunity(
        app_client,
        caller,
        opp_id,
        outcome="call_back",
        callback_on=business_today().isoformat(),
    )
    assert first.status_code == 200, first.text
    # Kontakt dopisany do szansy po pierwszej rozmowie: sprzeciw ma trafić do niego.
    contact_id = await _contact(company_id, full_name="Ewa Późniejsza")
    async with AsyncSessionLocal() as db:
        (await db.get(SalesOpportunity, opp_id)).primary_contact_id = contact_id
        await db.commit()
    [item] = (await _queue(app_client, caller))["callbacks"]
    assert item["person_name"] == "Ewa Późniejsza"
    objected = await _save_opportunity(
        app_client, caller, opp_id, outcome="do_not_contact"
    )
    assert objected.status_code == 200, objected.text
    async with AsyncSessionLocal() as db:
        assert (await db.get(SalesContact, contact_id)).do_not_contact_at is not None
    record = await _get_record(first.json()["record_id"])
    assert (record.contact_id, record.person_name, record.phone) == (
        contact_id,
        "Ewa Późniejsza",
        "600 100 200",
    )
    assert (await _calls(company_id))[-1].contact_id == contact_id


@pytest.mark.asyncio
async def test_opportunity_moved_back_to_lead_returns_to_callbacks(app_client) -> None:
    caller = await _user("sales_edit")
    opp_id = await _opportunity(
        caller.id,
        await _company(),
        created=_noon(business_today() - timedelta(days=20)),
    )
    booked = await _save_opportunity(
        app_client, caller, opp_id, outcome="meeting_booked"
    )
    assert booked.status_code == 200, booked.text
    _pipeline, lead_stage = await _stage("lead")
    async with AsyncSessionLocal() as db:
        (await db.get(SalesOpportunity, opp_id)).stage_id = lead_stage
        await db.commit()
    queue = await _queue(app_client, caller)
    # Spotkanie nie doszło do skutku: pozycja nie może zniknąć z obu sekcji.
    assert [item["key"] for item in queue["callbacks"]] == [f"o:{opp_id}"]
    assert queue["meetings"] == []


@pytest.mark.asyncio
async def test_opportunity_outcome_refuses_strangers_and_other_stages(
    app_client,
) -> None:
    owner = await _user("sales_edit")
    viewer = await _user("sales_view")
    opp_id = await _opportunity(owner.id, await _company())
    assert (
        await _save_opportunity(app_client, viewer, opp_id, outcome="no_answer")
    ).status_code == 403
    async with AsyncSessionLocal() as db:
        assert (
            await db.scalar(
                select(SalesCallRecord.id).where(
                    SalesCallRecord.opportunity_id == opp_id
                )
            )
        ) is None
    offer = await _opportunity(owner.id, await _company(), stage="offer-sent")
    outside = await _save_opportunity(app_client, owner, offer, outcome="no_answer")
    assert (outside.status_code, outside.json()["detail"]) == (
        409,
        calling.NOT_IN_QUEUE_DETAIL,
    )
    missing = await _save_opportunity(
        app_client, owner, 2_000_000_000, outcome="no_answer"
    )
    assert missing.status_code == 404


@pytest.mark.asyncio
async def test_do_not_contact_on_an_opportunity_leaves_a_history_trace(
    app_client,
) -> None:
    caller = await _user("sales_edit")
    company_id = await _company()
    contact_id = await _contact(company_id)
    opp_id = await _opportunity(
        caller.id,
        company_id,
        created=_noon(business_today() - timedelta(days=20)),
        contact_id=contact_id,
    )
    resp = await _save_opportunity(app_client, caller, opp_id, outcome="do_not_contact")
    assert resp.status_code == 200, resp.text
    async with AsyncSessionLocal() as db:
        assert (await db.get(SalesContact, contact_id)).do_not_contact_at is not None
        fields = (
            await db.execute(
                select(SalesOpportunityEvent.field).where(
                    SalesOpportunityEvent.opportunity_id == opp_id
                )
            )
        ).scalars()
        assert "do_not_contact" in set(fields)
    assert (await _queue(app_client, caller))["callbacks"] == []


# ── Kampanie i scalanie firm ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_campaign_is_created_edited_and_counted(app_client) -> None:
    caller = await _user("sales_edit")
    viewer = await _user("sales_view")
    name = f"Kampania {uuid.uuid4().hex[:8]}"
    denied = await app_client.post(
        f"{URL}/campaigns", json={"name": name}, headers=_headers(viewer)
    )
    assert denied.status_code == 403
    blank = await app_client.post(
        f"{URL}/campaigns", json={"name": "   "}, headers=_headers(caller)
    )
    assert blank.status_code == 422
    created = await app_client.post(
        f"{URL}/campaigns",
        json={"name": f"  {name} ", "service": "Usługa", "script": " Skrypt "},
        headers=_headers(caller),
    )
    assert created.status_code == 201, created.text
    campaign = created.json()
    assert (campaign["name"], campaign["script"], campaign["total"]) == (
        name,
        "Skrypt",
        0,
    )
    await _record(caller.id, campaign["id"], await _company())
    await _record(caller.id, campaign["id"], await _company(), state="offer_sent")
    edited = await app_client.patch(
        f"{URL}/campaigns/{campaign['id']}",
        json={"script": "Nowy skrypt"},
        headers=_headers(caller),
    )
    assert edited.status_code == 200, edited.text
    assert (edited.json()["script"], edited.json()["name"]) == ("Nowy skrypt", name)
    assert edited.json()["counts"] == {"new": 1, "offer_sent": 1}
    listed = (await app_client.get(f"{URL}/campaigns", headers=_headers(viewer))).json()
    assert campaign["id"] in {row["id"] for row in listed}
    missing = await app_client.patch(
        f"{URL}/campaigns/2000000000", json={"script": "x"}, headers=_headers(caller)
    )
    assert missing.status_code == 404


@pytest.mark.asyncio
async def test_merging_companies_moves_queue_records(app_client) -> None:
    caller = await _user("sales_edit")
    source_id = await _company("Źródło")
    target_id = await _company("Cel")
    record_id = await _record(caller.id, await _campaign(), source_id)
    async with AsyncSessionLocal() as db:
        await merge.merge_companies(
            db,
            target=await db.get(SalesCompany, target_id),
            source=await db.get(SalesCompany, source_id),
            now=datetime.now(timezone.utc),
            user_id=caller.id,
        )
        await db.commit()
    assert (await _get_record(record_id)).company_id == target_id
    [item] = (await _queue(app_client, caller))["new"]
    assert item["company"]["id"] == target_id
