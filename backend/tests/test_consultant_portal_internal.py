"""Tryb „Tylko zespół” (``internal``, decyzja Artura 16.11.2026).

Zespół (Finanse, rozliczenia, back office) widzi i testuje rozliczenia na produkcji,
a konsultant nic nie dostaje: panel zamknięty, żadnego maila. Czytnik rozliczenia@
rozpoznaje nadawcę bez aktywacji panelu (adres z kontraktu, potem z kartoteki).
Skrzynka i mailer to atrapy; dane fikcyjne.
"""

from __future__ import annotations

import base64
from datetime import datetime, timezone

import pytest
import pytest_asyncio
from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert

from app.core.database import AsyncSessionLocal
from app.models.app_setting import AppSetting
from app.models.back_office import BoCard
from app.models.candidate import Candidate
from app.models.consultant_portal import CpDocument, CpMailboxState
from app.models.contract import Contract
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
