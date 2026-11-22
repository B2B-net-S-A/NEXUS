"""„Podgląd PDF” faktury z kolejki kosztów (``GET /api/finance/costs/{id}/pdf``).

D2: faktury osoby zespołu sam „Moduł Finanse” nie widzi — podgląd to 404,
jak karta. Faktura kosztowa z KSeF: XML pobrany na żądanie raz i zapamiętany
(drugie otwarcie nie pyta KSeF); plik innego sprzedawcy albo inny niż
pobrany przez Płace — 409 i nic w pamięci; wyłączony KSeF — 409. Firmy,
NIP-y i kwoty fikcyjne; PDF zastąpiony atrapą (WeasyPrint sprawdza
``test_ksef_fa_visual.py``).
"""

from __future__ import annotations

import hashlib
from types import SimpleNamespace

import pytest
from sqlalchemy import select, update

from app.core.database import AsyncSessionLocal
from app.models.hr_approval import ApprovalDocument
from app.models.hr_settlement import PayrollInvoice
from app.services import storage_service
from app.services.finance_ledger import invoice_preview
from app.services.hr.ksef import fa_visual, sync, xml_cache
from app.services.hr.ksef.client import KsefApiError
from tests._fa3_samples import correction_eur
from tests import test_finance_ledger_db as ledger_db
from tests.test_finance_ledger_db import COSTS, _entry, _expense_entry, _headers

#: Fikstury świata (osoby, faktury, moduł) i klient HTTP z testów kolejki.
world = ledger_db.world
client = ledger_db.client


class FakeSource:
    def __init__(self, files: dict[str, bytes]) -> None:
        self.files = files
        self.downloads = 0

    async def __aenter__(self) -> "FakeSource":
        return self

    async def __aexit__(self, *_exc: object) -> None:
        return None

    async def download_invoice(self, ksef_number: str) -> bytes:
        self.downloads += 1
        if ksef_number not in self.files:
            raise KsefApiError("not_found")
        return self.files[ksef_number]


@pytest.fixture
def ksef(monkeypatch, tmp_path):
    """KSeF włączony (atrapa źródła), magazyn w katalogu testu, PDF jako atrapa."""

    source = FakeSource({})
    config = SimpleNamespace(enabled=True, mode="test")
    monkeypatch.setattr(storage_service, "STORAGE_ROOT", str(tmp_path))
    monkeypatch.setattr(invoice_preview, "load_config", lambda: config)
    monkeypatch.setattr(invoice_preview, "open_source", lambda *_a, **_k: source)
    monkeypatch.setattr(fa_visual, "render_pdf", lambda visual: b"%PDF-atrapa")
    monkeypatch.setattr(invoice_preview, "_downloads", invoice_preview.deque())

    async def _not_blocked(*_a, **_k):
        return None

    monkeypatch.setattr(sync, "_blocked_any", _not_blocked)
    return SimpleNamespace(source=source, config=config)


async def _ksef_of(model, row_id: int) -> str:
    async with AsyncSessionLocal() as db:
        return await db.scalar(select(model.ksef_number).where(model.id == row_id))


async def test_faktura_osoby_zespolu_bez_plac_to_404(world, client, ksef) -> None:
    payroll_entry = await _entry("payroll_invoice", world["person_invoice"].id)
    number = await _ksef_of(PayrollInvoice, world["person_invoice"].id)
    xml = correction_eur(seller_nip=world["nips"]["person"])
    ksef.source.files[number] = xml
    async with AsyncSessionLocal() as db:
        await db.execute(
            update(PayrollInvoice)
            .where(PayrollInvoice.id == world["person_invoice"].id)
            .values(xml_sha256=hashlib.sha256(xml).hexdigest())
        )
        await db.commit()

    hidden = await client.get(
        f"{COSTS}/{payroll_entry.id}/pdf", headers=_headers(world["module_only"])
    )
    assert hidden.status_code == 404
    assert hidden.json()["detail"] == "Nie ma takiej faktury w kolejce."
    assert ksef.source.downloads == 0

    for viewer in ("accountant", "admin"):
        shown = await client.get(
            f"{COSTS}/{payroll_entry.id}/pdf", headers=_headers(world[viewer])
        )
        assert shown.status_code == 200, shown.text
        assert shown.headers["content-type"] == "application/pdf"
        assert shown.content == b"%PDF-atrapa"
        assert "inline" in shown.headers["content-disposition"]
    assert ksef.source.downloads == 1  # drugie otwarcie z pamięci


async def test_inny_plik_niz_pobrany_przez_place_to_409(world, client, ksef) -> None:
    payroll_entry = await _entry("payroll_invoice", world["person_invoice"].id)
    number = await _ksef_of(PayrollInvoice, world["person_invoice"].id)
    # Skrót z fikstury to skrót numeru, nie tego pliku.
    ksef.source.files[number] = correction_eur(seller_nip=world["nips"]["person"])

    response = await client.get(
        f"{COSTS}/{payroll_entry.id}/pdf", headers=_headers(world["accountant"])
    )
    assert response.status_code == 409
    assert "różni się" in response.json()["detail"]
    assert xml_cache.load(number) is None


async def test_faktura_kosztowa_pobrana_raz_i_zapamietana(world, client, ksef) -> None:
    expense = await _expense_entry(world)
    number = await _ksef_of(ApprovalDocument, expense.source_id)
    ksef.source.files[number] = correction_eur(seller_nip=world["nips"]["supplier"])
    only = _headers(world["module_only"])

    first = await client.get(f"{COSTS}/{expense.id}/pdf", headers=only)
    assert first.status_code == 200, first.text
    assert "faktura-KOR-7-11-2026.pdf" in first.headers["content-disposition"]
    second = await client.get(f"{COSTS}/{expense.id}/pdf", headers=only)
    assert second.status_code == 200
    assert ksef.source.downloads == 1
    assert xml_cache.load(number) == ksef.source.files[number]


async def test_plik_innego_sprzedawcy_nie_trafia_do_pamieci(
    world, client, ksef
) -> None:
    expense = await _expense_entry(world)
    number = await _ksef_of(ApprovalDocument, expense.source_id)
    ksef.source.files[number] = correction_eur(seller_nip=world["nips"]["client"])

    response = await client.get(
        f"{COSTS}/{expense.id}/pdf", headers=_headers(world["accountant"])
    )
    assert response.status_code == 409
    assert "innego sprzedawcę" in response.json()["detail"]
    assert xml_cache.load(number) is None


async def test_wylaczony_ksef_i_brak_faktury_w_ksef(world, client, ksef) -> None:
    expense = await _expense_entry(world)
    headers = _headers(world["accountant"])

    missing = await client.get(f"{COSTS}/{expense.id}/pdf", headers=headers)
    assert missing.status_code == 404
    assert missing.json()["detail"] == "Nie ma tej faktury w KSeF."

    ksef.config.enabled = False
    off = await client.get(f"{COSTS}/{expense.id}/pdf", headers=headers)
    assert off.status_code == 409
    assert "wyłączone" in off.json()["detail"]


async def test_limit_pobran_na_godzine(world, client, ksef, monkeypatch) -> None:
    monkeypatch.setattr(invoice_preview, "ON_DEMAND_PER_HOUR", 0)
    expense = await _expense_entry(world)

    response = await client.get(
        f"{COSTS}/{expense.id}/pdf", headers=_headers(world["accountant"])
    )
    assert response.status_code == 503
    assert ksef.source.downloads == 0
