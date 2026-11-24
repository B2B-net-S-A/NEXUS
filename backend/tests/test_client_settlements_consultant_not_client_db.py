"""Na bazie: mail samego konsultanta ze skrzynki u klienta to nie akceptacja klienta.

Próba IX–X 2026: konsultant ma skrzynkę w domenie klienta (adres z kontraktu albo
``imie.nazwisko@`` w domenie z rejestru klientów). Jego mail z samą fakturą dawał
„Mail z akceptacją godzin jest”, a jego „Potwierdzam … h” przechodziło jako
akceptacja. Konsultanta rozpoznaje ta sama reguła co czytnik poczty
(``identity.sender_contract_ids``). Odpowiedź kierownika nadal akceptuje.
Dane fikcyjne.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import update

from app.core.database import AsyncSessionLocal
from app.models.candidate import Candidate
from app.models.client import Client
from app.models.contract import Contract
from app.services.client_settlements import service
from app.services.order_policies import known_clients
from tests.test_client_settlements_client_invoice_db import _month, _rules
from tests.test_client_settlements_consultant_db import _module, _restore
from tests.test_client_settlements_pko_velo_db import _settlement, _store, _titles
from tests.test_client_settlements_service_db import _cleanup, _world
from tests.test_client_settlements_timesheet_db import RULES, _timesheet

pytestmark = pytest.mark.asyncio

ROWS = [(3, "", "Testy", 8, None), (4, "", "Testy", 8, None)]


def _eml(sender: str, month: str, body: str) -> bytes:
    year, mon = month.split("-")
    return (
        f"From: {sender}\r\n"
        "To: rozliczenia@firma.example\r\n"
        f"Subject: Faktura {mon}.{year}\r\n"
        "Date: Mon, 2 Nov 2026 16:00:00 +0100\r\nMIME-Version: 1.0\r\n"
        "Content-Type: text/plain; charset=utf-8\r\n\r\n"
        f"{body}\r\n"
    ).encode()


async def _recompute(contract_id: int, month: str) -> dict[str, str]:
    async with AsyncSessionLocal() as db:
        s = await service._settlement(db, contract_id, month, for_update=True)
        await service.recompute_and_store(db, s)
        await db.commit()
    return _titles(await _settlement(contract_id, month))


async def _candidate_of(contract_id: int) -> tuple[str, str]:
    async with AsyncSessionLocal() as db:
        contract = await db.get(Contract, contract_id)
        candidate = await db.get(Candidate, contract.candidate_id)
        return candidate.name, candidate.lastname


async def test_mail_konsultanta_z_adresu_z_kontraktu_w_domenie_klienta(
    tmp_path, monkeypatch
) -> None:
    from app.services import storage_service

    monkeypatch.setattr(storage_service, "STORAGE_ROOT", tmp_path)
    domain = f"klient-{uuid.uuid4().hex[:8]}.example"
    consultant = f"konsultant@{domain}"
    client_id, contract_id, _line = await _world(md_total="60")
    month = _month(-1)
    previous = await _module(True)
    try:
        async with AsyncSessionLocal() as db:
            await db.execute(
                update(Contract)
                .where(Contract.id == contract_id)
                .values(candidate_email=consultant)
            )
            await db.commit()
        await _rules(
            client_id,
            {
                **RULES,
                "proof.excel_with_mail": {
                    "level": "warn",
                    "params": {"domain": domain},
                },
            },
        )
        await _store(contract_id, month, _timesheet(month, ROWS), "Time Sheet.xlsx")
        await _store(
            contract_id,
            month,
            _eml(f"Konsultant <{consultant}>", month, "W załączniku faktura."),
            "faktura.eml",
        )

        titles = await _recompute(contract_id, month)
        assert titles["Brak akceptacji klienta"] == "warn", titles
        assert "Mail z akceptacją godzin jest" not in titles

        await _store(
            contract_id,
            month,
            _eml(f"Kierownik <kierownik@{domain}>", month, "Potwierdzam."),
            "akceptacja.eml",
        )
        titles = await _recompute(contract_id, month)
        assert titles["Mail z akceptacją godzin jest"] == "ok", titles
        assert "Brak akceptacji klienta" not in titles
    finally:
        await _restore(previous)
        await _cleanup(client_id)


async def test_skrzynka_imie_nazwisko_w_domenie_klienta_z_rejestru(
    tmp_path, monkeypatch
) -> None:
    """Adres ``imie.nazwisko@<domena klienta>`` bez wpisu w kontrakcie: konsultanta
    wskazuje forma adresu i domena z rejestru klientów, jak w czytniku poczty."""

    from app.services import storage_service

    monkeypatch.setattr(storage_service, "STORAGE_ROOT", tmp_path)
    key = f"test_{uuid.uuid4().hex[:8]}"
    domain = f"{key.replace('_', '-')}.example"
    nip = f"99{uuid.uuid4().int % 10**8:08d}"
    monkeypatch.setitem(known_clients.KNOWN_REGISTRY_IDS, key, (nip,))
    monkeypatch.setitem(known_clients.KNOWN_SENDER_DOMAINS, domain, key)
    client_id, contract_id, _line = await _world(md_total="60")
    month = _month(-1)
    year, mon = month.split("-")
    previous = await _module(True)
    try:
        async with AsyncSessionLocal() as db:
            await db.execute(
                update(Client).where(Client.id == client_id).values(nip=nip)
            )
            await db.commit()
        first, last = await _candidate_of(contract_id)
        mailbox = f"{first.lower()}.{last.lower()}@{domain}"
        await _rules(
            client_id,
            {
                **RULES,
                "proof.accept_has_hours": {"level": "warn", "params": {}},
            },
        )
        await _store(contract_id, month, _timesheet(month, ROWS), "Time Sheet.xlsx")
        await _store(
            contract_id,
            month,
            _eml(
                f"{first} {last} <{mailbox}>",
                month,
                f"Potwierdzam 16 h za {mon}.{year}. W załączniku faktura.",
            ),
            "faktura.eml",
        )

        titles = await _recompute(contract_id, month)
        assert titles["Brak akceptacji klienta"] == "warn", titles
        assert "Akceptacja: 16 h za" not in " ".join(titles)

        await _store(
            contract_id,
            month,
            _eml(
                f"Kierownik <kierownik@{domain}>",
                month,
                f"Potwierdzam 16 h za {mon}.{year}.",
            ),
            "akceptacja.eml",
        )
        titles = await _recompute(contract_id, month)
        assert any(t.startswith("Akceptacja: 16 h za") for t in titles), titles
    finally:
        await _restore(previous)
        await _cleanup(client_id)
