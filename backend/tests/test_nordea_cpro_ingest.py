"""Powiadomienia CPro Nordei na wsparcie@: czytnik → propozycja albo zadanie Finansów.

Dane fikcyjne (repo publiczne). Ścieżka jak na produkcji: mail CPro przekierowany
na skrzynkę, ``mail_ingest.run_once``, propozycja „Klient kończy” z numerem CoA
dopasowanym do linii zamówienia, potwierdzenie otwiera sprawę wyjścia z datą,
a zmiana nabywcy staje się sprawą Rozliczeń z wartością „od dnia”.
"""

from __future__ import annotations

import random
import uuid
from datetime import date, datetime, timedelta
from typing import Any

import pytest
import pytest_asyncio
from sqlalchemy import select

from app.core.database import AsyncSessionLocal
from app.core.scheduling import business_date, business_today
from app.models.admin_case import AdminCase
from app.models.candidate import Candidate
from app.models.client import Client
from app.models.client_order import ClientOrder, ClientOrderStatus
from app.models.contract import Contract, ContractStatus
from app.models.equipment import EquipmentAssignment, EquipmentItem, EquipmentModel
from app.models.notice_mail import NoticeMailProposal
from app.models.user import User, UserRole
from app.services.admin_cases import hooks, notice_view
from app.services.admin_cases import rules as case_rules
from app.services.back_office import steps
from tests.test_admin_cases_mail_ingest import (  # noqa: F401 — fikstury
    FakeMailbox,
    _run,
    cases_on,
    mailbox_on,
)
from tests.test_notice_mail_ingest import _body, _case_of, _proposals

CPRO = "noreply@onevms.se"


@pytest_asyncio.fixture
async def nordea_line() -> dict[str, Any]:
    tag = uuid.uuid4().hex[:8]
    # Sześć cyfr jak numer CoA; losowe, żeby nie trafić w cudze linie zamówień.
    number = str(random.randint(700000, 799999))
    today = business_today()
    async with AsyncSessionLocal() as db:
        client = Client(name=f"Bank Północny {tag}")
        candidate = Candidate(name="Jan", lastname=f"Fikcyjny{tag}")
        db.add_all([client, candidate])
        await db.flush()
        contract = Contract(
            candidate_id=candidate.id,
            client_id=client.id,
            start_date=today - timedelta(days=300),
            status=ContractStatus.active,
        )
        user = User(
            email=f"bo-{tag}@example.com",
            name="Obsługa Spraw",
            role=UserRole.admin,
            is_active=True,
        )
        db.add_all([contract, user])
        await db.flush()
        order_end = today + timedelta(days=40)
        order = ClientOrder(
            client_id=client.id,
            contract_id=contract.id,
            title=number,
            status=ClientOrderStatus.active,
            start_date=today - timedelta(days=300),
            end_date=order_end,
        )
        model = EquipmentModel(category="laptop", name=f"Monitor Fikcyjny {tag}")
        db.add_all([order, model])
        await db.flush()
        item = EquipmentItem(
            model_id=model.id, serial_number=f"S{tag}", status="wydany"
        )
        db.add(item)
        await db.flush()
        db.add(EquipmentAssignment(item_id=item.id, contract_id=contract.id))
        await db.commit()
        return {
            "number": number,
            "contract_id": contract.id,
            "order_id": order.id,
            "order_end": order_end,
            "user_id": user.id,
            "model_name": model.name,
        }


def _received_day(msg: dict[str, Any]) -> date:
    return business_date(
        datetime.fromisoformat(msg["receivedDateTime"].replace("Z", "+00:00"))
    )


async def _confirm(proposal_id: int, user_id: int, applied: dict[str, Any]) -> None:
    async with AsyncSessionLocal() as db:
        await notice_view.decide(
            db,
            await db.get(NoticeMailProposal, proposal_id),
            actor=await db.get(User, user_id),
            decision="confirmed",
            contract_id=None,
            remember_sender=False,
            applied=applied,
            note=None,
        )
        await db.commit()


async def _exit_case(contract_id: int) -> AdminCase | None:
    async with AsyncSessionLocal() as db:
        return await db.scalar(
            select(AdminCase).where(
                AdminCase.source_key == hooks.contract_end_source_key(contract_id)
            )
        )


@pytest.mark.asyncio
@pytest.mark.usefixtures("mailbox_on")
async def test_not_extended_opens_exit_case_with_order_end_after_confirm(
    nordea_line,
) -> None:
    number = nordea_line["number"]
    fake = FakeMailbox()
    msg = fake.add(
        subject=f"Contract {number} will not be extended", hours_ago=1, sender=CPRO
    )
    _body(
        msg,
        f"Contract {number} will not be extended\nwill not be prolonged\n"
        f"CoA: PL - Tester ({number})\nShow CoA - PL - Tester ({number})\n"
        "This email is sent from CPro, Nordea's consultant procurement system.",
    )
    await _run(fake)
    case_id = await _case_of(msg["id"])
    [proposal] = await _proposals(case_id)
    assert proposal.kind == "client_termination"
    assert proposal.cpro_number == number
    assert proposal.contract_id == nordea_line["contract_id"]
    assert proposal.order_id == nordea_line["order_id"]
    assert proposal.match["cpro_event"] == "not_extended"
    # Sam mail CPro nie ma daty: koniec to obecny koniec zamówienia („Zostaw …”).
    assert proposal.client_end_date is None
    # Sprawa wyjścia powstaje dopiero po potwierdzeniu człowieka.
    assert await _exit_case(nordea_line["contract_id"]) is None

    end = nordea_line["order_end"]
    await _confirm(
        proposal.id,
        nordea_line["user_id"],
        {"choice": "keep_order", "order_end_date": end.isoformat()},
    )
    exit_case = await _exit_case(nordea_line["contract_id"])
    assert exit_case is not None
    assert exit_case.due_on == end
    assert "Nordea nie przedłuża kontraktu w CPro" in (exit_case.description or "")
    texts = [item["text"] for item in exit_case.checklist]
    assert any(t.startswith(case_rules.END_BENEFITS_PREFIX) for t in texts)
    assert (
        f"{case_rules.END_EQUIPMENT_REGISTER_PREFIX}{nordea_line['model_name']}"
        in texts
    )
    [decided] = await _proposals(case_id)
    assert decided.decision["exit_case_id"] == exit_case.id
    assert decided.decision["exit_last_day"] == end.isoformat()

    # Umowa konsultanta trwa (bez daty końca), ale sprawa wyjścia zostaje…
    async with AsyncSessionLocal() as db:
        contract = await db.get(Contract, nordea_line["contract_id"])
        contract.client_order_end_date = end
        await db.flush()  # sesja bez autoflush
        await steps.close_extended_exit_cases(db, today=business_today())
        await db.commit()
    assert (await _exit_case(nordea_line["contract_id"])).status == "new"
    # …dopóki zamówienie nie zostanie przedłużone dalej.
    async with AsyncSessionLocal() as db:
        contract = await db.get(Contract, nordea_line["contract_id"])
        contract.client_order_end_date = end + timedelta(days=90)
        await db.flush()
        await steps.close_extended_exit_cases(db, today=business_today())
        await db.commit()
    assert (await _exit_case(nordea_line["contract_id"])).status == "closed"


@pytest.mark.asyncio
@pytest.mark.usefixtures("mailbox_on")
async def test_terminated_with_date_from_cpro_table(nordea_line) -> None:
    number = nordea_line["number"]
    end = business_today() + timedelta(days=20)
    fake = FakeMailbox()
    msg = fake.add(
        subject=f"FW: Contract terminated: {number} - Windows expert developer",
        hours_ago=1,
        sender="dl.nordei@example.com",
    )
    _body(
        msg,
        "DW\n\nFrom: NOREPLY CPro <noreply@onevms.se>\n"
        f"Subject: Contract terminated: {number} - Windows expert developer\n"
        f"The contract has been terminated for {number} - Windows expert developer\n"
        f"CoA\n{number} Windows expert developer\nConsultant\nJan Fikcyjny\n"
        f"Termination reason\nNo more budget\nNew end date\n{end.isoformat()}\n",
    )
    await _run(fake)
    [proposal] = await _proposals(await _case_of(msg["id"]))
    assert proposal.match["cpro_event"] == "terminated"
    assert proposal.client_end_date == end
    await _confirm(
        proposal.id,
        nordea_line["user_id"],
        {"choice": "shorten_order", "order_end_date": end.isoformat()},
    )
    exit_case = await _exit_case(nordea_line["contract_id"])
    assert exit_case is not None and exit_case.due_on == end


@pytest.mark.asyncio
@pytest.mark.usefixtures("mailbox_on")
async def test_invoice_address_change_is_a_finance_task_not_a_termination(
    nordea_line,
) -> None:
    number = nordea_line["number"]
    fake = FakeMailbox()
    msg = fake.add(
        subject=f"Important changes made to contract {number}", hours_ago=1, sender=CPRO
    )
    _body(
        msg,
        "Please update your invoice reference details with the information provided below\n\n"
        "Invoice address was updated from: F218 Nordea Bank Abp S.A., "
        "to: F206 Nordea Bank Abp Finland\n\n"
        f"Show CoA - PL - IT Developer ({number})\n",
    )
    await _run(fake)
    case_id = await _case_of(msg["id"])
    assert await _proposals(case_id) == []
    async with AsyncSessionLocal() as db:
        case = await db.get(AdminCase, case_id)
    today = business_today()
    assert case.title == (
        f"Nordea CPro: zmiana nabywcy od {_received_day(msg):%d.%m.%Y} · CoA {number}"
    )
    assert case.area == "settlements"
    assert case.priority == "P1"
    assert f"kontrakt #{nordea_line['contract_id']}" in case.description
    assert "F206 Nordea Bank Abp Finland" in case.description
    assert case.checklist[0]["text"].startswith("Finanse: nabywca od ")
    # Automat nie przypina kontraktu do sprawy z maila.
    assert case.contract_id is None
    assert case.due_on is not None and case.due_on >= today


@pytest.mark.asyncio
@pytest.mark.usefixtures("mailbox_on")
async def test_cpro_recruitment_mails_do_not_become_cases() -> None:
    # Reguła przekierowuje wszystko z noreply@onevms.se; rekrutację prowadzi pętla
    # ``cpro_mail`` ze skrzynek DL-i, więc tu zostałaby tylko sprawą-szumem.
    fake = FakeMailbox()
    closed = fake.add(
        subject="PL - Tester was closed (91234)", hours_ago=2, sender=CPRO
    )
    _body(closed, "The request has been closed. Reason: demand change")
    rejected = fake.add(
        subject="Rejected: Jan Fikcyjny - Tester (91235)", hours_ago=1, sender=CPRO
    )
    _body(rejected, "Rejected (91235) Not a fit Offer: …")
    result = await _run(fake)
    assert result["status"] == "ok"
    assert await _case_of(closed["id"]) is None
    assert await _case_of(rejected["id"]) is None
