"""Rozliczenia zespołu — serwis: zamknięcie, dopasowanie faktur, zapłata (R2–R4, R7, R8, R11).

Interfejsy dla KSeF i płatności (``match_invoice``, ``mark_paid``, ``payable``)
z przypadkami brzegowymi: grosz różnicy, rachunek spoza białej listy, korekta,
faktura przed zamknięciem miesiąca, faktura bez okresu, NIP u dwóch osób,
idempotencja i anulowane. Dane fikcyjne.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import func, select

from app.core.database import AsyncSessionLocal
from app.core.scheduling import business_today
from app.models.hr_ops import HrAuditEvent
from app.models.hr_payroll import PayrollPeriod
from app.models.hr_settlement import PayrollInvoice, PayrollPayment, PayrollSettlement
from app.models.notification import Notification, NotificationType
from app.services.hr import payroll_bonuses, settlements
from app.services.hr.my_settlement import settlement as my_settlement
from tests.hr_settlements_seed import (
    add_bonus,
    add_line,
    add_timesheet,
    closed_period,
    fake_account,
    fake_nip,
    invoice,
    make_team,
    months_ago,
    set_billing,
    settlements_off,  # noqa: F401  (fixture)
    settlements_on,  # noqa: F401  (fixture)
)


async def _ensure(period_id: int) -> dict[str, int]:
    async with AsyncSessionLocal() as db:
        period = await db.get(PayrollPeriod, period_id)
        counts = await settlements.ensure_for_period(db, period, actor_id=None)
        await db.commit()
        return counts


async def _settlement(user_id: int, period_id: int) -> PayrollSettlement:
    async with AsyncSessionLocal() as db:
        row = await db.scalar(
            select(PayrollSettlement).where(
                PayrollSettlement.user_id == user_id,
                PayrollSettlement.period_id == period_id,
                PayrollSettlement.status != "cancelled",
            )
        )
        assert row is not None
        return row


async def _match(inv: PayrollInvoice) -> tuple[int | None, int]:
    async with AsyncSessionLocal() as db:
        db.add(inv)
        await db.flush()
        found = await settlements.match_invoice(db, inv)
        await db.commit()
        return (found.id if found else None), inv.id


async def _bells(user_id: int, ntype: NotificationType) -> int:
    async with AsyncSessionLocal() as db:
        return int(
            await db.scalar(
                select(func.count())
                .select_from(Notification)
                .where(
                    Notification.user_id == user_id,
                    Notification.notification_type == ntype,
                )
            )
            or 0
        )


# ── Zamknięcie miesiąca zakłada rozliczenia ───────────────────────────────────


@pytest.mark.usefixtures("settlements_on")
@pytest.mark.asyncio
async def test_close_creates_one_settlement_per_form_and_skips_zero() -> None:
    team = await make_team()
    year, month = months_ago(2)
    period_id = await closed_period(year, month)
    await add_line(
        period_id, team.b2b, employment_type="b2b", hours="160", rate="95.00"
    )
    await add_line(
        period_id, team.mandate, employment_type="zlecenie", hours="92", rate="32.00"
    )
    await add_line(
        period_id,
        team.uop,
        employment_type="uop",
        hours="0",
        rate=None,
        bonus_total="500",
    )
    # Zero do rozliczenia i osoba bez formy (premia bez kartoteki) — bez rozliczenia.
    await add_line(period_id, team.boss, employment_type="uop", hours="0", rate=None)
    await add_line(
        period_id,
        team.finance,
        employment_type=None,
        hours="0",
        rate=None,
        bonus_total="300",
    )

    counts = await _ensure(period_id)
    assert counts["created"] == 3
    assert counts["skipped_zero"] == 1 and counts["skipped_no_form"] == 1

    b2b = await _settlement(team.b2b.id, period_id)
    assert (b2b.status, b2b.amount_basis, b2b.due_on) == (
        "awaiting_document",
        "net",
        None,
    )
    assert b2b.expected_amount == Decimal("15200.00")
    mandate = await _settlement(team.mandate.id, period_id)
    assert (mandate.status, mandate.amount_basis) == ("ready", "gross")
    # Dzień wypłaty z ustawień Płac (domyślnie 10. następnego miesiąca, R8).
    assert mandate.due_on.day == 10 and mandate.due_on > date(year, month, 28)
    assert mandate.document_sha256 and len(mandate.document_sha256) == 64
    uop = await _settlement(team.uop.id, period_id)
    assert uop.expected_amount == Decimal("500.00") and uop.status == "ready"

    # Drugi przebieg niczego nie dubluje.
    again = await _ensure(period_id)
    assert again["created"] == 0 and again["kept"] == 3


# ── Dopasowanie faktury (interfejs dla KSeF) ──────────────────────────────────


async def _b2b_month(
    team, *, account_source: str = "white_list", net: str = "15200.00"
):
    year, month = months_ago(2)
    period_id = await closed_period(year, month)
    await add_line(
        period_id, team.b2b, employment_type="b2b", hours="160", rate="95.00"
    )
    nip = fake_nip()
    await set_billing(team.b2b, nip=nip, account=fake_account(), source=account_source)
    await _ensure(period_id)
    return year, month, period_id, nip


@pytest.mark.usefixtures("settlements_on")
@pytest.mark.asyncio
async def test_exact_invoice_is_ready_with_due_from_ksef_day() -> None:
    team = await make_team()
    year, month, period_id, nip = await _b2b_month(team)
    acquired = date(*months_ago(1), 4)
    found, _ = await _match(
        invoice(nip=nip, net="15200.00", year=year, month=month, acquired=acquired)
    )
    row = await _settlement(team.b2b.id, period_id)
    assert found == row.id
    assert row.status == "ready" and row.discrepancy_amount == Decimal("0.00")
    assert (row.due_on - acquired).days == 14


@pytest.mark.usefixtures("settlements_on")
@pytest.mark.asyncio
async def test_one_grosz_difference_is_mismatch_and_payroll_hears_once() -> None:
    team = await make_team()
    year, month, period_id, nip = await _b2b_month(team)
    inv = invoice(nip=nip, net="15200.01", year=year, month=month)
    found, invoice_id = await _match(inv)
    row = await _settlement(team.b2b.id, period_id)
    assert found == row.id and row.status == "mismatch"
    assert row.discrepancy_amount == Decimal("0.01")
    assert await _bells(team.finance.id, NotificationType.hr_settlement_review) == 1
    # Osoba nie dostaje dzwonka Płac o samej sobie.
    assert await _bells(team.b2b.id, NotificationType.hr_settlement_review) == 0

    # Ponowne wołanie (np. kolejny przebieg KSeF) — bez zmian i bez drugiego dzwonka.
    async with AsyncSessionLocal() as db:
        same = await db.get(PayrollInvoice, invoice_id)
        again = await settlements.match_invoice(db, same)
        await db.commit()
    assert again is not None and again.id == row.id
    assert (await _settlement(team.b2b.id, period_id)).status == "mismatch"
    assert await _bells(team.finance.id, NotificationType.hr_settlement_review) == 1


@pytest.mark.usefixtures("settlements_on")
@pytest.mark.asyncio
async def test_manual_account_on_b2b_is_mismatch_even_when_amount_matches() -> None:
    team = await make_team()
    year, month, period_id, nip = await _b2b_month(team, account_source="manual")
    await _match(invoice(nip=nip, net="15200.00", year=year, month=month))
    row = await _settlement(team.b2b.id, period_id)
    assert row.status == "mismatch" and row.discrepancy_amount == Decimal("0.00")


@pytest.mark.usefixtures("settlements_on")
@pytest.mark.asyncio
async def test_correction_joins_original_and_fixes_the_amount() -> None:
    team = await make_team()
    year, month, period_id, nip = await _b2b_month(team)
    _, original_id = await _match(
        invoice(nip=nip, net="15320.00", year=year, month=month)
    )
    assert (await _settlement(team.b2b.id, period_id)).status == "mismatch"
    # Korekta bez okresu: idzie za fakturą pierwotną, netto korekty to różnica.
    found, _ = await _match(
        invoice(
            nip=nip,
            net="-120.00",
            year=year,
            month=month,
            number="KOR 1/2026",
            kind="correction",
            corrects=original_id,
            period=False,
        )
    )
    row = await _settlement(team.b2b.id, period_id)
    assert found == row.id and row.status == "ready"
    assert row.discrepancy_amount == Decimal("0.00")


@pytest.mark.usefixtures("settlements_on")
@pytest.mark.asyncio
async def test_correction_from_other_seller_does_not_move_the_original() -> None:
    """Korekta z cudzym numerem faktury pierwotnej nie zmienia jej rozliczenia."""
    team = await make_team()
    year, month, period_id, nip = await _b2b_month(team)
    _, original_id = await _match(
        invoice(nip=nip, net="15320.00", year=year, month=month)
    )
    await _match(
        invoice(
            nip=fake_nip(),
            net="-120.00",
            year=year,
            month=month,
            number="KOR 9/2026",
            kind="correction",
            corrects=original_id,
            period=False,
        )
    )
    row = await _settlement(team.b2b.id, period_id)
    assert row.status == "mismatch"
    assert row.discrepancy_amount == Decimal("120.00")


@pytest.mark.usefixtures("settlements_on")
@pytest.mark.asyncio
async def test_invoice_before_close_waits_and_close_attaches_it() -> None:
    team = await make_team()
    year, month = months_ago(2)
    nip = fake_nip()
    await set_billing(team.b2b, nip=nip, account=fake_account(), source="white_list")
    found, invoice_id = await _match(
        invoice(nip=nip, net="15200.00", year=year, month=month)
    )
    assert found is None
    async with AsyncSessionLocal() as db:
        waiting = await db.get(PayrollInvoice, invoice_id)
        assert (waiting.match_status, waiting.user_id) == ("unmatched", team.b2b.id)

    period_id = await closed_period(year, month)
    await add_line(
        period_id, team.b2b, employment_type="b2b", hours="160", rate="95.00"
    )
    counts = await _ensure(period_id)
    assert counts["invoices_matched"] == 1
    assert (await _settlement(team.b2b.id, period_id)).status == "ready"


@pytest.mark.usefixtures("settlements_on")
@pytest.mark.asyncio
async def test_invoice_without_period_goes_to_the_only_open_settlement() -> None:
    team = await make_team()
    year, month, period_id, nip = await _b2b_month(team)
    found, _ = await _match(
        invoice(nip=nip, net="15200.00", year=year, month=month, period=False)
    )
    assert found == (await _settlement(team.b2b.id, period_id)).id

    # Dwa rozliczenia w toku — bez okresu decydują Płace.
    other_year, other_month = months_ago(3)
    other = await closed_period(other_year, other_month)
    await add_line(other, team.b2b, employment_type="b2b", hours="10", rate="95.00")
    await _ensure(other)
    found, _ = await _match(
        invoice(
            nip=nip, net="950.00", year=year, month=month, period=False, number="FV 2"
        )
    )
    # Pierwsze rozliczenie jest już gotowe, na dokument czeka jedno — tu ono.
    assert found == (await _settlement(team.b2b.id, other)).id

    # Dwa czekające na fakturę — faktura bez okresu zostaje do przypisania.
    for back in (4, 5):
        extra = await closed_period(*months_ago(back))
        await add_line(extra, team.b2b, employment_type="b2b", hours="5", rate="95.00")
        await _ensure(extra)
    found, invoice_id = await _match(
        invoice(
            nip=nip, net="475.00", year=year, month=month, period=False, number="FV 3"
        )
    )
    assert found is None
    async with AsyncSessionLocal() as db:
        waiting = await db.get(PayrollInvoice, invoice_id)
        assert (waiting.match_status, waiting.user_id) == ("unmatched", team.b2b.id)


@pytest.mark.usefixtures("settlements_on")
@pytest.mark.asyncio
async def test_unknown_nip_ambiguous_nip_ignored_and_other_currency() -> None:
    team = await make_team()
    year, month, period_id, nip = await _b2b_month(team)
    # Nieznany NIP — zostaje do przypisania, bez osoby.
    found, invoice_id = await _match(
        invoice(nip=fake_nip(), net="1.00", year=year, month=month)
    )
    assert found is None
    async with AsyncSessionLocal() as db:
        assert (await db.get(PayrollInvoice, invoice_id)).user_id is None
    # Inna waluta niż rozliczenie — bez dopasowania.
    found, _ = await _match(
        invoice(nip=nip, net="15200.00", year=year, month=month, currency="EUR")
    )
    assert found is None
    # Odrzucona przez Płace — nie dopasowuje się.
    ignored = invoice(nip=nip, net="15200.00", year=year, month=month)
    ignored.match_status = "ignored"
    found, _ = await _match(ignored)
    assert found is None
    # Ten sam NIP u drugiej osoby — decydują Płace.
    await set_billing(team.uop, nip=nip)
    found, _ = await _match(invoice(nip=nip, net="15200.00", year=year, month=month))
    assert found is None
    assert (await _settlement(team.b2b.id, period_id)).status == "awaiting_document"


@pytest.mark.usefixtures("settlements_on")
@pytest.mark.asyncio
async def test_new_document_clears_a_confirmed_override() -> None:
    team = await make_team()
    year, month, period_id, nip = await _b2b_month(team)
    await _match(invoice(nip=nip, net="15320.00", year=year, month=month))
    async with AsyncSessionLocal() as db:
        row = await settlements.lock_settlement(
            db, (await _settlement(team.b2b.id, period_id)).id
        )
        row.override_kind = "amount"
        row.override_reason = "Zaokrąglenie godzin uzgodnione"
        row.override_requested_by = team.finance.id
        row.override_confirmed_by = team.finance2.id
        await settlements.recompute(db, row)
        await db.commit()
    assert (await _settlement(team.b2b.id, period_id)).status == "ready"
    await _match(
        invoice(
            nip=nip,
            net="100.00",
            year=year,
            month=month,
            kind="correction",
            number="KOR 2",
        )
    )
    row = await _settlement(team.b2b.id, period_id)
    assert row.status == "mismatch" and row.override_confirmed_by is None


# ── Zapłata (interfejs dla wyciągu i paczki przelewów) ────────────────────────


@pytest.mark.usefixtures("settlements_on")
@pytest.mark.asyncio
async def test_mark_paid_is_idempotent_and_skips_cancelled() -> None:
    team = await make_team()
    year, month, period_id, nip = await _b2b_month(team)
    await _match(invoice(nip=nip, net="15200.00", year=year, month=month))
    row = await _settlement(team.b2b.id, period_id)
    async with AsyncSessionLocal() as db:
        target = await db.get(PayrollSettlement, row.id)
        first = await settlements.mark_paid(
            db,
            target,
            source="statement",
            amount=Decimal("18696.00"),
            paid_on=date(*months_ago(1), 15),
            actor_id=None,
        )
        second = await settlements.mark_paid(
            db,
            target,
            source="statement",
            amount=Decimal("18696.00"),
            paid_on=date(*months_ago(1), 16),
            actor_id=None,
        )
        await db.commit()
    assert (first, second) == (True, False)
    paid = await _settlement(team.b2b.id, period_id)
    assert paid.status == "paid" and paid.paid_source == "statement"
    assert paid.paid_at.date() == date(*months_ago(1), 15)
    assert await _bells(team.b2b.id, NotificationType.hr_settlement_paid) == 1
    # Wiersz wyciągu zapisuje import (R-C) — mark_paid nie dubluje płatności.
    async with AsyncSessionLocal() as db:
        assert not list(await db.scalars(select(PayrollPayment)))

    with pytest.raises(ValueError):
        async with AsyncSessionLocal() as db:
            await settlements.mark_paid(
                db,
                paid,
                source="cash",
                amount=Decimal("1"),
                paid_on=business_today(),
                actor_id=None,
            )


@pytest.mark.usefixtures("settlements_on")
@pytest.mark.asyncio
async def test_manual_paid_needs_reason_and_records_payment() -> None:
    team = await make_team()
    year, month = months_ago(2)
    period_id = await closed_period(year, month)
    await add_line(
        period_id, team.mandate, employment_type="zlecenie", hours="92", rate="32.00"
    )
    await _ensure(period_id)
    row = await _settlement(team.mandate.id, period_id)
    async with AsyncSessionLocal() as db:
        with pytest.raises(settlements.SettlementError):
            await settlements.mark_paid(
                db,
                row,
                source="manual",
                amount=Decimal("2944.00"),
                paid_on=date(*months_ago(1), 10),
                actor_id=team.finance.id,
                reason="  ",
            )
    async with AsyncSessionLocal() as db:
        target = await db.get(PayrollSettlement, row.id)
        assert await settlements.mark_paid(
            db,
            target,
            source="manual",
            amount=Decimal("2944.00"),
            paid_on=date(*months_ago(1), 10),
            actor_id=team.finance.id,
            reason="Przelew z banku poza paczką",
        )
        await db.commit()
    async with AsyncSessionLocal() as db:
        payments = list(await db.scalars(select(PayrollPayment)))
    assert len(payments) == 1 and payments[0].kind == "manual"
    assert payments[0].settlement_id == row.id


@pytest.mark.usefixtures("settlements_on")
@pytest.mark.asyncio
async def test_payable_lists_only_approved_by_due_date() -> None:
    team = await make_team()
    year, month = months_ago(2)
    period_id = await closed_period(year, month)
    await add_line(
        period_id, team.mandate, employment_type="zlecenie", hours="92", rate="32.00"
    )
    await add_line(
        period_id,
        team.uop,
        employment_type="uop",
        hours="0",
        rate=None,
        bonus_total="500",
    )
    await _ensure(period_id)
    mandate = await _settlement(team.mandate.id, period_id)
    async with AsyncSessionLocal() as db:
        row = await db.get(PayrollSettlement, mandate.id)
        row.status = "approved"
        row.approved_by = team.finance.id
        row.approved_at = row.created_at
        await db.commit()
    async with AsyncSessionLocal() as db:
        rows = await settlements.payable(db, period_id=period_id)
        everywhere = await settlements.payable(db)
    assert [r.id for r in rows] == [mandate.id]
    assert mandate.id in {r.id for r in everywhere}


# ── Ponowne otwarcie ──────────────────────────────────────────────────────────


@pytest.mark.usefixtures("settlements_on")
@pytest.mark.asyncio
async def test_cancel_keeps_paid_and_frees_invoices() -> None:
    team = await make_team()
    year, month, period_id, nip = await _b2b_month(team)
    await add_line(
        period_id, team.mandate, employment_type="zlecenie", hours="92", rate="32.00"
    )
    await _ensure(period_id)
    _, invoice_id = await _match(
        invoice(nip=nip, net="15200.00", year=year, month=month)
    )
    mandate = await _settlement(team.mandate.id, period_id)
    async with AsyncSessionLocal() as db:
        target = await db.get(PayrollSettlement, mandate.id)
        await settlements.mark_paid(
            db,
            target,
            source="manual",
            amount=Decimal("2944.00"),
            paid_on=date(*months_ago(1), 10),
            actor_id=team.finance.id,
            reason="Wypłata z listy płac",
        )
        period = await db.get(PayrollPeriod, period_id)
        cancelled = await settlements.cancel_for_period(
            db, period, actor_id=team.finance.id
        )
        await db.commit()
    assert cancelled == 1
    async with AsyncSessionLocal() as db:
        states = dict(
            (
                await db.execute(
                    select(PayrollSettlement.user_id, PayrollSettlement.status).where(
                        PayrollSettlement.period_id == period_id
                    )
                )
            ).all()
        )
        freed = await db.get(PayrollInvoice, invoice_id)
    assert states == {team.b2b.id: "cancelled", team.mandate.id: "paid"}
    assert (freed.match_status, freed.settlement_id, freed.user_id) == (
        "unmatched",
        None,
        team.b2b.id,
    )
    # Anulowane rozliczenie nie przyjmuje zapłaty.
    async with AsyncSessionLocal() as db:
        gone = await db.scalar(
            select(PayrollSettlement).where(
                PayrollSettlement.user_id == team.b2b.id,
                PayrollSettlement.period_id == period_id,
            )
        )
        assert not await settlements.mark_paid(
            db,
            gone,
            source="statement",
            amount=Decimal("1"),
            paid_on=date(year, month, 28),
            actor_id=None,
        )


# ── Premia wypłacona = rozliczenie opłacone (R11) ─────────────────────────────


@pytest.mark.usefixtures("settlements_on")
@pytest.mark.asyncio
async def test_bonus_is_paid_only_with_its_settlement() -> None:
    team = await make_team()
    year, month = months_ago(2)
    period_id = await closed_period(year, month)
    bonus_id = await add_bonus(
        team.mandate, year, month, "200.00", assigned_by=team.finance
    )
    await add_line(
        period_id,
        team.mandate,
        employment_type="zlecenie",
        hours="92",
        rate="32.00",
        bonus_total="200",
    )
    await _ensure(period_id)
    today = date(*months_ago(0), 1)
    async with AsyncSessionLocal() as db:
        from app.models.hr_payroll import HrBonus

        bonus = await db.get(HrBonus, bonus_id)
        assert (await payroll_bonuses.paid_flags(db, [bonus])) == {bonus_id: False}
        before = await my_settlement(
            db, user_id=team.mandate.id, year=year, today=today
        )
    assert before["bonuses_paid"] == {} and before["bonuses_rule"] == "paid_settlement"

    row = await _settlement(team.mandate.id, period_id)
    async with AsyncSessionLocal() as db:
        target = await db.get(PayrollSettlement, row.id)
        await settlements.mark_paid(
            db,
            target,
            source="statement",
            amount=Decimal("2700.00"),
            paid_on=date(*months_ago(1), 10),
            actor_id=None,
        )
        await db.commit()
    async with AsyncSessionLocal() as db:
        bonus = await db.get(HrBonus, bonus_id)
        assert (await payroll_bonuses.paid_flags(db, [bonus])) == {bonus_id: True}
        after = await my_settlement(db, user_id=team.mandate.id, year=year, today=today)
    assert after["bonuses_paid"] == {"PLN": "200.00"}


@pytest.mark.usefixtures("settlements_off")
@pytest.mark.asyncio
async def test_bonus_rule_stays_closed_month_when_module_off() -> None:
    team = await make_team()
    year, month = months_ago(2)
    period_id = await closed_period(year, month)
    bonus_id = await add_bonus(
        team.uop, year, month, "300.00", assigned_by=team.finance
    )
    await add_line(
        period_id,
        team.uop,
        employment_type="uop",
        hours="0",
        rate=None,
        bonus_total="300",
    )
    async with AsyncSessionLocal() as db:
        from app.models.hr_payroll import HrBonus

        bonus = await db.get(HrBonus, bonus_id)
        assert await payroll_bonuses.paid_flags(db, [bonus]) is None
        report = await my_settlement(
            db, user_id=team.uop.id, year=year, today=date(*months_ago(0), 1)
        )
    assert report["bonuses_paid"] == {"PLN": "300.00"}
    assert report["bonuses_rule"] == "closed_month"


# ── Ślad bez rachunku ─────────────────────────────────────────────────────────


@pytest.mark.usefixtures("settlements_on")
@pytest.mark.asyncio
async def test_audit_never_carries_the_account() -> None:
    team = await make_team()
    year, month = months_ago(2)
    period_id = await closed_period(year, month)
    await add_line(
        period_id, team.b2b, employment_type="b2b", hours="160", rate="95.00"
    )
    nip, account = fake_nip(), fake_account()
    await set_billing(team.b2b, nip=nip, account=account, source="white_list")
    await _ensure(period_id)
    await _match(invoice(nip=nip, net="15200.00", year=year, month=month))
    async with AsyncSessionLocal() as db:
        details = [
            str(event.details)
            for event in await db.scalars(
                select(HrAuditEvent).where(HrAuditEvent.subject_user_id == team.b2b.id)
            )
        ]
    assert details and not any(account[-10:] in text for text in details)


@pytest.mark.usefixtures("settlements_on")
@pytest.mark.asyncio
async def test_b2b_items_include_paid_break_from_timesheet() -> None:
    from app.services.hr import settlements_items
    from app.models.hr_payroll import PayrollLine

    team = await make_team()
    year, month = months_ago(2)
    period_id = await closed_period(year, month)
    await add_timesheet(
        team.b2b,
        year,
        month,
        approved_by=team.boss,
        work=[(5, "8"), (6, "8")],
        leave_paid=[7],
    )
    await add_bonus(team.b2b, year, month, "1200.00", assigned_by=team.finance)
    line_id = await add_line(
        period_id,
        team.b2b,
        employment_type="b2b",
        hours="24",
        rate="95.00",
        bonus_total="1200",
    )
    async with AsyncSessionLocal() as db:
        line = await db.get(PayrollLine, line_id)
        amounts = await settlements_items.frozen_amounts(
            db, line, year=year, month=month
        )
    kinds = [(item.kind, str(item.amount)) for item in amounts.items]
    assert kinds == [
        ("hours", "1520.00"),
        ("paid_days", "760.00"),
        ("bonus", "1200.00"),
    ]
    assert sum(item.amount for item in amounts.items) == amounts.total
    assert amounts.timesheet.approved_by_name == team.boss.name
