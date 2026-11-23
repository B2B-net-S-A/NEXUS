"""Blokady płatności kontraktorów w paczce przelewów (0764, 23.11.2026) — z bazą.

Zajęcie wierzytelności (komornik, e-US) dzieli płatność faktury kontraktora:
należność z odsetkami do dnia przelewu na rachunek organu, reszta do
kontraktora. Sprawdzamy: zajęcie większe niż płatność, kilka zajęć naraz,
uchylenie w trakcie (pozycja schodzi z paczki), kwota, której nie da się
policzyć (blokada do decyzji księgowej), wyciąg zamykający oba przelewy,
„Spór / wstrzymane” na rozliczeniu (powód, kto, zwolnienie), białą listę
w dniu paczki (spoza wykazu i błąd wykazu blokują, powrót zwalnia), 403 bez
„Modułu Finanse” i wpisy w Historii zdarzeń bez kwot i sygnatur.
Osoby, NIP-y, rachunki, sygnatury i kwoty fikcyjne.
"""

# ruff: noqa: F811  (fikstury ``world`` i ``client`` z test_finance_payments_db)
from __future__ import annotations

import uuid
from datetime import timedelta

from sqlalchemy import delete, select

from app.core.database import AsyncSessionLocal
from app.models.critical_event import CriticalEvent
from app.models.finance_ledger import FinanceCostEntry
from app.models.finance_payments import (
    FinanceCostPaymentRecord,
    FinancePaymentBatchItem,
)
from app.services.hr import white_list
from tests.test_finance_payments_db import (  # noqa: F401  (fikstury)
    COSTS,
    PAY,
    _contractor_entry,
    _drop_client,
    _headers,
    _items,
    _mt940,
    _nrb,
    _state,
    client,
    world,
)

CONTRACTOR_ACCOUNT = _nrb(71)  # rachunek kontraktora z ``_contractor_entry``


async def _contract_of(entry_id: int) -> int:
    from app.models.client_settlement import ClientContractorInvoice

    async with AsyncSessionLocal() as db:
        entry = await db.get(FinanceCostEntry, entry_id)
        invoice = await db.get(ClientContractorInvoice, entry.source_id)
        return invoice.contract_id


def _garnishment(contract_id: int, **kw) -> dict:
    body = {
        "contract_id": contract_id,
        "authority_kind": "bailiff",
        "authority_name": "Komornik Sądowy Testowy",
        "case_number": f"KM {uuid.uuid4().hex[:4].upper()}/26",
        "served_on": "2026-11-02",
        "principal_amount": "1000.00",
        "costs_amount": "30.00",
        "interest_mode": "fixed",
        "interest_amount": "20.00",
        "authority_account": _nrb(81),
    }
    body.update(kw)
    return body


async def _plan(client, headers, entry_id: int) -> dict:
    response = await client.post(f"{PAY}/plan", json={}, headers=headers)
    return _items(response, [entry_id])[entry_id]


async def _cleanup(entry_id: int, client_id: int) -> None:
    async with AsyncSessionLocal() as db:
        await db.execute(
            delete(FinanceCostPaymentRecord).where(
                FinanceCostPaymentRecord.entry_id == entry_id
            )
        )
        await db.execute(
            delete(FinanceCostEntry).where(FinanceCostEntry.id == entry_id)
        )
        await db.commit()
    await _drop_client(client_id)


async def test_zajecie_dzieli_platnosc_a_wyciag_zamyka_oba_przelewy(
    world, client
) -> None:
    entry, client_id = await _contractor_entry(world, rule="off", kesu="signed")
    headers = _headers(world["accountant"])
    try:
        contract_id = await _contract_of(entry)
        created = await client.post(
            f"{PAY}/garnishments", json=_garnishment(contract_id), headers=headers
        )
        assert created.status_code == 200, created.text
        case = created.json()["case_number"]
        assert created.json()["due_today"] == "1050.00"

        row = await _plan(client, headers, entry)
        assert row["selectable"] is True
        assert [ack["code"] for ack in row["acks"]] == ["garnishment"]
        assert row["preselect"] is False
        assert row["contractor_amount"] == "180.00"
        [organ] = row["garnishments"]
        assert (organ["amount"], organ["account"]) == ("1050.00", _nrb(81))
        assert organ["title"].startswith(f"Sygn. {case}")

        refused = await client.post(
            f"{PAY}/batches", json={"entry_ids": [entry]}, headers=headers
        )
        assert refused.json()["detail"]["code"] == "needs_ack"
        batch = await client.post(
            f"{PAY}/batches",
            json={"entry_ids": [entry], "acknowledged": [entry], "format": "csv"},
            headers=headers,
        )
        assert batch.status_code == 200, batch.text
        [item] = batch.json()["items"]
        assert item["amount"] == "1230.00" and item["contractor_amount"] == "180.00"
        file = await client.get(
            f"{PAY}/batches/{batch.json()['id']}/file", headers=headers
        )
        lines = file.content.decode("utf-8-sig").strip().splitlines()[1:]
        assert len(lines) == 2
        assert any("180,00" in line and "zajęcie" not in line for line in lines)
        assert any("1050,00" in line and line.endswith("zajęcie") for line in lines)

        # Organ i kontraktor z wyciągu — faktura zapłacona, pozycja zamknięta.
        ref = uuid.uuid4().hex[:6].upper()
        raw = _mt940(
            ("1050,00", f"Sygn. {case}", _nrb(81), f"G{ref}"),
            ("180,00", "przelew", CONTRACTOR_ACCOUNT, f"H{ref}"),
        )
        upload = await client.post(
            f"{PAY}/statements", files={"file": ("w.sta", raw)}, headers=headers
        )
        assert upload.status_code == 200, upload.text
        assert await _state(entry) == "paid"
        async with AsyncSessionLocal() as db:
            status = await db.scalar(
                select(FinancePaymentBatchItem.status).where(
                    FinancePaymentBatchItem.entry_id == entry
                )
            )
        assert status == "done"
        listing = await client.get(f"{PAY}/garnishments", headers=headers)
        mine = [g for g in listing.json()["items"] if g["contract_id"] == contract_id]
        assert mine[0]["transferred"] == "1050.00" and mine[0]["due_today"] == "0.00"
    finally:
        await _cleanup(entry, client_id)


async def test_zajecie_wieksze_niz_platnosc_i_kilka_zajec_naraz(world, client) -> None:
    entry, client_id = await _contractor_entry(world, rule="off", kesu="signed")
    headers = _headers(world["accountant"])
    try:
        contract_id = await _contract_of(entry)
        later = _garnishment(
            contract_id,
            served_on=(world["today"] - timedelta(days=1)).isoformat(),
            principal_amount="5000.00",
            costs_amount="0.00",
            interest_mode="none",
            authority_kind="tax_office",
            authority_name="Urząd Skarbowy Testowy",
            authority_account=_nrb(82),
        )
        first = _garnishment(
            contract_id,
            served_on="2026-10-01",
            principal_amount="200.00",
            costs_amount="0.00",
            interest_mode="none",
        )
        for body in (later, first):
            response = await client.post(
                f"{PAY}/garnishments", json=body, headers=headers
            )
            assert response.status_code == 200, response.text
        row = await _plan(client, headers, entry)
        # Najpierw wcześniej doręczone (200), reszta płatności do drugiego organu.
        assert [(g["account"], g["amount"]) for g in row["garnishments"]] == [
            (_nrb(81), "200.00"),
            (_nrb(82), "1030.00"),
        ]
        assert row["contractor_amount"] == "0.00"
        # Całość do organów: rachunku kontraktora nie sprawdzamy w wykazie.
        assert row["white_list"]["state"] == "garnished"
        batch = await client.post(
            f"{PAY}/batches",
            json={"entry_ids": [entry], "acknowledged": [entry], "format": "csv"},
            headers=headers,
        )
        assert batch.status_code == 200, batch.text
        file = await client.get(
            f"{PAY}/batches/{batch.json()['id']}/file", headers=headers
        )
        lines = file.content.decode("utf-8-sig").strip().splitlines()[1:]
        assert len(lines) == 2 and all(line.endswith("zajęcie") for line in lines)
    finally:
        await _cleanup(entry, client_id)


async def test_uchylenie_w_trakcie_zdejmuje_fakture_z_paczki(world, client) -> None:
    entry, client_id = await _contractor_entry(world, rule="off", kesu="signed")
    headers = _headers(world["accountant"])
    try:
        contract_id = await _contract_of(entry)
        created = await client.post(
            f"{PAY}/garnishments", json=_garnishment(contract_id), headers=headers
        )
        garnishment_id = created.json()["id"]
        batch = await client.post(
            f"{PAY}/batches",
            json={"entry_ids": [entry], "acknowledged": [entry], "format": "csv"},
            headers=headers,
        )
        assert batch.status_code == 200, batch.text
        await client.get(f"{PAY}/batches/{batch.json()['id']}/file", headers=headers)

        lifted = await client.post(
            f"{PAY}/garnishments/{garnishment_id}/lift",
            json={"lifted_on": world["today"].isoformat(), "note": "postanowienie"},
            headers=headers,
        )
        assert lifted.status_code == 200, lifted.text
        assert lifted.json()["active"] is False
        # Plik był pobrany (mógł pójść do banku) — nie zdejmujemy po cichu,
        # tylko mówimy, którą paczkę sprawdzić.
        assert lifted.json()["released_from_batches"] == [
            {
                "batch_id": batch.json()["id"],
                "entry_id": entry,
                "file_stale": False,
                "released": False,
                "reason": "downloaded",
            }
        ]
        assert await _state(entry) == "in_batch"
        manual = await client.post(
            f"{PAY}/batches/{batch.json()['id']}/items/{entry}/release",
            headers=headers,
        )
        assert manual.status_code == 200, manual.text
        assert await _state(entry) == "unpaid"
        row = await _plan(client, headers, entry)
        assert row["garnishments"] == [] and row["contractor_amount"] is None
        assert row["selectable"] is True and row["acks"] == []
        again = await client.post(
            f"{PAY}/garnishments/{garnishment_id}/lift",
            json={"lifted_on": world["today"].isoformat()},
            headers=headers,
        )
        assert again.status_code == 409
        edit = await client.put(
            f"{PAY}/garnishments/{garnishment_id}",
            json={
                k: v for k, v in _garnishment(contract_id).items() if k != "contract_id"
            },
            headers=headers,
        )
        assert edit.status_code == 409
    finally:
        await _cleanup(entry, client_id)


async def test_kwoty_nie_da_sie_policzyc_blokuje_do_decyzji_ksiegowej(
    world, client
) -> None:
    entry, client_id = await _contractor_entry(world, rule="off", kesu="signed")
    headers = _headers(world["accountant"])
    try:
        contract_id = await _contract_of(entry)
        body = _garnishment(contract_id, interest_mode="unknown", interest_amount=None)
        created = await client.post(f"{PAY}/garnishments", json=body, headers=headers)
        assert created.status_code == 200, created.text
        assert created.json()["due_today"] is None
        assert created.json()["problem"].startswith("odsetki nieustalone")
        row = await _plan(client, headers, entry)
        assert row["block"] == "garnishment"
        assert body["case_number"] in row["block_label"]
        assert "decyzję księgowej" in row["block_label"]
        refused = await client.post(
            f"{PAY}/batches",
            json={"entry_ids": [entry], "acknowledged": [entry]},
            headers=headers,
        )
        assert refused.json()["detail"]["code"] == "blocked"

        # Księgowa wpisuje stopę od dnia — kwota się liczy, blokada znika.
        fixed = {k: v for k, v in body.items() if k != "contract_id"}
        fixed.update(
            interest_mode="rate", interest_rate="11.25", interest_from="2026-10-01"
        )
        updated = await client.put(
            f"{PAY}/garnishments/{created.json()['id']}", json=fixed, headers=headers
        )
        assert updated.status_code == 200, updated.text
        row = await _plan(client, headers, entry)
        assert row["block"] is None and row["garnishments"]
        assert row["garnishments"][0]["amount"] > "1030.00"

        # Bez rachunku organu też nie zapłacimy.
        no_account = {**fixed, "authority_account": None}
        await client.put(
            f"{PAY}/garnishments/{created.json()['id']}",
            json=no_account,
            headers=headers,
        )
        row = await _plan(client, headers, entry)
        assert row["block"] == "garnishment" and "rachunku organu" in row["block_label"]
        bad = await client.put(
            f"{PAY}/garnishments/{created.json()['id']}",
            json={**fixed, "authority_account": "12 3456"},
            headers=headers,
        )
        assert bad.status_code == 422
    finally:
        await _cleanup(entry, client_id)


async def test_spor_wstrzymuje_platnosc_do_zwolnienia(world, client) -> None:
    entry, client_id = await _contractor_entry(world, rule="off", kesu="signed")
    headers = _headers(world["accountant"])
    try:
        batch = await client.post(
            f"{PAY}/batches", json={"entry_ids": [entry]}, headers=headers
        )
        assert batch.status_code == 200, batch.text
        reason = "Praca bez zamówienia klienta przez 1,5 miesiąca"
        hold = await client.post(
            f"{PAY}/holds", json={"entry_id": entry, "reason": reason}, headers=headers
        )
        assert hold.status_code == 200, hold.text
        assert hold.json()["created_by_name"] == world["accountant"].name
        # Faktura czekała w paczce — spór zdejmuje ją, zanim pójdzie do banku.
        assert [r["entry_id"] for r in hold.json()["released_from_batches"]] == [entry]
        row = await _plan(client, headers, entry)
        assert row["block"] == "dispute"
        assert reason in row["block_label"]
        assert world["accountant"].name in row["block_label"]
        assert row["hold"]["id"] == hold.json()["id"]
        twice = await client.post(
            f"{PAY}/holds", json={"entry_id": entry, "reason": "drugi"}, headers=headers
        )
        assert twice.status_code == 409
        listing = await client.get(f"{PAY}/holds", headers=headers)
        assert hold.json()["id"] in {h["id"] for h in listing.json()["items"]}

        released = await client.post(
            f"{PAY}/holds/{hold.json()['id']}/release",
            json={"note": "klient potwierdził zamówienie"},
            headers=headers,
        )
        assert released.status_code == 200, released.text
        row = await _plan(client, headers, entry)
        assert row["block"] is None and row["hold"] is None
    finally:
        await _cleanup(entry, client_id)


async def test_biala_lista_kontraktora_w_dniu_paczki(
    world, client, monkeypatch
) -> None:
    entry, client_id = await _contractor_entry(world, rule="off", kesu="signed")
    headers = _headers(world["accountant"])
    try:
        world["listed"].discard(CONTRACTOR_ACCOUNT)
        row = await _plan(client, headers, entry)
        assert row["block"] == "white_list_not_listed"
        assert "test-" in row["block_label"]  # identyfikator zapytania MF
        refused = await client.post(
            f"{PAY}/batches",
            json={"entry_ids": [entry], "acknowledged": [entry]},
            headers=headers,
        )
        assert refused.json()["detail"]["code"] == "blocked"

        # Rachunek wrócił do wykazu — płatność zwolniona bez niczyjej decyzji.
        world["listed"].add(CONTRACTOR_ACCOUNT)
        row = await _plan(client, headers, entry)
        assert row["block"] is None and row["white_list"]["state"] == "listed"

        # Błąd wykazu to nie zgoda: blokada z powodem.
        async def failing(*_args, **_kwargs):
            raise white_list.WhiteListError("unavailable")

        monkeypatch.setattr(white_list, "check", failing)
        row = await _plan(client, headers, entry)
        assert row["block"] == "white_list_unchecked"
        assert "unavailable" in row["block_label"]
    finally:
        await _cleanup(entry, client_id)


async def test_zajecia_tylko_z_modulem_finanse_i_slad_bez_danych(world, client) -> None:
    entry, client_id = await _contractor_entry(world, rule="off", kesu="signed")
    try:
        contract_id = await _contract_of(entry)
        body = _garnishment(contract_id)
        outsider = _headers(world["recruiter"])
        for method, path, payload in (
            ("get", f"{PAY}/garnishments", None),
            ("post", f"{PAY}/garnishments", body),
            ("post", f"{PAY}/garnishments/1/lift", {"lifted_on": "2026-11-20"}),
            ("get", f"{PAY}/holds", None),
            ("post", f"{PAY}/holds", {"entry_id": entry, "reason": "x"}),
        ):
            response = await getattr(client, method)(
                path, headers=outsider, **({"json": payload} if payload else {})
            )
            assert response.status_code == 403, (path, response.text)
        created = await client.post(
            f"{PAY}/garnishments", json=body, headers=_headers(world["accountant"])
        )
        assert created.status_code == 200, created.text
        async with AsyncSessionLocal() as db:
            events = list(
                await db.scalars(
                    select(CriticalEvent).where(
                        CriticalEvent.event_type == "contract.garnishment_add",
                        CriticalEvent.entity_id == contract_id,
                    )
                )
            )
        assert len(events) == 1
        dump = f"{events[0].entity_label} {events[0].details}"
        assert body["case_number"] not in dump and "1000" not in dump
        assert _nrb(81) not in dump
        # Kwoty z przyszłości i z dnia przed doręczeniem odrzucamy.
        future = await client.post(
            f"{PAY}/garnishments",
            json={
                **body,
                "served_on": (world["today"] + timedelta(days=1)).isoformat(),
            },
            headers=_headers(world["accountant"]),
        )
        assert future.status_code == 422
        early = await client.post(
            f"{PAY}/garnishments/{created.json()['id']}/lift",
            json={"lifted_on": "2026-11-01"},
            headers=_headers(world["accountant"]),
        )
        assert early.status_code == 422
    finally:
        await _cleanup(entry, client_id)


async def test_czesciowo_wykonanej_pozycji_z_podzialem_nie_zdejmiesz(
    world, client
) -> None:
    entry, client_id = await _contractor_entry(world, rule="off", kesu="signed")
    headers = _headers(world["accountant"])
    try:
        contract_id = await _contract_of(entry)
        created = await client.post(
            f"{PAY}/garnishments", json=_garnishment(contract_id), headers=headers
        )
        garnishment_id = created.json()["id"]
        batch = await client.post(
            f"{PAY}/batches",
            json={"entry_ids": [entry], "acknowledged": [entry], "format": "csv"},
            headers=headers,
        )
        batch_id = batch.json()["id"]
        # Bank wykonał tylko przelew do kontraktora (180 zł).
        ref = uuid.uuid4().hex[:6].upper()
        raw = _mt940(("180,00", "przelew", CONTRACTOR_ACCOUNT, f"P{ref}"))
        upload = await client.post(
            f"{PAY}/statements", files={"file": ("w.sta", raw)}, headers=headers
        )
        assert upload.status_code == 200, upload.text
        assert await _state(entry) == "in_batch"

        for path in (
            f"{PAY}/batches/{batch_id}/items/{entry}/release",
            f"{PAY}/batches/{batch_id}/cancel",
        ):
            refused = await client.post(path, headers=headers)
            assert refused.status_code == 409, path
            assert refused.json()["detail"]["code"] == "partly_executed"
        # Zmiana zajęcia też jej nie zdejmie (organ nie dostanie drugi raz).
        body = {
            k: v for k, v in _garnishment(contract_id).items() if k != "contract_id"
        }
        edited = await client.put(
            f"{PAY}/garnishments/{garnishment_id}",
            json={**body, "costs_amount": "40.00"},
            headers=headers,
        )
        assert edited.status_code == 200, edited.text
        assert edited.json()["released_from_batches"][0]["reason"] == "executed"
        # Przelew do organu Finanse oznaczają ręcznie — pozycja się kończy.
        paid = await client.post(
            f"{PAY}/entries/{entry}/paid",
            json={
                "amount": "1050.00",
                "paid_on": world["today"].isoformat(),
                "reason": "przelew do komornika potwierdzony",
            },
            headers=headers,
        )
        assert paid.status_code == 200, paid.text
        assert await _state(entry) == "paid"
        async with AsyncSessionLocal() as db:
            status = await db.scalar(
                select(FinancePaymentBatchItem.status).where(
                    FinancePaymentBatchItem.entry_id == entry
                )
            )
        assert status == "done"
    finally:
        await _cleanup(entry, client_id)


async def test_spor_blokuje_fakture_z_nipem_do_zatwierdzenia(world, client) -> None:
    from app.models.client_settlement import ClientContractorInvoice

    entry, client_id = await _contractor_entry(world, rule="off", kesu="signed")
    headers = _headers(world["accountant"])
    try:
        async with AsyncSessionLocal() as db:
            row = await db.get(FinanceCostEntry, entry)
            invoice = await db.get(ClientContractorInvoice, row.source_id)
            invoice.nip_state = "suggested"
            await db.commit()
        hold = await client.post(
            f"{PAY}/holds", json={"entry_id": entry, "reason": "spór"}, headers=headers
        )
        assert hold.status_code == 200, hold.text
        row = await _plan(client, headers, entry)
        assert row["block"] == "dispute"
    finally:
        await _cleanup(entry, client_id)


__all__ = ["COSTS"]
