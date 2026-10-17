"""Poprawki znalezisk po przeglądzie programu „Ludzie w NEXUSIE” (17.10.2026).

1. trwałe usunięcie kontraktu zamyka sprawę „Wejście konsultanta”, a awaria
   spraw nie blokuje usunięcia,
2. czytnik administracja@ czyta dalej, gdy w oknie nakładki leży pełna paczka,
3. automat premii i zmiana stawki czekają na trwające zamknięcie miesiąca płac
   (okres pod blokadą współdzieloną, potem reszta),
4. ponowny import z Compassa nie nadpisuje fragmentów opisu, domyślnych opisów
   ról ani wpisów timesheetu zmienionych w NEXUSIE,
5. ślad rozmowy opieki niesie wszystkie zamknięte punkty planu,
6. przekierowanie poczty tylko do zastępcy z adresem w domenie firmy (422 przy
   wniosku, odmowa wykonawcy bez adresu w ``last_error``),
8. cofnięcie decyzji recepcji przy urządzeniu z Intune.

Dane fikcyjne (repo jest publiczne).
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

import pytest
from sqlalchemy import delete, select

from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.core.scheduling import business_today, local_now
from app.models.admin_case import AdminCase, AdminCaseComment, AdminMailIngestState
from app.models.contract import Contract
from app.models.contract_care import CarePlanItem
from app.models.equipment_intune import EquipmentIntuneDevice
from app.models.hr_ops import HrAuditEvent
from app.models.hr_payroll import EmployeeRate, PayrollPeriod
from app.models.hr_profile import EmployeeProfile
from app.models.hr_time import (
    Timesheet,
    TimesheetEntry,
    TimesheetRoleDefault,
    TimesheetTemplate,
)
from app.services.admin_cases import hooks as case_hooks
from app.services.admin_cases import mail_ingest
from app.services.care import access as care_access
from app.services.care import records as care_records
from app.services.contract_lifecycle import hard_delete_contract
from app.services.equipment import intune
from app.services.hr import payroll_periods, payroll_rates, time_entries
from app.services.hr.bonus_rules import eligible_date
from app.services.hr.compass_import import time as time_import
from app.services.hr.m365 import executor
from app.services.hr.payroll_errors import PayrollConflict
from tests.hr.fakes import FakeMailboxOps
from tests.hr.m365_helpers import at, make_due, make_leave, operations, plan
from tests.hr.m365_helpers import make_user as make_staff
from tests.test_admin_cases_mail_ingest import (  # noqa: F401  (fixture'y)
    FakeMailbox,
    _cases_for,
    _run,
    cases_on,
    contract_id,
    mailbox_on,
)
from tests.test_care_api import care_on, make_client, make_contract  # noqa: F401
from tests.test_equipment_intune import (  # noqa: F401  (fixture'y)
    _device as intune_device,
    _devices as intune_devices,
    _headers as intune_headers,
    _run as intune_run,
    api,
    modules_state,
    people,
)
from tests.test_hr_bonus_automation import (  # noqa: F401
    _bonuses,
    _person,
    _placement,
    _reconcile,
    payroll_on,
)
from tests.test_hr_compass_import_leave import make_bundle, make_person
from tests.test_hr_leave_api import (  # noqa: F401
    BASE as LEAVE,
    _body,
    _headers,
    _pool,
    _user,
    modules_on,
)
from tests.test_review_payroll_leave import _apply_bundle, _dry_run

D = date


# ── 1. Trwałe usunięcie kontraktu a sprawa „Wejście konsultanta” ─────────────


async def _case_of(contract: int) -> AdminCase:
    async with AsyncSessionLocal() as db:
        return await db.scalar(
            select(AdminCase).where(
                AdminCase.source_key == case_hooks.contract_source_key(contract)
            )
        )


@pytest.mark.asyncio
async def test_hard_delete_closes_the_onboarding_case(
    contract_id: int,  # noqa: F811
    cases_on,  # noqa: F811
) -> None:
    async with AsyncSessionLocal() as db:
        contract = await db.get(Contract, contract_id)
        await case_hooks.open_case_for_new_contract(db, contract)
        await db.commit()
    opened = await _case_of(contract_id)
    assert opened is not None and opened.status == "new"

    async with AsyncSessionLocal() as db:
        contract = await db.get(Contract, contract_id)
        await hard_delete_contract(db, contract, actor_id=None)
        await db.commit()

    closed = await _case_of(contract_id)
    assert closed.status == "closed"
    assert closed.contract_id is None  # FK SET NULL
    async with AsyncSessionLocal() as db:
        notes = list(
            await db.scalars(
                select(AdminCaseComment.body).where(
                    AdminCaseComment.case_id == closed.id
                )
            )
        )
    assert any("usunięty" in note for note in notes)


@pytest.mark.asyncio
async def test_case_failure_does_not_block_the_hard_delete(
    contract_id: int,  # noqa: F811
    cases_on,  # noqa: F811
    monkeypatch,
) -> None:
    async def broken(db, contract_id):
        raise RuntimeError("awaria modułu spraw")

    monkeypatch.setattr(case_hooks, "close_case_for_deleted_contract", broken)
    async with AsyncSessionLocal() as db:
        contract = await db.get(Contract, contract_id)
        await case_hooks.open_case_for_new_contract(db, contract)
        await db.commit()
    async with AsyncSessionLocal() as db:
        contract = await db.get(Contract, contract_id)
        await hard_delete_contract(db, contract, actor_id=None)
        await db.commit()
    async with AsyncSessionLocal() as db:
        assert await db.get(Contract, contract_id) is None


# ── 2. Czytnik administracja@: pełna paczka w oknie nakładki ─────────────────


class _CappedMailbox(FakeMailbox):
    """Jak Graph: rosnąco po dacie odebrania, najwyżej ``MAX_MESSAGES_PER_RUN``."""

    async def list_messages(self, mailbox: str, since: datetime) -> list[dict]:
        found = await super().list_messages(mailbox, since)
        found.sort(key=lambda m: m["receivedDateTime"])
        return found[: mail_ingest.MAX_MESSAGES_PER_RUN]


@pytest.mark.usefixtures("mailbox_on")
async def test_full_batch_inside_the_overlap_window_does_not_stall_the_reader(
    monkeypatch,
) -> None:
    monkeypatch.setattr(mail_ingest, "MAX_MESSAGES_PER_RUN", 3)
    fake = _CappedMailbox()
    # Trzy wiadomości w jednym kwadransie — pełna paczka; znacznik staje na
    # najnowszej, a nakładka (2 h) obejmuje wszystkie trzy przy każdym odczycie.
    older = [
        fake.add(subject=f"Zgłoszenie {i}", hours_ago=1.5 - 0.1 * i) for i in range(3)
    ]
    first = await _run(fake)
    assert first["created"] == 3
    newer = [fake.add(subject=f"Nowe {i}", hours_ago=0.5 - 0.1 * i) for i in range(3)]

    for _ in range(4):
        await _run(fake)

    assert set(await _cases_for(fake)) == {m["id"] for m in older + newer}


@pytest.mark.usefixtures("mailbox_on")
async def test_reader_goes_back_to_the_overlap_after_the_backlog(monkeypatch) -> None:
    monkeypatch.setattr(mail_ingest, "MAX_MESSAGES_PER_RUN", 2)
    fake = _CappedMailbox()
    # Zaległości co 3 h — okno nakładki (2 h) po ich przejściu nie jest pełne.
    batch = [fake.add(subject=f"Zaległe {i}", hours_ago=12 - 3 * i) for i in range(4)]
    for _ in range(4):
        await _run(fake)
    assert set(await _cases_for(fake)) == {m["id"] for m in batch}
    async with AsyncSessionLocal() as db:
        state = await db.get(AdminMailIngestState, 1)
        assert mail_ingest.RESUME_KEY not in (state.stats or {})
    # Spóźniona wiadomość z datą sprzed znacznika (indeksowanie Graph) wpada
    # w nakładkę, gdy zaległości już nie ma.
    late = fake.add(subject="Spóźniona", hours_ago=3.5)
    await _run(fake)
    assert late["id"] in await _cases_for(fake)


# ── 3. Okres płac pod blokadą: automat premii i stawki ──────────────────────


async def _hold_closing(year: int, month: int):
    """Zamknięcie w toku: wiersz okresu pod ``FOR UPDATE``, status już „closed”."""

    closer = AsyncSessionLocal()
    period = await payroll_periods.lock_period(closer, year, month)
    period.status = "closed"
    period.closed_at = local_now()
    await closer.flush()
    return closer


@pytest.mark.asyncio
async def test_placement_proposal_waits_for_running_close_and_moves_on(
    payroll_on,  # noqa: F811
) -> None:
    world = await _placement(started_days_ago=40)
    deadline = eligible_date(business_today() - timedelta(days=40))
    year, month = deadline.year, deadline.month
    closer = await _hold_closing(year, month)
    try:
        task = asyncio.create_task(_reconcile(world["contract"]))
        await asyncio.sleep(0.5)
        assert not task.done()  # czeka na zamknięcie w toku
        await closer.commit()
    finally:
        await closer.close()
    counts = await asyncio.wait_for(task, timeout=20)

    assert counts["created"] == 2
    found = await _bonuses(world["contract"])
    nxt = payroll_periods.add_months(year, month, 1)
    assert {(b.period_year, b.period_month) for b in found.values()} == {nxt}
    assert found["dl"].rule_snapshot["period_shifted_from"] == f"{year}-{month:02d}"


@pytest.mark.asyncio
async def test_rate_change_waits_for_running_close_and_is_refused(
    payroll_on,  # noqa: F811
) -> None:
    today = business_today()
    year, month = payroll_periods.add_months(today.year, today.month, -2)
    async with AsyncSessionLocal() as db:
        person = await _person(db)
        await db.commit()
    closer = await _hold_closing(year, month)

    async def change() -> str:
        async with AsyncSessionLocal() as db:
            try:
                await payroll_rates.set_rate(
                    db,
                    user_id=person.id,
                    hourly_rate=Decimal("123.00"),
                    currency="PLN",
                    effective_from=D(year, month, 1),
                    reason=None,
                    actor_id=person.id,
                    today=today,
                )
            except PayrollConflict:
                await db.rollback()
                return "refused"
            await db.commit()
            return "set"

    try:
        task = asyncio.create_task(change())
        await asyncio.sleep(0.5)
        assert not task.done()
        await closer.commit()
    finally:
        await closer.close()
    assert await asyncio.wait_for(task, timeout=20) == "refused"
    async with AsyncSessionLocal() as db:
        rates = await db.scalars(
            select(EmployeeRate.id).where(EmployeeRate.user_id == person.id)
        )
        assert list(rates) == []


@pytest.mark.asyncio
async def test_rate_lock_does_not_reach_future_months(payroll_on) -> None:  # noqa: F811
    today = business_today()
    future = payroll_periods.add_months(today.year, today.month, 2)
    async with AsyncSessionLocal() as db:
        person = await _person(db)
        await db.commit()
        rate = await payroll_rates.set_rate(
            db,
            user_id=person.id,
            hourly_rate=Decimal("99.00"),
            currency="PLN",
            effective_from=D(*future, 1),
            reason=None,
            actor_id=person.id,
            today=today,
        )
        await db.commit()
        # Miesiąc, który się jeszcze nie skończył, nie może być zamykany —
        # nie zakładamy dla niego okresu.
        created = await db.scalar(
            select(PayrollPeriod.id).where(
                PayrollPeriod.year == future[0], PayrollPeriod.month == future[1]
            )
        )
    assert rate.id is not None
    assert created is None


# ── 4. Ponowny import: zmiany z NEXUSA zostają ───────────────────────────────


@pytest.mark.asyncio
async def test_reimport_keeps_templates_role_defaults_and_entries_changed_in_nexus() -> (
    None
):
    tag = uuid.uuid4().hex[:8]
    async with AsyncSessionLocal() as db:
        worker, w_id, w_row = await make_person(db, f"{tag}-worker")
        other, o_id, o_row = await make_person(db, f"{tag}-other")
        await db.commit()
    edited_sheet = {
        "id": str(uuid.uuid4()),
        "user_id": w_id,
        "year": 2092,
        "month": 5,
        "status": "draft",
        "submitted_at": None,
        "approved_by": None,
        "approved_at": None,
        "rejection_note": None,
        "pdf_hash": None,
        "created_at": "2092-05-01T08:00:00+00:00",
    }
    trimmed_sheet = {**edited_sheet, "id": str(uuid.uuid4()), "user_id": o_id}

    def entry(sheet: dict, day: str, description: str) -> dict:
        return {
            "id": str(uuid.uuid4()),
            "timesheet_id": sheet["id"],
            "work_date": day,
            "hours": 8,
            "project": None,
            "description": description,
            "source": "manual",
            "is_overtime_override": False,
            "override_reason": None,
            "override_by": None,
        }

    template = {
        "id": str(uuid.uuid4()),
        "user_id": w_id,
        "name": f"Spotkania {tag}",
        "description": "Spotkania zespołu",
        "project": None,
        "sort_order": 1,
    }
    default = {
        "id": str(uuid.uuid4()),
        "applies_to_role": "admin",
        "label": f"Administracja {tag}",
        "project": None,
        "default_description": "Prace administracyjne",
        "is_active": True,
        "sort_order": 0,
        "created_by": None,
    }
    bundle = make_bundle(
        {
            "profiles": [w_row, o_row],
            "timesheets": [edited_sheet, trimmed_sheet],
            "timesheet_entries": [
                entry(edited_sheet, "2092-05-05", "Praca nad wdrożeniem"),
                entry(trimmed_sheet, "2092-05-05", "Analiza"),
                entry(trimmed_sheet, "2092-05-06", "Analiza dalsza"),
            ],
            "timesheet_role_defaults": [default],
            "timesheet_user_templates": [template],
        }
    )
    first = await _apply_bundle("time", bundle)
    assert first["counts"] == {"create": 4}

    # Zmiany w NEXUSIE (osobna transakcja — po zapisie partii).
    async with AsyncSessionLocal() as db:
        mine = await db.scalar(
            select(TimesheetTemplate).where(
                TimesheetTemplate.user_id == worker.id,
                TimesheetTemplate.name == template["name"],
            )
        )
        mine.description = "Spotkania zespołu i klienta"
        role_default = await db.scalar(
            select(TimesheetRoleDefault).where(
                TimesheetRoleDefault.label == default["label"]
            )
        )
        role_default.default_description = "Prace administracyjne i kadrowe"
        sheet = await db.scalar(select(Timesheet).where(Timesheet.user_id == worker.id))
        (only,) = await db.scalars(
            select(TimesheetEntry).where(TimesheetEntry.timesheet_id == sheet.id)
        )
        only.description = "Praca nad wdrożeniem modułu płac"
        trimmed = await time_entries.lock_timesheet(
            db,
            await db.scalar(select(Timesheet.id).where(Timesheet.user_id == other.id)),
        )
        dropped = await db.scalar(
            select(TimesheetEntry).where(
                TimesheetEntry.timesheet_id == trimmed.id,
                TimesheetEntry.work_date == D(2092, 5, 6),
            )
        )
        profile = await db.scalar(
            select(EmployeeProfile).where(EmployeeProfile.user_id == other.id)
        )
        await time_entries.delete_entry(
            db, timesheet=trimmed, subject=profile, entry=dropped
        )
        await db.commit()

    again = await _dry_run("time", bundle)
    assert "update" not in again["counts"], again
    assert again["counts"] == {"conflict": 4}
    assert again["reasons"] == {
        time_import.CHANGED_IN_NEXUS: 2,
        time_import.TEMPLATE_CHANGED_IN_NEXUS: 1,
        time_import.ROLE_DEFAULT_CHANGED_IN_NEXUS: 1,
    }
    await _apply_bundle("time", bundle)
    async with AsyncSessionLocal() as db:
        kept_template = await db.scalar(
            select(TimesheetTemplate.description).where(
                TimesheetTemplate.user_id == worker.id,
                TimesheetTemplate.name == template["name"],
            )
        )
        kept_default = await db.scalar(
            select(TimesheetRoleDefault.default_description).where(
                TimesheetRoleDefault.label == default["label"]
            )
        )
        kept_entry = await db.scalar(
            select(TimesheetEntry.description)
            .join(Timesheet, Timesheet.id == TimesheetEntry.timesheet_id)
            .where(Timesheet.user_id == worker.id)
        )
        trimmed_days = list(
            await db.scalars(
                select(TimesheetEntry.work_date)
                .join(Timesheet, Timesheet.id == TimesheetEntry.timesheet_id)
                .where(Timesheet.user_id == other.id)
            )
        )
        await db.execute(
            delete(TimesheetRoleDefault).where(
                TimesheetRoleDefault.label == default["label"]
            )
        )
        await db.commit()
    assert kept_template == "Spotkania zespołu i klienta"
    assert kept_default == "Prace administracyjne i kadrowe"
    assert kept_entry == "Praca nad wdrożeniem modułu płac"
    assert trimmed_days == [D(2092, 5, 5)]


# ── 5. Ślad rozmowy opieki: wszystkie zamknięte punkty ───────────────────────


@pytest.mark.usefixtures("care_on")
async def test_care_conversation_trace_lists_every_closed_plan_item() -> None:
    client_id = await make_client()
    contract_id_, _ = await make_contract(client_id, started_days_ago=100)
    today = business_today()
    async with AsyncSessionLocal() as db:
        actor = await make_staff(db)
        items = []
        for kind, days_ago in (("day_7", 93), ("day_30", 70), ("day_90", 10)):
            item = CarePlanItem(
                contract_id=contract_id_,
                kind=kind,
                seq=0,
                due_on=today - timedelta(days=days_ago),
                status="open",
            )
            db.add(item)
            items.append(item)
        await db.flush()
        (contract,) = await care_access.live_contracts(db, contract_ids=[contract_id_])
        conversation = await care_records.add_conversation(
            db,
            contract,
            care_records.ConversationInput(occurred_on=today, channel="phone"),
            actor_id=actor.id,
            today=today,
            now=local_now(),
        )
        await db.commit()
        details = await db.scalar(
            select(HrAuditEvent.details).where(
                HrAuditEvent.entity_type == "care_conversation",
                HrAuditEvent.entity_id == str(conversation.id),
            )
        )

    assert details["plan_item_ids"] == sorted(item.id for item in items)
    assert details["plan_item_id"] == items[0].id


# ── 6. Przekierowanie poczty tylko w domenie firmy ───────────────────────────


@pytest.mark.asyncio
async def test_forward_consent_to_a_substitute_outside_the_company_is_422(
    app_client,
    modules_on,  # noqa: F811
    monkeypatch,
) -> None:
    monkeypatch.setattr(settings, "SSO_ALLOWED_DOMAINS", "firma.example")
    async with AsyncSessionLocal() as db:
        boss = await _user(db, "delivery_lead", profile=True)
        stand_in = await _user(db, "recruiter", profile=True)
        worker = await _user(db, "recruiter", profile=True, manager_user_id=boss.id)
        await _pool(db, worker, 2091, "26")
        await db.commit()

    refused = await app_client.post(
        LEAVE + "/requests",
        json=_body(substitute_user_id=stand_in.id, forward_mail_consent=True),
        headers=_headers(worker),
    )
    assert refused.status_code == 422, refused.text
    detail = refused.json()["detail"]
    assert "domenie firmy" in detail
    assert stand_in.email not in detail

    created = await app_client.post(
        LEAVE + "/requests",
        json=_body(substitute_user_id=stand_in.id),
        headers=_headers(worker),
    )
    assert created.status_code == 201, created.text
    consent = await app_client.put(
        f"{LEAVE}/requests/{created.json()['id']}/forward-consent",
        json={"consent": True},
        headers=_headers(worker),
    )
    assert consent.status_code == 422
    assert "domenie firmy" in consent.json()["detail"]

    # Zastępca w domenie firmy — zgoda przechodzi.
    monkeypatch.setattr(settings, "SSO_ALLOWED_DOMAINS", "firma.example, Example.com")
    allowed = await app_client.put(
        f"{LEAVE}/requests/{created.json()['id']}/forward-consent",
        json={"consent": True},
        headers=_headers(worker),
    )
    assert allowed.status_code == 200, allowed.text
    assert allowed.json()["forward_mail_consent"] is True


@pytest.mark.asyncio
async def test_executor_refuses_to_forward_outside_the_company(monkeypatch) -> None:
    monkeypatch.setattr(settings, "SSO_ALLOWED_DOMAINS", "firma.example")
    fake = FakeMailboxOps()
    async with AsyncSessionLocal() as db:
        substitute = await make_staff(db, name="Ola Zastępca")
        user = await make_staff(db)
        leave = await make_leave(
            db,
            user,
            D(2026, 11, 2),
            D(2026, 11, 6),
            substitute=substitute,
            consent=True,
        )
        # Reguła z Compassa tego urlopu — przejęcie nie może jej zostawić.
        fake.add_rule(user.email, f"COMPASS · zastępstwo · {leave.id}")
        await plan(db, leave, "approved", today=D(2026, 10, 20))
        await make_due(db, [user.id])
        await db.commit()
        await executor.run_once(
            db, ops=fake, mode="live", now=at(D(2026, 11, 2), 0, 1), user_ids=[user.id]
        )
        ops = await operations(db, user.id)

    (opening,) = [op for op in ops if op.kind == "forward_rule_open"]
    assert opening.status == "failed"
    assert opening.last_error == "substitute_outside_company"
    assert not [op for op in ops if op.kind == "forward_rule_close"]
    assert fake.rules[user.email.lower()] == {}
    assert not any(
        isinstance(body, dict) and "forwardTo" in body.get("actions", {})
        for _, _, body in fake.writes
    )


# ── 8. Intune: cofnięcie decyzji recepcji ────────────────────────────────────


@pytest.mark.asyncio
async def test_resolution_can_be_undone_and_the_device_returns_to_the_list(
    api,  # noqa: F811
    people,  # noqa: F811
) -> None:
    async with AsyncSessionLocal() as db:
        await db.execute(delete(EquipmentIntuneDevice))
        await db.commit()
    async with modules_state(True):
        t0 = datetime.now(timezone.utc)
        await intune_run(
            [intune_device("dev-u", serial=f"OBCY{uuid.uuid4().hex[:6]}")], t0
        )
        device = (await intune_devices())["dev-u"]
        headers = intune_headers(people["reception"])
        url = f"/api/equipment/intune/devices/{device.id}/resolution"

        nothing = await api.delete(url, headers=headers)
        assert nothing.status_code == 409
        missing = await api.delete(
            "/api/equipment/intune/devices/999999/resolution", headers=headers
        )
        assert missing.status_code == 404
        denied = await api.delete(url, headers=intune_headers(people["recruiter"]))
        assert denied.status_code == 403

        done = await api.post(
            f"/api/equipment/intune/devices/{device.id}/resolve",
            json={"resolution": "pominiete", "note": "Sprzęt testowy"},
            headers=headers,
        )
        assert done.status_code == 200
        report = await _intune_report()
        assert [row["device"]["id"] for row in report["resolved"]] == [device.id]
        assert report["resolved"][0]["device"]["resolution_note"] == "Sprzęt testowy"

        undone = await api.delete(url, headers=headers)
        assert undone.status_code == 200, undone.text
        body = undone.json()
        assert body["resolution"] is None and body["resolution_note"] is None
        report = await _intune_report()
        assert report["resolved"] == []
        assert report["counts"]["wyjasnione"] == 0
        kinds = {row["key"]: row["kind"] for row in report["rows"]}
        assert kinds[f"device:{device.id}"] == "brak_w_ewidencji"
        async with AsyncSessionLocal() as db:
            trace = await db.scalar(
                select(HrAuditEvent.details).where(
                    HrAuditEvent.entity_type == "equipment_intune_device",
                    HrAuditEvent.entity_id == str(device.id),
                    HrAuditEvent.action == "intune_resolution_undone",
                )
            )
        assert trace == {"previous": "pominiete"}


async def _intune_report() -> dict[str, Any]:
    async with AsyncSessionLocal() as db:
        return await intune.discrepancies(db)
