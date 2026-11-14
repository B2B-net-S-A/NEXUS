"""Rozrachunki z rozliczaniem pozycji (K4b, 0706).

Pozycja rozrachunkowa to zapis zatwierdzonego dokumentu na koncie kontrahenta:
analityce konta ze słownikiem „kontrahent” w planie kont (``200-1234``,
``201-2-15``). Stroną pozycji jest strona zapisu; kwota ujemna (storno
czerwone w PK) idzie na stronę przeciwną. Rozliczenie (``ledger_settlements``)
łączy pozycję Wn z pozycją Ma tego samego konta na kwotę; pozostało = kwota
pozycji − jej rozliczenia.

* **Żywe dokumenty**: zatwierdzone, bez storna i niebędące stornem. Storno
  zeruje dokument razem z nim, więc od daty storna oba wypadają
  z rozrachunków, a ich rozliczenia przestają się liczyć — wpłata wraca do
  rozliczenia z nową fakturą. Na dzień sprzed storna dokument i jego
  rozliczenia zostają (jak w obrotach i saldach).
* **Bilans otwarcia** daje pozycje tylko w pierwszym roku księgi NEXUSA (BO
  z Symfonii). BO kolejnego roku powstaje z sald poprzedniego, którego pozycje
  przechodzą same — inaczej faktura z grudnia byłaby otwarta dwa razy.
* **Na dzień**: pozycje dokumentów z datą operacji do tego dnia i rozliczenia
  z datą do tego dnia (data rozliczenia = późniejsza z dat obu dokumentów).
* **Termin**: faktura sprzedaży (KSeF) i faktura kosztowa (kolejka kosztów)
  mają termin płatności; pozostałe pozycje są „bez terminu”.
* **Automat** (podgląd w zestawieniu, zapis przyciskiem): operacja wyciągu
  dopasowana w E3/E8 z fakturą, korekta faktury sprzedaży z fakturą pierwotną,
  a na koniec pozycje konta, które razem dają zero (od najstarszych).
* **D2**: dokumenty płacowe widzi i rozlicza tylko osoba z Płacami albo
  administrator. Rozliczenie łączy pozycje o tej samej wrażliwości, więc
  osobie bez Płac nic się nie „rozlicza” dokumentem, którego nie widzi.
* **Waluty (K4c-1)**: pozycja walutowa ma kwotę w walucie (``amount_cur``).
  Para w tej samej walucie obcej rozlicza się w walucie: każda strona zdejmuje
  swój udział PLN (PLN pozostałe × rozliczana część waluty pozostałej), więc
  pozycje zamykają się w walucie i w PLN naraz. Różnicę udziałów (różnicę
  kursową zrealizowaną) księguje PK w buforze (źródło ``fx_difference``):
  nadwyżka po Wn = ujemna (Wn koszty finansowe, Ma konto kontrahenta), po Ma =
  dodatnia (Wn konto kontrahenta, Ma przychody finansowe); jej pozycje nie są
  rozrachunkami. Faktura w walucie zapłacona w PLN rozlicza się w PLN (jak
  w K4b), a z pozycji walutowej schodzi proporcjonalna część waluty; dwóch
  różnych walut obcych się nie łączy.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import ROUND_HALF_UP, Decimal
from typing import Any, Iterable, Optional

from sqlalchemy import String, and_, case, cast, func, or_, select, union_all
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.models.client_sales_invoice import ClientSalesInvoice
from app.models.finance_ledger import FinanceCostEntry
from app.models.ledger import (
    LedgerBankLine,
    LedgerDocument,
    LedgerLine,
    LedgerPeriod,
    LedgerSettlement,
    LedgerYear,
)
from app.services.finance_ledger.costs import LedgerError
from app.services.finance_ledger.posting import money_pl
from app.services.ledger import bank, documents, sources
from app.services.ledger.documents import DocumentSpec, Viewer
from app.services.ledger.engine import LineIn
from app.services.ledger.settings import BankSettings

SALES_SOURCE = sources.SOURCE_TYPES[sources.SALES]
COST_SOURCE = sources.SOURCE_TYPES[sources.COSTS]
#: Rodzaje operacji wyciągu z fakturą dopasowaną w E3 (koszty) i E8 (sprzedaż).
BANK_TARGETS: dict[str, str] = {
    "cost_invoice": COST_SOURCE,
    "sales_invoice": SALES_SOURCE,
}
#: Przedziały wiekowania: klucz, etykieta, górna granica dni po terminie.
AGING: tuple[tuple[str, str, Optional[int]], ...] = (
    ("current", "w terminie", 0),
    ("d30", "1–30 dni", 30),
    ("d60", "31–60 dni", 60),
    ("d90", "61–90 dni", 90),
    ("d180", "91–180 dni", 180),
    ("d365", "181–365 dni", 365),
    ("over", "ponad rok", None),
)
NO_DUE = ("none", "bez terminu")
SELECT_MAX = 200
LOCK_KEY = "ledger-settlements"

NO_ITEMS = (
    "Pozycji nie ma w rozrachunkach — rozlicza się zapisy zatwierdzonych "
    "dokumentów na kontach kontrahentów."
)
NO_SETTLEMENT = "Tego rozliczenia nie ma albo zostało już cofnięte."
APPROVERS_ONLY = "Pozycje rozlicza osoba z listy „Księgowi” albo administrator."
FX_SOURCE = "fx_difference"
MIXED_CURRENCIES = (
    "Pozycje są w dwóch różnych walutach obcych — rozlicza się walutę z tą samą "
    "walutą albo z PLN."
)
FX_ACCOUNT_MISSING = (
    "Rozliczenie w walucie daje różnicę kursową {amount} zł — ustaw konto "
    "{kind} różnic kursowych w Ustawieniach (Bank)."
)
FX_APPROVED = (
    "Różnica kursowa tego rozliczenia jest zaksięgowana ({number}) — najpierw "
    "storno tego dokumentu."
)


@dataclass
class Item:
    """Pozycja rozrachunkowa: zapis na koncie kontrahenta z tym, co zostało."""

    line_id: int
    document_id: int
    line_no: int
    account: str
    direction: str
    value: int
    used: int
    doc_type: str
    number: str
    op_date: date
    description: str
    due_on: Optional[date]
    currency: str
    amount_cur: Optional[int]
    counterparty_id: Optional[int]
    sensitivity: Optional[str]
    source_type: Optional[str]
    source_id: Optional[str]
    used_cur: int = 0

    @property
    def remaining(self) -> int:
        return self.value - self.used

    @property
    def is_currency(self) -> bool:
        return self.currency != "PLN" and bool(self.amount_cur)

    @property
    def remaining_cur(self) -> Optional[int]:
        return self.amount_cur - self.used_cur if self.is_currency else None


@dataclass(frozen=True)
class Proposal:
    """Rozliczenie pary: ``amount`` = udział PLN pozycji Wn, ``credit_amount`` —
    pozycji Ma (tylko w walucie; bez niego Ma zdejmuje ``amount``)."""

    debit: Item
    credit: Item
    amount: int
    method: str
    amount_cur: Optional[int] = None
    credit_amount: Optional[int] = None

    @property
    def credit_share(self) -> int:
        return self.credit_amount if self.credit_amount is not None else self.amount

    @property
    def fx(self) -> int:
        """Różnica kursowa w PLN: dodatnia = Wn zdjęła więcej (ujemna różnica)."""

        return self.amount - self.credit_share

    @property
    def settled_on(self) -> date:
        return max(self.debit.op_date, self.credit.op_date)

    @property
    def currency(self) -> Optional[str]:
        """Waluta rozliczenia (pozycji walutowej pary) albo ``None`` — same PLN."""

        if not self.amount_cur:
            return None
        return self.debit.currency if self.debit.is_currency else self.credit.currency


# ── Reguły bez bazy ─────────────────────────────────────────────────────────


def settlement_parents(plan: dict[str, Any]) -> tuple[str, ...]:
    """Konta ze słownikiem „kontrahent” — ich analityka to rozrachunki."""

    return tuple(
        sorted(
            number
            for number, account in plan.items()
            if account.dictionary == "counterparty" and account.active
        )
    )


def is_settlement_account(account: str, parents: Iterable[str]) -> bool:
    return any(account.startswith(f"{parent}-") for parent in parents)


def aging_key(due_on: Optional[date], as_of: date) -> str:
    if due_on is None:
        return NO_DUE[0]
    days = (as_of - due_on).days
    for key, _, limit in AGING:
        if limit is None or days <= limit:
            return key
    return AGING[-1][0]  # pragma: no cover — ostatni przedział nie ma granicy


def overdue_days(due_on: Optional[date], as_of: date) -> int:
    if due_on is None:
        return 0
    return max(0, (as_of - due_on).days)


def _order(item: Item) -> tuple[date, int, int]:
    return (item.op_date, item.document_id, item.line_no)


def share(left_pln: int, left_cur: int, part: int) -> int:
    """Udział PLN części waluty: proporcja tego, co zostało (cała reszta = całe PLN)."""

    if part >= left_cur:
        return left_pln
    return int(
        (Decimal(left_pln) * part / left_cur).quantize(
            Decimal("1"), rounding=ROUND_HALF_UP
        )
    )


@dataclass
class Left:
    """Ile zostało do rozliczenia: PLN i — przy pozycjach walutowych — waluta."""

    pln: dict[int, int]
    cur: dict[int, int]

    @classmethod
    def of(cls, items: Iterable[Item]) -> "Left":
        listed = list(items)
        return cls(
            {item.line_id: item.remaining for item in listed},
            {
                item.line_id: item.remaining_cur or 0
                for item in listed
                if item.is_currency
            },
        )

    def open(self, item: Item) -> bool:
        if item.is_currency:
            return self.cur[item.line_id] > 0
        return self.pln[item.line_id] > 0


def pairable(debit: Item, credit: Item) -> bool:
    """Para do rozliczenia: nie dwie różne waluty obce (EUR z USD)."""

    return not (
        debit.is_currency and credit.is_currency and debit.currency != credit.currency
    )


def terms(
    debit: Item,
    credit: Item,
    left: Left,
    *,
    method: str,
    amount: Optional[int] = None,
) -> Optional[Proposal]:
    """Rozliczenie pary na tym, co zostało; ``amount`` — kwota w walucie pary.

    * obie w tej samej walucie obcej — kwota w walucie, każda strona zdejmuje
      swój udział PLN, różnica udziałów to różnica kursowa;
    * jedna w walucie, druga w PLN (faktura w EUR zapłacona w złotych) — kwota
      w PLN jak w K4b, a pozycja walutowa traci proporcjonalną część waluty;
    * obie w PLN — kwota w PLN.

    ``None`` = nie da się rozliczyć.
    """

    if not pairable(debit, credit):
        return None
    d_id, c_id = debit.line_id, credit.line_id
    if debit.is_currency and credit.is_currency:
        limit = min(left.cur[d_id], left.cur[c_id])
        part = limit if amount is None else amount
        if part <= 0 or part > limit:
            return None
        d_share = share(left.pln[d_id], left.cur[d_id], part)
        c_share = share(left.pln[c_id], left.cur[c_id], part)
        if d_share <= 0 or c_share <= 0:
            return None
        return Proposal(
            debit, credit, d_share, method, amount_cur=part, credit_amount=c_share
        )
    limit = min(left.pln[d_id], left.pln[c_id])
    value = limit if amount is None else amount
    if value <= 0 or value > limit:
        return None
    foreign = debit if debit.is_currency else credit if credit.is_currency else None
    if foreign is None:
        return Proposal(debit, credit, value, method)
    part = share(left.cur[foreign.line_id], left.pln[foreign.line_id], value)
    if part <= 0:
        return None
    return Proposal(debit, credit, value, method, amount_cur=part)


def take(left: Left, proposal: Proposal) -> None:
    """Zdejmuje rozliczenie z tego, co zostało (w miejscu)."""

    left.pln[proposal.debit.line_id] -= proposal.amount
    left.pln[proposal.credit.line_id] -= proposal.credit_share
    if proposal.amount_cur:
        for item in (proposal.debit, proposal.credit):
            if item.is_currency:
                left.cur[item.line_id] -= proposal.amount_cur


def fifo(
    debits: list[Item], credits: list[Item], left: Left, *, method: str
) -> list[Proposal]:
    """Pary od najstarszych pozycji jednej waluty; ``left`` zmieniane w miejscu."""

    proposals: list[Proposal] = []
    queue_d = sorted((item for item in debits if left.open(item)), key=_order)
    queue_c = sorted((item for item in credits if left.open(item)), key=_order)
    i = j = 0
    while i < len(queue_d) and j < len(queue_c):
        proposal = terms(queue_d[i], queue_c[j], left, method=method)
        if proposal is None:
            break
        take(left, proposal)
        proposals.append(proposal)
        if not left.open(queue_d[i]):
            i += 1
        if not left.open(queue_c[j]):
            j += 1
    return proposals


@dataclass(frozen=True)
class FxContext:
    """Czy różnicę kursową da się zaksięgować: konta z Ustawień i otwarte okresy."""

    gain_account: str = ""
    loss_account: str = ""
    open_months: frozenset[tuple[int, int]] = frozenset()

    def blocker(self, proposal: Proposal) -> Optional[str]:
        fx = proposal.fx
        if not fx:
            return None
        if fx > 0 and not self.loss_account:
            return FX_ACCOUNT_MISSING.format(amount=money_pl(fx), kind="ujemnych")
        if fx < 0 and not self.gain_account:
            return FX_ACCOUNT_MISSING.format(amount=money_pl(-fx), kind="dodatnich")
        day = proposal.settled_on
        if (day.year, day.month) not in self.open_months:
            return (
                f"Różnica kursowa ({money_pl(abs(fx))} zł) wpada w zamknięty okres "
                f"{day.month:02d}.{day.year} — otwórz go albo zaksięguj ją ręcznie."
            )
        return None


async def fx_context(db: AsyncSession, bank_settings: BankSettings) -> FxContext:
    rows = await db.execute(
        select(LedgerYear.year, LedgerPeriod.month)
        .join(LedgerPeriod, LedgerPeriod.year_id == LedgerYear.id)
        .where(LedgerYear.status == "open", LedgerPeriod.status == "open")
    )
    return FxContext(
        gain_account=bank_settings.fx_gain_account,
        loss_account=bank_settings.fx_loss_account,
        open_months=frozenset((year, month) for year, month in rows.all()),
    )


# ── Odczyt pozycji ──────────────────────────────────────────────────────────


_DIRECTION = case(
    (and_(LedgerLine.side == "debit", LedgerLine.amount > 0), "debit"),
    (and_(LedgerLine.side == "credit", LedgerLine.amount < 0), "debit"),
    else_="credit",
)


async def _bo_years(db: AsyncSession) -> list[int]:
    """Lata, których BO tworzy pozycje: bez poprzedniego roku w księdze NEXUSA."""

    rows = (await db.execute(select(LedgerYear.id, LedgerYear.year))).all()
    known = {year for _, year in rows}
    return [year_id for year_id, year in rows if year - 1 not in known]


def _live(doc: Any, bo_years: list[int], as_of: Optional[date]) -> list[Any]:
    """Dokument żywy na dzień: zatwierdzony, nie storno, a jego storno (jeśli jest)
    ma datę po ``as_of``. Storno z 05.05 nie zmienia rozrachunków na 30.04 — tak
    jak w obrotach i saldach, gdzie liczy się w swoim okresie (przegląd K4b
    14.11.2026). Bez daty = stan dziś: odwrócony dokument wypada."""

    if as_of is None:
        not_reversed = doc.reversed_by_id.is_(None)
    else:
        storno = aliased(LedgerDocument)
        not_reversed = or_(
            doc.reversed_by_id.is_(None),
            select(storno.id)
            .where(storno.id == doc.reversed_by_id, storno.op_date > as_of)
            .exists(),
        )
    return [
        doc.status == "approved",
        not_reversed,
        doc.reverses_id.is_(None),
        or_(doc.doc_type != "BO", doc.year_id.in_(bo_years or [0])),
    ]


def _accounts_clause(parents: tuple[str, ...]) -> Any:
    return or_(
        *(
            LedgerLine.account.startswith(f"{parent}-", autoescape=True)
            for parent in parents
        )
    )


def _used(as_of: Optional[date], bo_years: list[int]) -> Any:
    """Rozliczone kwoty pozycji — tylko z żywą pozycją po drugiej stronie.

    Strona Wn zdejmuje ``amount``, strona Ma ``credit_amount`` (rozliczenie
    w walucie, K4c-1), a gdy go nie ma — też ``amount``.
    """

    other = aliased(LedgerLine)
    other_doc = aliased(LedgerDocument)

    def side(own: Any, theirs: Any, amount: Any) -> Any:
        query = (
            select(
                own.label("line_id"),
                amount.label("amount"),
                func.coalesce(LedgerSettlement.amount_cur, 0).label("amount_cur"),
            )
            .join(other, other.id == theirs)
            .join(other_doc, other_doc.id == other.document_id)
            .where(
                LedgerSettlement.removed_at.is_(None),
                *_live(other_doc, bo_years, as_of),
            )
        )
        if as_of is not None:
            query = query.where(LedgerSettlement.settled_on <= as_of)
        return query

    both = union_all(
        side(
            LedgerSettlement.debit_line_id,
            LedgerSettlement.credit_line_id,
            LedgerSettlement.amount,
        ),
        side(
            LedgerSettlement.credit_line_id,
            LedgerSettlement.debit_line_id,
            func.coalesce(LedgerSettlement.credit_amount, LedgerSettlement.amount),
        ),
    ).subquery()
    return (
        select(
            both.c.line_id,
            func.sum(both.c.amount).label("used"),
            func.sum(both.c.amount_cur).label("used_cur"),
        )
        .group_by(both.c.line_id)
        .subquery()
    )


async def load_items(
    db: AsyncSession,
    viewer: Viewer,
    *,
    parents: tuple[str, ...],
    as_of: Optional[date] = None,
    accounts: Optional[list[str]] = None,
    line_ids: Optional[Iterable[int]] = None,
    open_only: bool = True,
) -> list[Item]:
    if not parents:
        return []
    bo_years = await _bo_years(db)
    used = _used(as_of, bo_years)
    used_amount = func.coalesce(used.c.used, 0)
    value = func.abs(LedgerLine.amount)
    query = (
        select(
            LedgerLine.id,
            LedgerLine.document_id,
            LedgerLine.line_no,
            LedgerLine.account,
            _DIRECTION.label("direction"),
            value.label("value"),
            used_amount.label("used"),
            func.coalesce(used.c.used_cur, 0).label("used_cur"),
            LedgerLine.description,
            LedgerLine.currency,
            LedgerLine.amount_cur,
            LedgerLine.counterparty_id,
            LedgerDocument.doc_type,
            LedgerDocument.number,
            LedgerDocument.op_date,
            LedgerDocument.description.label("doc_description"),
            LedgerDocument.counterparty_id.label("doc_counterparty_id"),
            LedgerDocument.sensitivity,
            LedgerDocument.source_type,
            LedgerDocument.source_id,
            func.coalesce(ClientSalesInvoice.due_date, FinanceCostEntry.due_date).label(
                "due_on"
            ),
        )
        .join(LedgerDocument, LedgerDocument.id == LedgerLine.document_id)
        .outerjoin(used, used.c.line_id == LedgerLine.id)
        .outerjoin(
            ClientSalesInvoice,
            and_(
                LedgerDocument.source_type == SALES_SOURCE,
                LedgerDocument.source_id == cast(ClientSalesInvoice.id, String),
            ),
        )
        .outerjoin(
            FinanceCostEntry,
            and_(
                LedgerDocument.source_type == COST_SOURCE,
                LedgerDocument.source_id == cast(FinanceCostEntry.id, String),
            ),
        )
        .where(
            *_live(LedgerDocument, bo_years, as_of),
            _accounts_clause(parents),
            # Różnica kursowa zamyka różnicę udziałów PLN rozliczenia w walucie —
            # sama nie jest pozycją do rozliczenia.
            or_(
                LedgerDocument.source_type.is_(None),
                LedgerDocument.source_type != FX_SOURCE,
            ),
        )
        .order_by(
            LedgerLine.account,
            LedgerDocument.op_date,
            LedgerDocument.id,
            LedgerLine.line_no,
        )
    )
    if as_of is not None:
        query = query.where(LedgerDocument.op_date <= as_of)
    if not viewer.payroll:
        query = query.where(LedgerDocument.sensitivity.is_(None))
    if accounts is not None:
        query = query.where(LedgerLine.account.in_(accounts or [""]))
    if line_ids is not None:
        query = query.where(LedgerLine.id.in_(list(line_ids) or [0]))
    if open_only:
        query = query.where(value > used_amount)
    rows = (await db.execute(query)).all()
    return [
        Item(
            line_id=row.id,
            document_id=row.document_id,
            line_no=row.line_no,
            account=row.account,
            direction=row.direction,
            value=int(row.value),
            used=int(row.used or 0),
            doc_type=row.doc_type,
            number=row.number,
            op_date=row.op_date,
            description=row.description or row.doc_description or "",
            due_on=row.due_on,
            currency=row.currency,
            amount_cur=abs(row.amount_cur) if row.amount_cur is not None else None,
            counterparty_id=row.counterparty_id or row.doc_counterparty_id,
            sensitivity=row.sensitivity,
            source_type=row.source_type,
            source_id=row.source_id,
            used_cur=int(row.used_cur or 0),
        )
        for row in rows
    ]


async def load_parents(db: AsyncSession) -> tuple[str, ...]:
    """Konta ze słownikiem „kontrahent” z aktualnego planu kont."""

    return settlement_parents(await documents.load_plan(db))


# ── Automat ─────────────────────────────────────────────────────────────────


async def _bank_links(db: AsyncSession, items: list[Item]) -> dict[int, LedgerBankLine]:
    """Pozycja WB z kontem przeciwstawnym → operacja wyciągu (``meta.bank_lines``)."""

    wb = [
        item
        for item in items
        if item.doc_type == "WB" and item.source_type == bank.SOURCE_TYPE
    ]
    if not wb:
        return {}
    metas = dict(
        (
            await db.execute(
                select(LedgerDocument.id, LedgerDocument.meta).where(
                    LedgerDocument.id.in_({item.document_id for item in wb})
                )
            )
        ).all()
    )
    wanted: dict[int, int] = {}
    for item in wb:
        links = (metas.get(item.document_id) or {}).get("bank_lines") or {}
        bank_line_id = links.get(str(item.line_no))
        if isinstance(bank_line_id, int):
            wanted[item.line_id] = bank_line_id
    if not wanted:
        return {}
    lines = {
        line.id: line
        for line in await db.scalars(
            select(LedgerBankLine).where(LedgerBankLine.id.in_(set(wanted.values())))
        )
    }
    return {
        line_id: lines[bank_line_id]
        for line_id, bank_line_id in wanted.items()
        if bank_line_id in lines
    }


async def _corrections(db: AsyncSession, items: list[Item]) -> dict[str, str]:
    """Faktura korygująca (id źródła FVS) → faktura pierwotna (id źródła FVS)."""

    ids = {
        int(item.source_id)
        for item in items
        if item.source_type == SALES_SOURCE
        and item.direction == "credit"
        and (item.source_id or "").isdigit()
    }
    if not ids:
        return {}
    rows = await db.execute(
        select(ClientSalesInvoice.id, ClientSalesInvoice.corrects_invoice_id).where(
            ClientSalesInvoice.id.in_(ids),
            ClientSalesInvoice.invoice_kind == "correction",
            ClientSalesInvoice.corrects_invoice_id.is_not(None),
        )
    )
    return {str(own): str(original) for own, original in rows.all()}


@dataclass
class Proposals:
    """Rozliczenia automatu i pary, które czekają na różnicę kursową."""

    items: list[Proposal] = field(default_factory=list)
    fx_waiting: int = 0


async def propose(
    db: AsyncSession, items: list[Item], fx: FxContext = FxContext()
) -> Proposals:
    """Rozliczenia automatu na otwartych pozycjach (bez zapisu)."""

    left = Left.of(items)
    by_source: dict[tuple[str, str, str], list[Item]] = defaultdict(list)
    for item in items:
        if item.source_type and item.source_id:
            by_source[(item.source_type, item.source_id, item.account)].append(item)
    out = Proposals()

    def pair(first: Item, second: Item, method: str) -> None:
        debit, credit = (
            (first, second) if first.direction == "debit" else (second, first)
        )
        if debit.direction != "debit" or credit.direction != "credit":
            return
        if debit.account != credit.account or debit.sensitivity != credit.sensitivity:
            return
        proposal = terms(debit, credit, left, method=method)
        if proposal is None:
            return
        if fx.blocker(proposal):
            out.fx_waiting += 1
            return
        take(left, proposal)
        out.items.append(proposal)

    links = await _bank_links(db, items)
    for item in items:
        line = links.get(item.line_id)
        if line is None or line.kind not in BANK_TARGETS or not line.ref_id:
            continue
        # Pozycja WB musi być tą operacją: konto, kwota w PLN i strona z wyciągu
        # (szkic WB poprawiony ręcznie mógł zmienić kolejność pozycji).
        expected = "debit" if line.direction == "debit" else "credit"
        if (
            line.counter_account != item.account
            or bank.pln(line) != item.value
            or item.direction != expected
        ):
            continue
        for target in by_source.get(
            (BANK_TARGETS[line.kind], str(line.ref_id), item.account), []
        ):
            pair(item, target, "bank")

    corrections = await _corrections(db, items)
    for item in items:
        if item.source_type != SALES_SOURCE or item.source_id not in corrections:
            continue
        for target in by_source.get(
            (SALES_SOURCE, corrections[item.source_id], item.account), []
        ):
            pair(item, target, "correction")

    # Saldo zerowe liczy się w PLN; grupa z dwiema walutami obcymi (EUR i USD)
    # nie ma wspólnej miary, więc ją pomijamy.
    groups: dict[tuple[str, Optional[str]], list[Item]] = defaultdict(list)
    for item in items:
        if left.open(item):
            groups[(item.account, item.sensitivity)].append(item)
    for group in groups.values():
        debits = [item for item in group if item.direction == "debit"]
        credits = [item for item in group if item.direction == "credit"]
        if not debits or not credits:
            continue
        if len({item.currency for item in group if item.is_currency}) > 1:
            continue
        debit_sum = sum(left.pln[item.line_id] for item in debits)
        if debit_sum != sum(left.pln[item.line_id] for item in credits):
            continue
        out.items.extend(fifo(debits, credits, left, method="zero"))
    return out


def _counts(found: Proposals) -> dict[str, int]:
    out = {method: 0 for method in ("bank", "correction", "zero")}
    for proposal in found.items:
        out[proposal.method] += 1
    out["fx_waiting"] = found.fx_waiting
    return out


async def _open_items(
    db: AsyncSession, viewer: Viewer, account: Optional[str]
) -> list[Item]:
    parents = await load_parents(db)
    if account is not None and not is_settlement_account(account, parents):
        return []
    return await load_items(
        db,
        viewer,
        parents=parents,
        accounts=[account] if account is not None else None,
    )


async def auto_counts(
    db: AsyncSession,
    viewer: Viewer,
    bank_settings: BankSettings,
    *,
    account: Optional[str] = None,
) -> dict[str, int]:
    """Ile rozliczeń zrobiłby automat (podgląd, bez zapisu); ``account`` — jedno konto."""

    fx = await fx_context(db, bank_settings)
    return _counts(await propose(db, await _open_items(db, viewer, account), fx))


# ── Zapis ───────────────────────────────────────────────────────────────────


async def _lock(db: AsyncSession) -> None:
    """Rozliczenia po kolei — dwie osoby nie rozliczą tej samej kwoty dwa razy."""

    await db.execute(select(func.pg_advisory_xact_lock(func.hashtext(LOCK_KEY))))


def _require_approver(viewer: Viewer) -> None:
    if not viewer.approver:
        raise LedgerError(APPROVERS_ONLY, status=403)


def _row(proposal: Proposal, *, viewer: Viewer) -> LedgerSettlement:
    return LedgerSettlement(
        account=proposal.debit.account,
        debit_line_id=proposal.debit.line_id,
        credit_line_id=proposal.credit.line_id,
        amount=proposal.amount,
        credit_amount=proposal.credit_amount,
        currency=proposal.currency,
        amount_cur=proposal.amount_cur,
        settled_on=proposal.settled_on,
        method=proposal.method,
        sensitivity=proposal.debit.sensitivity,
        created_by=viewer.user_id,
    )


def _label(item: Item) -> str:
    """„FVS FV/1/2026” albo „PK 2/10/2026” — typ raz, nawet gdy jest w numerze."""

    if item.number.upper().startswith(f"{item.doc_type} "):
        return item.number
    return f"{item.doc_type} {item.number}"


async def _fx_document(
    db: AsyncSession,
    row: LedgerSettlement,
    proposal: Proposal,
    fx: FxContext,
    *,
    viewer: Viewer,
    plan: dict[str, Any],
) -> Optional[LedgerDocument]:
    """PK różnicy kursowej rozliczenia w walucie (bufor); ``None`` = bez różnicy.

    Nadwyżka udziału po Wn = ujemna różnica (Wn koszty finansowe, Ma konto
    kontrahenta), po Ma = dodatnia (Wn konto kontrahenta, Ma przychody
    finansowe) — po niej saldo konta zgadza się z pozycjami.
    """

    diff = proposal.fx
    if not diff:
        return None
    party = proposal.debit.counterparty_id or proposal.credit.counterparty_id
    text_ = (
        f"Różnica kursowa {row.currency}: {_label(proposal.debit)} — "
        f"{_label(proposal.credit)}"
    )[:200]
    if diff > 0:
        lines = [
            LineIn("debit", fx.loss_account, diff, text_),
            LineIn("credit", row.account, diff, text_, counterparty_id=party),
        ]
    else:
        lines = [
            LineIn("debit", row.account, -diff, text_, counterparty_id=party),
            LineIn("credit", fx.gain_account, -diff, text_),
        ]
    spec = DocumentSpec(
        doc_type="PK",
        op_date=row.settled_on,
        doc_date=row.settled_on,
        lines=lines,
        description=text_,
        counterparty_id=party,
        source_type=FX_SOURCE,
        source_id=str(row.id),
        sensitivity=row.sensitivity,
        meta={"settlement": row.id, "fx": diff, "currency": row.currency},
    )
    return await documents.create_draft(db, spec, actor_id=viewer.user_id, plan=plan)


async def _write(
    db: AsyncSession,
    proposals: list[Proposal],
    fx: FxContext,
    *,
    viewer: Viewer,
) -> dict[str, Any]:
    """Wiersze rozliczeń i PK różnic kursowych (bez commita)."""

    rows = [_row(proposal, viewer=viewer) for proposal in proposals]
    db.add_all(rows)
    await db.flush()
    plan = await documents.load_plan(db) if any(p.fx for p in proposals) else {}
    created_fx: list[dict[str, Any]] = []
    for row, proposal in zip(rows, proposals):
        doc = await _fx_document(db, row, proposal, fx, viewer=viewer, plan=plan)
        if doc is not None:
            created_fx.append(
                {"id": doc.id, "number": doc.number, "amount": abs(proposal.fx)}
            )
    return {
        "created": len(rows),
        "amount": sum(row.amount for row in rows),
        "fx_documents": created_fx,
    }


async def settle(
    db: AsyncSession,
    viewer: Viewer,
    bank_settings: BankSettings,
    *,
    debit_ids: list[int],
    credit_ids: list[int],
    amount: Optional[int] = None,
) -> dict[str, Any]:
    """Rozliczenie zaznaczonych pozycji (od najstarszych), bez commita.

    ``amount`` — kwota jednej pary w jej walucie (grosze/centy).
    """

    _require_approver(viewer)
    debit_ids = list(dict.fromkeys(debit_ids))
    credit_ids = list(dict.fromkeys(credit_ids))
    if not debit_ids or not credit_ids:
        raise LedgerError(
            "Zaznacz co najmniej jedną pozycję Wn i jedną pozycję Ma.", status=422
        )
    if len(debit_ids) + len(credit_ids) > SELECT_MAX:
        raise LedgerError(f"Za dużo pozycji naraz (najwyżej {SELECT_MAX}).", status=422)
    if set(debit_ids) & set(credit_ids):
        raise LedgerError("Ta sama pozycja jest po obu stronach.", status=422)
    if amount is not None and (len(debit_ids) != 1 or len(credit_ids) != 1):
        raise LedgerError(
            "Kwotę wpisuje się przy rozliczeniu jednej pozycji Wn z jedną Ma.",
            status=422,
        )
    await _lock(db)
    parents = await load_parents(db)
    items = await load_items(
        db,
        viewer,
        parents=parents,
        line_ids=[*debit_ids, *credit_ids],
        open_only=False,
    )
    found = {item.line_id: item for item in items}
    if any(line_id not in found for line_id in [*debit_ids, *credit_ids]):
        raise LedgerError(NO_ITEMS, status=404)
    debits = [found[line_id] for line_id in debit_ids]
    credits = [found[line_id] for line_id in credit_ids]
    chosen = [*debits, *credits]
    if len({item.account for item in chosen}) > 1:
        raise LedgerError("Rozlicza się pozycje jednego konta kontrahenta.", status=422)
    for item, side in [
        *((item, "debit") for item in debits),
        *((item, "credit") for item in credits),
    ]:
        if item.direction != side:
            where = "Wn" if item.direction == "debit" else "Ma"
            raise LedgerError(
                f"Pozycja {_label(item)} jest po stronie {where} — zaznacz ją po "
                "drugiej stronie.",
                status=422,
            )
    if len({item.sensitivity for item in chosen}) > 1:
        raise LedgerError(
            "Dokumentu płacowego nie rozlicza się z dokumentem spoza Płac.",
            status=422,
        )
    if len({item.currency for item in chosen if item.is_currency}) > 1:
        raise LedgerError(MIXED_CURRENCIES, status=422)
    left = Left.of(chosen)
    for item in chosen:
        if not left.open(item):
            raise LedgerError(
                f"Pozycja {_label(item)} jest już rozliczona.", status=409
            )
    if amount is not None:
        proposal = terms(debits[0], credits[0], left, method="manual", amount=amount)
        if proposal is None:
            raise LedgerError(
                "Kwota rozliczenia musi być większa od zera i nie większa niż to, "
                "co zostało do rozliczenia.",
                status=422,
            )
        proposals = [proposal]
    else:
        proposals = fifo(debits, credits, left, method="manual")
    fx = await fx_context(db, bank_settings)
    for proposal in proposals:
        problem = fx.blocker(proposal)
        if problem:
            raise LedgerError(problem, status=422)
    result = await _write(db, proposals, fx, viewer=viewer)
    return {"account": chosen[0].account, **result}


async def settle_auto(
    db: AsyncSession,
    viewer: Viewer,
    bank_settings: BankSettings,
    *,
    account: Optional[str] = None,
) -> dict[str, Any]:
    """Automat: wyciąg ↔ faktura, korekta ↔ faktura, saldo zerowe (bez commita)."""

    _require_approver(viewer)
    await _lock(db)
    fx = await fx_context(db, bank_settings)
    found = await propose(db, await _open_items(db, viewer, account), fx)
    result = await _write(db, found.items, fx, viewer=viewer)
    return {**_counts(found), **result}


async def unsettle(
    db: AsyncSession, viewer: Viewer, settlement_id: int, *, now: datetime
) -> None:
    """Cofnięcie rozliczenia — wiersz zostaje jako ślad (kto i kiedy).

    Szkic różnicy kursowej tego rozliczenia znika razem z nim; zaksięgowanej
    nie ruszamy — najpierw jej storno (409).
    """

    _require_approver(viewer)
    await _lock(db)
    row = await db.get(
        LedgerSettlement, settlement_id, with_for_update=True, populate_existing=True
    )
    if row is None or row.removed_at is not None:
        raise LedgerError(NO_SETTLEMENT, status=404)
    if row.sensitivity is not None and not viewer.payroll:
        raise LedgerError(NO_SETTLEMENT, status=404)
    fx_doc = await db.scalar(
        select(LedgerDocument).where(
            LedgerDocument.source_type == FX_SOURCE,
            LedgerDocument.source_id == str(row.id),
            LedgerDocument.reversed_by_id.is_(None),
        )
    )
    if fx_doc is not None:
        if fx_doc.status != "draft":
            raise LedgerError(FX_APPROVED.format(number=fx_doc.number), status=409)
        await documents.delete_draft(db, fx_doc.id, viewer=viewer)
    row.removed_at = now
    row.removed_by = viewer.user_id
    await db.flush()
