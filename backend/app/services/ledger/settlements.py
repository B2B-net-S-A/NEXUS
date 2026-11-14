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
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime
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
    LedgerSettlement,
    LedgerYear,
)
from app.services.finance_ledger.costs import LedgerError
from app.services.ledger import bank, documents, sources
from app.services.ledger.documents import Viewer

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

    @property
    def remaining(self) -> int:
        return self.value - self.used


@dataclass(frozen=True)
class Proposal:
    debit: Item
    credit: Item
    amount: int
    method: str


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


def fifo(
    debits: list[Item], credits: list[Item], left: dict[int, int]
) -> list[tuple[Item, Item, int]]:
    """Pary od najstarszych pozycji; ``left`` — ile zostało (zmieniane w miejscu)."""

    pairs: list[tuple[Item, Item, int]] = []
    queue_d = sorted((item for item in debits if left[item.line_id] > 0), key=_order)
    queue_c = sorted((item for item in credits if left[item.line_id] > 0), key=_order)
    i = j = 0
    while i < len(queue_d) and j < len(queue_c):
        debit, credit = queue_d[i], queue_c[j]
        amount = min(left[debit.line_id], left[credit.line_id])
        pairs.append((debit, credit, amount))
        left[debit.line_id] -= amount
        left[credit.line_id] -= amount
        if left[debit.line_id] == 0:
            i += 1
        if left[credit.line_id] == 0:
            j += 1
    return pairs


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
    """Rozliczone kwoty pozycji — tylko z żywą pozycją po drugiej stronie."""

    other = aliased(LedgerLine)
    other_doc = aliased(LedgerDocument)

    def side(own: Any, theirs: Any) -> Any:
        query = (
            select(own.label("line_id"), LedgerSettlement.amount.label("amount"))
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
        side(LedgerSettlement.debit_line_id, LedgerSettlement.credit_line_id),
        side(LedgerSettlement.credit_line_id, LedgerSettlement.debit_line_id),
    ).subquery()
    return (
        select(both.c.line_id, func.sum(both.c.amount).label("used"))
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
        .where(*_live(LedgerDocument, bo_years, as_of), _accounts_clause(parents))
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
            amount_cur=row.amount_cur,
            counterparty_id=row.counterparty_id or row.doc_counterparty_id,
            sensitivity=row.sensitivity,
            source_type=row.source_type,
            source_id=row.source_id,
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


async def propose(db: AsyncSession, items: list[Item]) -> list[Proposal]:
    """Rozliczenia automatu na otwartych pozycjach (bez zapisu)."""

    left = {item.line_id: item.remaining for item in items}
    by_source: dict[tuple[str, str, str], list[Item]] = defaultdict(list)
    for item in items:
        if item.source_type and item.source_id:
            by_source[(item.source_type, item.source_id, item.account)].append(item)
    proposals: list[Proposal] = []

    def pair(first: Item, second: Item, method: str) -> None:
        debit, credit = (
            (first, second) if first.direction == "debit" else (second, first)
        )
        if debit.direction != "debit" or credit.direction != "credit":
            return
        if debit.account != credit.account or debit.sensitivity != credit.sensitivity:
            return
        amount = min(left[debit.line_id], left[credit.line_id])
        if amount <= 0:
            return
        left[debit.line_id] -= amount
        left[credit.line_id] -= amount
        proposals.append(Proposal(debit, credit, amount, method))

    links = await _bank_links(db, items)
    for item in items:
        line = links.get(item.line_id)
        if line is None or line.kind not in BANK_TARGETS or not line.ref_id:
            continue
        # Pozycja WB musi być tą operacją: konto, kwota i strona z wyciągu
        # (szkic WB poprawiony ręcznie mógł zmienić kolejność pozycji).
        expected = "debit" if line.direction == "debit" else "credit"
        if (
            line.counter_account != item.account
            or line.amount != item.value
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

    groups: dict[tuple[str, Optional[str]], list[Item]] = defaultdict(list)
    for item in items:
        if left[item.line_id] > 0:
            groups[(item.account, item.sensitivity)].append(item)
    for group in groups.values():
        debits = [item for item in group if item.direction == "debit"]
        credits = [item for item in group if item.direction == "credit"]
        debit_sum = sum(left[item.line_id] for item in debits)
        if not debits or not credits:
            continue
        if debit_sum != sum(left[item.line_id] for item in credits):
            continue
        for debit, credit, amount in fifo(debits, credits, left):
            proposals.append(Proposal(debit, credit, amount, "zero"))
    return proposals


def _counts(proposals: list[Proposal]) -> dict[str, int]:
    out = {method: 0 for method in ("bank", "correction", "zero")}
    for proposal in proposals:
        out[proposal.method] += 1
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
    db: AsyncSession, viewer: Viewer, *, account: Optional[str] = None
) -> dict[str, int]:
    """Ile rozliczeń zrobiłby automat (podgląd, bez zapisu); ``account`` — jedno konto."""

    return _counts(await propose(db, await _open_items(db, viewer, account)))


# ── Zapis ───────────────────────────────────────────────────────────────────


async def _lock(db: AsyncSession) -> None:
    """Rozliczenia po kolei — dwie osoby nie rozliczą tej samej kwoty dwa razy."""

    await db.execute(select(func.pg_advisory_xact_lock(func.hashtext(LOCK_KEY))))


def _require_approver(viewer: Viewer) -> None:
    if not viewer.approver:
        raise LedgerError(APPROVERS_ONLY, status=403)


def _row(proposal: Proposal, *, method: str, viewer: Viewer) -> LedgerSettlement:
    return LedgerSettlement(
        account=proposal.debit.account,
        debit_line_id=proposal.debit.line_id,
        credit_line_id=proposal.credit.line_id,
        amount=proposal.amount,
        settled_on=max(proposal.debit.op_date, proposal.credit.op_date),
        method=method,
        sensitivity=proposal.debit.sensitivity,
        created_by=viewer.user_id,
    )


def _label(item: Item) -> str:
    """„FVS FV/1/2026” albo „PK 2/10/2026” — typ raz, nawet gdy jest w numerze."""

    if item.number.upper().startswith(f"{item.doc_type} "):
        return item.number
    return f"{item.doc_type} {item.number}"


async def settle(
    db: AsyncSession,
    viewer: Viewer,
    *,
    debit_ids: list[int],
    credit_ids: list[int],
    amount: Optional[int] = None,
) -> dict[str, Any]:
    """Rozliczenie zaznaczonych pozycji (od najstarszych), bez commita."""

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
    for item in chosen:
        if item.remaining <= 0:
            raise LedgerError(
                f"Pozycja {_label(item)} jest już rozliczona.", status=409
            )
    left = {item.line_id: item.remaining for item in chosen}
    if amount is not None:
        limit = min(left[debits[0].line_id], left[credits[0].line_id])
        if amount <= 0 or amount > limit:
            raise LedgerError(
                "Kwota rozliczenia musi być większa od zera i nie większa niż to, "
                "co zostało do rozliczenia.",
                status=422,
            )
        pairs = [(debits[0], credits[0], amount)]
    else:
        pairs = fifo(debits, credits, left)
    rows = [
        _row(Proposal(debit, credit, value, "manual"), method="manual", viewer=viewer)
        for debit, credit, value in pairs
    ]
    db.add_all(rows)
    await db.flush()
    return {
        "account": chosen[0].account,
        "created": len(rows),
        "amount": sum(row.amount for row in rows),
    }


async def settle_auto(
    db: AsyncSession, viewer: Viewer, *, account: Optional[str] = None
) -> dict[str, Any]:
    """Automat: wyciąg ↔ faktura, korekta ↔ faktura, saldo zerowe (bez commita)."""

    _require_approver(viewer)
    await _lock(db)
    proposals = await propose(db, await _open_items(db, viewer, account))
    rows = [_row(item, method=item.method, viewer=viewer) for item in proposals]
    db.add_all(rows)
    await db.flush()
    return {
        **_counts(proposals),
        "created": len(rows),
        "amount": sum(row.amount for row in rows),
    }


async def unsettle(
    db: AsyncSession, viewer: Viewer, settlement_id: int, *, now: datetime
) -> None:
    """Cofnięcie rozliczenia — wiersz zostaje jako ślad (kto i kiedy)."""

    _require_approver(viewer)
    await _lock(db)
    row = await db.get(
        LedgerSettlement, settlement_id, with_for_update=True, populate_existing=True
    )
    if row is None or row.removed_at is not None:
        raise LedgerError(NO_SETTLEMENT, status=404)
    if row.sensitivity is not None and not viewer.payroll:
        raise LedgerError(NO_SETTLEMENT, status=404)
    row.removed_at = now
    row.removed_by = viewer.user_id
    await db.flush()
