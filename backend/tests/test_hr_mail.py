"""Mail „Czas i ludzie” (`hr_people`, 17.10.2026).

Typy kadrowe miały tylko dymek dla zalogowanych. Teraz sprawy, na które ktoś
czeka, idą kolejką maili natychmiast — bez rodzaju nieobecności i bez kwot
(D6: mail wychodzi poza aplikację), za polityką firmy i własnym wyłącznikiem.
Dane fikcyjne (repo jest publiczne).
"""

from __future__ import annotations

import re
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.dialects import postgresql

from app.core.database import AsyncSessionLocal
from app.models.notification import Notification, NotificationType
from app.models.user import User, UserRole
from app.services import hr_notification_schema
from app.services import notification_delivery as delivery
from app.services import notification_email_prefs as prefs
from app.services.hr import hr_mail
from app.services.hr.employment_terms import terms
from app.tasks import notification_email_outbox as outbox

_BACKEND = Path(__file__).resolve().parents[1]
_AT = "2026-10-17T08:00:00+00:00"

# Bez maila „Czas i ludzie”: kwoty (stawki), opieka (sekcja Delivery). Raport
# godzin wysłany do akceptacji idzie mailem od 18.10.2026 (jak w Compassie).
# Premia ma od 26.10.2026 własny mail „Masz nową premię” bez kwoty.
_OWN_MAIL = {"hr_bonus_assigned": "hr_bonus"}
_NO_MAIL = (
    "hr_rate_changed",
    "care_contact_due",
    # Tygodniowe „uzupełnij strukturę klienta” (0475) — przypomnienie opieki.
    "care_client_structure",
    # Popyt z rozmowy opiekuna (0509) — karta na tablicy DL, bez maila.
    "care_demand_signal",
    # Informacja o zapłacie — nikt na nią nie czeka (dymek i „Mój czas”).
    "hr_settlement_paid",
)


def _user(role: UserRole = UserRole.employee) -> User:
    return User(
        email=f"{role.value}@example.com",
        name="Anna Przykładowa",
        role=role,
        roles=[role.value],
        is_active=True,
        daily_digest_email_enabled=True,
        email_opt_outs={},
        muted_notification_categories={},
    )


# ── Mapa typów ──────────────────────────────────────────────────────────────


def test_every_hr_type_is_either_mailed_or_deliberately_left_out():
    mailed = set(delivery.HR_MAIL_TYPES)
    assert mailed | set(_NO_MAIL) | set(_OWN_MAIL) == set(
        hr_notification_schema.NOTIFICATION_TYPES
    )
    assert not mailed & set(_NO_MAIL)
    for value, kind in _OWN_MAIL.items():
        assert delivery.notification_kind(value) == kind
    for value in mailed:
        assert delivery.notification_kind(value) == "hr_people"
        assert (
            delivery.immediate_email_kind(
                NotificationType(value), title="x", related_entity_type=None
            )
            == "hr_people"
        )
    for value in _NO_MAIL:
        assert delivery.notification_kind(value) is None
    # Każdy mailowany typ ma własne zdanie zastępcze — bez niego mail powiedziałby
    # tylko „Czas i ludzie”.
    assert set(hr_mail.FALLBACK) == mailed


def test_hr_kind_has_a_sql_clause_with_only_mailed_types():
    sql = str(
        outbox.kind_clause("hr_people").compile(
            dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}
        )
    )
    assert "notification_type IN" in sql
    assert "'hr_leave_requested'" in sql and "'equipment_task'" in sql
    assert "'hr_bonus_assigned'" not in sql and "'care_contact_due'" not in sql


def test_hr_kind_sits_in_the_catalog_and_the_immediate_queue():
    spec = next(item for item in delivery.CATALOG if item["id"] == "hr_people")
    assert spec["label"] == "Czas i ludzie"
    assert "hr_people" in delivery.IMMEDIATE_KINDS
    assert "hr_people" in delivery.ROUTINE_KINDS
    assert "hr_people" not in delivery.REPORT_KINDS


# ── Treść maila ─────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "message",
    [
        "Anna Przykładowa: Zwolnienie lekarskie (L4) 20.10–24.10.2026.",
        "Anna Przykładowa: L4 20.10–24.10.2026.",
        "Anna Przykładowa: urlop wypoczynkowy 20.10–24.10.2026.",
        "Twój urlop 20.10–24.10.2026 jest krótszy o 1 dzień.",
        "Anna Przykładowa: opieka nad dzieckiem (art. 188), 20.10.",
        "Anna Przykładowa: chorobowe od 20.10.",
        "Anna Przykładowa: oddanie krwi 20.10.",
    ],
)
def test_absence_kind_never_leaves_by_mail(message):
    title, body = hr_mail.mail_text(
        NotificationType.hr_absence_reported, "Zgłoszona nieobecność", message
    )
    assert (title, body) == (
        "Zgłoszona nieobecność",
        "Osoba z Twojego zespołu zgłosiła nieobecność.",
    )


def test_unsafe_title_is_replaced_too():
    title, body = hr_mail.mail_text(
        NotificationType.hr_leave_requested,
        "Urlop na żądanie do akceptacji",
        "Anna Przykładowa: 20.10.2026 (1 dzień).",
    )
    assert title == "Wniosek o nieobecność do akceptacji"
    assert body == "Anna Przykładowa: 20.10.2026 (1 dzień)."


@pytest.mark.parametrize(
    "message",
    ["Premia za placement: 1 500 zł.", "Nowa stawka od 1.11.", "Kwota 120 PLN/h."],
)
def test_amounts_never_leave_by_mail(message):
    _title, body = hr_mail.mail_text(
        NotificationType.hr_lifecycle_task, "Zadania: wejście — Anna", message
    )
    assert body == "Masz zadania w sprawie wejścia albo odejścia pracownika."


@pytest.mark.parametrize(
    ("ntype", "title", "message"),
    [
        (
            "hr_leave_requested",
            "Wniosek o nieobecność do akceptacji",
            "Anna Przykładowa: 20.10–24.10.2026 (5 dni).",
        ),
        (
            "hr_absence_reported",
            "Zgłoszona nieobecność",
            "Anna Przykładowa: nieobecność 20.10–24.10.2026, zatwierdzona od razu.",
        ),
        ("hr_leave_substitute", "Zastępstwo", "Zastępujesz: Anna, 20.10–24.10.2026."),
        (
            "hr_timesheet_decided",
            "Timesheet zaakceptowany",
            "Timesheet za październik 2026 jest zaakceptowany.",
        ),
        (
            "hr_work_handover",
            "Przejmujesz pracę: Anna Przykładowa",
            "Od dziś prowadzisz po tej osobie — Rekrutacje: 3.",
        ),
        ("equipment_task", "Sprzęt: 2 do zrobienia", "Na dziś i najbliższe dni: 2."),
    ],
)
def test_plain_texts_go_unchanged(ntype, title, message):
    assert hr_mail.mail_text(NotificationType(ntype), title, message) == (
        title,
        message,
    )


def test_submitted_report_mail_says_who_and_which_month_in_the_form_words():
    """Raport wysłany do akceptacji (18.10.2026): mail do akceptującego niesie
    tytuł słowami formy i „kto: miesiąc” — to samo, co dymek z `time_flow`."""

    source = (_BACKEND / "app/services/hr/time_flow.py").read_text(encoding="utf-8")
    assert 'title=words["timesheet_submitted_title"]' in source
    message = "Anna Przykładowa: październik 2026."
    for form in ("uop", "b2b", "zlecenie"):
        title = terms(form)["timesheet_submitted_title"]
        assert hr_mail.mail_text(
            NotificationType.hr_timesheet_submitted, title, message
        ) == (title, message)
    assert delivery.notification_kind("hr_timesheet_submitted") == "hr_people"


def test_case_title_and_return_note_never_go_by_mail():
    # Tytuł sprawy przychodzi z cudzej poczty — może nieść cokolwiek.
    _t, body = hr_mail.mail_text(
        NotificationType.admin_case_assigned,
        "Przypisano Ci sprawę administracja@",
        "Prośba o zaświadczenie dla Anny Przykładowej",
    )
    assert body == "Szczegóły sprawy znajdziesz w NEXUSIE."
    # Tytuł zwrotu zależy od formy (ewidencja / raport / potwierdzenie godzin).
    assert len(hr_mail.RETURNED_TIMESHEET_TITLES) == 3
    for returned in hr_mail.RETURNED_TIMESHEET_TITLES:
        title, body = hr_mail.mail_text(
            NotificationType.hr_timesheet_decided,
            returned,
            "Październik 2026: brakuje wpisu z 3.10, popraw proszę.",
        )
        assert title == returned
        assert "3.10" not in body and "Moim miesiącu" in body


def test_return_title_is_the_one_time_flow_writes():
    source = (_BACKEND / "app/services/hr/time_flow.py").read_text(encoding="utf-8")
    assert 'title=words["timesheet_returned_title"]' in source
    assert hr_mail.RETURNED_TIMESHEET_TITLES == {
        words["timesheet_returned_title"]
        for words in (terms("uop"), terms("b2b"), terms("zlecenie"))
    }


def test_conflict_note_never_goes_by_mail():
    """Kolizja od koordynatora (D5): notatka to wolny tekst — mail ma zdanie typu."""

    title, body = hr_mail.mail_text(
        NotificationType.hr_leave_conflict,
        "Kolizja z Twoją przerwą w świadczeniu usług",
        "23.12–31.12.2026 — Jan Przykładowy: wdrożenie u klienta 28.12",
    )
    assert title == "Kolizja z Twoją przerwą w świadczeniu usług"
    assert "wdrożenie" not in body and "„Moim czasie”" in body


def test_fallback_texts_are_themselves_mail_safe():
    for title, body in hr_mail.FALLBACK.values():
        assert hr_mail.mail_safe(title) and hr_mail.mail_safe(body)


# ── Kogo dotyczy i wyciszenia ───────────────────────────────────────────────


def test_hr_mail_applies_when_a_people_module_runs():
    off = prefs._Context()
    on = prefs._Context(hr_modules={"leave": True})
    employee = _user()
    assert not prefs.APPLIES["hr_people"](employee, off)
    assert prefs.APPLIES["hr_people"](employee, on)
    assert prefs.APPLIES["hr_people"](_user(UserRole.recruiter), on)
    # Admin widzi ekrany „Ludzi” także przy wyłączonych modułach.
    assert prefs.APPLIES["hr_people"](_user(UserRole.admin), off)


def test_muted_people_category_does_not_stop_the_required_mail():
    # Od 26.10.2026 „Czas i ludzie” to mail obowiązkowy: wyciszony dzwonek
    # go nie zatrzymuje, grupa wyłączona dla roli przez admina — tak.
    user = _user()
    spec = next(item for item in delivery.CATALOG if item["id"] == "hr_people")
    assert prefs._item(user, spec, company_enabled=True)["state"] == "on"
    user.muted_notification_categories = {"people": _AT}
    row = prefs._item(user, spec, company_enabled=True)
    assert row["state"] == "on" and row["receiving"] is True
    user.role_muted_notification_types = frozenset({NotificationType.hr_leave_decided})
    by_role = prefs._item(user, spec, company_enabled=True)
    assert by_role["state"] == "role_muted" and by_role["receiving"] is False
    assert "„Czas i ludzie”" in by_role["note"]


# ── Kolejka maili (z bazą) ──────────────────────────────────────────────────


def _policy_on(cutoff: datetime | None = None) -> delivery.DeliveryPolicy:
    cutoff = cutoff or datetime.now(timezone.utc) - timedelta(seconds=5)
    return delivery.DeliveryPolicy.from_value(
        {
            "enabled": True,
            "send_not_before": cutoff.isoformat(),
            "types": {
                kind: {"email_enabled": True, "send_not_before": cutoff.isoformat()}
                for kind in delivery.ROUTINE_KINDS
            },
        }
    )


def _wire(monkeypatch, policy) -> list[tuple[str, str, str, str]]:
    async def load(_db):
        return policy

    monkeypatch.setattr(outbox, "load_policy", load)
    monkeypatch.setattr(delivery, "load_policy_sync", lambda: policy)
    monkeypatch.setattr(outbox, "email_channel_enabled", lambda: True)
    sent: list[tuple[str, str, str, str]] = []

    def fake_send(to, subject, text_body, html_body=None):
        sent.append((to, subject, text_body, html_body or ""))
        return True

    monkeypatch.setattr("app.services.email.send_email", fake_send)
    return sent


async def _account(db, **fields) -> User:
    user = User(
        email=f"hr-mail-{uuid.uuid4().hex}@example.com",
        password_hash="test-only",
        name="Anna Przykładowa",
        role=UserRole.employee,
        roles=["employee"],
        is_active=True,
        **fields,
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user


def _row(user: User, ntype: str, title: str, message: str, link: str):
    return Notification(
        user_id=user.id,
        notification_type=NotificationType(ntype),
        title=title,
        message=message,
        link=link,
        related_entity_type="leave_request",
        related_entity_id=None,
        created_at=datetime.now(timezone.utc),
    )


@pytest.mark.asyncio
async def test_outbox_mails_hr_events_without_absence_kind_or_amounts(monkeypatch):
    async with AsyncSessionLocal() as db:
        boss = await _account(db)
        # Stary wpis wyłączenia „Czas i ludzie” nic nie znaczy — mail jest
        # obowiązkowy od 26.10.2026.
        off = await _account(db, email_opt_outs={"hr_people": _AT})
        # Kolejka bierze najstarsze wiersze paczkami po 50: powiadomienia HR,
        # które inne testy zostawiły przed chwilą (Kadry dostają je od każdego
        # wniosku), zabierały miejsce tym czterem. Wysyłka od teraz — liczą się
        # tylko wiersze tego testu, w każdej kolejności biegu.
        sent = _wire(monkeypatch, _policy_on(datetime.now(timezone.utc)))
        rows = [
            # Treść dla kręgu D6 z rodzajem — mail i tak go nie niesie.
            _row(
                boss,
                "hr_absence_reported",
                "Zgłoszona nieobecność",
                "Jan Przykładowy: Zwolnienie lekarskie (L4) 20.10–24.10.",
                "/people/approvals",
            ),
            _row(
                boss,
                "admin_case_assigned",
                "Przypisano Ci sprawę administracja@",
                "Zaświadczenie dla Jana Przykładowego",
                "/people/cases/7",
            ),
            # Premia ma własny mail (26.10.2026), składany z wiersza premii;
            # wpis bez premii i z obcym tytułem nie wychodzi, kwota nigdy.
            _row(
                boss,
                "hr_bonus_assigned",
                "Premia przyznana",
                "Premia 1 500 zł.",
                "/my-time",
            ),
            # Konto ze starym wyłączeniem „Czas i ludzie” — mail i tak idzie.
            _row(
                off,
                "hr_leave_decided",
                "Wniosek zaakceptowany",
                "20.10–24.10.2026 — akceptacja: Jan Przykładowy.",
                "/my-time",
            ),
        ]
        db.add_all(rows)
        await db.commit()
        ids = [row.id for row in rows]
        try:
            await outbox.dispatch(db)
            await outbox.dispatch(db)  # drugi przebieg nic nie dokłada
            mine = [item for item in sent if item[0] in {boss.email, off.email}]
            assert sorted((to, subject) for to, subject, _t, _h in mine) == sorted(
                [
                    (boss.email, "[Nexus] Przypisano Ci sprawę administracja@"),
                    (boss.email, "[Nexus] Zgłoszona nieobecność"),
                    (off.email, "[Nexus] Wniosek zaakceptowany"),
                ]
            )
            text = "\n".join(body for *_s, body, _h in mine)
            html = "\n".join(h for *_b, h in mine)
            for leaked in ("L4", "lekarsk", "Zaświadczenie", "zł"):
                assert leaked not in text and leaked not in html
            assert "Osoba z Twojego zespołu zgłosiła nieobecność." in text
            assert "/people/approvals" in text and "/people/cases/7" in text
            stamped = dict(
                (
                    await db.execute(
                        select(Notification.id, Notification.email_sent_at).where(
                            Notification.id.in_(ids)
                        )
                    )
                ).all()
            )
            assert stamped[ids[0]] is not None and stamped[ids[1]] is not None
            assert stamped[ids[2]] is None and stamped[ids[3]] is not None
        finally:
            for row in rows:
                await db.delete(row)
            await db.delete(boss)
            await db.delete(off)
            await db.commit()


@pytest.mark.asyncio
async def test_rows_nobody_receives_do_not_block_the_mail_queue(monkeypatch):
    async with AsyncSessionLocal() as db:
        # Pracownik bez sekcji rekrutacji nie dostaje „Klient zaakceptował”
        # (wyciszony dzwonek już nie wystarcza — mail jest obowiązkowy).
        muted = await _account(db)
        boss = await _account(db)
        sent = _wire(monkeypatch, _policy_on(datetime.now(timezone.utc)))
        rows = [
            _row(muted, "client_accepted", "Klient zaakceptował", "Osoba.", "/")
            for _ in range(outbox.BATCH)
        ]
        rows.append(
            _row(
                boss,
                "hr_leave_substitute",
                "Zastępstwo",
                "Zastępujesz: Jan Przykładowy.",
                "/people/calendar",
            )
        )
        db.add_all(rows)
        await db.commit()
        try:
            await outbox.dispatch(db)
            await outbox.dispatch(db)
            assert [to for to, *_ in sent if to == boss.email] == [boss.email]
        finally:
            for row in rows:
                await db.delete(row)
            await db.delete(muted)
            await db.delete(boss)
            await db.commit()


@pytest.mark.asyncio
async def test_outbox_sends_no_hr_mail_while_the_company_kind_is_off(monkeypatch):
    policy = _policy_on()
    types = dict(policy.types)
    types["hr_people"] = {"email_enabled": False}
    sent = _wire(
        monkeypatch,
        delivery.DeliveryPolicy(
            enabled=True, send_not_before=policy.send_not_before, types=types
        ),
    )
    async with AsyncSessionLocal() as db:
        user = await _account(db)
        row = _row(user, "hr_leave_substitute", "Zastępstwo", "Zastępujesz: Jan.", "/")
        db.add(row)
        await db.commit()
        try:
            await outbox.dispatch(db)
            assert not [item for item in sent if item[0] == user.email]
        finally:
            await db.delete(row)
            await db.delete(user)
            await db.commit()


# ── „Maile do Ciebie” (z bazą) ──────────────────────────────────────────────


async def _set_modules(value: dict | None) -> dict | None:
    from app.models.app_setting import AppSetting
    from app.services.hr_foundation_schema import HR_MODULES_SETTING

    async with AsyncSessionLocal() as db:
        row = await db.get(AppSetting, HR_MODULES_SETTING)
        previous = dict(row.value) if row is not None else None
        if row is None:
            db.add(AppSetting(key=HR_MODULES_SETTING, value=value or {}))
        else:
            row.value = value or {}
        await db.commit()
    return previous


@pytest.mark.asyncio
async def test_my_emails_list_the_hr_mail_only_while_a_module_runs(app_client):
    from app.core.security import create_access_token

    async with AsyncSessionLocal() as db:
        user = await _account(db)
    headers = {
        "Authorization": "Bearer "
        + create_access_token(subject=user.id, role=user.role.value)
    }
    previous = await _set_modules({"leave": True})
    try:
        on = await app_client.get("/api/users/me/email-notifications", headers=headers)
        assert on.status_code == 200
        assert "hr_people" in {item["id"] for item in on.json()["items"]}
        # Mail obowiązkowy (26.10.2026) — konto nie może go wyłączyć.
        saved = await app_client.put(
            "/api/users/me/email-notifications/hr_people",
            headers=headers,
            json={"enabled": False},
        )
        assert saved.status_code == 409

        await _set_modules({})
        off = (
            await app_client.get("/api/users/me/email-notifications", headers=headers)
        ).json()
        assert "hr_people" in {ref["id"] for ref in off["not_applicable"]}
        # Mail, który do konta nie trafia, nie ma czego wyłączać.
        refused = await app_client.put(
            "/api/users/me/email-notifications/hr_people",
            headers=headers,
            json={"enabled": False},
        )
        assert refused.status_code == 422
    finally:
        await _set_modules(previous)
        async with AsyncSessionLocal() as db:
            await db.delete(await db.get(User, user.id))
            await db.commit()


# ── „Masz nową premię” (mail obowiązkowy, 26.10.2026) ───────────────────────

# Kwota z cyfrą i walutą albo sama liczba z groszami — nic z tego nie może wyjść.
_AMOUNT_RE = re.compile(r"\d[\d\s]*(?:[.,]\d{2})?\s*(?:zł|pln|eur|usd|€|\$)", re.I)


def test_bonus_kind_is_required_and_mailed_on_its_own():
    assert delivery.notification_kind("hr_bonus_assigned") == "hr_bonus"
    assert "hr_bonus" in delivery.REQUIRED_KINDS
    assert "hr_bonus" in delivery.IMMEDIATE_KINDS
    spec = next(item for item in delivery.CATALOG if item["id"] == "hr_bonus")
    assert spec["label"] == "Masz nową premię"
    sql = str(
        outbox.kind_clause("hr_bonus").compile(
            dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}
        )
    )
    assert "'hr_bonus_assigned'" in sql


@pytest.mark.parametrize("form", ["uop", "b2b", "zlecenie", None])
@pytest.mark.parametrize("event", hr_mail.BONUS_EVENTS)
def test_bonus_text_says_what_for_and_which_month_without_amount(form, event):
    title, body = hr_mail.bonus_text(
        form,
        event=event,
        source="contract_placement",
        period_year=2026,
        period_month=11,
    )
    assert title == terms(form)[f"bonus_{event}_title"]
    assert "Rodzaj: za placement." in body
    assert "Miesiąc rozliczenia: listopad 2026." in body
    assert "„Moim czasie”" in body
    assert not _AMOUNT_RE.search(title) and not _AMOUNT_RE.search(body)


def test_bonus_source_labels_cover_every_source():
    from app.services.hr_payroll_schema import BONUS_SOURCES

    assert set(hr_mail.BONUS_SOURCE_LABELS) == set(BONUS_SOURCES)
    _t, body = hr_mail.bonus_text(
        "uop", event="new", source="manual", period_year=2026, period_month=10
    )
    assert body.startswith("Rodzaj: ręczna. Miesiąc rozliczenia: październik 2026.")


async def _bonus(db, user: User, *, amount: str = "1234.56") -> "HrBonus":
    from decimal import Decimal

    from app.models.hr_payroll import HrBonus

    bonus = HrBonus(
        recipient_user_id=user.id,
        amount=Decimal(amount),
        currency="PLN",
        category="recruiter",
        period_year=2026,
        period_month=11,
        status="assigned",
        source="contract_placement",
        source_key=f"test-{uuid.uuid4().hex}",
        assigned_at=datetime.now(timezone.utc),
    )
    db.add(bonus)
    await db.commit()
    await db.refresh(bonus)
    return bonus


def _bonus_row(user: User, bonus_id: int | None, title: str) -> Notification:
    return Notification(
        user_id=user.id,
        notification_type=NotificationType.hr_bonus_assigned,
        title=title,
        message="Premia za listopad 2026. Szczegóły w „Moim czasie” → Premie.",
        link="/my-time?tab=bonuses",
        related_entity_type="hr_bonus",
        related_entity_id=bonus_id,
        created_at=datetime.now(timezone.utc),
    )


@pytest.mark.asyncio
async def test_outbox_mails_the_bonus_without_amount(monkeypatch):
    async with AsyncSessionLocal() as db:
        person = await _account(db)
        other = await _account(db)
        # Stary wpis wyłączenia nic nie znaczy — mail jest obowiązkowy.
        person.email_opt_outs = {"hr_bonus": _AT}
        await db.commit()
        sent = _wire(monkeypatch, _policy_on(datetime.now(timezone.utc)))
        mine = await _bonus(db, person)
        foreign = await _bonus(db, other)
        new_title = terms(None)["bonus_new_title"]
        rows = [
            _bonus_row(person, mine.id, new_title),
            # Premia innej osoby pod cudzym dzwonkiem — bez maila.
            _bonus_row(person, foreign.id, new_title),
            # Dzwonek bez id premii (`notify_each(fresh=True)`) — bez maila.
            _bonus_row(person, None, new_title),
        ]
        db.add_all(rows)
        await db.commit()
        ids = [row.id for row in rows]
        try:
            await outbox.dispatch(db)
            await outbox.dispatch(db)
            got = [item for item in sent if item[0] == person.email]
            assert [subject for _to, subject, *_ in got] == [f"[Nexus] {new_title}"]
            _to, _subject, text, html = got[0]
            assert "Rodzaj: za placement." in text
            assert "Miesiąc rozliczenia: listopad 2026." in text
            assert "/my-time?tab=bonuses" in text
            for body in (text, html):
                assert not _AMOUNT_RE.search(body)
                assert "1234" not in body and "1 234" not in body
            stamped = dict(
                (
                    await db.execute(
                        select(Notification.id, Notification.email_sent_at).where(
                            Notification.id.in_(ids)
                        )
                    )
                ).all()
            )
            assert stamped[ids[0]] is not None
            assert stamped[ids[1]] is None and stamped[ids[2]] is None
        finally:
            for row in rows:
                await db.delete(row)
            await db.delete(mine)
            await db.delete(foreign)
            await db.commit()
            await db.delete(person)
            await db.delete(other)
            await db.commit()


def test_bonus_mail_applies_only_while_the_payroll_module_runs():
    employee = _user()
    assert not prefs.APPLIES["hr_bonus"](employee, prefs._Context())
    assert not prefs.APPLIES["hr_bonus"](
        employee, prefs._Context(hr_modules={"leave": True})
    )
    assert prefs.APPLIES["hr_bonus"](
        employee, prefs._Context(hr_modules={"payroll": True})
    )


@pytest.mark.asyncio
async def test_bonus_mail_cannot_be_switched_off_and_not_where_it_does_not_apply():
    employee = _user()
    # Bez modułu płac mail konta nie dotyczy — nie ma czego wyłączać.
    with pytest.raises(prefs.EmailKindNotApplicable):
        await prefs.set_enabled(object(), employee, "hr_bonus", False)
    assert employee.email_opt_outs == {}
