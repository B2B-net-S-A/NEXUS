"""Faktura PDF z rozliczenia@: odczyt pól i ten sam koszt z kilku źródeł (27.11.2026).

Osoby, numery i kwoty zmyślone.
"""

from __future__ import annotations

import contextlib
import hashlib
import uuid
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from app.core.database import AsyncSessionLocal
from app.models.consultant_portal import CpDocument
from app.services.consultant_portal import invoice_read
from app.services.hr.approvals import reader
from app.services.month_check import collect, rules

D = Decimal


def _cost(number: str, *, day: int = 30, net: str = "24000.00") -> rules.CostDoc:
    return rules.CostDoc(
        candidate_id=1,
        number=number,
        issue_date=date(2026, 10, day),
        net=D(net),
        currency="PLN",
        correction=False,
    )


def test_number_written_differently_is_the_same_invoice():
    keys = collect._keys_of([_cost("FV 1/10/2026")])
    assert collect._twin(keys, _cost("fv-1-10-2026", day=31, net="1"), "fv-1-10-2026")


def test_invoice_without_number_matches_by_day_and_net():
    keys = collect._keys_of([_cost("FV 1/10/2026")])
    assert collect._twin(keys, _cost("PDF 7"), None)
    assert not collect._twin(keys, _cost("PDF 8", net="23000.00"), None)


def test_other_number_other_day_is_another_invoice():
    keys = collect._keys_of([_cost("FV 1/10/2026")])
    assert not collect._twin(keys, _cost("FV 2/10/2026", day=15), "FV 2/10/2026")


def test_other_number_same_day_and_net_is_another_invoice():
    """Stała stawka, dwa kontrakty: dwie faktury z tym samym dniem i kwotą to dwa koszty."""

    keys = collect._keys_of([_cost("FV 1/10/2026")])
    assert not collect._twin(keys, _cost("FV 2/10/2026"), "FV 2/10/2026")
    # Plik bez numeru z tego dnia nie wie, którą z nich jest: liczy się raz.
    assert collect._twin(keys, _cost("PDF 9"), None)


def test_net_falls_back_to_gross_only_with_explicit_zero_vat():
    assert invoice_read.cost_net(
        {"net_amount": "100.00", "gross_amount": "123.00"}
    ) == D("100.00")
    assert invoice_read.cost_net({"gross_amount": "100.00", "vat_amount": "0.00"}) == D(
        "100.00"
    )
    # VAT nieodczytany to nie zwolnienie: brutto zawyżyłoby koszt o 23%.
    assert invoice_read.cost_net({"gross_amount": "123.00", "vat_amount": None}) is None
    assert (
        invoice_read.cost_net({"gross_amount": "123.00", "vat_amount": "23.00"}) is None
    )


def test_only_read_invoices_with_amount_count():
    read = {"status": "read", "doc_type": "invoice", "net_amount": "1.00"}
    assert invoice_read.counts_as_cost(read)
    assert not invoice_read.counts_as_cost({**read, "status": "retry"})
    assert not invoice_read.counts_as_cost({**read, "doc_type": "receipt"})
    # Czytnik zgód: netto bez brutto to „failed”, ale koszt liczymy netto.
    assert invoice_read.counts_as_cost(
        {**read, "status": "failed", "net_amount": "93000.00", "gross_amount": None}
    )
    assert not invoice_read.counts_as_cost(
        {"status": "failed", "doc_type": "invoice", "net_amount": None}
    )
    assert not invoice_read.counts_as_cost(
        {**read, "net_amount": None, "gross_amount": None}
    )
    assert not invoice_read.counts_as_cost(
        {**read, "net_amount": None, "gross_amount": "123.00", "vat_amount": None}
    )
    assert not invoice_read.counts_as_cost(None)


def _document(tag: str, *, mime: str = "application/pdf") -> CpDocument:
    return CpDocument(
        contract_id=None,
        kind="invoice",
        period_year=2026,
        period_month=10,
        channel="mailbox",
        file_path=f"consultant_portal/test/{tag}.pdf",
        mime=mime,
        size_bytes=10,
        sha256=hashlib.sha256(tag.encode()).hexdigest(),
    )


REPLY = (
    '{"doc_type": "invoice", "seller_nip": null, "invoice_number": "F/1",'
    ' "issue_date": "2026-10-30", "currency": "PLN", "net_amount": "100",'
    ' "vat_amount": "0", "gross_amount": "100"}'
)


@pytest.mark.asyncio
async def test_read_pending_reads_retries_and_gives_up(monkeypatch, tmp_path):
    """Odczyt zapisuje pola; awaria modelu i brak pliku wracają do kolejki, ale
    najwyżej ``MAX_ATTEMPTS`` razy; nieczytelna odpowiedź to ``failed`` od razu."""

    tag = uuid.uuid4().hex[:8]
    pdf = tmp_path / "f.pdf"
    pdf.write_bytes(b"%PDF-1.4 test")
    calls: list[str] = []
    outage = {"on": True}

    def path_for(relative: str) -> Path:
        if relative.endswith(f"{tag}-missing.pdf"):
            raise FileNotFoundError("brak pliku")
        return pdf

    async def try_read(content: bytes, mime: str):
        calls.append(mime)
        if outage["on"] and mime == "image/png":
            return None  # 529 od dostawcy
        if mime == "image/jpeg":
            return reader.parse_reply("nie umiem")
        return reader.parse_reply(REPLY)

    monkeypatch.setattr(invoice_read.documents, "path_for", path_for)
    monkeypatch.setattr(invoice_read.reader, "try_read", try_read)
    monkeypatch.setattr(
        invoice_read, "ai_feature", lambda *a, **k: contextlib.nullcontext()
    )

    async with AsyncSessionLocal() as db:
        good = _document(tag)
        missing = _document(f"{tag}-missing")
        busy = _document(f"{tag}-busy", mime="image/png")
        garbage = _document(f"{tag}-garbage", mime="image/jpeg")
        sheet = _document(f"{tag}-sheet", mime="application/vnd.ms-excel")
        rows = (good, missing, busy, garbage, sheet)
        db.add_all(rows)
        await db.commit()

        await invoice_read.read_pending(db, limit=1000)
        await db.commit()
        for row in rows:
            await db.refresh(row)
        assert invoice_read.counts_as_cost(good.invoice_fields)
        assert good.invoice_fields["invoice_number"] == "F/1"
        assert garbage.invoice_fields["status"] == "failed"
        assert busy.invoice_fields == {
            "status": "retry",
            "error": "model",
            "attempts": 1,
        }
        assert missing.invoice_fields["status"] == "retry"
        assert sheet.invoice_fields is None

        # Model wraca: faktura z awarii zostaje odczytana w następnym przebiegu.
        outage["on"] = False
        await invoice_read.read_pending(db, limit=1000)
        await db.commit()
        await db.refresh(busy)
        assert invoice_read.counts_as_cost(busy.invoice_fields)

        # Brak pliku: po MAX_ATTEMPTS próbach koniec, bez wiecznej kolejki.
        for _ in range(invoice_read.MAX_ATTEMPTS):
            await invoice_read.read_pending(db, limit=1000)
            await db.commit()
        await db.refresh(missing)
        assert missing.invoice_fields["status"] == "failed"
        assert missing.invoice_fields["attempts"] == invoice_read.MAX_ATTEMPTS

        # Żaden z plików nie zostaje w kolejce na zawsze.
        assert all(
            row.invoice_fields["status"] != "retry" for row in rows if row is not sheet
        )
