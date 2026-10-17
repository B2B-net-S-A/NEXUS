"""Faktury od osób w NEXUSIE: lista, PDF spoza KSeF, miesiąc, pominięcie (M5).

* ``list_invoices`` — zakładka „Faktury z KSeF” miesiąca Płac: faktury
  dopasowane do rozliczeń tego miesiąca, niedopasowane z tym miesiącem
  oraz niedopasowane bez okresu wystawione w tym albo następnym miesiącu
  (kandydaci „do przypisania”),
* ``add_manual_pdf`` — faktura spoza KSeF (do końca 2026 r. sprzedaż do
  10 000 zł brutto miesięcznie może zostać poza KSeF) z PDF-em i kwotami
  wpisanymi przez Płace; NIP osoby bez NIP-u w danych do rozliczeń uzupełnia
  ``billing_details.assign_nip``,
* ``assign_period`` — „Przypisz do miesiąca” (i do osoby, gdy NIP mają dwie),
  potem zwykłe dopasowanie,
* ``set_ignored`` — „Pomiń” fakturę, która nie jest rozliczeniem miesiąca
  (z powodem w śladzie) i „Przywróć”.
* ``status_payload`` — karta stanu KSeF (tylko odczyt).

Kwoty idą w odpowiedziach jako napisy dziesiętne; w śladzie z poziomem
``payroll``. Do logów — identyfikatory.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from pathlib import Path
from decimal import Decimal, InvalidOperation
from typing import Any, Optional

from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.scheduling import business_today
from app.models.hr_payroll import PayrollPeriod
from app.models.hr_profile import EmployeeProfile
from app.models.hr_settlement import (
    EmployeeBillingDetails,
    PayrollInvoice,
    PayrollSettlement,
)
from app.models.user import User
from app.services.hr import audit, billing_details, settlements, white_list
from app.services.hr.ksef import environment, pdf_store, sync
from app.services.hr.ksef.client import format_instant, parse_instant
from app.services.hr.payroll_errors import PayrollError
from app.services.hr.payroll_periods import add_months, month_end, month_start
from app.services.hr_settlement_schema import (
    AMOUNT_MAX,
    CURRENCIES,
    REASON_MAX_LENGTH,
)

NOT_FOUND = "Nie ma takiej faktury."
LIST_LIMIT = 500
_LIMIT = Decimal(AMOUNT_MAX)
_CENT = Decimal("0.01")

PROBLEM_REASONS = {
    "seller_mismatch": "NIP sprzedawcy w pliku jest inny niż w numerze KSeF.",
    "buyer_mismatch": "Nabywcą na fakturze nie jest spółka.",
    "pending_expired": "Faktura długo nie była gotowa do pobrania z KSeF.",
    "db:constraint": "Faktura ma dane, których NEXUS nie przyjmuje — sprawdź ją z osobą.",
}


class KsefInvoiceError(PayrollError):
    """Błąd zakładki faktur — zdanie dla Płac, bez danych do przelewu."""


def _money(value: Optional[Decimal]) -> Optional[str]:
    return None if value is None else f"{Decimal(value).quantize(_CENT):.2f}"


def parse_amount(raw: Any, label: str) -> Decimal:
    try:
        value = Decimal(str(raw).replace(",", ".").replace(" ", ""))
    except (InvalidOperation, ValueError):
        raise KsefInvoiceError(f"{label}: wpisz kwotę, np. 1234,50.") from None
    if not value.is_finite() or abs(value) > _LIMIT or value != value.quantize(_CENT):
        raise KsefInvoiceError(
            f"{label}: kwota z najwyżej dwoma miejscami po przecinku."
        )
    return value.quantize(_CENT)


# ── Lista ────────────────────────────────────────────────────────────────────


async def _names(db: AsyncSession, user_ids: set[int]) -> dict[int, str]:
    if not user_ids:
        return {}
    rows = await db.execute(select(User.id, User.name).where(User.id.in_(user_ids)))
    return {int(uid): name for uid, name in rows}


async def _registry_names(db: AsyncSession, nips: set[str]) -> dict[str, str]:
    if not nips:
        return {}
    rows = await db.execute(
        select(EmployeeBillingDetails.nip, EmployeeBillingDetails.registry_name).where(
            EmployeeBillingDetails.nip.in_(nips),
            EmployeeBillingDetails.registry_name.is_not(None),
        )
    )
    return {nip: name for nip, name in rows}


async def _settlement_refs(
    db: AsyncSession, settlement_ids: set[int]
) -> dict[int, dict[str, Any]]:
    if not settlement_ids:
        return {}
    rows = await db.execute(
        select(
            PayrollSettlement.id,
            PayrollSettlement.status,
            PayrollSettlement.expected_amount,
            PayrollPeriod.year,
            PayrollPeriod.month,
        )
        .join(PayrollPeriod, PayrollPeriod.id == PayrollSettlement.period_id)
        .where(PayrollSettlement.id.in_(settlement_ids))
    )
    return {
        int(sid): {
            "id": int(sid),
            "status": status,
            "expected_amount": _money(expected),
            "year": int(year),
            "month": int(month),
        }
        for sid, status, expected, year, month in rows
    }


def invoice_payload(
    invoice: PayrollInvoice,
    *,
    names: dict[int, str],
    registry: dict[str, str],
    settlement_refs: dict[int, dict[str, Any]],
) -> dict[str, Any]:
    period = settlements.invoice_period(invoice)
    return {
        "id": invoice.id,
        "source": invoice.source,
        "ksef_number": invoice.ksef_number,
        "ksef_acquired_at": format_instant(invoice.ksef_acquired_at)
        if invoice.ksef_acquired_at
        else None,
        "seller_nip": invoice.seller_nip,
        "seller_name": registry.get(invoice.seller_nip),
        "user": {"id": invoice.user_id, "name": names.get(invoice.user_id, "")}
        if invoice.user_id
        else None,
        "invoice_number": invoice.invoice_number,
        "invoice_kind": invoice.invoice_kind,
        "corrects_invoice_id": invoice.corrects_invoice_id,
        "corrected_ksef_number": invoice.corrected_ksef_number,
        "issue_date": invoice.issue_date.isoformat(),
        "sale_date": invoice.sale_date.isoformat() if invoice.sale_date else None,
        "period": f"{period[0]:04d}-{period[1]:02d}" if period else None,
        "currency": invoice.currency,
        "net_amount": _money(invoice.net_amount),
        "vat_amount": _money(invoice.vat_amount),
        "gross_amount": _money(invoice.gross_amount),
        "items_count": len(invoice.items or []),
        "match_status": invoice.match_status,
        "settlement": settlement_refs.get(invoice.settlement_id)
        if invoice.settlement_id
        else None,
        "has_pdf": bool(invoice.pdf_storage_key),
        "fetched_at": format_instant(invoice.fetched_at)
        if invoice.fetched_at
        else None,
    }


async def payloads(
    db: AsyncSession, invoices: list[PayrollInvoice]
) -> list[dict[str, Any]]:
    names = await _names(db, {inv.user_id for inv in invoices if inv.user_id})
    registry = await _registry_names(db, {inv.seller_nip for inv in invoices})
    refs = await _settlement_refs(
        db, {inv.settlement_id for inv in invoices if inv.settlement_id}
    )
    return [
        invoice_payload(inv, names=names, registry=registry, settlement_refs=refs)
        for inv in invoices
    ]


async def list_invoices(
    db: AsyncSession, *, year: Optional[int] = None, month: Optional[int] = None
) -> dict[str, Any]:
    query = select(PayrollInvoice)
    if year is not None and month is not None:
        matched_here = PayrollInvoice.settlement_id.in_(
            select(PayrollSettlement.id)
            .join(PayrollPeriod, PayrollPeriod.id == PayrollSettlement.period_id)
            .where(PayrollPeriod.year == year, PayrollPeriod.month == month)
        )
        next_year, next_month = add_months(year, month, 1)
        not_matched = PayrollInvoice.match_status != "matched"
        query = query.where(
            or_(
                matched_here,
                and_(
                    not_matched,
                    PayrollInvoice.period_year == year,
                    PayrollInvoice.period_month == month,
                ),
                and_(
                    not_matched,
                    PayrollInvoice.period_year.is_(None),
                    PayrollInvoice.sale_date.between(
                        month_start(year, month), month_end(year, month)
                    ),
                ),
                and_(
                    not_matched,
                    PayrollInvoice.period_year.is_(None),
                    PayrollInvoice.sale_date.is_(None),
                    PayrollInvoice.issue_date.between(
                        month_start(year, month), month_end(next_year, next_month)
                    ),
                ),
            )
        )
    rows = list(
        await db.scalars(
            query.order_by(
                PayrollInvoice.issue_date.desc(), PayrollInvoice.id.desc()
            ).limit(LIST_LIMIT)
        )
    )
    counts = {"total": len(rows), "matched": 0, "unmatched": 0, "ignored": 0}
    for row in rows:
        counts[row.match_status] = counts.get(row.match_status, 0) + 1
    return {"invoices": await payloads(db, rows), "counts": counts}


async def _locked(db: AsyncSession, invoice_id: int) -> PayrollInvoice:
    invoice = await db.scalar(
        select(PayrollInvoice)
        .where(PayrollInvoice.id == invoice_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if invoice is None:
        raise KsefInvoiceError(NOT_FOUND, 404)
    return invoice


async def get_invoice(db: AsyncSession, invoice_id: int) -> PayrollInvoice:
    invoice = await db.get(PayrollInvoice, invoice_id)
    if invoice is None:
        raise KsefInvoiceError(NOT_FOUND, 404)
    return invoice


def _audit(
    db: AsyncSession,
    invoice: PayrollInvoice,
    *,
    actor_id: int,
    action: str,
    details: dict[str, Any],
) -> None:
    audit.record(
        db,
        actor_user_id=actor_id,
        subject_user_id=invoice.user_id,
        entity_type="payroll_invoice",
        entity_id=invoice.id,
        action=action,
        sensitivity="payroll",
        details=details,
    )


# ── PDF spoza KSeF ───────────────────────────────────────────────────────────


def _valid_period(year: int, month: int) -> None:
    if not (2020 <= year <= 2100 and 1 <= month <= 12):
        raise KsefInvoiceError("Miesiąc rozliczenia jest spoza zakresu.")


async def add_manual_pdf(
    db: AsyncSession,
    *,
    actor: User,
    user_id: int,
    seller_nip: Optional[str],
    invoice_number: str,
    issue_date: date,
    sale_date: Optional[date],
    period_year: int,
    period_month: int,
    currency: str,
    net_amount: Any,
    vat_amount: Any,
    gross_amount: Any,
    pdf: bytes,
) -> PayrollInvoice:
    number = " ".join(str(invoice_number or "").split())
    if not 1 <= len(number) <= 256:
        raise KsefInvoiceError("Wpisz numer faktury (do 256 znaków).")
    if issue_date > business_today():
        raise KsefInvoiceError("Data wystawienia nie może być z przyszłości.")
    _valid_period(period_year, period_month)
    if currency not in CURRENCIES:
        raise KsefInvoiceError("Waluta faktury: PLN, EUR albo USD.")
    net = parse_amount(net_amount, "Netto")
    vat = parse_amount(vat_amount, "VAT")
    gross = parse_amount(gross_amount, "Brutto")
    if net < 0 or vat < 0 or gross <= 0:
        raise KsefInvoiceError("Kwoty faktury muszą być dodatnie.")
    if net + vat != gross:
        raise KsefInvoiceError("Netto + VAT musi dać brutto co do grosza.")
    try:
        digest = pdf_store.check_pdf(pdf)
    except pdf_store.PdfRejected as exc:
        raise KsefInvoiceError(str(exc)) from None

    profile = await db.scalar(
        select(EmployeeProfile.id).where(EmployeeProfile.user_id == user_id)
    )
    if profile is None:
        raise KsefInvoiceError("Nie ma takiej osoby.", 404)
    billing = await settlements.billing_of(db, user_id)
    nip = billing.nip if billing is not None else None
    if seller_nip:
        try:
            given = white_list.clean_nip(seller_nip)
        except white_list.WhiteListError as exc:
            raise KsefInvoiceError(exc.message) from None
        if nip and given != nip:
            raise KsefInvoiceError(
                "Ta osoba ma w danych do rozliczeń inny NIP — sprawdź fakturę.", 409
            )
        nip = given
    if not nip:
        raise KsefInvoiceError("Wpisz NIP sprzedawcy z faktury.")

    duplicate = await db.scalar(
        select(PayrollInvoice.id).where(
            or_(
                PayrollInvoice.pdf_sha256 == digest,
                and_(
                    PayrollInvoice.seller_nip == nip,
                    func.lower(PayrollInvoice.invoice_number) == number.lower(),
                    PayrollInvoice.invoice_kind == "original",
                ),
            )
        )
    )
    if duplicate is not None:
        raise KsefInvoiceError("Ta faktura jest już w NEXUSIE.", 409)

    key, _ = pdf_store.save_pdf(pdf)
    invoice = PayrollInvoice(
        source="manual_pdf",
        seller_nip=nip,
        user_id=user_id,
        invoice_number=number,
        invoice_kind="original",
        issue_date=issue_date,
        sale_date=sale_date,
        period_year=period_year,
        period_month=period_month,
        currency=currency,
        net_amount=net,
        vat_amount=vat,
        gross_amount=gross,
        items=[],
        pdf_storage_key=key,
        pdf_sha256=digest,
        match_status="unmatched",
        added_by=actor.id,
    )
    db.add(invoice)
    await db.flush()
    if billing is None or not billing.nip:
        try:
            await billing_details.assign_nip(
                db, user_id=user_id, nip=nip, actor_id=actor.id
            )
        except PayrollError as exc:
            raise KsefInvoiceError(exc.message, exc.status_code) from None
    await sync.match(db, invoice)
    _audit(
        db,
        invoice,
        actor_id=actor.id,
        action="payroll_invoice_added",
        details={
            "source": "manual_pdf",
            "period": f"{period_year:04d}-{period_month:02d}",
            "net": str(net),
            "currency": currency,
            "match_status": invoice.match_status,
        },
    )
    await db.flush()
    return invoice


async def pdf_path(db: AsyncSession, invoice_id: int) -> Path:
    invoice = await get_invoice(db, invoice_id)
    if not invoice.pdf_storage_key:
        raise KsefInvoiceError("Ta faktura nie ma PDF-u — jest w KSeF jako XML.", 404)
    try:
        return pdf_store.path_for(invoice.pdf_storage_key)
    except FileNotFoundError:
        raise KsefInvoiceError("Brak pliku PDF tej faktury.", 404) from None


# ── Przypisanie i pominięcie ─────────────────────────────────────────────────


async def assign_period(
    db: AsyncSession,
    *,
    actor: User,
    invoice_id: int,
    year: int,
    month: int,
    user_id: Optional[int] = None,
) -> PayrollInvoice:
    _valid_period(year, month)
    invoice = await _locked(db, invoice_id)
    if invoice.match_status == "matched":
        raise KsefInvoiceError("Faktura jest już dopasowana do rozliczenia.", 409)
    if user_id is not None:
        owners = await settlements.users_with_nip(db, invoice.seller_nip)
        if owners and user_id not in owners:
            raise KsefInvoiceError(
                "Ta osoba nie ma NIP-u z faktury w danych do rozliczeń.", 422
            )
        invoice.user_id = user_id
    invoice.period_year = year
    invoice.period_month = month
    invoice.match_status = "unmatched"
    await db.flush()
    await sync.match(db, invoice)
    _audit(
        db,
        invoice,
        actor_id=actor.id,
        action="payroll_invoice_period_assigned",
        details={
            "period": f"{year:04d}-{month:02d}",
            "match_status": invoice.match_status,
        },
    )
    await db.flush()
    return invoice


async def set_ignored(
    db: AsyncSession,
    *,
    actor: User,
    invoice_id: int,
    ignored: bool,
    reason: Optional[str],
) -> PayrollInvoice:
    invoice = await _locked(db, invoice_id)
    if ignored:
        text = " ".join(str(reason or "").split())
        if not 1 <= len(text) <= REASON_MAX_LENGTH:
            raise KsefInvoiceError("Napisz, dlaczego faktura nie jest rozliczeniem.")
        if invoice.match_status == "matched":
            raise KsefInvoiceError(
                "Faktura jest dopasowana do rozliczenia — nie można jej pominąć.", 409
            )
        invoice.match_status = "ignored"
        invoice.settlement_id = None
        await db.flush()
        _audit(
            db,
            invoice,
            actor_id=actor.id,
            action="payroll_invoice_ignored",
            details={"reason": text},
        )
    else:
        if invoice.match_status != "ignored":
            raise KsefInvoiceError("Ta faktura nie jest pominięta.", 409)
        invoice.match_status = "unmatched"
        await db.flush()
        await sync.match(db, invoice)
        _audit(
            db,
            invoice,
            actor_id=actor.id,
            action="payroll_invoice_restored",
            details={"match_status": invoice.match_status},
        )
    await db.flush()
    return invoice


# ── Karta stanu ──────────────────────────────────────────────────────────────


def _problem_text(reason: str) -> str:
    if reason.startswith("parse:"):
        return "Pliku faktury nie da się odczytać — sprawdź go z osobą w KSeF."
    if reason.startswith("ksef:"):
        return "KSeF odmówił pobrania faktury."
    return PROBLEM_REASONS.get(reason, "Faktury nie udało się zapisać.")


def _health(
    config: environment.KsefConfig, state: dict[str, Any], now: datetime
) -> str:
    """``healthy`` = udane pobranie w tym trybie w ostatnich 3 h i bez błędu."""

    if not config.enabled:
        return "disabled"
    if state.get("last_error") or state.get("mode") != config.mode:
        return "degraded"
    last = parse_instant(state.get("last_success_at"))
    return (
        "healthy"
        if last is not None and (now - last).total_seconds() < 3 * 3600
        else "degraded"
    )


async def health_state(db: AsyncSession, *, now: Optional[datetime] = None) -> str:
    """Sonda ``/api/health`` (``hr/health.PROBES``): disabled / healthy / degraded."""

    return _health(
        environment.load_config(),
        await sync.load_state(db),
        now or datetime.now(timezone.utc),
    )


async def status_payload(
    db: AsyncSession, *, now: Optional[datetime] = None
) -> dict[str, Any]:
    config = environment.load_config()
    state = await sync.load_state(db)
    moment = now or datetime.now(timezone.utc)
    reason = config.disabled_reason
    pending = (state.get("pending") or {}).get(config.state_key) or []
    blocked = parse_instant(state.get("blocked_until"))
    return {
        "mode": config.mode,
        "mode_label": environment.MODE_LABELS[config.mode],
        "enabled": config.enabled,
        "health": _health(config, state, moment),
        "disabled_reason": reason,
        "disabled_text": environment.DISABLED_REASONS.get(reason) if reason else None,
        "context_nip": config.context_nip or None,
        "token_configured": bool(config.token),
        "cursor": (state.get("cursors") or {}).get(config.state_key),
        "last_run_at": state.get("last_run_at"),
        "last_run_kind": state.get("last_run_kind"),
        "last_success_at": state.get("last_success_at"),
        "last_error": state.get("last_error"),
        "last_error_text": state.get("last_error_text"),
        "last_error_at": state.get("last_error_at"),
        "blocked_until": format_instant(blocked)
        if blocked and blocked > moment
        else None,
        "last_counts": state.get("last_counts") or {},
        "pending": len(pending),
        "problems": [
            {
                "ksef_number": problem.get("ksef_number"),
                "reason": problem.get("reason"),
                "text": _problem_text(str(problem.get("reason") or "")),
                "at": problem.get("at"),
            }
            for problem in reversed(state.get("problems") or [])
        ],
        "white_list": {"mode": white_list.current_mode(), **white_list.usage()},
    }
