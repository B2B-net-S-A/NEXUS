"""„Możliwa podwójna zapłata” w planie paczki przelewów (audyt 25.11.2026) — z bazą.

Korekta na plus równa całej wcześniejszej fakturze, druga faktura kontraktora
na tę samą kwotę w miesiącu i ten sam numer dwa razy dają ostrzeżenie do
odhaczenia (``double_payment``): paczka bez odhaczenia = 409 ``needs_ack``,
z odhaczeniem przechodzi. Dostawcy, NIP-y i kwoty fikcyjne.
"""

# ruff: noqa: F811  (fikstury ``world`` i ``client`` z test_finance_payments_db)
from __future__ import annotations

from datetime import date
from decimal import Decimal

from app.core.database import AsyncSessionLocal
from app.models.finance_ledger import FinanceCostEntry
from app.models.hr_approval import ApprovalDocument
from tests.test_finance_payments_db import (  # noqa: F401  (fikstury)
    PAY,
    _headers,
    _items,
    _nrb,
    _supplier_entry,
    client,
    world,
)


async def _set_doc(
    entry_id: int,
    *,
    kind: str = "Vat",
    issued: date = date(2026, 11, 3),
    net: str | None = None,
    category: str | None = None,
) -> None:
    async with AsyncSessionLocal() as db:
        entry = await db.get(FinanceCostEntry, entry_id)
        doc = await db.get(ApprovalDocument, entry.source_id)
        doc.ksef_invoice_type = kind
        doc.issue_date = issued
        if net is not None:
            doc.net_amount = Decimal(net)
        if category is not None:
            entry.category = category
        await db.commit()


async def _plan(client, headers, ids: list[int]) -> dict[int, dict]:
    response = await client.post(f"{PAY}/plan", json={}, headers=headers)
    return _items(response, ids)


def _codes(row: dict) -> list[str]:
    return [ack["code"] for ack in row["acks"]]


async def test_druga_faktura_kontraktora_na_te_sama_kwote_wymaga_odhaczenia(
    world, client
) -> None:
    nip = world["nips"]["a"]
    world["listed"].add(_nrb(41))
    first = await _supplier_entry(
        world, nip, gross="1230.00", vat="230.00", account=_nrb(41)
    )
    second = await _supplier_entry(
        world, nip, gross="1230.00", vat="230.00", account=_nrb(41)
    )
    for entry_id, day in ((first, date(2026, 10, 31)), (second, date(2026, 11, 3))):
        await _set_doc(entry_id, issued=day, category="contractor")
    headers = _headers(world["accountant"])

    rows = await _plan(client, headers, [first, second])
    for entry_id in (first, second):
        assert _codes(rows[entry_id]) == ["double_payment"]
        assert rows[entry_id]["preselect"] is False
    [ack] = rows[second]["acks"]
    assert "Druga faktura" in ack["label"]
    assert world["number"][first] in ack["label"]

    refused = await client.post(
        f"{PAY}/batches", json={"entry_ids": [second]}, headers=headers
    )
    assert refused.status_code == 409
    assert refused.json()["detail"]["code"] == "needs_ack"
    batch = await client.post(
        f"{PAY}/batches",
        json={"entry_ids": [second], "acknowledged": [second], "format": "csv"},
        headers=headers,
    )
    assert batch.status_code == 200, batch.text


async def test_korekta_na_plus_rowna_wczesniejszej_fakturze_ostrzega(
    world, client
) -> None:
    nip = world["nips"]["b"]
    world["listed"].add(_nrb(42))
    invoice = await _supplier_entry(
        world, nip, gross="1230.00", vat="230.00", account=_nrb(42)
    )
    kor = await _supplier_entry(
        world, nip, gross="1230.00", vat="230.00", account=_nrb(42)
    )
    small = await _supplier_entry(
        world, nip, gross="123.00", vat="23.00", account=_nrb(42)
    )
    await _set_doc(invoice, issued=date(2026, 9, 30))
    await _set_doc(kor, kind="Kor", issued=date(2026, 11, 4))
    await _set_doc(small, kind="Kor", issued=date(2026, 11, 4))
    headers = _headers(world["accountant"])

    rows = await _plan(client, headers, [invoice, kor, small])
    assert _codes(rows[kor]) == ["double_payment"]
    assert "Korekta" in rows[kor]["acks"][0]["label"]
    # Dokument wydatku spoza „Kontraktorów”: druga faktura za miesiąc nie liczy się,
    # korekta o różnicę nie ostrzega.
    assert _codes(rows[invoice]) == []
    assert _codes(rows[small]) == []


async def test_ten_sam_numer_dwa_razy_i_duplikat_rozstrzygniety(world, client) -> None:
    nip = world["nips"]["c"]
    world["listed"].add(_nrb(43))
    first = await _supplier_entry(
        world, nip, gross="100.00", number="ZZ 9/11/2026", account=_nrb(43)
    )
    second = await _supplier_entry(
        world, nip, gross="250.00", number="zz9/11/2026", account=_nrb(43)
    )
    headers = _headers(world["accountant"])
    rows = await _plan(client, headers, [first, second])
    assert _codes(rows[second]) == ["double_payment"]
    assert "Ten sam numer" in rows[second]["acks"][0]["label"]

    # Finanse oznaczyły pierwszą jako „Duplikat” — druga nie ostrzega.
    async with AsyncSessionLocal() as db:
        entry = await db.get(FinanceCostEntry, first)
        entry.flags = ["duplicate"]
        await db.commit()
    rows = await _plan(client, headers, [second])
    assert _codes(rows[second]) == []
