"""Mapy decydentów od bota (``people``) bez bazy: raport, wiersze przeglądu, harmonogram.

Reguły: ``docs/claude/sprzedaz/mapy-decydentow-od-bota.md``. Nazwy i adresy
w testach są fikcyjne (repo jest publiczne).
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest
from pydantic import ValidationError

from app.core.config import settings
from app.models.sales import SalesBotResult, SalesCompany
from app.services import sales_schema
from app.services.sales import bot_tasks, research_import
from app.services.sales.bot_tasks import people
from app.tasks import sales_signals as loop

TODAY = date(2026, 11, 12)


def _person(**over) -> dict:
    base = {
        "full_name": "Jan Fikcyjny",
        "title": "Head of Data",
        "area": "data",
        "source_url": "https://firma.example/zespol",
        "published": "2026-10-01",
    }
    return {**base, **over}


def _report(*persons: dict, ref: int = 1) -> people.PeopleReport:
    return people.PeopleReport.model_validate(
        {"checked_firms": 1, "firms": [{"company_ref": ref, "people": list(persons)}]}
    )


def _one(**over) -> people.BotPerson:
    return _report(_person(**over)).firms[0].people[0]


# ── Raport: kontakty tylko ze źródłem ──────────────────────────────────────


def test_contact_without_its_own_source_is_dropped_but_person_stays() -> None:
    person = _one(email="jan@firma.example", phone="+48 600 100 200")
    assert (person.email, person.phone) == (None, None)
    assert person.full_name == "Jan Fikcyjny"
    assert person.warnings == [people.EMAIL_DROPPED, people.PHONE_DROPPED]


def test_contact_printed_on_a_source_is_kept_with_that_source() -> None:
    person = _one(
        email="Jan@Firma.example",
        email_source_url="firma.example/kontakt",
        phone="+48 600 100 200",
        phone_source_url="https://firma.example/kontakt",
    )
    assert person.email == "jan@firma.example"
    assert person.email_source_url == "https://firma.example/kontakt"
    assert person.phone == "+48 600 100 200"
    assert person.warnings == []


def test_malformed_contact_and_non_http_source_are_dropped() -> None:
    person = _one(
        email="jan(at)firma",
        email_source_url="https://firma.example/kontakt",
        phone="12",
        phone_source_url="javascript:alert(1)",
    )
    assert (person.email, person.email_source_url) == (None, None)
    assert (person.phone, person.phone_source_url) == (None, None)
    assert len(person.warnings) == 2


def test_linkedin_only_as_a_profile_link() -> None:
    assert _one(linkedin_url="linkedin.com/in/jan").linkedin_url == (
        "https://linkedin.com/in/jan"
    )
    assert _one(linkedin_url="https://pl.linkedin.com/in/jan").linkedin_url
    other = _one(linkedin_url="https://linkedin.com.evil.example/in/jan")
    assert other.linkedin_url is None
    assert other.warnings == [people.LINKEDIN_DROPPED]


def test_person_needs_an_http_source_and_no_extra_fields() -> None:
    with pytest.raises(ValidationError):
        _one(source_url="javascript:alert(1)")
    with pytest.raises(ValidationError):
        _one(source_url="")
    with pytest.raises(ValidationError):
        _one(cv="tekst CV")
    with pytest.raises(ValidationError):
        _one(full_name="   ")
    with pytest.raises(ValidationError):
        _report(*[_person(full_name=f"Osoba {i}") for i in range(16)])


# ── Wybór osób: znane i powtórzone odpadają ───────────────────────────────


def test_known_and_repeated_people_are_dropped_and_lines_renumbered() -> None:
    report = _report(
        _person(full_name="Fikcyjny Jan"),  # na mapie jako „Jan Fikcyjny”
        _person(full_name="Anna Przykładowa"),
        _person(full_name="Przykładowa Anna"),  # powtórzona w raporcie
        _person(
            full_name="Ewa Testowa",
            email="ewa@firma.example",
            email_source_url="https://firma.example/kontakt",
        ),
        # Ten sam adres ze źródłem pod inną pisownią nazwiska: ta sama osoba.
        _person(
            full_name="E. Testowa",
            email="EWA@firma.example",
            email_source_url="https://firma.example/kontakt",
        ),
    )
    known = people.person_marks("Jan Fikcyjny", None)
    picked, dropped = people.pick_new_people(
        report.firms[0].people, known=known, today=TODAY
    )
    assert [(p["line"], p["full_name"]) for p in picked] == [
        (1, "Anna Przykładowa"),
        (2, "Ewa Testowa"),
    ]
    assert dropped["known"] == 1
    assert dropped["duplicates"] == 2


def test_future_published_date_is_cleared() -> None:
    report = _report(_person(published=(TODAY + timedelta(days=5)).isoformat()))
    [picked], _ = people.pick_new_people(
        report.firms[0].people, known=set(), today=TODAY
    )
    assert picked["published"] is None
    report = _report(_person())
    [picked], _ = people.pick_new_people(
        report.firms[0].people, known=set(), today=TODAY
    )
    assert picked["published"] == "2026-10-01"


# ── Wynik → wiersze przeglądu listy z researchu ───────────────────────────


def _result(*persons: dict, outcomes: dict | None = None) -> SalesBotResult:
    return SalesBotResult(
        id=7,
        run_id=1,
        kind="people",
        company_id=11,
        status="new",
        payload={"people": list(persons), "outcomes": outcomes or {}},
    )


def _stored(line: int, **over) -> dict:
    report = _report(_person(**over))
    [stored], _ = people.pick_new_people(
        report.firms[0].people, known=set(), today=TODAY
    )
    return {**stored, "line": line}


def test_result_converts_to_import_rows_with_level_and_warnings() -> None:
    company = SalesCompany(id=11, name="Fabryka Testowa", domain="fabryka.example")
    result = _result(
        _stored(1, title="Chief Data Officer"),
        _stored(2, full_name="Anna Przykładowa", title="Kierownik", level_hint=2),
        _stored(3, full_name="Ewa Testowa", title="Analityk", email="ewa@x.example"),
    )
    rows = people.to_rows(result, company)
    assert [(r.line, r.company, r.decision_level) for r in rows] == [
        (1, "Fabryka Testowa", 1),
        (2, "Fabryka Testowa", 2),
        (3, "Fabryka Testowa", 3),
    ]
    assert all(r.confidence == "to_verify" for r in rows)
    assert rows[0].source_url == "https://firma.example/zespol"
    assert rows[0].domain == "fabryka.example"
    assert rows[2].email is None and rows[2].warnings == (people.EMAIL_DROPPED,)


def test_open_count_follows_handled_outcomes() -> None:
    result = _result(
        _stored(1),
        _stored(2, full_name="Anna Przykładowa"),
        _stored(3, full_name="Ewa Testowa"),
        outcomes={"1": "added", "2": "error"},
    )
    assert people.decided_lines(result) == {1: "added", 2: "error"}
    # „error” nie zamyka wiersza: można spróbować jeszcze raz.
    assert people.open_count(result) == 2


def _card(card_id: int, *, account: bool = False, **over) -> research_import.Card:
    return research_import.Card(
        id=card_id,
        name=f"Karta {card_id}",
        exact=over.pop("exact", True),
        contacts=0,
        account=research_import.AccountInfo(
            opportunity_id=card_id * 10,
            title="Konto",
            stage_name="Mapa decyzyjna w trakcie",
            status="open",
            counts=None,  # type: ignore[arg-type]
        )
        if account
        else None,
        archived_account=False,
        client=over.pop("client", None),
        blocked=over.pop("blocked", False),
    )


def _company_plan(*cards: research_import.Card, state: str = "choose"):
    return research_import.CompanyPlan(
        key="karta",
        name="Karta",
        state=state,
        company_id=None,
        cards=cards,
        client=None,
    )


def test_pin_targets_the_asked_card_by_the_import_rules() -> None:
    pinned = people.pin(_company_plan(_card(1), _card(2, exact=False)), 1)
    assert (pinned.state, pinned.company_id) == ("card", 1)
    pinned = people.pin(_company_plan(_card(1, account=True), _card(2)), 1)
    assert (pinned.state, pinned.company_id) == ("account", 1)
    # Inna karta marki ma konto w lejku: kartę wskazuje człowiek.
    pinned = people.pin(_company_plan(_card(1), _card(2, account=True)), 1)
    assert (pinned.state, pinned.company_id) == ("choose", None)
    blocked = people.pin(_company_plan(_card(1, blocked=True)), 1)
    assert blocked.state == "blocked"
    client = research_import.CompanyPlan(
        key="k", name="K", state="client", company_id=None, cards=(), client=None
    )
    assert people.pin(client, 1) is client


# ── Polecenie i rejestr ───────────────────────────────────────────────────


def test_task_text_states_the_source_rules_and_never_a_login() -> None:
    text = people._task_text(None, bot_tasks.TaskContext(firms=(), request={}))
    lowered = text.lower()
    for rule in (
        "publicznych źródłach",
        "source_url",
        "nigdy nie zgaduj adresów e-mail",
        "nie zbieraj danych z linkedina",
        "nigdzie się nie loguj",
    ):
        assert rule in lowered
    assert "zaloguj" not in lowered
    assert "hasło" not in lowered


def test_people_kind_is_registered_known_to_the_database_and_behind_the_flag(
    monkeypatch,
) -> None:
    assert bot_tasks.REGISTRY["people"] is people.PEOPLE
    assert "people" in sales_schema.BOT_RUN_KINDS
    assert people.PEOPLE.request_model is None and people.PEOPLE.needs_firms
    monkeypatch.setattr(settings, "SALES_BOT_TASKS_ENABLED", False)
    assert not bot_tasks.allowed_to_start("people")
    monkeypatch.setattr(settings, "SALES_BOT_TASKS_ENABLED", True)
    assert bot_tasks.allowed_to_start("people")


def test_reply_is_numbers_only() -> None:
    summary = {
        "firms": 1,
        "people": 2,
        "results": 1,
        "results_new": 1,
        "no_people": 0,
        "dropped": {"unknown_company": 0, "known": 1, "duplicates": 0, "contacts": 1},
    }
    assert people.PEOPLE.reply(summary) == summary


# ── Tygodniowy przegląd w pętli ───────────────────────────────────────────

WARSAW = ZoneInfo("Europe/Warsaw")


class _Db:
    async def scalar(self, statement):
        return None


def _patch_loop(monkeypatch, started: list) -> None:
    async def zero(*_a, **_k):
        return 0

    async def none(*_a, **_k):
        return []

    async def empty(*_a, **_k):
        return set()

    async def targets(_db, *, now, limit):
        assert limit == people.MAX_WEEKLY_FIRMS
        return [5, 6]

    class _Run:
        status = "started"

    async def start(_db, kind, company_ids, **_k):
        started.append((kind, list(company_ids)))
        return _Run()

    monkeypatch.setattr(loop.signals, "expire_runs", zero)
    monkeypatch.setattr(loop.signals, "start_run", start)
    monkeypatch.setattr(loop.targets, "pilot_company_ids", none)
    monkeypatch.setattr(loop.targets, "new_company_ids", none)
    monkeypatch.setattr(loop.targets, "refresh_company_ids", none)
    monkeypatch.setattr(loop.targets, "recently_sent", empty)
    monkeypatch.setattr(loop.targets, "people_company_ids", targets)


@pytest.mark.asyncio
async def test_weekly_people_run_only_with_the_flag_on_monday_from_eight(
    monkeypatch,
) -> None:
    started: list = []
    _patch_loop(monkeypatch, started)
    monday = datetime(2026, 11, 16, 8, 5, tzinfo=WARSAW)
    now = monday.astimezone(timezone.utc)

    monkeypatch.setattr(settings, "SALES_BOT_TASKS_ENABLED", False)
    done = await loop.tick(_Db(), now=now, local=monday)
    assert done["people"] == 0 and started == []

    monkeypatch.setattr(settings, "SALES_BOT_TASKS_ENABLED", True)
    early = datetime(2026, 11, 16, 7, 50, tzinfo=WARSAW)
    await loop.tick(_Db(), now=early.astimezone(timezone.utc), local=early)
    assert ("people", [5, 6]) not in started

    done = await loop.tick(_Db(), now=now, local=monday)
    assert done["people"] == 2
    assert ("people", [5, 6]) in started

    started.clear()
    tuesday = datetime(2026, 11, 17, 9, 0, tzinfo=WARSAW)
    await loop.tick(_Db(), now=tuesday.astimezone(timezone.utc), local=tuesday)
    assert all(kind != "people" for kind, _ in started)
