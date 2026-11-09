"""„Mój dzień” w Sprzedaży: cztery sekcje kolejki, osoba i numer, sekcja w mailu.

Baza testowa jest wspólna dla przebiegu, więc każdy test ma własnego handlowca
i patrzy tylko na jego kolejkę.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal
from typing import Any, Optional
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import select

from app.api import sales_my_day as sales_my_day_api
from app.core.database import AsyncSessionLocal
from app.core.scheduling import DEFAULT_TZ, business_today, is_business_day, local_now
from app.models.sales import (
    SalesActivity,
    SalesCompany,
    SalesCompanyContact,
    SalesContact,
    SalesOpportunity,
    SalesPipeline,
    SalesPipelineStage,
)
from app.models.user import User, UserRole
from app.services import daily_digest, notification_email_prefs
from app.services.effective_access import resolve_effective_access
from app.services.sales import my_day
from app.tasks import daily_digest_email
from tests.test_sales_companies_api import _headers, _user

URL = "/api/sales/my-day"
CONTACTS = "/api/sales/contacts"
ACTIVITIES = "/api/sales/activities"
MAIL = "msgraph-mail"
EVENT = "msgraph-event"
ZONE = ZoneInfo(DEFAULT_TZ)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _day_start() -> datetime:
    return datetime.combine(business_today(), time.min, tzinfo=ZONE)


def _noon(day: date) -> datetime:
    return datetime.combine(day, time(12), tzinfo=ZONE)


def _today_noon() -> datetime:
    """Spotkanie „dziś” niezależne od pory biegu: ``_now() + 1 h`` po 23:00 to już jutro."""

    return _noon(business_today())


def _days_with_gap(gap: int) -> date:
    """Dzień, od którego do dziś upłynęło dokładnie ``gap`` dni roboczych."""

    day = business_today()
    counted = 0
    while counted < gap:
        if is_business_day(_noon(day)):
            counted += 1
        day -= timedelta(days=1)
    return day


async def _company(name: str = "Firma", **fields: Any) -> int:
    marker = uuid.uuid4().hex[:10]
    async with AsyncSessionLocal() as db:
        company = SalesCompany(
            name=f"{name} {marker}",
            normalized_name=fields.pop("normalized_name", f"{name} {marker}".lower()),
            **fields,
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
    owner_id: int,
    company_id: int,
    *,
    stage: str = "offer-sent",
    value: Optional[str] = None,
    age_days: int = 0,
    title: str = "Zespół analityków",
    status: str = "open",
    primary_contact_id: Optional[int] = None,
) -> int:
    pipeline_id, stage_id = await _stage(stage)
    # Południe dnia sprzed ``age_days`` dni: o 23:00 w Warszawie „teraz minus 20 dni”
    # wypadało przez zmianę czasu na inny dzień kalendarza firmy (19 zamiast 20).
    created = _noon(business_today() - timedelta(days=age_days)) if age_days else _now()
    async with AsyncSessionLocal() as db:
        opportunity = SalesOpportunity(
            company_id=company_id,
            pipeline_id=pipeline_id,
            stage_id=stage_id,
            title=title,
            owner_user_id=owner_id,
            status=status,
            value=Decimal(value) if value else None,
            created_at=created,
            primary_contact_id=primary_contact_id,
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


async def _contact(company_id: Optional[int], **fields: Any) -> int:
    async with AsyncSessionLocal() as db:
        contact = SalesContact(
            company_id=company_id,
            full_name=fields.pop("full_name", f"Osoba {uuid.uuid4().hex[:6]}"),
            **fields,
        )
        db.add(contact)
        await db.commit()
        if company_id is not None:
            db.add(
                SalesCompanyContact(
                    company_id=company_id, contact_id=contact.id, is_primary=True
                )
            )
            await db.commit()
        return contact.id


async def _mail(company_id: int, when: datetime, **fields: Any) -> int:
    return await _activity(
        kind="email",
        external_source=MAIL,
        external_id=fields.pop("external_id", uuid.uuid4().hex),
        direction=fields.pop("direction", "in"),
        subject=fields.pop("subject", "Pytanie o ofertę"),
        company_id=company_id,
        occurred_at=when,
        **fields,
    )


async def _day(app_client: Any, user: Any) -> dict[str, Any]:
    resp = await app_client.get(URL, headers=_headers(user))
    assert resp.status_code == 200, resp.text
    return resp.json()


async def _prep_at(user: Any, now: datetime) -> dict[str, Any]:
    """Przygotowanie do spotkania na wskazaną chwilę, w kształcie odpowiedzi trasy.

    Dla testów, które potrzebują „za 20 minut, ale jeszcze dziś”: po 23:40
    takiej chwili od prawdziwego zegara już nie ma.
    """

    async with AsyncSessionLocal() as db:
        day = await my_day.load_my_day(db, user.id, now=now)
    prep = sales_my_day_api._prep(day.prep)
    assert prep is not None
    return prep.model_dump(mode="json")


# ── Dostęp ───────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_without_sales_view_the_day_is_closed(app_client) -> None:
    recruiter = await _user()
    resp = await app_client.get(URL, headers=_headers(recruiter))
    assert resp.status_code == 403
    assert resp.json()["detail"]["code"] == "permission_denied"


@pytest.mark.asyncio
async def test_empty_day_has_all_sections_empty(app_client) -> None:
    rep = await _user("sales_view")
    day = await _day(app_client, rep)
    assert day["today"] == business_today().isoformat()
    assert day["counts"] == {
        "meetings": 0,
        "reply": 0,
        "overdue": 0,
        "offers": 0,
        "older_tasks": 0,
    }
    assert day["meetings"] == day["reply"] == day["overdue"] == day["offers"] == []
    assert day["prep"] is None


# ── Spotkania dziś ───────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_meetings_today_are_mine_and_one_per_event(app_client) -> None:
    rep = await _user("sales_view")
    other = await _user("sales_view")
    first = await _company("Kopia A")
    second = await _company("Kopia B")
    # Dziś w kalendarzu firmy o każdej porze biegu („za godzinę” o 23:30 to już jutro).
    when = min(
        _now() + timedelta(hours=1), _day_start() + timedelta(hours=23, minutes=59)
    )
    uid = uuid.uuid4().hex
    for company in (first, second):
        await _activity(
            kind="meeting",
            subject="Omówienie współpracy",
            external_source=EVENT,
            external_id=uid,
            company_id=company,
            created_by_user_id=rep.id,
            occurred_at=when,
            duration_minutes=30,
        )
    await _opportunity(rep.id, second, stage="lead", value="1000")
    await _activity(
        kind="meeting",
        subject="Cudze spotkanie",
        external_source=EVENT,
        external_id=uuid.uuid4().hex,
        company_id=first,
        created_by_user_id=other.id,
        occurred_at=when,
    )
    day = await _day(app_client, rep)
    assert day["counts"]["meetings"] == 1
    # Wybrana kopia to karta z otwartą szansą, nie pierwsza z brzegu.
    assert day["meetings"][0]["company"]["id"] == second
    assert day["meetings"][0]["open_opportunities"] == 1
    assert day["meetings"][0]["duration_minutes"] == 30
    assert day["meetings"][0]["amount"] is None


@pytest.mark.asyncio
async def test_manual_meetings_without_external_id_stay_separate(app_client) -> None:
    rep = await _user("sales_view")
    company = await _company()
    when = _today_noon()
    for subject in ("Pierwsze", "Drugie"):
        await _activity(
            kind="meeting",
            subject=subject,
            company_id=company,
            created_by_user_id=rep.id,
            occurred_at=when,
        )
    assert (await _day(app_client, rep))["counts"]["meetings"] == 2


@pytest.mark.asyncio
async def test_cancelled_automatic_and_other_days_are_not_todays_meetings(
    app_client,
) -> None:
    rep = await _user("sales_view")
    company = await _company()
    today = _today_noon()
    for subject, when in (
        ("Canceled: Omówienie", today),
        ("Anulowano: Omówienie", today),
        ("Zaakceptowano: Omówienie", today),
        ("Wczorajsze", _day_start() - timedelta(minutes=1)),
        ("Jutrzejsze", _day_start() + timedelta(days=1, minutes=1)),
    ):
        await _activity(
            kind="meeting",
            subject=subject,
            company_id=company,
            created_by_user_id=rep.id,
            occurred_at=when,
        )
    assert (await _day(app_client, rep))["counts"]["meetings"] == 0


# ── Odpowiedz ────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_client_mail_without_our_answer_waits_for_reply(app_client) -> None:
    rep = await _user("sales_view")
    company = await _company()
    small = await _opportunity(rep.id, company, stage="lead", value="100")
    big = await _opportunity(rep.id, company, stage="lead", value="43210")
    when = _noon(_days_with_gap(3))
    await _mail(
        company, when, subject="RE: oferta", web_link="https://outlook.example/1"
    )
    day = await _day(app_client, rep)
    assert day["counts"]["reply"] == 1
    row = day["reply"][0]
    assert row["subject"] == "RE: oferta"
    assert row["web_link"] == "https://outlook.example/1"
    assert row["opportunity"]["id"] == big and big != small
    assert Decimal(row["amount"]) == Decimal("43210")
    assert row["days"] == (business_today() - when.date()).days


@pytest.mark.asyncio
async def test_reply_waits_for_two_business_days(app_client) -> None:
    rep = await _user("sales_view")
    company = await _company()
    await _opportunity(rep.id, company, stage="lead")
    await _mail(company, _noon(_days_with_gap(1)))
    assert (await _day(app_client, rep))["counts"]["reply"] == 0


def test_business_days_skip_weekend_and_holidays() -> None:
    # Pt 06.11.2026 → pn 09.11: minął jeden dzień roboczy.
    assert my_day.business_days_after(date(2026, 11, 6), date(2026, 11, 9)) == 1
    # Sobota nie zaczyna odliczania od zera: tylko poniedziałek.
    assert my_day.business_days_after(date(2026, 11, 7), date(2026, 11, 9)) == 1
    # 11.11 to święto: pn 09.11 → czw 12.11 to wtorek, środa wolna, czwartek.
    assert my_day.business_days_after(date(2026, 11, 9), date(2026, 11, 12)) == 2
    assert my_day.business_days_after(date(2026, 11, 9), date(2026, 11, 9)) == 0


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "kind,extra",
    [
        ("email", {"direction": "out", "external_source": MAIL}),
        ("call", {"done_at": True}),
        ("meeting", {}),
    ],
)
async def test_our_follow_up_closes_the_thread(app_client, kind, extra) -> None:
    rep = await _user("sales_view")
    company = await _company()
    await _opportunity(rep.id, company, stage="lead")
    when = _noon(_days_with_gap(4))
    await _mail(company, when)
    later = when + timedelta(days=1)
    fields = dict(extra)
    if fields.pop("done_at", False):
        fields["done_at"] = later
    await _activity(
        kind=kind,
        subject="Odpowiedź",
        company_id=company,
        occurred_at=later,
        external_id=uuid.uuid4().hex,
        **fields,
    )
    assert (await _day(app_client, rep))["counts"]["reply"] == 0


@pytest.mark.asyncio
async def test_our_answer_before_their_mail_does_not_close_it(app_client) -> None:
    rep = await _user("sales_view")
    company = await _company()
    await _opportunity(rep.id, company, stage="lead")
    when = _noon(_days_with_gap(4))
    await _mail(company, when - timedelta(days=1), direction="out")
    await _mail(company, when)
    assert (await _day(app_client, rep))["counts"]["reply"] == 1


@pytest.mark.asyncio
async def test_planned_step_after_the_mail_takes_it_off_the_queue(app_client) -> None:
    rep = await _user("sales_view")
    company = await _company()
    await _opportunity(rep.id, company, stage="lead")
    await _mail(company, _noon(_days_with_gap(4)))
    await _activity(
        kind="task",
        subject="Odpisać w środę",
        company_id=company,
        assignee_user_id=rep.id,
        due_at=_now() + timedelta(days=2),
    )
    assert (await _day(app_client, rep))["counts"]["reply"] == 0


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "subject",
    [
        "Automatic reply: urlop",
        "Odpowiedź automatyczna: urlop",
        "Automatyczna odpowiedź: urlop",
        "Informacja o nieobecności RE: oferta",
        "Nieobecność",
        "Out of Office until Monday",
        "Wstępna akceptacja: Spotkanie",
        "Odwołanie: Spotkanie",
        "New Time Proposed: Spotkanie",
        "Meeting Forward Notification: Spotkanie",
        "Niedostarczone: oferta",
        "Undeliverable: oferta",
        "Accepted: Spotkanie",
        "Zaakceptowano: Spotkanie",
        "Tentative: Spotkanie",
        "Your meeting recap - Spotkanie",
        "Meeting recap: Spotkanie",
        "Canceled: Spotkanie",
        "Zaproszenie: Spotkanie",
        "Invitation: Spotkanie",
    ],
)
async def test_auto_replies_and_invitations_do_not_count(app_client, subject) -> None:
    rep = await _user("sales_view")
    company = await _company()
    await _opportunity(rep.id, company, stage="lead")
    await _mail(company, _noon(_days_with_gap(4)), subject=subject)
    assert (await _day(app_client, rep))["counts"]["reply"] == 0


@pytest.mark.asyncio
async def test_autoresponder_right_after_our_mail_does_not_reopen_the_thread(
    app_client,
) -> None:
    rep = await _user("sales_view")
    company = await _company()
    await _opportunity(rep.id, company, stage="lead")
    when = _noon(_days_with_gap(5))
    await _mail(company, when, direction="out", subject="Oferta")
    await _mail(
        company, when + timedelta(minutes=1), subject="Automatyczna odpowiedź: Oferta"
    )
    assert (await _day(app_client, rep))["counts"]["reply"] == 0


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "subject",
    [
        "Zaproszenie do złożenia ofert w zapytaniu",
        "Odpowiedź na zapytanie RFP: zespół",
        "Moja nieobecność w przyszłym tygodniu",
        "Nieobecność kandydata na rozmowie",
        "Accepted candidates list",
    ],
)
async def test_real_mails_that_only_resemble_automats_wait_for_reply(
    app_client, subject
) -> None:
    rep = await _user("sales_view")
    company = await _company()
    await _opportunity(rep.id, company, stage="lead")
    await _mail(company, _noon(_days_with_gap(4)), subject=subject)
    day = await _day(app_client, rep)
    assert [row["subject"] for row in day["reply"]] == [subject]


@pytest.mark.asyncio
async def test_auto_reply_does_not_hide_the_real_mail_before_it(app_client) -> None:
    rep = await _user("sales_view")
    company = await _company()
    await _opportunity(rep.id, company, stage="lead")
    when = _noon(_days_with_gap(5))
    await _mail(company, when, subject="Prawdziwe pytanie")
    await _mail(
        company, when + timedelta(hours=2), subject="Automatic reply: Prawdziwe pytanie"
    )
    day = await _day(app_client, rep)
    assert [row["subject"] for row in day["reply"]] == ["Prawdziwe pytanie"]


@pytest.mark.asyncio
async def test_reply_on_the_second_card_of_the_same_company_closes_it(
    app_client,
) -> None:
    rep = await _user("sales_view")
    word = f"acme{uuid.uuid4().hex[:8]}"
    first = await _company("Acme", normalized_name=f"{word} polska")
    second = await _company("Acme", normalized_name=f"{word} sp")
    await _opportunity(rep.id, first, stage="lead")
    when = _noon(_days_with_gap(4))
    mail_id = uuid.uuid4().hex
    for company in (first, second):
        await _mail(company, when, external_id=mail_id)
    await _mail(second, when + timedelta(hours=3), direction="out")
    assert (await _day(app_client, rep))["counts"]["reply"] == 0


@pytest.mark.asyncio
async def test_same_mail_on_an_unrelated_company_does_not_close_it(app_client) -> None:
    rep = await _user("sales_view")
    first = await _company("Alfa", normalized_name=f"alfa{uuid.uuid4().hex[:8]}")
    second = await _company("Beta", normalized_name=f"beta{uuid.uuid4().hex[:8]}")
    await _opportunity(rep.id, first, stage="lead")
    when = _noon(_days_with_gap(4))
    mail_id = uuid.uuid4().hex
    for company in (first, second):
        await _mail(company, when, external_id=mail_id)
    await _mail(second, when + timedelta(hours=3), direction="out")
    assert (await _day(app_client, rep))["counts"]["reply"] == 1


@pytest.mark.asyncio
async def test_company_without_my_open_opportunity_does_not_wait(app_client) -> None:
    rep = await _user("sales_view")
    other = await _user("sales_view")
    company = await _company()
    await _opportunity(other.id, company, stage="lead")
    await _opportunity(rep.id, company, stage="lead", status="lost")
    await _mail(company, _noon(_days_with_gap(4)))
    assert (await _day(app_client, rep))["counts"]["reply"] == 0


@pytest.mark.asyncio
async def test_old_mail_outside_the_window_is_gone(app_client) -> None:
    rep = await _user("sales_view")
    company = await _company()
    await _opportunity(rep.id, company, stage="lead")
    await _mail(company, _day_start() - timedelta(days=my_day.REPLY_WINDOW_DAYS + 1))
    assert (await _day(app_client, rep))["counts"]["reply"] == 0


# ── Zaległe kroki ────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_overdue_up_to_sixty_days_and_older_as_a_counter(app_client) -> None:
    rep = await _user("sales_view")
    company = await _company()
    opp = await _opportunity(rep.id, company, stage="lead", value="15000")
    base = {"company_id": company, "assignee_user_id": rep.id, "opportunity_id": opp}
    recent = await _activity(
        kind="call",
        subject="Ustalić termin",
        due_at=_day_start() - timedelta(days=3),
        **base,
    )
    await _activity(
        kind="task", subject="Stare", due_at=_day_start() - timedelta(days=61), **base
    )
    await _activity(
        kind="task",
        subject="Dzisiejsze",
        due_at=_day_start() + timedelta(hours=1),
        **base,
    )
    await _activity(
        kind="task",
        subject="Zrobione",
        due_at=_day_start() - timedelta(days=3),
        done_at=_now(),
        **base,
    )
    day = await _day(app_client, rep)
    assert day["counts"]["overdue"] == 1
    assert day["counts"]["older_tasks"] == 1
    row = day["overdue"][0]
    assert row["activity_id"] == recent
    assert row["kind"] == "call"
    assert row["days"] == 3
    assert Decimal(row["amount"]) == Decimal("15000")


@pytest.mark.asyncio
async def test_overdue_skips_closed_opportunity_and_other_people(app_client) -> None:
    rep = await _user("sales_view")
    other = await _user("sales_view")
    company = await _company()
    lost = await _opportunity(rep.id, company, stage="lost", status="lost")
    await _activity(
        kind="task",
        subject="Sierota po przegranej",
        company_id=company,
        opportunity_id=lost,
        assignee_user_id=rep.id,
        due_at=_day_start() - timedelta(days=2),
    )
    await _activity(
        kind="task",
        subject="Cudze",
        company_id=company,
        assignee_user_id=other.id,
        due_at=_day_start() - timedelta(days=2),
    )
    day = await _day(app_client, rep)
    assert day["counts"]["overdue"] == 0 and day["counts"]["older_tasks"] == 0


@pytest.mark.asyncio
async def test_company_task_without_opportunity_is_overdue_too(app_client) -> None:
    rep = await _user("sales_view")
    company = await _company()
    await _activity(
        kind="task",
        subject="Przypomnieć się",
        company_id=company,
        assignee_user_id=rep.id,
        due_at=_day_start() - timedelta(days=4),
    )
    day = await _day(app_client, rep)
    assert day["counts"]["overdue"] == 1
    assert day["overdue"][0]["opportunity"] is None
    assert day["overdue"][0]["amount"] is None


# ── Oferty bez ruchu ─────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_idle_offers_are_listed_biggest_first(app_client) -> None:
    rep = await _user("sales_view")
    small = await _opportunity(
        rep.id, await _company(), value="100", age_days=20, title="Mała"
    )
    big = await _opportunity(
        rep.id, await _company(), value="9000", age_days=20, title="Duża"
    )
    no_value = await _opportunity(rep.id, await _company(), age_days=20, title="Bez")
    day = await _day(app_client, rep)
    assert day["counts"]["offers"] == 3
    assert [row["opportunity"]["id"] for row in day["offers"]] == [big, small, no_value]
    assert day["offers"][0]["days"] == 20


@pytest.mark.asyncio
async def test_offer_with_fresh_touch_or_other_stage_is_not_idle(app_client) -> None:
    rep = await _user("sales_view")
    touched = await _company()
    opp = await _opportunity(rep.id, touched, age_days=30)
    await _activity(
        kind="note",
        body="Rozmowa na korytarzu",
        company_id=touched,
        opportunity_id=opp,
        occurred_at=_now() - timedelta(days=2),
    )
    await _opportunity(rep.id, await _company(), stage="lead", age_days=30)
    await _opportunity(rep.id, await _company(), age_days=13)
    assert (await _day(app_client, rep))["counts"]["offers"] == 0


@pytest.mark.asyncio
async def test_offer_with_a_planned_step_is_not_in_the_queue(app_client) -> None:
    rep = await _user("sales_view")
    company = await _company()
    opp = await _opportunity(rep.id, company, age_days=30)
    await _activity(
        kind="task",
        subject="Dopytać o decyzję",
        company_id=company,
        opportunity_id=opp,
        assignee_user_id=rep.id,
        due_at=_now() + timedelta(days=3),
    )
    assert (await _day(app_client, rep))["counts"]["offers"] == 0


@pytest.mark.asyncio
async def test_task_created_today_is_not_movement_for_the_offer(app_client) -> None:
    """Zadanie po terminie nie jest dotykiem, więc oferta dalej stoi."""

    rep = await _user("sales_view")
    company = await _company()
    opp = await _opportunity(rep.id, company, age_days=30)
    await _activity(
        kind="task",
        subject="Zapomniane",
        company_id=company,
        opportunity_id=opp,
        assignee_user_id=rep.id,
        due_at=_day_start() - timedelta(days=2),
    )
    day = await _day(app_client, rep)
    assert day["counts"]["offers"] == 1 and day["counts"]["overdue"] == 1


# ── Osoba, numer, sprzeciw ───────────────────────────────────────────────


@pytest.mark.asyncio
async def test_row_carries_person_and_number_from_the_task(app_client) -> None:
    rep = await _user("sales_view")
    company = await _company()
    await _contact(company, full_name="Ktoś Inny", mobile_phone="+48 500 000 001")
    chosen = await _contact(
        company, full_name="Osoba Z Zadania", phone="+48 500 000 002", title="CTO"
    )
    await _activity(
        kind="call",
        subject="Oddzwonić",
        company_id=company,
        contact_id=chosen,
        assignee_user_id=rep.id,
        due_at=_day_start() - timedelta(days=1),
    )
    row = (await _day(app_client, rep))["overdue"][0]
    assert row["person"]["id"] == chosen
    assert row["person"]["phone"] == "+48 500 000 002"
    assert row["person"]["title"] == "CTO"


@pytest.mark.asyncio
async def test_person_of_another_company_is_not_offered_from_history(
    app_client,
) -> None:
    """Uczestnik spotkania z kalendarza bywa naszym pracownikiem, nie kontaktem klienta."""

    rep = await _user("sales_view")
    ours = await _company("Nasza")
    client = await _company()
    colleague = await _contact(ours, full_name="Kolega", mobile_phone="+48 500 000 020")
    await _activity(
        kind="meeting",
        subject="Spotkanie",
        company_id=client,
        contact_id=colleague,
        occurred_at=_now() - timedelta(days=40),
    )
    await _opportunity(rep.id, client, age_days=30)
    row = (await _day(app_client, rep))["offers"][0]
    assert row["person"] is None


@pytest.mark.asyncio
async def test_person_on_the_row_source_from_another_company_is_skipped(
    app_client,
) -> None:
    rep = await _user("sales_view")
    ours = await _company("Nasza")
    client = await _company()
    colleague = await _contact(ours, full_name="Kolega", mobile_phone="+48 500 000 021")
    own = await _contact(client, full_name="Klient", phone="+48 500 000 022")
    await _activity(
        kind="call",
        subject="Oddzwonić",
        company_id=client,
        contact_id=colleague,
        assignee_user_id=rep.id,
        due_at=_day_start() - timedelta(days=1),
    )
    row = (await _day(app_client, rep))["overdue"][0]
    assert row["person"]["id"] == own


@pytest.mark.asyncio
async def test_person_from_history_can_have_the_call_saved(app_client) -> None:
    rep = await _user("sales_view", "sales_edit")
    client = await _company()
    earlier = await _contact(client, full_name="Z Historii", phone="+48 500 000 023")
    await _contact(client, full_name="Bez Historii", phone="+48 500 000 024")
    await _activity(
        kind="meeting",
        subject="Spotkanie",
        company_id=client,
        contact_id=earlier,
        occurred_at=_now() - timedelta(days=40),
    )
    opportunity = await _opportunity(rep.id, client, age_days=30)
    row = (await _day(app_client, rep))["offers"][0]
    assert row["person"]["id"] == earlier
    saved = await app_client.post(
        f"/api/sales/opportunities/{opportunity}/calls",
        json={"outcome": "no_answer", "contact_id": row["person"]["id"]},
        headers=_headers(rep),
    )
    assert saved.status_code == 201, saved.text


@pytest.mark.asyncio
async def test_objecting_person_is_never_offered_for_a_call(app_client) -> None:
    rep = await _user("sales_view")
    company = await _company()
    objected = await _contact(
        company,
        full_name="Bez Kontaktu",
        mobile_phone="+48 500 000 003",
        do_not_contact_at=_now(),
    )
    await _opportunity(
        rep.id, company, age_days=30, primary_contact_id=objected, value="10"
    )
    row = (await _day(app_client, rep))["offers"][0]
    assert row["person"] is None
    assert all(p["id"] != objected for p in row["people_without_phone"])


@pytest.mark.asyncio
async def test_no_number_lists_people_who_can_get_one(app_client) -> None:
    rep = await _user("sales_view")
    company = await _company()
    plain = await _contact(company, full_name="Bez Numeru", title="CFO")
    await _contact(company, full_name="mail@example.com")
    await _contact(company, full_name="Z Archiwum", archived_at=_now())
    await _opportunity(rep.id, company, age_days=30)
    row = (await _day(app_client, rep))["offers"][0]
    assert row["person"]["id"] == plain and row["person"]["phone"] is None
    assert [p["id"] for p in row["people_without_phone"]] == [plain]


@pytest.mark.asyncio
async def test_company_marked_do_not_contact_hides_people(app_client) -> None:
    rep = await _user("sales_view")
    company = await _company(status="do_not_contact")
    await _contact(company, full_name="Kontakt Firmy", mobile_phone="+48 500 000 004")
    await _opportunity(rep.id, company, age_days=30)
    row = (await _day(app_client, rep))["offers"][0]
    assert row["do_not_contact"] is True
    assert row["person"] is None and row["people_without_phone"] == []


@pytest.mark.asyncio
async def test_new_number_for_objecting_contact_is_refused(app_client) -> None:
    rep = await _user("sales_edit")
    company = await _company()
    objected = await _contact(
        company, full_name="Sprzeciw", phone="+48 500 000 005", do_not_contact_at=_now()
    )
    changed = await app_client.patch(
        f"{CONTACTS}/{objected}",
        json={"mobile_phone": "+48 500 000 006"},
        headers=_headers(rep),
    )
    assert changed.status_code == 409
    same = await app_client.patch(
        f"{CONTACTS}/{objected}",
        json={"phone": "+48 500 000 005", "title": "Prezes"},
        headers=_headers(rep),
    )
    assert same.status_code == 200, same.text


@pytest.mark.asyncio
async def test_new_person_with_objecting_name_and_number_is_refused(
    app_client,
) -> None:
    rep = await _user("sales_edit")
    company = await _company()
    await _contact(company, full_name="Anna Sprzeciw", do_not_contact_at=_now())
    refused = await app_client.post(
        CONTACTS,
        json={
            "company_id": company,
            "full_name": "  anna sprzeciw ",
            "mobile_phone": "+48 500 000 007",
        },
        headers=_headers(rep),
    )
    assert refused.status_code == 409
    allowed = await app_client.post(
        CONTACTS,
        json={
            "company_id": company,
            "full_name": "Inna Osoba",
            "mobile_phone": "+48 500 000 008",
        },
        headers=_headers(rep),
    )
    assert allowed.status_code == 201, allowed.text


@pytest.mark.asyncio
async def test_assignee_can_reschedule_a_task_someone_else_created(app_client) -> None:
    author = await _user("sales_edit")
    rep = await _user("sales_edit")
    stranger = await _user("sales_edit")
    company = await _company()
    task = await _activity(
        kind="task",
        subject="Przełożyć",
        company_id=company,
        created_by_user_id=author.id,
        assignee_user_id=rep.id,
        due_at=_day_start() - timedelta(days=1),
    )
    new_due = (_now() + timedelta(days=3)).isoformat()
    refused = await app_client.patch(
        f"{ACTIVITIES}/{task}", json={"due_at": new_due}, headers=_headers(stranger)
    )
    assert refused.status_code == 403
    moved = await app_client.patch(
        f"{ACTIVITIES}/{task}", json={"due_at": new_due}, headers=_headers(rep)
    )
    assert moved.status_code == 200, moved.text
    assert (await _day(app_client, rep))["counts"]["overdue"] == 0


@pytest.mark.asyncio
async def test_call_at_company_without_opportunity_is_saved(app_client) -> None:
    rep = await _user("sales_edit")
    company = await _company()
    person = await _contact(company, full_name="Odbiera", phone="+48 500 000 010")
    resp = await app_client.post(
        f"/api/sales/companies/{company}/calls",
        json={"outcome": "connected", "contact_id": person, "note": "Rozmowa"},
        headers=_headers(rep),
    )
    assert resp.status_code == 204, resp.text
    async with AsyncSessionLocal() as db:
        call = await db.scalar(
            select(SalesActivity).where(SalesActivity.company_id == company)
        )
    assert call.kind == "call" and call.outcome == "connected"
    assert call.contact_id == person and call.done_at is not None


@pytest.mark.asyncio
async def test_objection_at_company_level_blocks_the_next_call(app_client) -> None:
    rep = await _user("sales_edit")
    company = await _company()
    person = await _contact(company, phone="+48 500 000 011")
    url = f"/api/sales/companies/{company}/calls"
    first = await app_client.post(
        url,
        json={"outcome": "do_not_contact", "contact_id": person},
        headers=_headers(rep),
    )
    assert first.status_code == 204, first.text
    second = await app_client.post(
        url, json={"outcome": "connected", "contact_id": person}, headers=_headers(rep)
    )
    assert second.status_code == 409


@pytest.mark.asyncio
async def test_company_call_refuses_foreign_contact_and_view_only(app_client) -> None:
    rep = await _user("sales_edit")
    viewer = await _user("sales_view")
    company = await _company()
    other = await _contact(await _company())
    url = f"/api/sales/companies/{company}/calls"
    foreign = await app_client.post(
        url, json={"outcome": "connected", "contact_id": other}, headers=_headers(rep)
    )
    assert foreign.status_code == 422
    no_person = await app_client.post(
        url, json={"outcome": "do_not_contact"}, headers=_headers(rep)
    )
    assert no_person.status_code == 422
    forbidden = await app_client.post(
        url, json={"outcome": "connected"}, headers=_headers(viewer)
    )
    assert forbidden.status_code == 403
    missing = await app_client.post(
        "/api/sales/companies/2147483000/calls",
        json={"outcome": "connected"},
        headers=_headers(rep),
    )
    assert missing.status_code == 404


# ── Przygotowanie do spotkania ───────────────────────────────────────────


@pytest.mark.asyncio
async def test_prep_covers_the_nearest_meeting(app_client) -> None:
    rep = await _user("sales_view")
    near = await _company("Najbliższa")
    far = await _company("Dalsza")
    now = _today_noon()
    await _contact(near, full_name="Dyrektor", mobile_phone="+48 500 000 009")
    await _activity(
        kind="note",
        body="Pytali o zespół",
        company_id=near,
        occurred_at=now - timedelta(days=9),
    )
    await _activity(
        kind="email",
        direction="in",
        subject="Zaproszenie na rozmowę",
        company_id=near,
        occurred_at=now - timedelta(days=4),
    )
    soon = now + timedelta(minutes=20)
    meeting = await _activity(
        kind="meeting",
        subject="Rozmowa",
        external_source=EVENT,
        external_id=uuid.uuid4().hex,
        company_id=near,
        created_by_user_id=rep.id,
        occurred_at=soon,
        duration_minutes=30,
    )
    await _activity(
        kind="meeting",
        subject="Później",
        external_source=EVENT,
        external_id=uuid.uuid4().hex,
        company_id=far,
        created_by_user_id=rep.id,
        occurred_at=now + timedelta(minutes=40),
    )
    prep = await _prep_at(rep, now)
    assert prep["activity_id"] == meeting
    assert prep["company"]["id"] == near
    assert prep["can_create_opportunity"] is True
    assert [item["kind"] for item in prep["history"]] == ["email", "note"]
    assert prep["history"][0]["days"] == 4
    assert prep["contacts"][0]["phone"] == "+48 500 000 009"


@pytest.mark.asyncio
async def test_prep_does_not_offer_opportunity_when_one_is_open(app_client) -> None:
    rep = await _user("sales_view")
    company = await _company()
    await _opportunity(rep.id, company, stage="lead")
    now = _today_noon()
    await _activity(
        kind="meeting",
        subject="Rozmowa",
        external_source=EVENT,
        external_id=uuid.uuid4().hex,
        company_id=company,
        created_by_user_id=rep.id,
        occurred_at=now + timedelta(minutes=20),
    )
    assert (await _prep_at(rep, now))["can_create_opportunity"] is False


# ── Poranny mail ─────────────────────────────────────────────────────────


def _row(section: str, **fields: Any) -> my_day.DayRow:
    defaults: dict[str, Any] = {
        "key": f"{section}-1",
        "section": section,
        "company_id": 7,
        "company_name": "Firma Testowa",
        "subject": "Temat",
        "at": datetime(2026, 11, 9, 8, 30, tzinfo=timezone.utc),
        "days": 14,
        "amount": Decimal("43210"),
    }
    return my_day.DayRow(**{**defaults, **fields})


def _digest_day(**sections: Any) -> my_day.MyDay:
    defaults: dict[str, Any] = {
        "today": date(2026, 11, 9),
        "meetings": [],
        "reply": [],
        "overdue": [],
        "offers": [],
        "older_tasks": 0,
    }
    return my_day.MyDay(**{**defaults, **sections})


def test_empty_sales_day_makes_no_sections() -> None:
    assert daily_digest.sales_sections(_digest_day()) == []


def test_digest_has_sales_sections_without_amounts() -> None:
    day = _digest_day(
        meetings=[_row("meetings")],
        reply=[_row("reply")],
        overdue=[_row("overdue", subject="Oddzwonić", days=3)],
        offers=[_row("offers", key=f"offers-{i}") for i in range(7)],
    )
    sections = daily_digest.sales_sections(day)
    assert [section.total for section in sections] == [1, 1, 1, 7]
    assert len(sections[3].rows) == daily_digest.MAX_ROWS
    assert all(section.path == daily_digest.SALES_DAY_PATH for section in sections)
    subject, text, html = daily_digest.render("Ola", sections, date(2026, 11, 9))
    assert "10 do zrobienia" in subject
    assert "Firma Testowa" in text and "Oddzwonić" in text
    assert "432" not in text
    assert "/sales/my-day" in html
    assert "Mój dzień" in html


@pytest.mark.asyncio
async def test_sales_person_without_digest_role_gets_only_sales_mail(
    app_client,
) -> None:
    rep = await _user("sales_view", role="employee")
    company = await _company("Mailowa")
    await _opportunity(rep.id, company, value="5000", age_days=40)
    async with AsyncSessionLocal() as db:
        ids = {user.id for user in await daily_digest_email._recipients(db)}
        assert rep.id in ids
        user = next(
            u for u in await daily_digest_email._recipients(db) if u.id == rep.id
        )
        mail = await daily_digest_email._mail_for(db, user, business_today())
    assert mail is not None
    assert "oferty bez ruchu" in mail.text
    assert "Mailowa" in mail.text
    assert "/sales/my-day" in mail.html
    assert "Czeka na Ciebie" not in mail.html


@pytest.mark.asyncio
async def test_sales_person_with_empty_day_gets_no_mail(app_client) -> None:
    rep = await _user("sales_view", role="employee")
    async with AsyncSessionLocal() as db:
        user = next(
            u for u in await daily_digest_email._recipients(db) if u.id == rep.id
        )
        assert await daily_digest_email._mail_for(db, user, business_today()) is None


@pytest.mark.asyncio
async def test_account_without_sales_view_gets_no_sales_section(app_client) -> None:
    employee = await _user(role="employee")
    async with AsyncSessionLocal() as db:
        ids = {user.id for user in await daily_digest_email._recipients(db)}
    assert employee.id not in ids


@pytest.mark.asyncio
async def test_sales_person_can_switch_the_morning_mail_off(app_client) -> None:
    rep = await _user("sales_view", role="employee")
    prefs = await app_client.get("/api/users/me/preferences", headers=_headers(rep))
    assert prefs.json()["daily_digest_email_available"] is True
    async with AsyncSessionLocal() as db:
        user = next(
            u for u in await daily_digest_email._recipients(db) if u.id == rep.id
        )
        view = await notification_email_prefs.my_view(db, user)
        assert "daily_digest" in {item["id"] for item in view["items"]}
        await notification_email_prefs.set_enabled(db, user, "daily_digest", False)
        await db.commit()
    async with AsyncSessionLocal() as db:
        ids = {user.id for user in await daily_digest_email._recipients(db)}
    assert rep.id not in ids


@pytest.mark.asyncio
async def test_account_outside_the_mail_has_no_switch(app_client) -> None:
    employee = await _user(role="employee")
    prefs = await app_client.get(
        "/api/users/me/preferences", headers=_headers(employee)
    )
    assert prefs.json()["daily_digest_email_available"] is False
    async with AsyncSessionLocal() as db:
        user = await db.get(User, employee.id)
        await resolve_effective_access(db, [user])
        view = await notification_email_prefs.my_view(db, user)
        assert "daily_digest" in {item["id"] for item in view["not_applicable"]}
        with pytest.raises(notification_email_prefs.EmailKindNotApplicable):
            await notification_email_prefs.set_enabled(db, user, "daily_digest", False)


@pytest.mark.asyncio
async def test_plain_admin_does_not_start_getting_the_digest(app_client) -> None:
    """Admin ma „Sprzedaż: podgląd” z roli, a skrót dotąd go omijał celowo."""

    admin = await _user(role=UserRole.admin.value)
    company = await _company()
    await _opportunity(admin.id, company, value="10", age_days=40)
    async with AsyncSessionLocal() as db:
        ids = {user.id for user in await daily_digest_email._recipients(db)}
    assert admin.id not in ids


def test_local_now_is_timezone_aware() -> None:
    # „Dziś” Mojego dnia idzie z kalendarza firmy, nie z UTC.
    assert local_now().tzinfo is not None
