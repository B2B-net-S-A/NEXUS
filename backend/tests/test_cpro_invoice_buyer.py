"""Nabywca kontraktu Nordei z maila CPro „Invoice address was updated” (24.11.2026).

Mail „Important changes made to contract N” przychodzi do skrzynki DL-a; numer N to
numer Call-Off, czyli tytuł zamówienia Nordei. NEXUS dopisuje nabywcę z kodem adresu
CPro (F206…) od miesiąca maila i dzwoni do Finansów. Wystawionych faktur nie rusza.
Dane fikcyjne.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timezone
from decimal import Decimal

import pytest
from sqlalchemy import delete, select

from app.core.database import AsyncSessionLocal
from app.core.security import hash_password
from app.models.candidate import Candidate
from app.models.client import Client
from app.models.client_issued_invoice import ClientIssuedInvoice
from app.models.client_order import ClientOrder, ClientOrderStatus
from app.models.contract import Contract, ContractStatus
from app.models.cpro_mail import CproMailEvent
from app.models.m365 import Email, EmailDirection, EmailMatchMethod
from app.models.notification import Notification, NotificationType
from app.models.user import User, UserRole
from app.services import cpro_invoice_buyer, cpro_mail
from app.services.client_invoicing import issue_settings
from app.services.cpro_mail import VerifiedMail


def _settings(*buyers: dict) -> dict:
    return issue_settings.normalize({"clients": {"11": {"buyers": list(buyers)}}})


def test_cpro_code_is_kept_uppercase_without_spaces():
    data = _settings({"name": "Nordea Bank Abp", "cpro_code": " f206 "})
    assert data["clients"]["11"]["buyers"][0]["cpro_code"] == "F206"


def test_cpro_code_with_wrong_shape_is_dropped():
    data = _settings({"name": "Nordea Bank Abp", "cpro_code": "Abp Finland"})
    assert data["clients"]["11"]["buyers"][0]["cpro_code"] == ""


def test_two_buyers_cannot_share_cpro_code():
    data = _settings(
        {"name": "Nordea Bank Abp", "cpro_code": "F206"},
        {"name": "Nordea Bank Abp S.A.", "cpro_code": "f206"},
    )
    with pytest.raises(issue_settings.IssueSettingsError, match="F206"):
        issue_settings.validate(data)


def test_buyer_found_by_cpro_code():
    data = _settings(
        {"name": "Nordea Bank Abp", "cpro_code": "F206"},
        {"name": "Nordea Bank Abp S.A.", "cpro_code": "F218"},
    )
    found = issue_settings.buyer_by_cpro_code(data, 11, "f218")
    assert found is not None and found["name"] == "Nordea Bank Abp S.A."
    assert issue_settings.buyer_by_cpro_code(data, 11, "F999") is None
    assert issue_settings.buyer_by_cpro_code(data, 12, "F206") is None
    assert issue_settings.buyer_by_cpro_code(data, 11, "") is None


def test_settings_screen_cannot_overwrite_contract_history():
    # Karta ustawień otwarta przed mailem CPro odsyła stare przypisania.
    stored = issue_settings.normalize(
        {
            "clients": {
                "11": {
                    "buyers": [
                        {"name": "A", "code": "b1"},
                        {"name": "B", "code": "b2"},
                    ],
                    "contract_buyers": {
                        "7": [
                            {"code": "b1", "from": "2026-01"},
                            {"code": "b2", "from": "2026-09"},
                        ]
                    },
                }
            }
        }
    )
    screen = {
        "clients": {
            "11": {
                "buyers": [
                    {"name": "A", "code": "b1", "cpro_code": "F218"},
                    {"name": "B", "code": "b2"},
                ],
                "contract_buyers": {"7": [{"code": "b1", "from": "2026-01"}]},
            },
            "12": {"payment_days": 30},
        }
    }
    merged = issue_settings.normalize(
        issue_settings.keep_stored_mapping(screen, stored)
    )
    assert merged["clients"]["11"]["contract_buyers"]["7"][-1] == {
        "code": "b2",
        "from": "2026-09",
    }
    assert merged["clients"]["11"]["buyers"][0]["cpro_code"] == "F218"
    assert merged["clients"]["12"]["payment_days"] == 30


# ── Pętla cpro_mail z bazą ─────────────────────────────────────────────────
CPRO_HTML = '<a href="https://nordea.onevms.se/nordea/start.jsp?x=1">Kontrakt</a>'
INTRO = (
    "Please update your invoice reference details with the information provided below"
)
#: 15.09.2026, 10:00 czasu firmy — nabywca od 2026-09.
MAIL_AT = datetime(2026, 9, 15, 8, 0, tzinfo=timezone.utc)


def _address_body(
    old: str = "F218 Nordea Bank Abp S.A.", new: str = "F206 Nordea Bank Abp Finland"
) -> str:
    return (
        f"{INTRO}\n\nInvoice address was updated from: {old}, to: {new}\n\n"
        "Anna TestA - PL dev (000000)** This is an auto-generated notification **"
    )


def _verifier(body: str):
    async def verifier(_db, _email):
        return VerifiedMail(
            found=True, authenticated=True, body_text=body, body_html=CPRO_HTML
        )

    return verifier


@pytest.fixture(autouse=True)
def _nordea_everywhere(monkeypatch):
    monkeypatch.setattr(cpro_mail, "cpro_enabled_for_client", lambda _c: True)
    monkeypatch.setattr(cpro_invoice_buyer, "cpro_enabled_for_client", lambda _c: True)
    monkeypatch.setattr(
        cpro_mail.settings, "CPRO_MAIL_SINCE", "2020-01-01", raising=False
    )
    monkeypatch.setattr(cpro_mail, "BATCH_LIMIT", 100_000)


@pytest.fixture(autouse=True)
async def _drop_finance_bells():
    """Dzwonek idzie do wszystkich kont Finansów w bazie testowej i jest mailem
    „od razu”: bez sprzątania wiersze wypełniłyby partię outboxu innych testów."""

    started = datetime.now(timezone.utc)
    yield
    async with AsyncSessionLocal() as db:
        await db.execute(
            delete(Notification).where(
                Notification.notification_type == NotificationType.cpro_invoice_buyer,
                Notification.created_at >= started,
            )
        )
        await db.commit()


def _number() -> str:
    return str(uuid.uuid4().int % 900_000 + 100_000)


async def _seed(number: str, *, history=None, buyers=None):
    """Klient z nabywcami (b1 = F218, b2 = F206), kontrakt, zamówienie N, osoba z Finansów."""

    suffix = uuid.uuid4().hex[:8]
    async with AsyncSessionLocal() as db:
        client = Client(name=f"Nordea-{suffix}")
        person = Candidate(
            name="Ola", lastname=f"Testowa{suffix}", email=f"o-{suffix}@example.test"
        )
        finance = User(
            email=f"fin-{suffix}@example.com",
            password_hash=hash_password("P@ssw0rd"),
            name=f"Finanse {suffix}",
            role=UserRole.finance,
            roles=[UserRole.finance.value],
            is_active=True,
        )
        lead = User(
            email=f"dl-{suffix}@example.com",
            password_hash=hash_password("P@ssw0rd"),
            name=f"DL {suffix}",
            role=UserRole.delivery_lead,
            roles=[UserRole.delivery_lead.value],
            is_active=True,
        )
        db.add_all([client, person, finance, lead])
        await db.flush()
        contract = Contract(
            candidate_id=person.id,
            client_id=client.id,
            start_date=date(2026, 1, 5),
            status=ContractStatus.active,
            rate_candidate=Decimal("100"),
        )
        db.add(contract)
        await db.flush()
        db.add(
            ClientOrder(
                client_id=client.id,
                contract_id=contract.id,
                title=f" {number} ",
                status=ClientOrderStatus.active,
                start_date=date(2026, 1, 5),
            )
        )
        data = await issue_settings.load(db)
        raw_clients = {k: v for k, v in data["clients"].items()}
        raw_clients[str(client.id)] = {
            "buyers": buyers
            if buyers is not None
            else [
                {
                    "code": "b1",
                    "name": "Nordea Bank Abp S.A.",
                    "country": "PL",
                    "cpro_code": "F218",
                },
                {
                    "code": "b2",
                    "name": "Nordea Bank Abp",
                    "country": "FI",
                    "cpro_code": "F206",
                },
            ],
            "contract_buyers": {
                str(contract.id): history or [{"code": "b1", "from": "2026-01"}]
            },
        }
        await issue_settings.save(db, {**data, "clients": raw_clients}, actor_id=None)
        await db.commit()
        return client.id, contract.id, finance.id, lead.id


async def _invoice(
    db,
    client_id: int,
    contract_id: int,
    month: int,
    *,
    status: str = "sent",
    code: str = "b1",
):
    seq = uuid.uuid4().int % 900_000 + 100_000
    invoice = ClientIssuedInvoice(
        client_id=client_id,
        invoice_type="VAT",
        series_code="UE",
        status=status,
        period_year=2026,
        period_month=month,
        issue_date=date(2026, month, 28),
        number_year=None if status == "draft" else 2026,
        number_month=None if status == "draft" else month,
        number_seq=None if status == "draft" else seq,
        invoice_number=None if status == "draft" else f"{seq}/{month}/2026/UE",
        currency="EUR",
        buyer={"code": code, "name": "Nordea"},
        lines=[{"name": "Usługi", "contract_id": contract_id}],
    )
    db.add(invoice)
    await db.flush()
    return invoice


async def _mail(owner_id: int, subject: str, received_at: datetime = MAIL_AT) -> str:
    message_id = uuid.uuid4().hex
    key = f"<{message_id}@onevms>"
    async with AsyncSessionLocal() as db:
        db.add(
            Email(
                user_id=owner_id,
                m365_message_id=message_id,
                m365_internet_message_id=key,
                m365_conversation_id=message_id,
                subject=subject,
                from_address="noreply@onevms.se",
                from_name="NOREPLY CPro",
                received_at=received_at,
                direction=EmailDirection.received,
                match_method=EmailMatchMethod.unmatched,
            )
        )
        await db.commit()
    return key


async def _sweep(body: str) -> None:
    async with AsyncSessionLocal() as db:
        await cpro_mail.run_sweep(db, verifier=_verifier(body))


async def _state(client_id: int, contract_id: int, key: str, finance_id: int):
    async with AsyncSessionLocal() as db:
        data = await issue_settings.load(db)
        history = (
            data["clients"][str(client_id)]
            .get("contract_buyers", {})
            .get(str(contract_id))
        )
        event = await db.scalar(
            select(CproMailEvent).where(CproMailEvent.message_key == key)
        )
        bells = (
            await db.scalars(
                select(Notification).where(
                    Notification.user_id == finance_id,
                    Notification.notification_type
                    == NotificationType.cpro_invoice_buyer,
                )
            )
        ).all()
        return history, event, bells


@pytest.mark.asyncio
async def test_address_change_writes_buyer_from_mail_month_and_rings_finance():
    number = _number()
    client_id, contract_id, finance_id, lead_id = await _seed(number)
    async with AsyncSessionLocal() as db:
        august = await _invoice(db, client_id, contract_id, 8)
        september = await _invoice(db, client_id, contract_id, 9)
        right = await _invoice(db, client_id, contract_id, 10, code="b2")
        await _invoice(db, client_id, contract_id, 10, status="draft")
        await db.commit()
        numbers = (
            august.invoice_number,
            september.invoice_number,
            right.invoice_number,
        )
    key = await _mail(lead_id, f"Important changes made to contract {number}")

    await _sweep(_address_body())

    history, event, bells = await _state(client_id, contract_id, key, finance_id)
    assert history == [
        {"code": "b1", "from": "2026-01"},
        {"code": "b2", "from": "2026-09"},
    ]
    assert (event.kind, event.outcome, event.request_number) == (
        "invoice_address",
        "done",
        number,
    )
    assert len(bells) == 1
    message = bells[0].message
    assert "od 09.2026 nabywca F206 Nordea Bank Abp" in message
    assert "był: Nordea Bank Abp S.A." in message
    assert numbers[1] in message
    assert numbers[0] not in message and numbers[2] not in message
    assert "Szkice do poprawy nabywcy: 1" in message
    assert bells[0].link.endswith("siPeriod=2026-09")
    # Faktury zostają przy swoim nabywcy: korekta to decyzja Finansów.
    async with AsyncSessionLocal() as db:
        kept = await db.get(ClientIssuedInvoice, september.id)
        assert kept.buyer["code"] == "b1"


@pytest.mark.asyncio
async def test_unknown_cpro_code_goes_to_manual_and_rings_finance():
    number = _number()
    client_id, contract_id, finance_id, lead_id = await _seed(number)
    key = await _mail(lead_id, f"Important changes made to contract {number}")

    await _sweep(_address_body(new="F999 Nordea Rahoitus Suomi Oy"))

    history, event, bells = await _state(client_id, contract_id, key, finance_id)
    assert history == [{"code": "b1", "from": "2026-01"}]
    assert event.outcome == "manual"
    assert "F999" in event.outcome_text
    assert len(bells) == 1 and "Kod w CPro" in bells[0].message


@pytest.mark.asyncio
async def test_number_without_order_goes_to_manual():
    number = _number()
    client_id, contract_id, finance_id, lead_id = await _seed(number)
    other = _number()
    key = await _mail(lead_id, f"Important changes made to contract {other}")

    await _sweep(_address_body())

    history, event, bells = await _state(client_id, contract_id, key, finance_id)
    assert history == [{"code": "b1", "from": "2026-01"}]
    assert event.outcome == "manual"
    assert "Nie ma zamówienia Nordei" in event.outcome_text
    assert len(bells) == 1


@pytest.mark.asyncio
async def test_same_buyer_already_set_changes_nothing():
    number = _number()
    client_id, contract_id, finance_id, lead_id = await _seed(
        number, history=[{"code": "b2", "from": "2026-07"}]
    )
    key = await _mail(lead_id, f"Important changes made to contract {number}")

    await _sweep(_address_body())

    history, event, bells = await _state(client_id, contract_id, key, finance_id)
    assert history == [{"code": "b2", "from": "2026-07"}]
    assert event.outcome == "already"
    assert bells == []


@pytest.mark.asyncio
async def test_other_reference_changes_are_only_logged():
    number = _number()
    client_id, contract_id, finance_id, lead_id = await _seed(number)
    key = await _mail(lead_id, f"Important changes made to contract {number}")

    await _sweep(f"{INTRO}Cost center was updated from: 1050000273, to: 2080009273")

    history, event, bells = await _state(client_id, contract_id, key, finance_id)
    assert history == [{"code": "b1", "from": "2026-01"}]
    assert (event.kind, event.outcome, event.reason) == (
        "contract_changed",
        "already",
        "cost center",
    )
    assert bells == []


@pytest.mark.asyncio
async def test_rule_switched_off_changes_nothing():
    number = _number()
    client_id, contract_id, finance_id, lead_id = await _seed(number)
    async with AsyncSessionLocal() as db:
        await cpro_mail.save_rules(db, {"invoice_address": False}, actor_id=lead_id)
        await db.commit()
    try:
        key = await _mail(lead_id, f"Important changes made to contract {number}")
        await _sweep(_address_body())
        history, event, bells = await _state(client_id, contract_id, key, finance_id)
    finally:
        async with AsyncSessionLocal() as db:
            await cpro_mail.save_rules(db, {"invoice_address": True}, actor_id=lead_id)
            await db.commit()
    assert history == [{"code": "b1", "from": "2026-01"}]
    assert event.outcome == "manual"
    assert bells == []


def test_change_month_is_the_company_day():
    # 30.09 23:30 UTC to już 01.10 w Warszawie.
    assert (
        cpro_invoice_buyer.change_month(
            datetime(2026, 9, 30, 23, 30, tzinfo=timezone.utc)
        )
        == "2026-10"
    )
    assert cpro_invoice_buyer.change_month(MAIL_AT) == "2026-09"


def test_finance_bell_goes_out_as_immediate_required_mail():
    # Dzwonek bez ikony to tylko dymek: Finanse offline nie zobaczyłyby zmiany.
    from app.services import notification_delivery as delivery

    kind = delivery.immediate_email_kind(
        NotificationType.cpro_invoice_buyer,
        title="CPro: nowy nabywca kontraktu Nordei",
        related_entity_type="cpro_mail_event",
    )
    assert kind == "cpro_invoice_buyer"
    assert kind in delivery.REQUIRED_KINDS
