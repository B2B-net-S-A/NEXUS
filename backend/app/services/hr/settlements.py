"""Rozliczenia zespołu (etap 4, R2–R4, R6–R8, R10–R11): stan rozliczenia miesiąca.

Rozliczenie (``payroll_settlements``) powstaje przy zamknięciu miesiąca płac
z zamrożonej linii (osoba × waluta, kwota > 0) i żyje do zapłaty. Stany
i znaczenie kolumn — docstring ``app/services/hr_settlement_schema.py``.

**Interfejsy dla innych części etapu 4** (stałe — KSeF i płatności piszą pod nie):

* ``match_invoice(db, invoice)`` — dopasowanie faktury (KSeF albo PDF dopięty
  ręcznie) do rozliczenia w toku po NIP-ie z ``employee_billing_details``
  i miesiącu (``period_year``/``period_month``, bez nich — data sprzedaży,
  a bez daty — jedyne rozliczenie B2B tej osoby czekające na dokument:
  bez faktury albo z rozbieżnością; przy kilku — bez dopasowania); korekta idzie za
  fakturą pierwotną. Faktura musi być w sesji (R-B woła po flushu, w SAVEPOINT). Ustawia ``invoice.settlement_id``,
  ``match_status`` i ``user_id``, przelicza stan (``ready`` przy zgodności
  netto co do grosza i rachunku z białej listy, inaczej ``mismatch``),
  powiadamia Płace o nowej rozbieżności. Idempotentne: dopasowana faktura
  zostaje przy swoim rozliczeniu. Miesiąc jeszcze niezamknięty = faktura
  czeka (``unmatched`` z ``user_id``) i dopasowuje ją zamknięcie miesiąca.
* ``mark_paid(db, settlement, source=…, amount=…, paid_on=…, actor_id=…)`` —
  ``source`` z ``PAID_SOURCES``; drugie wywołanie i anulowane = ``False``.
  Ręczne „opłacono” wymaga powodu i zapisuje wiersz ``payroll_payments``
  (``kind='manual'``); wiersze wyciągu i paczki zapisuje ich import.
* ``payable(db, period_id=None)`` — zatwierdzone do zapłaty (``approved``).

Netto faktury to suma faktury pierwotnej i korekt (``net_amount`` korekty to
różnica, jak w polach P_13 korekty FA(3)). Nowy dokument przy rozliczeniu
kasuje uznanie różnicy — porównanie zaczyna się od nowa. Rozliczenie opłacone
zostaje dowodem: późniejsza korekta tylko aktualizuje różnicę.

Rachunku bankowego nie ma tu nigdzie (dane do przelewu czyta
``billing_details``) — ani w śladzie, ani w powiadomieniach.
"""

from __future__ import annotations

import logging
from datetime import date, datetime, time
from decimal import Decimal
from typing import Any, Optional
from zoneinfo import ZoneInfo

from sqlalchemy import and_, case, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.scheduling import DEFAULT_TZ, business_date, business_today, local_now
from app.models.app_setting import AppSetting
from app.models.hr_payroll import PayrollLine, PayrollPeriod
from app.models.hr_settlement import (
    EmployeeBillingDetails,
    PayrollInvoice,
    PayrollPayment,
    PayrollSettlement,
)
from app.models.notification import NotificationType
from app.models.user import User, UserRole
from app.services.action_permissions import ProductAction
from app.services.hr import audit, settlements_items
from app.services.hr.notify import notify_each
from app.services.hr.payroll_errors import PayrollConflict, PayrollError
from app.services.hr.payroll_periods import label, month_end, month_start
from app.services.hr.payroll_report import money
from app.services.hr.settlements_rules import (
    B2B,
    PAYMENT_SETTINGS_KEY,
    SETTLEMENTS_SINCE_KEY,
    amount_basis,
    clamp_payout_day,
    gross_problem,
    initial_status,
    invoice_due_date,
    net_total,
    override_covers,
    parse_since,
    payment_amount_refusal,
    payment_state_refusal,
    payout_date,
    problems_of,
    seller_problem,
    settled_in_nexus,
)
from app.services.hr_settlement_schema import (
    AMOUNT_MAX,
    EMPLOYMENT_TYPES,
    PAID_SOURCES,
    REASON_MAX_LENGTH,
)

logger = logging.getLogger(__name__)

PERSON_LINK = "/my-time?tab=settlement"
#: Rozliczenia B2B, które jeszcze czekają na dokument (faktura bez okresu).
WAITING_FOR_DOCUMENT: tuple[str, ...] = ("awaiting_document", "mismatch")
_MISSING: Any = object()


class SettlementError(PayrollError):
    """Błąd rozliczenia — komunikat po polsku, status jak w Płacach."""


# ── Odczyty pomocnicze ────────────────────────────────────────────────────────


def queue_link(year: int, month: int, settlement_id: Optional[int] = None) -> str:
    link = f"/people/payroll/{year}-{month:02d}?view=settlements"
    return f"{link}&settlement={settlement_id}" if settlement_id else link


async def lock_settlement(
    db: AsyncSession, settlement_id: int
) -> Optional[PayrollSettlement]:
    return await db.scalar(
        select(PayrollSettlement)
        .where(PayrollSettlement.id == settlement_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )


async def billing_of(
    db: AsyncSession, user_id: int
) -> Optional[EmployeeBillingDetails]:
    return await db.scalar(
        select(EmployeeBillingDetails).where(EmployeeBillingDetails.user_id == user_id)
    )


async def users_with_nip(db: AsyncSession, nip: str) -> list[int]:
    return [
        int(uid)
        for uid in await db.scalars(
            select(EmployeeBillingDetails.user_id)
            .where(EmployeeBillingDetails.nip == nip)
            .order_by(EmployeeBillingDetails.user_id)
        )
    ]


async def load_payout_day(db: AsyncSession) -> int:
    raw = await db.scalar(
        select(AppSetting.value).where(AppSetting.key == PAYMENT_SETTINGS_KEY)
    )
    return clamp_payout_day(raw.get("payout_day") if isinstance(raw, dict) else None)


async def load_settlements_since(db: AsyncSession) -> Optional[tuple[int, int]]:
    """Pierwszy miesiąc rozliczany w NEXUSIE (``settlements_since``); ``None`` = bez progu."""

    raw = await db.scalar(
        select(AppSetting.value).where(AppSetting.key == PAYMENT_SETTINGS_KEY)
    )
    return parse_since(
        raw.get(SETTLEMENTS_SINCE_KEY) if isinstance(raw, dict) else None
    )


async def payroll_ids(db: AsyncSession) -> list[int]:
    """Płace (uprawnienie „Płace” bez adminów); bez nikogo — admini."""

    from app.services.hr.recipients import admin_ids, users_with_permission

    holders = await users_with_permission(db, ProductAction.payroll)
    ids = [user.id for user in holders if not user.has_role(UserRole.admin)]
    return ids or await admin_ids(db)


async def person_name(db: AsyncSession, user_id: int) -> str:
    return str(await db.scalar(select(User.name).where(User.id == user_id)) or "")


async def period_of(db: AsyncSession, settlement: PayrollSettlement) -> PayrollPeriod:
    period = await db.get(PayrollPeriod, settlement.period_id)
    assert period is not None  # FK ON DELETE RESTRICT
    return period


def invoice_period(invoice: PayrollInvoice) -> Optional[tuple[int, int]]:
    """Miesiąc faktury: z pozycji (``period_*``), bez nich — z daty sprzedaży."""

    if invoice.period_year and invoice.period_month:
        return int(invoice.period_year), int(invoice.period_month)
    if invoice.sale_date is not None:
        return invoice.sale_date.year, invoice.sale_date.month
    return None


def received_on(invoice: PayrollInvoice) -> date:
    """Dzień doręczenia: nadanie numeru KSeF; PDF spoza KSeF — dzień dopięcia."""

    moment = (
        invoice.ksef_acquired_at
        if invoice.source == "ksef" and invoice.ksef_acquired_at is not None
        else invoice.created_at or invoice.fetched_at
    )
    return business_date(moment) if moment is not None else business_today()


def paid_moment(paid_on: date) -> datetime:
    """Chwila zapłaty z dnia księgowania (południe w Warszawie — bez skoku doby)."""

    return datetime.combine(paid_on, time(12, 0), tzinfo=ZoneInfo(DEFAULT_TZ))


async def matched_invoices(
    db: AsyncSession, settlement_id: int
) -> list[PayrollInvoice]:
    return list(
        await db.scalars(
            select(PayrollInvoice)
            .where(
                PayrollInvoice.settlement_id == settlement_id,
                PayrollInvoice.match_status == "matched",
            )
            .order_by(PayrollInvoice.issue_date, PayrollInvoice.id)
        )
    )


def gross_issue_of(
    invoices: list[PayrollInvoice], billing: Optional[EmployeeBillingDetails]
) -> bool:
    """Brutto dopasowanych faktur nie wynika z netto i VAT (``gross_problem``)."""

    return gross_problem(
        ((i.net_amount, i.vat_amount, i.gross_amount) for i in invoices),
        vat_status=billing.vat_status if billing is not None else None,
    )


def seller_issue_of(
    invoices: list[PayrollInvoice], billing: Optional[EmployeeBillingDetails]
) -> bool:
    """Faktura od innego NIP-u niż w danych do rozliczeń (``seller_problem``)."""

    return seller_problem(
        (i.seller_nip for i in invoices), billing.nip if billing is not None else None
    )


async def problems_now(
    db: AsyncSession, settlement: PayrollSettlement
) -> tuple[str, ...]:
    """Problemy rozliczenia teraz (wniosek o uznanie bierze je do śladu)."""

    billing = await billing_of(db, settlement.user_id)
    invoices = await matched_invoices(db, settlement.id)
    return problems_of(
        employment_type=settlement.employment_type,
        discrepancy=settlement.discrepancy_amount,
        account_source=billing.account_source if billing is not None else None,
        gross_issue=gross_issue_of(invoices, billing),
        seller_issue=seller_issue_of(invoices, billing),
    )


async def ensure_payable_by_hand(
    db: AsyncSession, settlement: PayrollSettlement, *, amount: Decimal
) -> None:
    """Ręczne „opłacono” i „Przypisz” z wyciągu (decyzja Artura 19.10.2026).

    409, gdy rozliczenie czeka na dokument albo ma rozbieżność bez
    potwierdzonego uznania (``payment_state_refusal``); 422, gdy kwota B2B
    różni się od brutto faktur o więcej niż grosz (``payment_amount_refusal``).
    Opłacone, anulowane i własne rozliczenie sprawdzają wołający.
    """

    problems = await problems_now(db, settlement)
    refusal = payment_state_refusal(
        employment_type=settlement.employment_type,
        status=settlement.status,
        problems=problems,
        override_kind=settlement.override_kind,
        override_confirmed=settlement.override_confirmed_by is not None,
    )
    if refusal:
        raise PayrollConflict(refusal, code="settlement_not_payable")
    invoices = await matched_invoices(db, settlement.id)
    to_pay = net_total(i.gross_amount for i in invoices) if invoices else None
    refusal = payment_amount_refusal(
        employment_type=settlement.employment_type,
        amount=amount,
        to_pay=to_pay,
        currency=settlement.currency,
    )
    if refusal:
        raise SettlementError(refusal, code="paid_amount_differs")


def clear_override(settlement: PayrollSettlement) -> None:
    settlement.override_kind = None
    settlement.override_reason = None
    settlement.override_requested_by = None
    settlement.override_requested_at = None
    settlement.override_confirmed_by = None
    settlement.override_confirmed_at = None


def _clear_approval(settlement: PayrollSettlement) -> None:
    settlement.approved_by = None
    settlement.approved_at = None


# ── Powiadomienia (bez kwot) ──────────────────────────────────────────────────
#
# Dzwonki rozliczeń idą BEZ ``related_entity_id``: dzienny odsiew
# ``ix_notif_dedup_daily`` (osoba, typ, encja, doba) połknąłby drugi dzwonek
# o tym samym rozliczeniu tego samego dnia — np. wniosek o uznanie różnicy
# zaraz po dzwonku o rozbieżności. Powtórek pilnuje kod (dzwonek o rozbieżności
# tylko przy wejściu w ``mismatch``, „opłacono” raz). Jak w urlopach
# i komunikatach do konsultantów.


async def notify_review(
    db: AsyncSession,
    settlement: PayrollSettlement,
    *,
    title: str,
    message: str,
    exclude: tuple[Optional[int], ...] = (),
) -> int:
    """Płace: rozbieżność do sprawdzenia albo uznanie czekające na drugą osobę."""

    period = await period_of(db, settlement)
    return await notify_each(
        db,
        await payroll_ids(db),
        title=title,
        message=message,
        ntype=NotificationType.hr_settlement_review,
        link=queue_link(period.year, period.month, settlement.id),
        related_entity_type="payroll_settlement",
        exclude=(settlement.user_id, *exclude),
        log_tag="settlements",
    )


async def _notify_new_mismatch(db: AsyncSession, settlement: PayrollSettlement) -> None:
    period = await period_of(db, settlement)
    name = await person_name(db, settlement.user_id)
    await notify_review(
        db,
        settlement,
        title="Rozbieżność w rozliczeniu",
        message=(
            f"{name} · {label(period.year, period.month)}: faktura nie zgadza się "
            "z raportem albo rachunek jest spoza białej listy. Porównanie w Płacach "
            "→ Rozliczenia."
        ),
    )


# ── Przeliczenie stanu ────────────────────────────────────────────────────────


async def recompute(
    db: AsyncSession,
    settlement: PayrollSettlement,
    *,
    billing: Any = _MISSING,
    notify: bool = True,
) -> str:
    """Stan B2B z dopasowanych faktur i rachunku; zlecenie i UoP bez zmian.

    Opłacone zostaje opłacone (aktualizuje się tylko różnica), zatwierdzone
    wraca do rozbieżności, gdy nowy dokument przestał się zgadzać.
    """

    previous = settlement.status
    if settlement.employment_type != B2B or previous == "cancelled":
        return previous
    if billing is _MISSING:
        billing = await billing_of(db, settlement.user_id)
    invoices = await matched_invoices(db, settlement.id)
    originals = [invoice for invoice in invoices if invoice.invoice_kind == "original"]
    if not originals:
        settlement.discrepancy_amount = None
        settlement.due_on = None
        target = "awaiting_document"
    else:
        total = net_total(invoice.net_amount for invoice in invoices)
        discrepancy = money(total - Decimal(settlement.expected_amount))
        settlement.discrepancy_amount = discrepancy
        settlement.due_on = invoice_due_date(
            min(received_on(invoice) for invoice in originals),
            billing.payment_terms_days if billing is not None else None,
        )
        problems = problems_of(
            employment_type=B2B,
            discrepancy=discrepancy,
            account_source=billing.account_source if billing is not None else None,
            gross_issue=gross_issue_of(invoices, billing),
            seller_issue=seller_issue_of(invoices, billing),
        )
        # Uznanie nie obejmuje ``seller`` (faktura innego wystawcy) — po zmianie
        # NIP-u w danych stara faktura daje rozbieżność, nie „Do zapłaty”.
        confirmed = settlement.override_confirmed_by is not None and override_covers(
            settlement.override_kind, problems
        )
        target = "ready" if not problems or confirmed else "mismatch"
    if previous == "paid":
        return previous
    if previous == "approved":
        if target == "ready":
            return previous
        _clear_approval(settlement)
    settlement.status = target
    await db.flush()
    if notify and target == "mismatch" and previous != "mismatch":
        await _notify_new_mismatch(db, settlement)
    return target


# ── Interfejs: dopasowanie faktury ────────────────────────────────────────────


async def _settlement_for(
    db: AsyncSession, *, user_id: int, year: int, month: int, currency: str
) -> Optional[PayrollSettlement]:
    return await db.scalar(
        select(PayrollSettlement)
        .join(PayrollPeriod, PayrollPeriod.id == PayrollSettlement.period_id)
        .where(
            PayrollPeriod.year == year,
            PayrollPeriod.month == month,
            PayrollSettlement.user_id == user_id,
            PayrollSettlement.currency == currency,
            PayrollSettlement.status != "cancelled",
        )
        .with_for_update(of=PayrollSettlement)
        .execution_options(populate_existing=True)
    )


async def _target_for(
    db: AsyncSession, invoice: PayrollInvoice
) -> tuple[Optional[int], Optional[PayrollSettlement]]:
    """Osoba i rozliczenie faktury (bez zapisu)."""

    if invoice.invoice_kind == "correction" and invoice.corrects_invoice_id:
        original = await db.get(PayrollInvoice, invoice.corrects_invoice_id)
        # Korekta dopina się do rozliczenia faktury pierwotnej tylko od tego
        # samego sprzedawcy — cudzy numer w polu korekty nie przenosi kwoty.
        if (
            original is not None
            and original.seller_nip == invoice.seller_nip
            and original.match_status == "matched"
            and original.settlement_id is not None
        ):
            found = await lock_settlement(db, original.settlement_id)
            if found is not None and found.status != "cancelled":
                return found.user_id, found

    owners = await users_with_nip(db, invoice.seller_nip)
    if len(owners) == 1:
        user_id: Optional[int] = owners[0]
    elif not owners:
        # Faktura przypisana ręcznie przez Płace (NIP-u jeszcze nie ma w danych).
        user_id = invoice.user_id
    else:
        # Ten sam NIP u dwóch osób — decydują Płace (przypisanie ręczne).
        user_id = invoice.user_id if invoice.user_id in owners else None
    if user_id is None:
        return None, None
    period = invoice_period(invoice)
    if period is None:
        # Bez okresu i daty sprzedaży: jedyne rozliczenie B2B tej osoby, które
        # jeszcze czeka na dokument (bez faktury albo z rozbieżnością); zgodne
        # ma już swoją fakturę. Przy kilku decydują Płace (przypisanie ręczne).
        candidates = list(
            await db.scalars(
                select(PayrollSettlement)
                .where(
                    PayrollSettlement.user_id == user_id,
                    PayrollSettlement.employment_type == B2B,
                    PayrollSettlement.currency == invoice.currency,
                    PayrollSettlement.status.in_(WAITING_FOR_DOCUMENT),
                )
                .order_by(PayrollSettlement.id)
                .limit(2)
            )
        )
        if len(candidates) != 1:
            return user_id, None
        return user_id, await lock_settlement(db, candidates[0].id)
    found = await _settlement_for(
        db,
        user_id=user_id,
        year=period[0],
        month=period[1],
        currency=invoice.currency,
    )
    if found is None or found.employment_type != B2B:
        return user_id, None
    return user_id, found


async def match_invoice(
    db: AsyncSession, invoice: PayrollInvoice
) -> Optional[PayrollSettlement]:
    """Dopasuj fakturę do rozliczenia w toku i przelicz jego stan (idempotentne)."""

    if invoice.match_status == "ignored":
        return None
    if invoice.match_status == "matched" and invoice.settlement_id is not None:
        current = await lock_settlement(db, invoice.settlement_id)
        if current is not None and current.status != "cancelled":
            await recompute(db, current)
            return current

    user_id, settlement = await _target_for(db, invoice)
    if user_id is not None:
        invoice.user_id = user_id
    if settlement is None:
        invoice.settlement_id = None
        invoice.match_status = "unmatched"
        await db.flush()
        return None

    invoice.settlement_id = settlement.id
    invoice.match_status = "matched"
    invoice.user_id = settlement.user_id
    if settlement.status != "paid":
        clear_override(settlement)
    await db.flush()
    status = await recompute(db, settlement)
    audit.record(
        db,
        actor_user_id=None,
        subject_user_id=settlement.user_id,
        entity_type="payroll_settlement",
        entity_id=settlement.id,
        action="invoice_matched",
        sensitivity="payroll",
        details={
            "invoice_id": invoice.id,
            "source": invoice.source,
            "kind": invoice.invoice_kind,
            "net": str(invoice.net_amount),
            "currency": invoice.currency,
            "status": status,
        },
    )
    await db.flush()
    return settlement


async def attach_waiting_invoices(
    db: AsyncSession, settlement: PayrollSettlement, period: PayrollPeriod
) -> int:
    """Faktury, które przyszły przed zamknięciem miesiąca (albo przed NIP-em)."""

    if settlement.employment_type != B2B or settlement.status == "cancelled":
        return 0
    billing = await billing_of(db, settlement.user_id)
    owner = [PayrollInvoice.user_id == settlement.user_id]
    if billing is not None and billing.nip:
        owner.append(PayrollInvoice.seller_nip == billing.nip)
    first, last = (
        month_start(period.year, period.month),
        month_end(period.year, period.month),
    )
    rows = list(
        await db.scalars(
            select(PayrollInvoice)
            .where(
                PayrollInvoice.match_status == "unmatched",
                PayrollInvoice.currency == settlement.currency,
                or_(*owner),
                or_(
                    and_(
                        PayrollInvoice.period_year == period.year,
                        PayrollInvoice.period_month == period.month,
                    ),
                    and_(
                        PayrollInvoice.period_year.is_(None),
                        PayrollInvoice.sale_date.between(first, last),
                    ),
                ),
            )
            .order_by(
                case((PayrollInvoice.invoice_kind == "original", 0), else_=1),
                PayrollInvoice.issue_date,
                PayrollInvoice.id,
            )
        )
    )
    matched = 0
    for invoice in rows:
        if await match_invoice(db, invoice) is not None:
            matched += 1
    return matched


# ── Interfejs: zapłata ────────────────────────────────────────────────────────


async def mark_paid(
    db: AsyncSession,
    settlement: PayrollSettlement,
    *,
    source: str,
    amount: Decimal,
    paid_on: date,
    actor_id: Optional[int],
    reason: Optional[str] = None,
) -> bool:
    """Oznacz opłacone; ``False`` = już opłacone albo anulowane (nic nie zmienia)."""

    if source not in PAID_SOURCES:
        raise ValueError(f"nieznane źródło zapłaty: {source}")
    value = Decimal(amount)
    if not value.is_finite() or abs(value) > Decimal(AMOUNT_MAX):
        raise SettlementError("Kwota zapłaty jest poza zakresem.")
    note = (reason or "").strip()[:REASON_MAX_LENGTH] or None
    if source == "manual" and (note is None or len(note) < 3):
        raise SettlementError("Podaj powód ręcznego „opłacono” (co najmniej 3 znaki).")
    locked = await lock_settlement(db, settlement.id)
    if locked is None or locked.status in ("paid", "cancelled"):
        return False
    locked.status = "paid"
    locked.paid_at = paid_moment(paid_on)
    locked.paid_source = source
    locked.paid_amount = money(value)
    locked.paid_reason = note
    locked.paid_by = actor_id
    if source == "manual":
        db.add(
            PayrollPayment(
                kind="manual",
                settlement_id=locked.id,
                match_status="matched",
                amount=money(value),
                currency=locked.currency,
                booked_on=paid_on,
                reason=note,
                created_by=actor_id,
            )
        )
    await db.flush()
    audit.record(
        db,
        actor_user_id=actor_id,
        subject_user_id=locked.user_id,
        entity_type="payroll_settlement",
        entity_id=locked.id,
        action="settlement_paid",
        sensitivity="payroll",
        details={
            "source": source,
            "amount": str(money(value)),
            "currency": locked.currency,
            "paid_on": paid_on.isoformat(),
            "reason": note,
        },
    )
    period = await period_of(db, locked)
    words = "Wypłacono" if locked.employment_type != B2B else "Opłacono"
    await notify_each(
        db,
        [locked.user_id],
        title=f"Rozliczenie: {words.lower()}",
        message=(
            f"{words} rozliczenie za {label(period.year, period.month)}. "
            "Szczegóły w „Moim czasie” → Rozliczenie."
        ),
        ntype=NotificationType.hr_settlement_paid,
        link=PERSON_LINK,
        related_entity_type="payroll_settlement",
        exclude=(actor_id,),
        log_tag="settlements",
    )
    return True


async def payable(
    db: AsyncSession, *, period_id: Optional[int] = None
) -> list[PayrollSettlement]:
    """Zatwierdzone do zapłaty — ekran „Dla Finansów” i paczka przelewów."""

    query = select(PayrollSettlement).where(PayrollSettlement.status == "approved")
    if period_id is not None:
        query = query.where(PayrollSettlement.period_id == period_id)
    return list(
        await db.scalars(
            query.order_by(
                PayrollSettlement.due_on.asc().nulls_last(), PayrollSettlement.id
            )
        )
    )


# ── Zamknięcie i ponowne otwarcie miesiąca ────────────────────────────────────


async def _new_settlement(
    db: AsyncSession, line: PayrollLine, period: PayrollPeriod, payout_day: int
) -> PayrollSettlement:
    employment_type = str(line.employment_type)
    settlement = PayrollSettlement(
        period_id=period.id,
        line_id=line.id,
        user_id=line.user_id,
        employment_type=employment_type,
        currency=line.currency,
        expected_amount=money(Decimal(line.total)),
        amount_basis=amount_basis(employment_type),
        status=initial_status(employment_type),
        due_on=None
        if employment_type == B2B
        else payout_date(period.year, period.month, payout_day),
    )
    if employment_type == "zlecenie":
        amounts = await settlements_items.frozen_amounts(
            db, line, year=period.year, month=period.month
        )
        settlement.document_sha256 = settlements_items.document_hash(
            user_id=line.user_id,
            amounts=amounts,
            expected_amount=settlement.expected_amount,
        )
    return settlement


async def ensure_for_period(
    db: AsyncSession, period: PayrollPeriod, *, actor_id: Optional[int] = None
) -> dict[str, int]:
    """Rozliczenia zamkniętego miesiąca z linii płac (idempotentne).

    Linia z kwotą 0 nie ma czego rozliczać; linia bez formy współpracy (osoba
    bez kartoteki z premią) czeka na Płace — liczba w odpowiedzi. Rozliczenie
    opłacone przed ponownym otwarciem zostaje (dowód) i dostaje nową linię.
    """

    if period.status != "closed":
        raise SettlementError("Rozliczenia powstają z zamkniętego miesiąca płac.")
    since = await load_settlements_since(db)
    if not settled_in_nexus(period.year, period.month, since):
        raise SettlementError(
            "Ten miesiąc jest sprzed rozliczeń w NEXUSIE (pierwszy rozliczany: "
            f"{label(*since)}) — rozliczono go poza NEXUSEM."
        )
    lines = list(
        await db.scalars(
            select(PayrollLine)
            .where(PayrollLine.period_id == period.id)
            .order_by(PayrollLine.user_id, PayrollLine.currency)
        )
    )
    existing = {
        (row.user_id, row.currency): row
        for row in await db.scalars(
            select(PayrollSettlement).where(
                PayrollSettlement.period_id == period.id,
                PayrollSettlement.status != "cancelled",
            )
        )
    }
    payout_day = await load_payout_day(db)
    counts = {"created": 0, "kept": 0, "skipped_zero": 0, "skipped_no_form": 0}
    created: list[PayrollSettlement] = []
    for line in lines:
        known = existing.get((line.user_id, line.currency))
        if known is not None:
            if known.line_id != line.id:
                known.line_id = line.id
            counts["kept"] += 1
            continue
        if line.employment_type not in EMPLOYMENT_TYPES:
            counts["skipped_no_form"] += 1
            continue
        if Decimal(line.total) <= 0:
            counts["skipped_zero"] += 1
            continue
        settlement = await _new_settlement(db, line, period, payout_day)
        db.add(settlement)
        created.append(settlement)
    counts["created"] = len(created)
    await db.flush()
    matched = 0
    for settlement in created:
        matched += await attach_waiting_invoices(db, settlement, period)
    counts["invoices_matched"] = matched
    if created:
        audit.record(
            db,
            actor_user_id=actor_id,
            subject_user_id=None,
            entity_type="payroll_period",
            entity_id=period.id,
            action="settlements_created",
            sensitivity="payroll",
            details={"year": period.year, "month": period.month, **counts},
        )
    await db.flush()
    return counts


async def cancel_for_period(
    db: AsyncSession, period: PayrollPeriod, *, actor_id: Optional[int]
) -> int:
    """Ponowne otwarcie: nieopłacone rozliczenia → ``cancelled``, faktury wolne.

    Opłacone zostają jako dowód. Faktury wracają do ``unmatched`` (z osobą),
    więc kolejne zamknięcie dopasuje je od nowa.
    """

    rows = list(
        await db.scalars(
            select(PayrollSettlement)
            .where(
                PayrollSettlement.period_id == period.id,
                PayrollSettlement.status.not_in(("paid", "cancelled")),
            )
            .order_by(PayrollSettlement.id)
            .with_for_update()
        )
    )
    if not rows:
        return 0
    ids = [row.id for row in rows]
    now = local_now()
    for row in rows:
        row.status = "cancelled"
        row.cancelled_at = now
    await db.execute(
        update(PayrollInvoice)
        .where(PayrollInvoice.settlement_id.in_(ids))
        .values(settlement_id=None, match_status="unmatched")
        .execution_options(synchronize_session="fetch")
    )
    audit.record(
        db,
        actor_user_id=actor_id,
        subject_user_id=None,
        entity_type="payroll_period",
        entity_id=period.id,
        action="settlements_cancelled",
        sensitivity="payroll",
        details={"year": period.year, "month": period.month, "count": len(rows)},
    )
    await db.flush()
    return len(rows)


async def billing_changed(
    db: AsyncSession, user_id: int, *, payee_changed: bool = True
) -> None:
    """Zmiana danych do rozliczeń osoby: przelicz jej rozliczenia B2B przed zapłatą.

    ``payee_changed`` — zmienił się rachunek albo NIP (komu idą pieniądze).
    Wtedy znika uznanie KAŻDEGO rodzaju (dwie osoby uznały różnicę przy
    poprzednim odbiorcy) i zatwierdzenie do zapłaty: zatwierdzone wraca do
    przeliczenia, a rachunek spoza białej listy daje rozbieżność do decyzji
    dwóch osób. Sam termin płatności albo status VAT tylko przelicza stan.
    Faktury z nowym NIP-em, które czekały, dopasowują się.
    """

    rows = list(
        await db.scalars(
            select(PayrollSettlement)
            .where(
                PayrollSettlement.user_id == user_id,
                PayrollSettlement.employment_type == B2B,
                PayrollSettlement.status.in_(
                    ("awaiting_document", "mismatch", "ready", "approved")
                ),
            )
            .order_by(PayrollSettlement.id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
    )
    billing = await billing_of(db, user_id)
    for row in rows:
        if payee_changed:
            clear_override(row)
            if row.status == "approved":
                _clear_approval(row)
                row.status = "ready"
        await recompute(db, row, billing=billing)
        await attach_waiting_invoices(db, row, await period_of(db, row))


__all__ = [
    "PERSON_LINK",
    "SettlementError",
    "attach_waiting_invoices",
    "billing_changed",
    "billing_of",
    "cancel_for_period",
    "clear_override",
    "ensure_for_period",
    "ensure_payable_by_hand",
    "load_settlements_since",
    "gross_issue_of",
    "invoice_period",
    "load_payout_day",
    "lock_settlement",
    "mark_paid",
    "match_invoice",
    "matched_invoices",
    "notify_review",
    "paid_moment",
    "payable",
    "payroll_ids",
    "person_name",
    "problems_now",
    "queue_link",
    "received_on",
    "recompute",
    "seller_issue_of",
]
