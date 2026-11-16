"""E-faktury Peppol przy fakturach z KSeF: zapis XML-a, stany, wysyłka, tryb testowy.

Dostawca w trybie ``simulate`` (pliki w ``tmp_path``) — bez sieci. Próbki FA
z ``tests/data/peppol`` (zanonimizowane). Numery KSeF fikcyjne (``…-EE…``).
"""

from __future__ import annotations

import hashlib
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
import pytest_asyncio
from sqlalchemy import delete, select

from app.core.config import settings as app_settings
from app.core.database import AsyncSessionLocal
from app.models.app_setting import AppSetting
from app.models.client_einvoice import ClientSalesInvoiceEinvoice as Einvoice
from app.models.client_sales_invoice import ClientSalesInvoice
from app.services.hr.ksef.client import KsefApiError
from app.services.peppol import providers as peppol_providers
from app.services.peppol import service
from app.services.peppol import settings as peppol_settings

pytestmark = pytest.mark.asyncio

DATA = Path(__file__).parent / "data" / "peppol"
PREFIX = "9876543210-20261106-EE"
_ORIGINAL_SEND = peppol_providers.SimulatedProvider.send
TEST_ADDRESS = "0088:7332545042126"


def _ksef(n: int) -> str:
    return f"{PREFIX}{n:010X}-AA"


async def _wipe() -> None:
    async with AsyncSessionLocal() as db:
        await db.execute(
            delete(ClientSalesInvoice).where(
                ClientSalesInvoice.ksef_number.like(f"{PREFIX}%")
            )
        )
        await db.execute(
            delete(AppSetting).where(AppSetting.key == peppol_settings.SETTING_KEY)
        )
        await db.commit()


@pytest_asyncio.fixture
async def env(monkeypatch, tmp_path):
    monkeypatch.setattr(app_settings, "PEPPOL_PROVIDER", "simulate")
    monkeypatch.setattr(app_settings, "PEPPOL_SIMULATE_DIR", str(tmp_path))
    monkeypatch.setattr(app_settings, "PEPPOL_SENDER_ID", "")
    # WeasyPrint potrzebuje Pango z systemu; sam PDF sprawdza test_peppol_pdf.
    monkeypatch.setattr(
        service.pdf, "render", lambda doc, ksef_number: b"%PDF-1.4 test"
    )
    await _wipe()
    yield tmp_path
    await _wipe()


async def _invoice(
    n: int,
    sample: str,
    *,
    foreign: str | None = "FI28583949",
    nip: str | None = None,
    issue: date = date(2026, 11, 6),
) -> tuple[int, bytes]:
    xml = (DATA / sample).read_bytes()
    async with AsyncSessionLocal() as db:
        invoice = ClientSalesInvoice(
            ksef_number=_ksef(n),
            xml_sha256=hashlib.sha256(xml).hexdigest(),
            buyer_foreign_id=foreign,
            buyer_nip=nip,
            buyer_name="Nordea Bank Abp",
            invoice_number=f"{n}/11/2026/UE",
            issue_date=issue,
            period_year=2026,
            period_month=10,
            period_source="invoice",
            currency="PLN",
            net_amount=Decimal("1.00"),
            gross_amount=Decimal("1.00"),
            items=[],
            order_refs=[],
            match_status="unmatched",
        )
        db.add(invoice)
        await db.commit()
        return invoice.id, xml


async def _capture(invoice_id: int, xml: bytes) -> bool:
    async with AsyncSessionLocal() as db:
        invoice = await db.get(ClientSalesInvoice, invoice_id)
        captured = await service.capture(db, invoice, xml)
        await db.commit()
        return captured


async def _row(invoice_id: int) -> Einvoice | None:
    async with AsyncSessionLocal() as db:
        return await db.scalar(
            select(Einvoice).where(Einvoice.invoice_id == invoice_id)
        )


async def test_capture_prepares_nordea_invoice_and_ignores_other_buyers(env):
    nordea_id, xml = await _invoice(1, "fa_nordea_rabat_ae.xml")
    other_id, other_xml = await _invoice(
        2, "fa_nordea_rabat_ae.xml", foreign="DE123456789"
    )
    old_id, old_xml = await _invoice(
        3, "fa_nordea_rabat_ae.xml", issue=date(2026, 10, 2)
    )

    assert await _capture(nordea_id, xml) is True
    assert await _capture(other_id, other_xml) is False
    # Faktury sprzed daty „od” nie dostają e-faktury (bez zużywania limitu KSeF).
    assert await _capture(old_id, old_xml) is False

    row = await _row(nordea_id)
    assert row.status == "ready", row.problems
    assert row.document_type == "invoice"
    assert row.receiver_key == "FI28583949"
    assert await _row(other_id) is None


async def test_send_in_test_mode_goes_to_test_address_and_reopens_in_production(env):
    invoice_id, xml = await _invoice(4, "fa_nordea_rabat_ae.xml")
    await _capture(invoice_id, xml)
    row = await _row(invoice_id)

    async with AsyncSessionLocal() as db:
        result = await service.send(db, [row.id], actor=None)
    assert result == {"sent": 1, "failed": [], "mode": "test"}

    row = await _row(invoice_id)
    assert (row.status, row.target, row.recipient) == (
        "delivered",
        "test",
        TEST_ADDRESS,
    )
    assert row.provider == "simulate" and row.provider_document_id
    assert len(row.history) == 1
    sent_file = Path(env) / f"{row.provider_document_id}.xml"
    assert (
        b'<cbc:EndpointID schemeID="0088">7332545042126</cbc:EndpointID>'
        in sent_file.read_bytes()
    )
    # PDF faktury w załączniku.
    assert b'mimeCode="application/pdf"' in sent_file.read_bytes()
    assert hashlib.sha256(sent_file.read_bytes()).hexdigest() == row.ubl_sha256

    # Ponowna wysyłka w trybie testowym — już doręczona.
    async with AsyncSessionLocal() as db:
        again = await service.send(db, [row.id], actor=None)
    assert again["sent"] == 0 and again["failed"]

    # Tryb produkcyjny: wysyłka testowa nie zamyka faktury.
    async with AsyncSessionLocal() as db:
        value = peppol_settings.validate_update(
            await peppol_settings.load(db), {"mode": "production"}
        )
        db.add(AppSetting(key=peppol_settings.SETTING_KEY, value=value))
        await db.commit()
        view = await service.list_view(db, client_id=999999, month="2026-10")
    mine = [r for r in view["rows"] if r["id"] == row.id]
    assert mine and mine[0]["status"] == "ready" and mine[0]["tested_at"]

    async with AsyncSessionLocal() as db:
        result = await service.send(db, [row.id], actor=None)
    assert result["sent"] == 1
    row = await _row(invoice_id)
    assert (row.status, row.target, row.recipient) == (
        "delivered",
        "production",
        "0088:7332545014840",
    )
    assert len(row.history) == 2


async def test_receiver_without_production_address_waits(env):
    invoice_id, xml = await _invoice(
        5, "fa_nordea_oddzial_23.xml", foreign=None, nip="1050003082"
    )
    async with AsyncSessionLocal() as db:
        value = peppol_settings.validate_update(
            peppol_settings.normalize(None), {"mode": "production"}
        )
        db.add(AppSetting(key=peppol_settings.SETTING_KEY, value=value))
        await db.commit()

    await _capture(invoice_id, xml)

    row = await _row(invoice_id)
    assert row.status == "waiting_receiver"
    assert row.receiver_key == "PL1050003082"


async def test_correction_without_amount_change_is_skipped_and_credit_note_is_sent(env):
    data_id, data_xml = await _invoice(6, "fa_nordea_korekta_data.xml")
    minus_id, minus_xml = await _invoice(7, "fa_nordea_korekta_minus.xml")
    await _capture(data_id, data_xml)
    await _capture(minus_id, minus_xml)

    assert (await _row(data_id)).status == "skipped"
    credit = await _row(minus_id)
    assert (credit.status, credit.document_type) == ("ready", "credit_note")


async def test_conversion_error_blocks_sending_with_reason(env):
    xml = (
        (DATA / "fa_nordea_eur.xml")
        .read_bytes()
        .replace(b"<P_12>np II</P_12>", b"<P_12>zw</P_12>")
    )
    invoice_id, _ = await _invoice(8, "fa_nordea_eur.xml")
    await _capture(invoice_id, xml)

    row = await _row(invoice_id)
    assert row.status == "invalid"
    assert row.problems[0]["rule"] == "unsupported_rate"
    async with AsyncSessionLocal() as db:
        result = await service.send(db, [row.id], actor=None)
    assert result["sent"] == 0
    assert "nie do wysłania" in result["failed"][0]["reason"]


async def test_rejected_delivery_is_shown_and_can_be_resent(env):
    invoice_id, xml = await _invoice(9, "fa_nordea_rabat_ae.xml")
    async with AsyncSessionLocal() as db:
        value = peppol_settings.normalize(None)
        value["receivers"][0]["test_peppol_id"] = "0208:1234567894"
        db.add(AppSetting(key=peppol_settings.SETTING_KEY, value=value))
        await db.commit()
    await _capture(invoice_id, xml)
    row = await _row(invoice_id)

    async with AsyncSessionLocal() as db:
        result = await service.send(db, [row.id], actor=None)
    row = await _row(invoice_id)
    assert row.status == "rejected"
    assert "recipient_not_found" in row.delivery_detail
    assert result["failed"][0]["reason"].startswith("recipient_not_found")


class _Source:
    def __init__(self, files: dict[str, bytes], fail: set[str] = frozenset()) -> None:
        self.files = files
        self.fail = fail
        self.calls: list[str] = []

    async def download_invoice(self, ksef_number: str) -> bytes:
        self.calls.append(ksef_number)
        if ksef_number in self.fail:
            raise KsefApiError("rate_limited", status=429, retry_after=30)
        return self.files[ksef_number]


async def test_backfill_reads_missing_xml_within_budget_and_checks_hash(env):
    good_id, good_xml = await _invoice(10, "fa_nordea_rabat_ae.xml")
    bad_id, _ = await _invoice(11, "fa_nordea_eur.xml")
    async with AsyncSessionLocal() as db:
        assert await service.scan(db) >= 2
        await db.commit()
    assert (await _row(good_id)).status == "waiting_xml"

    source = _Source({_ksef(10): good_xml, _ksef(11): b"<inny/>"})
    async with AsyncSessionLocal() as db:
        attempted, loaded = await service.backfill_xml(db, source, budget=5)
        await db.commit()

    assert (attempted, loaded) == (2, 1)
    assert (await _row(good_id)).status == "ready"
    bad = await _row(bad_id)
    assert bad.status == "invalid" and bad.problems[0]["rule"] == "xml_hash"


async def test_backfill_stops_on_ksef_rate_limit(env):
    invoice_id, xml = await _invoice(12, "fa_nordea_rabat_ae.xml")
    async with AsyncSessionLocal() as db:
        await service.scan(db)
        await db.commit()
    source = _Source({_ksef(12): xml}, fail={_ksef(12)})

    async with AsyncSessionLocal() as db:
        with pytest.raises(KsefApiError):
            await service.backfill_xml(db, source, budget=5)

    assert (await _row(invoice_id)).status == "waiting_xml"


async def test_backfill_budget_zero_downloads_nothing(env):
    await _invoice(13, "fa_nordea_rabat_ae.xml")
    source = _Source({})

    async with AsyncSessionLocal() as db:
        assert await service.backfill_xml(db, source, budget=0) == (0, 0)

    assert source.calls == []


async def test_send_refuses_without_provider(env, monkeypatch):
    monkeypatch.setattr(app_settings, "PEPPOL_PROVIDER", "off")
    async with AsyncSessionLocal() as db:
        with pytest.raises(service.EinvoiceError):
            await service.send(db, [1], actor=None)


async def test_concurrent_sends_deliver_each_invoice_once(env, monkeypatch):
    import asyncio

    from app.services.peppol import providers

    first_id, first_xml = await _invoice(20, "fa_nordea_rabat_ae.xml")
    second_id, second_xml = await _invoice(21, "fa_nordea_rabat_ae.xml")
    await _capture(first_id, first_xml)
    await _capture(second_id, second_xml)
    ids = [(await _row(first_id)).id, (await _row(second_id)).id]
    original = providers.SimulatedProvider.send
    calls: list[str] = []

    async def slow_send(self, request):
        calls.append(request.recipient)
        await asyncio.sleep(0.3)
        return await original(self, request)

    monkeypatch.setattr(providers.SimulatedProvider, "send", slow_send)

    async def one_request():
        async with AsyncSessionLocal() as db:
            return await service.send(db, ids, actor=None)

    first, second = await asyncio.gather(one_request(), one_request())

    assert len(calls) == 2
    assert first["sent"] + second["sent"] == 2


async def test_uncertain_provider_answer_waits_for_a_person(env, monkeypatch):
    from datetime import timedelta

    from sqlalchemy import update

    from app.services.peppol import providers

    invoice_id, xml = await _invoice(22, "fa_nordea_rabat_ae.xml")
    await _capture(invoice_id, xml)
    row = await _row(invoice_id)
    calls = []

    async def timeout_after_accept(self, request):
        calls.append(request.recipient)
        raise providers.ProviderError(
            "Brak odpowiedzi dostawcy.", category="network", retry=True, uncertain=True
        )

    monkeypatch.setattr(providers.SimulatedProvider, "send", timeout_after_accept)
    async with AsyncSessionLocal() as db:
        result = await service.send(db, [row.id], actor=None)
    assert result["sent"] == 0
    row = await _row(invoice_id)
    assert row.status == "sending"
    assert "przed ponowną wysyłką" in row.delivery_detail

    # Automat nie wysyła drugi raz.
    async with AsyncSessionLocal() as db:
        value = peppol_settings.validate_update(
            peppol_settings.normalize(None), {"auto_send": True}
        )
        db.add(AppSetting(key=peppol_settings.SETTING_KEY, value=value))
        await db.commit()
        await service.hourly(db)
    assert len(calls) == 1

    # Ręcznie od razu też nie (druga wysyłka mogłaby być w toku)...
    async with AsyncSessionLocal() as db:
        again = await service.send(db, [row.id], actor=None)
    assert again["sent"] == 0 and len(calls) == 1

    # ...a po czasie osoba może wysłać ponownie.
    async with AsyncSessionLocal() as db:
        await db.execute(
            update(Einvoice)
            .where(Einvoice.id == row.id)
            .values(updated_at=Einvoice.updated_at - timedelta(minutes=30))
        )
        await db.commit()
    monkeypatch.setattr(providers.SimulatedProvider, "send", _ORIGINAL_SEND)
    async with AsyncSessionLocal() as db:
        manual = await service.send(db, [row.id], actor=None)
    assert manual["sent"] == 1
    assert (await _row(invoice_id)).status == "delivered"


async def test_connection_refused_returns_invoice_to_ready(env, monkeypatch):
    from app.services.peppol import providers

    invoice_id, xml = await _invoice(23, "fa_nordea_rabat_ae.xml")
    await _capture(invoice_id, xml)
    row = await _row(invoice_id)

    async def refused(self, request):
        raise providers.ProviderError(
            "Brak połączenia z dostawcą Peppol.", category="network", retry=True
        )

    monkeypatch.setattr(providers.SimulatedProvider, "send", refused)
    async with AsyncSessionLocal() as db:
        await service.send(db, [row.id], actor=None)

    row = await _row(invoice_id)
    assert row.status == "ready"
    assert row.sent_at is None
