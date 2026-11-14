"""Środki trwałe i WNiP (K6): ewidencja, dokumenty środka i amortyzacja miesiąca.

Plan „Księgowość w NEXUSIE” (13.11.2026): NEXUS zastępuje Symfonię Środki
Trwałe. Plan amortyzacji liczy ``depreciation.py`` (czyste funkcje), tu jest
ewidencja i to, co z niej trafia do księgi.

* **Ewidencja**: numer inwentarzowy (``ST/2026/001``, ``WNiP/2026/001`` albo
  własny), KŚT, data przyjęcia, wartość początkowa, konto środka (010/020)
  i umorzenia (070/071), MPK, metoda i stawka osobno dla planu bilansowego
  i podatkowego, powiązanie z pozycją „Sprzętu”. Środek przeniesiony
  z Symfonii ma stan na koniec miesiąca (umorzenie bilansowe i podatkowe) i nie
  dostaje OT w księdze — jego wartość i umorzenie przychodzą bilansem otwarcia.
* **Dokumenty środka**: OT (przyjęcie, także z faktury z kolejki kosztów:
  Wn 010 / Ma 080), UL (ulepszenie: Wn 010 / Ma 080), MT (zmiana MPK — bez
  zapisu, zmienia podział AM od swojego miesiąca), LT i SP (likwidacja,
  sprzedaż: Wn 070 umorzenie z odpisem za miesiąc zbycia, Wn 761 wartość
  netto / Ma 010 wartość początkowa; przychód ze sprzedaży księguje faktura).
  Dokumenty w księdze robi „Zaksięguj miesiąc” (źródło ``asset_operation``).
* **AM miesiąca** (źródło ``assets_month`` / ``RRRR-MM``): odpisy bilansowe
  wszystkich środków — Wn 401 z MPK, Ma 070/071, i od razu podział na „5”:
  Wn konta „5” z MPK (konta z rozliczenia kosztów K2), Ma 490. ``meta.assets``
  zatwierdzonego AM to trwały zapis, ile i na jakie MPK poszło z każdego środka.
* **Zatwierdzona przeszłość jest nietykalna**: zmiana, która przestawiłaby
  odpis środka (kwotę, MPK, konto) w miesiącu z zatwierdzonym AM, dostaje 409
  z numerem zapisu — tak samo nowy środek przyjęty wstecz, ulepszenie, MT i LT
  z datą w zamkniętym miesiącu i usunięcie dokumentu. Parametrów planu środka
  z jakimkolwiek zatwierdzonym zapisem nie zmienia się wcale. Każda zmiana
  zdejmuje z bufora szkice AM i dokumentów środka — następne „Zaksięguj
  miesiąc” zrobi je z nowych danych (jak automaty K3a).
* Ewidencję zmienia lista „Księgowi” albo admin (bramka w trasie); podgląd —
  „Moduł Finanse” przy otwartym module ``assets``.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any, Optional

from sqlalchemy import and_, or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.client import Client
from app.models.equipment import EquipmentItem
from app.models.finance_ledger import FinanceCostEntry
from app.models.ledger import LedgerDocument, LedgerPeriod, LedgerYear
from app.models.ledger_assets import LedgerAsset, LedgerAssetOperation
from app.services.finance_ledger.costs import LedgerError
from app.services.finance_ledger.posting import clean_account, money_pl
from app.services.ledger import depreciation, documents, engine
from app.services.ledger.allocation import KIND_ACCOUNT, Mpk
from app.services.ledger.depreciation import PlanInput, PlanRow, first_of
from app.services.ledger.documents import DocumentSpec, Viewer
from app.services.ledger.engine import LineIn, PlanAccount
from app.services.ledger.settings import (
    AllocationAccounts,
    AssetsAccounts,
    LedgerSettings,
)
from app.services.ledger_assets_schema import (
    ASSET_KINDS,
    INVENTORY_MAX,
    KST_MAX,
    NAME_MAX,
    NOTE_MAX,
    OPERATION_NOTE_MAX,
    OPERATION_TITLE_MAX,
)
from app.services.ledger_schema import DESCRIPTION_MAX, LINE_TEXT_MAX

SOURCE_MONTH = "assets_month"
SOURCE_OPERATION = "asset_operation"
#: Klucz blokady numeracji (numery inwentarzowe i dokumentów środka).
_NUMBER_LOCK = 703_0001
VALUE_LIMIT = 10**14

KIND_LABELS: dict[str, str] = {"fixed": "Środek trwały", "intangible": "WNiP"}
STATUS_LABELS: dict[str, str] = {
    "in_use": "w użyciu",
    "liquidated": "zlikwidowany",
    "sold": "sprzedany",
}
OPERATION_LABELS: dict[str, str] = {
    "OT": "Przyjęcie (OT)",
    "UL": "Ulepszenie",
    "MT": "Zmiana MPK (MT)",
    "LT": "Likwidacja (LT)",
    "SP": "Sprzedaż",
}
#: Dokumenty środka, które robi się z ekranu (OT powstaje z nowym środkiem).
ADDED_TYPES: tuple[str, ...] = ("UL", "MT", "LT", "SP")
#: Dokumenty z zapisem w księdze (MT zmienia tylko podział AM).
POSTED_TYPES: tuple[str, ...] = ("OT", "UL", "LT", "SP")
DISPOSALS: dict[str, str] = {"LT": "liquidated", "SP": "sold"}
DEFAULT_ACCOUNTS: dict[str, tuple[str, str]] = {
    "fixed": ("010", "070"),
    "intangible": ("020", "071"),
}
INVENTORY_PREFIX: dict[str, str] = {"fixed": "ST", "intangible": "WNiP"}
MPK_CODES: dict[str, tuple[str, str]] = {
    "FO": ("front_office", "Front office"),
    "BO": ("back_office", "Back office"),
    "OG": ("overhead", "Koszty ogólne"),
}
_CLIENT_MPK = re.compile(r"K(\d{1,9})")
_KST = re.compile(r"\d{1,3}([.\-]\d{1,3}){0,3}")
LOCKED = (
    "Środek ma zatwierdzony zapis w księdze ({what}) — parametrów planu już się nie "
    "zmienia. Popraw go stornem tego zapisu albo dokumentem (ulepszenie, likwidacja)."
)
NO_COST_ACCOUNT = (
    "Ustaw konto amortyzacji w Ustawieniach środków trwałych (administrator)."
)
NO_ALLOCATION = (
    "Ustaw konta rozliczenia kosztów na „5” w Ustawieniach Księgowości "
    "(administrator) — dokument AM dzieli amortyzację na MPK."
)
NO_DISPOSAL_ACCOUNT = (
    "Ustaw konto wartości netto likwidacji i sprzedaży w Ustawieniach środków "
    "trwałych (administrator)."
)


# ── MPK ──────────────────────────────────────────────────────────────────────


def mpk_kind(code: str) -> Optional[tuple[str, Optional[int]]]:
    """``FO`` / ``BO`` / ``OG`` / ``K<id klienta>`` → (rodzaj, id klienta)."""

    if code in MPK_CODES:
        return MPK_CODES[code][0], None
    match = _CLIENT_MPK.fullmatch(code or "")
    if match:
        return "client", int(match.group(1))
    return None


async def mpk_labels(db: AsyncSession, codes: set[str]) -> dict[str, Mpk]:
    clients = {
        kind[1]
        for code in codes
        if (kind := mpk_kind(code)) is not None and kind[1] is not None
    }
    names: dict[int, str] = {}
    if clients:
        rows = await db.execute(
            select(Client.id, Client.name).where(Client.id.in_(clients))
        )
        names = {client_id: name for client_id, name in rows.all()}
    out: dict[str, Mpk] = {}
    for code in codes:
        kind = mpk_kind(code)
        if kind is None:
            out[code] = Mpk(code, "unknown", code)
        elif kind[1] is not None:
            out[code] = Mpk(code, "client", names.get(kind[1]) or f"Klient {kind[1]}")
        else:
            out[code] = Mpk(code, kind[0], MPK_CODES[code][1])
    return out


async def clean_mpk(db: AsyncSession, raw: Optional[str]) -> str:
    code = "".join((raw or "").split()).upper()
    kind = mpk_kind(code)
    if kind is None:
        raise LedgerError(
            "MPK: FO (Front office), BO (Back office), OG (koszty ogólne) albo "
            "K<id klienta>.",
            status=422,
        )
    if kind[1] is not None:
        found = await db.scalar(select(Client.id).where(Client.id == kind[1]))
        if found is None:
            raise LedgerError(f"MPK {code}: nie ma takiego klienta.", status=422)
    return code


def mpk_in(
    asset: LedgerAsset, operations: list[LedgerAssetOperation], month: date
) -> str:
    """MPK środka w miesiącu: zmiana MPK (MT) działa od miesiąca dokumentu."""

    moves = sorted(
        (op for op in operations if op.op_type == "MT"),
        key=lambda op: (op.op_date, op.id or 0),
    )
    if not moves:
        return asset.mpk
    current = moves[0].mpk_from or asset.mpk
    for op in moves:
        if first_of(op.op_date) > month:
            break
        current = op.mpk_to or current
    return current


# ── Plan (bez bazy) ──────────────────────────────────────────────────────────


def plan_input(
    asset: LedgerAsset, operations: list[LedgerAssetOperation], *, tax: bool = False
) -> PlanInput:
    opening = None
    if asset.opening_month is not None:
        opening = depreciation.Opening(
            month=asset.opening_month,
            accumulated=asset.opening_tax if tax else asset.opening_balance,
            year_start=asset.opening_tax_year if tax else asset.opening_balance_year,
        )
    return PlanInput(
        method=asset.tax_method if tax else asset.balance_method,
        rate=Decimal(asset.tax_rate if tax else asset.balance_rate),
        initial=asset.initial_value,
        accepted=asset.accepted_on,
        coefficient=Decimal(asset.coefficient),
        improvements=tuple(
            (op.op_date, int(op.amount or 0)) for op in operations if op.op_type == "UL"
        ),
        opening=opening,
        disposed=asset.disposed_on,
    )


@dataclass(frozen=True)
class AmItem:
    """Odpis bilansowy jednego środka w dokumencie AM."""

    asset_id: int
    account: str
    mpk: str
    amount: int


def assets_word(count: int) -> str:
    last, last_two = count % 10, count % 100
    if count == 1:
        return "1 środek"
    if 2 <= last <= 4 and not 12 <= last_two <= 14:
        return f"{count} środki"
    return f"{count} środków"


def month_source_id(month: date) -> str:
    return f"{month.year}-{month.month:02d}"


def source_month(source_id: str) -> date:
    year, month = str(source_id).split("-")[:2]
    return date(int(year), int(month), 1)


def detail_of(items: list[AmItem]) -> list[list[Any]]:
    return [
        [item.asset_id, item.amount, item.mpk, item.account]
        for item in sorted(items, key=lambda item: item.asset_id)
    ]


def depreciation_spec(
    month: date,
    items: list[AmItem],
    accounts: AssetsAccounts,
    allocation: AllocationAccounts,
    labels: dict[str, Mpk],
) -> tuple[Optional[DocumentSpec], list[str]]:
    """Dokument AM miesiąca: Wn 401 (MPK) / Ma 070-071 i podział na „5” / Ma 490."""

    items = [item for item in items if item.amount]
    if not items:
        return None, []
    problems: list[str] = []
    if not accounts.cost_account:
        problems.append(NO_COST_ACCOUNT)
    by_mpk: dict[str, int] = defaultdict(int)
    by_account: dict[str, int] = defaultdict(int)
    for item in items:
        by_mpk[item.mpk] += item.amount
        by_account[item.account] += item.amount
    total = sum(by_mpk.values())
    cost_lines: list[LineIn] = []
    split_lines: list[LineIn] = []
    for code in sorted(by_mpk):
        mpk = labels.get(code) or Mpk(code, "unknown", code)
        cost_lines.append(
            LineIn(
                side="debit",
                account=accounts.cost_account,
                amount=by_mpk[code],
                mpk=code,
                description=f"Amortyzacja — {mpk.label}"[:LINE_TEXT_MAX],
            )
        )
        field_name = KIND_ACCOUNT.get(mpk.kind)
        if field_name is None:
            problems.append(
                f"MPK {code} nie jest miejscem kosztów — popraw MPK środka."
            )
            continue
        account = getattr(allocation, field_name)
        if not account:
            problems.append(NO_ALLOCATION)
            continue
        split_lines.append(
            LineIn(
                side="debit",
                account=account,
                amount=by_mpk[code],
                mpk=code,
                description=mpk.label[:LINE_TEXT_MAX],
            )
        )
    if not allocation.settlement_account:
        problems.append(NO_ALLOCATION)
    if problems:
        return None, list(dict.fromkeys(problems))
    lines = [
        *cost_lines,
        *(
            LineIn(
                side="credit",
                account=account,
                amount=by_account[account],
                description="Umorzenie",
            )
            for account in sorted(by_account)
        ),
        *split_lines,
        LineIn(
            side="credit",
            account=allocation.settlement_account,
            amount=total,
            description="Rozliczenie kosztów — amortyzacja",
        ),
    ]
    detail = detail_of(items)
    raw = json.dumps(detail, separators=(",", ":"))
    last = depreciation.add_months(month, 1).toordinal() - 1
    end = date.fromordinal(last)
    return (
        DocumentSpec(
            doc_type="AM",
            op_date=end,
            doc_date=end,
            lines=lines,
            description=(
                f"Amortyzacja {month.month:02d}.{month.year} — {assets_word(len(items))}"
            )[:DESCRIPTION_MAX],
            source_type=SOURCE_MONTH,
            source_id=month_source_id(month),
            meta={
                "source": "assets",
                "assets": detail,
                "detail_hash": hashlib.sha256(raw.encode()).hexdigest()[:16],
            },
        ),
        [],
    )


def operation_spec(
    op: LedgerAssetOperation,
    asset: LedgerAsset,
    operations: list[LedgerAssetOperation],
    accounts: AssetsAccounts,
) -> tuple[Optional[DocumentSpec], list[str]]:
    """Zapis dokumentu środka (OT, UL, LT, SP) — PK z numerem dokumentu środka."""

    text_ = f"{op.number} — {op.title}" if op.title else op.number
    if op.op_type in ("OT", "UL"):
        amount = int(op.amount or 0)
        counter = op.counter_account or accounts.intake_account
        if not counter:
            return None, ["Podaj konto przeciwstawne przyjęcia (np. 080)."]
        label = OPERATION_LABELS[op.op_type]
        lines = [
            LineIn(
                side="debit",
                account=asset.asset_account,
                amount=amount,
                mpk=None,
                description=label,
            ),
            LineIn(side="credit", account=counter, amount=amount, description=label),
        ]
    elif op.op_type in DISPOSALS:
        plan = plan_input(asset, operations)
        month = first_of(op.op_date)
        rows = depreciation.schedule(plan, until=month)
        value = depreciation.value_at(plan, month)
        accumulated = min(depreciation.accumulated_at(plan, rows, month), value)
        net = value - accumulated
        lines = []
        if accumulated > 0:
            lines.append(
                LineIn(
                    side="debit",
                    account=asset.depreciation_account,
                    amount=accumulated,
                    description="Umorzenie do miesiąca zbycia",
                )
            )
        if net > 0:
            if not accounts.disposal_account:
                return None, [NO_DISPOSAL_ACCOUNT]
            lines.append(
                LineIn(
                    side="debit",
                    account=accounts.disposal_account,
                    amount=net,
                    description="Wartość netto",
                )
            )
        lines.append(
            LineIn(
                side="credit",
                account=asset.asset_account,
                amount=value,
                description="Wartość początkowa",
            )
        )
    else:
        return None, []
    return (
        DocumentSpec(
            doc_type="PK",
            op_date=op.op_date,
            doc_date=op.op_date,
            lines=lines,
            number=op.number,
            description=text_[:DESCRIPTION_MAX],
            source_type=SOURCE_OPERATION,
            source_id=str(op.id),
            meta={
                "source": "asset_operation",
                "asset": asset.id,
                "op_type": op.op_type,
            },
        ),
        [],
    )


# ── Odczyt z bazy ────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class AmState:
    """Nieodwrócony dokument AM miesiąca i jego rozbicie na środki."""

    document_id: int
    number: str
    status: str
    journal_no: Optional[int]
    detail: dict[int, tuple[int, str, str]]


async def am_documents(db: AsyncSession) -> dict[date, AmState]:
    rows = await db.scalars(
        select(LedgerDocument).where(
            LedgerDocument.source_type == SOURCE_MONTH,
            LedgerDocument.reversed_by_id.is_(None),
        )
    )
    out: dict[date, AmState] = {}
    for doc in rows:
        detail: dict[int, tuple[int, str, str]] = {}
        for item in (doc.meta or {}).get("assets") or []:
            detail[int(item[0])] = (int(item[1]), str(item[2]), str(item[3]))
        out[source_month(str(doc.source_id))] = AmState(
            document_id=doc.id,
            number=doc.number,
            status=doc.status,
            journal_no=doc.journal_no,
            detail=detail,
        )
    return out


async def operations_of(
    db: AsyncSession, asset_ids: list[int]
) -> dict[int, list[LedgerAssetOperation]]:
    rows = await db.scalars(
        select(LedgerAssetOperation)
        .where(LedgerAssetOperation.asset_id.in_(asset_ids or [0]))
        .order_by(LedgerAssetOperation.op_date, LedgerAssetOperation.id)
    )
    out: dict[int, list[LedgerAssetOperation]] = defaultdict(list)
    for op in rows:
        out[op.asset_id].append(op)
    return out


async def operation_documents(
    db: AsyncSession, op_ids: list[int]
) -> dict[int, LedgerDocument]:
    rows = await db.scalars(
        select(LedgerDocument).where(
            LedgerDocument.source_type == SOURCE_OPERATION,
            LedgerDocument.source_id.in_([str(op_id) for op_id in op_ids] or ["-"]),
            LedgerDocument.reversed_by_id.is_(None),
        )
    )
    return {int(str(doc.source_id)): doc for doc in rows}


async def month_items(db: AsyncSession, month: date) -> list[AmItem]:
    """Odpisy bilansowe miesiąca: środki przyjęte wcześniej i niezbyte przed nim."""

    assets = list(
        await db.scalars(
            select(LedgerAsset)
            .where(
                LedgerAsset.accepted_on < month,
                or_(
                    LedgerAsset.disposed_on.is_(None),
                    LedgerAsset.disposed_on >= month,
                ),
            )
            .order_by(LedgerAsset.id)
        )
    )
    operations = await operations_of(db, [asset.id for asset in assets])
    items: list[AmItem] = []
    for asset in assets:
        ops = operations.get(asset.id, [])
        row = depreciation.row_for(
            depreciation.schedule(plan_input(asset, ops), until=month), month
        )
        if row is not None and row.amount:
            items.append(
                AmItem(
                    asset_id=asset.id,
                    account=asset.depreciation_account,
                    mpk=mpk_in(asset, ops, month),
                    amount=row.amount,
                )
            )
    return items


# ── Źródła miesiąca (księgowanie przez maszynę „Źródeł” K2) ───────────────────


@dataclass
class MonthDoc:
    source_id: str
    label: str
    spec: Optional[DocumentSpec] = None
    problems: list[str] = field(default_factory=list)
    skipped: bool = False


async def depreciation_docs(
    db: AsyncSession, month: date, settings: LedgerSettings
) -> list[MonthDoc]:
    items = await month_items(db, month)
    doc = MonthDoc(
        source_id=month_source_id(month),
        label=f"Amortyzacja {month.month:02d}.{month.year}",
    )
    if not items:
        doc.skipped = True
        return [doc]
    labels = await mpk_labels(db, {item.mpk for item in items})
    doc.spec, doc.problems = depreciation_spec(
        month, items, settings.assets, settings.allocation, labels
    )
    return [doc]


async def operation_docs(
    db: AsyncSession, month: date, settings: LedgerSettings
) -> list[MonthDoc]:
    following = depreciation.add_months(month, 1)
    month_ops = list(
        await db.scalars(
            select(LedgerAssetOperation)
            .where(
                LedgerAssetOperation.op_date >= month,
                LedgerAssetOperation.op_date < following,
                LedgerAssetOperation.op_type.in_(POSTED_TYPES),
            )
            .order_by(LedgerAssetOperation.op_date, LedgerAssetOperation.id)
        )
    )
    if not month_ops:
        return []
    asset_ids = sorted({op.asset_id for op in month_ops})
    assets = {
        asset.id: asset
        for asset in await db.scalars(
            select(LedgerAsset).where(LedgerAsset.id.in_(asset_ids))
        )
    }
    operations = await operations_of(db, asset_ids)
    out: list[MonthDoc] = []
    for op in month_ops:
        if op.op_type == "OT" and op.counter_account is None:
            continue  # przyjęcie bez zapisu w księdze
        spec, problems = operation_spec(
            op, assets[op.asset_id], operations[op.asset_id], settings.assets
        )
        out.append(
            MonthDoc(
                source_id=str(op.id),
                label=f"{op.number} — {op.title}" if op.title else op.number,
                spec=spec,
                problems=problems,
            )
        )
    return out


# ── Pilnowanie zatwierdzonej przeszłości ─────────────────────────────────────


def _month_text(month: date) -> str:
    return f"{month.month:02d}.{month.year}"


async def ensure_booked_unchanged(
    db: AsyncSession,
    asset_id: int,
    asset: Optional[LedgerAsset],
    operations: list[LedgerAssetOperation],
) -> None:
    """Odpis środka w każdym miesiącu z zatwierdzonym AM musi zostać ten sam.

    ``asset=None`` — środek znika (usunięcie): nie może go być w żadnym AM.
    """

    booked = {
        month: state
        for month, state in (await am_documents(db)).items()
        if state.status == "approved"
    }
    if not booked:
        return
    rows: dict[date, PlanRow] = {}
    if asset is not None:
        rows = {
            row.month: row
            for row in depreciation.schedule(
                plan_input(asset, operations), until=max(booked)
            )
        }
    for month in sorted(booked):
        state = booked[month]
        row = rows.get(month)
        expected = (
            (row.amount, mpk_in(asset, operations, month), asset.depreciation_account)
            if row is not None and asset is not None and row.amount
            else None
        )
        if state.detail.get(asset_id) != expected:
            raise LedgerError(
                f"Amortyzacja {_month_text(month)} jest zatwierdzona (zapis nr "
                f"{state.journal_no}) — ta zmiana przestawiłaby w niej odpis tego "
                "środka (kwotę, MPK albo konto umorzenia). Zrób najpierw storno tego "
                "zapisu albo wprowadź zmianę z datą po tym miesiącu.",
                status=409,
            )


async def booked_reason(
    db: AsyncSession, asset: LedgerAsset, operations: list[LedgerAssetOperation]
) -> Optional[str]:
    """Czy środek ma zatwierdzony zapis (dokument środka albo AM) — i jaki."""

    docs = await operation_documents(db, [op.id for op in operations])
    for op in operations:
        doc = docs.get(op.id)
        if doc is not None and doc.status == "approved":
            return f"{op.number}, zapis nr {doc.journal_no}"
    for month, state in sorted((await am_documents(db)).items()):
        if state.status == "approved" and asset.id in state.detail:
            return f"amortyzacja {_month_text(month)}, zapis nr {state.journal_no}"
    return None


async def withdraw_drafts(
    db: AsyncSession,
    viewer: Viewer,
    *,
    operation_ids: list[int],
    months: bool = True,
) -> int:
    """Zdejmuje z bufora szkice dokumentów podanych operacji i (``months``) AM.

    Jak automaty K3a: szkic ze starymi danymi dałoby się zatwierdzić. Sama
    zmiana opisu środka nie rusza AM (pozycje i opis AM jej nie zawierają),
    więc wtedy schodzą tylko szkice dokumentów tego środka.
    """

    own = and_(
        LedgerDocument.source_type == SOURCE_OPERATION,
        LedgerDocument.source_id.in_([str(op_id) for op_id in operation_ids] or ["-"]),
    )
    scope = or_(LedgerDocument.source_type == SOURCE_MONTH, own) if months else own
    drafts = list(
        await db.scalars(
            select(LedgerDocument).where(LedgerDocument.status == "draft", scope)
        )
    )
    for doc in drafts:
        await documents.delete_draft(db, doc.id, viewer=viewer)
    return len(drafts)


async def _require_open_month(db: AsyncSession, day: date, what: str) -> None:
    year = await db.scalar(select(LedgerYear).where(LedgerYear.year == day.year))
    if year is None:
        return
    period = await db.scalar(
        select(LedgerPeriod).where(
            LedgerPeriod.year_id == year.id, LedgerPeriod.month == day.month
        )
    )
    if year.status != "open" or (period is not None and period.status != "open"):
        raise LedgerError(
            f"{what}: okres {_month_text(first_of(day))} jest zamknięty — dokumentu "
            "z tą datą nie da się zaksięgować.",
            status=409,
        )


# ── Numeracja ────────────────────────────────────────────────────────────────


async def _lock_numbers(db: AsyncSession) -> None:
    await db.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": _NUMBER_LOCK})


async def next_inventory(db: AsyncSession, kind: str, year: int) -> str:
    prefix = f"{INVENTORY_PREFIX[kind]}/{year}/"
    numbers = await db.scalars(
        select(LedgerAsset.inventory_number).where(
            LedgerAsset.inventory_number.like(f"{prefix}%")
        )
    )
    used = [int(n[len(prefix) :]) for n in numbers if n[len(prefix) :].isdigit()]
    return f"{prefix}{max(used, default=0) + 1:03d}"


async def next_operation_number(db: AsyncSession, op_type: str, year: int) -> str:
    suffix = f"/{year}"
    numbers = await db.scalars(
        select(LedgerAssetOperation.number).where(
            LedgerAssetOperation.number.like(f"{op_type} %{suffix}")
        )
    )
    used = []
    for number in numbers:
        middle = number[len(op_type) + 1 : len(number) - len(suffix)]
        if middle.isdigit():
            used.append(int(middle))
    return f"{op_type} {max(used, default=0) + 1}{suffix}"


# ── Walidacja wartości ───────────────────────────────────────────────────────


def _text(raw: Optional[str], limit: int) -> str:
    return " ".join((raw or "").split())[:limit]


def _plan_account(plan: dict[str, PlanAccount], raw: Optional[str], label: str) -> str:
    number = clean_account(raw, label)
    resolved, problem = engine.resolve(number, plan)
    if resolved is None:
        raise LedgerError(f"{label}: {problem}", status=422)
    return number


def clean_rate(raw: Any, label: str) -> Decimal:
    try:
        value = Decimal(str(raw if raw is not None else "0").replace(",", "."))
    except InvalidOperation as exc:
        raise LedgerError(f"{label}: niepoprawna stawka.", status=422) from exc
    if not value.is_finite() or not Decimal(0) <= value <= Decimal(100):
        raise LedgerError(f"{label}: stawka od 0 do 100%.", status=422)
    if value != value.quantize(Decimal("0.01")):
        raise LedgerError(f"{label}: stawka z najwyżej dwoma miejscami.", status=422)
    return value.quantize(Decimal("0.01"))


def clean_amount(raw: Any, label: str) -> int:
    if not isinstance(raw, int) or isinstance(raw, bool) or raw <= 0:
        raise LedgerError(f"{label}: kwota musi być większa od zera.", status=422)
    if raw >= VALUE_LIMIT:
        raise LedgerError(f"{label}: kwota jest za duża.", status=422)
    return raw


def validate_plan(asset: LedgerAsset) -> None:
    """Spójność ewidencji: KŚT, metody i stawki, stan z Symfonii."""

    if asset.kind not in ASSET_KINDS:
        raise LedgerError("Rodzaj: środek trwały albo WNiP.", status=422)
    if asset.kind == "fixed":
        if not asset.kst or not _KST.fullmatch(asset.kst):
            raise LedgerError(
                "Podaj symbol KŚT środka (klasyfikacja 2016, np. 491).", status=422
            )
    else:
        asset.kst = None
    for label, method, rate in (
        ("Plan bilansowy", asset.balance_method, asset.balance_rate),
        ("Plan podatkowy", asset.tax_method, asset.tax_rate),
    ):
        if method not in depreciation.METHODS:
            raise LedgerError(f"{label}: nieznana metoda amortyzacji.", status=422)
        if not Decimal(rate).is_finite():
            raise LedgerError(f"{label}: niepoprawna stawka.", status=422)
        if method in ("linear", "degressive") and Decimal(rate) <= 0:
            raise LedgerError(
                f"{label}: metoda liniowa i degresywna potrzebują stawki.", status=422
            )
    if asset.kind == "intangible" and asset.tax_method == "degressive":
        raise LedgerError(
            "WNiP amortyzuje się podatkowo liniowo albo jednorazowo — metoda "
            "degresywna jest tylko dla środków trwałych (art. 16k ustawy o CIT).",
            status=422,
        )
    coefficient = Decimal(asset.coefficient)
    if not coefficient.is_finite() or not Decimal(1) <= coefficient <= Decimal(2):
        raise LedgerError("Współczynnik degresywnej: od 1,0 do 2,0.", status=422)
    if asset.opening_month is None:
        return
    if asset.opening_month < first_of(asset.accepted_on):
        raise LedgerError(
            "Stan z Symfonii nie może być sprzed miesiąca przyjęcia środka.", status=422
        )
    for label, accumulated, year_start, method in (
        (
            "Umorzenie bilansowe",
            asset.opening_balance,
            asset.opening_balance_year,
            asset.balance_method,
        ),
        (
            "Umorzenie podatkowe",
            asset.opening_tax,
            asset.opening_tax_year,
            asset.tax_method,
        ),
    ):
        if not 0 <= accumulated <= asset.initial_value:
            raise LedgerError(
                f"{label}: od zera do wartości początkowej "
                f"({money_pl(asset.initial_value)}).",
                status=422,
            )
        if year_start is not None and not 0 <= year_start <= accumulated:
            raise LedgerError(
                f"{label} na początek roku nie może być większe niż na koniec "
                "miesiąca stanu.",
                status=422,
            )
        if (
            method == "degressive"
            and asset.opening_month.month != 12
            and year_start is None
        ):
            raise LedgerError(
                f"{label}: dla metody degresywnej ze stanem nie na koniec grudnia "
                "podaj też umorzenie na początek roku (podstawa odpisów roku).",
                status=422,
            )


async def _equipment(
    db: AsyncSession, item_id: Optional[int], asset_id: Optional[int]
) -> Optional[int]:
    if item_id is None:
        return None
    if not await db.scalar(select(EquipmentItem.id).where(EquipmentItem.id == item_id)):
        raise LedgerError("Nie ma takiej pozycji w „Sprzęcie”.", status=422)
    taken = await db.scalar(
        select(LedgerAsset.inventory_number).where(
            LedgerAsset.equipment_item_id == item_id,
            LedgerAsset.id != (asset_id or 0),
        )
    )
    if taken is not None:
        raise LedgerError(
            f"Ta pozycja „Sprzętu” jest już przy środku {taken}.", status=409
        )
    return item_id


async def _cost_entry(db: AsyncSession, entry_id: Optional[int]) -> Optional[int]:
    if entry_id is None:
        return None
    source_type = await db.scalar(
        select(FinanceCostEntry.source_type).where(FinanceCostEntry.id == entry_id)
    )
    # Faktury osób zespołu (D2) nie są fakturami zakupu środków.
    if source_type is None or source_type == "payroll_invoice":
        raise LedgerError("Nie ma takiej faktury w kolejce kosztów.", status=422)
    return entry_id


def _opening_values(asset: LedgerAsset, raw: Optional[dict[str, Any]]) -> None:
    if not raw:
        asset.opening_month = None
        asset.opening_balance = asset.opening_tax = 0
        asset.opening_balance_year = asset.opening_tax_year = None
        return
    month = raw.get("month")
    if not isinstance(month, date):
        raise LedgerError("Stan z Symfonii: podaj miesiąc stanu.", status=422)
    asset.opening_month = first_of(month)

    def amount(key: str, required: bool) -> Optional[int]:
        value = raw.get(key)
        if value is None:
            return 0 if required else None
        if not isinstance(value, int) or isinstance(value, bool) or value < 0:
            raise LedgerError("Stan z Symfonii: niepoprawne umorzenie.", status=422)
        return value

    asset.opening_balance = amount("balance", True) or 0
    asset.opening_tax = amount("tax", True) or 0
    asset.opening_balance_year = amount("balance_year", False)
    asset.opening_tax_year = amount("tax_year", False)


async def _apply_values(
    db: AsyncSession,
    asset: LedgerAsset,
    values: dict[str, Any],
    plan: dict[str, PlanAccount],
    *,
    creating: bool,
) -> None:
    def given(key: str) -> bool:
        return creating or key in values

    if given("name"):
        asset.name = _text(values.get("name"), NAME_MAX)
        if not asset.name:
            raise LedgerError("Podaj nazwę środka.", status=422)
    if given("kind"):
        asset.kind = values.get("kind") or "fixed"
        if asset.kind not in ASSET_KINDS:
            raise LedgerError("Rodzaj: środek trwały albo WNiP.", status=422)
    if given("kst"):
        asset.kst = _text(values.get("kst"), KST_MAX).replace(" ", "") or None
    if given("note"):
        asset.note = _text(values.get("note"), NOTE_MAX)
    if given("accepted_on"):
        accepted = values.get("accepted_on")
        if not isinstance(accepted, date):
            raise LedgerError("Podaj datę przyjęcia środka.", status=422)
        asset.accepted_on = accepted
    if given("initial_value"):
        asset.initial_value = clean_amount(
            values.get("initial_value"), "Wartość początkowa"
        )
    defaults = DEFAULT_ACCOUNTS[asset.kind]
    if given("asset_account"):
        asset.asset_account = _plan_account(
            plan, values.get("asset_account") or defaults[0], "Konto środka"
        )
    if given("depreciation_account"):
        asset.depreciation_account = _plan_account(
            plan, values.get("depreciation_account") or defaults[1], "Konto umorzenia"
        )
    for side in ("balance", "tax"):
        if given(f"{side}_method"):
            setattr(asset, f"{side}_method", values.get(f"{side}_method") or "linear")
        if given(f"{side}_rate"):
            setattr(
                asset,
                f"{side}_rate",
                clean_rate(
                    values.get(f"{side}_rate"),
                    "Stawka bilansowa" if side == "balance" else "Stawka podatkowa",
                ),
            )
    if given("coefficient"):
        raw = values.get("coefficient")
        asset.coefficient = (
            depreciation.COEFFICIENT_DEFAULT
            if raw is None
            else clean_rate(raw, "Współczynnik")
        )
    if given("opening"):
        _opening_values(asset, values.get("opening"))
    if given("equipment_item_id"):
        asset.equipment_item_id = await _equipment(
            db, values.get("equipment_item_id"), asset.id
        )
    if given("inventory_number"):
        number = _text(values.get("inventory_number"), INVENTORY_MAX)
        if number:
            asset.inventory_number = number
        elif not creating:
            raise LedgerError("Podaj numer inwentarzowy.", status=422)
    validate_plan(asset)


async def _inventory_free(db: AsyncSession, asset: LedgerAsset) -> None:
    taken = await db.scalar(
        select(LedgerAsset.id).where(
            LedgerAsset.inventory_number == asset.inventory_number,
            LedgerAsset.id != (asset.id or 0),
        )
    )
    if taken is not None:
        raise LedgerError(
            f"Numer inwentarzowy {asset.inventory_number} jest już w ewidencji.",
            status=409,
        )


def _ensure_operations_after(
    asset: LedgerAsset, operations: list[LedgerAssetOperation]
) -> None:
    """Dokumenty środka (poza OT) po przyjęciu i po miesiącu stanu z Symfonii.

    Te same warunki co przy dodaniu dokumentu — zmiana daty przyjęcia albo
    miesiąca stanu nie może ich obejść (przegląd K6: LT lądował w księdze
    przed OT, a ulepszenie w okresie stanu liczyło się dwa razy).
    """

    for op in operations:
        if op.op_type == "OT":
            continue
        if op.op_date < asset.accepted_on:
            raise LedgerError(
                f"{op.number} ma datę {op.op_date:%d.%m.%Y} — przyjęcie środka nie "
                "może być późniejsze niż jego dokumenty.",
                status=422,
            )
        if (
            asset.opening_month is not None
            and first_of(op.op_date) <= asset.opening_month
        ):
            raise LedgerError(
                f"{op.number} ({op.op_date:%d.%m.%Y}) jest w miesiącu stanu z Symfonii "
                "albo przed nim — stan musi być wcześniejszy niż dokumenty środka "
                "w NEXUSIE.",
                status=422,
            )


def title_of(asset: LedgerAsset) -> str:
    return f"{asset.inventory_number} {asset.name}"[:OPERATION_TITLE_MAX]


# ── Zapis (bez commita; bramka lista „Księgowi” w trasie) ────────────────────


async def create_asset(
    db: AsyncSession,
    values: dict[str, Any],
    *,
    viewer: Viewer,
    settings: LedgerSettings,
) -> LedgerAsset:
    """Nowy środek (OT, chyba że ma stan z Symfonii) — bez commita."""

    await _lock_numbers(db)
    plan = await documents.load_plan(db)
    asset = LedgerAsset(created_by=viewer.user_id, status="in_use")
    asset.mpk = await clean_mpk(db, values.get("mpk"))
    await _apply_values(db, asset, values, plan, creating=True)
    if not asset.inventory_number:
        asset.inventory_number = await next_inventory(
            db, asset.kind, asset.accepted_on.year
        )
    await _inventory_free(db, asset)
    db.add(asset)
    await db.flush()
    operations: list[LedgerAssetOperation] = []
    if asset.opening_month is None:
        post = values.get("post_intake", True) is not False
        counter = None
        if post:
            counter = _plan_account(
                plan,
                values.get("counter_account") or settings.assets.intake_account,
                "Konto przeciwstawne OT",
            )
            await _require_open_month(db, asset.accepted_on, "Przyjęcie (OT)")
        intake = LedgerAssetOperation(
            asset_id=asset.id,
            op_type="OT",
            number=await next_operation_number(db, "OT", asset.accepted_on.year),
            op_date=asset.accepted_on,
            amount=asset.initial_value,
            counter_account=counter,
            cost_entry_id=await _cost_entry(db, values.get("cost_entry_id")),
            title=title_of(asset),
            created_by=viewer.user_id,
        )
        db.add(intake)
        operations.append(intake)
        await db.flush()
    await ensure_booked_unchanged(db, asset.id, asset, operations)
    await withdraw_drafts(db, viewer, operation_ids=[])
    return asset


async def _locked_asset(
    db: AsyncSession, asset_id: int
) -> tuple[LedgerAsset, list[LedgerAssetOperation]]:
    asset = await db.get(
        LedgerAsset, asset_id, with_for_update=True, populate_existing=True
    )
    if asset is None:
        raise LedgerError("Nie ma takiego środka.", status=404)
    operations = (await operations_of(db, [asset.id])).get(asset.id, [])
    return asset, operations


def _plan_snapshot(
    asset: LedgerAsset, intake: Optional[LedgerAssetOperation]
) -> tuple[Any, ...]:
    """Parametry planu i OT — po zatwierdzonym zapisie środka już się nie zmieniają."""

    return (
        asset.kind,
        asset.accepted_on,
        asset.initial_value,
        asset.asset_account,
        asset.depreciation_account,
        asset.mpk,
        asset.balance_method,
        Decimal(asset.balance_rate),
        asset.tax_method,
        Decimal(asset.tax_rate),
        Decimal(asset.coefficient),
        asset.opening_month,
        asset.opening_balance,
        asset.opening_tax,
        asset.opening_balance_year,
        asset.opening_tax_year,
        intake.counter_account if intake is not None else None,
        intake.cost_entry_id if intake is not None else None,
    )


async def update_asset(
    db: AsyncSession,
    asset_id: int,
    values: dict[str, Any],
    *,
    viewer: Viewer,
    settings: LedgerSettings,
) -> LedgerAsset:
    """Poprawka ewidencji (bez commita): opis zawsze, plan tylko bez zapisów."""

    asset, operations = await _locked_asset(db, asset_id)
    intake = next((op for op in operations if op.op_type == "OT"), None)
    before = _plan_snapshot(asset, intake)
    if values.get("mpk") is not None:
        mpk = await clean_mpk(db, values["mpk"])
        if mpk != asset.mpk and any(op.op_type == "MT" for op in operations):
            raise LedgerError(
                "Środek ma już zmianę MPK — kolejną zmianę zrób dokumentem MT.",
                status=409,
            )
        asset.mpk = mpk
    plan = await documents.load_plan(db)
    await _apply_values(db, asset, values, plan, creating=False)
    await _inventory_free(db, asset)
    _ensure_operations_after(asset, operations)
    if asset.opening_month is not None and intake is not None:
        raise LedgerError(
            "Środek przyjęty dokumentem OT nie dostaje stanu z Symfonii — usuń go "
            "i wprowadź jeszcze raz ze stanem.",
            status=409,
        )
    if intake is not None:
        intake.op_date = asset.accepted_on
        intake.amount = asset.initial_value
        if "post_intake" in values or "counter_account" in values:
            if values.get("post_intake", True) is False:
                intake.counter_account = None
            else:
                intake.counter_account = _plan_account(
                    plan,
                    values.get("counter_account")
                    or intake.counter_account
                    or settings.assets.intake_account,
                    "Konto przeciwstawne OT",
                )
        if "cost_entry_id" in values:
            intake.cost_entry_id = await _cost_entry(db, values.get("cost_entry_id"))
    changed = _plan_snapshot(asset, intake) != before
    if changed:
        reason = await booked_reason(db, asset, operations)
        if reason is not None:
            raise LedgerError(LOCKED.format(what=reason), status=409)
        if intake is not None and intake.counter_account is not None:
            await _require_open_month(db, asset.accepted_on, "Przyjęcie (OT)")
    docs = await operation_documents(db, [op.id for op in operations])
    retitled: list[int] = []
    for op in operations:
        doc = docs.get(op.id)
        if (doc is None or doc.status != "approved") and op.title != title_of(asset):
            op.title = title_of(asset)
            retitled.append(op.id)
    await db.flush()
    await ensure_booked_unchanged(db, asset.id, asset, operations)
    if changed:
        await withdraw_drafts(db, viewer, operation_ids=[op.id for op in operations])
    elif retitled:
        await withdraw_drafts(db, viewer, operation_ids=retitled, months=False)
    return asset


async def delete_asset(db: AsyncSession, asset_id: int, *, viewer: Viewer) -> None:
    asset, operations = await _locked_asset(db, asset_id)
    reason = await booked_reason(db, asset, operations)
    if reason is not None:
        raise LedgerError(
            f"Środek ma zatwierdzony zapis w księdze ({reason}) — nie usuwa się go. "
            "Zlikwiduj go albo sprzedaj dokumentem.",
            status=409,
        )
    await ensure_booked_unchanged(db, asset.id, None, [])
    await withdraw_drafts(db, viewer, operation_ids=[op.id for op in operations])
    await db.delete(asset)
    await db.flush()


async def add_operation(
    db: AsyncSession,
    asset_id: int,
    values: dict[str, Any],
    *,
    viewer: Viewer,
    settings: LedgerSettings,
) -> LedgerAssetOperation:
    """Ulepszenie, MT, likwidacja albo sprzedaż (bez commita)."""

    op_type = values.get("op_type")
    if op_type not in ADDED_TYPES:
        raise LedgerError("Dokument: ulepszenie, MT, LT albo sprzedaż.", status=422)
    asset, operations = await _locked_asset(db, asset_id)
    if asset.status != "in_use":
        raise LedgerError(
            f"Środek jest {STATUS_LABELS[asset.status]} — nie dodaje się do niego "
            "dokumentów.",
            status=409,
        )
    day = values.get("op_date")
    if not isinstance(day, date):
        raise LedgerError("Podaj datę dokumentu.", status=422)
    if day < asset.accepted_on:
        raise LedgerError("Dokument nie może być sprzed przyjęcia środka.", status=422)
    if asset.opening_month is not None and first_of(day) <= asset.opening_month:
        raise LedgerError(
            "Dokumenty do miesiąca stanu z Symfonii są w Symfonii — data musi być "
            f"po {_month_text(asset.opening_month)}.",
            status=422,
        )
    if operations and day < operations[-1].op_date:
        raise LedgerError(
            f"Ostatni dokument środka ({operations[-1].number}) ma datę "
            f"{operations[-1].op_date:%d.%m.%Y} — nowy nie może być wcześniejszy.",
            status=422,
        )
    await _lock_numbers(db)
    plan = await documents.load_plan(db)
    op = LedgerAssetOperation(
        asset_id=asset.id,
        op_type=op_type,
        number=await next_operation_number(db, op_type, day.year),
        op_date=day,
        note=_text(values.get("note"), OPERATION_NOTE_MAX),
        title=title_of(asset),
        created_by=viewer.user_id,
    )
    if op_type == "UL":
        op.amount = clean_amount(values.get("amount"), "Wartość ulepszenia")
        op.counter_account = _plan_account(
            plan,
            values.get("counter_account") or settings.assets.intake_account,
            "Konto przeciwstawne ulepszenia",
        )
        op.cost_entry_id = await _cost_entry(db, values.get("cost_entry_id"))
    elif op_type == "MT":
        target = await clean_mpk(db, values.get("mpk_to"))
        if target == asset.mpk:
            raise LedgerError(f"Środek ma już MPK {target}.", status=422)
        op.mpk_from, op.mpk_to = asset.mpk, target
        asset.mpk = target
    else:
        if values.get("amount") is not None:
            op.amount = clean_amount(values.get("amount"), "Cena sprzedaży")
        if op_type == "LT":
            op.amount = None
        asset.status = DISPOSALS[op_type]
        asset.disposed_on = day
    if op_type in POSTED_TYPES:
        await _require_open_month(db, day, OPERATION_LABELS[op_type])
    db.add(op)
    await db.flush()
    operations = [*operations, op]
    await ensure_booked_unchanged(db, asset.id, asset, operations)
    await withdraw_drafts(db, viewer, operation_ids=[])
    return op


async def delete_operation(db: AsyncSession, op_id: int, *, viewer: Viewer) -> None:
    """Usunięcie ostatniego dokumentu środka (bez commita), jeśli nie ma zapisu."""

    op = await db.get(LedgerAssetOperation, op_id)
    if op is None:
        raise LedgerError("Nie ma takiego dokumentu.", status=404)
    asset, operations = await _locked_asset(db, op.asset_id)
    if op.op_type == "OT":
        raise LedgerError(
            "Przyjęcia (OT) nie usuwa się osobno — usuń cały środek.", status=409
        )
    if operations[-1].id != op.id:
        raise LedgerError(
            f"Usuwa się tylko ostatni dokument środka ({operations[-1].number}).",
            status=409,
        )
    doc = (await operation_documents(db, [op.id])).get(op.id)
    if doc is not None and doc.status == "approved":
        raise LedgerError(
            f"{op.number} ma zapis nr {doc.journal_no} w dzienniku — zrób najpierw "
            "jego storno.",
            status=409,
        )
    if op.op_type == "MT":
        asset.mpk = op.mpk_from or asset.mpk
    elif op.op_type in DISPOSALS:
        asset.status, asset.disposed_on = "in_use", None
    remaining = [item for item in operations if item.id != op.id]
    await ensure_booked_unchanged(db, asset.id, asset, remaining)
    await withdraw_drafts(db, viewer, operation_ids=[op.id])
    await db.delete(op)
    await db.flush()
