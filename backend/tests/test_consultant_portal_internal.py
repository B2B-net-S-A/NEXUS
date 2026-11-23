"""Tryb „Tylko zespół” (``internal``, decyzja Artura 16.11.2026).

Zespół (Finanse, rozliczenia, back office) widzi i testuje rozliczenia na produkcji,
a konsultant nic nie dostaje: panel zamknięty, żadnego maila. Czytnik rozliczenia@
rozpoznaje nadawcę bez aktywacji panelu (adres z kontraktu, potem z kartoteki).
Skrzynka i mailer to atrapy; dane fikcyjne.
"""

from __future__ import annotations

import base64
from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio
from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert

from app.core.database import AsyncSessionLocal
from app.core.scheduling import business_today
from app.models.app_setting import AppSetting
from app.models.back_office import BoCard
from app.models.candidate import Candidate
from app.models.consultant_portal import CpDocument, CpMailboxState
from app.models.contract import Contract, ContractStatus
from app.models.user import UserRole
from app.services import storage_service
from app.services.consultant_portal import mailbox
from app.services.hr.modules import HR_MODULE_KEYS, HR_MODULES_SETTING
from tests.care_announcements_seed import (  # noqa: F401  (fixture'y)
    care_on,
    headers as staff_headers,
    make_user,
)
from tests.consultant_portal_seed import (  # noqa: F401  (fixture'y)
    BASE,
    STAFF,
    install_mailer,
    make_person,
    portal_restored,
    set_portal,
)

pytestmark = [pytest.mark.asyncio, pytest.mark.usefixtures("care_on")]

PDF = b"%PDF-1.4 fikcyjny raport"
SETTLEMENTS = "/api/finance/settlements"


# ── Z bazą ───────────────────────────────────────────────────────────────────


@pytest_asyncio.fixture(autouse=True)
async def _quiet_documents():
    async with AsyncSessionLocal() as db:
        for row in (await db.scalars(select(CpDocument))).all():
            await db.delete(row)
        for card in (
            await db.scalars(select(BoCard).where(BoCard.source_kind == "document"))
        ).all():
            await db.delete(card)
        state = await db.get(CpMailboxState, 1)
        if state is not None:
            await db.delete(state)
        await db.commit()
    yield


@pytest.fixture(autouse=True)
def _storage(tmp_path, monkeypatch):
    monkeypatch.setattr(storage_service, "STORAGE_ROOT", tmp_path)


@pytest_asyncio.fixture
async def internal(portal_restored):  # noqa: F811  (fixture z seeda)
    await set_portal("internal")
    yield


async def _setting(key: str, value: object) -> object:
    async with AsyncSessionLocal() as db:
        had = await db.get(AppSetting, key)
        previous = had.value if had else None
        if value is None:
            await db.execute(AppSetting.__table__.delete().where(AppSetting.key == key))
        else:
            await db.execute(
                insert(AppSetting)
                .values(key=key, value=value)
                .on_conflict_do_update(
                    index_elements=[AppSetting.key], set_={"value": value}
                )
            )
        await db.commit()
    return previous


@pytest_asyncio.fixture
async def module_on():
    previous = await _setting("client_settlements", {"enabled": True})
    yield
    await _setting("client_settlements", previous)


class FakeMailbox:
    def __init__(self, messages, files) -> None:
        self.messages = messages
        self.files = files

    async def list_messages(self, since):
        return self.messages

    async def attachments(self, message_id):
        return self.files.get(message_id, [])

    async def mime(self, message_id):
        return None


def _message(message_id: str, sender: str) -> dict:
    return {
        "id": message_id,
        "subject": "Raport",
        "hasAttachments": True,
        "from": {"emailAddress": {"address": sender}},
        "receivedDateTime": datetime.now(timezone.utc).isoformat(),
    }


def _attachment(name: str, data: bytes) -> dict:
    return {
        "@odata.type": "#microsoft.graph.fileAttachment",
        "name": name,
        "isInline": False,
        "contentBytes": base64.b64encode(data).decode(),
    }


async def _read(reader) -> dict:
    async with AsyncSessionLocal() as db:
        result = await mailbox.run_once(db, mailbox=reader)
        await db.commit()
    return result


async def _documents() -> list[CpDocument]:
    async with AsyncSessionLocal() as db:
        return list(
            (await db.scalars(select(CpDocument).order_by(CpDocument.id))).all()
        )


@pytest.mark.usefixtures("internal")
async def test_reader_matches_sender_without_panel_activation() -> None:
    person = await make_person(activated=False)
    reader = FakeMailbox(
        [_message("m1", person.email.upper())], {"m1": [_attachment("r.pdf", PDF)]}
    )
    result = await _read(reader)
    assert result["created"] == 1
    assert [row.contract_id for row in await _documents()] == [person.contract_id]


@pytest.mark.usefixtures("internal")
async def test_reader_falls_back_to_candidate_card_address() -> None:
    person = await make_person(activated=False)
    address = f"karta-{person.contract_id}@example.com"
    async with AsyncSessionLocal() as db:
        await db.execute(
            update(Contract)
            .where(Contract.id == person.contract_id)
            .values(candidate_email=None)
        )
        await db.execute(
            update(Candidate)
            .where(Candidate.id == person.candidate_id)
            .values(email=address)
        )
        await db.commit()
    reader = FakeMailbox([_message("m1", address)], {"m1": [_attachment("r.pdf", PDF)]})
    await _read(reader)
    assert [row.contract_id for row in await _documents()] == [person.contract_id]


@pytest.mark.usefixtures("internal")
async def test_unknown_sender_waits_for_assignment() -> None:
    reader = FakeMailbox(
        [_message("m1", "ktos@firma.example.com")], {"m1": [_attachment("r.pdf", PDF)]}
    )
    assert (await _read(reader))["created"] == 1
    assert [row.contract_id for row in await _documents()] == [None]


@pytest.mark.usefixtures("portal_restored")
async def test_internal_without_back_office_reads_nothing() -> None:
    await set_portal("internal")
    async with AsyncSessionLocal() as db:
        await db.execute(
            update(AppSetting)
            .where(AppSetting.key == HR_MODULES_SETTING)
            .values(value={key: False for key in HR_MODULE_KEYS})
        )
        await db.commit()
    reader = FakeMailbox([], {})
    assert await _read(reader) == {"status": "disabled"}


@pytest.mark.usefixtures("internal")
async def test_consultant_gets_no_link_and_no_mail(app_client, monkeypatch) -> None:
    mailer = install_mailer(monkeypatch)
    person = await make_person()  # nawet z aktywacją
    status = await app_client.get(f"{BASE}/status")
    assert status.status_code == 404
    link = await app_client.post(f"{BASE}/link", json={"email": person.email})
    assert link.status_code == 404
    reader = FakeMailbox(
        [_message("m1", person.email)], {"m1": [_attachment("r.pdf", PDF)]}
    )
    await _read(reader)
    document = (await _documents())[0]
    admin = await make_user(UserRole.admin)
    accepted = await app_client.post(
        f"{STAFF}/documents/{document.id}/accept", headers=staff_headers(admin)
    )
    assert accepted.status_code == 200, accepted.text
    assert mailer.sent == []


@pytest.mark.usefixtures("portal_restored")
async def test_admin_saves_internal_state(app_client) -> None:
    admin = await make_user(UserRole.admin)
    saved = await app_client.put(
        "/api/consultant-panel/settings",
        headers=staff_headers(admin),
        json={"state": "internal"},
    )
    assert saved.status_code == 200, saved.text
    assert saved.json()["state"] == "internal"


# ── Włącznik modułu i karta „Start rozliczeń” ────────────────────────────────


@pytest_asyncio.fixture
async def module_restored():
    previous = await _setting("client_settlements", None)
    yield
    await _setting("client_settlements", previous)


@pytest.mark.usefixtures("module_restored")
async def test_only_admin_switches_the_module(app_client) -> None:
    finance = await make_user(UserRole.finance)
    refused = await app_client.put(
        f"{SETTLEMENTS}/module", headers=staff_headers(finance), json={"enabled": True}
    )
    assert refused.status_code == 403
    admin = await make_user(UserRole.admin)
    saved = await app_client.put(
        f"{SETTLEMENTS}/module", headers=staff_headers(admin), json={"enabled": True}
    )
    assert saved.status_code == 200, saved.text
    assert saved.json()["enabled"] is True
    state = await app_client.get(
        f"{SETTLEMENTS}/module", headers=staff_headers(finance)
    )
    assert state.json() == {"enabled": True, "open": True}


@pytest.mark.usefixtures("module_restored", "internal")
async def test_start_card_shows_switches(app_client) -> None:
    admin = await make_user(UserRole.admin)
    card = await app_client.get(f"{SETTLEMENTS}/start", headers=staff_headers(admin))
    assert card.status_code == 200, card.text
    body = card.json()
    assert body["module_enabled"] is False
    assert body["portal_state"] == "internal"
    assert body["back_office"] is True
    assert set(body["mailbox"]) >= {"configured", "last_status"}
    finance = await make_user(UserRole.finance)
    refused = await app_client.get(
        f"{SETTLEMENTS}/start", headers=staff_headers(finance)
    )
    assert refused.status_code == 403


# ── Podgląd panelu ───────────────────────────────────────────────────────────


@pytest.mark.usefixtures("module_on", "internal")
async def test_finance_previews_panel_of_not_activated_contract(app_client) -> None:
    person = await make_person(activated=False)
    finance = await make_user(UserRole.finance)
    preview = await app_client.get(
        f"{SETTLEMENTS}/contract/{person.contract_id}/panel-preview",
        headers=staff_headers(finance),
    )
    assert preview.status_code == 200, preview.text
    body = preview.json()
    assert body["activated"] is False
    assert set(body) == {"activated", "me", "todo", "settlement", "finance"}
    assert isinstance(body["todo"]["items"], list)
    assert isinstance(body["finance"]["months"], list)
    # Podgląd nie zakłada aktywacji ani sesji.
    status = await app_client.get(f"{BASE}/status")
    assert status.status_code == 404


@pytest.mark.usefixtures("module_on")
async def test_preview_of_missing_contract_is_404(app_client) -> None:
    finance = await make_user(UserRole.finance)
    missing = await app_client.get(
        f"{SETTLEMENTS}/contract/987654321/panel-preview",
        headers=staff_headers(finance),
    )
    assert missing.status_code == 404


async def test_preview_needs_open_module(app_client) -> None:
    previous = await _setting("client_settlements", {"enabled": False})
    try:
        recruiter = await make_user(UserRole.recruiter)
        refused = await app_client.get(
            f"{SETTLEMENTS}/contract/1/panel-preview", headers=staff_headers(recruiter)
        )
        assert refused.status_code in (403, 404)
    finally:
        await _setting("client_settlements", previous)


@pytest.mark.usefixtures("internal")
async def test_person_with_two_live_contracts_waits_for_assignment() -> None:
    """Zakończony kontrakt żyje jeszcze 60 dni (ostatni raport przychodzi po końcu).
    Osoba z dwoma takimi kontraktami nie dostaje automatu: czytnik nie zgadnie, czyj
    to RCP, a przypisanego dokumentu Finanse nie przepną (``assign_contract`` → 409)."""

    old = await make_person(activated=False)
    new = await make_person(activated=False, candidate_id=old.candidate_id)
    async with AsyncSessionLocal() as db:
        await db.execute(
            update(Contract)
            .where(Contract.id == old.contract_id)
            .values(
                status=ContractStatus.ended,
                end_date=business_today() - timedelta(days=10),
            )
        )
        await db.execute(
            update(Contract)
            .where(Contract.id == new.contract_id)
            .values(candidate_email=old.email)
        )
        await db.commit()
    reader = FakeMailbox(
        [_message("m1", old.email)], {"m1": [_attachment("RCP_10_2026.pdf", PDF)]}
    )
    assert (await _read(reader))["created"] == 1
    assert [row.contract_id for row in await _documents()] == [None]


# ── Jedna skrzynka wsparcie@ (E8, 18.11.2026) ────────────────────────────────


def _to(message: dict, *addresses: str) -> dict:
    return {
        **message,
        "toRecipients": [{"emailAddress": {"address": a}} for a in addresses],
    }


@pytest.fixture
def shared_support_mailbox(monkeypatch):
    from app.core.config import settings

    monkeypatch.setattr(
        settings, "CONSULTANT_PORTAL_SETTLEMENTS_MAILBOX", "wsparcie@example.com"
    )
    monkeypatch.setattr(settings, "ADMIN_CASES_M365_MAILBOX", "Wsparcie@Example.com")
    return settings


@pytest.mark.usefixtures("internal")
async def test_shared_mailbox_reads_only_mail_to_settlements_address(
    shared_support_mailbox, monkeypatch
) -> None:
    monkeypatch.setattr(
        shared_support_mailbox,
        "CONSULTANT_PORTAL_SETTLEMENTS_ADDRESSES",
        "rozliczenia@example.com",
    )
    person = await make_person(activated=False)
    report = _to(_message("m1", person.email), "Rozliczenia@example.com")
    leave = _to(_message("m2", person.email), "wsparcie@example.com")
    reader = FakeMailbox(
        [report, leave],
        {
            "m1": [_attachment("rcp.pdf", PDF)],
            "m2": [_attachment("l4.pdf", PDF + b" inny")],
        },
    )
    result = await _read(reader)
    assert result["status"] == "ok"
    assert result["created"] == 1
    assert [row.graph_message_id for row in await _documents()] == ["m1"]


@pytest.mark.usefixtures("internal")
async def test_shared_mailbox_without_settlements_address_reads_nothing(
    shared_support_mailbox, monkeypatch
) -> None:
    monkeypatch.setattr(
        shared_support_mailbox, "CONSULTANT_PORTAL_SETTLEMENTS_ADDRESSES", ""
    )
    person = await make_person(activated=False)
    reader = FakeMailbox(
        [_to(_message("m1", person.email), "rozliczenia@example.com")],
        {"m1": [_attachment("rcp.pdf", PDF)]},
    )
    result = await _read(reader)
    assert result == {"status": "error", "reason": "shared_without_route"}
    assert await _documents() == []
    async with AsyncSessionLocal() as db:
        state = await db.get(CpMailboxState, 1)
    assert (state.last_status, state.last_error) == ("error", "shared_without_route")


@pytest.mark.usefixtures("internal")
async def test_settlements_address_with_separate_mailboxes_stops_reader(
    shared_support_mailbox, monkeypatch
) -> None:
    """Adresy rozliczeń przy innej skrzynce spraw (np. wsparcie@ ustawiona za wcześnie):
    czytnik stoi i nie rusza znacznika, zamiast robić dokument z każdego maila."""
    monkeypatch.setattr(
        shared_support_mailbox, "ADMIN_CASES_M365_MAILBOX", "stara@example.com"
    )
    monkeypatch.setattr(
        shared_support_mailbox,
        "CONSULTANT_PORTAL_SETTLEMENTS_ADDRESSES",
        "rozliczenia@example.com",
    )
    person = await make_person(activated=False)
    reader = FakeMailbox(
        [_to(_message("m1", person.email), "wsparcie@example.com")],
        {"m1": [_attachment("l4.pdf", PDF)]},
    )
    assert await _read(reader) == {"status": "error", "reason": "route_not_shared"}
    assert await _documents() == []
    async with AsyncSessionLocal() as db:
        state = await db.get(CpMailboxState, 1)
    assert (state.last_error, state.last_seen_received_at) == ("route_not_shared", None)


# ── Przekazane maile i nazwisko w temacie (próba IX–XI 2026) ────────────────


class MimeMailbox(FakeMailbox):
    def __init__(self, messages, files, raw) -> None:
        super().__init__(messages, files)
        self.raw = raw

    async def mime(self, message_id):
        return self.raw.get(message_id)


def _eml(sender: str, text: str, *, attach: object = None) -> bytes:
    from email.message import EmailMessage

    message = EmailMessage()
    message["From"] = sender
    message["Subject"] = "FW: raport"
    message.set_content(text)
    if isinstance(attach, EmailMessage):
        message.add_attachment(attach)
    elif attach is not None:
        message.add_attachment(
            attach, maintype="application", subtype="pdf", filename="TS.pdf"
        )
    return message.as_bytes()


async def _full_name(person) -> str:
    async with AsyncSessionLocal() as db:
        candidate = await db.get(Candidate, person.candidate_id)
    return f"{candidate.lastname} {candidate.name}"


@pytest.mark.usefixtures("internal")
async def test_forward_in_body_goes_to_the_original_sender() -> None:
    person = await make_person(activated=False)
    raw = _eml(
        "koordynator@firma.example.com",
        f"Przesyłam.\n\nFrom: Konsultant <{person.email}>\nSent: wtorek\n",
    )
    reader = MimeMailbox(
        [_message("m1", "koordynator@firma.example.com")],
        {"m1": [_attachment("r.pdf", PDF)]},
        {"m1": raw},
    )
    await _read(reader)
    assert [row.contract_id for row in await _documents()] == [person.contract_id]


@pytest.mark.usefixtures("internal")
async def test_attached_mail_files_are_read_and_assigned() -> None:
    from email.message import EmailMessage

    person = await make_person(activated=False)
    inner = EmailMessage()
    inner["From"] = person.email
    inner.set_content("raport")
    inner.add_attachment(
        b"%PDF-1.4 raport z wnetrza",
        maintype="application",
        subtype="pdf",
        filename="TS.pdf",
    )
    item = {"@odata.type": "#microsoft.graph.itemAttachment", "name": "raport"}
    reader = MimeMailbox(
        [_message("m1", "kierownik@klient.example.com")],
        {"m1": [item]},
        {"m1": _eml("kierownik@klient.example.com", "w załączeniu", attach=inner)},
    )
    assert (await _read(reader))["created"] == 1
    assert [(r.contract_id, r.file_name) for r in await _documents()] == [
        (person.contract_id, "TS.pdf")
    ]


@pytest.fixture
def company_domain(monkeypatch):
    from app.services.consultant_portal import identity

    monkeypatch.setattr(
        identity, "_company_domains", lambda: frozenset({"firma.example.com"})
    )


@pytest.mark.usefixtures("internal", "company_domain")
async def test_name_in_subject_assigns_only_settlement_files() -> None:
    person = await make_person(activated=False)
    message = _message("m1", "koordynator@firma.example.com")
    message["subject"] = f"Odbiór usług za 10.2026: {await _full_name(person)}"
    reader = FakeMailbox(
        [message],
        {
            "m1": [
                _attachment("TimeSheet.pdf", PDF),
                _attachment("pismo.pdf", b"%PDF-1.4 inne pismo"),
            ]
        },
    )
    await _read(reader)
    assert {r.file_name: r.contract_id for r in await _documents()} == {
        "TimeSheet.pdf": person.contract_id,
        "pismo.pdf": None,
    }


@pytest.mark.usefixtures("internal", "company_domain")
async def test_name_from_outside_address_waits_for_assignment() -> None:
    """Temat może napisać każdy: obcy adres nie wskazuje nim osoby."""
    person = await make_person(activated=False)
    message = _message("m1", "ktos@poczta.example.com")
    message["subject"] = f"Odbiór usług za 10.2026: {await _full_name(person)}"
    reader = FakeMailbox([message], {"m1": [_attachment("TimeSheet.pdf", PDF)]})
    await _read(reader)
    assert [row.contract_id for row in await _documents()] == [None]


@pytest.mark.usefixtures("internal", "company_domain")
async def test_two_people_in_subject_wait_for_assignment() -> None:
    first = await make_person(activated=False)
    second = await make_person(activated=False)
    message = _message("m1", "koordynator@firma.example.com")
    message["subject"] = (
        f"Raport {await _full_name(first)} i {await _full_name(second)}"
    )
    reader = FakeMailbox([message], {"m1": [_attachment("raport.pdf", PDF)]})
    await _read(reader)
    assert [row.contract_id for row in await _documents()] == [None]


@pytest.mark.usefixtures("internal", "company_domain")
async def test_files_of_two_people_go_each_to_the_person_in_its_name() -> None:
    """Koordynator wysyła protokoły zespołu jednym mailem (próba IX–X 2026, Orlen)."""
    first = await make_person(activated=False)
    second = await make_person(activated=False)
    message = _message("m1", "koordynator@firma.example.com")
    message["subject"] = "protokoły"
    reader = FakeMailbox(
        [message],
        {
            "m1": [
                _attachment(f"PROTOKÓŁ_ {await _full_name(first)}_09.2026.pdf", PDF),
                _attachment(
                    f"PROTOKÓŁ_ {await _full_name(second)}_09.2026.pdf",
                    b"%PDF-1.4 drugi raport",
                ),
                _attachment("protokół zbiorczy.pdf", b"%PDF-1.4 zbiorczy"),
                _attachment(f"Umowa {await _full_name(first)}.pdf", b"%PDF-1.4 umowa"),
            ]
        },
    )
    await _read(reader)
    owners = {r.file_name: r.contract_id for r in await _documents()}
    assert owners == {
        f"PROTOKÓŁ_ {await _full_name(first)}_09.2026.pdf": first.contract_id,
        f"PROTOKÓŁ_ {await _full_name(second)}_09.2026.pdf": second.contract_id,
        "protokół zbiorczy.pdf": None,
        # Plik bez słowa raportu albo faktury w nazwie nie idzie do osoby.
        f"Umowa {await _full_name(first)}.pdf": None,
    }


@pytest.mark.usefixtures("internal", "company_domain")
async def test_file_naming_two_people_waits_for_assignment() -> None:
    first = await make_person(activated=False)
    second = await make_person(activated=False)
    message = _message("m1", "koordynator@firma.example.com")
    name = f"TS {await _full_name(first)} i {await _full_name(second)}.pdf"
    reader = FakeMailbox([message], {"m1": [_attachment(name, PDF)]})
    await _read(reader)
    assert [row.contract_id for row in await _documents()] == [None]


@pytest.mark.usefixtures("internal", "company_domain")
async def test_names_in_files_from_outside_address_wait_for_assignment() -> None:
    first = await make_person(activated=False)
    second = await make_person(activated=False)
    message = _message("m1", "ktos@poczta.example.com")
    reader = FakeMailbox(
        [message],
        {
            "m1": [
                _attachment(f"TS {await _full_name(first)}.pdf", PDF),
                _attachment(f"TS {await _full_name(second)}.pdf", b"%PDF-1.4 drugi"),
            ]
        },
    )
    await _read(reader)
    assert [row.contract_id for row in await _documents()] == [None, None]


@pytest.mark.usefixtures("internal")
async def test_forwarded_notice_without_settlement_name_waits() -> None:
    """Wypowiedzenie przekazane z łańcuchem konsultanta nie jest jego fakturą."""
    person = await make_person(activated=False)
    message = _message("m1", "koordynator@firma.example.com")
    message["subject"] = "PD: Wypowiedzenie umowy o współpracy"
    reader = MimeMailbox(
        [message],
        {"m1": [_attachment("skan.pdf", PDF)]},
        {"m1": _eml("koordynator@firma.example.com", f"Od: {person.email}\n")},
    )
    await _read(reader)
    assert [row.contract_id for row in await _documents()] == [None]
