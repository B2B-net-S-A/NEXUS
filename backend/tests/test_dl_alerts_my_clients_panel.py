"""Panel „Moi klienci" — cykle przypomnień, karty, odhaczenie, maile.

Ticket (09.2026): powiadomienia o zamówieniach i kontraktach klientów wychodzą
z widgetu „Moje zadania" do osobnego panelu. Sedno testów:

* cykl datowy T-30 → co 7 dni → T-14 (mail) → T-7 (wysoki priorytet + mail),
  liczony z zakresu, więc dzień bez skanera nie gubi progu;
* MD startuje przy 21 MD, kosztowe przy 10 000 zł, wysoki priorytet = ~7 dni
  roboczych przy tempie TEGO zamówienia;
* odhaczenie zamyka całą sprawę (wszystkie powtórki), zatrzymuje dalsze
  przypomnienia i zostawia ślad w historii zamówienia;
* przyczyna, która ustąpiła, zamyka kartę automatycznie (``resolved``), a to
  nie jest odhaczenie Delivery Leada.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import pytest
from httpx import AsyncClient
from sqlalchemy import select

_TODAY = date(2026, 10, 1)


# ── Seedy ───────────────────────────────────────────────────────────────────


async def _seed_client() -> int:
    from app.core.database import AsyncSessionLocal
    from app.models.client import Client

    async with AsyncSessionLocal() as db:
        client = Client(name=f"Panel-{uuid.uuid4().hex[:8]}")
        db.add(client)
        await db.commit()
        await db.refresh(client)
        return client.id


async def _seed_dl(client_id: int) -> tuple[int, str, str]:
    from app.core.database import AsyncSessionLocal
    from app.core.security import hash_password
    from app.models.team_structure import DeliveryLeadClientAssignment
    from app.models.user import User, UserRole

    suffix = uuid.uuid4().hex[:8]
    email = f"panel-dl-{suffix}@example.com"
    password = f"T3st_{suffix}!PassX"
    async with AsyncSessionLocal() as db:
        user = User(
            email=email,
            password_hash=hash_password(password),
            name="DL Panel",
            role=UserRole.delivery_lead,
            is_active=True,
            profile_completed=True,
        )
        db.add(user)
        await db.commit()
        await db.refresh(user)
        db.add(
            DeliveryLeadClientAssignment(
                client_id=client_id, delivery_lead_user_id=user.id
            )
        )
        await db.commit()
        return user.id, email, password


async def _headers(app_client: AsyncClient, email: str, password: str) -> dict:
    resp = await app_client.post(
        "/api/auth/login", json={"email": email, "password": password}
    )
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


async def _seed_contract(
    client_id: int, *, first: str = "Anna", last: str | None = None
):
    from app.core.database import AsyncSessionLocal
    from app.models.candidate import Candidate
    from app.models.contract import Contract, ContractStatus

    async with AsyncSessionLocal() as db:
        cand = Candidate(
            name=first,
            lastname=last or f"Testowa-{uuid.uuid4().hex[:6]}",
            email=f"panel-{uuid.uuid4().hex[:8]}@example.com",
        )
        db.add(cand)
        await db.commit()
        await db.refresh(cand)
        contract = Contract(
            candidate_id=cand.id,
            client_id=client_id,
            status=ContractStatus.active,
            rate_candidate=Decimal("100.000"),
        )
        db.add(contract)
        await db.commit()
        await db.refresh(contract)
        return contract.id, f"{cand.name} {cand.lastname}"


async def _seed_periodic_order(client_id: int, contract_id: int, end: date) -> int:
    from app.core.database import AsyncSessionLocal
    from app.models.client_order import ClientOrder, ClientOrderStatus

    async with AsyncSessionLocal() as db:
        order = ClientOrder(
            client_id=client_id,
            contract_id=contract_id,
            title=f"ZAM-{uuid.uuid4().hex[:6]}",
            status=ClientOrderStatus.active,
            start_date=date(2026, 1, 1),
            end_date=end,
            rate_client=Decimal("150.000"),
        )
        db.add(order)
        await db.commit()
        await db.refresh(order)
        return order.id


async def _alerts(user_id: int, alert_type: str):
    from app.core.database import AsyncSessionLocal
    from app.models.dl_alert import DlAlert

    async with AsyncSessionLocal() as db:
        return list(
            (
                await db.scalars(
                    select(DlAlert)
                    .where(DlAlert.user_id == user_id, DlAlert.alert_type == alert_type)
                    .order_by(DlAlert.id)
                )
            ).all()
        )


async def _run(rule, monkeypatch, today: date):
    from app.core.database import AsyncSessionLocal
    import app.tasks.dl_alerts_scanner as scanner

    monkeypatch.setattr(scanner, "business_today", lambda: today)
    async with AsyncSessionLocal() as db:
        await rule(db)
        await db.commit()


# ── Czyste funkcje ──────────────────────────────────────────────────────────


def test_workdays_skip_weekends_and_polish_holidays():
    from app.services.order_burn_rate import workdays_between

    # Listopad 2026: 1.11 to niedziela, 11.11 (środa) — Święto Niepodległości.
    assert workdays_between(date(2026, 11, 9), date(2026, 11, 13)) == 4
    assert workdays_between(date(2026, 11, 14), date(2026, 11, 15)) == 0
    assert workdays_between(date(2026, 11, 13), date(2026, 11, 12)) == 0


def test_burn_rate_uses_order_history_and_start_date():
    from app.services.order_burn_rate import (
        burn_rate_from_reports,
        high_priority_threshold,
        md_burn_rate,
    )

    # Wrzesień 2026 ma 22 dni robocze; start zamówienia 15.09 → 12 dni.
    rate = burn_rate_from_reports(
        [("2026-09", Decimal("12"))], order_start=date(2026, 9, 15), today=_TODAY
    )
    assert rate == Decimal("1")
    assert burn_rate_from_reports([], order_start=None, today=_TODAY) is None
    assert (
        burn_rate_from_reports(
            [("2026-09", Decimal("0"))], order_start=None, today=_TODAY
        )
        is None
    ), "zerowe zużycie to brak tempa, nie nieskończony zapas"

    estimated = md_burn_rate([], order_start=None, today=_TODAY, consultants=3)
    assert estimated is not None and estimated.estimated
    assert high_priority_threshold(estimated, 7) == Decimal("21")


def test_date_cycle_thresholds():
    from app.services.dl_alerts import date_cycle_stage

    assert date_cycle_stage(30) == (None, "standard", False)
    assert date_cycle_stage(15) == (None, "standard", False)
    assert date_cycle_stage(14) == ("t14", "standard", True)
    assert date_cycle_stage(8) == ("t14", "standard", True)
    assert date_cycle_stage(7) == ("t7", "high", True)
    assert date_cycle_stage(0) == ("t7", "high", True)


def test_new_contractor_missing_fields():
    from app.models.client_order import ClientOrder
    from app.services.dl_alerts import new_contractor_missing_fields

    draft = ClientOrder(title="Jan Nowak — Java Developer", start_date=date(2026, 9, 1))
    assert new_contractor_missing_fields(
        draft, candidate_name="Jan Nowak", job_title="Java Developer"
    ) == ["stawkę przychodową", "okres zamówienia", "numer zamówienia"]

    done = ClientOrder(
        title="PO/2026/77",
        start_date=date(2026, 9, 1),
        end_date=date(2026, 12, 31),
        rate_client=Decimal("150"),
    )
    assert (
        new_contractor_missing_fields(done, candidate_name="Jan Nowak", job_title="X")
        == []
    )


# ── Cykl zamówienia okresowego ──────────────────────────────────────────────


async def test_periodic_order_cycle_t30_weekly_t14_email_t7_high(monkeypatch):
    from app.models.dl_alert import ALERT_PERIODIC_ORDER_ENDING
    from app.tasks.dl_alerts_scanner import rule_periodic_order_ending

    client_id = await _seed_client()
    user_id, _, _ = await _seed_dl(client_id)
    contract_id, name = await _seed_contract(client_id)
    end = _TODAY + timedelta(days=30)
    order_id = await _seed_periodic_order(client_id, contract_id, end)

    # Zegar emisji startuje od TERAZ: `created_at` wierszy stawia baza
    # (`now()`), a okno powtórki liczy się od niego.
    moment = datetime.now(timezone.utc)
    import app.services.dl_alerts as svc

    class _Clock(datetime):
        current = moment

        @classmethod
        def now(cls, tz=None):  # noqa: D401
            return cls.current

    monkeypatch.setattr(svc, "datetime", _Clock)

    await _run(rule_periodic_order_ending, monkeypatch, _TODAY)
    rows = await _alerts(user_id, ALERT_PERIODIC_ORDER_ENDING)
    assert len(rows) == 1
    assert rows[0].priority == "standard"
    assert rows[0].link == f"/clients/{client_id}?tab=zamowienia&order={order_id}"
    assert name in rows[0].message and end.isoformat() in rows[0].message
    assert not (rows[0].payload or {}).get("email")

    # Dzień później: bez nowego wiersza.
    _Clock.current = moment + timedelta(days=1)
    await _run(rule_periodic_order_ending, monkeypatch, _TODAY + timedelta(days=1))
    assert len(await _alerts(user_id, ALERT_PERIODIC_ORDER_ENDING)) == 1

    # Ponad tydzień później: powtórka jako nowy wiersz (+8 d, bo `created_at`
    # bazy jest o ułamek sekundy późniejszy niż start zegara testu).
    _Clock.current = moment + timedelta(days=8)
    await _run(rule_periodic_order_ending, monkeypatch, _TODAY + timedelta(days=8))
    assert len(await _alerts(user_id, ALERT_PERIODIC_ORDER_ENDING)) == 2

    # T-13 (skaner NIE ruszył w dniu T-14) — próg t14 i tak wpada, z mailem.
    _Clock.current = moment + timedelta(days=17)
    await _run(rule_periodic_order_ending, monkeypatch, _TODAY + timedelta(days=17))
    rows = await _alerts(user_id, ALERT_PERIODIC_ORDER_ENDING)
    assert rows[-1].dedupe_key.endswith(":t14")
    assert (rows[-1].payload or {}).get("email") is True

    # T-7 — wysoki priorytet + mail.
    _Clock.current = moment + timedelta(days=23)
    await _run(rule_periodic_order_ending, monkeypatch, _TODAY + timedelta(days=23))
    rows = await _alerts(user_id, ALERT_PERIODIC_ORDER_ENDING)
    assert rows[-1].dedupe_key.endswith(":t7")
    assert rows[-1].priority == "high"
    assert (rows[-1].payload or {}).get("email") is True
    assert len({r.event_key for r in rows}) == 1, "jedna sprawa = jeden klucz karty"


async def test_extended_order_resolves_old_card_and_starts_new_cycle(monkeypatch):
    from app.core.database import AsyncSessionLocal
    from app.models.client_order import ClientOrder
    from app.models.dl_alert import ALERT_PERIODIC_ORDER_ENDING
    from app.tasks.dl_alerts_scanner import rule_periodic_order_ending

    client_id = await _seed_client()
    user_id, _, _ = await _seed_dl(client_id)
    contract_id, _ = await _seed_contract(client_id)
    order_id = await _seed_periodic_order(
        client_id, contract_id, _TODAY + timedelta(days=10)
    )

    await _run(rule_periodic_order_ending, monkeypatch, _TODAY)
    assert [r.status for r in await _alerts(user_id, ALERT_PERIODIC_ORDER_ENDING)] == [
        "new"
    ]

    async with AsyncSessionLocal() as db:
        order = await db.get(ClientOrder, order_id)
        order.end_date = _TODAY + timedelta(days=25)
        await db.commit()

    await _run(rule_periodic_order_ending, monkeypatch, _TODAY)
    rows = await _alerts(user_id, ALERT_PERIODIC_ORDER_ENDING)
    assert [r.status for r in rows] == ["resolved", "new"]
    assert rows[0].handled_by_user_id is None, "auto-zamknięcie to nie odhaczenie DL"
    assert rows[0].event_key != rows[1].event_key


# ── MD i kosztowe ───────────────────────────────────────────────────────────


async def _seed_md_line(client_id: int, contract_id: int, remaining: str) -> int:
    from app.core.database import AsyncSessionLocal
    from app.models.client_order import ClientOrder, ClientOrderStatus
    from app.models.client_order_group import GROUP_STATUS_ACTIVE, ClientOrderGroup
    from app.models.md_consumption import ClientOrderMdConsumption

    async with AsyncSessionLocal() as db:
        group = ClientOrderGroup(
            client_id=client_id,
            order_number=f"MD-{uuid.uuid4().hex[:6]}",
            start_date=date(2026, 9, 1),
            status=GROUP_STATUS_ACTIVE,
            order_type="md",
        )
        db.add(group)
        await db.flush()
        line = ClientOrder(
            client_id=client_id,
            contract_id=contract_id,
            title=group.order_number,
            status=ClientOrderStatus.active,
            order_group_id=group.id,
            start_date=date(2026, 9, 1),
            md_rate_revenue=Decimal("1200"),
            md_input_mode="md",
            md_input_value=Decimal("40"),
            md_total=Decimal("40"),
            md_remaining=Decimal(remaining),
        )
        db.add(line)
        await db.flush()
        # Wrzesień 2026: 22 dni robocze, zaraportowano 22 MD → 1 MD/dzień.
        db.add(
            ClientOrderMdConsumption(
                order_id=line.id,
                period_month="2026-09",
                md_reported=Decimal("22"),
                source="manual",
            )
        )
        await db.commit()
        return line.id


async def test_md_starts_at_21_and_escalates_on_order_burn_rate(monkeypatch):
    from app.models.dl_alert import ALERT_MD_BUDGET_LOW
    from app.tasks.dl_alerts_scanner import rule_md_budget_low

    client_id = await _seed_client()
    user_id, _, _ = await _seed_dl(client_id)
    contract_id, _ = await _seed_contract(client_id)
    line_id = await _seed_md_line(client_id, contract_id, remaining="21")

    await _run(rule_md_budget_low, monkeypatch, _TODAY)
    rows = [
        r for r in await _alerts(user_id, ALERT_MD_BUDGET_LOW) if r.order_id == line_id
    ]
    assert len(rows) == 1 and rows[0].priority == "standard"

    from app.core.database import AsyncSessionLocal
    from app.models.client_order import ClientOrder

    async with AsyncSessionLocal() as db:
        line = await db.get(ClientOrder, line_id)
        line.md_remaining = Decimal("7")  # = 7 dni roboczych przy 1 MD/dzień
        await db.commit()

    await _run(rule_md_budget_low, monkeypatch, _TODAY)
    rows = [
        r for r in await _alerts(user_id, ALERT_MD_BUDGET_LOW) if r.order_id == line_id
    ]
    assert rows[-1].priority == "high"
    assert rows[-1].dedupe_key.endswith(":high")
    assert (rows[-1].payload or {}).get("email") is True


async def test_cost_order_starts_at_10000_without_amounts_in_text(monkeypatch):
    from app.core.database import AsyncSessionLocal
    from app.models.client_order_group import GROUP_STATUS_ACTIVE, ClientOrderGroup
    from app.models.dl_alert import ALERT_COST_BUDGET_LOW
    from app.tasks.dl_alerts_scanner import rule_cost_budget_low

    client_id = await _seed_client()
    user_id, _, _ = await _seed_dl(client_id)
    async with AsyncSessionLocal() as db:
        group = ClientOrderGroup(
            client_id=client_id,
            order_number=f"KOSZT-{uuid.uuid4().hex[:6]}",
            start_date=date(2026, 9, 1),
            status=GROUP_STATUS_ACTIVE,
            order_type="cost",
            is_cost_based=True,
            budget_amount=Decimal("200000"),
            budget_remaining=Decimal("9876.54"),
        )
        db.add(group)
        await db.commit()
        group_id = group.id

    await _run(rule_cost_budget_low, monkeypatch, _TODAY)
    rows = [
        r
        for r in await _alerts(user_id, ALERT_COST_BUDGET_LOW)
        if r.order_group_id == group_id
    ]
    assert len(rows) == 1
    # Bez faktur nie ma tempa → brak progu dynamicznego, tylko standard.
    assert rows[0].priority == "standard"
    assert "9876" not in rows[0].message and "9 876" not in rows[0].message
    assert rows[0].link == f"/clients/{client_id}?tab=zamowienia&group={group_id}"


# ── Karty, odhaczenie, historia ─────────────────────────────────────────────


async def test_cards_group_repeats_and_handling_closes_the_whole_case(
    app_client: AsyncClient,
):
    from app.core.database import AsyncSessionLocal
    from app.models.activity import Activity
    from app.models.dl_alert import ALERT_PERIODIC_ORDER_ENDING
    from app.services.dl_alerts import emit

    client_id = await _seed_client()
    user_id, email, password = await _seed_dl(client_id)
    contract_id, name = await _seed_contract(client_id)
    order_id = await _seed_periodic_order(
        client_id, contract_id, _TODAY + timedelta(days=6)
    )
    now = datetime.now(timezone.utc)

    async with AsyncSessionLocal() as db:
        for stage, priority, when in (
            (None, "standard", now - timedelta(days=16)),
            ("t14", "standard", now - timedelta(days=8)),
            ("t7", "high", now),
        ):
            await emit(
                db,
                alert_type=ALERT_PERIODIC_ORDER_ENDING,
                user_ids=[user_id],
                client_id=client_id,
                entity_key=f"order:{order_id}:end:2026-10-07",
                title="t",
                message=f"Zamówienie dla {name} kończy się 2026-10-07.",
                link=f"/clients/{client_id}?tab=zamowienia&order={order_id}",
                payload={"candidate_name": name, "end_date": "2026-10-07"},
                order_id=order_id,
                repeat_every_days=7,
                stage=stage,
                priority=priority,
                email=stage is not None,
                now=when,
            )
        await db.commit()

    headers = await _headers(app_client, email, password)
    resp = await app_client.get("/api/dl-alerts/cards", headers=headers)
    assert resp.status_code == 200, resp.text
    cards = resp.json()["cards"]
    assert len(cards) == 1, "trzy powtórki jednej sprawy to jedna karta"
    card = cards[0]
    assert card["priority"] == "high"
    assert card["section"] == "ending"
    assert card["repeat_count"] == 3
    assert card["candidate_name"] == name
    assert card["email_requested"] is True
    assert card["can_mark_handled"] is True

    done = await app_client.post(
        f"/api/dl-alerts/{card['id']}/handled", headers=headers
    )
    assert done.status_code == 200, done.text

    rows = await _alerts(user_id, ALERT_PERIODIC_ORDER_ENDING)
    assert {r.status for r in rows} == {"handled"}
    assert all(r.handled_by_user_id == user_id for r in rows)

    after = await app_client.get("/api/dl-alerts/cards", headers=headers)
    assert after.json()["cards"] == []

    async with AsyncSessionLocal() as db:
        activity = await db.scalar(
            select(Activity).where(
                Activity.entity_type == "client_order",
                Activity.entity_id == order_id,
                Activity.action == "dl_alert_handled",
            )
        )
    assert activity is not None and activity.user_id == user_id
    assert activity.details["candidate_name"] == name
    assert len(activity.details["dl_alert_ids"]) == 3

    # Odhaczona sprawa nie wraca, choć warunek trwa.
    async with AsyncSessionLocal() as db:
        again = await emit(
            db,
            alert_type=ALERT_PERIODIC_ORDER_ENDING,
            user_ids=[user_id],
            client_id=client_id,
            entity_key=f"order:{order_id}:end:2026-10-07",
            title="t",
            message="m",
            repeat_every_days=7,
            stage="t7",
            now=now + timedelta(days=3),
        )
        await db.commit()
    assert again == []


async def test_resolved_episode_can_alert_again():
    from app.core.database import AsyncSessionLocal
    from app.models.dl_alert import ALERT_COST_BUDGET_LOW
    from app.services.dl_alerts import emit, resolve_stale

    client_id = await _seed_client()
    user_id, _, _ = await _seed_dl(client_id)
    key = f"group:{uuid.uuid4().int % 10**9}"
    async with AsyncSessionLocal() as db:
        first = await emit(
            db,
            alert_type=ALERT_COST_BUDGET_LOW,
            user_ids=[user_id],
            client_id=client_id,
            entity_key=key,
            title="t",
            message="m",
            repeat_every_days=7,
        )
        assert len(first) == 1
        await resolve_stale(
            db,
            alert_type=ALERT_COST_BUDGET_LOW,
            live_event_keys={"cost_budget_low:group:inny:1"},
            entity_prefix=key,
        )
        second = await emit(
            db,
            alert_type=ALERT_COST_BUDGET_LOW,
            user_ids=[user_id],
            client_id=client_id,
            entity_key=key,
            title="t",
            message="m",
            repeat_every_days=7,
        )
        await db.commit()
    assert len(second) == 1, "warunek wrócił po zamknięciu — nowy epizod alarmuje"
    assert second[0].dedupe_key.endswith(":e1:0")


async def test_email_is_sent_once_for_threshold_rows(monkeypatch):
    from app.core.database import AsyncSessionLocal
    from app.models.dl_alert import ALERT_PERIODIC_ORDER_ENDING, DlAlert
    import app.services.email as email_mod
    import app.services.m365.system_mail as system_mail
    from app.services.dl_alerts import emit, send_pending_alert_emails

    client_id = await _seed_client()
    user_id, email, _ = await _seed_dl(client_id)
    sent: list[tuple[str, str]] = []

    async def _no_connection(_db):
        return None

    monkeypatch.setattr(system_mail, "get_system_sender_connection", _no_connection)
    monkeypatch.setattr(email_mod, "email_channel_enabled", lambda: True)
    monkeypatch.setattr(
        email_mod,
        "send_email",
        lambda to, subject, text, html=None: sent.append((to, subject)) or True,
    )

    async with AsyncSessionLocal() as db:
        created = await emit(
            db,
            alert_type=ALERT_PERIODIC_ORDER_ENDING,
            user_ids=[user_id],
            client_id=client_id,
            entity_key=f"order:{uuid.uuid4().int % 10**9}:end:2026-10-10",
            title="Zamówienie kończy się",
            message="m",
            link="/clients/1?tab=zamowienia&order=1",
            stage="t14",
            email=True,
        )
        await db.commit()
        alert_id = created[0].id
        await send_pending_alert_emails(db)
        await send_pending_alert_emails(db)

    assert [to for to, _ in sent].count(email) == 1
    async with AsyncSessionLocal() as db:
        row = await db.get(DlAlert, alert_id)
    assert row.email_sent_at is not None


async def test_order_mail_review_names_client_and_candidate():
    from app.core.database import AsyncSessionLocal
    from app.models.dl_alert import ALERT_ORDER_MAIL_REVIEW
    from app.models.order_mail import OUTCOME_NEEDS_REVIEW, OrderMailDocument
    from app.services.order_mail_ingest import notify_review

    client_id = await _seed_client()
    user_id, _, _ = await _seed_dl(client_id)
    async with AsyncSessionLocal() as db:
        doc = OrderMailDocument(
            internet_message_id=f"<{uuid.uuid4().hex}@example.com>",
            outcome=OUTCOME_NEEDS_REVIEW,
            client_id=client_id,
            attachment_name="zam.pdf",
            extraction={"consultant_rows": [{"consultant_name": "Maria Fikcyjna"}]},
        )
        db.add(doc)
        await db.commit()
        await db.refresh(doc)
        assert await notify_review(db, doc) == 1
        await db.commit()
        doc_id = doc.id

    rows = await _alerts(user_id, ALERT_ORDER_MAIL_REVIEW)
    assert rows, "DL klienta nie dostał karty"
    assert "Maria Fikcyjna" in rows[-1].message
    assert "Panel-" in rows[-1].message, "brak nazwy klienta w treści"
    assert rows[-1].link == f"/order-mail?doc={doc_id}"


# ── „Moje zadania" bez spraw klientów ───────────────────────────────────────


@pytest.mark.asyncio
async def test_my_tasks_can_exclude_delivery_notifications(
    app_client: AsyncClient, app_auth_headers: dict[str, str]
):
    from app.core.database import AsyncSessionLocal
    from app.models.notification import Notification, NotificationType

    me = await app_client.get("/api/auth/me", headers=app_auth_headers)
    uid = me.json()["id"]
    marker = uuid.uuid4().hex[:8]
    async with AsyncSessionLocal() as db:
        db.add_all(
            [
                Notification(
                    user_id=uid,
                    title=f"kandydat-{marker}",
                    message="m",
                    notification_type=NotificationType.candidate_added,
                ),
                Notification(
                    user_id=uid,
                    title=f"zamowienie-{marker}",
                    message="m",
                    notification_type=NotificationType.client_order_ending_14d,
                ),
            ]
        )
        await db.commit()

    full = await app_client.get(
        "/api/notifications?limit=200", headers=app_auth_headers
    )
    filtered = await app_client.get(
        "/api/notifications?limit=200&exclude_section=delivery",
        headers=app_auth_headers,
    )
    assert filtered.status_code == 200, filtered.text
    titles = {i["title"] for i in filtered.json()["items"]}
    assert f"kandydat-{marker}" in titles
    assert f"zamowienie-{marker}" not in titles
    assert {i["title"] for i in full.json()["items"]} >= {
        f"kandydat-{marker}",
        f"zamowienie-{marker}",
    }, "dzwonek (bez parametru) widzi wszystko jak dotąd"
    assert filtered.json()["unread_count"] == full.json()["unread_count"] - 1

    bad = await app_client.get(
        "/api/notifications?exclude_section=nieznana", headers=app_auth_headers
    )
    assert bad.status_code == 422


async def test_checked_off_case_alerts_again_after_the_cause_went_away_and_came_back():
    """Odhaczenie zatrzymuje TEN epizod, nie sprawę na zawsze.

    Pula MD odhaczona przy 21 MD, potem uzupełniona (warunek ustał), a po
    miesiącach znowu niska — to nowa sytuacja i ma przyjść nowa karta.
    """
    from app.core.database import AsyncSessionLocal
    from app.models.dl_alert import ALERT_MD_BUDGET_LOW, DlAlert
    from app.services.dl_alerts import emit, resolve_stale

    client_id = await _seed_client()
    user_id, _, _ = await _seed_dl(client_id)
    key = f"group:{uuid.uuid4().int % 10**9}"

    async def _emit(db):
        return await emit(
            db,
            alert_type=ALERT_MD_BUDGET_LOW,
            user_ids=[user_id],
            client_id=client_id,
            entity_key=key,
            title="t",
            message="m",
            repeat_every_days=7,
        )

    async with AsyncSessionLocal() as db:
        (first,) = await _emit(db)
        first.status = "handled"
        first.handled_at = datetime.now(timezone.utc)
        first.handled_by_user_id = user_id
        await db.commit()

        assert await _emit(db) == [], "odhaczona sprawa nie wraca, póki warunek trwa"

        # Warunek ustał (pula uzupełniona) — klucz nie jest żywy.
        assert (
            await resolve_stale(
                db,
                alert_type=ALERT_MD_BUDGET_LOW,
                live_event_keys={"md_budget_low:group:inny:1"},
                entity_prefix=f"{key}:",
            )
            == 0
        ), "odhaczona karta nie jest „zamykana automatycznie"
        await db.commit()

        again = await _emit(db)
        await db.commit()
    assert len(again) == 1
    assert again[0].dedupe_key.endswith(":e1:0")
    async with AsyncSessionLocal() as db:
        handled = await db.get(DlAlert, first.id)
    assert handled.status == "handled" and handled.handled_by_user_id == user_id
