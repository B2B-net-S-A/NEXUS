"""Bank Pocztowy (E6.5) na bazie: KCP → wysyłka do klienta → akceptacja → faktura.
Dane fikcyjne.

KCP osoby rozliczamy bez czekania na klienta; faktura do klienta czeka na jego
akceptację („Czeka na klienta”). Odpowiedź banku z jego domeny, wgrana bez
kontraktu, akceptuje osoby wysłane przed nią; opis pozycji idzie ze wzoru reguły.
"""

from __future__ import annotations

import base64
import io
import zipfile
from datetime import timedelta
from decimal import Decimal
from email.utils import format_datetime
from types import SimpleNamespace

import pytest
from sqlalchemy import delete, select

from app.core.database import AsyncSessionLocal
from app.core.scheduling import business_today, local_now
from app.models.client_order import ClientOrder
from app.models.client_settlement import ClientSettlementRuleSet
from app.models.consultant_portal import CpDocument
from app.models.contract import RateUnit
from app.services.client_settlements import (
    client_acceptance,
    client_invoice,
    kcp,
    service,
)
from app.services.client_settlements.service import SettlementError
from tests.care_announcements_seed import care_on, tag  # noqa: F401  (fixture'y)
from tests.consultant_portal_seed import (  # noqa: F401  (fixture'y)
    make_person,
    portal_all,
    portal_restored,
)
from tests.test_client_settlements_client_invoice_db import _month, _rules
from tests.test_client_settlements_consultant_db import _module, _restore
from tests.test_client_settlements_kcp import _card_rows, _workbook
from tests.test_client_settlements_pko_velo_db import _settlement, _store
from tests.test_client_settlements_service_db import _cleanup, _world

pytestmark = pytest.mark.asyncio

ACTOR = SimpleNamespace(id=None)
ORDER = "7/2026/ZAM/B2B"


def _reply(month: str, body: str, *, sender: str = "body@bank.example") -> bytes:
    year, mon = (int(x) for x in month.split("-"))
    word = kcp.MONTHS_PL[mon - 1].lower()
    when = format_datetime(local_now() + timedelta(hours=1))
    return (
        f"From: Body <{sender}>\r\nTo: rozliczenia@b2b.example\r\n"
        f"Subject: RE: KCP B2Bnetwork {word} {year}\r\n"
        f"Date: {when}\r\nMIME-Version: 1.0\r\n"
        "Content-Type: text/plain; charset=utf-8\r\n\r\n"
        f"{body}\r\n\r\nOd: Koordynatorka <k@b2b.example>\r\nProśba o akceptację.\r\n"
    ).encode()


async def test_kcp_wysylka_akceptacja_banku_i_faktura(tmp_path, monkeypatch) -> None:
    from app.services import storage_service

    monkeypatch.setattr(storage_service, "STORAGE_ROOT", tmp_path)
    client_id, contract_id, line_id = await _world()
    month = _month(-1)
    year, mon = (int(x) for x in month.split("-"))
    previous = await _module(True)
    try:
        async with AsyncSessionLocal() as db:
            line = await db.get(ClientOrder, line_id)
            line.title = ORDER
            line.rate_unit = RateUnit.hourly
            line.rate_client = Decimal("100")
            line.rate_candidate = Decimal("60")
            line.md_total = line.md_remaining = None
            line.md_input_mode = line.md_input_value = None
            line.md_rate_cost = line.md_rate_revenue = None
            await db.commit()
        await _rules(
            client_id,
            {
                "proof.month": {"level": "block", "params": {}},
                "proof.name_match": {"level": "off", "params": {}},
                "fields.md_hours": {"level": "block", "params": {"hours": "8"}},
                "cl.client_acceptance": {
                    "level": "warn",
                    "params": {"email": "body@bank.example", "subject": ""},
                },
                "cl.after_signed_document": {"level": "block", "params": {}},
                "cl.item_name": {
                    "level": "warn",
                    "params": {
                        "template": "Prace informatyczne zgodnie z zamówieniem "
                        "{zamowienie}, {osoba}"
                    },
                },
            },
        )
        card = _workbook(
            {"KARTA": _card_rows(month=kcp.MONTHS_PL[mon - 1], year=str(year))}
        )
        await _store(contract_id, month, card, "KCP.xlsx")
        s = await _settlement(contract_id, month)
        assert s.md_regular == Decimal("3.000")
        assert not any(
            c.get("state") == "fail"
            for g in s.checks
            if isinstance(g, dict)
            for c in g.get("checks") or []
        )

        async with AsyncSessionLocal() as db:
            view = await client_acceptance.month_view(db, client_id, month)
            assert view["enabled"] and view["counts"]["to_send"] == 1
            assert view["email"] == "body@bank.example"
            with pytest.raises(SettlementError, match="najpierw wyślij"):
                await client_acceptance.accept(
                    db, client_id, month, [contract_id], actor=ACTOR, now=local_now()
                )
            package, count = await client_acceptance.package(db, client_id, month)
            assert count == 1
            names = zipfile.ZipFile(io.BytesIO(package)).namelist()
            assert len(names) == 1 and names[0].endswith(".pdf")
            assert (
                await client_acceptance.mark_sent(
                    db, client_id, month, [contract_id], actor=ACTOR, now=local_now()
                )
                == 1
            )
            # Przeliczenie (nowy plik, poprawka MD) nie gubi wysyłki.
            s = await service._settlement(db, contract_id, month, for_update=True)
            await service.recompute_and_store(db, s)
            assert client_acceptance.status(s) == client_acceptance.SENT
            # Kontraktora rozliczamy bez czekania na klienta.
            await service.accept(db, contract_id, month, actor=ACTOR, now=local_now())
            await db.commit()

        async with AsyncSessionLocal() as db:
            rows = (await service.month_view(db, client_id, month, amounts=True))[
                "rows"
            ]
            assert rows[0]["client_acceptance"]["state"] == "sent"
            assert rows[0]["client_invoice"] == "awaiting_client"
            invoice = await client_invoice.invoice_month(
                db, client_id, month, amounts=True
            )
            row = invoice["rows"][0]
            assert row["state"] == "awaiting_client"
            # Numer z wiersza miesiąca (u BP z tytułu linii, tu z grupy zamówienia).
            assert row["order_number"]
            assert row["positions"][0]["name"] == (
                f"Prace informatyczne zgodnie z zamówieniem {row['order_number']}, "
                f"{row['person']}"
            )

        # Odpowiedź z obcej domeny i odpowiedź bez akceptacji nic nie zmieniają.
        await _store(
            None,
            month,
            _reply(month, "Akceptuję.", sender="ktos@inny.example"),
            "a.eml",
        )
        await _store(None, month, _reply(month, "W KCP jest błąd w dniu 5."), "b.eml")
        assert client_acceptance.status(await _settlement(contract_id, month)) == "sent"

        await _store(
            None,
            month,
            _reply(month, "Dzień dobry,\n\nAkceptuję nadesłane KCP."),
            "c.eml",
        )
        s = await _settlement(contract_id, month)
        assert client_acceptance.status(s) == client_acceptance.ACCEPTED
        assert client_acceptance.state_of(s)["reply"] == "Akceptuję nadesłane KCP."
        async with AsyncSessionLocal() as db:
            invoice = await client_invoice.invoice_month(
                db, client_id, month, amounts=True
            )
            assert invoice["rows"][0]["state"] == "ready"
            # 3 MD × 8 h × 100 zł.
            assert invoice["rows"][0]["net"] == "2400.00"
            detail = await service.detail(db, contract_id, month, amounts=True)
            group = next(
                g for g in detail["checks"] if g["title"] == "Akceptacja klienta"
            )
            assert [c["state"] for c in group["checks"]] == ["ok", "ok"]
            assert detail["kcp_pdf"] is True
    finally:
        await _restore(previous)
        await _cleanup(client_id)


async def test_brakujaca_osoba_z_odpowiedzi_nie_jest_akceptowana(
    tmp_path, monkeypatch
) -> None:
    from app.services import storage_service

    monkeypatch.setattr(storage_service, "STORAGE_ROOT", tmp_path)
    client_id, contract_id, _line_id = await _world()
    month = _month(-1)
    year, mon = (int(x) for x in month.split("-"))
    previous = await _module(True)
    try:
        await _rules(
            client_id,
            {
                "cl.client_acceptance": {
                    "level": "warn",
                    "params": {"email": "body@bank.example"},
                },
            },
        )
        card = _workbook(
            {"KARTA": _card_rows(month=kcp.MONTHS_PL[mon - 1], year=str(year))}
        )
        await _store(contract_id, month, card, "KCP.xlsx")
        async with AsyncSessionLocal() as db:
            person = (await service._contract(db, contract_id)).name
            await client_acceptance.mark_sent(
                db, client_id, month, [contract_id], actor=ACTOR, now=local_now()
            )
            await db.commit()
        await _store(
            None,
            month,
            _reply(
                month,
                f"Akceptuję nadesłane KCP.\n\nProszę o dosłanie brakujących:\n* {person}",
            ),
            "r.eml",
        )
        assert client_acceptance.status(await _settlement(contract_id, month)) == "sent"
        async with AsyncSessionLocal() as db:
            assert (
                await client_acceptance.accept(
                    db, client_id, month, [contract_id], actor=ACTOR, now=local_now()
                )
                == 1
            )
            await db.commit()
        s = await _settlement(contract_id, month)
        assert client_acceptance.state_of(s)["source"] == "manual"
    finally:
        await _restore(previous)
        await _cleanup(client_id)


class _Mailbox:
    def __init__(self, content: bytes) -> None:
        self.content = content

    async def mime(self, message_id: str) -> bytes:
        return self.content


async def test_odpowiedz_banku_na_rozliczenia_zapisuje_sie_i_akceptuje(
    tmp_path, monkeypatch
) -> None:
    """Czytnik rozliczenia@: mail z domeny klienta z regułą akceptacji zapisuje się
    bez kontraktu tylko wtedy, gdy akceptuje; inny nadawca idzie zwykłą ścieżką."""

    from app.services import storage_service
    from app.services.consultant_portal import mailbox

    monkeypatch.setattr(storage_service, "STORAGE_ROOT", tmp_path)
    client_id, contract_id, _line_id = await _world()
    month = _month(-1)
    year, mon = (int(x) for x in month.split("-"))
    previous = await _module(True)
    try:
        await _rules(
            client_id,
            {
                "cl.client_acceptance": {
                    "level": "warn",
                    "params": {"email": "body@bank.example"},
                },
            },
        )
        card = _workbook(
            {"KARTA": _card_rows(month=kcp.MONTHS_PL[mon - 1], year=str(year))}
        )
        await _store(contract_id, month, card, "KCP.xlsx")
        async with AsyncSessionLocal() as db:
            await client_acceptance.mark_sent(
                db, client_id, month, [contract_id], actor=ACTOR, now=local_now()
            )
            await db.commit()
        word = kcp.MONTHS_PL[mon - 1].lower()

        def message(sender: str) -> dict:
            return {
                "id": f"msg-{sender}",
                "subject": f"RE: KCP B2Bnetwork {word} {year}",
                "from": {"emailAddress": {"address": sender}},
                "receivedDateTime": local_now().isoformat(),
                "hasAttachments": False,
            }

        async with AsyncSessionLocal() as db:
            other = await mailbox._store_client_reply(
                db,
                _Mailbox(b""),
                message("ktos@inny.example"),
                subject=message("x")["subject"],
                now=local_now(),
            )
            assert other is None
            refused = await mailbox._store_client_reply(
                db,
                _Mailbox(_reply(month, "W KCP jest błąd.")),
                message("body@bank.example"),
                subject=message("x")["subject"],
                now=local_now(),
            )
            # Bez akceptacji: zwykła ścieżka, nie koniec czytania maila.
            assert refused is None
            made = await mailbox._store_client_reply(
                db,
                _Mailbox(_reply(month, "Potwierdzam.")),
                message("body@bank.example"),
                subject=message("x")["subject"],
                now=local_now(),
            )
            assert made == 1
            await db.commit()
        s = await _settlement(contract_id, month)
        assert client_acceptance.status(s) == client_acceptance.ACCEPTED
    finally:
        await _restore(previous)
        await _cleanup(client_id)


class _MailboxWithFiles(_Mailbox):
    def __init__(self, content: bytes, files: list[dict]) -> None:
        super().__init__(content)
        self.files = files

    async def attachments(self, message_id: str) -> list[dict]:
        return self.files


@pytest.mark.usefixtures("care_on", "portal_all")
async def test_mail_konsultanta_z_domeny_banku_bez_akceptacji_idzie_zwykla_sciezka(
    tmp_path, monkeypatch
) -> None:
    """Konsultant ze skrzynką w domenie klienta z ``cl.client_acceptance`` wysyła KCP.
    ``_store_client_reply`` nie uznaje maila za akceptację, więc czytnik czyta go
    dalej jak każdy inny; dotąd kończył na ``(0, 0)`` i plik przepadał bez śladu."""

    from app.services import storage_service
    from app.services.consultant_portal import mailbox, portal_settings

    monkeypatch.setattr(storage_service, "STORAGE_ROOT", tmp_path)
    domain = f"bank-{tag()}.example"
    person = await make_person(email=f"konsultant.{tag()}@{domain}")
    month = _month(-1)
    year, mon = (int(x) for x in month.split("-"))
    previous = await _module(True)
    async with AsyncSessionLocal() as db:
        db.add(
            ClientSettlementRuleSet(
                client_id=person.client_id,
                effective_from="2020-01",
                rules={
                    "cl.client_acceptance": {
                        "level": "warn",
                        "params": {"email": f"body@{domain}"},
                    },
                },
            )
        )
        await db.commit()
    try:
        word = kcp.MONTHS_PL[mon - 1].lower()
        message = {
            "id": f"msg-kcp-{tag()}",
            "subject": f"KCP {word} {year}",
            "from": {"emailAddress": {"address": person.email}},
            "receivedDateTime": local_now().isoformat(),
            "hasAttachments": True,
        }
        reader = _MailboxWithFiles(
            _reply(month, "W załączniku przesyłam KCP.", sender=person.email),
            [
                {
                    "@odata.type": "#microsoft.graph.fileAttachment",
                    "name": "KCP.pdf",
                    "isInline": False,
                    "contentBytes": base64.b64encode(b"%PDF-1.4 fikcyjne KCP").decode(),
                }
            ],
        )
        async with AsyncSessionLocal() as db:
            assert await client_acceptance.is_client_domain(db, person.email, month)
            made, ignored = await mailbox._ingest_message(
                db,
                reader,
                message,
                state=await portal_settings.load(db),
                today=business_today(),
                now=local_now(),
            )
            await db.commit()
        assert (made, ignored) == (1, 0)
        async with AsyncSessionLocal() as db:
            names = (
                await db.scalars(
                    select(CpDocument.file_name).where(
                        CpDocument.contract_id == person.contract_id
                    )
                )
            ).all()
        assert names == ["KCP.pdf"]
    finally:
        async with AsyncSessionLocal() as db:
            await db.execute(
                delete(ClientSettlementRuleSet).where(
                    ClientSettlementRuleSet.client_id == person.client_id
                )
            )
            await db.commit()
        await _restore(previous)


async def test_wgranie_odpowiedzi_klienta_przez_api(
    app_client, app_auth_headers, tmp_path, monkeypatch
) -> None:
    """„Wgraj odpowiedź klienta”: zapis pliku sam odczytuje akceptację, więc trasa
    nie może drugi raz dostać „0 osób” i cofnąć zapisu (18.11, staging)."""

    from app.services import storage_service

    monkeypatch.setattr(storage_service, "STORAGE_ROOT", tmp_path)
    client_id, contract_id, _line_id = await _world()
    month = _month(-1)
    year, mon = (int(x) for x in month.split("-"))
    previous = await _module(True)
    try:
        await _rules(
            client_id,
            {
                "cl.client_acceptance": {
                    "level": "warn",
                    "params": {"email": "body@bank.example"},
                },
            },
        )
        card = _workbook(
            {"KARTA": _card_rows(month=kcp.MONTHS_PL[mon - 1], year=str(year))}
        )
        await _store(contract_id, month, card, "KCP.xlsx")
        async with AsyncSessionLocal() as db:
            await client_acceptance.mark_sent(
                db, client_id, month, [contract_id], actor=ACTOR, now=local_now()
            )
            await db.commit()
        url = "/api/finance/settlements/client-acceptance/reply"
        unknown = await app_client.post(
            url,
            headers=app_auth_headers,
            data={"month": month},
            files={
                "file": ("x.eml", _reply(month, "W KCP jest błąd."), "message/rfc822")
            },
        )
        assert unknown.status_code == 422
        ok = await app_client.post(
            url,
            headers=app_auth_headers,
            data={"month": month},
            files={"file": ("r.eml", _reply(month, "Potwierdzam."), "message/rfc822")},
        )
        assert ok.status_code == 200, ok.text
        s = await _settlement(contract_id, month)
        assert client_acceptance.status(s) == client_acceptance.ACCEPTED
    finally:
        await _restore(previous)
        await _cleanup(client_id)
