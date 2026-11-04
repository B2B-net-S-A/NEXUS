"""Rozliczenia — płatności (R9): bramki, ustawienia, „Dla Finansów”, wyciąg.

Zakres: wyłączony moduł = 404 (admin przechodzi), bez „Płac” = 403 z nazwą
uprawnienia; lista do zapłaty pokazuje brutto faktur i tytuł z numerem KSeF,
nigdy pełnego rachunku; wyciąg MT940/CAMT.053 zamienia zatwierdzone na
„opłacono”, ten sam plik drugi raz nic nie zmienia, obce przelewy nie trafiają
do bazy, niepewne czekają na decyzję Płac. Dane fikcyjne (repo jest publiczne).
"""

from __future__ import annotations

import io
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select

from app.api import hr_payments
from app.core.database import AsyncSessionLocal
from app.core.scheduling import local_now
from app.core.encryption import TokenCipherNotConfigured
from app.models.hr_ops import HrAuditEvent
from app.models.hr_payroll import PayrollPeriod
from app.models.hr_settlement import PayrollPayment, PayrollSettlement
from app.services.hr import billing_details
from app.services.hr import settlements as settlement_service
from app.services.hr.bank import statements
from app.services.hr_foundation_schema import HR_MODULES_SETTING
from tests.hr import payments_fixtures as fx

PREFIX = "/api/hr/payments"
DATA = Path(__file__).parent / "data" / "bank"
KSEF = "1234563218-20261104-5F2A9C0D71B3-4E"
OLA_ACCOUNT = fx.account("99990002", "4521")
KUBA_ACCOUNT = fx.account("99990003", "937")
OLA_NIP = fx.nip("123456321")


@pytest_asyncio.fixture
async def client():
    """Router z aplikacji, gdy koordynator już go wpiął; inaczej sam router."""

    from app.main import app

    mounted = any(getattr(route, "path", "").startswith(PREFIX) for route in app.routes)
    target = app
    if not mounted:
        target = FastAPI()
        target.include_router(hr_payments.router, prefix=PREFIX)
    async with AsyncClient(
        transport=ASGITransport(app=target), base_url="http://testserver"
    ) as http:
        yield http


@pytest_asyncio.fixture
async def env():
    modules = await fx.get_setting(HR_MODULES_SETTING)
    payments = await fx.get_setting(fx.SETTING_KEY)
    await fx.modules(True)
    await fx.set_setting(fx.SETTING_KEY, None)
    await fx.wipe()
    yield
    await fx.wipe()
    await fx.set_setting(fx.SETTING_KEY, payments)
    await fx.set_setting(HR_MODULES_SETTING, modules)


async def _team():
    """Płace, Kadry, osoba B2B (Ola) i osoba na zleceniu (Kuba) z zatwierdzonymi rozliczeniami."""

    async with AsyncSessionLocal() as db:
        finance = await fx.make_user(db, "finance", name="Filip Finansowy")
        hr = await fx.make_user(db, "recruiter", permissions=("people_admin",))
        ola = await fx.make_user(
            db, "employee", name="Ola Nowak", profile={"employment_type": "b2b"}
        )
        kuba = await fx.make_user(
            db, "employee", name="Kuba Lato", profile={"employment_type": "zlecenie"}
        )
        await fx.set_billing(
            db,
            ola,
            nip_value=OLA_NIP,
            account_value=OLA_ACCOUNT,
            registry_name="Nowak Recruitment Ola Nowak",
        )
        await fx.set_billing(db, kuba, account_value=KUBA_ACCOUNT, source="manual")
        period = await fx.closed_period(db, 2026, 10)
        ola_s = await fx.settlement(
            db,
            period,
            ola,
            employment_type="b2b",
            expected="17160.00",
            approver=finance,
            due_on=date(2026, 11, 18),
        )
        await fx.invoice(
            db,
            ola_s,
            seller_nip=OLA_NIP,
            invoice_number="FV 10/2026",
            ksef_number=KSEF,
            net="17160.00",
            gross="21106.80",
        )
        kuba_s = await fx.settlement(
            db,
            period,
            kuba,
            employment_type="zlecenie",
            expected="1856.00",
            approver=finance,
            due_on=date(2026, 11, 10),
        )
        await db.commit()
    return finance, hr, ola, kuba, ola_s, kuba_s


async def _status(settlement_id: int) -> PayrollSettlement:
    async with AsyncSessionLocal() as db:
        return await db.get(PayrollSettlement, settlement_id)


async def _upload(client, user, name: str, content: bytes):
    return await client.post(
        f"{PREFIX}/statements",
        files={"file": (name, io.BytesIO(content), "application/octet-stream")},
        headers=fx.headers(user),
    )


# ── Bramki ────────────────────────────────────────────────────────────────────


def test_every_route_has_named_hr_gate():
    for route in hr_payments.router.routes:
        names = {
            getattr(dep.call, "__qualname__", "")
            for dep in route.dependant.dependencies
        }
        assert any("require_hr_" in name for name in names), route.path


@pytest.mark.asyncio
async def test_module_off_is_404_except_admin(client, env):
    async with AsyncSessionLocal() as db:
        finance = await fx.make_user(db, "finance")
        admin = await fx.make_user(db, "admin")
        await db.commit()
    await fx.modules(False)
    assert (
        await client.get(f"{PREFIX}/finance", headers=fx.headers(finance))
    ).status_code == 404
    assert (
        await client.get(f"{PREFIX}/finance", headers=fx.headers(admin))
    ).status_code == 200


@pytest.mark.asyncio
async def test_without_payroll_permission_is_named_403(client, env):
    async with AsyncSessionLocal() as db:
        worker = await fx.make_user(db, "employee", profile={"employment_type": "uop"})
        hr = await fx.make_user(db, "recruiter", permissions=("people_admin",))
        await db.commit()
    for user in (worker, hr):
        for path in (
            "/finance",
            "/statements",
            "/settings",
            "/nip-list.csv",
            "/batches",
        ):
            response = await client.get(f"{PREFIX}{path}", headers=fx.headers(user))
            assert response.status_code == 403, path
            assert response.json()["detail"]["permission"] == "payroll"
    # Kadry dostają paczkę Symfonii (bez kwot), zwykła osoba — nie.
    refused = await client.get(
        f"{PREFIX}/symfonia/2026/9/preview", headers=fx.headers(worker)
    )
    assert refused.status_code == 403
    assert (
        await client.get(f"{PREFIX}/symfonia/2026/9/preview", headers=fx.headers(hr))
    ).status_code == 409  # miesiąc niezamknięty, ale bramka przepuściła


# ── Ustawienia ────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_settings_defaults_and_save_keeps_other_fields(client, env):
    async with AsyncSessionLocal() as db:
        finance = await fx.make_user(db, "finance")
        await db.commit()
    await fx.set_setting(fx.SETTING_KEY, {"payout_day": 12, "obce_pole": "zostaje"})
    current = (
        await client.get(f"{PREFIX}/settings", headers=fx.headers(finance))
    ).json()
    assert current["payout_day"] == 12
    assert current["transfer_batch"]["enabled"] is False
    assert current["symfonia"]["leave_events"]["vacation"] == "Urlop wypoczynkowy"
    assert current["symfonia"]["export_sick_leave"] is False

    # Zapis samych słowników nie gubi dnia wypłaty (czyta go termin rozliczenia).
    saved = await client.put(
        f"{PREFIX}/settings",
        json={"symfonia": {**current["symfonia"], "overtime_event": "Nadgodziny 50%"}},
        headers=fx.headers(finance),
    )
    assert saved.status_code == 200, saved.text
    stored = await fx.get_setting(fx.SETTING_KEY)
    assert stored["payout_day"] == 12
    assert stored["obce_pole"] == "zostaje"
    assert stored["symfonia"]["overtime_event"] == "Nadgodziny 50%"


@pytest.mark.asyncio
async def test_payout_day_from_card_is_what_settlement_due_date_reads(client, env):
    async with AsyncSessionLocal() as db:
        finance = await fx.make_user(db, "finance")
        await db.commit()
    saved = await client.put(
        f"{PREFIX}/settings", json={"payout_day": 15}, headers=fx.headers(finance)
    )
    assert saved.status_code == 200, saved.text
    async with AsyncSessionLocal() as db:
        assert await settlement_service.load_payout_day(db) == 15


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "body, fragment",
    [
        ({"payout_day": 0}, "Dzień wypłaty"),
        ({"payout_day": 32}, "Dzień wypłaty"),
        (
            {"transfer_batch": {"enabled": True, "sender_name": "Spółka"}},
            "rachunku i nazwy nadawcy",
        ),
        (
            {"transfer_batch": {"sender_account": "PL72999900010000000000001235"}},
            "sumę kontrolną",
        ),
        ({"symfonia": {"work_start": "17:00"}}, "Początek dnia pracy"),
        ({"symfonia": {"leave_events": {"nieznany": "X"}}}, "nieznane klucze"),
    ],
)
async def test_settings_refuse_invalid_values(client, env, body, fragment):
    async with AsyncSessionLocal() as db:
        finance = await fx.make_user(db, "finance")
        await db.commit()
    response = await client.put(
        f"{PREFIX}/settings", json=body, headers=fx.headers(finance)
    )
    assert response.status_code == 422
    assert fragment in response.text
    assert "1235" not in response.text


# ── Dla Finansów ──────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_finance_list_shows_invoice_gross_and_ksef_title_without_account(
    client, env
):
    finance, _hr, ola, kuba, ola_s, kuba_s = await _team()
    async with AsyncSessionLocal() as db:
        # Korekta faktury (różnica) liczy się do kwoty do zapłaty.
        settlement = await db.get(PayrollSettlement, ola_s.id)
        await fx.invoice(
            db,
            settlement,
            seller_nip=OLA_NIP,
            invoice_number="FVK 1/2026",
            ksef_number="1234563218-20261106-0B91E4C2A7D8-1F",
            net="-100.00",
            gross="-123.00",
            kind="correction",
        )
        # Rozliczenie, które nie jest zatwierdzone, nie trafia na listę.
        other = await fx.make_user(db, "employee", profile={"employment_type": "b2b"})
        period = await db.get(PayrollPeriod, ola_s.period_id)
        await fx.settlement(
            db, period, other, employment_type="b2b", expected="900.00", status="ready"
        )
        await db.commit()

    response = await client.get(
        f"{PREFIX}/finance?year=2026&month=10", headers=fx.headers(finance)
    )
    assert response.status_code == 200, response.text
    body = response.json()
    rows = {row["name"]: row for row in body["rows"]}
    assert set(rows) == {"Ola Nowak", "Kuba Lato"}
    ola_row = rows["Ola Nowak"]
    assert ola_row["amount_to_pay"] == "20983.80"
    assert ola_row["expected_amount"] == "17160.00"
    assert KSEF in ola_row["title"]
    assert ola_row["account_last4"] == "4521"
    assert ola_row["account_source"] == "white_list"
    kuba_row = rows["Kuba Lato"]
    assert kuba_row["amount_to_pay"] is None
    assert kuba_row["title"] == "Wynagrodzenie zlecenie 10/2026"
    assert body["stats"] == {
        "payable": 2,
        "b2b": 1,
        "payroll_program": 1,
        "overdue": 0,
        "unmatched_lines": 0,
    }
    assert body["totals_to_pay"] == {"PLN": "20983.80"}
    assert OLA_ACCOUNT not in response.text and KUBA_ACCOUNT not in response.text
    assert other.id not in {row["user_id"] for row in body["rows"]}

    empty = await client.get(
        f"{PREFIX}/finance?year=2026&month=8", headers=fx.headers(finance)
    )
    assert empty.json()["rows"] == []
    half = await client.get(f"{PREFIX}/finance?year=2026", headers=fx.headers(finance))
    assert half.status_code == 422


@pytest.mark.asyncio
async def test_finance_csv_has_titles_and_no_full_account(client, env):
    finance, *_ = await _team()
    response = await client.get(
        f"{PREFIX}/finance/export.csv?year=2026&month=10", headers=fx.headers(finance)
    )
    assert response.status_code == 200
    assert "do-zaplaty-2026-10.csv" in response.headers["content-disposition"]
    text_ = response.content.decode("utf-8-sig")
    assert text_.splitlines()[0].startswith("Osoba;Forma;Okres;Dokument;Numer KSeF")
    assert KSEF in text_
    assert "21106,80" in text_
    assert "netto z programu płacowego" in text_
    assert "•• 4521 (z białej listy VAT)" in text_
    assert OLA_ACCOUNT not in text_ and KUBA_ACCOUNT not in text_
    async with AsyncSessionLocal() as db:
        logged = await db.scalar(
            select(func.count())
            .select_from(HrAuditEvent)
            .where(HrAuditEvent.action == "finance_list_exported")
        )
    assert logged >= 1


@pytest.mark.asyncio
async def test_nip_list_for_ebi24_includes_recent_leavers_only(client, env):
    async with AsyncSessionLocal() as db:
        finance = await fx.make_user(db, "finance")
        active = await fx.make_user(db, "employee", profile={"employment_type": "b2b"})
        recent = await fx.make_user(
            db,
            "employee",
            profile={
                "employment_type": "b2b",
                "employment_status": "exited",
                "last_working_day": date(2026, 9, 30),
            },
        )
        old = await fx.make_user(
            db,
            "employee",
            profile={
                "employment_type": "b2b",
                "employment_status": "exited",
                "last_working_day": date(2025, 12, 31),
            },
        )
        await fx.set_billing(db, active, nip_value=fx.nip("777777777"))
        await fx.set_billing(db, recent, nip_value=fx.nip("555000000"))
        await fx.set_billing(db, old, nip_value=fx.nip("987654321"))
        await db.commit()
    response = await client.get(f"{PREFIX}/nip-list.csv", headers=fx.headers(finance))
    assert response.status_code == 200
    text_ = response.content.decode("utf-8-sig")
    assert fx.nip("777777777") in text_
    assert fx.nip("555000000") in text_
    assert fx.nip("987654321") not in text_


# ── Wyciąg ────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_mt940_marks_paid_and_skips_unrelated_operations(client, env):
    finance, _hr, ola, kuba, ola_s, kuba_s = await _team()
    raw = (DATA / "mt940_listopad.sta").read_bytes()
    response = await _upload(client, finance, "wyciag.sta", raw)
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["format"] == "mt940"
    assert result["operations"] == 5
    assert result["matched"] == 2
    assert result["unmatched"] == 0
    # Czynsz, uznanie i storno nie dotyczą nikogo z zespołu — nie trafiają do bazy.
    assert result["skipped"] == 3
    assert {row["name"] for row in result["paid"]} == {"Ola Nowak", "Kuba Lato"}
    assert OLA_ACCOUNT not in response.text

    ola_after = await _status(ola_s.id)
    assert ola_after.status == "paid"
    assert ola_after.paid_source == "statement"
    assert ola_after.paid_amount == Decimal("21106.80")
    kuba_after = await _status(kuba_s.id)
    assert kuba_after.status == "paid"
    # Zlecenie: na rękę z Symfonii (mniej niż brutto) — opłacone kwotą z banku.
    assert kuba_after.paid_amount == Decimal("1612.00")

    async with AsyncSessionLocal() as db:
        stored = list(
            await db.scalars(
                select(PayrollPayment).where(PayrollPayment.kind == "statement_line")
            )
        )
        events = list(
            await db.scalars(
                select(HrAuditEvent).where(HrAuditEvent.action == "statement_imported")
            )
        )
    assert len(stored) == 2
    assert {p.counterparty_last4 for p in stored} == {"4521", "0937"}
    assert all(p.match_status == "matched" for p in stored)
    assert events and OLA_ACCOUNT not in str(events[-1].details)

    # Ten sam plik drugi raz: nic nowego.
    again = await _upload(client, finance, "wyciag.sta", raw)
    assert again.status_code == 200
    assert again.json()["already_imported"] is True
    async with AsyncSessionLocal() as db:
        count = await db.scalar(
            select(func.count())
            .select_from(PayrollPayment)
            .where(PayrollPayment.kind == "statement_line")
        )
    assert count == 2


@pytest.mark.asyncio
async def test_same_operation_on_second_statement_is_ignored_as_duplicate(client, env):
    finance, *_ = await _team()
    await _upload(
        client, finance, "wyciag.sta", (DATA / "mt940_listopad.sta").read_bytes()
    )
    response = await _upload(
        client, finance, "wyciag.xml", (DATA / "camt053_listopad.xml").read_bytes()
    )
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["format"] == "camt053"
    # Faktura Oli ma ten sam numer operacji banku, kwotę i dzień — duplikat.
    assert result["duplicates"] == 1
    # Przelew Kuby z innym numerem operacji: rozliczenie już opłacone → do decyzji.
    assert result["unmatched"] == 1
    overview = (
        await client.get(f"{PREFIX}/statements", headers=fx.headers(finance))
    ).json()
    assert len(overview["recent"]) == 2
    (line,) = overview["unmatched"]
    assert line["amount"] == "1612.00"
    assert line["reason"] == "Osoba nie ma rozliczenia do zapłaty."


@pytest.mark.asyncio
async def test_ksef_number_with_other_amount_waits_for_decision(client, env):
    finance, _hr, ola, _kuba, ola_s, _kuba_s = await _team()
    raw = (
        (DATA / "mt940_listopad.sta").read_bytes().replace(b"DN21106,80", b"DN21000,00")
    )
    result = (await _upload(client, finance, "wyciag.sta", raw)).json()
    assert result["unmatched"] == 1
    assert (await _status(ola_s.id)).status == "approved"

    overview = (
        await client.get(f"{PREFIX}/statements", headers=fx.headers(finance))
    ).json()
    line = next(item for item in overview["unmatched"] if item["amount"] == "21000.00")
    assert line["reason"] == "Kwota przelewu inna niż do zapłaty."
    assert [hint["settlement_id"] for hint in line["hints"]] == [ola_s.id]

    short = await client.post(
        f"{PREFIX}/statement-lines/{line['id']}/ignore",
        json={"reason": "no"},
        headers=fx.headers(finance),
    )
    assert short.status_code == 422
    # Decyzja Artura 19.10.2026: przelew B2B o kwocie innej niż brutto faktur
    # nie opłaca rozliczenia ręcznym „Przypisz” — odmowa z obiema kwotami.
    assigned = await client.post(
        f"{PREFIX}/statement-lines/{line['id']}/assign",
        json={"settlement_id": ola_s.id},
        headers=fx.headers(finance),
    )
    assert assigned.status_code == 422, assigned.text
    assert "21000,00" in assigned.text and "21106,80" in assigned.text
    assert (await _status(ola_s.id)).status == "approved"
    async with AsyncSessionLocal() as db:
        stored = await db.get(PayrollPayment, line["id"])
    assert stored.match_status == "unmatched" and stored.settlement_id is None
    missing = await client.post(
        f"{PREFIX}/statement-lines/999999999/ignore",
        json={"reason": "Przelew zwrotny"},
        headers=fx.headers(finance),
    )
    assert missing.status_code == 404


@pytest.mark.asyncio
async def test_payment_to_other_account_is_flagged(client, env):
    finance, _hr, ola, *_ = await _team()
    other = fx.account("99990009", "9999")
    raw = (
        (DATA / "mt940_listopad.sta")
        .read_bytes()
        .replace(b"~38PL53999900020000000000004521", f"~38PL{other}".encode())
    )
    result = (await _upload(client, finance, "wyciag.sta", raw)).json()
    assert result["matched"] == 2
    (warning,) = result["warnings"]
    assert warning["code"] == "other_account"
    assert warning["name"] == "Ola Nowak"
    assert other not in str(result)


@pytest.mark.asyncio
async def test_unreadable_accounts_still_match_by_ksef(client, env, monkeypatch):
    finance, _hr, _ola, _kuba, ola_s, kuba_s = await _team()

    def broken(_details):
        raise TokenCipherNotConfigured("klucz")

    monkeypatch.setattr(billing_details, "decrypt_account", broken)
    result = (
        await _upload(
            client, finance, "wyciag.sta", (DATA / "mt940_listopad.sta").read_bytes()
        )
    ).json()
    assert result["accounts_unreadable"] is True
    assert (await _status(ola_s.id)).status == "paid"
    assert (await _status(kuba_s.id)).status == "approved"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "content, fragment",
    [
        (b"", "pusty"),
        (b"Data;Kwota\n2026-11-01;10\n", "Nie rozpoznaję formatu"),
        (b"<?xml version='1.0'?><Document><BkToCstmrStmt>", "uszkodzony"),
    ],
)
async def test_wrong_statement_files_are_refused(client, env, content, fragment):
    async with AsyncSessionLocal() as db:
        finance = await fx.make_user(db, "finance")
        await db.commit()
    response = await _upload(client, finance, "plik.txt", content)
    assert response.status_code == 422
    assert fragment in response.text


@pytest.mark.asyncio
async def test_too_large_statement_is_refused(client, env, monkeypatch):
    async with AsyncSessionLocal() as db:
        finance = await fx.make_user(db, "finance")
        await db.commit()
    monkeypatch.setattr(statements, "MAX_STATEMENT_BYTES", 100)
    response = await _upload(
        client, finance, "wyciag.sta", (DATA / "mt940_listopad.sta").read_bytes()
    )
    assert response.status_code == 422
    assert "większy niż" in response.text


# ── Dopasowanie (czyste reguły) ───────────────────────────────────────────────


def _candidate(**changes):
    values = dict(
        settlement_id=1,
        user_id=10,
        employment_type="zlecenie",
        currency="PLN",
        status="approved",
        year=2026,
        month=10,
        expected_amount=Decimal("2000.00"),
        pay_amount=None,
    )
    values.update(changes)
    return statements.Candidate(**values)


def _line(title: str, amount: str, account=None):
    from app.services.hr.bank.parsed import StatementLine

    return StatementLine(
        index=1,
        booked_on=date(2026, 11, 10),
        amount=Decimal(amount),
        direction="debit",
        currency="PLN",
        title=title,
        counterparty_account=account,
    )


def test_period_in_title_breaks_tie_between_two_months():
    september = _candidate(settlement_id=1, month=9)
    october = _candidate(settlement_id=2, month=10)
    accounts = {KUBA_ACCOUNT: {10}}
    decision = statements.decide(
        _line("Wynagrodzenie za październik 2026", "1500.00", KUBA_ACCOUNT),
        [september, october],
        accounts,
    )
    assert decision.settlement_id == 2
    numeric = statements.decide(
        _line("Wyplata 09/2026", "1500.00", KUBA_ACCOUNT),
        [september, october],
        accounts,
    )
    assert numeric.settlement_id == 1
    unclear = statements.decide(
        _line("Wynagrodzenie", "1500.00", KUBA_ACCOUNT), [september, october], accounts
    )
    assert unclear.settlement_id is None and unclear.related
    # Bez miesiąca w tytule zlecenie nie jest opłacane po samej kwocie.
    assert unclear.reason == "no_period"


def test_mandate_transfer_above_gross_is_not_matched():
    decision = statements.decide(
        _line("Wynagrodzenie zlecenie 10/2026", "2500.00", KUBA_ACCOUNT),
        [_candidate()],
        {KUBA_ACCOUNT: {10}},
    )
    assert decision.settlement_id is None
    assert decision.reason == "amount_differs"


def test_unrelated_transfer_is_not_kept():
    decision = statements.decide(
        _line("Czynsz", "4000.00", fx.account("99990004", "7777")), [_candidate()], {}
    )
    assert decision.related is False


def test_invoice_number_without_account_matches_when_amount_fits():
    candidate = _candidate(
        employment_type="b2b",
        pay_amount=Decimal("2460.00"),
        invoice_numbers=("FV 7/2026",),
    )
    decision = statements.decide(_line("Zapłata FV 7/2026", "2460.00"), [candidate], {})
    assert decision.settlement_id == 1 and decision.reason == "invoice_number"


# ── Po przeglądzie (17.10): rachunek w tytule, zlecenie bez miesiąca, podwójna zapłata ──


@pytest.mark.asyncio
async def test_full_account_in_statement_title_is_masked(client, env):
    finance, _hr, _ola, kuba, _ola_s, kuba_s = await _team()
    mt = (
        ":20:X\r\n:25:/PL72999900010000000000001234\r\n:60F:C261117PLN100,00\r\n"
        ":61:2611181118DN9999,00NTRFNONREF//BR-MASK-1\r\n"
        f":86:Przelew PL{KUBA_ACCOUNT} Kuba Lato premia\r\n-"
    ).encode()
    result = (await _upload(client, finance, "wyciag.sta", mt)).json()
    assert result["unmatched"] == 1
    overview = await client.get(f"{PREFIX}/statements", headers=fx.headers(finance))
    assert KUBA_ACCOUNT not in overview.text
    assert "•• 0937" in overview.text
    camt = (
        (DATA / "camt053_listopad.xml")
        .read_bytes()
        .replace(
            b"<Ustrd>Wynagrodzenie zlecenie 10/2026</Ustrd>",
            f"<Ustrd>Wynagrodzenie na PL{KUBA_ACCOUNT}</Ustrd>".encode(),
        )
    )
    await _upload(client, finance, "wyciag.xml", camt)
    async with AsyncSessionLocal() as db:
        titles = [
            title
            for title in await db.scalars(
                select(PayrollPayment.title).where(
                    PayrollPayment.kind == "statement_line"
                )
            )
        ]
    assert titles and all(KUBA_ACCOUNT not in (title or "") for title in titles)
    assert (await _status(kuba_s.id)).status == "approved"


@pytest.mark.asyncio
async def test_mandate_transfer_needs_month_of_settlement_in_title(client, env):
    finance, _hr, _ola, kuba, _ola_s, kuba_s = await _team()
    for ref, title in (
        ("BR-DELEG", "Zwrot kosztow delegacji 09/2026"),
        ("BR-NOMONTH", "Wynagrodzenie"),
    ):
        mt = (
            ":20:X\r\n:25:/PL72999900010000000000001234\r\n:60F:C261117PLN100,00\r\n"
            f":61:2611181118DN120,00NTRFNONREF//{ref}\r\n"
            f":86:020~00TRF~20{title}~38PL{KUBA_ACCOUNT}\r\n-"
        ).encode()
        result = (await _upload(client, finance, f"{ref}.sta", mt)).json()
        assert result["matched"] == 0 and result["unmatched"] == 1, title
    assert (await _status(kuba_s.id)).status == "approved"


@pytest.mark.asyncio
async def test_second_payment_of_paid_invoice_is_flagged_not_swallowed(client, env):
    finance, _hr, _ola, _kuba, ola_s, _kuba_s = await _team()
    line = (
        ":61:2611181118DN21106,80NTRFNONREF//{ref}\r\n"
        f":86:020~00TRF~20FV 10/2026 {KSEF}~38PL{OLA_ACCOUNT}\r\n"
    )
    mt = (
        ":20:X\r\n:25:/PL72999900010000000000001234\r\n:60F:C261117PLN100,00\r\n"
        + line.format(ref="BR-PAY-1")
        + line.format(ref="BR-PAY-2")
        + "-"
    ).encode()
    result = (await _upload(client, finance, "wyciag.sta", mt)).json()
    assert result["matched"] == 1
    assert result["unmatched"] == 1
    assert result["already_paid"] == 0
    overview = (
        await client.get(f"{PREFIX}/statements", headers=fx.headers(finance))
    ).json()
    (waiting,) = overview["unmatched"]
    assert "było już opłacone" in waiting["reason"]
    assert (await _status(ola_s.id)).paid_amount == Decimal("21106.80")


# ── Po przeglądzie (17/18.10): przypisanie operacji z wyciągu ────────────────


@pytest.mark.asyncio
async def test_operacji_nie_przypiszesz_do_wlasnego_ani_oplaconego_rozliczenia(
    client, env
):
    finance, _hr, _ola, _kuba, ola_s, _kuba_s = await _team()
    async with AsyncSessionLocal() as db:
        period = await db.get(PayrollPeriod, ola_s.period_id)
        own = await fx.settlement(
            db, period, finance, employment_type="uop", expected="9000.00"
        )
        await db.commit()
    raw = (
        (DATA / "mt940_listopad.sta").read_bytes().replace(b"DN21106,80", b"DN21000,00")
    )
    await _upload(client, finance, "wyciag.sta", raw)
    overview = (
        await client.get(f"{PREFIX}/statements", headers=fx.headers(finance))
    ).json()
    line = next(item for item in overview["unmatched"] if item["amount"] == "21000.00")
    url = f"{PREFIX}/statement-lines/{line['id']}/assign"

    mine = await client.post(
        url, json={"settlement_id": own.id}, headers=fx.headers(finance)
    )
    assert mine.status_code == 403, mine.text

    async with AsyncSessionLocal() as db:
        target = await db.get(PayrollSettlement, ola_s.id)
        await settlement_service.mark_paid(
            db,
            target,
            source="manual",
            amount=Decimal("21106.80"),
            paid_on=date(2026, 11, 18),
            actor_id=finance.id,
            reason="Przelew z banku poza NEXUSEM",
        )
        await db.commit()
    paid = await client.post(
        url, json={"settlement_id": ola_s.id}, headers=fx.headers(finance)
    )
    assert paid.status_code == 409, paid.text
    async with AsyncSessionLocal() as db:
        stored = await db.get(PayrollPayment, line["id"])
    assert stored.match_status == "unmatched" and stored.settlement_id is None


# ── Po przeglądzie (17/18.10): rachunek nadawcy w odpowiedzi tylko jako 4 cyfry ──


@pytest.mark.asyncio
async def test_rachunek_nadawcy_w_ustawieniach_tylko_jako_cztery_cyfry(client, env):
    company = fx.account("99990001", "1234")
    async with AsyncSessionLocal() as db:
        finance = await fx.make_user(db, "finance")
        await db.commit()
    saved = await client.put(
        f"{PREFIX}/settings",
        json={
            "transfer_batch": {
                "enabled": True,
                "format": "elixir",
                "sender_account": company,
                "sender_name": "Spółka Przykładowa S.A.",
            }
        },
        headers=fx.headers(finance),
    )
    assert saved.status_code == 200, saved.text
    assert company not in saved.text
    current = await client.get(f"{PREFIX}/settings", headers=fx.headers(finance))
    assert company not in current.text and company[2:10] not in current.text
    batch = current.json()["transfer_batch"]
    assert batch["sender_account_last4"] == "1234"
    assert "sender_account" not in batch

    # Formularz bez nowego rachunku (pole puste) zostawia zapisany.
    again = await client.put(
        f"{PREFIX}/settings",
        json={
            "transfer_batch": {
                "enabled": True,
                "format": "csv",
                "sender_account": None,
                "sender_name": "Spółka Przykładowa S.A.",
            }
        },
        headers=fx.headers(finance),
    )
    assert again.status_code == 200, again.text
    stored = await fx.get_setting(fx.SETTING_KEY)
    assert stored["transfer_batch"]["sender_account"] == company
    assert stored["transfer_batch"]["format"] == "csv"


# ── Audyt A2 (19.10.2026): własne rozliczenie i ręczne „Przypisz” ─────────────


@pytest.mark.asyncio
async def test_wyciag_nie_oplaca_rozliczenia_osoby_ktora_go_wgrala(client, env):
    finance, hr, _ola, _kuba, ola_s, _kuba_s = await _team()
    own_account = fx.account("99990008", "8008")
    async with AsyncSessionLocal() as db:
        period = await db.get(PayrollPeriod, ola_s.period_id)
        await fx.set_billing(db, finance, account_value=own_account, source="manual")
        own = await fx.settlement(
            db,
            period,
            finance,
            employment_type="zlecenie",
            expected="3000.00",
            approver=hr,
        )
        second = await fx.make_user(db, "finance", name="Fabian Drugi")
        await db.commit()
    mt = (
        ":20:X\r\n:25:/PL72999900010000000000001234\r\n:60F:C261117PLN100,00\r\n"
        ":61:2611181118DN2400,00NTRFNONREF//BR-OWN\r\n"
        f":86:020~00TRF~20Wynagrodzenie zlecenie 10/2026~38PL{own_account}\r\n-"
    ).encode()
    result = (await _upload(client, finance, "wlasny.sta", mt)).json()
    assert result["matched"] == 0 and result["unmatched"] == 1
    assert (await _status(own.id)).status == "approved"
    overview = (
        await client.get(f"{PREFIX}/statements", headers=fx.headers(second))
    ).json()
    (line,) = overview["unmatched"]
    assert "wgrała wyciąg" in line["reason"]
    # Ten sam wiersz przypisuje ktoś inny z Płac.
    assigned = await client.post(
        f"{PREFIX}/statement-lines/{line['id']}/assign",
        json={"settlement_id": own.id},
        headers=fx.headers(second),
    )
    assert assigned.status_code == 200, assigned.text
    assert (await _status(own.id)).status == "paid"


@pytest.mark.asyncio
async def test_przypisz_nie_oplaca_rozbieznosci_a_zgodna_kwote_przyjmuje(client, env):
    finance, _hr, _ola, _kuba, ola_s, _kuba_s = await _team()
    async with AsyncSessionLocal() as db:
        target = await db.get(PayrollSettlement, ola_s.id)
        target.status = "mismatch"
        target.approved_by = None
        target.approved_at = None
        target.discrepancy_amount = Decimal("120.00")
        line = PayrollPayment(
            kind="statement_line",
            match_status="unmatched",
            amount=Decimal("21106.80"),
            currency="PLN",
            booked_on=date(2026, 11, 18),
            title="Przelew bez numeru faktury",
            statement_sha256="a" * 64,
            statement_format="mt940",
            statement_line_ref="1:BR-RECZNY",
            created_by=finance.id,
        )
        db.add(line)
        await db.commit()
        line_id = line.id
    second = await _second_payroll()
    url = f"{PREFIX}/statement-lines/{line_id}/assign"
    refused = await client.post(
        url, json={"settlement_id": ola_s.id}, headers=fx.headers(second)
    )
    assert refused.status_code == 409, refused.text
    assert "Uznaj różnicę" in refused.text
    assert (await _status(ola_s.id)).status == "mismatch"

    async with AsyncSessionLocal() as db:
        target = await db.get(PayrollSettlement, ola_s.id)
        target.status = "approved"
        target.discrepancy_amount = Decimal("0.00")
        target.approved_by = finance.id
        target.approved_at = local_now()
        await db.commit()
    assigned = await client.post(
        url, json={"settlement_id": ola_s.id}, headers=fx.headers(second)
    )
    assert assigned.status_code == 200, assigned.text
    paid = await _status(ola_s.id)
    assert paid.status == "paid" and paid.paid_amount == Decimal("21106.80")


async def _second_payroll():
    async with AsyncSessionLocal() as db:
        user = await fx.make_user(db, "finance", name="Fabian Drugi")
        await db.commit()
    return user
