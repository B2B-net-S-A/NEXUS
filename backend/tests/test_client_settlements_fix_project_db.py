"""Projekt FIX na bazie: odpowiedź PM-a firmy akceptuje koszt, u T&M nie.

Ten sam Time Sheet i ten sam mail PM-a („Akceptuje rozliczenie.” z domeny
firmy). Kontrakt czasowy: „Brak akceptacji klienta”. Kontrakt „FIX / produkt”
(``engagement_model = fixed``, decyzja Artura z 24.11.2026): akceptacja jest,
a karta ma notkę „Projekt FIX”. Dane fikcyjne.
"""

from __future__ import annotations

import pytest

from app.core.database import AsyncSessionLocal
from app.models.contract import Contract, EngagementModel
from app.services.client_settlements import service
from tests.test_client_settlements_client_invoice_db import _month, _rules
from tests.test_client_settlements_consultant_db import _module, _restore
from tests.test_client_settlements_pko_velo_db import _settlement, _store, _titles
from tests.test_client_settlements_service_db import _cleanup, _world
from tests.test_client_settlements_timesheet_db import RULES, _timesheet

pytestmark = pytest.mark.asyncio

COMPANY = "firma.example"


def _pm_reply(month: str) -> bytes:
    year, mon = month.split("-")
    return (
        f"From: Kierownik Projektu <pm@{COMPANY}>\r\n"
        "To: Podwykonawca <tester@gmail.com>\r\n"
        f"Subject: RE: ts {mon}.{year}\r\n"
        "Date: Mon, 2 Nov 2026 20:06:00 +0100\r\nMIME-Version: 1.0\r\n"
        "Content-Type: text/plain; charset=utf-8\r\n\r\n"
        "Akceptuje rozliczenie.\r\n\r\n"
        "From: Podwykonawca <tester@gmail.com>\r\n"
        "Sent: Monday, November 2, 2026 3:12 PM\r\n"
        "Prosba o akcept.\r\n"
    ).encode()


async def _model(contract_id: int, model: EngagementModel) -> None:
    async with AsyncSessionLocal() as db:
        contract = await db.get(Contract, contract_id)
        contract.engagement_model = model
        await db.commit()


async def _recompute(client_id: int, month: str) -> None:
    async with AsyncSessionLocal() as db:
        await service.month_view(db, client_id, month, amounts=True)
        await db.commit()


async def test_akceptacja_pma_liczy_sie_tylko_w_projekcie_fix(
    tmp_path, monkeypatch
) -> None:
    from app.services import storage_service

    monkeypatch.setattr(storage_service, "STORAGE_ROOT", tmp_path)
    from app.services.consultant_portal import identity

    # Domena firmy = domena adresu rozliczeń; w CI tego adresu nie ma.
    monkeypatch.setattr(identity, "_company_domains", lambda: frozenset({COMPANY}))
    client_id, contract_id, _line = await _world(md_total="60")
    month = _month(-1)
    previous = await _module(True)
    try:
        await _rules(
            client_id,
            {
                **RULES,
                "proof.excel_with_mail": {"level": "warn", "params": {"domain": ""}},
            },
        )
        await _store(
            contract_id,
            month,
            _timesheet(month, [(3, "", "Testy", 8, None), (4, "", "Testy", 8, None)]),
            "Time Sheet.xlsx",
        )
        await _store(contract_id, month, _pm_reply(month), "akceptacja.eml")

        await _recompute(client_id, month)
        titles = _titles(await _settlement(contract_id, month))
        assert titles["Brak akceptacji klienta"] == "warn", titles
        assert "Godziny to koszt firmy: akceptuje PM firmy" not in titles

        await _model(contract_id, EngagementModel.fixed)
        await _recompute(client_id, month)
        titles = _titles(await _settlement(contract_id, month))
        assert titles["Mail z akceptacją godzin jest"] == "ok", titles
        assert titles["Godziny to koszt firmy: akceptuje PM firmy"] == "none"
        assert "Brak akceptacji klienta" not in titles
        assert "Brak akceptacji PM-a firmy" not in titles
    finally:
        await _restore(previous)
        await _cleanup(client_id)
