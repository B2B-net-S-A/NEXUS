"""Obieg KEŚU z Jirą na bazie (roadmapa E6.3, Alior). Dane fikcyjne.

Mail z Jiry przekazany przez koordynatora → osoba po temacie (nie po nadawcy)
→ KEŚU z godzinami, stawka MD z kontraktu, „Razem brutto” → przyjęcie →
faktura do klienta czeka na podpis klienta → odpowiedź klienta z jednym,
potem dwoma podpisami → „Do faktury” i zapłata konsultanta. Awaryjnie zapłata
po mailowej akceptacji, gdy podpisujący jest nieobecny.
"""

from __future__ import annotations

import base64
import email.message
import re
import uuid
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from app.core.database import AsyncSessionLocal
from app.core.scheduling import local_now
from app.models.candidate import Candidate
from app.models.client_order import ClientOrder
from app.models.consultant_portal import CpDocument
from app.models.contract import Contract, RateUnit
from app.services.client_settlements import client_invoice, kesu, service
from app.services.client_settlements.service import SettlementError
from app.services.consultant_portal import mailbox
from tests._signed_pdf import signed_by
from app.models.user import UserRole
from tests.care_announcements_seed import make_user
from tests.consultant_portal_seed import (  # noqa: F401  (fixture'y)
    portal_all,
    portal_restored,
)
from tests.test_client_settlements_client_invoice_db import _month, _rules
from tests.test_client_settlements_consultant_db import _module, _restore
from tests.test_client_settlements_service_db import _cleanup, _world

pytestmark = pytest.mark.asyncio

ACTOR = SimpleNamespace(id=None)
KESU = (
    Path(__file__).parent / "fixtures" / "kesu" / "kesu_bez_kosztow.xls"
).read_bytes()
ALIOR_RULES = {
    "proof.month": {"level": "block", "params": {}},
    "proof.name_match": {"level": "warn", "params": {}},
    "fields.md_hours": {"level": "block", "params": {"hours": "8"}},
    "pay.after_client_signature": {"level": "block", "params": {}},
    "pay.mail_accept_fallback": {"level": "warn", "params": {}},
    "cl.after_signed_document": {"level": "block", "params": {}},
    "travel.extra_costs_confirm": {"level": "warn", "params": {}},
}


def _kesu_for(month: str, name: str) -> bytes:
    year, mon = month.split("-")
    text = KESU.decode("utf-8")
    text = re.sub(
        r'(Miesiąc:</Data></Cell>\s*<Cell[^>]*><Data ss:Type="Number">)\d+',
        rf"\g<1>{int(mon)}",
        text,
    )
    text = text.replace("Rok:    2026", f"Rok:    {year}")
    text = text.replace("Imię i nazwisko: Kozłowska Ewa", f"Imię i nazwisko: {name}")
    return text.encode("utf-8")


class FakeMailbox:
    def __init__(self, messages: list[dict], files: dict, mimes: dict) -> None:
        self.messages, self.files, self.mimes = messages, files, mimes

    async def list_messages(self, since):  # noqa: ANN001, ANN201
        return self.messages

    async def attachments(self, message_id):  # noqa: ANN001, ANN201
        return self.files.get(message_id, [])

    async def mime(self, message_id):  # noqa: ANN001, ANN201
        return self.mimes.get(message_id)


def _attachment(name: str, data: bytes) -> dict:
    return {
        "@odata.type": "#microsoft.graph.fileAttachment",
        "name": name,
        "isInline": False,
        "contentBytes": base64.b64encode(data).decode(),
    }


def _message(message_id: str, sender: str, subject: str) -> dict:
    return {
        "id": message_id,
        "subject": subject,
        "hasAttachments": True,
        "from": {"emailAddress": {"address": sender}},
        "receivedDateTime": datetime.now(timezone.utc)
        .isoformat()
        .replace("+00:00", "Z"),
    }


def _jira_eml(subject: str, person: str, month: str, xls: bytes) -> bytes:
    year, mon = month.split("-")
    message = email.message.EmailMessage()
    message["From"] = "koordynator@dostawca.example"
    message["To"] = "rozliczenia@dostawca.example"
    message["Subject"] = subject
    message["Date"] = "Tue, 03 Nov 2026 13:09:00 +0100"
    message["Message-ID"] = f"<{uuid.uuid4().hex}@dostawca.example>"
    message.set_content(
        "-----Original Message-----\n"
        "From: jira@klient.example\n"
        "To: Osoba@klient.example; Pawel.Opiekun@klient.example\n"
        f"Subject: {subject}\n\n"
        f"Rozliczenie kontraktora {person} za miesiąc {mon}-{year} zostało "
        "zaakceptowane przez Paweł Opiekun w dniu 03/11/2026 13:08:28.\n"
    )
    message.add_attachment(
        xls, maintype="application", subtype="octet-stream", filename="k.xls"
    )
    return message.as_bytes()


async def _alior_person(client_id: int, contract_id: int, line_id: int) -> str:
    suffix = "".join(c for c in uuid.uuid4().hex if c.isalpha())[:6] or "abc"
    first, last = "Ewa", f"Kozłowska{suffix}"
    async with AsyncSessionLocal() as db:
        contract = await db.get(Contract, contract_id)
        candidate = await db.get(Candidate, contract.candidate_id)
        candidate.name, candidate.lastname = first, last
        # Stawka klienta godzinowa (fikcyjna): 143,21 zł/h × 8 h = 1 145,68 zł/MD.
        contract.rate_client = Decimal("143.21")
        contract.rate_unit = RateUnit.hourly
        contract.rate_client_currency = "PLN"
        line = await db.get(ClientOrder, line_id)
        line.md_rate_revenue = Decimal("1145.68")
        line.md_rate_cost = Decimal("720")  # 90 zł/h × 8
        await db.commit()
    return f"{first} {last}"


async def _read(reader: FakeMailbox) -> dict:
    async with AsyncSessionLocal() as db:
        result = await mailbox.run_once(db, mailbox=reader)
        await db.commit()
    return result


@pytest.mark.usefixtures("portal_all")
async def test_obieg_keszu_z_jiry_do_faktury_i_zaplaty(tmp_path, monkeypatch) -> None:
    from app.services import storage_service

    monkeypatch.setattr(storage_service, "STORAGE_ROOT", tmp_path)
    monkeypatch.setattr(mailbox, "mailbox_upn", lambda: "rozliczenia@dostawca.example")
    client_id, contract_id, line_id = await _world(md_total="60")
    month = _month(-1)
    previous = await _module(True)
    try:
        person = await _alior_person(client_id, contract_id, line_id)
        await _rules(client_id, ALIOR_RULES)
        year, mon = month.split("-")
        run = uuid.uuid4().hex[:8]
        jira_id, re_one, re_two = f"jira-{run}", f"re1-{run}", f"re2-{run}"
        subject = (
            f"FW: [ALIOR JIRA] Rozliczenie kontraktora {person} za miesiąc "
            f"{mon}-{year} zaakceptowane przez opiekuna"
        )
        sheet = _kesu_for(month, f"{person.split()[1]} {person.split()[0]}")
        # Ten sam temat od obcego adresu: osoby z tematu nie przypisujemy.
        forged = f"forged-{run}"
        await _read(
            FakeMailbox(
                [_message(forged, "ktos@obcy.example", subject)],
                {forged: [_attachment("10-2026-ei1.xls", sheet)]},
                {forged: _jira_eml(subject, person, month, sheet)},
            )
        )
        async with AsyncSessionLocal() as db:
            stray = (
                await db.scalars(
                    select(CpDocument).where(CpDocument.graph_message_id == forged)
                )
            ).all()
            assert stray and {d.contract_id for d in stray} == {None}

        coordinator = await make_user(UserRole.recruiter, name="Koordynator")
        reader = FakeMailbox(
            # Nadawcą jest koordynator (konto NEXUS-a), nie konsultant: osoba z tematu.
            [_message(jira_id, coordinator.email.lower(), subject)],
            {jira_id: [_attachment("10-2026-ei1.xls", sheet)]},
            {jira_id: _jira_eml(subject, person, month, sheet)},
        )
        result = await _read(reader)
        assert result["created"] == 2, result
        async with AsyncSessionLocal() as db:
            docs = (
                await db.scalars(
                    select(CpDocument).where(CpDocument.graph_message_id == jira_id)
                )
            ).all()
            assert {d.contract_id for d in docs} == {contract_id}
            assert {(d.kind, d.mime) for d in docs} == {
                ("report", "message/rfc822"),
                ("report", "application/vnd.ms-excel"),
            }
            view = await service.month_view(db, client_id, month, amounts=True)
            row = next(r for r in view["rows"] if r["contract_id"] == contract_id)
            assert row["md_regular"] == "20.000"  # 160 h / 8
            assert row["kesu"]["state"] == kesu.TO_COMPANY
            assert row["kesu"]["approver"] == "Paweł Opiekun"
            assert row["status"] == "ok", row

            card = await service.detail(db, contract_id, month, amounts=True)
            block = card["kesu"]
            assert block["rate_md"] == "1145.68"
            assert block["total_gross"] == "28183.73"
            assert block["rate_differs"] is False
            assert block["mail"]["to"] == "Pawel.Opiekun@klient.example"
            assert block["payment"]["can_pay"] is False
            # Bez dostępu do kwot: stan tak, stawki i kwoty nie.
            hidden = await service.detail(db, contract_id, month, amounts=False)
            assert hidden["kesu"]["total_gross"] is None
            assert hidden["kesu"]["state"] == kesu.TO_COMPANY

            await service.accept(db, contract_id, month, actor=ACTOR, now=local_now())
            await db.commit()

        async with AsyncSessionLocal() as db:
            invoice = await client_invoice.invoice_month(
                db, client_id, month, amounts=True
            )
            item = next(r for r in invoice["rows"] if r["contract_id"] == contract_id)
            assert item["state"] == "awaiting_signature"
            assert item["net"] == "22913.60"  # 20 MD × 1 145,68
            # Przyjęcie: koszt = MD × stawka kosztowa = faktura kontraktora.
            accepted = await service._settlement(db, contract_id, month)
            assert accepted.amount_cost == Decimal("14400.00")

        at = datetime(2026, 11, 4, 13, 16, tzinfo=timezone.utc)
        ours = await signed_by(("Spółka", at))
        reply = f"RE: KEŚU {kesu._MONTHS_PL[int(mon) - 1]} - {person}"
        await _read(
            FakeMailbox(
                [_message(re_one, "opiekun@klient.example", reply)],
                {re_one: [_attachment(f"KESU {mon}.{year}-sig.pdf", ours)]},
                {},
            )
        )
        async with AsyncSessionLocal() as db:
            view = await service.month_view(db, client_id, month, amounts=True)
            row = next(r for r in view["rows"] if r["contract_id"] == contract_id)
            assert row["kesu"]["state"] == kesu.AWAITING_CLIENT
            assert row["kesu"]["state_label"] == "Czeka na podpis klienta"
            assert row["status"] == "accepted"
            assert row["client_invoice"] == "awaiting_signature"

            # Podpisujący nieobecny: Finanse płacą po mailowej akceptacji.
            await service.pay_on_mail(
                db, contract_id, month, actor=ACTOR, now=local_now()
            )
            await db.commit()
        async with AsyncSessionLocal() as db:
            card = await service.detail(db, contract_id, month, amounts=True)
            assert card["kesu"]["payment"]["can_pay"] is True
            assert card["kesu"]["payment"]["on_mail"] is True
            assert card["kesu"]["invoice_waits"] is True

        # Odpowiedź z innej domeny niż opiekuna z Jiry: karta do ręcznego przypisania.
        both = await signed_by(("Spółka", at), ("Klient", at))
        fake_reply = f"fake-{run}"
        await _read(
            FakeMailbox(
                [_message(fake_reply, "ktos@obcy.example", reply)],
                {fake_reply: [_attachment(f"KESU {mon}.{year}-sig.pdf", both)]},
                {},
            )
        )
        async with AsyncSessionLocal() as db:
            view = await service.month_view(db, client_id, month, amounts=True)
            row = next(r for r in view["rows"] if r["contract_id"] == contract_id)
            assert row["kesu"]["state"] == kesu.AWAITING_CLIENT

        await _read(
            FakeMailbox(
                [_message(re_two, "inna.osoba@klient.example", reply)],
                {re_two: [_attachment(f"KESU {mon}.{year}-sig.pdf", both)]},
                {},
            )
        )
        async with AsyncSessionLocal() as db:
            card = await service.detail(db, contract_id, month, amounts=True)
            assert card["kesu"]["state"] == kesu.SIGNED
            assert card["kesu"]["payment"]["state"] == "ok"
            invoice = await client_invoice.invoice_month(
                db, client_id, month, amounts=True
            )
            item = next(r for r in invoice["rows"] if r["contract_id"] == contract_id)
            assert item["state"] == "ready"
            with pytest.raises(SettlementError):
                await service.pay_on_mail(
                    db, contract_id, month, actor=ACTOR, now=local_now()
                )

            monkeypatch.setattr(kesu, "render_pdf", lambda html: _one_page_pdf())
            content, name = await service.kesu_package(db, contract_id, month)
            assert content.startswith(b"%PDF")
            assert name.startswith("KESU_Ewa_Kozlowska")
    finally:
        await _restore(previous)
        await _cleanup(client_id)


def _one_page_pdf() -> bytes:
    from tests.test_client_settlements_kesu import _text_pdf

    return _text_pdf("KESU")
