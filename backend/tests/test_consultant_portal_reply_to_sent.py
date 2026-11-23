"""Odpowiedź klienta bez pliku na nasze zestawienie godzin z Wysłanych (próba IX–X 2026).

Koordynator wysyła z adresu rozliczeń „Zestawienie godzin 2026.09 … - Imię Nazwisko”
z plikiem godzin do klienta, a klient odpisuje samym „Potwierdzam zestawienie”. Plik
leży tylko w naszym mailu wychodzącym, a odpowiedź przychodzi z obcego adresu, więc
czytnik dawał „nikt”. Teraz odpowiedź prowadzi do naszego maila z Wysłanych (ten sam
temat, domena adresata, do 45 dni wcześniej). Osobę wskazuje temat NASZEGO maila: jedna
osoba albo nikt. Decyzja Artura z 23.11.2026. Osoby, domeny i maile fikcyjne.
"""

from __future__ import annotations

import base64
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage

import pytest
import pytest_asyncio
from sqlalchemy import select

from app.core.database import AsyncSessionLocal
from app.models.candidate import Candidate
from app.models.consultant_portal import CpDocument, CpMailboxState
from app.services import storage_service
from app.services.consultant_portal import mailbox
from tests.consultant_portal_seed import (  # noqa: F401  (fixture'y)
    make_person,
    portal_restored,
    set_portal,
)

pytestmark = pytest.mark.asyncio

SETTLEMENTS = "rozliczenia@firma.example.com"
CLIENT = "bank-cib.example.com"
PDF = b"%PDF-1.4 fikcyjne zestawienie godzin"


def _logo() -> bytes:
    from io import BytesIO

    from PIL import Image

    out = BytesIO()
    Image.new("RGB", (140, 40), (0, 80, 160)).save(out, "PNG")
    return out.getvalue()


# Logo stopki Outlooka (mały obrazek ``image00N``).
PNG = _logo()
REPLIED = datetime(2026, 10, 5, 10, 16, tzinfo=timezone.utc)


@pytest_asyncio.fixture(autouse=True)
async def _clean():
    async def wipe() -> None:
        async with AsyncSessionLocal() as db:
            for row in (await db.scalars(select(CpDocument))).all():
                await db.delete(row)
            state = await db.get(CpMailboxState, 1)
            if state is not None:
                await db.delete(state)
            await db.commit()

    await wipe()
    yield
    await wipe()


@pytest.fixture(autouse=True)
def _setup(tmp_path, monkeypatch):
    from app.core.config import settings
    from app.services.consultant_portal import identity

    monkeypatch.setattr(storage_service, "STORAGE_ROOT", tmp_path)
    monkeypatch.setattr(
        identity, "_company_domains", lambda: frozenset({"firma.example.com"})
    )
    # Jedna skrzynka wsparcie@ (E8): odpowiedź bez pliku router oddaje sprawom.
    monkeypatch.setattr(
        settings, "CONSULTANT_PORTAL_SETTLEMENTS_MAILBOX", "wsparcie@firma.example.com"
    )
    monkeypatch.setattr(
        settings, "ADMIN_CASES_M365_MAILBOX", "wsparcie@firma.example.com"
    )
    monkeypatch.setattr(
        settings, "CONSULTANT_PORTAL_SETTLEMENTS_ADDRESSES", SETTLEMENTS
    )


@pytest_asyncio.fixture
async def internal(portal_restored):  # noqa: F811  (fixture z seeda)
    await set_portal("internal")
    yield


class SentMailbox:
    def __init__(self, inbox, sent, files, raw) -> None:
        self.inbox, self.sent, self.files, self.raw = inbox, sent, files, raw
        self.sent_calls = 0

    async def list_messages(self, since):
        return self.inbox

    async def sent_messages(self, since):
        self.sent_calls += 1
        return [m for m in self.sent if mailbox._parse_time(m["sentDateTime"]) >= since]

    async def attachments(self, message_id):
        return self.files.get(message_id, [])

    async def mime(self, message_id):
        return self.raw.get(message_id)


async def _name(person) -> str:
    async with AsyncSessionLocal() as db:
        candidate = await db.get(Candidate, person.candidate_id)
    return f"{candidate.name} {candidate.lastname}"


def _address(address: str) -> dict:
    return {"emailAddress": {"address": address}}


def _sent(subject: str, *, to: str = f"kierownik@{CLIENT}", when=None) -> dict:
    moment = when or REPLIED - timedelta(days=4)
    return {
        "id": "s1",
        "subject": subject,
        "from": _address(SETTLEMENTS),
        "toRecipients": [_address(to)],
        "ccRecipients": [],
        "sentDateTime": moment.isoformat(),
        "hasAttachments": True,
        "conversationId": "c1",
    }


def _reply(subject: str, *, sender: str = f"szef@{CLIENT}") -> dict:
    return {
        "id": "r1",
        "subject": subject,
        "from": _address(sender),
        "toRecipients": [_address(SETTLEMENTS)],
        "receivedDateTime": REPLIED.isoformat(),
        "hasAttachments": False,
        "conversationId": "c2",
    }


def _reply_eml(sender: str, subject: str, text: str) -> bytes:
    message = EmailMessage()
    message["From"] = sender
    message["To"] = SETTLEMENTS
    message["Subject"] = subject
    message.set_content(text)
    return message.as_bytes()


def _file(name: str, data: bytes = PDF) -> dict:
    return {
        "@odata.type": "#microsoft.graph.fileAttachment",
        "name": name,
        "isInline": False,
        "contentBytes": base64.b64encode(data).decode(),
    }


def _quoted(subject: str, accept: str) -> str:
    # Jak w próbie: akceptację przekazuje dalej przełożony („FYI”), a pod nią cytat
    # naszego maila z adresu rozliczeń.
    return (
        "FYI\n\nFrom: Kierownik <kierownik@" + CLIENT + ">\nSent: 05 October 2026\n"
        f"Subject: RE: [EXTERNAL] {subject}\n\n{accept}\n\n"
        f"From: {SETTLEMENTS} <{SETTLEMENTS}>\nSent: 01 October 2026\n"
        f"Subject: [EXTERNAL] {subject}\n\nProśba o akceptację załączonego czasu pracy.\n"
    )


async def _run(reader) -> dict:
    async with AsyncSessionLocal() as db:
        result = await mailbox.run_once(
            db, mailbox=reader, now=REPLIED + timedelta(hours=1)
        )
        await db.commit()
    return result


async def _documents() -> list[CpDocument]:
    async with AsyncSessionLocal() as db:
        return list(
            (await db.scalars(select(CpDocument).order_by(CpDocument.id))).all()
        )


def _reader(
    subject: str,
    *,
    reply_subject=None,
    sender=None,
    accept="Potwierdzam godziny pracy.",
    sent=None,
):
    reply_subject = reply_subject or f"RE: [EXTERNAL] {subject}"
    sender = sender or f"szef@{CLIENT}"
    return SentMailbox(
        [_reply(reply_subject, sender=sender)],
        [sent or _sent(subject)],
        # Obrazek stopki Outlooka w naszym mailu nie jest dowodem (powtórka IX: 3 pliki).
        {"s1": [_file("202609_worksheet.pdf"), _file("image001.png", PNG)]},
        {"r1": _reply_eml(sender, reply_subject, _quoted(subject, accept))},
    )


@pytest.mark.usefixtures("internal")
async def test_client_reply_takes_file_from_our_sent_mail() -> None:
    person = await make_person(activated=False)
    subject = f"Zestawienie godzin 2026.09 Firma S.A. - {await _name(person)}"
    reader = _reader(subject)
    result = await _run(reader)
    assert result["created"] == 2
    docs = await _documents()
    assert {(d.graph_message_id, d.contract_id, d.kind) for d in docs} == {
        ("s1", person.contract_id, "report"),
        ("r1", person.contract_id, "report"),
    }
    assert {(d.period_year, d.period_month, d.period_guessed) for d in docs} == {
        (2026, 9, False)
    }
    assert {d.file_name for d in docs} == {
        "202609_worksheet.pdf",
        f"RE: [EXTERNAL] {subject}.eml",
    }
    # Powtórka (zakładka 2 h) nie dubluje dokumentów.
    assert (await _run(reader))["created"] == 0


@pytest.mark.usefixtures("internal")
async def test_reply_from_other_domain_than_our_recipient_is_ignored() -> None:
    person = await make_person(activated=False)
    subject = f"Zestawienie godzin 2026.09 Firma S.A. - {await _name(person)}"
    await _run(_reader(subject, sender="ktos@obcy.example.com"))
    assert await _documents() == []


@pytest.mark.usefixtures("internal")
async def test_reply_without_acceptance_stores_nothing() -> None:
    person = await make_person(activated=False)
    subject = f"Zestawienie godzin 2026.09 Firma S.A. - {await _name(person)}"
    await _run(_reader(subject, accept="Proszę o korektę, brakuje dwóch dni."))
    assert await _documents() == []


@pytest.mark.usefixtures("internal")
async def test_reply_to_other_month_does_not_match() -> None:
    person = await make_person(activated=False)
    name = await _name(person)
    await _run(
        _reader(
            f"Zestawienie godzin 2026.09 Firma S.A. - {name}",
            reply_subject=f"RE: Zestawienie godzin 2026.08 Firma S.A. - {name}",
        )
    )
    assert await _documents() == []


@pytest.mark.usefixtures("internal")
async def test_our_sent_mail_older_than_window_does_not_match() -> None:
    person = await make_person(activated=False)
    subject = f"Zestawienie godzin 2026.09 Firma S.A. - {await _name(person)}"
    old = _sent(subject, when=REPLIED - timedelta(days=60))
    await _run(_reader(subject, sent=old))
    assert await _documents() == []


@pytest.mark.usefixtures("internal")
async def test_our_subject_naming_two_people_stores_nothing() -> None:
    first, second = (
        await make_person(activated=False),
        await make_person(activated=False),
    )
    subject = (
        f"Zestawienie godzin 2026.09 - {await _name(first)}, {await _name(second)}"
    )
    await _run(_reader(subject))
    assert await _documents() == []


@pytest.mark.usefixtures("internal")
async def test_name_in_client_subject_alone_does_not_point_to_a_person() -> None:
    """Bez naszego maila w Wysłanych temat obcego nadawcy nikogo nie wskazuje."""
    person = await make_person(activated=False)
    subject = f"Zestawienie godzin 2026.09 Firma S.A. - {await _name(person)}"
    reader = _reader(subject)
    reader.sent = []
    await _run(reader)
    assert await _documents() == []


@pytest.mark.usefixtures("portal_restored")
async def test_pilot_mode_does_not_look_into_sent_items() -> None:
    await set_portal("pilot")
    person = await make_person(activated=False)
    subject = f"Zestawienie godzin 2026.09 Firma S.A. - {await _name(person)}"
    reader = _reader(subject)
    await _run(reader)
    assert reader.sent_calls == 0
    assert await _documents() == []
