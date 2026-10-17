"""Pobieranie faktur z KSeF (R1, R7): przyrostowo od znacznika HWM, tylko NIP-y zespołu.

Fałszywy serwer KSeF (``tests/_ksef_fake.py``) — bez sieci. Osoby, NIP-y,
numery KSeF i kwoty fikcyjne.
"""

from __future__ import annotations

import hashlib
import logging
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import httpx
import pytest
import pytest_asyncio
from sqlalchemy import delete, select

from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.models.app_setting import AppSetting
from app.models.hr_ops import HrJobRun
from app.models.hr_payroll import PayrollPeriod
from app.models.hr_profile import EmployeeProfile
from app.models.hr_settlement import (
    EmployeeBillingDetails,
    PayrollInvoice,
    PayrollSettlement,
)
from app.models.user import User, UserRole
from app.services.hr import job_runs, settlements
from app.services.hr.ksef import client as ksef_client
from app.services.hr.ksef import sync
from app.services.hr_foundation_schema import HR_MODULE_KEYS, HR_MODULES_SETTING
from tests._ksef_fake import (
    ANNA_CORRECTION,
    ANNA_INVOICE,
    ANNA_NIP,
    COMPANY_NIP,
    DATA_DIR,
    OLA_INVOICE,
    OLA_NIP,
    SUPPLIER_INVOICE,
    SUPPLIER_NIP,
    TOKEN,
    Clock,
    FakeKsef,
    rate_limited,
)

FIXTURE_NIPS = (OLA_NIP, ANNA_NIP, SUPPLIER_NIP)
STATE = f"test:{COMPANY_NIP}"


async def _set_setting(key: str, value) -> None:
    async with AsyncSessionLocal() as db:
        row = await db.get(AppSetting, key)
        if value is None:
            if row is not None:
                await db.delete(row)
        elif row is None:
            db.add(AppSetting(key=key, value=value))
        else:
            row.value = value
        await db.commit()


async def _person(db, *, nip: str | None) -> User:
    marker = uuid.uuid4().hex[:10]
    user = User(
        email=f"ksef-{marker}@example.com",
        name=f"Osoba Przykładowa {marker}",
        role=UserRole.employee,
        roles=["employee"],
        is_active=True,
    )
    db.add(user)
    await db.flush()
    db.add(EmployeeProfile(user_id=user.id, employment_type="b2b"))
    if nip:
        db.add(EmployeeBillingDetails(user_id=user.id, nip=nip))
    await db.flush()
    return user


async def _wipe(user_ids: list[int]) -> None:
    async with AsyncSessionLocal() as db:
        await db.execute(
            delete(PayrollInvoice).where(PayrollInvoice.seller_nip.in_(FIXTURE_NIPS))
        )
        if user_ids:
            await db.execute(
                delete(PayrollSettlement).where(PayrollSettlement.user_id.in_(user_ids))
            )
            await db.execute(
                delete(EmployeeBillingDetails).where(
                    EmployeeBillingDetails.user_id.in_(user_ids)
                )
            )
            await db.execute(
                delete(EmployeeProfile).where(EmployeeProfile.user_id.in_(user_ids))
            )
            await db.execute(delete(User).where(User.id.in_(user_ids)))
        await db.execute(delete(HrJobRun).where(HrJobRun.kind.like("ksef_%")))
        await db.execute(delete(AppSetting).where(AppSetting.key == sync.STATE_KEY))
        await db.commit()


class Env:
    def __init__(self, clock: Clock, fake: FakeKsef, ola: User, anna: User) -> None:
        self.clock = clock
        self.fake = fake
        self.ola = ola
        self.anna = anna
        self.extra_users: list[int] = []

    async def run(self, **kwargs):
        async with AsyncSessionLocal() as db:
            return await sync.run_once(
                db, now=self.clock(), transport=self.fake.transport, **kwargs
            )

    async def invoices(self) -> list[PayrollInvoice]:
        async with AsyncSessionLocal() as db:
            return list(
                await db.scalars(
                    select(PayrollInvoice)
                    .where(PayrollInvoice.seller_nip.in_(FIXTURE_NIPS))
                    .order_by(PayrollInvoice.id)
                )
            )

    async def state(self) -> dict:
        async with AsyncSessionLocal() as db:
            return await sync.load_state(db)


@pytest_asyncio.fixture
async def env(monkeypatch):
    monkeypatch.setattr(settings, "KSEF_MODE", "test")
    monkeypatch.setattr(settings, "KSEF_CONTEXT_NIP", COMPANY_NIP)
    monkeypatch.setattr(settings, "KSEF_TOKEN", TOKEN)
    monkeypatch.setattr(ksef_client, "AUTH_POLL_DELAYS", (0.0,))
    monkeypatch.setattr(ksef_client, "SERVER_ERROR_DELAYS", (0.0, 0.0))
    ksef_client.forget_sessions()
    async with AsyncSessionLocal() as db:
        previous = await db.scalar(
            select(AppSetting.value).where(AppSetting.key == HR_MODULES_SETTING)
        )
    await _wipe([])
    await _set_setting(HR_MODULES_SETTING, {key: True for key in HR_MODULE_KEYS})
    async with AsyncSessionLocal() as db:
        ola = await _person(db, nip=OLA_NIP)
        anna = await _person(db, nip=ANNA_NIP)
        await db.commit()
    clock = Clock()
    environment = Env(clock, FakeKsef(clock), ola, anna)
    yield environment
    await _wipe([ola.id, anna.id, *environment.extra_users])
    await _set_setting(
        HR_MODULES_SETTING, previous or {key: False for key in HR_MODULE_KEYS}
    )
    ksef_client.forget_sessions()


# ── Pobieranie ───────────────────────────────────────────────────────────────


async def test_tylko_faktury_od_nipow_z_danych_do_rozliczen(env, caplog):
    caplog.set_level(logging.DEBUG)
    result = await env.run()
    assert result["status"] == "ok"
    assert result["listed"] == 4
    assert result["saved"] == 3
    assert result["skipped"] == 1

    rows = await env.invoices()
    assert {row.ksef_number for row in rows} == {
        OLA_INVOICE,
        ANNA_INVOICE,
        ANNA_CORRECTION,
    }
    # Faktura dostawcy firmy: ani wiersza, ani numeru, ani NIP-u w logach.
    assert SUPPLIER_NIP not in caplog.text
    assert SUPPLIER_INVOICE not in caplog.text
    assert env.fake.count("GET", f"/invoices/ksef/{SUPPLIER_INVOICE}") == 0

    ola = next(row for row in rows if row.ksef_number == OLA_INVOICE)
    assert ola.source == "ksef"
    assert ola.user_id == env.ola.id
    assert ola.invoice_number == "FV 9/2026"
    assert (ola.period_year, ola.period_month) == (2026, 9)
    assert ola.net_amount == Decimal("16400.00")
    assert ola.gross_amount == Decimal("20172.00")
    assert ola.ksef_acquired_at == datetime(2026, 10, 3, 8, 15, tzinfo=timezone.utc)
    assert ola.xml_sha256 == hashlib.sha256(env.fake.xml[OLA_INVOICE]).hexdigest()
    assert ola.items[1]["name"] == "Premia za placement"
    assert (
        ola.match_status == "unmatched"
    )  # miesiąc bez rozliczenia — czeka na zamknięcie

    correction = next(row for row in rows if row.ksef_number == ANNA_CORRECTION)
    original = next(row for row in rows if row.ksef_number == ANNA_INVOICE)
    assert correction.invoice_kind == "correction"
    assert correction.corrects_invoice_id == original.id
    assert (correction.period_year, correction.period_month) == (2026, 9)
    assert correction.net_amount == Decimal("-120.00")

    # Pierwszy przebieg: od 1. dnia poprzedniego miesiąca (Warszawa), jako nabywca.
    query = next(
        body
        for body, call in zip(env.fake.bodies, env.fake.calls)
        if call.url.path.endswith("/invoices/query/metadata")
    )
    assert query["subjectType"] == "Subject2"
    assert query["dateRange"]["from"] == "2026-08-31T22:00:00.000+00:00"
    assert query["dateRange"]["restrictToPermanentStorageHwmDate"] is True

    state = await env.state()
    assert state["cursors"][STATE] == "2026-10-17T12:00:00.000+00:00"
    assert state["last_error"] is None
    assert state["last_counts"]["saved"] == 3
    assert TOKEN not in str(state)


async def test_kolejny_przebieg_od_znacznika_bez_duplikatow(env):
    await env.run()
    assert (await env.run())["reason"] == "already_ran"  # ta sama godzina

    env.clock.advance(hours=1)
    result = await env.run()
    assert result["status"] == "ok"
    assert result.get("saved", 0) == 0
    queries = [
        body
        for body, call in zip(env.fake.bodies, env.fake.calls)
        if call.url.path.endswith("/invoices/query/metadata")
    ]
    assert queries[-1]["dateRange"]["from"] == "2026-10-17T12:00:00.000+00:00"
    assert len(await env.invoices()) == 3
    # Drugi przebieg odświeża token zamiast logować się od nowa.
    assert env.fake.count("POST", "/auth/challenge") == 1


async def test_dopasowanie_do_rozliczenia_b2b_w_toku(env):
    async with AsyncSessionLocal() as db:
        period = await db.scalar(
            select(PayrollPeriod).where(
                PayrollPeriod.year == 2026, PayrollPeriod.month == 9
            )
        )
        created = period is None
        if created:
            period = PayrollPeriod(
                year=2026, month=9, status="closed", closed_at=env.clock()
            )
            db.add(period)
            await db.flush()
        settlement = PayrollSettlement(
            period_id=period.id,
            user_id=env.ola.id,
            employment_type="b2b",
            currency="PLN",
            expected_amount=Decimal("16400.00"),
            amount_basis="net",
            status="awaiting_document",
        )
        db.add(settlement)
        await db.commit()
        settlement_id, period_id = settlement.id, period.id
    try:
        await env.run()
        ola = next(
            row for row in await env.invoices() if row.ksef_number == OLA_INVOICE
        )
        assert ola.match_status == "matched"
        assert ola.settlement_id == settlement_id
        async with AsyncSessionLocal() as db:
            refreshed = await db.get(PayrollSettlement, settlement_id)
            assert refreshed.status in {"ready", "mismatch"}
            assert refreshed.status != "awaiting_document"
    finally:
        async with AsyncSessionLocal() as db:
            await db.execute(
                delete(PayrollInvoice).where(
                    PayrollInvoice.seller_nip.in_(FIXTURE_NIPS)
                )
            )
            await db.execute(
                delete(PayrollSettlement).where(PayrollSettlement.id == settlement_id)
            )
            if created:
                await db.execute(
                    delete(PayrollPeriod).where(PayrollPeriod.id == period_id)
                )
            await db.commit()


async def test_awaria_dopasowania_nie_zatrzymuje_pobierania(env, monkeypatch, caplog):
    async def broken(db, invoice):
        raise RuntimeError("dopasowanie padło")

    monkeypatch.setattr(settlements, "match_invoice", broken)
    result = await env.run()
    assert result["status"] == "ok"
    rows = await env.invoices()
    assert len(rows) == 3
    assert {row.match_status for row in rows} == {"unmatched"}
    assert "dopasowanie faktury" in caplog.text


async def test_faktura_niegotowa_czeka_w_kolejce(env):
    env.fake.not_ready.add(OLA_INVOICE)
    first = await env.run()
    assert first["pending"] == 1
    assert OLA_INVOICE not in {row.ksef_number for row in await env.invoices()}
    state = await env.state()
    assert state["pending"][STATE][0]["ksef_number"] == OLA_INVOICE

    env.fake.not_ready.clear()
    env.clock.advance(hours=1)
    second = await env.run()
    assert second["saved"] == 1
    assert second["pending"] == 0
    ola = next(row for row in await env.invoices() if row.ksef_number == OLA_INVOICE)
    # Data nadania numeru z metadanych przetrwała kolejkę (termin płatności B2B).
    assert ola.ksef_acquired_at == datetime(2026, 10, 3, 8, 15, tzinfo=timezone.utc)


async def test_korekta_przed_pierwotna_dopina_sie_pozniej(env):
    env.fake.not_ready.add(ANNA_INVOICE)
    await env.run()
    correction = next(
        row for row in await env.invoices() if row.ksef_number == ANNA_CORRECTION
    )
    assert correction.corrects_invoice_id is None
    assert correction.corrected_ksef_number == ANNA_INVOICE

    env.fake.not_ready.clear()
    env.clock.advance(hours=1)
    await env.run()
    rows = await env.invoices()
    original = next(row for row in rows if row.ksef_number == ANNA_INVOICE)
    correction = next(row for row in rows if row.ksef_number == ANNA_CORRECTION)
    assert correction.corrects_invoice_id == original.id
    assert (correction.period_year, correction.period_month) == (2026, 9)


async def test_dluga_blokada_429_wstrzymuje_pobieranie(env):
    env.fake.script[("POST", "/invoices/query/metadata")] = [rate_limited(900)]
    result = await env.run()
    assert result["status"] == "error"
    assert result["error"].startswith("rate_limited")
    state = await env.state()
    assert state["blocked_until"] == "2026-10-17T12:15:00.000+00:00"
    assert STATE not in (state.get("cursors") or {})  # znacznik nie przesunięty

    env.clock.advance(minutes=10)
    assert (await env.run())["reason"] == "blocked"
    async with AsyncSessionLocal() as db:
        with pytest.raises(sync.KsefSyncError) as caught:
            await sync.fetch_now(
                db, actor_id=env.ola.id, now=env.clock(), transport=env.fake.transport
            )
    assert caught.value.status_code == 409
    assert caught.value.code == "blocked"
    assert "14:15" in caught.value.message  # godzina w Warszawie


async def test_niezgodny_nip_sprzedawcy_to_problem_bez_zapisu(env):
    env.fake.xml[OLA_INVOICE] = (DATA_DIR / f"{ANNA_INVOICE}.xml").read_bytes()
    result = await env.run()
    assert result["failed"] == 1
    assert OLA_INVOICE not in {row.ksef_number for row in await env.invoices()}
    problems = (await env.state())["problems"]
    assert problems[-1] == {
        "ksef_number": OLA_INVOICE,
        "reason": "seller_mismatch",
        "at": "2026-10-17T12:00:00.000+00:00",
    }


async def test_ten_sam_nip_u_dwoch_osob_bez_osoby(env):
    async with AsyncSessionLocal() as db:
        twin = await _person(db, nip=OLA_NIP)
        await db.commit()
    env.extra_users.append(twin.id)
    await env.run()
    ola = next(row for row in await env.invoices() if row.ksef_number == OLA_INVOICE)
    assert ola.user_id is None
    assert ola.match_status == "unmatched"


async def test_okno_najwyzej_100_dni(env):
    await _set_setting(
        sync.STATE_KEY,
        {"cursors": {STATE: "2026-05-01T00:00:00.000+00:00"}},
    )
    await env.run()
    queries = [
        body["dateRange"]
        for body, call in zip(env.fake.bodies, env.fake.calls)
        if call.url.path.endswith("/invoices/query/metadata")
    ]
    assert queries[0]["from"] == "2026-05-01T00:00:00.000+00:00"
    assert queries[0]["to"] == "2026-08-08T00:00:00.000+00:00"
    assert queries[1]["from"] == "2026-08-08T00:00:00.000+00:00"
    assert "to" not in queries[1]
    assert (await env.state())["cursors"][STATE] == "2026-10-17T12:00:00.000+00:00"


# ── Wyłączenia ───────────────────────────────────────────────────────────────


async def test_tryb_off_brak_tokenu_i_modul_wylaczony(env, monkeypatch):
    monkeypatch.setattr(settings, "KSEF_MODE", "off")
    assert await env.run() == {"status": "disabled", "reason": "mode_off"}
    monkeypatch.setattr(settings, "KSEF_MODE", "prod")
    monkeypatch.setattr(settings, "KSEF_TOKEN", "")
    assert await env.run() == {"status": "disabled", "reason": "missing_token"}
    monkeypatch.setattr(settings, "KSEF_TOKEN", TOKEN)
    monkeypatch.setattr(settings, "KSEF_CONTEXT_NIP", "9876543211")
    assert (await env.run())["reason"] == "invalid_context_nip"
    monkeypatch.setattr(settings, "KSEF_MODE", "test")
    monkeypatch.setattr(settings, "KSEF_CONTEXT_NIP", COMPANY_NIP)
    await _set_setting(HR_MODULES_SETTING, {key: False for key in HR_MODULE_KEYS})
    assert await env.run() == {"status": "disabled", "reason": "module_off"}
    assert env.fake.calls == []


# ── Ręczne przebiegi ─────────────────────────────────────────────────────────


async def test_pobierz_teraz_odstep_i_trwajacy_przebieg(env):
    async with AsyncSessionLocal() as db:
        result = await sync.fetch_now(
            db, actor_id=env.ola.id, now=env.clock(), transport=env.fake.transport
        )
    assert result["saved"] == 3

    env.clock.advance(minutes=2)
    async with AsyncSessionLocal() as db:
        with pytest.raises(sync.KsefSyncError) as caught:
            await sync.fetch_now(
                db, actor_id=env.ola.id, now=env.clock(), transport=env.fake.transport
            )
    assert caught.value.code == "cooldown"

    env.clock.advance(minutes=10)
    async with AsyncSessionLocal() as db:
        await job_runs.claim(
            db, sync.LOCK_KIND, sync.LOCK_KEY, env.clock(), retake_done=True
        )
        with pytest.raises(sync.KsefSyncError) as caught:
            await sync.fetch_now(
                db, actor_id=env.ola.id, now=env.clock(), transport=env.fake.transport
            )
    assert caught.value.code == "busy"
    assert caught.value.status_code == 409


async def test_pobierz_ponownie_okres_po_dopisaniu_nipu(env):
    async with AsyncSessionLocal() as db:
        await db.execute(
            delete(EmployeeBillingDetails).where(
                EmployeeBillingDetails.user_id == env.anna.id
            )
        )
        await db.commit()
    first = await env.run()
    assert first["saved"] == 1 and first["skipped"] == 3
    cursor = (await env.state())["cursors"][STATE]

    async with AsyncSessionLocal() as db:
        db.add(EmployeeBillingDetails(user_id=env.anna.id, nip=ANNA_NIP))
        await db.commit()
    env.clock.advance(minutes=1)
    async with AsyncSessionLocal() as db:
        result = await sync.refetch_period(
            db,
            year=2026,
            month=10,
            actor_id=env.ola.id,
            seller_nip=ANNA_NIP,
            now=env.clock(),
            transport=env.fake.transport,
        )
    assert result["saved"] == 2
    body = env.fake.bodies[
        max(i for i, c in enumerate(env.fake.calls) if c.url.path.endswith("/metadata"))
    ]
    assert body["sellerNip"] == ANNA_NIP
    assert body["dateRange"]["from"] == "2026-09-30T22:00:00.000+00:00"
    # „Pobierz ponownie okres” nie rusza znacznika przyrostowego.
    assert (await env.state())["cursors"][STATE] == cursor
    rows = await env.invoices()
    correction = next(row for row in rows if row.ksef_number == ANNA_CORRECTION)
    assert correction.corrects_invoice_id is not None


@pytest.mark.parametrize(("year", "month"), [(2025, 9), (2026, 11)])
async def test_pobierz_ponownie_okres_poza_zakresem(env, year, month):
    async with AsyncSessionLocal() as db:
        with pytest.raises(sync.KsefSyncError) as caught:
            await sync.refetch_period(
                db,
                year=year,
                month=month,
                actor_id=env.ola.id,
                now=env.clock(),
                transport=env.fake.transport,
            )
    assert caught.value.status_code == 422
    assert env.fake.calls == []


async def test_awaria_ksef_przy_recznym_to_502_z_powodem(env):
    env.fake.script[("POST", "/auth/challenge")] = [
        httpx.Response(503) for _ in range(3)
    ]
    async with AsyncSessionLocal() as db:
        with pytest.raises(sync.KsefSyncError) as caught:
            await sync.fetch_now(
                db, actor_id=env.ola.id, now=env.clock(), transport=env.fake.transport
            )
    assert caught.value.status_code == 502
    assert caught.value.message == "KSeF nie odpowiada."
    state = await env.state()
    assert state["last_error"] == "unavailable (503)"
    assert state["last_error_text"] == "KSeF nie odpowiada."


# ── Tryb symulacji ───────────────────────────────────────────────────────────


async def test_tryb_simulate_czyta_pliki_bez_sieci(env, monkeypatch):
    monkeypatch.setattr(settings, "KSEF_MODE", "simulate")
    monkeypatch.setattr(settings, "KSEF_SIMULATE_DIR", str(DATA_DIR))
    async with AsyncSessionLocal() as db:
        result = await sync.run_once(db, now=env.clock())
    assert result["status"] == "ok"
    assert result["saved"] == 3
    assert result["skipped"] == 1
    assert env.fake.calls == []
    assert (await env.state())["cursors"][f"simulate:{COMPANY_NIP}"] == (
        "2026-10-17T12:00:00.000+00:00"
    )


def test_poczatkowy_znacznik_to_poczatek_poprzedniego_miesiaca():
    moment = datetime(2026, 1, 15, 10, tzinfo=timezone.utc)
    assert sync.initial_cursor(moment) == datetime(
        2025, 12, 1, tzinfo=timezone.utc
    ) + timedelta(hours=-1)


async def test_sonda_zdrowia_po_przebiegu(env, monkeypatch):
    from app.services.hr.ksef import invoices

    async with AsyncSessionLocal() as db:
        assert (
            await invoices.health_state(db, now=env.clock()) == "degraded"
        )  # bez przebiegu
    await env.run()
    async with AsyncSessionLocal() as db:
        assert await invoices.health_state(db, now=env.clock()) == "healthy"
        assert (
            await invoices.health_state(db, now=env.clock() + timedelta(hours=4))
            == "degraded"
        )
    monkeypatch.setattr(settings, "KSEF_MODE", "prod")
    async with AsyncSessionLocal() as db:
        # Udany przebieg w trybie testowym nie świadczy o produkcji.
        assert await invoices.health_state(db, now=env.clock()) == "degraded"
    monkeypatch.setattr(settings, "KSEF_MODE", "off")
    async with AsyncSessionLocal() as db:
        assert await invoices.health_state(db, now=env.clock()) == "disabled"


# ── Poprawki po przeglądzie bezpieczeństwa (17.10.2026) ─────────────────────


async def test_korekta_z_numerem_ksef_cudzej_faktury_nie_dopina_sie(env):
    # Osoba A (Anna) podaje w korekcie numer KSeF faktury osoby B (Oli).
    forged = env.fake.xml[ANNA_CORRECTION].replace(
        ANNA_INVOICE.encode(), OLA_INVOICE.encode()
    )
    env.fake.xml[ANNA_CORRECTION] = forged
    env.fake.metadata = [
        dict(item, invoiceHash="") for item in env.fake.metadata
    ]  # skrót z metadanych nie gra roli w zapisie
    env.fake.not_ready.add(OLA_INVOICE)
    await env.run()
    correction = next(
        row for row in await env.invoices() if row.ksef_number == ANNA_CORRECTION
    )
    assert correction.corrected_ksef_number == OLA_INVOICE
    assert (
        correction.corrects_invoice_id is None
    )  # wskazanie po numerze faktury Anny też nie

    # Faktura Oli przychodzi później — korekta Anny nie dopina się do niej.
    env.fake.not_ready.clear()
    env.clock.advance(hours=1)
    await env.run()
    rows = await env.invoices()
    ola = next(row for row in rows if row.ksef_number == OLA_INVOICE)
    correction = next(row for row in rows if row.ksef_number == ANNA_CORRECTION)
    assert correction.corrects_invoice_id is None
    assert ola.user_id == env.ola.id

    # Ta sama korekta, gdy faktura Oli już jest w bazie (ścieżka po numerze KSeF).
    async with AsyncSessionLocal() as db:
        await db.execute(
            delete(PayrollInvoice).where(PayrollInvoice.ksef_number == ANNA_CORRECTION)
        )
        await db.commit()
    async with AsyncSessionLocal() as db:
        await sync.refetch_period(
            db,
            year=2026,
            month=10,
            actor_id=env.ola.id,
            seller_nip=ANNA_NIP,
            now=env.clock(),
            transport=env.fake.transport,
        )
    correction = next(
        row for row in await env.invoices() if row.ksef_number == ANNA_CORRECTION
    )
    assert correction.corrects_invoice_id is None


async def test_okres_spoza_zakresu_bazy_nie_gubi_faktury(env):
    env.fake.xml[OLA_INVOICE] = env.fake.xml[OLA_INVOICE].replace(
        b"<P_6>2026-09-30</P_6>", b"<P_6>2019-12-31</P_6>"
    )
    result = await env.run()
    assert result["status"] == "ok"
    ola = next(row for row in await env.invoices() if row.ksef_number == OLA_INVOICE)
    assert ola.period_year is None
    assert ola.sale_date.year == 2019


async def test_naruszenie_ograniczenia_to_problem_a_nie_duplikat(env, monkeypatch):
    from dataclasses import replace

    from app.services.hr.ksef import fa

    real = fa.parse_invoice

    def broken_period(xml: bytes):
        parsed = real(xml)
        return (
            replace(parsed, period=(1999, 1))
            if parsed.seller_nip == OLA_NIP
            else parsed
        )

    monkeypatch.setattr(fa, "parse_invoice", broken_period)
    result = await env.run()
    assert result.get("duplicates", 0) == 0
    assert result["failed"] == 1
    assert OLA_INVOICE not in {row.ksef_number for row in await env.invoices()}
    problems = (await env.state())["problems"]
    assert problems[-1]["ksef_number"] == OLA_INVOICE
    assert problems[-1]["reason"] == "db:constraint"


async def test_wyczerpany_budzet_zapytan_przesuwa_znacznik(env, monkeypatch):
    from app.services.hr.ksef import numbers as ksef_numbers

    monkeypatch.setattr(sync, "MAX_METADATA_REQUESTS", 1)
    monkeypatch.setattr(ksef_client, "PAGE_SIZE_MAX", 10)
    template = next(
        item for item in env.fake.metadata if item["ksefNumber"] == SUPPLIER_INVOICE
    )
    suppliers = []
    for index in range(25):
        stamp = f"2026-10-01T00:{index:02d}:00.000+00:00"
        suppliers.append(
            dict(
                template,
                ksefNumber=ksef_numbers.make(
                    SUPPLIER_NIP, datetime(2026, 10, 1).date(), f"{index:012X}"
                ),
                permanentStorageDate=stamp,
                acquisitionDate=stamp,
            )
        )
    env.fake.metadata = suppliers + env.fake.metadata

    saved: set[str] = set()
    for _ in range(6):
        result = await env.run()
        saved = {row.ksef_number for row in await env.invoices()}
        if {OLA_INVOICE, ANNA_INVOICE, ANNA_CORRECTION} <= saved:
            break
        assert result.get("partial") is True
        env.clock.advance(hours=1)
    assert {OLA_INVOICE, ANNA_INVOICE, ANNA_CORRECTION} <= saved


# ── Po przeglądzie (17/18.10): brutto z KSeF niezgodne z netto i VAT ─────────


async def test_podmienione_brutto_to_rozbieznosc_a_nie_zgodna(env):
    from app.core.encryption import get_token_cipher
    from app.services.hr.bank.accounts import iban_check_digits

    bban = "99990001" + "0000000000004521"  # bank 9999xxxx nie istnieje
    account = iban_check_digits(bban) + bban
    async with AsyncSessionLocal() as db:
        details = await db.scalar(
            select(EmployeeBillingDetails).where(
                EmployeeBillingDetails.user_id == env.ola.id
            )
        )
        details.vat_status = "active"
        details.account_encrypted = get_token_cipher().encrypt(account)
        details.account_last4 = account[-4:]
        details.account_source = "white_list"
        details.account_check_request_id = "sim-fikcyjne-1"
        period = await db.scalar(
            select(PayrollPeriod).where(
                PayrollPeriod.year == 2026, PayrollPeriod.month == 9
            )
        )
        created = period is None
        if created:
            period = PayrollPeriod(
                year=2026, month=9, status="closed", closed_at=env.clock()
            )
            db.add(period)
            await db.flush()
        settlement = PayrollSettlement(
            period_id=period.id,
            user_id=env.ola.id,
            employment_type="b2b",
            currency="PLN",
            expected_amount=Decimal("16400.00"),
            amount_basis="net",
            status="awaiting_document",
        )
        db.add(settlement)
        await db.commit()
        settlement_id, period_id = settlement.id, period.id
    # Netto i VAT bez zmian, P_15 dziesięć razy większe. Faktury nie odrzucamy.
    env.fake.xml[OLA_INVOICE] = env.fake.xml[OLA_INVOICE].replace(
        b"<P_15>20172.00</P_15>", b"<P_15>201720.00</P_15>"
    )
    try:
        await env.run()
        ola = next(
            row for row in await env.invoices() if row.ksef_number == OLA_INVOICE
        )
        assert ola.match_status == "matched"
        assert ola.gross_amount == Decimal("201720.00")
        async with AsyncSessionLocal() as db:
            refreshed = await db.get(PayrollSettlement, settlement_id)
            assert refreshed.discrepancy_amount == Decimal("0.00")
            assert refreshed.status == "mismatch"
    finally:
        async with AsyncSessionLocal() as db:
            await db.execute(
                delete(PayrollInvoice).where(
                    PayrollInvoice.seller_nip.in_(FIXTURE_NIPS)
                )
            )
            await db.execute(
                delete(PayrollSettlement).where(PayrollSettlement.id == settlement_id)
            )
            if created:
                await db.execute(
                    delete(PayrollPeriod).where(PayrollPeriod.id == period_id)
                )
            await db.commit()


# ── Po przeglądzie (17/18.10): ta sama faktura z PDF-u i z KSeF ──────────────


async def test_faktura_z_ksef_laczy_sie_z_recznym_pdfem_tej_samej_faktury(env):
    async with AsyncSessionLocal() as db:
        period = await db.scalar(
            select(PayrollPeriod).where(
                PayrollPeriod.year == 2026, PayrollPeriod.month == 9
            )
        )
        created = period is None
        if created:
            period = PayrollPeriod(
                year=2026, month=9, status="closed", closed_at=env.clock()
            )
            db.add(period)
            await db.flush()
        settlement = PayrollSettlement(
            period_id=period.id,
            user_id=env.ola.id,
            employment_type="b2b",
            currency="PLN",
            expected_amount=Decimal("16400.00"),
            amount_basis="net",
            status="mismatch",
            discrepancy_amount=Decimal("0.00"),
        )
        db.add(settlement)
        await db.flush()
        # Płace dopięły PDF tej samej faktury, zanim przyszła z KSeF.
        manual = PayrollInvoice(
            source="manual_pdf",
            seller_nip=OLA_NIP,
            user_id=env.ola.id,
            invoice_number="fv 9/2026",
            issue_date=datetime(2026, 10, 3).date(),
            period_year=2026,
            period_month=9,
            currency="PLN",
            net_amount=Decimal("16400.00"),
            vat_amount=Decimal("3772.00"),
            gross_amount=Decimal("20172.00"),
            items=[],
            pdf_storage_key="payroll_invoices/aa/fikcyjna.pdf",
            pdf_sha256="b" * 64,
            settlement_id=settlement.id,
            match_status="matched",
        )
        db.add(manual)
        await db.commit()
        settlement_id, period_id, manual_id = settlement.id, period.id, manual.id
    try:
        await env.run()
        rows = [
            row
            for row in await env.invoices()
            if row.seller_nip == OLA_NIP and row.invoice_kind == "original"
        ]
        assert [row.id for row in rows] == [manual_id]
        (row,) = rows
        assert row.source == "ksef" and row.ksef_number == OLA_INVOICE
        assert row.xml_sha256 == hashlib.sha256(env.fake.xml[OLA_INVOICE]).hexdigest()
        assert row.pdf_storage_key == "payroll_invoices/aa/fikcyjna.pdf"
        assert row.ksef_acquired_at == datetime(2026, 10, 3, 8, 15, tzinfo=timezone.utc)
        assert row.settlement_id == settlement_id and row.match_status == "matched"
        async with AsyncSessionLocal() as db:
            refreshed = await db.get(PayrollSettlement, settlement_id)
            # Netto liczone raz, nie dwa razy (16 400, a nie 32 800).
            assert refreshed.discrepancy_amount == Decimal("0.00")
    finally:
        async with AsyncSessionLocal() as db:
            await db.execute(
                delete(PayrollInvoice).where(
                    PayrollInvoice.seller_nip.in_(FIXTURE_NIPS)
                )
            )
            await db.execute(
                delete(PayrollSettlement).where(PayrollSettlement.id == settlement_id)
            )
            if created:
                await db.execute(
                    delete(PayrollPeriod).where(PayrollPeriod.id == period_id)
                )
            await db.commit()


# ── Po przeglądzie (17/18.10): znacznik przy oknie przyciętym do 99 dni ──────


async def test_znacznik_nie_przeskakuje_konca_przycietego_okna(env):
    """KSeF podaje HWM całego magazynu — dalej niż koniec przyciętego okna."""

    await _set_setting(
        sync.STATE_KEY,
        {"cursors": {STATE: "2026-05-01T00:00:00.000+00:00"}},
    )
    original = env.fake._metadata

    def far_hwm(request, body, now):
        response = original(request, body, now)
        payload = response.json()
        payload["permanentStorageHwmDate"] = ksef_client.format_instant(now)
        return httpx.Response(response.status_code, json=payload)

    env.fake._metadata = far_hwm
    result = await env.run()
    assert result["status"] == "ok"
    queries = [
        body["dateRange"]
        for body, call in zip(env.fake.bodies, env.fake.calls)
        if call.url.path.endswith("/invoices/query/metadata")
    ]
    assert queries[0]["to"] == "2026-08-08T00:00:00.000+00:00"
    # Kolejne okno zaczyna się tam, gdzie skończyło poprzednie, nie na HWM.
    assert queries[1]["from"] == "2026-08-08T00:00:00.000+00:00"
    assert {row.ksef_number for row in await env.invoices()} == {
        OLA_INVOICE,
        ANNA_INVOICE,
        ANNA_CORRECTION,
    }
