"""Poprawki po przeglądzie backendu 16.10.2026 — Microsoft 365, opieka, administracja@.

* D17 — wcześniejszy urlop B nadpisał autoodpowiedź późniejszego A; anulowanie
  B oddaje autoodpowiedź A, a uzgadnianie nie bierze naszego wyłączenia za
  „osoba sama wyłączyła”,
* D19 — operacje ``simulated`` po przejściu na ``live`` są w uzgadnianiu
  niewykonane (autoodpowiedź, przekierowanie, wydarzenie w kalendarzu),
* E20 — nieaktywne ogniwo łańcucha opiekuna przepuszcza do następnego,
* E21 — follow-up z dawnym terminem (import z Compassa) nie dzwoni,
* E22 — rozmowa zamyka wszystkie zaległe punkty planu,
* E23 — czytnik administracja@ bierze token rejestracji HR,
* E24 — trwale zepsuta wiadomość nie blokuje nowszych,
* E25 — imię i nazwisko konsultanta w opiece i dla ATLASA.

Dane fikcyjne (repo jest publiczne).
"""

from __future__ import annotations

import uuid
from datetime import date, timedelta
from typing import Any, Optional

import pytest
from sqlalchemy import select, update

from app.core.database import AsyncSessionLocal
from app.core.scheduling import business_today, local_now
from app.models.candidate import Candidate
from app.models.contract import Contract
from app.models.contract_care import (
    CLIENTS_CARE,
    CONTRACTS_CARE,
    CareConversation,
    CarePlanItem,
    TechCard,
)
from app.models.hr_leave import HrM365Operation
from app.models.job import Job, JobStatus
from app.models.notification import Notification, NotificationType
from app.models.admin_case import AdminMailIngestState
from app.models.user import User, UserRole
from app.services.admin_cases import mail_ingest
from app.services.care import access as care_access
from app.services.care import plan as care_plan
from app.services.care import reminders, signals
from app.services.hr.m365 import executor, forward_rules, oof_state, reconcile
from tests.hr.fakes import FakeMailboxOps
from tests.hr.m365_helpers import (
    at,
    make_due,
    make_leave,
    make_user as make_staff,
    of_kind,
    operations,
    plan,
    reset_reconcile_runs,
)
from tests.test_admin_cases_mail_ingest import (  # noqa: F401  (fixture'y skrzynki)
    FakeMailbox,
    _cases_for,
    _run,
    cases_on,
    mailbox_on,
)
from tests.test_care_api import (  # noqa: F401  (fixture'y modułów)
    care_on,
    make_client,
    make_contract,
    make_user,
)

D = date


# ── D17: nakładające się urlopy i autoodpowiedź ──────────────────────────────


async def test_cancelling_earlier_leave_gives_the_oof_back_to_the_later_one() -> None:
    fake = FakeMailboxOps()
    async with AsyncSessionLocal() as db:
        user = await make_staff(db)
        later = await make_leave(db, user, D(2026, 11, 16), D(2026, 11, 20))
        await plan(db, later, "approved", today=D(2026, 10, 20))
        await make_due(db, [user.id])
        await db.commit()
        await executor.run_once(
            db, ops=fake, mode="live", now=at(D(2026, 10, 20)), user_ids=[user.id]
        )
        current = await fake.get_auto_replies(user.email)
        assert oof_state.matches_leave(current, later.start_date, later.end_date)

        # Wcześniejszy urlop ma pierwszeństwo i nadpisuje harmonogram.
        earlier = await make_leave(db, user, D(2026, 11, 2), D(2026, 11, 6))
        await plan(db, earlier, "approved", today=D(2026, 10, 21))
        await make_due(db, [user.id])
        await db.commit()
        await executor.run_once(
            db, ops=fake, mode="live", now=at(D(2026, 10, 21)), user_ids=[user.id]
        )
        current = await fake.get_auto_replies(user.email)
        assert oof_state.matches_leave(current, earlier.start_date, earlier.end_date)

        earlier.status = "cancelled"
        await plan(db, earlier, "cancelled", today=D(2026, 10, 22))
        await make_due(db, [user.id])
        await db.commit()
        await executor.run_once(
            db, ops=fake, mode="live", now=at(D(2026, 10, 22)), user_ids=[user.id]
        )
        await make_due(db, [user.id])
        await db.commit()
        await executor.run_once(
            db, ops=fake, mode="live", now=at(D(2026, 10, 22), 9, 5), user_ids=[user.id]
        )
        ops = await operations(db, user.id)

    current = await fake.get_auto_replies(user.email)
    assert oof_state.matches_leave(current, later.start_date, later.end_date)
    handover = [
        op
        for op in of_kind(ops, "set_oof")
        if op.leave_request_id == later.id and ":after_clear:" in op.dedupe_key
    ]
    assert [op.status for op in handover] == ["done"]


async def test_reconcile_restores_oof_switched_off_by_our_own_operation() -> None:
    fake = FakeMailboxOps()
    async with AsyncSessionLocal() as db:
        await reset_reconcile_runs(db)
        # (a) A ustawione, B (wcześniejszy) nadpisał A, anulowanie B wyłączyło
        # autoodpowiedź — to nasza operacja, nie decyzja osoby.
        overwritten = await make_staff(db)
        later = await make_leave(db, overwritten, D(2026, 10, 26), D(2026, 10, 30))
        earlier = await make_leave(db, overwritten, D(2026, 10, 19), D(2026, 10, 23))
        await plan(db, later, "approved", today=D(2026, 10, 12))
        await plan(db, earlier, "approved", today=D(2026, 10, 13))
        earlier.status = "cancelled"
        await plan(db, earlier, "cancelled", today=D(2026, 10, 14))
        await db.execute(
            update(HrM365Operation)
            .where(HrM365Operation.user_id == overwritten.id)
            .values(status="done")
        )
        # (b) osoba sama wyłączyła autoodpowiedź A; zdjęcie autoodpowiedzi
        # innego (anulowanego) urlopu zastało skrzynkę wyłączoną i nic nie pisało.
        returned = await make_staff(db)
        own = await make_leave(db, returned, D(2026, 10, 26), D(2026, 10, 30))
        await plan(db, own, "approved", today=D(2026, 10, 12))
        await db.execute(
            update(HrM365Operation)
            .where(HrM365Operation.user_id == returned.id)
            .values(status="done")
        )
        other = await make_leave(
            db, returned, D(2026, 10, 19), D(2026, 10, 20), status="cancelled"
        )
        await plan(db, other, "cancelled", today=D(2026, 10, 14))
        await make_due(db, [returned.id])
        await db.commit()
        fake.set_oof(returned.email, {"status": "disabled"})
        await executor.run_once(
            db, ops=fake, mode="live", now=at(D(2026, 10, 24)), user_ids=[returned.id]
        )
        (clear,) = of_kind(await operations(db, returned.id), "clear_oof")
        assert (clear.status, clear.last_error) == ("skipped", "already_disabled")
        # (c) autoodpowiedź A czekała na ponowienie i weszła PO autoodpowiedzi
        # wcześniejszego urlopu z nowszego wiersza kolejki — ostatnim zapisem
        # było A, więc wyłączenie to decyzja osoby.
        retried = await make_staff(db)
        retried_later = await make_leave(db, retried, D(2026, 10, 26), D(2026, 10, 30))
        retried_earlier = await make_leave(
            db, retried, D(2026, 10, 12), D(2026, 10, 16)
        )
        await plan(db, retried_later, "approved", today=D(2026, 10, 5))
        await plan(db, retried_earlier, "approved", today=D(2026, 10, 6))
        for leave, done_on in ((retried_earlier, 6), (retried_later, 17)):
            await db.execute(
                update(HrM365Operation)
                .where(HrM365Operation.leave_request_id == leave.id)
                .values(status="done", done_at=at(D(2026, 10, done_on)))
            )
        await db.commit()
        fake.set_oof(retried.email, {"status": "disabled"})

        people = [overwritten.id, returned.id, retried.id]
        await reconcile.run_once(
            db, ops=fake, mode="live", now=at(D(2026, 10, 25), 7, 30), user_ids=people
        )
        added = {
            person: [
                op
                for op in await operations(db, person)
                if ":reconcile:" in op.dedupe_key
            ]
            for person in people
        }

    assert [(op.kind, op.leave_request_id) for op in added[overwritten.id]] == [
        ("set_oof", later.id)
    ]
    assert added[returned.id] == []
    assert added[retried.id] == []


# ── D19: symulacja → live ────────────────────────────────────────────────────


async def test_simulated_operations_are_redone_after_switching_to_live() -> None:
    fake = FakeMailboxOps()
    async with AsyncSessionLocal() as db:
        await reset_reconcile_runs(db)
        substitute = await make_staff(db, name="Ola Zastępca")
        user = await make_staff(db)
        running = await make_leave(
            db,
            user,
            D(2026, 10, 19),
            D(2026, 10, 23),
            substitute=substitute,
            consent=True,
        )
        future = await make_leave(db, user, D(2026, 11, 2), D(2026, 11, 6))
        await plan(db, running, "approved", today=D(2026, 10, 15))
        await plan(db, future, "approved", today=D(2026, 10, 15))
        await make_due(db, [user.id])
        await db.commit()
        # Akceptacje na produkcji w trybie symulacji — nic nie wyszło do skrzynki.
        await executor.run_once(
            db, mode="simulate", now=at(D(2026, 10, 19)), user_ids=[user.id]
        )
        simulated = {
            (op.kind, op.leave_request_id)
            for op in await operations(db, user.id)
            if op.status == "simulated"
        }
        assert ("set_oof", running.id) in simulated
        assert ("forward_rule_open", running.id) in simulated
        assert ("calendar_event_upsert", future.id) in simulated

        counts = await reconcile.run_once(
            db,
            ops=fake,
            mode="live",
            now=at(D(2026, 10, 20), 7, 30),
            user_ids=[user.id],
        )
        added = {
            (op.kind, op.leave_request_id)
            for op in await operations(db, user.id)
            if op.status == "pending" and "reconcile" in op.dedupe_key
        }
        assert ("set_oof", running.id) in added
        assert ("forward_rule_open", running.id) in added
        assert ("calendar_event_upsert", running.id) in added
        assert ("calendar_event_upsert", future.id) in added
        assert counts["calendar_enqueued"] == 2

        await make_due(db, [user.id])
        await db.commit()
        await executor.run_once(
            db,
            ops=fake,
            mode="live",
            now=at(D(2026, 10, 20), 7, 35),
            user_ids=[user.id],
        )

    current = await fake.get_auto_replies(user.email)
    assert oof_state.matches_leave(current, running.start_date, running.end_date)
    (rule,) = fake.rules[user.email.lower()].values()
    assert forward_rules.parse_leave_id(rule["displayName"]) == str(running.id)
    transactions = {
        event["transactionId"] for event in fake.events[user.email.lower()].values()
    }
    assert transactions == {f"nexus-leave-{running.id}", f"nexus-leave-{future.id}"}


# ── E20–E22, E25: opieka ─────────────────────────────────────────────────────


async def _deactivate(*users: User) -> None:
    async with AsyncSessionLocal() as db:
        await db.execute(
            update(User)
            .where(User.id.in_([u.id for u in users]))
            .values(is_active=False)
        )
        await db.commit()


async def _set_owners(
    contract_id: int,
    client_id: int,
    *,
    contract_owner: Optional[int],
    client_default: Optional[int],
    job_dl: Optional[int] = None,
) -> None:
    async with AsyncSessionLocal() as db:
        await db.execute(
            update(CONTRACTS_CARE)
            .where(CONTRACTS_CARE.c.id == contract_id)
            .values(care_owner_user_id=contract_owner)
        )
        await db.execute(
            update(CLIENTS_CARE)
            .where(CLIENTS_CARE.c.id == client_id)
            .values(default_care_owner_user_id=client_default)
        )
        if job_dl is not None:
            job = Job(
                title="Programista Przykładowy",
                status=JobStatus.published,
                client_id=client_id,
                delivery_lead_id=job_dl,
            )
            db.add(job)
            await db.flush()
            contract = await db.get(Contract, contract_id)
            contract.job_id = job.id
        await db.commit()


@pytest.mark.usefixtures("care_on")
async def test_inactive_owner_links_fall_through_and_the_bell_reaches_someone() -> None:
    head = await make_user(UserRole.delivery_lead)
    gone_owner = await make_user(UserRole.delivery_lead)
    gone_default = await make_user(UserRole.talent_community_manager)
    gone_job_dl = await make_user(UserRole.delivery_lead)
    default_tcm = await make_user(UserRole.talent_community_manager)

    # Cały łańcuch nieaktywny → główny DL klienta.
    client_id = await make_client(dl=head)
    contract_id, _ = await make_contract(client_id, started_days_ago=10)
    await _set_owners(
        contract_id,
        client_id,
        contract_owner=gone_owner.id,
        client_default=gone_default.id,
        job_dl=gone_job_dl.id,
    )
    # Opiekun kontraktu nieaktywny → domyślny opiekun klienta.
    second_client = await make_client(dl=head)
    second_contract, _ = await make_contract(second_client, started_days_ago=10)
    await _set_owners(
        second_contract,
        second_client,
        contract_owner=gone_owner.id,
        client_default=default_tcm.id,
    )
    await _deactivate(gone_owner, gone_default, gone_job_dl)

    today = business_today()
    async with AsyncSessionLocal() as db:
        contracts = await care_access.live_contracts(
            db, contract_ids=[contract_id, second_contract]
        )
        owners = await care_access.effective_owners(db, contracts)
        for contract in contracts:
            await care_plan.ensure_plan(
                db,
                contract.id,
                start=contract.start_date,
                end=contract.end_date,
                today=today,
            )
        result = await reminders.remind(db, contracts, today=today, now=local_now())
        await db.commit()
        sent = (
            await db.execute(
                select(Notification.related_entity_id, Notification.user_id).where(
                    Notification.notification_type == NotificationType.care_contact_due,
                    # Zbiorczy dzwonek niesie id osoby, nie kontraktu — bez typu
                    # cudzy digest z tym samym numerem w bazie shardu liczył się tu.
                    Notification.related_entity_type == "contract",
                    Notification.related_entity_id.in_([contract_id, second_contract]),
                )
            )
        ).all()

    assert owners[contract_id] == care_access.OwnerChoice(head.id, "delivery_lead")
    assert owners[second_contract] == care_access.OwnerChoice(default_tcm.id, "client")
    assert (result["sent"], result["skipped"]) == (2, 0)
    assert set(sent) == {(contract_id, head.id), (second_contract, default_tcm.id)}


@pytest.mark.usefixtures("care_on")
async def test_old_follow_up_from_import_does_not_ring() -> None:
    owner = await make_user(UserRole.talent_community_manager)
    client_id = await make_client()
    imported, _ = await make_contract(client_id, started_days_ago=400)
    recent, _ = await make_contract(client_id, started_days_ago=400)
    today = business_today()
    async with AsyncSessionLocal() as db:
        db.add_all(
            [
                CareConversation(
                    contract_id=imported,
                    occurred_on=today - timedelta(days=220),
                    channel="phone",
                    follow_up_on=today - timedelta(days=200),
                    compass_source_id=f"compass-{uuid.uuid4().hex[:12]}",
                ),
                CareConversation(
                    contract_id=recent,
                    occurred_on=today - timedelta(days=10),
                    channel="phone",
                    follow_up_on=today - timedelta(days=3),
                ),
            ]
        )
        await db.commit()
    for contract_id in (imported, recent):
        await _set_owners(
            contract_id, client_id, contract_owner=owner.id, client_default=None
        )

    async with AsyncSessionLocal() as db:
        contracts = await care_access.live_contracts(
            db, contract_ids=[imported, recent]
        )
        result = await reminders.remind(db, contracts, today=today, now=local_now())
        await db.commit()
        # Zbiorczy dzwonek ma ``related_entity_id`` = id osoby — bez zawężenia
        # do umów i właściciela id konta z innego testu zderzało się z id umowy.
        rung = (
            await db.scalars(
                select(Notification.related_entity_id).where(
                    Notification.notification_type == NotificationType.care_contact_due,
                    # Zbiorczy dzwonek niesie id osoby, nie kontraktu — bez typu
                    # cudzy digest z tym samym numerem w bazie shardu liczył się tu.
                    Notification.related_entity_type == "contract",
                    Notification.user_id == owner.id,
                    Notification.related_entity_id.in_([imported, recent]),
                )
            )
        ).all()

    assert result["due"] == 1
    assert list(rung) == [recent]


async def _plan_item(
    db, contract_id: int, kind: str, seq: int, due_on: date
) -> CarePlanItem:
    item = CarePlanItem(
        contract_id=contract_id, kind=kind, seq=seq, due_on=due_on, status="open"
    )
    db.add(item)
    await db.flush()
    return item


@pytest.mark.usefixtures("care_on")
async def test_conversation_closes_every_overdue_plan_item() -> None:
    client_id = await make_client()
    contract_id, _ = await make_contract(
        client_id, started_days_ago=100, end_in_days=40
    )
    today = business_today()
    end = today + timedelta(days=40)
    async with AsyncSessionLocal() as db:
        day_7 = await _plan_item(db, contract_id, "day_7", 0, today - timedelta(93))
        day_30 = await _plan_item(db, contract_id, "day_30", 0, today - timedelta(70))
        day_90 = await _plan_item(db, contract_id, "day_90", 0, today - timedelta(10))
        pre_end = await _plan_item(
            db, contract_id, "pre_end", end.toordinal(), end - timedelta(days=30)
        )
        conversation = CareConversation(
            contract_id=contract_id, occurred_on=today, channel="phone"
        )
        db.add(conversation)
        await db.flush()
        closed = await care_plan.close_with_conversation(
            db, conversation, actor_id=None, now=local_now()
        )
        await db.commit()
        statuses = dict(
            (
                await db.execute(
                    select(CarePlanItem.id, CarePlanItem.status).where(
                        CarePlanItem.contract_id == contract_id
                    )
                )
            ).all()
        )
        done_by = set(
            (
                await db.scalars(
                    select(CarePlanItem.done_conversation_id).where(
                        CarePlanItem.contract_id == contract_id,
                        CarePlanItem.status == "done",
                    )
                )
            ).all()
        )

    assert closed is not None and closed.id == day_7.id
    assert statuses == {
        day_7.id: "done",
        day_30.id: "done",
        day_90.id: "done",
        pre_end.id: "open",  # „30 dni przed końcem” jest dopiero za 10 dni
    }
    assert done_by == {conversation.id}


@pytest.mark.usefixtures("care_on")
async def test_early_conversation_covers_a_regular_item_but_not_the_pre_end() -> None:
    client_id = await make_client()
    regular, _ = await make_contract(client_id, started_days_ago=20)
    ending, _ = await make_contract(client_id, started_days_ago=200, end_in_days=40)
    today = business_today()
    end = today + timedelta(days=40)
    async with AsyncSessionLocal() as db:
        day_30 = await _plan_item(db, regular, "day_30", 0, today + timedelta(10))
        pre_end = await _plan_item(
            db, ending, "pre_end", end.toordinal(), end - timedelta(days=30)
        )
        results = []
        for contract_id in (regular, ending):
            conversation = CareConversation(
                contract_id=contract_id, occurred_on=today, channel="phone"
            )
            db.add(conversation)
            await db.flush()
            results.append(
                await care_plan.close_with_conversation(
                    db, conversation, actor_id=None, now=local_now()
                )
            )
        await db.commit()
        await db.refresh(day_30)
        await db.refresh(pre_end)

    assert results[0] is not None and results[0].id == day_30.id
    assert results[1] is None
    assert (day_30.status, pre_end.status) == ("done", "open")


@pytest.mark.usefixtures("care_on")
async def test_consultant_full_name_in_care_and_for_atlas() -> None:
    client_id = await make_client()
    contract_id, candidate_id = await make_contract(client_id)
    async with AsyncSessionLocal() as db:
        candidate = await db.get(Candidate, candidate_id)
        full = f"{candidate.name} {candidate.lastname}"
        db.add(
            TechCard(
                contract_id=contract_id,
                client_id=client_id,
                interview_on=business_today(),
                status="ok",
                is_draft=False,
                finalized_at=local_now(),
                hiring=True,
            )
        )
        await db.commit()
        (contract,) = await care_access.live_contracts(db, contract_ids=[contract_id])
        exported = [
            row
            for row in await signals.export(db, since=None)
            if row["client_id"] == client_id
        ]

    assert contract.candidate_name == full
    assert contract.label.startswith(full)
    assert [row["consultant_name"] for row in exported] == [full]


# ── E23–E24: czytnik administracja@ ──────────────────────────────────────────


class _RecordingGraphClient:
    """Zastępuje ``AppGraphClient``: zapamiętuje rejestrację, skrzynka pusta."""

    providers: list[Any] = []

    def __init__(self, token_provider=None) -> None:
        type(self).providers.append(token_provider)

    async def __aenter__(self) -> "_RecordingGraphClient":
        return self

    async def __aexit__(self, *exc_info) -> None:
        return None

    async def paginate(self, path: str, params: Optional[dict] = None):
        yield {"value": []}

    async def get(self, path: str, params: Optional[dict] = None) -> dict:
        return {"value": []}


@pytest.mark.usefixtures("mailbox_on")
async def test_admin_mailbox_reader_uses_the_hr_registration(monkeypatch) -> None:
    from app.services.hr.m365.auth import acquire_hr_token
    from app.services.m365 import app_graph_client

    _RecordingGraphClient.providers = []
    monkeypatch.setattr(app_graph_client, "AppGraphClient", _RecordingGraphClient)
    async with AsyncSessionLocal() as db:
        result = await mail_ingest.run_once(db)

    assert result["status"] == "ok", result
    assert _RecordingGraphClient.providers == [acquire_hr_token]


@pytest.mark.usefixtures("mailbox_on")
async def test_permanently_broken_message_does_not_block_newer_ones(
    monkeypatch,
) -> None:
    monkeypatch.setattr(mail_ingest, "MAX_MESSAGES_PER_RUN", 3)
    fake = FakeMailbox()
    broken = fake.add(
        subject="Umowa z uszkodzonym załącznikiem",
        hours_ago=12,
        attachments=[{"name": "umowa.pdf", "contentType": "application/pdf"}],
    )
    fake.broken.add(broken["id"])
    # Co 2 h — nakładka odczytu (2 h) nie mieści więcej wiadomości niż limit 3.
    newer = [fake.add(subject=f"Pytanie {i}", hours_ago=9 - 2 * i) for i in range(4)]

    results = [await _run(fake) for _ in range(mail_ingest.MAX_MESSAGE_ATTEMPTS + 2)]

    assert set(await _cases_for(fake)) == {msg["id"] for msg in newer}
    assert [
        r.get("failed", 0) for r in results[: mail_ingest.MAX_MESSAGE_ATTEMPTS]
    ] == [1] * mail_ingest.MAX_MESSAGE_ATTEMPTS
    given_up = results[mail_ingest.MAX_MESSAGE_ATTEMPTS - 1]
    assert (given_up["status"], given_up["abandoned"]) == ("partial", 1)
    # Porzuconej wiadomości nikt już nie próbuje — kolejne przebiegi są czyste.
    assert results[-1]["status"] == "ok"
    async with AsyncSessionLocal() as db:
        state = await db.get(AdminMailIngestState, 1)
    stored = f"{state.stats} {state.last_error}"
    assert broken["id"] not in stored
    assert "uszkodzonym" not in stored
