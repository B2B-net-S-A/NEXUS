"""Wycena walut na koniec miesiąca (K4c-2) — art. 30 ust. 1 ustawy o rachunkowości.

Na dzień bilansowy (31.12, obowiązkowo) albo na koniec dowolnego miesiąca
(zarządczo) pozycje w walucie przelicza się po średnim kursie NBP obowiązującym
na ten dzień: z ostatniego dnia roboczego miesiąca (``posting.rate_day``
następnego dnia), dokładnie z tego dnia. Brak kursu = blokada, nie starszy kurs —
kurs sprzed kilku dni przeszedłby po cichu (przegląd K4c-2 15.11.2026).

* **Rozrachunki**: otwarte pozycje walutowe kontrahentów na ten dzień
  (``settlements.load_items``), netto per konto i waluta: Wn ze znakiem +,
  Ma ze znakiem −.
* **Rachunki walutowe** z Ustawień (Bank): saldo konta rachunku w walucie
  i w PLN z zatwierdzonych zapisów bieżącego roku obrotowego (BO i obroty do
  tego dnia — jak w obrotach i saldach), bez wyceny tego miesiąca i jej storna.
  Rachunek z zapisami bez kwoty w walucie (BO z Symfonii, ręczna PK) albo bez BO
  po poprzednim roku jest pominięty z powodem — wycena odpisałaby wtedy saldo
  PLN, którego waluty nie znamy.
* **D2**: pozycje płacowe i rachunek z wypłatami dla zespołu wycenia osobna PK
  płacowa (``RRRR-MM-payroll``), widoczna tylko dla osób z Płacami.
* Korekta konta = wartość po kursie − kwota w księdze: dodatnia = Wn konto,
  Ma przychody finansowe; ujemna = Wn koszty finansowe, Ma konto (konta różnic
  kursowych z K4c-1).
* **PK wyceny** na ostatni dzień miesiąca (źródło ``fx_valuation`` / RRRR-MM)
  i **odwrócenie** pierwszego dnia następnego miesiąca
  (``fx_valuation_reversal``) — z zaksięgowanej PK, nie z dzisiejszego
  przeliczenia. Brak następnego okresu albo zamknięty = odwrócenie czeka.
  Szkic jak w K2: bez zmian / przebudowa. Zatwierdzonej się nie podmienia:
  różnica od dzisiejszego przeliczenia to flaga ``changed`` (storno robi
  księgowa).
* **Kolejność**: wycena czeka, dopóki którakolwiek wcześniejsza zatwierdzona
  wycena nie ma zatwierdzonego odwrócenia, które ją odwraca (albo odwrócenie
  zostało bez wyceny) — inaczej korekta weszłaby do salda drugi raz.
* Pozycje PK wyceny i odwrócenia nie są rozrachunkami — rozrachunki są
  w kursach historycznych (``settlements.NOT_ITEMS``).
"""

from __future__ import annotations

import calendar
from collections import defaultdict
from dataclasses import dataclass, replace
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal
from typing import Any, Optional

from sqlalchemy import and_, case, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.scheduling import business_today
from app.models.finance_ledger import FinanceCounterparty
from app.models.fx_rate import FxRate
from app.models.ledger import LedgerDocument, LedgerLine, LedgerPeriod, LedgerYear
from app.services.finance_ledger import posting
from app.services.finance_ledger.costs import LedgerError
from app.services.ledger import documents, settlements, sources
from app.services.ledger.documents import DocumentSpec, Viewer
from app.services.ledger.engine import LineIn
from app.services.ledger.settings import BankSettings

SOURCE = documents.FX_VALUATION_SOURCE
REVERSAL_SOURCE = documents.FX_VALUATION_REVERSAL_SOURCE
PAYROLL_SUFFIX = "-payroll"
LOCK_KEY = "ledger-fx-valuation"
SKIPPED_DOCS = 3
APPROVERS_ONLY = "Wycenę księguje osoba z listy „Księgowi” albo administrator."
APPROVED = (
    "{label} z {day}: zatwierdzony dokument {number} różni się od dzisiejszego — "
    "najpierw jego storno."
)
WAITING = (
    "Wycena z {day} ({number}) nie ma zaksięgowanego odwrócenia — zaksięguj je "
    "najpierw (ponowna wycena tamtego miesiąca robi odwrócenie, gdy okres jest "
    "otwarty)."
)
ORPHAN = (
    "Odwrócenie wyceny {number} z {day} zostało bez zaksięgowanej wyceny — zrób "
    "jego storno albo zaksięguj wycenę tamtego miesiąca ponownie."
)
STALE = (
    "Odwrócenie {reversal} nie odwraca wyceny {number} z {day} (to odwrócenie "
    "wcześniejszej wersji) — storno odwrócenia i ponowna wycena tamtego miesiąca."
)
_FLIP = {"debit": "credit", "credit": "debit"}


@dataclass(frozen=True)
class Position:
    """Pozycja wyceny: konto, waluta, kwota w walucie i w księdze (Wn = +)."""

    account: str
    kind: str
    currency: str
    amount_cur: int
    book: int
    #: ``None`` = brak kursu NBP z dnia wyceny (pozycja jest, wyceny nie ma).
    rate: Optional[Decimal]
    counterparty_id: Optional[int] = None
    #: D2 — pozycja płacowa albo rachunek z wypłatami dla zespołu.
    payroll: bool = False

    @property
    def valued(self) -> Optional[int]:
        if self.rate is None:
            return None
        return int(
            (Decimal(self.amount_cur) * self.rate).quantize(
                Decimal("1"), rounding=ROUND_HALF_UP
            )
        )

    @property
    def diff(self) -> Optional[int]:
        """Korekta salda konta: + = Wn konto (dodatnia różnica), − = Ma konto."""

        valued = self.valued
        return None if valued is None else valued - self.book


@dataclass(frozen=True)
class Skipped:
    """Rachunek walutowy poza wyceną: powód i wycena ręczna (PK)."""

    account: str
    currency: str
    reason: str
    payroll: bool = False


@dataclass(frozen=True)
class Group:
    """PK wyceny: zwykła (``RRRR-MM``) albo płacowa (``RRRR-MM-payroll``, D2)."""

    key: str
    payroll: bool


def month_end(year: int, month: int) -> date:
    return date(year, month, calendar.monthrange(year, month)[1])


def key(year: int, month: int) -> str:
    return f"{year}-{month:02d}"


def groups(own: str, viewer: Viewer) -> list[Group]:
    """PK, które ta osoba widzi: płacowa tylko z Płacami."""

    found = [Group(own, False)]
    if viewer.payroll:
        found.append(Group(own + PAYROLL_SUFFIX, True))
    return found


def _rate(rates: dict[str, tuple[Decimal, date]], currency: str) -> Optional[Decimal]:
    found = rates.get(currency)
    return found[0] if found else None


def settlement_positions(
    items: list[settlements.Item], rates: dict[str, tuple[Decimal, date]]
) -> list[Position]:
    """Otwarte pozycje walutowe netto per konto i waluta — płacowe (D2) osobno."""

    cur: dict[tuple[str, str, bool], int] = defaultdict(int)
    book: dict[tuple[str, str, bool], int] = defaultdict(int)
    party: dict[tuple[str, str, bool], Optional[int]] = {}
    for item in items:
        if not item.is_currency:
            continue
        left_cur = item.remaining_cur or 0
        if item.remaining <= 0 or left_cur <= 0:
            continue
        sign = 1 if item.direction == "debit" else -1
        slot = (item.account, item.currency, item.sensitivity is not None)
        cur[slot] += sign * left_cur
        book[slot] += sign * item.remaining
        party.setdefault(slot, item.counterparty_id)
    out = []
    for slot in sorted(cur):
        account, currency, payroll = slot
        out.append(
            Position(
                account=account,
                kind="settlement",
                currency=currency,
                amount_cur=cur[slot],
                book=book[slot],
                rate=_rate(rates, currency),
                counterparty_id=party.get(slot),
                payroll=payroll,
            )
        )
    return out


def gain_of(positions: list[Position]) -> int:
    return sum(item.diff for item in positions if item.diff and item.diff > 0)


def loss_of(positions: list[Position]) -> int:
    return -sum(item.diff for item in positions if item.diff and item.diff < 0)


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

    return [
        LineIn(
            _FLIP[line.side],
            line.account,
            line.amount,
            line.description,
            counterparty_id=line.counterparty_id,
        )
        for line in lines
    ]


def mirrors(valued: list[tuple], reversal: list[tuple]) -> bool:
    """Czy odwrócenie (strona, konto, kwota, kontrahent) odwraca dokładnie tę wycenę."""

    flipped = [(_FLIP[side], *rest) for side, *rest in valued]
    return sorted(flipped) == sorted(reversal)


async def nbp_rates(
    db: AsyncSession, currencies: set[str], day: date
) -> tuple[dict[str, tuple[Decimal, date]], list[str]]:
    """Średni kurs NBP z dnia ``day`` — dokładnie z tego dnia."""

    if not currencies:
        return {}, []
    rows = await db.execute(
        select(FxRate.currency, FxRate.rate_to_pln).where(
            FxRate.currency.in_(sorted(currencies)),
            FxRate.source == "NBP",
            FxRate.effective_date == day,
        )
    )
    found = {currency: (Decimal(rate), day) for currency, rate in rows.all()}
    return found, sorted(currencies - set(found))


_SIGN = case((LedgerLine.side == "debit", 1), else_=-1)


async def bank_positions(
    db: AsyncSession,
    bank_settings: BankSettings,
    day: date,
    rates: dict[str, tuple[Decimal, date]],
    *,
    own_keys: tuple[str, ...],
) -> tuple[list[Position], list[Skipped]]:
    """Salda rachunków walutowych w roku obrotowym ``day`` (BO + obroty do ``day``)."""

    # Jedna pozycja na konto księgi — dwa rachunki (NRB) na jednym koncie
    # liczyłyby korektę podwójnie (drugi przegląd K4c-2).
    accounts = []
    seen: set[str] = set()
    for item in bank_settings.accounts:
        if item.currency != "PLN" and item.account not in seen:
            seen.add(item.account)
            accounts.append(item)
    if not accounts:
        return [], []
    years = dict(
        (
            await db.execute(
                select(LedgerYear.year, LedgerYear.id).where(
                    LedgerYear.year.in_((day.year - 1, day.year))
                )
            )
        ).all()
    )
    year_id = years.get(day.year)
    if year_id is None:
        return [], []
    # Wszystkie wersje wyceny tego miesiąca (też te ze stornem) i ich storna —
    # przeliczenie liczy saldo sprzed wyceny (przegląd K4c-2: storno z datą tego
    # miesiąca zostawało w saldzie i nowa wycena dodawała różnicę drugi raz).
    own = select(LedgerDocument.id).where(
        LedgerDocument.source_type == SOURCE, LedgerDocument.source_id.in_(own_keys)
    )
    corrections = select(LedgerDocument.id).where(
        LedgerDocument.source_type.in_((SOURCE, REVERSAL_SOURCE))
    )
    # ``reverses_id IS NOT NULL`` wprost: „NULL IN (…)” to NULL, a „NOT NULL”
    # wyłączało sprawdzenie zapisów bez waluty, gdy w księdze była już
    # jakakolwiek PK wyceny (drugi przegląd K4c-2).
    correction = or_(
        LedgerDocument.id.in_(corrections),
        and_(
            LedgerDocument.reverses_id.is_not(None),
            LedgerDocument.reverses_id.in_(corrections),
        ),
    )
    positions: list[Position] = []
    skipped: list[Skipped] = []
    for company in accounts:
        scope = (
            LedgerLine.account == company.account,
            LedgerDocument.status == "approved",
            LedgerDocument.year_id == year_id,
            LedgerDocument.op_date <= day,
            LedgerDocument.id.not_in(own),
            or_(
                LedgerDocument.reverses_id.is_(None),
                LedgerDocument.reverses_id.not_in(own),
            ),
        )
        # Zapis bez kwoty w walucie rachunku (korekty wyceny są w PLN z zasady).
        bare = or_(
            LedgerLine.currency.is_distinct_from(company.currency),
            LedgerLine.amount_cur.is_(None),
        )
        row = (
            await db.execute(
                select(
                    func.coalesce(func.sum(_SIGN * LedgerLine.amount), 0),
                    func.coalesce(
                        func.sum(case((bare, 0), else_=_SIGN * LedgerLine.amount_cur)),
                        0,
                    ),
                    func.coalesce(
                        func.sum(
                            case(
                                (bare & ~correction, _SIGN * LedgerLine.amount), else_=0
                            )
                        ),
                        0,
                    ),
                    func.coalesce(
                        func.bool_or(LedgerDocument.sensitivity.is_not(None)), False
                    ),
                    func.count(case((LedgerDocument.doc_type == "BO", 1))),
                )
                .join(LedgerDocument, LedgerDocument.id == LedgerLine.document_id)
                .where(*scope)
            )
        ).one()
        book, amount_cur, bare_pln = int(row[0]), int(row[1]), int(row[2])
        payroll, opened = bool(row[3]), int(row[4]) > 0
        if bare_pln:
            numbers = (
                await db.scalars(
                    select(LedgerDocument.number)
                    .join(LedgerLine, LedgerLine.document_id == LedgerDocument.id)
                    .where(*scope, bare, ~correction)
                    .distinct()
                    .order_by(LedgerDocument.number)
                    .limit(SKIPPED_DOCS + 1)
                )
            ).all()
            listed = ", ".join(numbers[:SKIPPED_DOCS]) + (
                " …" if len(numbers) > SKIPPED_DOCS else ""
            )
            skipped.append(
                Skipped(
                    company.account,
                    company.currency,
                    f"zapisy bez kwoty w {company.currency} ({listed}) — wyceń ten "
                    "rachunek ręcznie (PK)",
                    payroll,
                )
            )
            continue
        previous_id = years.get(day.year - 1)
        if (
            previous_id is not None
            and not opened
            and await _carried(db, company.account, previous_id)
        ):
            skipped.append(
                Skipped(
                    company.account,
                    company.currency,
                    f"saldo z {day.year - 1} nie jest przeniesione (brak BO "
                    f"{day.year}) — wyceń ręcznie albo najpierw zaksięguj BO",
                    payroll,
                )
            )
            continue
        if not book and not amount_cur:
            continue
        positions.append(
            Position(
                account=company.account,
                kind="bank",
                currency=company.currency,
                amount_cur=amount_cur,
                book=book,
                rate=_rate(rates, company.currency),
                payroll=payroll,
            )
        )
    return positions, skipped


async def _carried(db: AsyncSession, account: str, year_id: int) -> bool:
    """Saldo konta na koniec roku ``year_id`` (PLN albo waluta) różne od zera."""

    row = (
        await db.execute(
            select(
                func.coalesce(func.sum(_SIGN * LedgerLine.amount), 0),
                func.coalesce(
                    func.sum(_SIGN * func.coalesce(LedgerLine.amount_cur, 0)), 0
                ),
            )
            .join(LedgerDocument, LedgerDocument.id == LedgerLine.document_id)
            .where(
                LedgerLine.account == account,
                LedgerDocument.status == "approved",
                LedgerDocument.year_id == year_id,
            )
        )
    ).one()
    return bool(row[0]) or bool(row[1])


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


async def _booked_lines(db: AsyncSession, doc_id: int) -> list[LineIn]:
    rows = await db.execute(
        select(
            LedgerLine.side,
            LedgerLine.account,
            LedgerLine.amount,
            LedgerLine.description,
            LedgerLine.counterparty_id,
        )
        .where(LedgerLine.document_id == doc_id)
        .order_by(LedgerLine.line_no)
    )
    return [
        LineIn(side, account, int(amount), description, counterparty_id=party)
        for side, account, amount, description, party in rows.all()
    ]


async def _earlier_open(db: AsyncSession, own: str, *, payroll: bool) -> Optional[str]:
    """Wcześniejsza zatwierdzona wycena bez odwrócenia, które ją odwraca — albo
    odwrócenie bez wyceny. Każdy wcześniejszy miesiąc, nie tylko poprzedni:
    wycena maja przy wiszącym marcu dodałaby korektę marca drugi raz."""

    docs = (
        await db.scalars(
            select(LedgerDocument).where(
                LedgerDocument.source_type.in_((SOURCE, REVERSAL_SOURCE)),
                LedgerDocument.status == "approved",
                LedgerDocument.reversed_by_id.is_(None),
            )
        )
    ).all()
    pairs: dict[str, dict[str, LedgerDocument]] = defaultdict(dict)
    for doc in docs:
        source_id = doc.source_id or ""
        if source_id[:7] >= own[:7]:
            continue
        if source_id.endswith(PAYROLL_SUFFIX) and not payroll:
            continue
        pairs[source_id][doc.source_type or ""] = doc
    if not pairs:
        return None
    ids = [doc.id for pair in pairs.values() for doc in pair.values()]
    lines: dict[int, list[tuple]] = defaultdict(list)
    rows = await db.execute(
        select(
            LedgerLine.document_id,
            LedgerLine.side,
            LedgerLine.account,
            LedgerLine.amount,
            LedgerLine.counterparty_id,
        ).where(LedgerLine.document_id.in_(ids))
    )
    for doc_id, side, account, amount, party in rows.all():
        lines[doc_id].append((side, account, int(amount), party))
    for source_id in sorted(pairs):
        valued = pairs[source_id].get(SOURCE)
        reversal = pairs[source_id].get(REVERSAL_SOURCE)
        if valued is None and reversal is not None:
            return ORPHAN.format(
                number=reversal.number, day=reversal.op_date.strftime("%d.%m.%Y")
            )
        if valued is None:
            continue
        day = valued.op_date.strftime("%d.%m.%Y")
        if reversal is None:
            return WAITING.format(day=day, number=valued.number)
        if not mirrors(lines[valued.id], lines[reversal.id]):
            return STALE.format(reversal=reversal.number, number=valued.number, day=day)
    return None


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
    #: Dzień kursu NBP: ostatni dzień roboczy miesiąca.
    rate_day: date
    rates: dict[str, tuple[Decimal, date]]
    #: Pozycje i pominięte rachunki widoczne dla tej osoby (D2).
    positions: list[Position]
    skipped: list[Skipped]
    #: Część płacowa jest, ale ta osoba jej nie widzi.
    hidden: bool
    #: Wcześniejsza wycena bez zaksięgowanego odwrócenia — nowa dodałaby
    #: różnicę drugi raz do salda konta.
    previous_open: Optional[str] = None

    @property
    def missing(self) -> list[str]:
        return sorted({item.currency for item in self.positions if item.rate is None})

    def of(self, group: Group) -> list[Position]:
        return [item for item in self.positions if item.payroll == group.payroll]


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
    rate_on = posting.rate_day(day + timedelta(days=1))
    # Płacowe liczą się zawsze, żeby rachunek z wypłatą dla zespołu poszedł
    # w całości do PK płacowej; osoba bez Płac dostaje tylko resztę (D2).
    everything = replace(viewer, payroll=True)
    parents = await settlements.load_parents(db)
    items = await settlements.load_items(db, everything, parents=parents, as_of=day)
    currencies = {item.currency for item in items if item.is_currency}
    currencies |= {
        account.currency
        for account in bank_settings.accounts
        if account.currency != "PLN"
    }
    rates, _ = await nbp_rates(db, currencies, rate_on)
    bank, skipped = await bank_positions(
        db, bank_settings, day, rates, own_keys=(own, own + PAYROLL_SUFFIX)
    )
    positions = settlement_positions(items, rates) + bank
    shown = [item for item in positions if viewer.payroll or not item.payroll]
    shown_skipped = [item for item in skipped if viewer.payroll or not item.payroll]
    used = {item.currency for item in shown}
    return Valuation(
        day=day,
        own=own,
        rate_day=rate_on,
        rates={currency: rate for currency, rate in rates.items() if currency in used},
        positions=shown,
        skipped=shown_skipped,
        hidden=len(shown) < len(positions) or len(shown_skipped) < len(skipped),
        previous_open=await _earlier_open(db, own, payroll=viewer.payroll),
    )


def _spec(
    found: Valuation, group: Group, bank_settings: BankSettings
) -> Optional[DocumentSpec]:
    text_ = f"Wycena walut na {found.day:%d.%m.%Y}"
    lines = valuation_lines(
        found.of(group),
        gain=bank_settings.fx_gain_account,
        loss=bank_settings.fx_loss_account,
        text_=text_,
    )
    if not lines:
        return None
    return DocumentSpec(
        doc_type="PK",
        op_date=found.day,
        doc_date=found.day,
        lines=lines,
        description=text_ + (" — Płace" if group.payroll else ""),
        source_type=SOURCE,
        source_id=group.key,
        sensitivity="payroll" if group.payroll else None,
        meta={"valuation": found.own},
    )


def _changed(
    found: Valuation,
    group: Group,
    doc: Optional[LedgerDocument],
    bank_settings: BankSettings,
) -> bool:
    """Zatwierdzona wycena różni się od dzisiejszego przeliczenia (późny dokument,
    storno, inny kurs) — trzeba jej storna i ponownej wyceny."""

    if doc is None or doc.status != "approved" or found.missing:
        return False
    spec = _spec(found, group, bank_settings)
    return spec is None or (doc.meta or {}).get("fingerprint") != sources.fingerprint(
        spec
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
    listed = []
    for group in groups(found.own, viewer):
        positions = found.of(group)
        valued = await _document(db, SOURCE, group.key)
        reversal = await _document(db, REVERSAL_SOURCE, group.key)
        if not positions and valued is None and reversal is None:
            continue
        listed.append(
            {
                "key": group.key,
                "payroll": group.payroll,
                "gain": gain_of(positions),
                "loss": loss_of(positions),
                # Jest co księgować (bez kursu nie wiadomo — wtedy też tak).
                "to_book": any(item.diff != 0 for item in positions),
                "valuation": _doc_payload(valued),
                "reversal": _doc_payload(reversal),
                "changed": _changed(found, group, valued, bank_settings),
            }
        )
    return {
        "year": year,
        "month": month,
        "day": found.day.isoformat(),
        "rate_day": found.rate_day.isoformat(),
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
                "payroll": item.payroll,
            }
            for item in found.positions
        ],
        "skipped": [
            {
                "account": item.account,
                "name": names.get(item.account, ""),
                "currency": item.currency,
                "reason": item.reason,
                "payroll": item.payroll,
            }
            for item in found.skipped
        ],
        "gain": gain_of(found.positions),
        "loss": loss_of(found.positions),
        "groups": listed,
        "payroll_hidden": found.hidden,
        "blocker": _blocker(found, bank_settings),
        "can_post": viewer.approver,
    }


async def _account_names(
    db: AsyncSession, bank_settings: BankSettings, positions: list[Position]
) -> dict[str, str]:
    """Kontrahent z pozycji albo nazwa rachunku z Ustawień (pozycje są już po D2)."""

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
    missing = found.missing
    if missing:
        currencies, rate_day = ", ".join(missing), f"{found.rate_day:%d.%m.%Y}"
        if found.rate_day >= business_today():
            return (
                f"Kurs NBP {currencies} z dnia {rate_day} jeszcze nie jest pobrany — "
                f"wycena na {found.day:%d.%m.%Y} po jego ogłoszeniu."
            )
        return (
            f"Brak kursu NBP {currencies} z dnia {rate_day} (kurs na "
            f"{found.day:%d.%m.%Y}) — pobierz kursy (Finanse → Kursy walut)."
        )
    if gain_of(found.positions) and not bank_settings.fx_gain_account:
        return "Ustaw konto dodatnich różnic kursowych w Ustawieniach (Bank)."
    if loss_of(found.positions) and not bank_settings.fx_loss_account:
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

    def refused() -> LedgerError:
        return LedgerError(
            APPROVED.format(
                label=label,
                day=existing.op_date.strftime("%d.%m.%Y"),
                number=existing.number,
            ),
            status=409,
        )

    if spec is None:
        if existing is None:
            return "none", None
        if existing.status != "draft":
            raise refused()
        await documents.delete_draft(db, existing.id, viewer=viewer)
        return "removed", None
    mark = sources.fingerprint(spec)
    spec.meta["fingerprint"] = mark
    if existing is not None:
        if (existing.meta or {}).get("fingerprint") == mark:
            return "unchanged", existing
        if existing.status != "draft":
            raise refused()
        await documents.delete_draft(db, existing.id, viewer=viewer)
        created = await documents.create_draft(
            db, spec, actor_id=viewer.user_id, plan=plan
        )
        return "rebuilt", created
    created = await documents.create_draft(db, spec, actor_id=viewer.user_id, plan=plan)
    return "created", created


async def _write_reversal(
    db: AsyncSession,
    found: Valuation,
    group: Group,
    booked: list[LineIn],
    existing: Optional[LedgerDocument],
    *,
    viewer: Viewer,
    plan: dict[str, Any],
) -> tuple[str, Optional[LedgerDocument], Optional[str]]:
    """Odwrócenie z zaksięgowanej (albo właśnie zapisanej) PK wyceny."""

    label = "Odwrócenie wyceny"
    if not booked:
        outcome, doc = await _write(
            db, None, existing, viewer=viewer, plan=plan, label=label
        )
        return outcome, doc, None
    next_day = found.day + timedelta(days=1)
    waiting = await _next_period_open(db, next_day)
    if waiting is not None:
        if existing is not None:
            # Odwrócenie, które już jest, zostaje — następny okres zamknięto po nim.
            return "unchanged", existing, None
        return "waiting", None, waiting
    spec = DocumentSpec(
        doc_type="PK",
        op_date=next_day,
        doc_date=next_day,
        lines=reversed_lines(booked),
        description=f"Odwrócenie wyceny walut z {found.day:%d.%m.%Y}"
        + (" — Płace" if group.payroll else ""),
        source_type=REVERSAL_SOURCE,
        source_id=group.key,
        sensitivity="payroll" if group.payroll else None,
        meta={"valuation": found.own},
    )
    outcome, doc = await _write(
        db, spec, existing, viewer=viewer, plan=plan, label=label
    )
    return outcome, doc, None


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
    plan = await documents.load_plan(db)
    results = []
    for group in groups(found.own, viewer):
        existing = await _document(db, SOURCE, group.key)
        existing_reversal = await _document(db, REVERSAL_SOURCE, group.key)
        if not found.of(group) and existing is None and existing_reversal is None:
            continue
        changed = False
        if existing is not None and existing.status == "approved":
            # Zatwierdzonej się nie podmienia: odwrócenie idzie z zaksięgowanej PK
            # (inaczej czekające odwrócenie nie powstałoby po żadnej zmianie —
            # przegląd K4c-2), a różnica od przeliczenia to flaga dla księgowej.
            outcome, doc = "approved", existing
            changed = _changed(found, group, existing, bank_settings)
            booked = await _booked_lines(db, existing.id)
        else:
            spec = _spec(found, group, bank_settings)
            outcome, doc = await _write(
                db, spec, existing, viewer=viewer, plan=plan, label="Wycena"
            )
            booked = list(spec.lines) if spec is not None else []
        reversal_outcome, reversal, waiting = await _write_reversal(
            db, found, group, booked, existing_reversal, viewer=viewer, plan=plan
        )
        results.append(
            {
                "key": group.key,
                "payroll": group.payroll,
                "valuation": {"outcome": outcome, **(_doc_payload(doc) or {})},
                "reversal": {
                    "outcome": reversal_outcome,
                    **(_doc_payload(reversal) or {}),
                },
                "reversal_waiting": waiting,
                "changed": changed,
            }
        )
    return {
        "groups": results,
        "gain": gain_of(found.positions),
        "loss": loss_of(found.positions),
    }
