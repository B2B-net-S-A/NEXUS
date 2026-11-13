"""Rozliczenia PKO (E6.1) i Velo (E6.2) na bazie. Dane fikcyjne.

PKO: Time Sheet ``.xlsm`` ze stawką godzinową, bez maila akceptacji zadanie
„Popraw akceptację” i blokada przyjęcia, z mailem przyjęcie; zbiorczy protokół
i paczka (protokół, Time Sheet, akceptacja w HTML) przy komplecie; faktura do
klienta czeka na podpisany protokół.

Velo: arkusz zbiorczy per podpisujący (menedżer u klienta z kontraktu), MD
osoby łącznie z drugim klientem ponad dni robocze, zapłata dopiero po
podpisanym arkuszu tej osoby — arkusz rozpoznany po treści, wgrany bez kontraktu.
"""

from __future__ import annotations

import asyncio
import io
import zipfile
from decimal import Decimal
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from app.core.database import AsyncSessionLocal
from app.core.scheduling import local_now
from app.models.client_order import ClientOrder
from app.models.client_settlement import ClientSettlement
from app.models.consultant_portal import CpDocument
from app.models.contract import Contract, RateUnit
from app.services.client_settlements import (
    client_documents,
    client_invoice,
    consultant,
    service,
    signoffs,
)
from app.services.client_settlements.service import SettlementError
from app.services.consultant_portal import documents
from tests.test_client_settlements_client_invoice_db import _month, _rules
from tests.test_client_settlements_consultant_db import _module, _restore
from tests.test_client_settlements_pko_velo import _old_template, _signed_pdf, _xlsm
from tests.test_client_settlements_service_db import _cleanup, _world
from tests.test_client_settlements_timesheet_db import _timesheet

pytestmark = pytest.mark.asyncio

ACTOR = SimpleNamespace(id=None)


async def _store(
    contract_id: int | None, month: str, content: bytes, name: str
) -> CpDocument:
    year, mon = (int(x) for x in month.split("-"))
    async with AsyncSessionLocal() as db:
        stored = await documents.store(
            db,
            contract_id=contract_id,
            kind="report",
            year=year,
            month=mon,
            content=content,
            file_name=name,
            channel="portal",
            now=local_now(),
        )
        await db.commit()
        return stored.document


async def _settlement(contract_id: int, month: str) -> ClientSettlement:
    async with AsyncSessionLocal() as db:
        return await db.scalar(
            select(ClientSettlement).where(
                ClientSettlement.contract_id == contract_id,
                ClientSettlement.period_month == month,
                ClientSettlement.kind == "actual",
            )
        )


def _titles(s: ClientSettlement) -> dict[str, str]:
    return {
        c["title"]: c["state"]
        for g in s.checks
        if isinstance(g, dict)
        for c in g.get("checks") or []
    }


async def _person(contract_id: int) -> str:
    async with AsyncSessionLocal() as db:
        return (await service._contract(db, contract_id)).name


async def _drop_documents(ids: list[int]) -> None:
    async with AsyncSessionLocal() as db:
        await db.execute(CpDocument.__table__.delete().where(CpDocument.id.in_(ids)))
        await db.commit()


def _eml(month: str, hours: int) -> bytes:
    year, mon = month.split("-")
    return (
        "From: Akceptujacy <akceptujacy@klient.example>\r\n"
        "To: konsultant@klient.example\r\n"
        f"Subject: RE: Odbior uslug za {mon}.{year}\r\n"
        "Date: Mon, 2 Nov 2026 09:56:00 +0100\r\nMIME-Version: 1.0\r\n"
        "Content-Type: text/plain; charset=utf-8\r\n\r\n"
        "Potwierdzam.\r\n\r\n"
        f"> Prosze o potwierdzenie odbioru uslug zrealizowanych w {mon}.{year}. "
        f"Laczna liczba godzin realizacji uslug: {hours}.\r\n"
    ).encode()


async def test_pko_akceptacja_protokol_paczka_i_faktura_po_podpisie(
    tmp_path, monkeypatch
) -> None:
    from app.services import storage_service

    monkeypatch.setattr(storage_service, "STORAGE_ROOT", tmp_path)
    monkeypatch.setattr(client_documents, "render_pdf", lambda html: html.encode())
    client_id, contract_id, line_id = await _world()
    month = _month(-1)
    year, mon = (int(x) for x in month.split("-"))
    previous = await _module(True)
    try:
        async with AsyncSessionLocal() as db:
            line = await db.get(ClientOrder, line_id)
            line.title = "Zamówienie nr 1234/2026"
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
                "proof.accept_has_hours": {"level": "block", "params": {}},
                "cl.client_document": {
                    "level": "warn",
                    "params": {
                        "kind": "Protokół odbioru",
                        "per": "cały miesiąc",
                        "from": month,
                        "header": "Załącznik do umowy",
                    },
                },
                "cl.after_signed_document": {"level": "block", "params": {}},
                "cl.send_to": {
                    "level": "warn",
                    "params": {"email": "paczki@klient.example"},
                },
            },
        )
        rows = _old_template("październik")
        rows[15 - 1][13] = f"Liczba godzin realizacji usług {_polish(mon)} {year}"
        await _store(contract_id, month, _xlsm(rows, ("D",)), "TimeSheet.xlsm")

        s = await _settlement(contract_id, month)
        assert s.md_regular == Decimal("22.000")
        assert _titles(s)["Brak maila z akceptacją"] == "fail"
        async with AsyncSessionLocal() as db:
            view = await consultant.view(db, contract_id, client_id, year, mon)
            assert view["todo"] == ["Popraw akceptację"]
            with pytest.raises(SettlementError, match="Brak maila z akceptacją"):
                await service.accept(
                    db, contract_id, month, actor=ACTOR, now=local_now()
                )

        await _store(contract_id, month, _eml(month, 176), "akceptacja.eml")
        s = await _settlement(contract_id, month)
        assert _titles(s)[f"Akceptacja: 176 h za {_polish(mon)} {year}"] == "ok"
        async with AsyncSessionLocal() as db:
            await service.accept(db, contract_id, month, actor=ACTOR, now=local_now())
            await db.commit()
        s = await _settlement(contract_id, month)
        # Linia ze stawką godzinową bez stawek MD: 22 MD × 8 h × 100 zł.
        assert s.amount_revenue == Decimal("17600.00")
        assert s.amount_cost == Decimal("10560.00")

        async with AsyncSessionLocal() as db:
            block = await client_documents.collect(db, client_id, month, amounts=True)
            assert block["layout"] == "month"
            assert block["protocol"]["ready"]
            assert block["protocol"]["send_to"] == "paczki@klient.example"
            assert block["protocol"]["net"] == "17600.00"
            content, name = await client_documents.protocol_pdf(db, client_id, month)
            html = content.decode()
            assert (
                "1234/2026" in html and "100,00 zł" in html and "17 600,00 zł" in html
            )
            assert "Załącznik do umowy" in html
            package, _ = await client_documents.package_zip(db, client_id, month)
            names = zipfile.ZipFile(io.BytesIO(package)).namelist()
            assert name in names and "TimeSheet.xlsm" in names
            assert any(n.endswith(".html") for n in names)

            invoice = await client_invoice.invoice_month(
                db, client_id, month, amounts=True
            )
            assert (
                invoice["signature_hold"]["label"]
                == "Czeka na podpisany protokół odbioru"
            )
            assert invoice["rows"][0]["state"] == "awaiting_signature"

            s = await db.get(ClientSettlement, s.id)
            s.checks = signoffs.with_marker(
                list(s.checks), {"kind": "protocol", "complete": True, "document_id": 0}
            )
            await db.commit()
            invoice = await client_invoice.invoice_month(
                db, client_id, month, amounts=True
            )
            assert invoice["signature_hold"] is None
            assert invoice["rows"][0]["state"] == "ready"
    finally:
        await _restore(previous)
        await _cleanup(client_id)


def _polish(mon: int) -> str:
    from app.services.client_settlements.mail_text import MONTHS_NOMINATIVE

    return MONTHS_NOMINATIVE[mon - 1]


async def test_velo_arkusz_per_podpisujacy_limit_md_i_zaplata_po_podpisie(
    tmp_path, monkeypatch
) -> None:
    from app.services import storage_service

    monkeypatch.setattr(storage_service, "STORAGE_ROOT", tmp_path)
    monkeypatch.setattr(client_documents, "render_pdf", lambda html: html.encode())
    client_id, contract_id, _line_id = await _world(md_total="60")
    other_client, other_contract, _other_line = await _world()
    month = _month(-1)
    year, mon = (int(x) for x in month.split("-"))
    previous = await _module(True)
    stored: list[int] = []
    try:
        async with AsyncSessionLocal() as db:
            contract = await db.get(Contract, contract_id)
            contract.client_pm_name = "Podpisujący A"
            other = await db.get(Contract, other_contract)
            other.candidate_id = contract.candidate_id
            db.add(
                ClientSettlement(
                    contract_id=other_contract,
                    client_id=other_client,
                    period_month=month,
                    kind="actual",
                    status="accepted",
                    md_regular=Decimal("17"),
                    lines=[],
                    checks=[],
                )
            )
            await db.commit()
        await _rules(
            client_id,
            {
                "proof.month": {"level": "block", "params": {}},
                "proof.excel_with_mail": {"level": "off", "params": {"domain": ""}},
                "proof.name_match": {"level": "off", "params": {}},
                "fields.md_month_limit": {"level": "warn", "params": {}},
                "pay.per_person": {"level": "block", "params": {}},
                "cl.client_document": {
                    "level": "warn",
                    "params": {
                        "kind": "Arkusz zbiorczy",
                        "per": "podpisujący",
                        "from": "",
                    },
                },
                "cl.after_signed_document": {"level": "block", "params": {}},
            },
        )
        days = list(range(1, 18))  # 17 dni po 8 h = 17 MD
        await _store(
            contract_id,
            month,
            _timesheet(month, [(d, "VELO", "Praca", 8, None) for d in days]),
            "Time Sheet.xlsx",
        )
        s = await _settlement(contract_id, month)
        assert s.md_regular == Decimal("17.000")
        titles = _titles(s)
        assert titles["Arkusz czeka na podpis klienta"] == "fail"
        limit = next(t for t in titles if t.startswith("34 MD przy"))
        assert titles[limit] == "warn"
        async with AsyncSessionLocal() as db:
            with pytest.raises(SettlementError, match="Arkusz czeka na podpis klienta"):
                await service.accept(
                    db, contract_id, month, actor=ACTOR, now=local_now()
                )
            block = await client_documents.collect(db, client_id, month, amounts=True)
            assert block["layout"] == "signer"
            assert block["sheets"]["signers"][0]["signer"] == "Podpisujący A"
            assert block["sheets"]["rows"][0]["signed"] is False
            sheet, sheet_name = await client_documents.sheet_pdf(
                db, client_id, month, "Podpisujący A"
            )
            assert "17" in sheet.decode() and sheet_name.endswith(".pdf")
            with pytest.raises(SettlementError, match="czeka na podpisy"):
                await client_documents.invoice_sheet_pdf(db, client_id, month)

        # Podpisany arkusz wrzucony przez koordynatora (bez kontraktu): rozpoznany po treści.
        person = await _person(contract_id)
        # Podpis pyHanko ma własną pętlę zdarzeń: w wątku.
        pdf = await asyncio.to_thread(
            _signed_pdf,
            [
                "Nazwisko i imie Rodzaj kompetencji (profil) Zlecenie od Zlecenie do Liczba MD",
                f"{person} Tester 01-{mon:02d}-{year} 28-{mon:02d}-{year} 17",
            ],
            1,
        )
        document = await _store(None, month, pdf, "Arkusz podpisany.pdf")
        stored.append(document.id)
        async with AsyncSessionLocal() as db:
            again = await db.get(CpDocument, document.id)
            assert again.contract_id is None and again.status == "accepted"
        s = await _settlement(contract_id, month)
        assert signoffs.is_complete(s.checks, signoffs.SHEET)
        signed_title = next(
            t for t in _titles(s) if t.startswith("Arkusz podpisany przez klienta")
        )
        assert "Podpisujacy 0" in signed_title and _titles(s)[signed_title] == "ok"
        async with AsyncSessionLocal() as db:
            # Znacznik podpisu nie jest grupą kontroli na karcie osoby.
            card = await service.detail(db, contract_id, month, amounts=True)
            assert all("checks" in group for group in card["checks"])
            await service.accept(db, contract_id, month, actor=ACTOR, now=local_now())
            await db.commit()
            final, _ = await client_documents.invoice_sheet_pdf(db, client_id, month)
            assert "Wartość" in final.decode()
            invoice = await client_invoice.invoice_month(
                db, client_id, month, amounts=True
            )
            assert invoice["signature_hold"] is None
    finally:
        await _restore(previous)
        await _drop_documents(stored)
        await _cleanup(client_id)
        await _cleanup(other_client)
