"""Faktury sprzedażowe z KSeF (E8): ``Subject1``, zapis, dopasowanie, korekta, limity.

Fałszywy serwer KSeF (``tests/_ksef_fake.py``) z fakturami z
``tests/data/ksef/sales`` — bez sieci. NIP-y, numery KSeF i kwoty fikcyjne.
"""

from __future__ import annotations

import hashlib
import logging
import re
import uuid
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
from app.models.client_einvoice import ClientSalesInvoiceEinvoice
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


async def test_hourly_run_saves_a_buyer_number_proven_by_people(env):
    """Osoby z pozycji dowodzą nabywcy: numer dopisuje przebieg, bez Finansów."""

    await env.run()
    marker = uuid.uuid4().hex[:8]
    people = [("Anna", f"Dowodowa{marker}"), ("Piotr", f"Dowodowy{marker}")]
    async with AsyncSessionLocal() as db:
        client_id = await fx.client(db, "Nabywca Z Osobami", None)
        for first, last in people:
            await fx.periodic_order(
                db,
                client_id,
                f"PO-{marker}-{first}",
                rate="1000",
                unit=RateUnit.monthly,
                person=(first, last),
            )
        stored = await db.scalar(
            select(ClientSalesInvoice).where(
                ClientSalesInvoice.ksef_number == fx.KSEF_UNKNOWN
            )
        )
        stored.items = [
            {"name": f"Usługi IT — {first} {last}"} for first, last in people
        ]
        await db.commit()
    env.clock.advance(hours=1)

    result = await env.run()

    assert result["buyer_numbers"] >= 1
    async with AsyncSessionLocal() as db:
        assert (await db.get(Client, client_id)).nip == fx.UNKNOWN_NIP
    assert (await fx.invoice(fx.KSEF_UNKNOWN)).client_id == client_id


async def test_waiting_for_download_budget_does_not_expire_the_queue(env, monkeypatch):
    """Zaległość większa niż budżet: faktura czeka, aż przyjdzie jej kolej.

    Na produkcji pierwszy przebieg widzi ponad 1500 faktur przy 20 pobraniach
    na godzinę. Czekanie nie jest nieudaną próbą — liczone jako próba wygaszało
    kolejkę po dobie, a znacznik był już za tymi fakturami.
    """

    monkeypatch.setattr(sync, "MAX_DOWNLOADS", 1)
    monkeypatch.setattr(sync, "BACKFILL_EXTRA_DOWNLOADS", 0)
    monkeypatch.setattr(sync, "MAX_PENDING_ATTEMPTS", 2)
    for _ in range(6):
        await env.run()
        env.clock.advance(hours=1)
    state = await _state()
    assert state["problems"] == []
    assert state["pending"][f"test:{fx.COMPANY_NIP}"] == []
    async with AsyncSessionLocal() as db:
        count = await db.scalar(
            select(func.count())
            .select_from(ClientSalesInvoice)
            .where(ClientSalesInvoice.ksef_number.like(f"{fx.COMPANY_NIP}-%"))
        )
    assert count == 5


async def test_real_failures_still_expire_the_queue(env, monkeypatch):
    monkeypatch.setattr(sync, "MAX_PENDING_ATTEMPTS", 2)
    env.fake.not_ready.add(fx.KSEF_UNKNOWN)
    for _ in range(3):
        await env.run()
        env.clock.advance(hours=1)
    state = await _state()
    assert [p["reason"] for p in state["problems"]] == ["pending_expired"]
    assert state["pending"][f"test:{fx.COMPANY_NIP}"] == []


async def test_eu_vat_buyer_goes_to_client_with_that_id(env):
    """Nabywca z VAT UE zamiast NIP-u (na produkcji 48% faktur sprzedażowych)."""

    xml = env.fake.xml[fx.KSEF_UNKNOWN].decode("utf-8")
    env.fake.xml[fx.KSEF_UNKNOWN] = xml.replace(
        f"<NIP>{fx.UNKNOWN_NIP}</NIP>", "<KodUE>FI</KodUE><NrVatUE>12345678</NrVatUE>"
    ).encode("utf-8")
    async with AsyncSessionLocal() as db:
        client = await db.get(Client, env.seed.other_client_id)
        client.nip = fx.EU_CLIENT_ID
        await db.commit()
    await env.run()
    stored = await fx.invoice(fx.KSEF_UNKNOWN)
    assert stored.buyer_nip is None
    assert stored.buyer_foreign_id == "FI12345678"
    assert stored.client_id == env.seed.other_client_id


async def test_non_eu_buyer_is_linked_by_registry_number_and_imported_once(env):
    registry_number = "NO123456785"
    async with AsyncSessionLocal() as db:
        other_bank_name = (await db.get(Client, env.seed.client_id)).name
        client = await db.get(Client, env.seed.other_client_id)
        client.nip = registry_number
        await db.commit()

    xml = env.fake.xml[fx.KSEF_UNKNOWN].decode("utf-8")
    env.fake.xml[fx.KSEF_UNKNOWN] = xml.replace(
        f"<NIP>{fx.UNKNOWN_NIP}</NIP><Nazwa>Firma Spoza Przykładowa</Nazwa>",
        "<KodKraju>NO</KodKraju><NrID>NO 123 456 785 MVA</NrID>"
        f"<Nazwa>{other_bank_name}</Nazwa>",
    ).encode("utf-8")
    try:
        assert (await env.run())["status"] == "ok"
        stored = await fx.invoice(fx.KSEF_UNKNOWN)
        assert stored.buyer_name == other_bank_name
        assert stored.buyer_nip is None
        assert stored.buyer_foreign_id == registry_number
        assert stored.client_id == env.seed.other_client_id
        assert (stored.match_status, stored.match_reason) == ("unmatched", "no_orders")
        assert await _links(stored.id) == []

        env.clock.advance(hours=1)
        replay = await env.run()
        assert replay["status"] == "ok"
        assert replay.get("saved", 0) == 0
        assert (await fx.invoice(fx.KSEF_UNKNOWN)).id == stored.id
        assert env.fake.count("GET", f"/invoices/ksef/{fx.KSEF_UNKNOWN}") == 1
    finally:
        async with AsyncSessionLocal() as db:
            client = await db.get(Client, env.seed.other_client_id)
            client.nip = fx.OTHER_CLIENT_NIP
            await db.commit()


async def test_person_and_rate_link_invoice_with_real_hours(env):
    """Faktura z rzeczywistymi godzinami: osoba i stawka wiążą, kwota nie musi być równa."""

    xml = env.fake.xml[fx.KSEF_UNKNOWN].decode("utf-8")
    body = re.sub(
        r"<P_7>.*?</P_7>", "<P_7>ABCD:2026-111111, Ewa Przykładowa, usługa</P_7>", xml
    )
    body = re.sub(r"<P_9A>.*?</P_9A>", "<P_9A>1000.00</P_9A>", body)
    env.fake.xml[fx.KSEF_UNKNOWN] = body.encode("utf-8")
    async with AsyncSessionLocal() as db:
        order_id = await fx.periodic_order(
            db,
            env.seed.other_client_id,
            "PO-OSOBA",
            rate="1000",
            unit=RateUnit.hourly,
            start=date(2026, 1, 1),
        )
        client = await db.get(Client, env.seed.other_client_id)
        client.nip = fx.UNKNOWN_NIP
        await db.commit()
    await env.run()
    stored = await fx.invoice(fx.KSEF_UNKNOWN)
    assert (stored.match_status, stored.match_method) == ("matched", "person")
    links = await _links(stored.id)
    assert [link.order_id for link in links] == [order_id]


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


async def test_backfill_walks_old_windows_up_to_the_first_cursor(env, monkeypatch):
    """Zaległe okna idą od ``BACKFILL_FROM`` do dnia sprzed pierwszego znacznika."""

    monkeypatch.setattr(sync, "BACKFILL_FROM", datetime(2026, 2, 1, tzinfo=sync._ZONE))
    result = await env.run()
    assert result["status"] == "ok", result
    assert result["saved"] == 5
    assert result["backfill_windows"] == 2
    key = f"test:{fx.COMPANY_NIP}"
    mark = (await _state())["backfill"][key]
    assert mark["done"] is True
    assert mark["to"] == sync.format_instant(sync.initial_cursor(env.clock()))
    # Gotowe zaległe okna nie wracają w kolejnych przebiegach.
    env.clock.advance(hours=1)
    again = await env.run()
    assert again.get("backfill_windows", 0) == 0


async def test_backfill_saves_invoices_older_than_the_first_cursor(env, monkeypatch):
    """Faktura z zaległego okna trafia do bazy i nie dubluje się z pętlą bieżącą."""

    key = f"test:{fx.COMPANY_NIP}"
    start = datetime(2026, 11, 1, tzinfo=sync._ZONE)
    async with AsyncSessionLocal() as db:
        await sync._save_state(
            db,
            {
                "cursors": {key: sync.format_instant(env.clock())},
                "backfill": {
                    key: {
                        "from": sync.format_instant(start),
                        "to": sync.format_instant(start + timedelta(days=10)),
                        "cursor": sync.format_instant(start),
                    }
                },
            },
        )
        await db.commit()
    result = await env.run()
    assert result["status"] == "ok", result
    assert result["saved"] == 5
    assert result["backfill_windows"] == 1
    assert (await _state())["backfill"][key]["done"] is True


async def test_backfill_keeps_its_place_when_the_budget_runs_out(env, monkeypatch):
    """Wyczerpany budżet zapytań: znacznik zaległych okien zostaje tam, gdzie doszedł."""

    monkeypatch.setattr(sync, "BACKFILL_FROM", datetime(2026, 2, 1, tzinfo=sync._ZONE))
    monkeypatch.setattr(sync, "MAX_METADATA_REQUESTS", 3)
    first = await env.run()
    assert first["status"] == "ok", first
    key = f"test:{fx.COMPANY_NIP}"
    mark = (await _state())["backfill"][key]
    assert not mark.get("done")
    assert mark["cursor"] != mark["from"]
    env.clock.advance(hours=1)
    await env.run()
    assert (await _state())["backfill"][key]["done"] is True


async def test_backfill_raises_the_download_budget_until_it_is_done(env, monkeypatch):
    """Dopóki trwają zaległe okna, przebieg ma dodatkowy budżet pobrań; po ``done`` — zwykły."""

    key = f"test:{fx.COMPANY_NIP}"
    assert sync._backfill_pending({}, key) is True
    assert sync._backfill_pending({"backfill": {key: {"cursor": "x"}}}, key) is True
    assert sync._backfill_pending({"backfill": {key: {"done": True}}}, key) is False
    # Budżet 1 + 3 dodatkowe: pierwszy przebieg pobiera 4 z 5 faktur, drugi resztę.
    monkeypatch.setattr(sync, "MAX_DOWNLOADS", 1)
    monkeypatch.setattr(sync, "BACKFILL_EXTRA_DOWNLOADS", 3)
    first = await env.run()
    assert first["status"] == "ok", first
    assert first["saved"] == 4


async def _finish_backfill_windows(key: str) -> None:
    """Zaległe okna wylistowane (``done``), znacznik bieżący od pierwszego przebiegu."""

    async with AsyncSessionLocal() as db:
        await sync._save_state(
            db,
            {
                "backfill": {
                    key: {
                        "from": "2025-01-01T00:00:00+00:00",
                        "to": "2026-08-01T00:00:00+00:00",
                        "cursor": "2026-08-01T00:00:00+00:00",
                        "done": True,
                    }
                }
            },
        )
        await db.commit()


async def test_download_budget_stays_raised_while_listed_backfill_waits(
    env, monkeypatch
):
    """Okna wylistowane, ale faktury czekają w kolejce na budżet: dodatkowy budżet zostaje.

    Produkcja 19.11.2026: znacznik zaległych okien doszedł do końca w kilka godzin
    (listowanie to jedno zapytanie na okno), a 494 faktury z czerwca i lipca czekały
    w kolejce na pobranie po 20 na godzinę, bo ``done`` wyłączało dodatkowe 30.
    """

    key = f"test:{fx.COMPANY_NIP}"
    assert (
        sync._backfill_pending(
            {
                "backfill": {key: {"done": True}},
                "pending": {key: [{"ksef_number": "x", "reason": "budget"}]},
            },
            key,
        )
        is True
    )
    assert (
        sync._backfill_pending(
            {
                "backfill": {key: {"done": True}},
                "pending": {key: [{"ksef_number": "x", "reason": "not_ready"}]},
            },
            key,
        )
        is False
    )
    await _finish_backfill_windows(key)
    monkeypatch.setattr(sync, "MAX_DOWNLOADS", 1)
    monkeypatch.setattr(sync, "BACKFILL_EXTRA_DOWNLOADS", 3)
    first = await env.run()
    assert first["status"] == "ok", first
    assert (first["saved"], first["pending"]) == (1, 4)
    env.clock.advance(hours=1)
    second = await env.run()
    assert second["status"] == "ok", second
    assert (second["saved"], second["pending"]) == (4, 0)


async def test_queue_downloads_the_newest_invoices_first(env, monkeypatch):
    """Kolejka zaległości nie trzyma bieżących faktur za starymi (najnowsze pierwsze)."""

    key = f"test:{fx.COMPANY_NIP}"
    await _finish_backfill_windows(key)
    monkeypatch.setattr(sync, "MAX_DOWNLOADS", 1)
    monkeypatch.setattr(sync, "BACKFILL_EXTRA_DOWNLOADS", 0)
    await env.run()
    env.clock.advance(hours=1)
    await env.run()
    async with AsyncSessionLocal() as db:
        stored = set(
            await db.scalars(
                select(ClientSalesInvoice.ksef_number).where(
                    ClientSalesInvoice.ksef_number.like(f"{fx.COMPANY_NIP}-%")
                )
            )
        )
    assert stored == {fx.KSEF_118, fx.KSEF_CORRECTION}


# ── Adres nabywcy (0730) ─────────────────────────────────────────────────────


async def _forget_address(ksef_number: str, **extra) -> int:
    """Faktura jak sprzed 0730: bez adresu i bez znacznika odczytu."""

    async with AsyncSessionLocal() as db:
        row = await db.scalar(
            select(ClientSalesInvoice).where(
                ClientSalesInvoice.ksef_number == ksef_number
            )
        )
        row.buyer_country = None
        row.buyer_address_line1 = None
        row.buyer_address_line2 = None
        row.buyer_address_read_at = None
        for name, value in extra.items():
            setattr(row, name, value)
        await db.commit()
        return row.id


def _with_address(xml: bytes, address: str) -> bytes:
    text = xml.decode("utf-8")
    old = "<Adres><KodKraju>PL</KodKraju><AdresL1>ul. Przykładowa 5</AdresL1></Adres>"
    assert text.count(old) == 1
    return text.replace(old, address).encode("utf-8")


async def test_buyer_address_is_saved_when_the_invoice_is_downloaded(env):
    env.fake.xml[fx.KSEF_UNKNOWN] = _with_address(
        env.fake.xml[fx.KSEF_UNKNOWN],
        "<Adres><KodKraju>de</KodKraju><AdresL1> Beispielstraße  7 </AdresL1>"
        "<AdresL2>10115 Berlin</AdresL2></Adres>",
    )
    result = await env.run()
    assert result["status"] == "ok", result

    first = await fx.invoice(fx.KSEF_118)
    assert (first.buyer_country, first.buyer_address_line1) == (
        "PL",
        "ul. Przykładowa 5",
    )
    assert first.buyer_address_line2 is None
    assert first.buyer_address_read_at == env.clock()
    foreign = await fx.invoice(fx.KSEF_UNKNOWN)
    assert (
        foreign.buyer_country,
        foreign.buyer_address_line1,
        foreign.buyer_address_line2,
    ) == ("DE", "Beispielstraße 7", "10115 Berlin")


async def test_invoice_without_buyer_address_is_marked_as_read(env):
    env.fake.xml[fx.KSEF_UNKNOWN] = _with_address(env.fake.xml[fx.KSEF_UNKNOWN], "")
    await env.run()
    unknown = await fx.invoice(fx.KSEF_UNKNOWN)
    assert unknown.buyer_address_line1 is None
    assert unknown.buyer_address_read_at is not None


async def test_old_invoices_get_the_address_from_ksef_once(env):
    await env.run()
    old_id = await _forget_address(fx.KSEF_118)
    # Plik pod numerem inny niż przy pobraniu — nie ta faktura, adresu nie bierzemy.
    await _forget_address(fx.KSEF_121, xml_sha256="0" * 64)

    env.clock.advance(hours=1)
    result = await env.run()
    assert result["status"] == "ok", result
    assert result["buyer_address"] == 1

    restored = await fx.invoice(fx.KSEF_118)
    assert restored.id == old_id
    assert (restored.buyer_country, restored.buyer_address_line1) == (
        "PL",
        "ul. Przykładowa 5",
    )
    other = await fx.invoice(fx.KSEF_121)
    assert other.buyer_address_line1 is None
    assert other.buyer_address_read_at is not None
    assert env.fake.count("GET", f"/invoices/ksef/{fx.KSEF_118}") == 2

    # Oba oznaczone — następny przebieg niczego nie pobiera drugi raz.
    env.clock.advance(hours=1)
    await env.run()
    assert env.fake.count("GET", f"/invoices/ksef/{fx.KSEF_118}") == 2
    assert env.fake.count("GET", f"/invoices/ksef/{fx.KSEF_121}") == 2


async def test_old_invoice_takes_the_address_from_xml_already_in_the_database(env):
    await env.run()
    old_id = await _forget_address(fx.KSEF_124)
    async with AsyncSessionLocal() as db:
        db.add(
            ClientSalesInvoiceEinvoice(
                invoice_id=old_id,
                receiver_key="test",
                status="skipped",
                fa_xml=env.fake.xml[fx.KSEF_124].decode("utf-8"),
            )
        )
        await db.commit()

    env.clock.advance(hours=1)
    result = await env.run()
    assert result["buyer_address"] == 1
    restored = await fx.invoice(fx.KSEF_124)
    assert restored.buyer_address_line1 == "ul. Przykładowa 5"
    # Bez drugiego pobrania z KSeF.
    assert env.fake.count("GET", f"/invoices/ksef/{fx.KSEF_124}") == 1
