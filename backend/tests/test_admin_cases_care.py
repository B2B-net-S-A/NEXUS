"""Sprawy w opiece (decyzja 7, 22.10.2026) — z bazą.

* mail od uwierzytelnionego konsultanta (``Authentication-Results``)
  z jednym aktywnym kontraktem wiąże sprawę sam; bez uwierzytelnienia albo z dwoma —
  tylko propozycje; mail z firmy klienta z nazwiskiem konsultanta — propozycja,
* karta na tablicy niesie opiekuna kontraktu, chip „Moi podopieczni”,
* szczegół: sekcja „Konsultant” bez kwot, ślad przypięcia kontraktu,
* ``GET /api/care/contracts/{id}/cases``: treść tylko ``may_read``, negocjacje
  nigdy, wyłączone „Sprawy” = pusta lista, cudzy klient DL — 403,
* „Zakończ współpracę” zakłada sprawę „Koniec współpracy” u opiekuna,
  „Cofnij zakończenie” ją zamyka, unieważnienie jej nie zakłada,
* import z Compassa wiąże pewny kontrakt i nie nadpisuje wyboru z NEXUSA.

Baza testowa nie jest czyszczona między testami — asercje dotyczą wyłącznie
danych założonych w teście. Dane fikcyjne (repo jest publiczne).
"""

from __future__ import annotations

import json
import uuid
from datetime import date, timedelta

import pytest
import pytest_asyncio
from sqlalchemy import func, select, text, update

import app.models  # noqa: F401  (rejestracja wszystkich mapperów)
from app.core.database import AsyncSessionLocal
from app.core.scheduling import business_today
from app.models.admin_case import AdminCase, AdminCaseMessage
from app.models.candidate import Candidate
from app.models.client import Client
from app.models.contact import Contact
from app.models.contract import Contract, ContractStatus
from app.models.equipment import ClientOnboardingPack, ClientOnboardingPackItem
from app.models.hr_ops import HrAuditEvent
from app.models.section_permission import UserActionOverride
from app.models.user import UserRole
from app.services.admin_cases import hooks, mail_ingest, queries, rules
from app.services.admin_cases.contract_links import REASON_CLIENT_MAIL, REASON_SENDER
from app.services.hr import contract_hooks
from app.services.hr_foundation_schema import HR_MODULE_KEYS
from tests.test_admin_cases_mail_ingest import FakeMailbox
from tests.test_care_api import (
    _previous_modules,
    headers,
    make_client,
    make_contract,
    make_user,
    set_modules,
)
from tests.test_hr_compass_import_cases import CATEGORIES, _meta, _ticket
from tests.test_hr_compass_import_leave import make_bundle, make_person, run_import

pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture
async def care_on():
    previous = await _previous_modules()
    await set_modules({key: True for key in HR_MODULE_KEYS})
    yield
    await set_modules(previous or {key: False for key in HR_MODULE_KEYS})


@pytest.fixture
def mailbox(monkeypatch, care_on) -> str:
    upn = f"administracja-{uuid.uuid4().hex[:8]}@example.com"
    monkeypatch.setenv(mail_ingest.MAILBOX_ENV, upn)
    monkeypatch.setenv(mail_ingest.ENABLED_ENV, "true")
    return upn


async def _ingest(fake: FakeMailbox) -> dict:
    async with AsyncSessionLocal() as db:
        return await mail_ingest.run_once(db, graph=fake)


async def _case_of(message_id: str) -> AdminCase:
    async with AsyncSessionLocal() as db:
        case_id = await db.scalar(
            select(AdminCaseMessage.case_id).where(
                AdminCaseMessage.graph_message_id == message_id
            )
        )
        return await db.get(AdminCase, case_id)


async def _candidate(candidate_id: int) -> Candidate:
    async with AsyncSessionLocal() as db:
        return await db.get(Candidate, candidate_id)


async def _second_contract(candidate_id: int, client_id: int) -> int:
    async with AsyncSessionLocal() as db:
        contract = Contract(
            candidate_id=candidate_id,
            client_id=client_id,
            status=ContractStatus.active,
            start_date=business_today() - timedelta(days=5),
        )
        db.add(contract)
        await db.commit()
        return contract.id


async def _grant_cases(user_id: int) -> None:
    async with AsyncSessionLocal() as db:
        db.add(UserActionOverride(user_id=user_id, action="cases", access="manage"))
        await db.commit()


# ── Czytnik poczty ───────────────────────────────────────────────────────────


def _authenticated(email: str) -> list[dict[str, str]]:
    domain = email.rsplit("@", 1)[1]
    return [
        {
            "name": "Authentication-Results",
            "value": f"spf=pass smtp.mailfrom={domain}; dkim=pass header.d={domain};"
            f" dmarc=pass action=none header.from={domain}",
        }
    ]


async def test_mail_from_consultant_links_the_only_live_contract(mailbox) -> None:
    dl = await make_user(UserRole.delivery_lead)
    client_id = await make_client(dl=dl)
    contract_id, candidate_id = await make_contract(client_id)
    candidate = await _candidate(candidate_id)

    fake = FakeMailbox()
    msg = fake.add(
        subject="Pytanie o urlop",
        hours_ago=1,
        sender=candidate.email,
        headers=_authenticated(candidate.email),
    )
    assert (await _ingest(fake))["created"] == 1

    case = await _case_of(msg["id"])
    assert case.contract_id == contract_id
    async with AsyncSessionLocal() as db:
        trace = await db.scalar(
            select(HrAuditEvent).where(
                HrAuditEvent.entity_type == "admin_case",
                HrAuditEvent.entity_id == str(case.id),
                HrAuditEvent.action == "case_linked",
            )
        )
        events = await queries.contract_case_events(db, contract_id, dl)
    assert trace.details == {"contract_id": contract_id, "source": "mail_sender"}
    assert {e["kind"] for e in events} >= {"case_opened", "case_linked"}


async def test_unauthenticated_sender_is_only_a_suggestion(app_client, mailbox) -> None:
    """Podrobiony ``From`` bez ``dmarc=pass`` nie wiąże sprawy z kontraktem."""

    admin = await make_user(UserRole.admin)
    client_id = await make_client()
    contract_id, candidate_id = await make_contract(client_id)
    candidate = await _candidate(candidate_id)
    domain = candidate.email.rsplit("@", 1)[1]

    fake = FakeMailbox()
    msg = fake.add(
        subject="Zmiana konta do przelewu",
        hours_ago=1,
        sender=candidate.email,
        headers=[
            {
                "name": "Authentication-Results",
                "value": f"spf=fail smtp.mailfrom={domain}; dmarc=fail header.from={domain}",
            }
        ],
    )
    await _ingest(fake)
    case = await _case_of(msg["id"])
    assert case.contract_id is None

    detail = await app_client.get(f"/api/cases/{case.id}", headers=headers(admin))
    suggestions = detail.json()["link_suggestions"]
    assert [s["contract_id"] for s in suggestions] == [contract_id]
    assert suggestions[0]["reason"] == REASON_SENDER


async def test_two_live_contracts_are_only_suggestions(app_client, mailbox) -> None:
    admin = await make_user(UserRole.admin)
    client_id = await make_client()
    first, candidate_id = await make_contract(client_id)
    second = await _second_contract(candidate_id, client_id)
    candidate = await _candidate(candidate_id)

    fake = FakeMailbox()
    msg = fake.add(subject="Faktura", hours_ago=1, sender=candidate.email)
    await _ingest(fake)
    case = await _case_of(msg["id"])
    assert case.contract_id is None

    detail = await app_client.get(f"/api/cases/{case.id}", headers=headers(admin))
    assert detail.status_code == 200, detail.text
    suggestions = detail.json()["link_suggestions"]
    assert {s["contract_id"] for s in suggestions} == {first, second}
    assert {s["reason"] for s in suggestions} == {REASON_SENDER}
    assert detail.json()["consultant"] is None


async def test_client_mail_naming_consultant_is_a_suggestion_never_a_link(
    app_client, mailbox
) -> None:
    admin = await make_user(UserRole.admin)
    client_id = await make_client()
    contract_id, candidate_id = await make_contract(client_id)
    candidate = await _candidate(candidate_id)
    sender = f"menedzer-{uuid.uuid4().hex[:8]}@example.com"
    async with AsyncSessionLocal() as db:
        db.add(Contact(client_id=client_id, name="Menedżer Przykładowy", email=sender))
        await db.commit()

    fake = FakeMailbox()
    msg = fake.add(
        subject=f"Nieobecność: {candidate.lastname} {candidate.name}",
        hours_ago=1,
        sender=sender,
    )
    await _ingest(fake)
    case = await _case_of(msg["id"])
    assert case.contract_id is None

    body = (
        await app_client.get(f"/api/cases/{case.id}", headers=headers(admin))
    ).json()
    first = body["link_suggestions"][0]
    assert first["contract_id"] == contract_id
    assert first["reason"] == REASON_CLIENT_MAIL.format(
        name=f"{candidate.name} {candidate.lastname}"
    )


# ── Tablica i szczegół ───────────────────────────────────────────────────────


async def _case(app_client, actor, **payload) -> dict:
    body = {"title": "Pytanie o fakturę", "area": "administration", **payload}
    response = await app_client.post("/api/cases", json=body, headers=headers(actor))
    assert response.status_code == 201, response.text
    return response.json()


async def test_card_carries_care_owner_and_mine_care_chip(app_client, care_on) -> None:
    admin = await make_user(UserRole.admin)
    dl = await make_user(UserRole.delivery_lead)
    await _grant_cases(dl.id)
    client_id = await make_client(dl=dl)  # opiekun z łańcucha = DL klienta
    contract_id, candidate_id = await make_contract(client_id)
    created = await _case(app_client, admin, contract_id=contract_id)
    other = await _case(app_client, admin)

    mine = await app_client.get(
        "/api/cases", params={"mine_care": "true"}, headers=headers(dl)
    )
    assert mine.status_code == 200, mine.text
    ids = {item["id"] for item in mine.json()["items"]}
    assert created["id"] in ids and other["id"] not in ids
    assert mine.json()["counts"]["mine_care"] >= 1
    card = next(i for i in mine.json()["items"] if i["id"] == created["id"])
    assert card["contract"]["care_owner_user_id"] == dl.id
    assert card["contract"]["care_owner_name"] == dl.name
    assert card["contract"]["candidate_id"] == candidate_id
    assert "health" in card["contract"]

    as_admin = await app_client.get(
        "/api/cases", params={"mine_care": "true"}, headers=headers(admin)
    )
    assert created["id"] not in {item["id"] for item in as_admin.json()["items"]}


async def test_detail_consultant_section_without_amounts(app_client, care_on) -> None:
    admin = await make_user(UserRole.admin)
    dl = await make_user(UserRole.delivery_lead)
    client_id = await make_client(dl=dl)
    contract_id, _ = await make_contract(client_id, end_in_days=40)
    first = await _case(app_client, admin, contract_id=contract_id)
    await _case(app_client, admin, contract_id=contract_id, title="Druga sprawa")

    body = (
        await app_client.get(f"/api/cases/{first['id']}", headers=headers(admin))
    ).json()
    consultant = body["consultant"]
    assert consultant["contract_id"] == contract_id
    assert consultant["owner_user_id"] == dl.id
    assert consultant["owner_name"] == dl.name
    assert consultant["cadence_label"] == "co 2 tygodnie"  # pierwsze 90 dni
    assert (
        consultant["order_end_on"]
        == (business_today() + timedelta(days=40)).isoformat()
    )
    assert consultant["other_open_cases"] == 1
    assert consultant["last_conversation"] is None
    assert body["link_suggestions"] == []
    dumped = json.dumps(body)
    assert "100.0" not in dumped and "130.0" not in dumped  # stawki kontraktu


async def test_out_of_portfolio_contract_hides_care_data(app_client, care_on) -> None:
    """DL z „Sprawami” widzi sprawę obcego klienta bez opiekuna i zdrowia."""

    admin = await make_user(UserRole.admin)
    owner_dl = await make_user(UserRole.delivery_lead)
    handler_dl = await make_user(UserRole.delivery_lead)
    await _grant_cases(handler_dl.id)
    client_id = await make_client(dl=owner_dl)
    await make_client(dl=handler_dl)
    contract_id, _ = await make_contract(client_id)
    created = await _case(app_client, admin, contract_id=contract_id)

    board = await app_client.get("/api/cases", headers=headers(handler_dl))
    assert board.status_code == 200, board.text
    card = next(i for i in board.json()["items"] if i["id"] == created["id"])
    assert card["contract"]["candidate_name"]
    assert card["contract"]["care_owner_user_id"] is None
    assert card["contract"]["care_owner_name"] is None
    assert card["contract"]["health"] is None

    detail = (
        await app_client.get(f"/api/cases/{created['id']}", headers=headers(handler_dl))
    ).json()
    consultant = detail["consultant"]
    assert consultant["client_name"] and consultant["candidate_name"]
    for key in queries.CARE_ONLY_FIELDS:
        assert consultant[key] is None, key

    own = (
        await app_client.get(f"/api/cases/{created['id']}", headers=headers(admin))
    ).json()["consultant"]
    assert own["owner_user_id"] == owner_dl.id


async def test_patch_contract_leaves_a_trace(app_client, care_on) -> None:
    admin = await make_user(UserRole.admin)
    client_id = await make_client()
    contract_id, _ = await make_contract(client_id)
    created = await _case(app_client, admin)
    patched = await app_client.patch(
        f"/api/cases/{created['id']}",
        json={"contract_id": contract_id},
        headers=headers(admin),
    )
    assert patched.status_code == 200, patched.text
    assert patched.json()["contract"]["id"] == contract_id
    async with AsyncSessionLocal() as db:
        trace = await db.scalar(
            select(HrAuditEvent).where(
                HrAuditEvent.entity_type == "admin_case",
                HrAuditEvent.entity_id == str(created["id"]),
                HrAuditEvent.action == "case_linked",
            )
        )
        events = await queries.contract_case_events(db, contract_id, admin)
    assert trace.actor_user_id == admin.id
    assert trace.details["previous_contract_id"] is None
    assert [e["kind"] for e in events if e["case_id"] == created["id"]] == [
        "case_opened",
        "case_linked",
    ]


# ── Sprawy w karcie konsultanta ──────────────────────────────────────────────


async def test_contract_cases_hide_content_and_negotiations(
    app_client, care_on
) -> None:
    admin = await make_user(UserRole.admin)
    dl = await make_user(UserRole.delivery_lead)
    stranger = await make_user(UserRole.delivery_lead)
    client_id = await make_client(dl=dl)
    await make_client(dl=stranger)
    contract_id, _ = await make_contract(client_id)
    plain = await _case(app_client, admin, contract_id=contract_id)
    talk = await _case(
        app_client,
        admin,
        contract_id=contract_id,
        title="Nowa stawka od stycznia",
        area="negotiation",
    )
    url = f"/api/care/contracts/{contract_id}/cases"

    rows = (await app_client.get(url, headers=headers(admin))).json()
    by_id = {row["id"]: row for row in rows}
    assert by_id[plain["id"]]["content_hidden"] is False
    assert by_id[talk["id"]]["content_hidden"] is True
    assert by_id[talk["id"]]["title"] == "Nowa stawka od stycznia"
    assert by_id[talk["id"]]["area_label"] == "Negocjacje"
    assert by_id[plain["id"]]["status_label"] == "Nowa"
    assert set(by_id[plain["id"]]) == {
        "id",
        "title",
        "area",
        "area_label",
        "status",
        "status_label",
        "due_on",
        "follow_up_on",
        "overdue",
        "assignee_name",
        "source",
        "content_hidden",
    }

    as_dl = (await app_client.get(url, headers=headers(dl))).json()
    assert {row["id"] for row in as_dl} >= {plain["id"], talk["id"]}
    assert all(row["content_hidden"] for row in as_dl)  # DL bez „Spraw”
    dl_rows = {row["id"]: row for row in as_dl}
    assert dl_rows[talk["id"]]["title"] == "Sprawa: Negocjacje"
    assert dl_rows[plain["id"]]["title"] == "Sprawa: Administracja"
    assert all(row["assignee_name"] is None for row in as_dl)
    async with AsyncSessionLocal() as db:
        events = await queries.contract_case_events(db, contract_id, dl)
    assert "Nowa stawka od stycznia" not in json.dumps(events, default=str)

    refused = await app_client.get(url, headers=headers(stranger))
    assert refused.status_code == 403

    await set_modules({**{k: True for k in HR_MODULE_KEYS}, "cases": False})
    assert (await app_client.get(url, headers=headers(admin))).json() == []


# ── Koniec współpracy ────────────────────────────────────────────────────────


async def _pack(client_id: int) -> None:
    async with AsyncSessionLocal() as db:
        await db.execute(
            text("UPDATE clients SET equipment_provider = 'nasz' WHERE id = :id"),
            {"id": client_id},
        )
        pack = ClientOnboardingPack(client_id=client_id, version=1)
        db.add(pack)
        await db.flush()
        db.add(
            ClientOnboardingPackItem(
                pack_id=pack.id, section="access", position=0, name="Konto VPN"
            )
        )
        await db.commit()


async def _end(contract_id: int, on: date) -> dict:
    async with AsyncSessionLocal() as db:
        contract = await db.get(Contract, contract_id)
        contract.end_date = on
        contract.terminated_at = on
        outcome = await contract_hooks.contract_ended(db, contract)
        await db.commit()
        return outcome


async def _end_case(contract_id: int) -> AdminCase | None:
    async with AsyncSessionLocal() as db:
        return await db.scalar(
            select(AdminCase).where(
                AdminCase.source_key == hooks.contract_end_source_key(contract_id)
            )
        )


async def test_contract_end_opens_case_for_owner_and_undo_closes_it(care_on) -> None:
    dl = await make_user(UserRole.delivery_lead)
    client_id = await make_client(dl=dl)
    await _pack(client_id)
    contract_id, candidate_id = await make_contract(client_id)
    candidate = await _candidate(candidate_id)
    last_day = business_today() + timedelta(days=20)

    assert (await _end(contract_id, last_day))["cases_end"] == "ok"
    case = await _end_case(contract_id)
    assert case.title.startswith(
        f"Koniec współpracy: {candidate.name} {candidate.lastname} · Firma"
    )
    assert (case.area, case.source, case.status) == ("offboarding", "contract", "new")
    assert case.assignee_user_id == dl.id
    assert case.contract_id == contract_id
    assert case.due_on == last_day
    texts = [item["text"] for item in case.checklist]
    assert rules.END_EQUIPMENT_ITEM in texts
    assert f"{rules.END_ACCESS_PREFIX}Konto VPN" in texts
    assert texts[-1] == rules.END_SETTLEMENT_ITEM

    await _end(contract_id, last_day)  # drugi raz — ta sama sprawa
    async with AsyncSessionLocal() as db:
        count = await db.scalar(
            select(func.count(AdminCase.id)).where(
                AdminCase.source_key == hooks.contract_end_source_key(contract_id)
            )
        )
    assert count == 1

    async with AsyncSessionLocal() as db:
        contract = await db.get(Contract, contract_id)
        await contract_hooks.contract_end_undone(db, contract)
        await db.commit()
    assert (await _end_case(contract_id)).status == "closed"

    await _end(contract_id, last_day + timedelta(days=5))  # zakończona ponownie
    reopened = await _end_case(contract_id)
    assert reopened.id == case.id
    assert reopened.status == "new"
    assert reopened.closed_at is None
    assert reopened.due_on == last_day + timedelta(days=5)


async def test_voided_contract_and_switched_off_module_open_nothing(
    care_on,
) -> None:
    client_id = await make_client()
    voided, _ = await make_contract(client_id)
    async with AsyncSessionLocal() as db:
        await db.execute(
            update(Contract)
            .where(Contract.id == voided)
            .values(status=ContractStatus.void)
        )
        await db.commit()
        contract = await db.get(Contract, voided)
        await contract_hooks.contract_ended(db, contract)
        await db.commit()
    assert await _end_case(voided) is None

    other, _ = await make_contract(client_id)
    await set_modules({**{k: True for k in HR_MODULE_KEYS}, "cases": False})
    await _end(other, business_today() + timedelta(days=3))
    assert await _end_case(other) is None


# ── Import z Compassa ────────────────────────────────────────────────────────


async def test_compass_import_links_sure_contract_and_keeps_nexus_choice() -> None:
    tag = uuid.uuid4().hex[:8]
    async with AsyncSessionLocal() as db:
        try:
            client = Client(name=f"Spółka Łącznik {tag}")
            ewa = Candidate(name="Ewa", lastname=f"Łącznik{tag}")
            db.add_all([client, ewa])
            await db.flush()
            contract = Contract(
                candidate_id=ewa.id,
                client_id=client.id,
                status=ContractStatus.active,
                start_date=date(2026, 8, 1),
            )
            chosen = Contract(
                candidate_id=ewa.id,
                client_id=client.id,
                status=ContractStatus.ended,
                start_date=date(2025, 1, 1),
                end_date=date(2025, 12, 31),
            )
            db.add_all([contract, chosen])
            await db.flush()
            _, a_id, a_row = await make_person(db, f"{tag}-author")
            sure = _ticket("inbox_administracja", a_id, f"Urlop {tag}")
            unknown = _ticket("inbox_administracja", a_id, f"Inna {tag}")
            bundle = make_bundle(
                {
                    "profiles": [a_row],
                    "support_categories": [
                        {"id": cid, "slug": slug} for slug, cid in CATEGORIES.items()
                    ],
                    "support_tickets": [sure, unknown],
                    "support_inbox_meta": [
                        _meta(
                            sure,
                            consultant_name=f"łącznik{tag} EWA",
                            client_name=f"Spółka Łącznik {tag}",
                        ),
                        _meta(
                            unknown,
                            consultant_name="Ktoś Nieznany",
                            client_name=f"Spółka Łącznik {tag}",
                        ),
                    ],
                }
            )
            _, _, written = await run_import(db, "cases", bundle)
            assert written["contracts_linked"] == 1
            cases = {
                c.source_key: c
                for c in await db.scalars(
                    select(AdminCase).where(
                        AdminCase.source_key.in_(
                            [f"compass:{sure['id']}", f"compass:{unknown['id']}"]
                        )
                    )
                )
            }
            linked = cases[f"compass:{sure['id']}"]
            assert linked.contract_id == contract.id
            assert cases[f"compass:{unknown['id']}"].contract_id is None

            # Obsługa przepięła sprawę w NEXUSIE — kolejny import tego nie cofa.
            linked.contract_id = chosen.id
            await db.flush()
            _, _, again = await run_import(db, "cases", bundle)
            assert again["contracts_linked"] == 0
            assert (await db.get(AdminCase, linked.id)).contract_id == chosen.id
        finally:
            await db.rollback()


async def test_compass_case_without_sure_contract_gets_link_only_on_reading() -> None:
    """Niepewna para nie zapisuje się, ale propozycje liczy odczyt sprawy."""

    tag = uuid.uuid4().hex[:8]
    async with AsyncSessionLocal() as db:
        try:
            client = Client(name=f"Firma Odczyt {tag}")
            ola = Candidate(name="Ola", lastname=f"Odczyt{tag}")
            db.add_all([client, ola])
            await db.flush()
            contract = Contract(
                candidate_id=ola.id,
                client_id=client.id,
                status=ContractStatus.active,
                start_date=business_today() - timedelta(days=3),
            )
            case = AdminCase(
                title="Sprawa z Compassa",
                area="administration",
                priority="P2",
                status="new",
                source="compass_import",
                source_key=f"compass:{uuid.uuid4()}",
                description=f"Konsultant: Ola Odczyt{tag} · klient: Firma Odczyt {tag}",
                checklist=[],
            )
            db.add_all([contract, case])
            await db.flush()
            from app.services.admin_cases.contract_links import link_suggestions

            suggestions = await link_suggestions(db, case)
            assert suggestions[0]["contract_id"] == contract.id
            assert case.contract_id is None
        finally:
            await db.rollback()
