"""Rozliczenia w portalu i czytnik ``rozliczenia@``: jedna karta, bez duplikatów.

Skrzynka to atrapa. Pliki idą do katalogu tymczasowego; dane fikcyjne.
"""

from __future__ import annotations

import base64
from datetime import date, datetime, timedelta, timezone

import pytest
import pytest_asyncio
from sqlalchemy import select

from app.core.database import AsyncSessionLocal
from app.core.scheduling import business_today
from app.models.back_office import BoCard
from app.models.consultant_portal import CpDocument, CpMailboxState
from app.services import storage_service
from app.services.back_office import sync
from app.services.consultant_portal import documents, mailbox
from app.services.consultant_portal.mailbox import (
    classify_kind,
    find_period,
    period_for,
)
from app.services.m365.graph_client import GraphRequestError
from tests.care_announcements_seed import (  # noqa: F401  (fixture'y)
    care_on,
    divisions_restored,
    headers as staff_headers,
    make_head,
    make_user,
)
from app.models.user import UserRole
from tests.consultant_portal_seed import (  # noqa: F401  (fixture'y)
    BASE,
    STAFF,
    clean_team,
    install_mailer,
    make_member,
    make_person,
    portal_all,
    portal_restored,
    session_headers,
    set_portal,
)

pytestmark = [pytest.mark.asyncio, pytest.mark.usefixtures("care_on")]

PDF = b"%PDF-1.4 fikcyjny raport"
OTHER_PDF = b"%PDF-1.4 inna wersja raportu"
PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 32


@pytest_asyncio.fixture(autouse=True)
async def _quiet_documents():
    """Karty czytają wszystkie dokumenty: każdy test zaczyna od pustego stanu."""
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


def _period() -> tuple[int, int]:
    from app.core.scheduling import business_today

    today = business_today()
    return today.year, today.month


async def _upload(client, headers, *, kind="report", data=PDF, name="raport.pdf"):
    year, month = _period()
    return await client.post(
        f"{BASE}/finance/documents",
        headers=headers,
        data={"kind": kind, "year": str(year), "month": str(month)},
        files={"file": (name, data, "application/pdf")},
    )


async def _document_cards() -> list[BoCard]:
    async with AsyncSessionLocal() as db:
        return list(
            (
                await db.scalars(
                    select(BoCard).where(
                        BoCard.source_kind == "document", BoCard.state != "done"
                    )
                )
            ).all()
        )


async def _sync() -> dict:
    async with AsyncSessionLocal() as db:
        result = await sync.sync_kinds(db, ["document"], today=business_today())
        await db.commit()
    assert result["failed"] == []
    return result


# ── Dostęp ───────────────────────────────────────────────────────────────────


@pytest.mark.usefixtures("portal_all")
async def test_upload_and_download_with_a_session(app_client) -> None:
    person = await make_person()
    headers = await session_headers(app_client, person)
    done = await _upload(app_client, headers)
    assert done.status_code == 201, done.text
    download = await app_client.get(
        f"{BASE}/finance/documents/{done.json()['id']}/file", headers=headers
    )
    assert download.status_code == 200
    assert download.content == PDF
    assert "attachment" in download.headers["content-disposition"]
    assert (await app_client.get(f"{BASE}/finance/overview")).status_code == 401


@pytest.mark.usefixtures("portal_all")
async def test_consultant_cannot_read_anothers_document(
    app_client, monkeypatch
) -> None:
    owner = await make_person()
    stranger = await make_person()
    uploaded = await _upload(app_client, await session_headers(app_client, owner))
    other = await session_headers(app_client, stranger)
    response = await app_client.get(
        f"{BASE}/finance/documents/{uploaded.json()['id']}/file", headers=other
    )
    assert response.status_code == 404
    overview = await app_client.get(f"{BASE}/finance/overview", headers=other)
    assert "raport.pdf" not in overview.text


@pytest.mark.usefixtures("portal_all")
@pytest.mark.parametrize(
    "data",
    [b"", b"to nie jest dokument", b"MZ\x90\x00 program", b"<html>nie</html>"],
)
async def test_file_type_comes_from_content(app_client, monkeypatch, data) -> None:
    person = await make_person()
    headers = await session_headers(app_client, person)
    response = await _upload(app_client, headers, data=data, name="udaje.pdf")
    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "bad_file"


@pytest.mark.usefixtures("portal_all")
async def test_file_over_the_limit_is_refused(app_client, monkeypatch) -> None:
    person = await make_person()
    headers = await session_headers(app_client, person)
    monkeypatch.setattr(documents, "MAX_FILE_BYTES", 10)
    response = await _upload(app_client, headers, data=PDF)
    assert response.status_code == 413


@pytest.mark.usefixtures("portal_all")
async def test_bad_period_is_refused(app_client, monkeypatch) -> None:
    person = await make_person()
    headers = await session_headers(app_client, person)
    for year, month in ((2031, 1), (2010, 1), (2026, 13)):
        response = await app_client.post(
            f"{BASE}/finance/documents",
            headers=headers,
            data={"kind": "report", "year": str(year), "month": str(month)},
            files={"file": ("raport.pdf", PDF, "application/pdf")},
        )
        assert response.status_code == 422, (year, month)


def test_stored_path_cannot_escape_the_directory(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(storage_service, "STORAGE_ROOT", tmp_path)
    (tmp_path / "tajne.txt").write_text("x")
    with pytest.raises(FileNotFoundError):
        documents.path_for("../tajne.txt")
    with pytest.raises(FileNotFoundError):
        documents.path_for("consultant_portal/../tajne.txt")


# ── Dwa kanały, jedna karta ──────────────────────────────────────────────────


class FakeMailbox:
    def __init__(self, messages=None, attachments=None, error=None) -> None:
        self.messages = messages or []
        self.files = attachments or {}
        self.error = error
        self.since = None

    async def list_messages(self, since):
        self.since = since
        if self.error:
            raise self.error
        return self.messages

    async def attachments(self, message_id):
        return self.files.get(message_id, [])


def _attachment(name, data, *, inline=False) -> dict:
    return {
        "@odata.type": "#microsoft.graph.fileAttachment",
        "name": name,
        "isInline": inline,
        "contentBytes": base64.b64encode(data).decode(),
    }


def _message(message_id, sender, *, subject="Raport", received=None) -> dict:
    moment = received or datetime.now(timezone.utc)
    return {
        "id": message_id,
        "subject": subject,
        "hasAttachments": True,
        "from": {"emailAddress": {"address": sender}},
        "receivedDateTime": moment.isoformat().replace("+00:00", "Z"),
    }


async def _read(reader) -> dict:
    async with AsyncSessionLocal() as db:
        result = await mailbox.run_once(db, mailbox=reader)
        await db.commit()
    return result


@pytest.mark.usefixtures("portal_all")
async def test_both_channels_give_one_card_without_duplicates(
    app_client, monkeypatch
) -> None:
    person = await make_person()
    headers = await session_headers(app_client, person)
    year, month = _period()
    assert (await _upload(app_client, headers)).status_code == 201
    await _sync()
    assert len(await _document_cards()) == 1

    # Ten sam plik mailem: bez nowego wiersza, także gdy okres z maila jest inny.
    reader = FakeMailbox(
        [_message("m1", person.email, subject="Raport bez daty")],
        {"m1": [_attachment("raport.pdf", PDF)]},
    )
    assert (await _read(reader))["created"] == 0
    await _sync()
    async with AsyncSessionLocal() as db:
        rows = (
            await db.scalars(
                select(CpDocument).where(CpDocument.contract_id == person.contract_id)
            )
        ).all()
    assert len(rows) == 1
    assert len(await _document_cards()) == 1

    # Inna wersja za ten sam okres: drugi wiersz, ta sama karta.
    reader = FakeMailbox(
        [_message("m2", person.email, subject=f"Raport {month:02d}/{year}")],
        {"m2": [_attachment("raport2.pdf", OTHER_PDF)]},
    )
    assert (await _read(reader))["created"] == 1
    await _sync()
    cards = await _document_cards()
    assert len(cards) == 1
    assert cards[0].team == "finance"
    assert cards[0].lane == "invoice"
    assert cards[0].contract_id == person.contract_id
    assert len(cards[0].meta["document_ids"]) == 2


@pytest.mark.usefixtures("portal_all")
async def test_report_and_invoice_are_separate_cards(app_client, monkeypatch) -> None:
    person = await make_person()
    headers = await session_headers(app_client, person)
    await _upload(app_client, headers, kind="report", data=PDF)
    await _upload(app_client, headers, kind="invoice", data=OTHER_PDF, name="fv.pdf")
    await _sync()
    titles = sorted(card.title.split(" · ")[0] for card in await _document_cards())
    assert titles == ["Faktura", "Raport"]


@pytest.mark.usefixtures("portal_all")
async def test_second_read_of_same_mail_changes_nothing() -> None:
    person = await make_person()
    reader = FakeMailbox(
        [_message("m1", person.email)],
        {"m1": [_attachment("raport.pdf", PDF)]},
    )
    assert (await _read(reader))["created"] == 1
    assert (await _read(reader))["created"] == 0


@pytest.mark.usefixtures("portal_all")
async def test_card_has_no_amounts_and_closes_after_decision(
    app_client, monkeypatch
) -> None:
    person = await make_person()
    headers = await session_headers(app_client, person)
    uploaded = await _upload(app_client, headers)
    await _sync()
    card = (await _document_cards())[0]
    assert "PLN" not in card.title
    finance = await make_user(UserRole.admin)
    listed = await app_client.get(
        f"{STAFF}/documents/by-card/{card.id}", headers=staff_headers(finance)
    )
    assert listed.status_code == 200
    assert [row["id"] for row in listed.json()["items"]] == [uploaded.json()["id"]]
    accepted = await app_client.post(
        f"{STAFF}/documents/{uploaded.json()['id']}/accept",
        headers=staff_headers(finance),
    )
    assert accepted.status_code == 200, accepted.text
    assert accepted.json()["invoice_signal_at"] is not None
    assert await _document_cards() == []


# ── Czytnik: odmowy i pilotaż ────────────────────────────────────────────────


@pytest.mark.usefixtures("portal_restored")
async def test_reader_does_nothing_when_portal_is_off() -> None:
    await set_portal("off")
    reader = FakeMailbox(error=AssertionError("nie wolno czytać skrzynki"))
    assert await _read(reader) == {"status": "disabled"}


@pytest.mark.usefixtures("portal_all")
async def test_reader_without_configuration_says_so(monkeypatch) -> None:
    monkeypatch.setattr(mailbox.settings, "CONSULTANT_PORTAL_SETTLEMENTS_MAILBOX", "")
    async with AsyncSessionLocal() as db:
        result = await mailbox.run_once(db)
    assert result == {"status": "disabled", "reason": "no_mailbox"}
    async with AsyncSessionLocal() as db:
        state = await db.get(CpMailboxState, 1)
    assert state.last_error == "no_mailbox"


@pytest.mark.usefixtures("portal_all")
@pytest.mark.parametrize("status_code", [401, 403, 404])
async def test_reader_records_graph_refusal_without_crashing(status_code) -> None:
    reader = FakeMailbox(error=GraphRequestError(status_code, {"poufne": "treść"}))
    result = await _read(reader)
    assert result == {"status": "error", "reason": f"http_{status_code}"}
    async with AsyncSessionLocal() as db:
        state = await db.get(CpMailboxState, 1)
    assert state.last_status == "error"
    assert "poufne" not in (state.last_error or "")


@pytest.mark.usefixtures("portal_restored")
async def test_pilot_reads_only_pilot_senders() -> None:
    inside = await make_person()
    outside = await make_person(activated=False)
    await set_portal("pilot")
    reader = FakeMailbox(
        [
            _message("in", inside.email),
            _message("out", outside.email),
            _message("nobody", "nikt@example.com"),
        ],
        {
            "in": [_attachment("a.pdf", PDF)],
            "out": [_attachment("b.pdf", OTHER_PDF)],
            "nobody": [_attachment("c.pdf", b"%PDF-1.4 obcy")],
        },
    )
    result = await _read(reader)
    assert result["created"] == 1
    async with AsyncSessionLocal() as db:
        rows = (await db.scalars(select(CpDocument))).all()
    assert [row.contract_id for row in rows] == [inside.contract_id]


@pytest.mark.usefixtures("portal_all")
async def test_unknown_sender_gets_a_card_to_assign(app_client) -> None:
    reader = FakeMailbox(
        [_message("m1", "ktos@firma.example.com", subject="Faktura 10/2026")],
        {"m1": [_attachment("fv.pdf", PDF)]},
    )
    await _read(reader)
    await _sync()
    cards = await _document_cards()
    assert len(cards) == 1
    assert cards[0].meta["unmatched"] is True
    document_id = cards[0].meta["document_ids"][0]
    admin = await make_user(UserRole.admin)
    refused = await app_client.post(
        f"{STAFF}/documents/{document_id}/accept", headers=staff_headers(admin)
    )
    assert refused.status_code == 409
    assert refused.json()["detail"]["code"] == "unmatched"
    person = await make_person()
    assigned = await app_client.post(
        f"{STAFF}/documents/{document_id}/assign",
        headers=staff_headers(admin),
        json={"contract_id": person.contract_id},
    )
    assert assigned.status_code == 200, assigned.text
    cards = await _document_cards()
    assert [card.contract_id for card in cards] == [person.contract_id]


@pytest.mark.usefixtures("portal_all")
async def test_reader_skips_inline_images_and_bad_files() -> None:
    person = await make_person()
    reader = FakeMailbox(
        [_message("m1", person.email)],
        {
            "m1": [
                _attachment("logo.png", PNG, inline=True),
                _attachment("wirus.exe", b"MZ\x90\x00"),
                {
                    "@odata.type": "#microsoft.graph.itemAttachment",
                    "name": "mail",
                },
                {
                    "@odata.type": "#microsoft.graph.fileAttachment",
                    "name": "x.pdf",
                    "contentBytes": "nie-base64!!",
                },
                _attachment("raport.pdf", PDF),
            ]
        },
    )
    result = await _read(reader)
    assert result["created"] == 1
    assert result["skipped"] == 2


@pytest.mark.usefixtures("portal_all")
async def test_watermark_moves_and_overlaps() -> None:
    person = await make_person()
    received = datetime.now(timezone.utc) - timedelta(hours=1)
    reader = FakeMailbox(
        [_message("m1", person.email, received=received)],
        {"m1": [_attachment("raport.pdf", PDF)]},
    )
    await _read(reader)
    second = FakeMailbox()
    await _read(second)
    assert second.since <= received - mailbox.OVERLAP + timedelta(seconds=1)


@pytest.mark.usefixtures("portal_all")
async def test_failure_does_not_move_watermark_past_the_message(monkeypatch) -> None:
    person = await make_person()
    early = datetime.now(timezone.utc) - timedelta(hours=5)
    late = datetime.now(timezone.utc) - timedelta(hours=1)

    class Broken(FakeMailbox):
        async def attachments(self, message_id):
            raise RuntimeError("awaria")

    reader = Broken(
        [
            _message("m1", person.email, received=early),
            _message("m2", person.email, received=late),
        ]
    )
    result = await _read(reader)
    assert result["status"] == "partial"
    async with AsyncSessionLocal() as db:
        state = await db.get(CpMailboxState, 1)
    assert state.last_seen_received_at is None


@pytest.mark.parametrize(
    ("subject", "name", "expected"),
    [
        ("Raport", "raport.pdf", "report"),
        ("Dokumenty", "timesheet_10.pdf", "report"),
        ("Faktura", "dokument.pdf", "invoice"),
        ("Do opłacenia", "FV 12/2026.pdf", "invoice"),
        ("Raport i faktura", "fv.pdf", "invoice"),
        ("Dzień dobry", "skan.pdf", "invoice"),
    ],
)
def test_classify_kind(subject, name, expected) -> None:
    assert classify_kind(subject, name) == expected


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Raport 10/2026", (2026, 10)),
        ("raport_2026-03.pdf", (2026, 3)),
        ("Faktura październik 2026", (2026, 10)),
        ("faktura pazdziernik 2026", (2026, 10)),
        ("za grudzień 2025", (2025, 12)),
        ("13/2026", None),
        ("bez daty", None),
    ],
)
def test_find_period(text, expected) -> None:
    assert find_period(text) == expected


def test_period_without_a_sign_is_guessed_and_flagged() -> None:
    assert period_for("Raport", "skan.pdf", date(2026, 1, 3)) == (2025, 12, True)
    assert period_for("Raport 10/2026", "skan.pdf", date(2026, 11, 3)) == (
        2026,
        10,
        False,
    )


# ── Sygnał „wystaw fakturę” i stan miesiąca ──────────────────────────────────


@pytest.mark.usefixtures("portal_all")
async def test_accepted_report_tells_consultant_to_issue_invoice(
    app_client, monkeypatch
) -> None:
    mailer = install_mailer(monkeypatch)
    person = await make_person()
    headers = await session_headers(app_client, person)
    uploaded = await _upload(app_client, headers)
    finance = await make_user(UserRole.admin)
    await app_client.post(
        f"{STAFF}/documents/{uploaded.json()['id']}/accept",
        headers=staff_headers(finance),
    )
    assert [mail["to"] for mail in mailer.sent] == [person.email]
    assert "wystawić fakturę" in mailer.sent[0]["subject"]
    months = (await app_client.get(f"{BASE}/finance/overview", headers=headers)).json()[
        "months"
    ]
    year, month = _period()
    row = next(m for m in months if (m["year"], m["month"]) == (year, month))
    assert row["issue_invoice"] is True
    assert row["action"] == "send_invoice"
    assert row["report_label"] == "Raport: zaakceptowany"
    # Bez kwot i stawek.
    assert "rate" not in str(months)


@pytest.mark.usefixtures("portal_restored")
async def test_no_mail_about_decision_when_portal_is_off(
    app_client, monkeypatch
) -> None:
    mailer = install_mailer(monkeypatch)
    await set_portal("all")
    person = await make_person()
    headers = await session_headers(app_client, person)
    uploaded = await _upload(app_client, headers)
    await set_portal("off")
    finance = await make_user(UserRole.admin)
    response = await app_client.post(
        f"{STAFF}/documents/{uploaded.json()['id']}/accept",
        headers=staff_headers(finance),
    )
    assert response.status_code == 200
    assert mailer.sent == []


@pytest.mark.usefixtures("portal_all")
async def test_rejection_goes_back_with_a_reason(app_client, monkeypatch) -> None:
    install_mailer(monkeypatch)
    person = await make_person()
    headers = await session_headers(app_client, person)
    uploaded = await _upload(app_client, headers)
    finance = await make_user(UserRole.admin)
    url = f"{STAFF}/documents/{uploaded.json()['id']}/reject"
    assert (
        await app_client.post(url, headers=staff_headers(finance), json={"reason": ""})
    ).status_code == 422
    done = await app_client.post(
        url, headers=staff_headers(finance), json={"reason": "Brak podpisu klienta"}
    )
    assert done.status_code == 200
    again = await app_client.post(
        url, headers=staff_headers(finance), json={"reason": "Drugi raz"}
    )
    assert again.status_code == 409
    months = (await app_client.get(f"{BASE}/finance/overview", headers=headers)).json()[
        "months"
    ]
    year, month = _period()
    row = next(m for m in months if (m["year"], m["month"]) == (year, month))
    assert row["action"] == "send_report"
    assert row["documents"][0]["reject_reason"] == "Brak podpisu klienta"


def _doc(kind, status, *, doc_id=1) -> CpDocument:
    return CpDocument(
        id=doc_id,
        kind=kind,
        status=status,
        period_year=2026,
        period_month=10,
        channel="portal",
        file_path="x",
        mime="application/pdf",
        size_bytes=1,
        sha256="a",
        created_at=datetime(2026, 11, 2, tzinfo=timezone.utc),
    )


def test_month_row_says_what_is_next() -> None:
    empty = documents.month_row(2026, 10, [])
    assert empty["action"] == "send_report"
    assert empty["report_label"] == "Raport: do wysłania"
    waiting = documents.month_row(2026, 10, [_doc("report", "received")])
    assert waiting["action"] is None
    assert waiting["invoice_label"] == "Faktura: po akceptacji raportu"
    accepted = documents.month_row(2026, 10, [_doc("report", "accepted")])
    assert accepted["action"] == "send_invoice"
    assert accepted["issue_invoice"] is True
    paid = documents.month_row(
        2026,
        10,
        [_doc("report", "accepted"), _doc("invoice", "paid", doc_id=2)],
    )
    assert paid["action"] is None
    assert paid["invoice_label"] == "Faktura: opłacona"
    # Odrzucona wersja nie zasłania przyjętej.
    mixed = documents.month_row(
        2026,
        10,
        [_doc("report", "rejected"), _doc("report", "accepted", doc_id=2)],
    )
    assert mixed["report_label"] == "Raport: zaakceptowany"


@pytest.mark.usefixtures("portal_all")
async def test_only_accepted_invoice_can_be_paid(app_client, monkeypatch) -> None:
    person = await make_person()
    headers = await session_headers(app_client, person)
    invoice = await _upload(app_client, headers, kind="invoice")
    report = await _upload(app_client, headers, kind="report", data=OTHER_PDF)
    finance = await make_user(UserRole.admin)
    staff = staff_headers(finance)
    assert (
        await app_client.post(
            f"{STAFF}/documents/{invoice.json()['id']}/paid", headers=staff
        )
    ).status_code == 409
    await app_client.post(
        f"{STAFF}/documents/{invoice.json()['id']}/accept", headers=staff
    )
    paid = await app_client.post(
        f"{STAFF}/documents/{invoice.json()['id']}/paid", headers=staff
    )
    assert paid.json()["status"] == "paid"
    assert (
        await app_client.post(
            f"{STAFF}/documents/{report.json()['id']}/paid", headers=staff
        )
    ).status_code == 409


# ── Bramki Finansów ──────────────────────────────────────────────────────────


@pytest.mark.usefixtures("portal_all", "care_on", "clean_team", "divisions_restored")
async def test_finance_routes_refuse_other_teams(app_client, monkeypatch) -> None:
    person = await make_person()
    uploaded = await _upload(app_client, await session_headers(app_client, person))
    care_member = await make_member("care")
    finance_member = await make_member("finance")
    url = f"{STAFF}/documents/{uploaded.json()['id']}"
    for method, path, body in (
        ("post", "/accept", None),
        ("post", "/reject", {"reason": "Nie"}),
        ("post", "/paid", None),
        ("post", "/assign", {"contract_id": 1}),
        ("get", "/file", None),
    ):
        response = await getattr(app_client, method)(
            f"{url}{path}",
            headers=staff_headers(care_member),
            **({"json": body} if body else {}),
        )
        assert response.status_code == 403, path
    file_response = await app_client.get(
        f"{url}/file", headers=staff_headers(finance_member)
    )
    assert file_response.status_code == 200
    assert file_response.content == PDF


@pytest.mark.usefixtures("portal_all")
async def test_employee_without_access_gets_nothing(app_client, monkeypatch) -> None:
    outsider = await make_user(UserRole.recruiter)
    response = await app_client.get(
        f"{STAFF}/documents/1/file", headers=staff_headers(outsider)
    )
    assert response.status_code in (403, 404)
