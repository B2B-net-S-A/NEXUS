"""Mapa decyzyjna ← Outlook: status kontaktu osoby przesuwa się sam (rekomendacja B4).

Decyzje Artura z 10.11.2026: nasz mail daje „w toku”, mail od osoby albo odbyte
spotkanie „pierwszy kontakt”, „stały dialog” ustawia tylko człowiek. Status nigdy
się nie cofa, sprzeciw wyłącza automat, a ręczna zmiana ma pierwszeństwo.

Maile i spotkania przechodzą przez prawdziwą ścieżkę synchronizacji. Dane są
fikcyjne, a adresy i nazwy niosą losowy tag, bo baza testowa jest wspólna.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

import pytest
from sqlalchemy import select, update

from app.core.database import AsyncSessionLocal
from app.models.sales import (
    SalesActivity,
    SalesContact,
    SalesOpportunity,
    SalesOpportunityEvent,
)
from app.services.m365 import sync as sync_mod
from app.services.sales import decision_map, factories
from app.services.sales import decision_map_outlook as map_outlook
from app.services.sales import outlook_activities as outlook
from app.services.sales.motion import ATLAS_CONTACT_REF, entry_keys
from scripts import sales_decision_map_outlook as backfill
from tests.test_sales_companies_api import _headers
from tests.test_sales_companies_api import _user as _sales_user
from tests.test_sales_factories import LOST, _account, _company, _person
from tests.test_sales_last_touch import _touch
from tests.test_sales_outlook_sync import (
    SALES_ONLY,
    _conn,
    _graph_event,
    _graph_msg,
    _tag,
    _user,
)

NOW = datetime(2026, 11, 10, 12, 0, tzinfo=timezone.utc)
MAIL_AT = NOW - timedelta(days=1)
MAIL_DAY = "2026-11-09"
URL = "/api/sales/opportunities"

#: Szanse tego modułu; automat widzi tylko je, bo inne testy też zakładają mapy.
_own: set[int] = set()


@pytest.fixture(autouse=True)
def only_own_maps(monkeypatch):
    original = map_outlook._open_maps
    _own.clear()
    monkeypatch.setattr(
        map_outlook,
        "_open_maps",
        lambda: [*original(), SalesOpportunity.id.in_(set(_own))],
    )


def _address(local: str = "osoba") -> str:
    return f"{local}-{_tag()}@mapa-{_tag()}.example"


async def _map_account(people: list[dict[str, Any]], **fields: Any) -> tuple[int, int]:
    opportunity_id, company_id = await _account(people, **fields)
    _own.add(opportunity_id)
    return opportunity_id, company_id


async def _contact(
    company_id: int, name: str, email: Optional[str] = None, **fields: Any
) -> int:
    async with AsyncSessionLocal() as db:
        contact = SalesContact(
            full_name=name, email=email, company_id=company_id, **fields
        )
        db.add(contact)
        await db.commit()
        return contact.id


async def _known_person(
    status: str = "not_contacted", **entry: Any
) -> tuple[int, int, str, str]:
    """Konto z jedną osobą, której kontakt ma adres; (szansa, firma, adres, nazwisko)."""

    name = f"Dyrektor {_tag()}"
    address = _address()
    opportunity_id, company_id = await _map_account([_person(name, 1, status, **entry)])
    await _contact(company_id, name, address)
    return opportunity_id, company_id, address, name


def _message(
    *,
    sender: str,
    to: str,
    cc: tuple[str, ...] = (),
    at: datetime = MAIL_AT,
    subject: str = "Oferta współpracy",
) -> dict:
    msg = _graph_msg(sender=sender, to=to)
    msg["subject"] = subject
    stamp = at.strftime("%Y-%m-%dT%H:%M:%SZ")
    msg["sentDateTime"] = msg["receivedDateTime"] = stamp
    msg["ccRecipients"] = [{"emailAddress": {"address": a}} for a in cc]
    return msg


async def _sent(rep, to: str, **fields: Any) -> None:
    """Mail handlowca do osoby, zapisany przez synchronizację folderu Wysłane."""

    async with AsyncSessionLocal() as db:
        await sync_mod._upsert_message(
            db,
            None,
            _conn(rep),
            _message(sender=rep.email, to=to, **fields),
            "SentItems",
            scope=SALES_ONLY,
        )
        await db.commit()


async def _received(rep, sender: str, **fields: Any) -> None:
    async with AsyncSessionLocal() as db:
        await sync_mod._upsert_message(
            db,
            None,
            _conn(rep),
            _message(sender=sender, to=rep.email, **fields),
            "Inbox",
            scope=SALES_ONLY,
        )
        await db.commit()


async def _meeting(
    rep, *attendees: str, start: datetime, subject: str = "Spotkanie"
) -> None:
    ev = _graph_event(*attendees, start=start)
    ev["subject"] = subject
    async with AsyncSessionLocal() as db:
        await sync_mod._upsert_event(db, _conn(rep), ev, scope=SALES_ONLY)
        await db.commit()


async def _imported_mail(
    company_id: int, contact_id: int, direction: str, at: datetime = MAIL_AT
) -> None:
    """Historia z Atlasa: sam kontakt i kierunek, bez wiersza poczty z adresami."""

    marker = _tag()
    async with AsyncSessionLocal() as db:
        db.add(
            SalesActivity(
                kind="email",
                company_id=company_id,
                contact_id=contact_id,
                direction=direction,
                occurred_at=at,
                done_at=at,
                external_source=outlook.EMAIL_SOURCE,
                external_id=f"<{marker}@atlas.example>",
                external_ref=f"atlas:activities:{marker}",
            )
        )
        await db.commit()


async def _sync(
    *, apply: bool = True, since: Optional[datetime] = None, now: datetime = NOW
) -> map_outlook.Report:
    async with AsyncSessionLocal() as db:
        report = await map_outlook.sync(db, now=now, since=since, apply=apply)
        await db.commit()
        return report


async def _entries(opportunity_id: int) -> list[dict[str, Any]]:
    async with AsyncSessionLocal() as db:
        opportunity = await db.get(SalesOpportunity, opportunity_id)
        assert opportunity is not None
        return decision_map.decision_entries(opportunity.custom_fields)


async def _person_now(opportunity_id: int) -> dict[str, Any]:
    [entry] = await _entries(opportunity_id)
    return entry


async def _history(
    opportunity_id: int, field: str = "decision_map"
) -> list[SalesOpportunityEvent]:
    async with AsyncSessionLocal() as db:
        return list(
            (
                await db.execute(
                    select(SalesOpportunityEvent)
                    .where(
                        SalesOpportunityEvent.opportunity_id == opportunity_id,
                        SalesOpportunityEvent.field == field,
                    )
                    .order_by(SalesOpportunityEvent.id)
                )
            ).scalars()
        )


# ── Które zdarzenie daje który status ─────────────────────────────────────


async def test_our_mail_means_in_progress_with_date_and_history() -> None:
    rep = await _user("employee", "sales_view")
    opportunity_id, _, address, name = await _known_person()
    [key_before] = entry_keys(await _entries(opportunity_id))
    await _sent(rep, address)

    report = await _sync()

    entry = await _person_now(opportunity_id)
    assert entry["contact_status"] == "in_progress"
    assert entry["last_contact_at"] == MAIL_DAY
    assert factories.is_contacted(entry)
    # Klucz osoby to skrót treści: okno otwarte przed zmianą dostanie 409.
    assert entry_keys([entry]) != [key_before]
    [event] = await _history(opportunity_id)
    assert event.user_id is None
    assert (
        event.old_value == f"{name} — status kontaktu: bez kontaktu; ostatni kontakt: —"
    )
    assert event.new_value == (
        f"{name} — status kontaktu: w toku; ostatni kontakt: {MAIL_DAY}"
        " · z Outlooka: mail od nas"
    )
    assert [(c.opportunity_id, c.old_status, c.new_status) for c in report.changes] == [
        (opportunity_id, "not_contacted", "in_progress")
    ]


async def test_mail_from_the_person_means_first_contact() -> None:
    rep = await _user("employee", "sales_view")
    opportunity_id, _, address, _ = await _known_person()
    await _received(rep, address.upper())

    await _sync()

    entry = await _person_now(opportunity_id)
    assert entry["contact_status"] == "first_contact"
    [event] = await _history(opportunity_id)
    assert event.new_value.endswith("z Outlooka: mail od osoby")


async def test_incoming_mail_with_the_person_only_in_copy_is_in_progress() -> None:
    rep = await _user("employee", "sales_view")
    opportunity_id, company_id, address, _ = await _known_person()
    colleague = _address("asystent")
    await _contact(company_id, f"Asystent {_tag()}", colleague)
    await _received(rep, colleague, cc=(address,))

    await _sync()

    entry = await _person_now(opportunity_id)
    assert entry["contact_status"] == "in_progress"
    [event] = await _history(opportunity_id)
    assert event.new_value.endswith("z Outlooka: mail przychodzący")


async def test_auto_reply_and_invitation_response_are_not_contact() -> None:
    rep = await _user("employee", "sales_view")
    opportunity_id, _, address, _ = await _known_person()
    await _received(rep, address, subject="Automatyczna odpowiedź: urlop do 20.11")
    await _received(rep, address, subject="Accepted: Spotkanie zapoznawcze")
    await _sent(rep, address, subject="Zaakceptowano: Spotkanie zapoznawcze")

    report = await _sync()

    assert report.changes == []
    assert (await _person_now(opportunity_id))["contact_status"] == "not_contacted"


async def test_held_meeting_means_first_contact() -> None:
    rep = await _user("employee", "sales_view")
    opportunity_id, _, address, _ = await _known_person("in_progress")
    await _meeting(rep, rep.email, address, start=NOW - timedelta(hours=3))

    await _sync()

    entry = await _person_now(opportunity_id)
    assert entry["contact_status"] == "first_contact"
    assert entry["last_contact_at"] == "2026-11-10"
    [event] = await _history(opportunity_id)
    assert event.new_value.endswith("z Outlooka: spotkanie")


async def test_upcoming_and_cancelled_meetings_change_nothing() -> None:
    rep = await _user("employee", "sales_view")
    opportunity_id, _, address, _ = await _known_person()
    await _meeting(rep, address, start=NOW + timedelta(days=2))
    await _meeting(
        rep, address, start=NOW - timedelta(days=2), subject="Canceled: Spotkanie"
    )

    report = await _sync()

    assert report.changes == []
    assert (await _person_now(opportunity_id))["contact_status"] == "not_contacted"
    assert await _history(opportunity_id) == []


async def test_meeting_counts_once_it_has_passed() -> None:
    rep = await _user("employee", "sales_view")
    opportunity_id, _, address, _ = await _known_person()
    start = NOW + timedelta(days=2)
    await _meeting(rep, address, start=start)

    await _sync()
    assert (await _person_now(opportunity_id))["contact_status"] == "not_contacted"
    await _sync(now=start + timedelta(hours=1))

    entry = await _person_now(opportunity_id)
    assert (entry["contact_status"], entry["last_contact_at"]) == (
        "first_contact",
        "2026-11-12",
    )


async def test_last_contact_is_a_day_of_the_company_calendar() -> None:
    rep = await _user("employee", "sales_view")
    opportunity_id, _, address, _ = await _known_person()
    # 23:30 UTC to w Warszawie już następny dzień.
    await _sent(rep, address, at=datetime(2026, 11, 8, 23, 30, tzinfo=timezone.utc))

    await _sync()

    assert (await _person_now(opportunity_id))["last_contact_at"] == "2026-11-09"


async def test_history_from_import_counts_by_contact_and_unknown_sender_is_weaker() -> (
    None
):
    name_out, name_in = f"Prezes {_tag()}", f"Dyrektorka {_tag()}"
    opportunity_id, company_id = await _map_account(
        [_person(name_out, 1), _person(name_in, 2)]
    )
    await _imported_mail(company_id, await _contact(company_id, name_out), "out")
    # Mail przychodzący bez adresów: nie wiemy, czy osoba była nadawcą.
    await _imported_mail(company_id, await _contact(company_id, name_in), "in")

    await _sync()

    assert [entry["contact_status"] for entry in await _entries(opportunity_id)] == [
        "in_progress",
        "in_progress",
    ]


# ── Kogo automat nie rusza ────────────────────────────────────────────────


@pytest.mark.parametrize("status", ["first_contact", "regular_dialog"])
async def test_status_never_goes_back(status: str) -> None:
    rep = await _user("employee", "sales_view")
    opportunity_id, _, address, _ = await _known_person(
        status, last_contact_at="2026-10-01"
    )
    await _sent(rep, address)

    await _sync()

    entry = await _person_now(opportunity_id)
    assert entry["contact_status"] == status
    # Data idzie tylko w przód, a zmiana samej daty też zostaje w historii.
    assert entry["last_contact_at"] == MAIL_DAY
    [event] = await _history(opportunity_id)
    assert "status kontaktu" not in event.new_value


async def test_later_manual_date_and_higher_status_leave_no_trace() -> None:
    rep = await _user("employee", "sales_view")
    opportunity_id, _, address, _ = await _known_person(
        "regular_dialog", last_contact_at="2026-11-10"
    )
    before = await _person_now(opportunity_id)
    await _sent(rep, address)

    report = await _sync()

    assert report.changes == []
    assert await _person_now(opportunity_id) == before
    assert await _history(opportunity_id) == []


async def test_objection_on_the_map_or_on_the_contact_stops_the_automation() -> None:
    rep = await _user("employee", "sales_view")
    on_map, _, address_map, _ = await _known_person(do_not_contact=True)
    on_contact, company_id, address_contact, _ = await _known_person()
    async with AsyncSessionLocal() as db:
        await db.execute(
            update(SalesContact)
            .where(SalesContact.company_id == company_id)
            .values(do_not_contact_at=NOW - timedelta(days=5))
        )
        await db.commit()
    await _received(rep, address_map)
    await _received(rep, address_contact)

    report = await _sync()

    assert report.changes == []
    assert report.skipped_objection == 2
    for opportunity_id in (on_map, on_contact):
        entry = await _person_now(opportunity_id)
        assert entry["contact_status"] == "not_contacted"
        assert "last_contact_at" not in entry
        assert await _history(opportunity_id) == []


async def test_person_without_contact_needs_an_address_on_the_map() -> None:
    rep = await _user("employee", "sales_view")
    domain = f"fabryka-{_tag()}.example"
    company_id = await _company(domain=domain)
    opportunity_id, _ = await _map_account(
        [
            _person("Bez Kartoteki", 1),
            _person("Z Adresem", 2, email=f"z.adresem@{domain}"),
        ],
        company_id=company_id,
    )
    # Firma dopasowana po domenie: aktywność nie ma kontaktu.
    await _sent(rep, f"biuro@{domain}", cc=(f"Z.Adresem@{domain}",))

    await _sync()

    without, with_address = await _entries(opportunity_id)
    assert without["contact_status"] == "not_contacted"
    assert with_address["contact_status"] == "in_progress"
    assert len(await _history(opportunity_id)) == 1


async def test_contact_matched_by_atlas_id_counts_on_another_company_card() -> None:
    rep = await _user("employee", "sales_view")
    atlas_id = str(uuid.uuid4())
    opportunity_id, _ = await _map_account(
        [_person("Osoba Z Atlasa", 1, contact_id=atlas_id)]
    )
    address = _address()
    await _contact(
        await _company(),
        f"Inna Pisownia {_tag()}",
        address,
        external_ref=f"{ATLAS_CONTACT_REF}{atlas_id}",
    )
    await _sent(rep, address)

    await _sync()

    assert (await _person_now(opportunity_id))["contact_status"] == "in_progress"


async def test_closed_and_archived_opportunities_are_skipped() -> None:
    rep = await _user("employee", "sales_view")
    name, address = f"Dyrektor {_tag()}", _address()
    company_id = await _company()
    await _contact(company_id, name, address)
    closed, _ = await _map_account(
        [_person(name, 1)], company_id=company_id, stage=LOST, status="lost"
    )
    archived, _ = await _map_account([_person(name, 1)], company_id=company_id)
    async with AsyncSessionLocal() as db:
        await db.execute(
            update(SalesOpportunity)
            .where(SalesOpportunity.id == archived)
            .values(archived_at=NOW - timedelta(days=30))
        )
        await db.commit()
    await _received(rep, address)

    report = await _sync()

    assert report.open_maps == 0
    for opportunity_id in (closed, archived):
        assert (await _person_now(opportunity_id))["contact_status"] == "not_contacted"
        assert await _history(opportunity_id) == []


# ── Idempotencja, ręczna zmiana, dotyk ────────────────────────────────────


async def test_second_run_changes_nothing() -> None:
    rep = await _user("employee", "sales_view")
    opportunity_id, _, address, _ = await _known_person()
    await _sent(rep, address)
    await _sync()
    after_first = await _person_now(opportunity_id)

    report = await _sync()

    assert report.changes == []
    assert await _person_now(opportunity_id) == after_first
    assert len(await _history(opportunity_id)) == 1


async def test_dry_run_reports_and_writes_nothing() -> None:
    rep = await _user("employee", "sales_view")
    opportunity_id, _, address, _ = await _known_person()
    await _sent(rep, address)
    before = await _person_now(opportunity_id)

    report = await _sync(apply=False)

    assert [(c.old_status, c.new_status) for c in report.changes] == [
        ("not_contacted", "in_progress")
    ]
    assert (report.open_maps, report.people, report.people_with_contact) == (1, 1, 1)
    assert await _person_now(opportunity_id) == before
    assert await _history(opportunity_id) == []


async def test_manual_change_wins_until_a_new_mail(app_client) -> None:
    rep = await _user("employee", "sales_view")
    editor = await _sales_user("sales_edit")
    opportunity_id, _, address, _ = await _known_person()
    await _sent(rep, address)
    await _sync()

    # Handlowiec cofa status w oknie osoby: stary mail już go nie podniesie.
    [key] = entry_keys(await _entries(opportunity_id))
    resp = await app_client.patch(
        f"{URL}/{opportunity_id}/decision-map/{key}",
        json={"contact_status": "not_contacted"},
        headers=_headers(editor),
    )
    assert resp.status_code == 200, resp.text
    later = datetime.now(timezone.utc) + timedelta(minutes=5)
    assert (await _sync(now=later)).changes == []
    assert (await _person_now(opportunity_id))["contact_status"] == "not_contacted"

    await _received(rep, address, at=later + timedelta(hours=1))
    await _sync(now=later + timedelta(hours=2))

    assert (await _person_now(opportunity_id))["contact_status"] == "first_contact"


async def test_manual_edit_of_other_fields_does_not_hide_mail(app_client) -> None:
    rep = await _user("employee", "sales_view")
    editor = await _sales_user("sales_edit")
    opportunity_id, _, address, _ = await _known_person()
    await _sent(rep, address)
    [key] = entry_keys(await _entries(opportunity_id))
    resp = await app_client.patch(
        f"{URL}/{opportunity_id}/decision-map/{key}",
        json={"notes": "Wraca z urlopu w grudniu."},
        headers=_headers(editor),
    )
    assert resp.status_code == 200, resp.text

    await _sync()

    assert (await _person_now(opportunity_id))["contact_status"] == "in_progress"


async def test_write_reads_the_locked_row_not_a_copy_held_by_the_session(
    app_client,
) -> None:
    """Sesja przebiegu skrzynki żyje długo i mogła wczytać szansę wcześniej."""

    rep = await _user("employee", "sales_view")
    editor = await _sales_user("sales_edit")
    opportunity_id, _, address, _ = await _known_person()
    await _sent(rep, address)

    async with AsyncSessionLocal() as db:
        held = await db.get(SalesOpportunity, opportunity_id)
        [key] = entry_keys(decision_map.decision_entries(held.custom_fields))
        # W trakcie przebiegu handlowiec dopisuje notatkę w oknie osoby.
        resp = await app_client.patch(
            f"{URL}/{opportunity_id}/decision-map/{key}",
            json={"notes": "Wraca z urlopu w grudniu."},
            headers=_headers(editor),
        )
        assert resp.status_code == 200, resp.text
        await map_outlook.sync(db, now=NOW, apply=True)
        await db.commit()

    entry = await _person_now(opportunity_id)
    assert entry["contact_status"] == "in_progress"
    assert entry["notes"] == "Wraca z urlopu w grudniu."


async def test_status_change_does_not_move_the_last_touch() -> None:
    rep = await _user("employee", "sales_view")
    opportunity_id, _, address, _ = await _known_person()
    async with AsyncSessionLocal() as db:
        # Szansa starsza niż mail, żeby dotyk wynikał z maila, a nie z założenia.
        await db.execute(
            update(SalesOpportunity)
            .where(SalesOpportunity.id == opportunity_id)
            .values(created_at=NOW - timedelta(days=30))
        )
        await db.commit()
    await _sent(rep, address)
    # Dotyk liczony na chwilę po zapisie: zmiana wpisana „teraz” byłaby widoczna.
    later = datetime.now(timezone.utc) + timedelta(hours=1)
    touch_before = await _touch(opportunity_id, later)
    async with AsyncSessionLocal() as db:
        last_activity_before = (
            await db.get(SalesOpportunity, opportunity_id)
        ).last_activity_at

    await _sync()

    assert (await _person_now(opportunity_id))["contact_status"] == "in_progress"
    assert await _touch(opportunity_id, later) == touch_before == MAIL_AT
    async with AsyncSessionLocal() as db:
        opportunity = await db.get(SalesOpportunity, opportunity_id)
        assert opportunity.last_activity_at == last_activity_before


# ── Przebieg po synchronizacji skrzynki ───────────────────────────────────


async def test_live_pass_starts_at_go_live_and_leaves_history_to_the_script(
    monkeypatch,
) -> None:
    monkeypatch.setattr(map_outlook, "LIVE_SINCE_KEY", f"test-map-outlook-{_tag()}")
    rep = await _user("employee", "sales_view")
    opportunity_id, _, address, _ = await _known_person()
    go_live = NOW - timedelta(hours=4)
    await _sent(rep, address, at=go_live - timedelta(days=3))

    # Pierwszy przebieg tylko zapamiętuje start; mail sprzed startu to historia.
    async with AsyncSessionLocal() as db:
        assert await map_outlook.sync_live(db, now=go_live) == 0
        await db.commit()
    assert (await _person_now(opportunity_id))["contact_status"] == "not_contacted"

    await _received(rep, address, at=go_live + timedelta(hours=1))
    async with AsyncSessionLocal() as db:
        assert await map_outlook.sync_live(db, now=go_live + timedelta(hours=2)) == 1
        await db.commit()

    entry = await _person_now(opportunity_id)
    assert entry["contact_status"] == "first_contact"
    [event] = await _history(opportunity_id)
    assert event.new_value.endswith("z Outlooka: mail od osoby")


async def test_mailbox_pass_runs_the_automation_and_survives_its_failure(
    monkeypatch,
) -> None:
    calls = []

    async def boom(db, **kwargs):
        calls.append(kwargs)
        raise RuntimeError("awaria")

    monkeypatch.setattr(map_outlook, "sync_live", boom)
    rep = await _user("employee", "sales_view")
    async with AsyncSessionLocal() as db:
        await sync_mod._sync_sales_decision_maps(db, _conn(rep))
        # Błąd automatu nie zatruwa sesji, na której biegnie przebieg skrzynki.
        assert await db.scalar(select(1)) == 1
    assert len(calls) == 1


# ── Jednorazowe uzupełnienie wstecz ───────────────────────────────────────


def test_backfill_cli_default_is_a_dry_run() -> None:
    assert backfill._parse([]).apply is False


async def test_backfill_dry_run_reports_numbers_and_writes_nothing() -> None:
    rep = await _user("employee", "sales_view")
    opportunity_id, _, address, name = await _known_person()
    await _sent(rep, address)
    before = await _person_now(opportunity_id)

    report = await backfill.run(backfill.Options(), now=NOW)

    assert report.mode == "dry-run"
    assert (report.open_maps, report.people, report.people_with_contact) == (1, 1, 1)
    assert report.people_to_change == 1
    assert report.transitions == {"not_contacted->in_progress": 1}
    assert report.opportunity_ids == [opportunity_id]
    assert (report.changed, report.emails_filled) == (0, 0)
    assert await _person_now(opportunity_id) == before
    # Raport trafia do logu, który może być publiczny: bez nazwisk i adresów.
    dumped = json.dumps(backfill.asdict(report), ensure_ascii=False)
    assert name not in dumped and address not in dumped


async def test_backfill_dry_run_transaction_refuses_writes(monkeypatch) -> None:
    async def write_anyway(db, **kwargs):
        await db.execute(
            update(SalesActivity).values(subject="x").where(SalesActivity.id == 0)
        )

    monkeypatch.setattr(map_outlook, "sync", write_anyway)
    with pytest.raises(Exception, match="read-only"):
        await backfill.run(backfill.Options(), now=NOW)


async def test_backfill_apply_needs_the_counters_from_the_dry_run() -> None:
    rep = await _user("employee", "sales_view")
    opportunity_id, _, address, _ = await _known_person()
    await _sent(rep, address)

    with pytest.raises(backfill.Refused):
        await backfill.run(backfill.Options(apply=True), now=NOW)
    with pytest.raises(backfill.Refused):
        await backfill.run(
            backfill.Options(apply=True, expect_people=5, expect_emails=0), now=NOW
        )
    assert (await _person_now(opportunity_id))["contact_status"] == "not_contacted"

    report = await backfill.run(
        backfill.Options(apply=True, expect_people=1, expect_emails=0), now=NOW
    )

    assert (report.mode, report.changed) == ("apply", 1)
    assert (await _person_now(opportunity_id))["contact_status"] == "in_progress"
    again = await backfill.run(backfill.Options(), now=NOW)
    assert (again.people_to_change, again.contact_emails_to_fill) == (0, 0)


async def test_backfill_copies_map_address_to_an_empty_contact_only() -> None:
    """Reguła z 02.11.2026: mapa uzupełnia puste pola kontaktu, niczego nie nadpisuje."""

    empty, other, archived = (f"Osoba {_tag()}" for _ in range(3))
    address = _address()
    opportunity_id, company_id = await _map_account(
        [
            _person(empty, 1, email=address),
            _person(other, 2, email=_address("mapa")),
            _person(archived, 2, email=_address("archiwum")),
            _person("Bez Kontaktu", 3, email=_address("nikt")),
        ]
    )
    empty_id = await _contact(company_id, empty)
    kept = _address("kartoteka")
    other_id = await _contact(company_id, other, kept)
    archived_id = await _contact(company_id, archived, archived_at=NOW)

    planned = await backfill.run(backfill.Options(), now=NOW)
    assert planned.contact_emails_to_fill == 1
    assert planned.contact_ids_to_fill == [empty_id]

    report = await backfill.run(
        backfill.Options(apply=True, expect_people=0, expect_emails=1), now=NOW
    )

    assert report.emails_filled == 1
    async with AsyncSessionLocal() as db:
        emails = {
            contact.id: contact.email
            for contact in (
                await db.scalars(
                    select(SalesContact).where(
                        SalesContact.id.in_([empty_id, other_id, archived_id])
                    )
                )
            ).all()
        }
    assert emails == {empty_id: address, other_id: kept, archived_id: None}
    [event] = await _history(opportunity_id, "decision_map_contact")
    assert (event.user_id, event.new_value) == (None, f"{empty}: e-mail")
