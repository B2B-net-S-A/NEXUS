"""Przelewy z zatwierdzonej listy płac (K7a): wypłaty, ZUS, PIT-4 i PIT-8AR.

Plik powstaje w formacie paczki przelewów Płac (``bank/elixir.py``: Elixir-O
albo CSV, nadawca i format z Ustawień → Płace — ta sama opcja, domyślnie
wyłączona, ``batches.ensure_enabled``):

* **wypłaty** — kwota do wypłaty każdej pozycji > 0 na rachunek z danych do
  rozliczeń (zespół, ``employee_billing_details``) albo z danych płacowych
  (zleceniobiorca u klienta). Brak rachunku = pozycja poza plikiem z powodem,
* **ZUS** — jeden przelew na rachunek składkowy płatnika (NRS): składki osób
  i pracodawcy, zdrowotna, FP i FGŚP z listy,
* **PIT-4** — zaliczki (skala) na mikrorachunek podatkowy, tytuł przelewu do
  urzędu skarbowego ``/TI/N<NIP>/OKR/<RR>M<MM>/SFP/PIT4R/TXT/…``,
* **PIT-8AR** — podatek ryczałtowy (należności do 200 zł) tak samo,
  z symbolem ``PIT8AR``.

Przelewy do urzędu mają klasyfikację Elixir-O „71” (przelew podatkowy); jak
cały format paczki — do sprawdzenia w banku firmy przy pierwszym imporcie.
Pierwsze pobranie zapisuje przy pozycji 4 cyfry i skrót HMAC rachunku;
ponowne pobranie po zmianie rachunku = 409 ``batch_account_changed`` (jak
paczka R9). „Bank wykonał” zaznacza Płace — nie osoba z własną pozycją.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.encryption import TokenCipherNotConfigured
from app.core.scheduling import business_today, local_now
from app.models.hr_payroll_lists import PayrollList, PayrollListLine
from app.models.hr_settlement import EmployeeBillingDetails
from app.models.user import User
from app.services.hr import audit, billing_details
from app.services.hr.bank import batches, elixir
from app.services.hr.bank.settings import load_settings
from app.services.hr.payroll_errors import PayrollConflict, PayrollForbidden
from app.services.hr.payroll_lists import parameters, person_data
from app.services.hr.payroll_lists.engine import ZERO

#: Przelew podatkowy w Elixir-O (do sprawdzenia w banku firmy).
CLASSIFICATION_TAX = "71"


@dataclass(frozen=True)
class PlanRow:
    kind: str  # wage | zus | pit4 | pit8ar
    line_id: Optional[int]
    name: str
    amount: Decimal
    account_last4: Optional[str]
    included: bool
    reason: Optional[str] = None


def _d(raw: Any) -> Decimal:
    try:
        return Decimal(str(raw if raw not in (None, "") else "0"))
    except ArithmeticError:
        return ZERO


def tax_title(nip: str, pay: date, symbol: str, text: str) -> tuple[str, ...]:
    """Tytuł przelewu do US: identyfikator NIP, okres miesięczny, symbol formularza."""

    period = f"{pay.year % 100:02d}M{pay.month:02d}"
    full = f"/TI/N{nip}/OKR/{period}/SFP/{symbol}/TXT/{text}"
    return tuple(full[i : i + 35] for i in range(0, min(len(full), 140), 35))


def sums(lines: list[PayrollListLine]) -> dict[str, Decimal]:
    out = {"zus": ZERO, "pit4": ZERO, "pit8ar": ZERO}
    for line in lines:
        result = line.result or {}
        out["zus"] += _d(result.get("zus_due"))
        if result.get("tax_kind") == "flat":
            out["pit8ar"] += _d(result.get("pit"))
        else:
            out["pit4"] += _d(result.get("pit"))
    return out


async def _accounts(
    db: AsyncSession, lines: list[PayrollListLine]
) -> dict[int, tuple[Optional[str], Optional[str]]]:
    """Pozycja → (pełny rachunek albo ``None``, powód braku)."""

    user_ids = {line.user_id for line in lines if line.user_id is not None}
    billing: dict[int, EmployeeBillingDetails] = {}
    if user_ids:
        billing = {
            item.user_id: item
            for item in await db.scalars(
                select(EmployeeBillingDetails).where(
                    EmployeeBillingDetails.user_id.in_(user_ids)
                )
            )
        }
    candidate_ids = {
        line.candidate_id for line in lines if line.candidate_id is not None
    }
    records = await person_data.records_for(db, set(), candidate_ids)
    out: dict[int, tuple[Optional[str], Optional[str]]] = {}
    for line in lines:
        try:
            if line.user_id is not None:
                account = billing_details.decrypt_account(billing.get(line.user_id))
                out[line.id] = (account, None if account else "no_account")
            else:
                record = records.get(f"c{line.candidate_id}")
                data = person_data.decrypt(record) if record else {}
                account = data.get("bank_account")
                out[line.id] = (account, None if account else "no_account")
        except (TokenCipherNotConfigured, ValueError, person_data.PersonDataError):
            out[line.id] = (None, "account_unreadable")
    return out


REASONS = {
    "no_account": "Brak rachunku do wypłaty.",
    "account_unreadable": "Nie udało się odczytać rachunku — sprawdź klucz szyfrowania.",
    "no_company_account": "Brak rachunku płatnika w danych płatnika (Księgowość → Lista płac → parametry).",
    "zero": "Kwota 0.",
}


async def plan(
    db: AsyncSession, lst: PayrollList
) -> tuple[list[PlanRow], dict[int, str]]:
    lines = list(
        await db.scalars(
            select(PayrollListLine)
            .where(PayrollListLine.list_id == lst.id)
            .order_by(PayrollListLine.person_name, PayrollListLine.id)
        )
    )
    accounts = await _accounts(db, lines)
    company = await parameters.load_company(db)
    rows: list[PlanRow] = []
    full: dict[int, str] = {}
    for line in lines:
        amount = _d(line.net)
        account, reason = accounts.get(line.id, (None, "no_account"))
        if amount <= 0:
            reason = "zero"
        rows.append(
            PlanRow(
                kind="wage",
                line_id=line.id,
                name=line.person_name,
                amount=amount,
                account_last4=account[-4:] if account else None,
                included=reason is None,
                reason=REASONS.get(reason) if reason else None,
            )
        )
        if reason is None and account:
            full[line.id] = account
    totals = sums(lines)
    for kind, label, account in (
        ("zus", "ZUS — składki", company.zus_account),
        ("pit4", "Urząd skarbowy — zaliczki PIT-4", company.tax_account),
        ("pit8ar", "Urząd skarbowy — podatek ryczałtowy PIT-8AR", company.tax_account),
    ):
        amount = totals[kind]
        if amount <= 0:
            continue
        rows.append(
            PlanRow(
                kind=kind,
                line_id=None,
                name=label,
                amount=amount,
                account_last4=account[-4:] if account else None,
                included=bool(account),
                reason=None if account else REASONS["no_company_account"],
            )
        )
    return rows, full


def plan_payload(rows: list[PlanRow]) -> list[dict[str, Any]]:
    return [
        {
            "kind": row.kind,
            "line_id": row.line_id,
            "name": row.name,
            "amount": str(row.amount),
            "account_last4": row.account_last4,
            "included": row.included,
            "reason": row.reason,
        }
        for row in rows
    ]


async def build_file(
    db: AsyncSession, *, actor: User, lst: PayrollList
) -> tuple[bytes, str, str, list[PlanRow]]:
    """Plik przelewów (bez commita): treść, nazwa, typ i plan z wykluczeniami."""

    if lst.status != "approved":
        raise PayrollConflict(
            "Przelewy powstają z zatwierdzonej listy.", code="list_not_approved"
        )
    settings = await load_settings(db)
    batches.ensure_enabled(settings)
    sender_account = settings.transfer_batch.sender_account
    if not sender_account:
        raise PayrollConflict(
            "Brak rachunku nadawcy w Ustawieniach → Rozliczenia.", code="no_sender"
        )
    rows, accounts = await plan(db, lst)
    lines = {
        line.id: line
        for line in await db.scalars(
            select(PayrollListLine).where(PayrollListLine.list_id == lst.id)
        )
    }
    first_time = lst.transfers_created_at is None
    for line_id, account in accounts.items():
        line = lines[line_id]
        try:
            fingerprint = billing_details.account_fingerprint(account)
        except TokenCipherNotConfigured:
            raise PayrollConflict(
                "Szyfrowanie rachunków nie jest skonfigurowane.", code="no_cipher"
            ) from None
        if line.payee_hmac and line.payee_hmac != fingerprint:
            raise PayrollConflict(
                f"Rachunek osoby „{line.person_name}” zmienił się po pierwszym pobraniu "
                "pliku — sprawdź zmianę i przygotuj przelew ręcznie albo anuluj listę.",
                code="batch_account_changed",
            )
        line.payee_hmac = fingerprint
        line.payee_last4 = account[-4:]
    company = await parameters.load_company(db)
    execution = max(lst.pay_date, business_today())
    period_text = f"{lst.month:02d}/{lst.year}"
    transfer_rows: list[elixir.TransferRow] = []
    for row in rows:
        if not row.included:
            continue
        if row.kind == "wage" and row.line_id is not None:
            transfer_rows.append(
                elixir.TransferRow(
                    recipient_name=row.name,
                    recipient_account=accounts[row.line_id],
                    amount=row.amount,
                    title_lines=(f"Wynagrodzenie {period_text}", lst.number),
                    execution_date=execution,
                )
            )
        elif row.kind == "zus" and company.zus_account:
            transfer_rows.append(
                elixir.TransferRow(
                    recipient_name="ZAKŁAD UBEZPIECZEŃ SPOŁECZNYCH",
                    recipient_account=company.zus_account,
                    amount=row.amount,
                    title_lines=(
                        f"Składki ZUS {lst.pay_date.month:02d}/{lst.pay_date.year}",
                        lst.number,
                    ),
                    execution_date=execution,
                )
            )
        elif row.kind in ("pit4", "pit8ar") and company.tax_account:
            symbol = "PIT4R" if row.kind == "pit4" else "PIT8AR"
            transfer_rows.append(
                elixir.TransferRow(
                    recipient_name="URZĄD SKARBOWY",
                    recipient_account=company.tax_account,
                    amount=row.amount,
                    title_lines=tax_title(
                        company.nip, lst.pay_date, symbol, lst.number
                    ),
                    execution_date=execution,
                    classification=CLASSIFICATION_TAX,
                )
            )
    if not transfer_rows:
        raise PayrollConflict(
            "Żadna pozycja nie ma rachunku — nic do przelania.", code="nothing_to_pay"
        )
    sender = elixir.Sender(
        name=settings.transfer_batch.sender_name, account=sender_account
    )
    fmt = settings.transfer_batch.format
    base = f"przelewy-{lst.number.replace('/', '-').lower()}"
    if fmt == "csv":
        content, name, media = (
            elixir.render_csv(transfer_rows),
            f"{base}.csv",
            "text/csv",
        )
    else:
        content = elixir.render_elixir(transfer_rows, sender)
        name, media = f"{base}.pli", "application/octet-stream"
    if first_time:
        lst.transfers_created_at = local_now()
        lst.transfers_created_by = actor.id
    await db.flush()
    audit.record(
        db,
        actor_user_id=actor.id,
        subject_user_id=None,
        entity_type="payroll_list",
        entity_id=lst.id,
        action="payroll_list_transfers_downloaded",
        sensitivity="payroll",
        details={
            "number": lst.number,
            "format": fmt,
            "rows": len(transfer_rows),
            "excluded": sum(1 for row in rows if not row.included),
        },
    )
    return content, name, media, rows


async def mark_paid(db: AsyncSession, *, actor: User, lst: PayrollList) -> PayrollList:
    if lst.status != "approved" or lst.transfers_created_at is None:
        raise PayrollConflict(
            "Najpierw pobierz plik przelewów zatwierdzonej listy.", code="no_transfers"
        )
    own = await db.scalar(
        select(PayrollListLine.id).where(
            PayrollListLine.list_id == lst.id, PayrollListLine.user_id == actor.id
        )
    )
    if own is not None:
        raise PayrollForbidden(
            "Na liście jest Twoja pozycja — wykonanie przelewów potwierdza inna osoba "
            "z Rozliczeń."
        )
    if lst.paid_at is None:
        lst.paid_at = local_now()
        lst.paid_by = actor.id
        audit.record(
            db,
            actor_user_id=actor.id,
            subject_user_id=None,
            entity_type="payroll_list",
            entity_id=lst.id,
            action="payroll_list_paid",
            sensitivity="payroll",
            details={"number": lst.number},
        )
        await db.flush()
    return lst


__all__ = [
    "CLASSIFICATION_TAX",
    "PlanRow",
    "build_file",
    "mark_paid",
    "plan",
    "plan_payload",
    "sums",
    "tax_title",
]
