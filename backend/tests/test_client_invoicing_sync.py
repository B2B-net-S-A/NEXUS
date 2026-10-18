"""Faktury sprzedażowe z KSeF (E8): ``Subject1``, zapis, dopasowanie, korekta, limity.

Fałszywy serwer KSeF (``tests/_ksef_fake.py``) z fakturami z
``tests/data/ksef/sales`` — bez sieci. NIP-y, numery KSeF i kwoty fikcyjne.
"""

from __future__ import annotations

import hashlib
import logging
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

import pytest
import pytest_asyncio
from sqlalchemy import func, select

from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.models.app_setting import AppSetting
from app.models.client import Client
from app.models.client_sales_invoice import ClientSalesInvoice, ClientSalesInvoiceLink
from app.models.contract import RateUnit
from app.services.client_invoicing import sync
from app.services.hr.ksef import client as ksef_client
from app.services.hr.ksef import sync as people_sync
from tests._ksef_fake import TOKEN, Clock, FakeKsef
from tests.client_invoicing import helpers as fx

pytestmark = pytest.mark.asyncio


class Env:
    def __init__(self, clock: Clock, fake: FakeKsef, seed: fx.Seed) -> None:
        self.clock = clock
        self.fake = fake
        self.seed = seed

    async def run(self):
        async with AsyncSessionLocal() as db:
            return await sync.run_once(
                db, now=self.clock(), transport=self.fake.transport
            )

    async def fetch(self, actor_id: int):
        async with AsyncSessionLocal() as db:
            return await sync.fetch_now(
                db, actor_id=actor_id, now=self.clock(), transport=self.fake.transport
            )


@pytest_asyncio.fixture
async def env(monkeypatch):
    monkeypatch.setattr(settings, "KSEF_MODE", "test")
    monkeypatch.setattr(settings, "KSEF_CONTEXT_NIP", fx.COMPANY_NIP)
    monkeypatch.setattr(settings, "KSEF_TOKEN", TOKEN)
    monkeypatch.setattr(ksef_client, "AUTH_POLL_DELAYS", (0.0,))
    monkeypatch.setattr(ksef_client, "SERVER_ERROR_DELAYS", (0.0, 0.0))
    ksef_client.forget_sessions()
    async with AsyncSessionLocal() as db:
        people_state = await db.get(AppSetting, people_sync.STATE_KEY)
        saved_people_state = dict(people_state.value) if people_state else None
    seed = await fx.seed_month()
    await fx.set_module(True)
    clock = Clock(datetime(2026, 11, 20, 12, 0, tzinfo=timezone.utc))
    yield Env(clock, FakeKsef(clock, data_dir=fx.DATA_DIR), seed)
    await fx.wipe()
    await fx.set_module(None)
    async with AsyncSessionLocal() as db:
        row = await db.get(AppSetting, people_sync.STATE_KEY)
        if saved_people_state is None and row is not None:
            await db.delete(row)
        elif saved_people_state is not None:
            row.value = saved_people_state
        await db.commit()
    ksef_client.forget_sessions()


async def _links(invoice_id: int) -> list[ClientSalesInvoiceLink]:
    async with AsyncSessionLocal() as db:
        return list(
            await db.scalars(
                select(ClientSalesInvoiceLink).where(
                    ClientSalesInvoiceLink.invoice_id == invoice_id
                )
            )
        )


async def test_reads_company_sales_and_links_them_to_orders(env, caplog):
    caplog.set_level(logging.INFO)
    result = await env.run()
    assert result["status"] == "ok", result
    assert result["saved"] == 5
    assert result["matched"] == 4
    # Spółka jako sprzedawca — wyłącznie ``Subject1``.
    subjects = {
        body.get("subjectType") for body in env.fake.bodies if "subjectType" in body
    }
    assert subjects == {"Subject1"}

    first = await fx.invoice(fx.KSEF_118)
    assert first.client_id == env.seed.client_id
    assert (first.period_year, first.period_month, first.period_source) == (
        2026,
        10,
        "invoice",
    )
    assert first.due_date == date(2026, 11, 17)
    assert first.order_refs == ["ZAM/2026/118"]
    assert first.match_method == "order_number"
    assert first.xml_sha256 == hashlib.sha256(env.fake.xml[fx.KSEF_118]).hexdigest()
    assert [link.order_group_id for link in await _links(first.id)] == [
        env.seed.groups["118"]
    ]

    # Numer zamówienia w nazwie pozycji: zamówienie okresowe.
    hourly = await fx.invoice(fx.KSEF_121)
    assert [link.order_id for link in await _links(hourly.id)] == [
        env.seed.orders["121"]
    ]

    # Numer wiąże mimo różnicy kwoty; korekta idzie za pierwotną.
    diff = await fx.invoice(fx.KSEF_124)
    assert diff.match_method == "order_number"
    correction = await fx.invoice(fx.KSEF_CORRECTION)
    assert correction.corrects_invoice_id == diff.id
    assert correction.match_status == "matched"
    assert correction.match_method == "correction"
    assert (correction.period_year, correction.period_month) == (2026, 10)

    unknown = await fx.invoice(fx.KSEF_UNKNOWN)
    assert unknown.client_id is None
    assert (unknown.match_status, unknown.match_reason) == (
        "unmatched",
        "unknown_buyer",
    )
    assert (unknown.period_source, unknown.period_month) == ("issue_date", 11)

    # Logi modułu bez numerów KSeF i NIP-ów nabywców (``httpx`` loguje adresy
    # tylko poniżej WARNING, a produkcja ma dla niego WARNING — logging_config).
    own = "\n".join(
        record.getMessage()
        for record in caplog.records
        if record.name.startswith("app.services.client_invoicing")
    )
    assert own
    assert fx.KSEF_118 not in own
    assert fx.CLIENT_NIP not in own


async def test_second_run_is_idempotent_and_people_state_untouched(env):
    async with AsyncSessionLocal() as db:
        before = await db.get(AppSetting, people_sync.STATE_KEY)
        before_value = dict(before.value) if before else None
    await env.run()
    env.clock.advance(hours=1)
    again = await env.run()
    assert again["status"] == "ok"
    assert again.get("saved", 0) == 0
    async with AsyncSessionLocal() as db:
        count = await db.scalar(
            select(func.count())
            .select_from(ClientSalesInvoice)
            .where(ClientSalesInvoice.ksef_number.like(f"{fx.COMPANY_NIP}-%"))
        )
        after = await db.get(AppSetting, people_sync.STATE_KEY)
    assert count == 5
    assert sum(env.fake.count("GET", f"/invoices/ksef/{n}") for n in env.fake.xml) == 5
    assert (dict(after.value) if after else None) == before_value
    state = await _state()
    assert state["cursors"][f"test:{fx.COMPANY_NIP}"]


async def _state():
    async with AsyncSessionLocal() as db:
        return await sync.load_state(db)


async def test_module_or_ksef_off_does_nothing(env, monkeypatch):
    await fx.set_module(False)
    assert (await env.run()) == {"status": "disabled", "reason": "module_off"}
    await fx.set_module(True)
    monkeypatch.setattr(settings, "KSEF_MODE", "off")
    assert (await env.run())["status"] == "disabled"
    assert env.fake.calls == []


async def test_rate_limit_from_people_fetch_blocks_sales_fetch(env):
    until = env.clock() + timedelta(minutes=30)
    async with AsyncSessionLocal() as db:
        row = await db.get(AppSetting, people_sync.STATE_KEY)
        value = dict(row.value) if row else {}
        value["blocked_until"] = until.isoformat()
        if row is None:
            db.add(AppSetting(key=people_sync.STATE_KEY, value=value))
        else:
            row.value = value
        await db.commit()
    assert (await env.run()) == {"status": "skipped", "reason": "blocked"}
    with pytest.raises(sync.SalesSyncError) as raised:
        await env.fetch(env.seed.users["finance"].id)
    assert raised.value.status_code == 409
    assert env.fake.calls == []


async def test_manual_fetch_has_a_cooldown(env):
    result = await env.fetch(env.seed.users["finance"].id)
    assert result["saved"] == 5
    env.clock.advance(minutes=2)
    with pytest.raises(sync.SalesSyncError) as raised:
        await env.fetch(env.seed.users["finance"].id)
    assert "przed chwilą" in str(raised.value)


async def test_unknown_buyer_matches_once_the_client_has_the_nip(env):
    await env.run()
    async with AsyncSessionLocal() as db:
        await fx.periodic_order(
            db,
            env.seed.other_client_id,
            "PO-SPRZET",
            rate="1000",
            unit=RateUnit.monthly,
            start=date(2026, 11, 1),
            end=date(2026, 11, 30),
        )
        client = await db.get(Client, env.seed.other_client_id)
        client.nip = fx.UNKNOWN_NIP
        await db.commit()
    env.clock.advance(hours=1)
    result = await env.run()
    assert result["rematched"] >= 1
    stored = await fx.invoice(fx.KSEF_UNKNOWN)
    assert stored.client_id == env.seed.other_client_id
    assert (stored.match_status, stored.match_method) == ("matched", "amount")


async def test_simulate_mode_reads_the_sales_folder(env, monkeypatch):
    monkeypatch.setattr(settings, "KSEF_MODE", "simulate")
    monkeypatch.setattr(settings, "KSEF_SIMULATE_DIR", str(Path(fx.DATA_DIR).parent))
    result = await env.run()
    assert result["status"] == "ok"
    assert result["saved"] == 5
    assert env.fake.calls == []
    stored = await fx.invoice(fx.KSEF_118)
    assert stored.net_amount == Decimal("25200.00")


async def test_correction_before_its_original_waits_and_then_follows_it(env):
    """Korekta, która przyszła pierwsza, nie wiąże się sama z zamówieniem."""

    from app.services.client_invoicing import fa_sales, matching

    now = env.clock()
    correction_xml = (fx.DATA_DIR / f"{fx.KSEF_CORRECTION}.xml").read_bytes()
    original_xml = (fx.DATA_DIR / f"{fx.KSEF_124}.xml").read_bytes()
    async with AsyncSessionLocal() as db:
        correction = await sync.store_invoice(
            db,
            ksef_number=fx.KSEF_CORRECTION,
            sales=fa_sales.parse_sales_invoice(correction_xml),
            xml_sha256=hashlib.sha256(correction_xml).hexdigest(),
            acquired_at=None,
            now=now,
        )
        await db.commit()
        assert correction.match_status == "unmatched"
        assert correction.match_reason == "original_missing"
    assert await _links(correction.id) == []

    async with AsyncSessionLocal() as db:
        original = await sync.store_invoice(
            db,
            ksef_number=fx.KSEF_124,
            sales=fa_sales.parse_sales_invoice(original_xml),
            xml_sha256=hashlib.sha256(original_xml).hexdigest(),
            acquired_at=None,
            now=now,
        )
        await db.commit()
        await matching.rematch_pending(db)
        await db.commit()
    stored = await fx.invoice(fx.KSEF_CORRECTION)
    assert stored.corrects_invoice_id == original.id
    assert (stored.match_status, stored.match_method) == ("matched", "correction")
