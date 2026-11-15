"""Wycena walut na koniec miesiąca (K4c-2) — art. 30 ust. 1 ustawy o rachunkowości.

Na dzień bilansowy (31.12, obowiązkowo) albo na koniec dowolnego miesiąca
(zarządczo) pozycje w walucie przelicza się po średnim kursie NBP obowiązującym
na ten dzień — ostatnim ogłoszonym do tego dnia, nie starszym niż tydzień
(starszy = luka w pobieraniu kursów, nie kurs).

* **Rozrachunki**: otwarte pozycje walutowe kontrahentów na ten dzień
  (``settlements.load_items``), netto per konto i waluta: Wn ze znakiem +,
  Ma ze znakiem −. Pozycje płacowe (D2) zostają poza wyceną — ich PK zrobiłby
  osoba z Płacami ręcznie.
* **Rachunki walutowe** z Ustawień (Bank): saldo konta rachunku w walucie
  (Σ ``amount_cur`` pozycji w tej walucie) i w PLN z zatwierdzonych zapisów do
  tego dnia — tak jak w obrotach i saldach (storno liczy się ze znakiem).
* Korekta konta = wartość po kursie − kwota w księdze: dodatnia = Wn konto,
  Ma przychody finansowe; ujemna = Wn koszty finansowe, Ma konto (konta różnic
  kursowych z K4c-1).
* **PK wyceny** na ostatni dzień miesiąca (źródło ``fx_valuation`` / RRRR-MM)
  i **odwrócenie** pierwszego dnia następnego miesiąca
  (``fx_valuation_reversal`` / RRRR-MM), żeby rozliczenia liczyły różnice od
  kursów historycznych. Brak następnego okresu (nowy rok) albo zamknięty =
  odwrócenie czeka, wycena idzie. Odcisk jak w K2: bez zmian / przebudowa
  szkicu / zatwierdzony inny = 409 (storno).
* Pozycje PK wyceny i odwrócenia nie są rozrachunkami — rozrachunki są
  w kursach historycznych (``settlements.NOT_ITEMS``).
"""

from __future__ import annotations

import calendar
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal
from typing import Any, Optional

from sqlalchemy import case, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.finance_ledger import FinanceCounterparty
from app.models.fx_rate import FxRate
from app.models.ledger import LedgerDocument, LedgerLine, LedgerPeriod, LedgerYear
from app.services.finance_ledger.costs import LedgerError
from app.services.ledger import documents, settlements, sources
from app.services.ledger.documents import DocumentSpec, Viewer
from app.services.ledger.engine import LineIn
from app.services.ledger.settings import BankSettings

SOURCE = documents.FX_VALUATION_SOURCE
REVERSAL_SOURCE = documents.FX_VALUATION_REVERSAL_SOURCE
RATE_MAX_AGE = 7
LOCK_KEY = "ledger-fx-valuation"
APPROVERS_ONLY = "Wycenę księguje osoba z listy „Księgowi” albo administrator."
APPROVED = (
    "{label} na {day} jest zatwierdzona ({number}) i różni się od dzisiejszej — "
    "najpierw storno tego dokumentu."
)


@dataclass(frozen=True)
class Position:
    """Pozycja wyceny: konto, waluta, kwota w walucie i w księdze (Wn = +)."""

    account: str
    kind: str
    currency: str
    amount_cur: int
    book: int
    rate: Decimal
    counterparty_id: Optional[int] = None

    @property
    def valued(self) -> int:
        return int(
            (Decimal(self.amount_cur) * self.rate).quantize(
                Decimal("1"), rounding=ROUND_HALF_UP
            )
        )

    @property
    def diff(self) -> int:
        """Korekta salda konta: + = Wn konto (dodatnia różnica), − = Ma konto."""

        return self.valued - self.book


def month_end(year: int, month: int) -> date:
    return date(year, month, calendar.monthrange(year, month)[1])


def key(year: int, month: int) -> str:
    return f"{year}-{month:02d}"


def settlement_positions(
    items: list[settlements.Item], rates: dict[str, tuple[Decimal, date]]
) -> list[Position]:
    """Otwarte pozycje walutowe (bez płacowych) netto per konto i waluta."""

    cur: dict[tuple[str, str], int] = defaultdict(int)
    book: dict[tuple[str, str], int] = defaultdict(int)
    party: dict[tuple[str, str], Optional[int]] = {}
    for item in items:
        if not item.is_currency or item.sensitivity is not None:
            continue
        left_cur = item.remaining_cur or 0
        if item.remaining <= 0 or left_cur <= 0 or item.currency not in rates:
            continue
        sign = 1 if item.direction == "debit" else -1
        slot = (item.account, item.currency)
        cur[slot] += sign * left_cur
        book[slot] += sign * item.remaining
        party.setdefault(slot, item.counterparty_id)
    return [
        Position(
            account=account,
            kind="settlement",
            currency=currency,
            amount_cur=cur[(account, currency)],
            book=book[(account, currency)],
            rate=rates[currency][0],
            counterparty_id=party.get((account, currency)),
        )
        for account, currency in sorted(cur)
    ]


def valuation_lines(
    positions: list[Position], *, gain: str, loss: str, text_: str
) -> list[LineIn]:
    """Korekty kont i zbiorcze linie przychodów i kosztów finansowych."""

    lines: list[LineIn] = []
    gains = losses = 0
    for item in positions:
        diff = item.diff
        if not diff:
            continue
        label = f"{text_} · {item.currency} {item.rate}"[:200]
        side = "debit" if diff > 0 else "credit"
        lines.append(
            LineIn(
                side,
                item.account,
                abs(diff),
                label,
                counterparty_id=item.counterparty_id,
            )
        )
        if diff > 0:
            gains += diff
        else:
            losses -= diff
    if gains:
        lines.append(LineIn("credit", gain, gains, text_))
    if losses:
        lines.append(LineIn("debit", loss, losses, text_))
    return lines


def reversed_lines(lines: list[LineIn]) -> list[LineIn]:
    """Odwrócenie wyceny: te same konta i kwoty po przeciwnej stronie."""

    flip = {"debit": "credit", "credit": "debit"}
    return [
        LineIn(
            flip[line.side],
            line.account,
            line.amount,
            line.description,
            counterparty_id=line.counterparty_id,
        )
        for line in lines
    ]


async def nbp_rates(
    db: AsyncSession, currencies: set[str], day: date
) -> tuple[dict[str, tuple[Decimal, date]], list[str]]:
    """Kurs NBP obowiązujący na ``day`` (ostatni ogłoszony, nie starszy niż tydzień)."""

    found: dict[str, tuple[Decimal, date]] = {}
    for currency in sorted(currencies):
        row = (
            await db.execute(
                select(FxRate.rate_to_pln, FxRate.effective_date)
                .where(
                    FxRate.currency == currency,
                    FxRate.source == "NBP",
                    FxRate.effective_date <= day,
                    FxRate.effective_date >= day - timedelta(days=RATE_MAX_AGE),
                )
                .order_by(FxRate.effective_date.desc())
                .limit(1)
            )
        ).first()
        if row is not None:
            found[currency] = (Decimal(row.rate_to_pln), row.effective_date)
    return found, sorted(currencies - set(found))


async def bank_positions(
    db: AsyncSession,
    bank_settings: BankSettings,
    day: date,
    rates: dict[str, tuple[Decimal, date]],
    *,
    own: str,
) -> list[Position]:
    """Salda rachunków walutowych z zatwierdzonych zapisów do ``day`` (bez tej wyceny)."""

    out: list[Position] = []
    for company in bank_settings.accounts:
        if company.currency == "PLN" or company.currency not in rates:
            continue
        sign = case((LedgerLine.side == "debit", 1), else_=-1)
        row = (
            await db.execute(
                select(
                    func.coalesce(func.sum(sign * LedgerLine.amount), 0),
                    func.coalesce(
                        func.sum(
                            case(
                                (
                                    LedgerLine.currency == company.currency,
                                    sign * func.coalesce(LedgerLine.amount_cur, 0),
                                ),
                                else_=0,
                            )
                        ),
                        0,
                    ),
                )
                .join(LedgerDocument, LedgerDocument.id == LedgerLine.document_id)
                .where(
                    LedgerLine.account == company.account,
                    LedgerDocument.status == "approved",
                    LedgerDocument.op_date <= day,
                    # Bez tej wyceny (przebudowa); dokumenty bez źródła zostają —
                    # samo „NOT (typ = … AND id = …)” odrzuciłoby je przez NULL.
                    or_(
                        LedgerDocument.source_type.is_(None),
                        LedgerDocument.source_type != SOURCE,
                        LedgerDocument.source_id != own,
                    ),
                )
            )
        ).one()
        book, amount_cur = int(row[0]), int(row[1])
        if not amount_cur and not book:
            continue
        out.append(
            Position(
                account=company.account,
                kind="bank",
                currency=company.currency,
                amount_cur=amount_cur,
                book=book,
                rate=rates[company.currency][0],
            )
        )
    return out


async def _document(
    db: AsyncSession, source: str, own: str
) -> Optional[LedgerDocument]:
    return await db.scalar(
        select(LedgerDocument).where(
            LedgerDocument.source_type == source,
            LedgerDocument.source_id == own,
            LedgerDocument.reversed_by_id.is_(None),
        )
    )


async def _next_period_open(db: AsyncSession, day: date) -> Optional[str]:
    """Powód, dla którego odwrócenia nie da się założyć (``None`` = można)."""

    period = await db.scalar(
        select(LedgerPeriod.status)
        .join(LedgerYear, LedgerYear.id == LedgerPeriod.year_id)
        .where(LedgerYear.year == day.year, LedgerPeriod.month == day.month)
    )
    if period is None:
        return (
            f"odwrócenie {day:%d.%m.%Y} czeka na rok obrotowy {day.year} — "
            "zaksięguj wycenę ponownie po jego założeniu"
        )
    if period != "open":
        return f"odwrócenie {day:%d.%m.%Y} czeka — okres {day:%m.%Y} jest zamknięty"
    return None


def _doc_payload(doc: Optional[LedgerDocument]) -> Optional[dict[str, Any]]:
    if doc is None:
        return None
    return {"id": doc.id, "number": doc.number, "status": doc.status}


@dataclass
class Valuation:
    day: date
    own: str
    rates: dict[str, tuple[Decimal, date]]
    missing: list[str]
    positions: list[Position]
    #: Wycena poprzedniego miesiąca bez zaksięgowanego odwrócenia — nowa
    #: dodałaby różnicę drugi raz do salda konta.
    previous_open: Optional[str] = None


async def _previous_open(db: AsyncSession, year: int, month: int) -> Optional[str]:
    prev_year, prev_month = (year, month - 1) if month > 1 else (year - 1, 12)
    previous = key(prev_year, prev_month)
    valuation = await _document(db, SOURCE, previous)
    if valuation is None or valuation.status != "approved":
        return None
    reversal = await _document(db, REVERSAL_SOURCE, previous)
    if reversal is not None and reversal.status == "approved":
        return None
    return (
        f"Wycena z {month_end(prev_year, prev_month):%d.%m.%Y} ({valuation.number}) "
        "nie ma zaksięgowanego odwrócenia — zaksięguj je najpierw (wycena tamtego "
        "miesiąca ponownie robi odwrócenie, gdy okres jest otwarty)."
    )


async def compute(
    db: AsyncSession,
    viewer: Viewer,
    bank_settings: BankSettings,
    *,
    year: int,
    month: int,
) -> Valuation:
    if not 1 <= month <= 12:
        raise LedgerError("Niepoprawny miesiąc.", status=422)
    day = month_end(year, month)
    own = key(year, month)
    parents = await settlements.load_parents(db)
    items = await settlements.load_items(db, viewer, parents=parents, as_of=day)
    currencies = {item.currency for item in items if item.is_currency}
    currencies |= {
        account.currency
        for account in bank_settings.accounts
        if account.currency != "PLN"
    }
    rates, missing = await nbp_rates(db, currencies, day)
    positions = settlement_positions(items, rates) + await bank_positions(
        db, bank_settings, day, rates, own=own
    )
    return Valuation(
        day, own, rates, missing, positions, await _previous_open(db, year, month)
    )


async def preview(
    db: AsyncSession,
    viewer: Viewer,
    bank_settings: BankSettings,
    *,
    year: int,
    month: int,
) -> dict[str, Any]:
    """Wycena na koniec miesiąca (bez zapisu): kursy, pozycje, korekty, dokumenty."""

    found = await compute(db, viewer, bank_settings, year=year, month=month)
    names = await _account_names(db, bank_settings, found.positions)
    valuation = await _document(db, SOURCE, found.own)
    reversal = await _document(db, REVERSAL_SOURCE, found.own)
    gain = sum(item.diff for item in found.positions if item.diff > 0)
    loss = -sum(item.diff for item in found.positions if item.diff < 0)
    return {
        "year": year,
        "month": month,
        "day": found.day.isoformat(),
        "rates": [
            {"currency": currency, "rate": str(rate), "date": day.isoformat()}
            for currency, (rate, day) in sorted(found.rates.items())
        ],
        "missing_rates": found.missing,
        "positions": [
            {
                "account": item.account,
                "name": names.get(item.account, ""),
                "kind": item.kind,
                "currency": item.currency,
                "amount_cur": item.amount_cur,
                "book": item.book,
                "valued": item.valued,
                "diff": item.diff,
            }
            for item in found.positions
        ],
        "gain": gain,
        "loss": loss,
        "documents": {
            "valuation": _doc_payload(valuation),
            "reversal": _doc_payload(reversal),
        },
        "blocker": _blocker(found, bank_settings),
        "can_post": viewer.approver,
    }


async def _account_names(
    db: AsyncSession, bank_settings: BankSettings, positions: list[Position]
) -> dict[str, str]:
    """Kontrahent z pozycji (bez płacowych — D2) albo nazwa rachunku z Ustawień."""

    ids = {item.counterparty_id for item in positions if item.counterparty_id}
    parties: dict[int, str] = {}
    if ids:
        rows = await db.execute(
            select(FinanceCounterparty.id, FinanceCounterparty.name).where(
                FinanceCounterparty.id.in_(ids)
            )
        )
        parties = dict(rows.all())
    names = {
        account.account: account.name or f"rachunek …{account.number[-4:]}"
        for account in bank_settings.accounts
    }
    for item in positions:
        if item.kind == "settlement":
            names[item.account] = parties.get(item.counterparty_id or 0, "")
    return names


def _blocker(found: Valuation, bank_settings: BankSettings) -> Optional[str]:
    if found.previous_open:
        return found.previous_open
    if found.missing:
        return (
            f"Brak kursu NBP {', '.join(found.missing)} z ostatnich dni przed "
            f"{found.day:%d.%m.%Y} — pobierz kursy (Finanse → Kursy walut)."
        )
    if (
        any(item.diff > 0 for item in found.positions)
        and not bank_settings.fx_gain_account
    ):
        return "Ustaw konto dodatnich różnic kursowych w Ustawieniach (Bank)."
    if (
        any(item.diff < 0 for item in found.positions)
        and not bank_settings.fx_loss_account
    ):
        return "Ustaw konto ujemnych różnic kursowych w Ustawieniach (Bank)."
    return None


async def _write(
    db: AsyncSession,
    spec: Optional[DocumentSpec],
    existing: Optional[LedgerDocument],
    *,
    viewer: Viewer,
    plan: dict[str, Any],
    label: str,
) -> tuple[str, Optional[LedgerDocument]]:
    """``unchanged`` / ``rebuilt`` / ``created`` / ``removed`` / ``none``."""

    if spec is None:
        if existing is None:
            return "none", None
        if existing.status != "draft":
            raise LedgerError(
                APPROVED.format(
                    label=label,
                    day=existing.op_date.strftime("%d.%m.%Y"),
                    number=existing.number,
                ),
                status=409,
            )
        await documents.delete_draft(db, existing.id, viewer=viewer)
        return "removed", None
    mark = sources.fingerprint(spec)
    spec.meta["fingerprint"] = mark
    if existing is not None:
        if (existing.meta or {}).get("fingerprint") == mark:
            return "unchanged", existing
        if existing.status != "draft":
            raise LedgerError(
                APPROVED.format(
                    label=label,
                    day=existing.op_date.strftime("%d.%m.%Y"),
                    number=existing.number,
                ),
                status=409,
            )
        await documents.delete_draft(db, existing.id, viewer=viewer)
        created = await documents.create_draft(
            db, spec, actor_id=viewer.user_id, plan=plan
        )
        return "rebuilt", created
    created = await documents.create_draft(db, spec, actor_id=viewer.user_id, plan=plan)
    return "created", created


async def post(
    db: AsyncSession,
    viewer: Viewer,
    bank_settings: BankSettings,
    *,
    year: int,
    month: int,
) -> dict[str, Any]:
    """„Zaksięguj wycenę”: PK wyceny i jej odwrócenie do bufora (bez commita)."""

    if not viewer.approver:
        raise LedgerError(APPROVERS_ONLY, status=403)
    await db.execute(select(func.pg_advisory_xact_lock(func.hashtext(LOCK_KEY))))
    found = await compute(db, viewer, bank_settings, year=year, month=month)
    problem = _blocker(found, bank_settings)
    if problem:
        raise LedgerError(problem, status=422)
    text_ = f"Wycena walut na {found.day:%d.%m.%Y}"
    lines = valuation_lines(
        found.positions,
        gain=bank_settings.fx_gain_account,
        loss=bank_settings.fx_loss_account,
        text_=text_,
    )
    plan = await documents.load_plan(db)
    spec = (
        DocumentSpec(
            doc_type="PK",
            op_date=found.day,
            doc_date=found.day,
            lines=lines,
            description=text_,
            source_type=SOURCE,
            source_id=found.own,
            meta={"valuation": found.own},
        )
        if lines
        else None
    )
    outcome, doc = await _write(
        db,
        spec,
        await _document(db, SOURCE, found.own),
        viewer=viewer,
        plan=plan,
        label="Wycena",
    )
    next_day = found.day + timedelta(days=1)
    waiting = await _next_period_open(db, next_day) if lines else None
    reversal_spec = None
    if lines and waiting is None:
        reversal_spec = DocumentSpec(
            doc_type="PK",
            op_date=next_day,
            doc_date=next_day,
            lines=reversed_lines(lines),
            description=f"Odwrócenie wyceny walut z {found.day:%d.%m.%Y}",
            source_type=REVERSAL_SOURCE,
            source_id=found.own,
            meta={"valuation": found.own},
        )
    existing_reversal = await _document(db, REVERSAL_SOURCE, found.own)
    if reversal_spec is None and lines and existing_reversal is not None:
        # Odwrócenie, które już jest, zostaje — następny okres zamknięto po nim.
        reversal_outcome, reversal = "unchanged", existing_reversal
    else:
        reversal_outcome, reversal = await _write(
            db,
            reversal_spec,
            existing_reversal,
            viewer=viewer,
            plan=plan,
            label="Odwrócenie wyceny",
        )
    return {
        "valuation": {"outcome": outcome, **(_doc_payload(doc) or {})},
        "reversal": {"outcome": reversal_outcome, **(_doc_payload(reversal) or {})},
        "reversal_waiting": waiting,
        "gain": sum(item.diff for item in found.positions if item.diff > 0),
        "loss": -sum(item.diff for item in found.positions if item.diff < 0),
    }
