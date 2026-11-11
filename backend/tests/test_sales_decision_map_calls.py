"""Mapa decyzyjna ← telefon: status kontaktu osoby po zapisanej rozmowie.

Decyzje Artura z 10.11.2026: rozmowa, w której osoba odebrała, daje „pierwszy
kontakt”; próba bez rozmowy („Nie odebrał”, „Oddzwonić”) i telefon z importu bez
wyniku dają „w toku”; „Nie kontaktować” to sprzeciw, nie kontakt. Reszta reguł jak
przy poczcie (``test_sales_decision_map_outlook.py``): status się nie cofa, sprzeciw
i szansa zamknięta wyłączają automat, ręczna zmiana ma pierwszeństwo.

Rozmowy idą przez prawdziwe trasy zapisu. Dane są fikcyjne.
"""

from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional

import pytest
from sqlalchemy import update

from app.core.database import AsyncSessionLocal
from app.core.scheduling import business_date
from app.models.sales import SalesActivity, SalesOpportunity
from app.services import sales_schema as schema
from app.services.sales import decision_map_outlook as map_outlook
from app.services.sales import factories
from app.services.sales.motion import entry_keys
from scripts import sales_decision_map_outlook as backfill
from tests.test_sales_companies_api import _headers
from tests.test_sales_companies_api import _user as _sales_user
from tests.test_sales_decision_map_outlook import (  # noqa: F401 — fixture modułu
    NOW,
    URL,
    _contact,
    _entries,
    _history,
    _map_account,
    _person_now,
    _sync,
    only_own_maps,
)
from tests.test_sales_factories import LOST, _person
from tests.test_sales_outlook_sync import _tag

COMPANY_URL = "/api/sales/companies"
CALL_AT = NOW - timedelta(days=1)
CALL_DAY = "2026-11-09"
TALK = "z telefonu: rozmowa"
ATTEMPT = "z telefonu: próba bez rozmowy"
NO_OUTCOME = "z telefonu: wpis bez wyniku"


def _today() -> str:
    return business_date(datetime.now(timezone.utc)).isoformat()


async def _call_from_card(
    app_client, opportunity_id: int, outcome: str, **person: Any
) -> dict[str, Any]:
    editor = await _sales_user("sales_edit")
    resp = await app_client.post(
        f"{URL}/{opportunity_id}/calls",
        json={"outcome": outcome, **person},
        headers=_headers(editor),
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


async def _saved_call(
    company_id: int,
    contact_id: Optional[int],
    outcome: Optional[str],
    at: datetime = CALL_AT,
    **fields: Any,
) -> None:
    """Telefon w dzienniku bez trasy: import albo zapis, który idzie inną ścieżką."""

    values = {"occurred_at": at, "done_at": at, **fields}
    async with AsyncSessionLocal() as db:
        db.add(
            SalesActivity(
                kind="call",
                outcome=outcome,
                company_id=company_id,
                contact_id=contact_id,
                **values,
            )
        )
        await db.commit()


async def _person_with_contact(
    status: str = "not_contacted", **entry: Any
) -> tuple[int, int, int, str]:
    """Konto z jedną osobą z kartoteki; (szansa, firma, kontakt, nazwisko)."""

    name = f"Dyrektor {_tag()}"
    opportunity_id, company_id = await _map_account([_person(name, 1, status, **entry)])
    return opportunity_id, company_id, await _contact(company_id, name), name


async def _only_key(opportunity_id: int) -> str:
    [key] = entry_keys(await _entries(opportunity_id))
    return key


# ── Który wynik daje który status ─────────────────────────────────────────


@pytest.mark.parametrize(
    ("outcome", "status"),
    [
        ("connected", "first_contact"),
        ("wants_offer", "first_contact"),
        ("not_now", "first_contact"),
        # Wyniki kolejki dzwonienia: rozmowa się odbyła.
        ("offer_sent", "first_contact"),
        ("meeting_booked", "first_contact"),
        ("no_answer", "in_progress"),
        ("call_back", "in_progress"),
        # Import z Atlasa nie niesie wyniku: nie wiemy, czy ktoś odebrał.
        (None, "in_progress"),
    ],
)
def test_outcome_table(outcome: Optional[str], status: str) -> None:
    signal = map_outlook.call_signal(outcome)
    assert signal is not None and signal.status == status


def test_objection_and_unknown_outcome_are_not_contact() -> None:
    assert map_outlook.call_signal("do_not_contact") is None
    assert map_outlook.call_signal("cos_nowego") is None


def test_every_outcome_of_the_dictionary_has_a_decision() -> None:
    """Nowy wynik w słowniku bez decyzji, co robi z mapą, ma zatrzymać PR."""

    undecided = [
        outcome
        for outcome in schema.CALL_OUTCOMES
        if outcome != "do_not_contact" and map_outlook.call_signal(outcome) is None
    ]
    assert undecided == []


def test_excel_outcomes_count_like_their_neighbours() -> None:
    assert map_outlook.call_signal("not_interested") == map_outlook.call_signal(
        "not_now"
    )
    assert map_outlook.call_signal("bad_contact") == map_outlook.call_signal(
        "no_answer"
    )


@pytest.mark.parametrize(
    ("outcome", "status", "source"),
    [
        ("connected", "first_contact", TALK),
        ("wants_offer", "first_contact", TALK),
        ("not_now", "first_contact", TALK),
        ("no_answer", "in_progress", ATTEMPT),
        ("call_back", "in_progress", ATTEMPT),
    ],
)
async def test_call_from_the_card_moves_the_person_at_once(
    app_client, outcome: str, status: str, source: str
) -> None:
    # Osoba tylko na mapie, bez kontaktu w kartotece: łączy ją sam zapis z karty.
    name = f"Dyrektor {_tag()}"
    opportunity_id, _ = await _map_account([_person(name, 1)])
    key_before = await _only_key(opportunity_id)

    body = await _call_from_card(
        app_client, opportunity_id, outcome, person_key=key_before
    )

    entry = await _person_now(opportunity_id)
    assert entry["contact_status"] == status
    assert entry["last_contact_at"] == _today()
    assert factories.is_contacted(entry)
    # Automat to nie ręczna poprawka: znacznika pierwszeństwa nie stawia.
    assert "contact_edited_at" not in entry
    [shown] = body["atlas_motion"]["it_factory"]["decision_map"]
    assert shown["contact_status"] == status
    assert shown["key"] != key_before
    [event] = await _history(opportunity_id)
    assert event.user_id is None
    assert (
        event.old_value == f"{name} — status kontaktu: bez kontaktu; ostatni kontakt: —"
    )
    assert event.new_value.endswith(f"ostatni kontakt: {_today()} · {source}")


async def test_call_with_a_contact_moves_the_matching_person(app_client) -> None:
    other = f"Prezes {_tag()}"
    name = f"Dyrektor {_tag()}"
    opportunity_id, company_id = await _map_account(
        [_person(other, 1), _person(name, 2)]
    )
    contact_id = await _contact(company_id, name)

    await _call_from_card(
        app_client, opportunity_id, "connected", contact_id=contact_id
    )

    untouched, called = await _entries(opportunity_id)
    assert untouched["contact_status"] == "not_contacted"
    assert called["contact_status"] == "first_contact"
    assert len(await _history(opportunity_id)) == 1


async def test_call_without_a_person_changes_no_map(app_client) -> None:
    opportunity_id, _ = await _map_account([_person(f"Dyrektor {_tag()}", 1)])

    await _call_from_card(app_client, opportunity_id, "connected")

    assert (await _person_now(opportunity_id))["contact_status"] == "not_contacted"
    assert await _history(opportunity_id) == []


# ── Czego automat nie rusza ───────────────────────────────────────────────


async def test_objection_call_is_not_contact(app_client) -> None:
    opportunity_id, _ = await _map_account([_person(f"Dyrektor {_tag()}", 1)])

    await _call_from_card(
        app_client,
        opportunity_id,
        "do_not_contact",
        person_key=await _only_key(opportunity_id),
    )

    entry = await _person_now(opportunity_id)
    assert entry["do_not_contact"] is True
    assert entry["contact_status"] == "not_contacted"
    assert "last_contact_at" not in entry
    assert await _history(opportunity_id) == []
    assert (await _sync(now=datetime.now(timezone.utc))).changes == []


@pytest.mark.parametrize("status", ["first_contact", "regular_dialog"])
async def test_attempt_never_lowers_the_status(app_client, status: str) -> None:
    opportunity_id, _ = await _map_account(
        [_person(f"Dyrektor {_tag()}", 1, status, last_contact_at="2026-10-01")]
    )

    await _call_from_card(
        app_client,
        opportunity_id,
        "no_answer",
        person_key=await _only_key(opportunity_id),
    )

    entry = await _person_now(opportunity_id)
    assert entry["contact_status"] == status
    # Data idzie w przód także wtedy, gdy status zostaje.
    assert entry["last_contact_at"] == _today()
    [event] = await _history(opportunity_id)
    assert "status kontaktu" not in event.new_value
    assert event.new_value.endswith(ATTEMPT)


async def test_person_flagged_on_the_map_is_left_alone(app_client) -> None:
    # Flaga leży na wpisie mapy, a kontakt doszedł później i sprzeciwu nie ma.
    opportunity_id, _, contact_id, _ = await _person_with_contact(do_not_contact=True)
    before = await _person_now(opportunity_id)

    await _call_from_card(
        app_client, opportunity_id, "connected", contact_id=contact_id
    )

    assert await _person_now(opportunity_id) == before
    report = await _sync(now=datetime.now(timezone.utc) + timedelta(minutes=5))
    assert report.changes == []
    assert await _person_now(opportunity_id) == before
    assert await _history(opportunity_id) == []


async def test_closed_opportunity_is_left_alone(app_client) -> None:
    opportunity_id, _ = await _map_account(
        [_person(f"Dyrektor {_tag()}", 1)], stage=LOST, status="lost"
    )

    await _call_from_card(
        app_client,
        opportunity_id,
        "connected",
        person_key=await _only_key(opportunity_id),
    )

    assert (await _person_now(opportunity_id))["contact_status"] == "not_contacted"
    assert await _history(opportunity_id) == []


async def test_planned_call_is_not_contact() -> None:
    opportunity_id, company_id, contact_id, _ = await _person_with_contact()
    # Telefon z terminem bez „zrobione” to pozycja listy zadań, nie rozmowa.
    await _saved_call(
        company_id, contact_id, None, done_at=None, due_at=NOW + timedelta(days=1)
    )

    assert (await _sync()).changes == []
    assert (await _person_now(opportunity_id))["contact_status"] == "not_contacted"


# ── Idempotencja i ręczna zmiana ──────────────────────────────────────────


async def test_pass_after_the_card_changes_nothing(app_client) -> None:
    opportunity_id, company_id, contact_id, _ = await _person_with_contact()
    await _call_from_card(
        app_client, opportunity_id, "connected", contact_id=contact_id
    )
    after_call = await _person_now(opportunity_id)

    later = datetime.now(timezone.utc) + timedelta(minutes=5)
    report = await _sync(now=later)

    assert report.changes == []
    assert report.calls == {"connected": 1}
    assert await _person_now(opportunity_id) == after_call
    assert len(await _history(opportunity_id)) == 1


async def test_manual_change_wins_until_a_new_call(app_client) -> None:
    editor = await _sales_user("sales_edit")
    opportunity_id, company_id, contact_id, _ = await _person_with_contact()
    await _call_from_card(
        app_client, opportunity_id, "connected", contact_id=contact_id
    )

    # Handlowiec cofa status w oknie osoby: zapisana rozmowa już go nie podniesie.
    resp = await app_client.patch(
        f"{URL}/{opportunity_id}/decision-map/{await _only_key(opportunity_id)}",
        json={"contact_status": "not_contacted"},
        headers=_headers(editor),
    )
    assert resp.status_code == 200, resp.text
    later = datetime.now(timezone.utc) + timedelta(minutes=5)
    assert (await _sync(now=later)).changes == []
    assert (await _person_now(opportunity_id))["contact_status"] == "not_contacted"

    await _call_from_card(
        app_client, opportunity_id, "no_answer", contact_id=contact_id
    )

    assert (await _person_now(opportunity_id))["contact_status"] == "in_progress"


# ── Rozmowy spoza karty szansy: przebieg po synchronizacji skrzynki ───────


async def test_call_logged_at_the_company_counts_on_the_next_pass(app_client) -> None:
    editor = await _sales_user("sales_edit")
    opportunity_id, company_id, contact_id, _ = await _person_with_contact()
    async with AsyncSessionLocal() as db:
        await db.execute(
            update(SalesOpportunity)
            .where(SalesOpportunity.id == opportunity_id)
            .values(last_activity_at=NOW - timedelta(days=30))
        )
        await db.commit()

    resp = await app_client.post(
        f"{COMPANY_URL}/{company_id}/calls",
        json={"outcome": "connected", "contact_id": contact_id},
        headers=_headers(editor),
    )
    assert resp.status_code == 204, resp.text
    # Telefon przy firmie nie ma szansy pod blokadą: mapę przesuwa dopiero przebieg.
    assert (await _person_now(opportunity_id))["contact_status"] == "not_contacted"

    report = await _sync(now=datetime.now(timezone.utc) + timedelta(minutes=5))

    assert [(c.old_status, c.new_status) for c in report.changes] == [
        ("not_contacted", "first_contact")
    ]
    entry = await _person_now(opportunity_id)
    assert (entry["contact_status"], entry["last_contact_at"]) == (
        "first_contact",
        _today(),
    )
    [event] = await _history(opportunity_id)
    assert (event.user_id, event.new_value.endswith(TALK)) == (None, True)
    # Zmiana statusu to nie dotyk szansy.
    async with AsyncSessionLocal() as db:
        opportunity = await db.get(SalesOpportunity, opportunity_id)
        assert opportunity.last_activity_at == NOW - timedelta(days=30)


async def test_imported_call_without_outcome_means_in_progress() -> None:
    opportunity_id, company_id, contact_id, _ = await _person_with_contact()
    await _saved_call(
        company_id,
        contact_id,
        None,
        external_source="atlas",
        external_ref=f"atlas:activities:{_tag()}",
    )

    report = await _sync()

    assert report.calls == {"bez_wyniku": 1}
    entry = await _person_now(opportunity_id)
    assert (entry["contact_status"], entry["last_contact_at"]) == (
        "in_progress",
        CALL_DAY,
    )
    [event] = await _history(opportunity_id)
    assert event.new_value.endswith(NO_OUTCOME)


async def test_talk_outweighs_a_later_attempt_and_the_date_follows_the_latest() -> None:
    opportunity_id, company_id, contact_id, _ = await _person_with_contact()
    await _saved_call(company_id, contact_id, "connected", CALL_AT - timedelta(days=3))
    await _saved_call(company_id, contact_id, "no_answer", CALL_AT)

    await _sync()

    entry = await _person_now(opportunity_id)
    assert (entry["contact_status"], entry["last_contact_at"]) == (
        "first_contact",
        CALL_DAY,
    )
    [event] = await _history(opportunity_id)
    assert event.new_value.endswith(TALK)


async def test_call_before_a_manual_edit_is_ignored() -> None:
    opportunity_id, company_id, contact_id, _ = await _person_with_contact(
        contact_edited_at=NOW.isoformat()
    )
    await _saved_call(company_id, contact_id, "connected", CALL_AT)

    assert (await _sync(now=NOW + timedelta(hours=1))).changes == []

    await _saved_call(company_id, contact_id, "call_back", NOW + timedelta(minutes=30))
    await _sync(now=NOW + timedelta(hours=1))

    assert (await _person_now(opportunity_id))["contact_status"] == "in_progress"


async def test_live_pass_counts_calls_since_go_live(monkeypatch) -> None:
    monkeypatch.setattr(map_outlook, "LIVE_SINCE_KEY", f"test-map-calls-{_tag()}")
    opportunity_id, company_id, contact_id, _ = await _person_with_contact()
    go_live = NOW - timedelta(hours=4)
    await _saved_call(company_id, contact_id, "connected", go_live - timedelta(days=3))

    # Pierwszy przebieg tylko zapamiętuje start; starsza rozmowa to historia dla skryptu.
    async with AsyncSessionLocal() as db:
        assert await map_outlook.sync_live(db, now=go_live) == 0
        await db.commit()
    assert (await _person_now(opportunity_id))["contact_status"] == "not_contacted"

    await _saved_call(company_id, contact_id, "no_answer", go_live + timedelta(hours=1))
    async with AsyncSessionLocal() as db:
        assert await map_outlook.sync_live(db, now=go_live + timedelta(hours=2)) == 1
        await db.commit()

    assert (await _person_now(opportunity_id))["contact_status"] == "in_progress"


# ── Jednorazowe uzupełnienie wstecz ───────────────────────────────────────


async def test_backfill_covers_saved_calls_and_reports_numbers_only() -> None:
    opportunity_id, company_id, contact_id, name = await _person_with_contact()
    await _saved_call(company_id, contact_id, None)
    before = await _person_now(opportunity_id)

    report = await backfill.run(backfill.Options(), now=NOW)

    assert report.call_events == {"bez_wyniku": 1}
    assert report.people_to_change == 1
    assert report.transitions == {"not_contacted->in_progress": 1}
    assert await _person_now(opportunity_id) == before
    assert name not in json.dumps(backfill.asdict(report), ensure_ascii=False)


# ── Kolejność importów ────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "module",
    [
        "app.services.sales.companies",
        "scripts.sales_signals_run",
        "app.services.sales.outlook_activities",
        "app.services.sales.meeting_decisions",
    ],
)
def test_automation_does_not_close_an_import_cycle(module: str) -> None:
    """``m365.sync`` importował automaty na górze pliku i proces, który zaczynał od
    ``companies``, kończył się błędem importu, choć sama aplikacja wstawała.

    Mapa decyzyjna wracała przez ``decision_map`` → ``companies``, przypinanie
    spotkań przez ``meeting_autopin`` → ``handoff`` → ``companies``, który bierze
    ``COMPANY_DOMAIN_SQL`` z niedokończonego ``outlook_activities``."""

    result = subprocess.run(
        [sys.executable, "-c", f"import {module}"],
        capture_output=True,
        text=True,
        cwd=Path(__file__).resolve().parents[1],
        check=False,
    )
    assert result.returncode == 0, result.stderr[-600:]
