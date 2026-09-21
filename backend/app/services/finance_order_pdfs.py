"""Finanse → Zamówienia PDF: pliki zamówień pogrupowane po miesiącu startu i kliencie.

Widok jest liczony PRZY ODCZYCIE z wierszy, na których PDF już leży — bez
osobnej tabeli i bez migracji. Dzięki temu obejmuje całą historię, a nowe
zamówienie z PDF-em pojawia się samo, bez żadnej ręcznej akcji. Druga kopia
(tabela „wykaz PDF-ów") rozjechałaby się z zamówieniami przy pierwszej
poprawce daty albo podmianie pliku.

Trzy źródła plików:

* ``client_orders.file_path`` — zamówienie okresowe albo linia zamówienia
  zbiorczego z WŁASNYM plikiem (np. BNP: PDF dograny do zamówienia konkretnej
  osoby). Okres = ``COALESCE(linia, grupa)``, jak w „Zmianach w zamówieniach";
* ``client_order_groups.file_path`` — PDF zamówienia zbiorczego (MD/kosztowe);
* aneks przedłużający umowę (``contract_amendments`` typu ``extension``)
  z dołączonym dokumentem.

Kopie PDF-u grupy w dokumentach kontraktu (``source_order_group_id``) NIE są
listowane — to duplikaty pliku grupy.

Nazwisko w nazwie pliku pochodzi z PRZYPISANIA zamówienia w NEXUSIE (kontrakt
→ kandydat), nigdy z treści PDF-a. PDF grupy dostaje nazwisko tylko wtedy,
gdy grupa obejmuje dokładnie jedną osobę — przy kilku osobach plik należy do
klienta, a nazwisko dopisuje Finanse ręcznie.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import PurePath
from typing import Literal, Optional

from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.candidate import Candidate
from app.models.client import Client
from app.models.client_order import ClientOrder, ClientOrderStatus
from app.models.client_order_group import ClientOrderGroup
from app.models.contract import Contract
from app.models.contract_amendment import ContractAmendment, ContractAmendmentType
from app.models.contract_document import ContractDocument
from app.services.client_identity import client_display_name_expression
from app.services.order_facts import effective_end_expr, effective_start_expr

PdfKind = Literal["order", "group", "amendment"]
EntryType = Literal["new", "extension", "amendment"]

OPEN_ENDED_LABEL = "bezterminowo"

# Znaki, których nie przyjmuje system plików Windows/macOS, plus sterujące.
_FORBIDDEN_CHARS = re.compile(r'[\\/:*?"<>|\x00-\x1f]')
_WHITESPACE = re.compile(r"\s+")


@dataclass(frozen=True)
class OrderPdfEntry:
    kind: PdfKind
    id: int
    client_id: int
    client_name: str
    original_name: str
    file_path: str
    content_type: Optional[str]
    consultant_name: Optional[str]
    consultant_lastname: Optional[str]
    start: date
    end: Optional[date]
    entry_type: EntryType
    status: Optional[str]
    order_number: Optional[str]
    uploaded_at: Optional[datetime]

    @property
    def download_name(self) -> str:
        return build_download_name(
            self.original_name, self.consultant_lastname, self.start, self.end
        )


def format_period(start: date, end: Optional[date]) -> str:
    """``DD.MM.RRRR-DD.MM.RRRR``; brak końca = ``DD.MM.RRRR-bezterminowo``."""

    tail = end.strftime("%d.%m.%Y") if end is not None else OPEN_ENDED_LABEL
    return f"{start.strftime('%d.%m.%Y')}-{tail}"


def _clean(part: str) -> str:
    return _FORBIDDEN_CHARS.sub("_", part).strip()


def build_download_name(
    original: Optional[str],
    lastname: Optional[str],
    start: date,
    end: Optional[date],
) -> str:
    """Oryginalna nazwa + ``_Nazwisko`` (gdy znane) + ``_okres``.

    ``zamowienie_alior.pdf`` → ``zamowienie_alior_Nowak_15.09.2026-31.12.2026.pdf``.
    Rozszerzenie zostaje; plik bez rozszerzenia dostaje ``.pdf``. Polskie
    litery zostają (nagłówek niesie je przez RFC 5987).
    """

    name = (
        _clean(PurePath((original or "").replace("\\", "/")).name) or "zamowienie.pdf"
    )
    path = PurePath(name)
    suffix = path.suffix if path.suffix and len(path.suffix) <= 6 else ""
    stem = path.stem if suffix else name
    stem = stem.strip(" .") or "zamowienie"
    parts = [stem]
    surname = _clean(_WHITESPACE.sub("_", (lastname or "").strip()))
    if surname:
        parts.append(surname)
    parts.append(format_period(start, end))
    return "_".join(parts) + (suffix or ".pdf")


def _value(raw: object) -> Optional[str]:
    if raw is None:
        return None
    return str(getattr(raw, "value", raw))


def _full_name(first: Optional[str], last: Optional[str]) -> Optional[str]:
    full = f"{first or ''} {last or ''}".strip()
    return full or None


def _parse_iso(raw: object) -> Optional[date]:
    if not isinstance(raw, str) or not raw:
        return None
    try:
        return date.fromisoformat(raw[:10])
    except ValueError:
        return None


def _client_visible():
    # Archiwalny klient zostaje — jego zamówienia są historią rozliczeń.
    # Znika wyłącznie klient usunięty albo techniczny (ukryty).
    return and_(Client.hidden.is_(False), Client.deleted_at.is_(None))


def month_bounds(year: int, month: int) -> tuple[date, date]:
    first = date(year, month, 1)
    nxt = date(year + (month == 12), month % 12 + 1, 1)
    return first, nxt


async def _order_entries(
    db: AsyncSession,
    *,
    window: Optional[tuple[date, date]],
    order_id: Optional[int],
) -> list[OrderPdfEntry]:
    eff_start = effective_start_expr()
    eff_end = effective_end_expr()
    stmt = (
        select(
            ClientOrder.id,
            ClientOrder.client_id,
            client_display_name_expression().label("client_name"),
            ClientOrder.filename,
            ClientOrder.file_path,
            ClientOrder.content_type,
            ClientOrder.file_uploaded_at,
            ClientOrder.status,
            ClientOrder.title,
            ClientOrderGroup.order_number,
            Contract.candidate_id,
            Candidate.name.label("first"),
            Candidate.lastname.label("last"),
            eff_start.label("eff_start"),
            eff_end.label("eff_end"),
        )
        .select_from(ClientOrder)
        .join(Client, Client.id == ClientOrder.client_id)
        .join(Contract, Contract.id == ClientOrder.contract_id)
        .outerjoin(Candidate, Candidate.id == Contract.candidate_id)
        .outerjoin(ClientOrderGroup, ClientOrderGroup.id == ClientOrder.order_group_id)
        .where(
            ClientOrder.file_path.is_not(None),
            ClientOrder.status != ClientOrderStatus.cancelled,
            eff_start.is_not(None),
            _client_visible(),
        )
    )
    if window is not None:
        stmt = stmt.where(eff_start >= window[0], eff_start < window[1])
    if order_id is not None:
        stmt = stmt.where(ClientOrder.id == order_id)
    rows = (await db.execute(stmt)).all()
    if not rows:
        return []

    # Przedłużenie = ta sama osoba miała u tego klienta zamówienie, które
    # zaczęło się wcześniej. Jedno zapytanie agregujące zamiast per wiersz.
    pairs = {
        (row.candidate_id, row.client_id)
        for row in rows
        if row.candidate_id is not None
    }
    first_start: dict[tuple[int, int], date] = {}
    if pairs:
        pair_rows = (
            await db.execute(
                select(
                    Contract.candidate_id,
                    ClientOrder.client_id,
                    func.min(eff_start),
                )
                .select_from(ClientOrder)
                .join(Contract, Contract.id == ClientOrder.contract_id)
                .outerjoin(
                    ClientOrderGroup, ClientOrderGroup.id == ClientOrder.order_group_id
                )
                .where(
                    ClientOrder.status != ClientOrderStatus.cancelled,
                    Contract.candidate_id.in_({p[0] for p in pairs}),
                    ClientOrder.client_id.in_({p[1] for p in pairs}),
                )
                .group_by(Contract.candidate_id, ClientOrder.client_id)
            )
        ).all()
        first_start = {(r[0], r[1]): r[2] for r in pair_rows if r[2] is not None}

    entries: list[OrderPdfEntry] = []
    for row in rows:
        earliest = first_start.get((row.candidate_id, row.client_id))
        is_extension = earliest is not None and earliest < row.eff_start
        entries.append(
            OrderPdfEntry(
                kind="order",
                id=row.id,
                client_id=row.client_id,
                client_name=row.client_name or "—",
                original_name=row.filename or "zamowienie.pdf",
                file_path=row.file_path,
                content_type=row.content_type,
                consultant_name=_full_name(row.first, row.last),
                consultant_lastname=(row.last or "").strip() or None,
                start=row.eff_start,
                end=row.eff_end,
                entry_type="extension" if is_extension else "new",
                status=_value(row.status),
                order_number=row.order_number or row.title,
                uploaded_at=row.file_uploaded_at,
            )
        )
    return entries


async def _group_entries(
    db: AsyncSession,
    *,
    window: Optional[tuple[date, date]],
    group_id: Optional[int],
) -> list[OrderPdfEntry]:
    stmt = (
        select(
            ClientOrderGroup.id,
            ClientOrderGroup.client_id,
            client_display_name_expression().label("client_name"),
            ClientOrderGroup.filename,
            ClientOrderGroup.file_path,
            ClientOrderGroup.content_type,
            ClientOrderGroup.file_uploaded_at,
            ClientOrderGroup.status,
            ClientOrderGroup.order_number,
            ClientOrderGroup.predecessor_group_id,
            ClientOrderGroup.start_date,
            ClientOrderGroup.end_date,
        )
        .join(Client, Client.id == ClientOrderGroup.client_id)
        .where(ClientOrderGroup.file_path.is_not(None), _client_visible())
    )
    if window is not None:
        stmt = stmt.where(
            ClientOrderGroup.start_date >= window[0],
            ClientOrderGroup.start_date < window[1],
        )
    if group_id is not None:
        stmt = stmt.where(ClientOrderGroup.id == group_id)
    rows = (await db.execute(stmt)).all()
    if not rows:
        return []

    # Osoby na zamówieniu: nazwisko dopisujemy tylko przy JEDNEJ osobie.
    people_rows = (
        await db.execute(
            select(
                ClientOrder.order_group_id,
                Contract.candidate_id,
                Candidate.name,
                Candidate.lastname,
            )
            .select_from(ClientOrder)
            .join(Contract, Contract.id == ClientOrder.contract_id)
            .outerjoin(Candidate, Candidate.id == Contract.candidate_id)
            .where(
                ClientOrder.order_group_id.in_([row.id for row in rows]),
                ClientOrder.status != ClientOrderStatus.cancelled,
            )
        )
    ).all()
    people: dict[int, dict[object, tuple[Optional[str], Optional[str]]]] = {}
    for gid, candidate_id, first, last in people_rows:
        key = candidate_id if candidate_id is not None else ("no-candidate", last)
        people.setdefault(gid, {})[key] = (first, last)

    entries: list[OrderPdfEntry] = []
    for row in rows:
        persons = list(people.get(row.id, {}).values())
        first, last = persons[0] if len(persons) == 1 else (None, None)
        entries.append(
            OrderPdfEntry(
                kind="group",
                id=row.id,
                client_id=row.client_id,
                client_name=row.client_name or "—",
                original_name=row.filename or "zamowienie.pdf",
                file_path=row.file_path,
                content_type=row.content_type,
                consultant_name=_full_name(first, last),
                consultant_lastname=(last or "").strip() or None,
                start=row.start_date,
                end=row.end_date,
                entry_type="extension" if row.predecessor_group_id else "new",
                status=row.status,
                order_number=row.order_number,
                uploaded_at=row.file_uploaded_at,
            )
        )
    return entries


def _amendment_start(old_values: object, effective: date) -> date:
    old_end = (
        _parse_iso(old_values.get("end_date")) if isinstance(old_values, dict) else None
    )
    return old_end + timedelta(days=1) if old_end is not None else effective


async def _amendment_entries(
    db: AsyncSession,
    *,
    window: Optional[tuple[date, date]],
    amendment_id: Optional[int],
) -> list[OrderPdfEntry]:
    stmt = (
        select(
            ContractAmendment.id,
            ContractAmendment.old_values,
            ContractAmendment.new_values,
            ContractAmendment.effective_date,
            Contract.client_id,
            client_display_name_expression().label("client_name"),
            ContractDocument.filename,
            ContractDocument.file_path,
            ContractDocument.content_type,
            ContractDocument.created_at.label("uploaded_at"),
            Candidate.name.label("first"),
            Candidate.lastname.label("last"),
        )
        .select_from(ContractAmendment)
        .join(ContractDocument, ContractDocument.id == ContractAmendment.document_id)
        .join(Contract, Contract.id == ContractAmendment.contract_id)
        .join(Client, Client.id == Contract.client_id)
        .outerjoin(Candidate, Candidate.id == Contract.candidate_id)
        .where(
            ContractAmendment.amendment_type == ContractAmendmentType.extension,
            ContractDocument.source_order_group_id.is_(None),
            _client_visible(),
        )
    )
    if amendment_id is not None:
        stmt = stmt.where(ContractAmendment.id == amendment_id)
    # Start aneksu liczy się z old_values (koniec umowy przed aneksem + 1 dzień),
    # więc okno miesiąca nakładamy po odczycie. Aneksów z dokumentem jest mało.
    rows = (await db.execute(stmt)).all()
    entries: list[OrderPdfEntry] = []
    for row in rows:
        start = _amendment_start(row.old_values, row.effective_date)
        if window is not None and not (window[0] <= start < window[1]):
            continue
        new_values = row.new_values if isinstance(row.new_values, dict) else {}
        entries.append(
            OrderPdfEntry(
                kind="amendment",
                id=row.id,
                client_id=row.client_id,
                client_name=row.client_name or "—",
                original_name=row.filename or "aneks.pdf",
                file_path=row.file_path,
                content_type=row.content_type,
                consultant_name=_full_name(row.first, row.last),
                consultant_lastname=(row.last or "").strip() or None,
                start=start,
                end=_parse_iso(new_values.get("end_date")),
                entry_type="amendment",
                status=None,
                order_number=None,
                uploaded_at=row.uploaded_at,
            )
        )
    return entries


def _sort_key(entry: OrderPdfEntry) -> tuple:
    return (entry.start, (entry.consultant_name or "~").lower(), entry.kind, entry.id)


async def collect_entries(
    db: AsyncSession, *, window: Optional[tuple[date, date]] = None
) -> list[OrderPdfEntry]:
    entries = [
        *await _order_entries(db, window=window, order_id=None),
        *await _group_entries(db, window=window, group_id=None),
        *await _amendment_entries(db, window=window, amendment_id=None),
    ]
    return sorted(entries, key=_sort_key)


async def find_entry(
    db: AsyncSession, kind: PdfKind, entry_id: int
) -> Optional[OrderPdfEntry]:
    """Jeden plik — liczony TĄ SAMĄ ścieżką co lista, więc nazwa się zgadza."""

    if kind == "order":
        found = await _order_entries(db, window=None, order_id=entry_id)
    elif kind == "group":
        found = await _group_entries(db, window=None, group_id=entry_id)
    else:
        found = await _amendment_entries(db, window=None, amendment_id=entry_id)
    return found[0] if found else None


def summarize_months(entries: list[OrderPdfEntry]) -> list[dict]:
    months: dict[str, dict] = {}
    for entry in entries:
        key = entry.start.strftime("%Y-%m")
        bucket = months.setdefault(key, {"month": key, "files": 0, "clients": set()})
        bucket["files"] += 1
        bucket["clients"].add(entry.client_id)
    return [
        {"month": key, "files": value["files"], "clients": len(value["clients"])}
        for key, value in sorted(months.items(), reverse=True)
    ]


def group_by_client(entries: list[OrderPdfEntry]) -> list[dict]:
    clients: dict[int, dict] = {}
    for entry in entries:
        bucket = clients.setdefault(
            entry.client_id,
            {
                "client_id": entry.client_id,
                "client_name": entry.client_name,
                "files": [],
            },
        )
        bucket["files"].append(entry)
    return sorted(clients.values(), key=lambda c: c["client_name"].lower())
