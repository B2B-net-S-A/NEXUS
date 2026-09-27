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

import os
import re
import tempfile
import unicodedata
import zipfile
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import PurePath
from typing import Collection, Literal, Optional

from sqlalchemy import and_, func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.candidate import Candidate
from app.models.client import Client
from app.models.client_order import ClientOrder, ClientOrderStatus
from app.models.client_order_group import GROUP_STATUS_CANCELLED, ClientOrderGroup
from app.models.contract import Contract
from app.models.contract_amendment import ContractAmendment, ContractAmendmentType
from app.models.contract_document import ContractDocument
from app.models.order_change_check import OrderPdfDownload
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
    order_ids: Optional[Collection[int]],
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
    if order_ids is not None:
        if not order_ids:
            return []
        stmt = stmt.where(ClientOrder.id.in_(sorted(order_ids)))
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
    group_ids: Optional[Collection[int]],
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
        .where(
            ClientOrderGroup.file_path.is_not(None),
            # Anulowane zamówienie MD/kosztowe nie jest do rozliczenia — do
            # 24.09.2026 wpadało do listy i ZIP-ów jako „Nowy" PDF. Lustro
            # warunku dla zamówień okresowych w ``_order_entries``; ten sam
            # filtr obejmuje ``find_entry`` i ``entries_for``.
            ClientOrderGroup.status != GROUP_STATUS_CANCELLED,
            _client_visible(),
        )
    )
    if window is not None:
        stmt = stmt.where(
            ClientOrderGroup.start_date >= window[0],
            ClientOrderGroup.start_date < window[1],
        )
    if group_ids is not None:
        if not group_ids:
            return []
        stmt = stmt.where(ClientOrderGroup.id.in_(sorted(group_ids)))
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
        *await _order_entries(db, window=window, order_ids=None),
        *await _group_entries(db, window=window, group_ids=None),
        *await _amendment_entries(db, window=window, amendment_id=None),
    ]
    return sorted(entries, key=_sort_key)


async def find_entry(
    db: AsyncSession, kind: PdfKind, entry_id: int
) -> Optional[OrderPdfEntry]:
    """Jeden plik — liczony TĄ SAMĄ ścieżką co lista, więc nazwa się zgadza."""

    if kind == "order":
        found = await _order_entries(db, window=None, order_ids=(entry_id,))
    elif kind == "group":
        found = await _group_entries(db, window=None, group_ids=(entry_id,))
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


async def entries_for(
    db: AsyncSession,
    *,
    order_ids: Collection[int] = (),
    group_ids: Collection[int] = (),
) -> tuple[dict[int, OrderPdfEntry], dict[int, OrderPdfEntry]]:
    """PDF-y wskazanych zamówień i grup — ta sama ścieżka co lista (nazwy,
    okres i miesiąc zgadzają się z „Zamówieniami PDF")."""

    orders = await _order_entries(db, window=None, order_ids=set(order_ids))
    groups = await _group_entries(db, window=None, group_ids=set(group_ids))
    return {e.id: e for e in orders}, {e.id: e for e in groups}


# ── ZIP i nazwy plików w archiwum ───────────────────────────────────────────

_ZIP_TYPE_LABELS: dict[str, str] = {
    "new": "Nowe",
    "extension": "Przedluzenie",
    "amendment": "Aneks",
}
_NON_SLUG = re.compile(r"[^A-Za-z0-9.-]+")


def ascii_slug(value: Optional[str], *, keep_dash: bool = True) -> str:
    """Bez polskich znaków, spacji i znaków spoza nazwy pliku.

    ``ł`` nie rozkłada się przez NFKD (to osobna litera), stąd jawna podmiana.
    ``/`` w numerze zamówienia (``OIT/0189/2026``) staje się myślnikiem.
    """

    text = (value or "").replace("ł", "l").replace("Ł", "L").replace("/", "-")
    folded = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    slug = _NON_SLUG.sub("_", folded).strip("_.-")
    slug = re.sub(r"_+", "_", slug)
    if not keep_dash:
        slug = slug.replace("-", "_")
    return slug


def _zip_date(value: Optional[date]) -> str:
    return value.strftime("%d.%m.%Y") if value is not None else OPEN_ENDED_LABEL


_ZIP_SUFFIX = re.compile(r"\.[a-z0-9]{1,5}")


def zip_member_name(entry: OrderPdfEntry) -> str:
    """``[Klient]_[NrZam]_[Nazwisko]_[Typ]_[DataOd]-[DataDo].<rozszerzenie>``.

    Brakujący człon dostaje zaślepkę zamiast znikać — nazwa ma zawsze tyle
    samo członów, więc pliki sortują się i czytają tak samo.
    """

    parts = [
        ascii_slug(entry.client_name) or "klient",
        ascii_slug(entry.order_number) or "bez-numeru",
        ascii_slug(entry.consultant_lastname) or "bez-nazwiska",
        _ZIP_TYPE_LABELS[entry.entry_type],
        f"{_zip_date(entry.start)}-{_zip_date(entry.end)}",
    ]
    # Runda 8 (R8-N6-3): rozszerzenie z oryginału, jak w pobraniu
    # pojedynczym — zamówienie w Wordzie z końcówką ``.pdf`` nie otwierało
    # się w archiwum. Nazwa w ZIP-ie jest ASCII, więc dziwna końcówka = ``.pdf``.
    suffix = PurePath((entry.original_name or "").replace("\\", "/")).suffix.lower()
    if not _ZIP_SUFFIX.fullmatch(suffix):
        suffix = ".pdf"
    return "_".join(parts) + suffix


def client_zip_name(client_name: str, year: int, month: int) -> str:
    return f"{ascii_slug(client_name) or 'klient'}_{year}-{month:02d}.zip"


def month_zip_name(year: int, month: int) -> str:
    return f"Zamowienia_{year}-{month:02d}.zip"


def build_zip_file(
    files: list[tuple[OrderPdfEntry, Optional[str]]],
    *,
    client_folders: bool,
) -> str:
    """Archiwum z plikami ``(wpis, ścieżka bezwzględna | None)`` — ścieżka pliku.

    ZIP powstaje w pliku tymczasowym, nie w pamięci (runda 6 audytu): wersja
    z ``BytesIO`` + ``getvalue()`` trzymała archiwum dwa razy naraz w jedynym
    procesie uvicorna, a miesiąc PDF-ów bywa duży. Wołający oddaje plik
    strumieniem i USUWA go po wysłaniu (``BackgroundTask``); przy błędzie
    budowy plik jest usuwany tutaj.

    Plik, którego nie ma na dysku, nie wywraca archiwum: jego nazwa trafia do
    ``BRAKUJACE_PLIKI.txt`` — pusty ZIP bez wyjaśnienia wyglądałby jak
    kompletny.
    """

    handle = tempfile.NamedTemporaryFile(
        prefix="zamowienia-", suffix=".zip", delete=False
    )
    try:
        with handle:
            _write_zip(handle, files, client_folders=client_folders)
    except BaseException:
        remove_file_quietly(handle.name)
        raise
    return handle.name


def remove_file_quietly(path: str) -> None:
    try:
        os.unlink(path)
    except FileNotFoundError:
        pass


def _write_zip(
    target,
    files: list[tuple[OrderPdfEntry, Optional[str]]],
    *,
    client_folders: bool,
) -> None:
    used: set[str] = set()
    missing: list[str] = []
    with zipfile.ZipFile(target, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for entry, path in files:
            name = zip_member_name(entry)
            if client_folders:
                name = f"{ascii_slug(entry.client_name) or 'klient'}/{name}"
            if path is None:
                missing.append(name)
                continue
            unique = name
            counter = 2
            while unique in used:
                stem, _, ext = name.rpartition(".")
                unique = f"{stem}_{counter}.{ext}"
                counter += 1
            used.add(unique)
            archive.write(path, arcname=unique)
        if missing:
            archive.writestr(
                "BRAKUJACE_PLIKI.txt",
                "Tych plików nie ma już na dysku — pobierz je ponownie z zamówienia:\n"
                + "\n".join(missing)
                + "\n",
            )


# ── Pobrania per osoba ──────────────────────────────────────────────────────


async def downloads_for_user(
    db: AsyncSession, user_id: int, entries: list[OrderPdfEntry]
) -> dict[tuple[str, int], datetime]:
    """Kiedy ta osoba pobrała te pliki. Podmieniony plik (inna ścieżka) = „Nowy"."""

    if not entries:
        return {}
    ids_by_kind: dict[str, set[int]] = {}
    for entry in entries:
        ids_by_kind.setdefault(entry.kind, set()).add(entry.id)
    rows = (
        await db.execute(
            select(
                OrderPdfDownload.file_kind,
                OrderPdfDownload.file_id,
                OrderPdfDownload.file_path,
                OrderPdfDownload.downloaded_at,
            ).where(
                OrderPdfDownload.user_id == user_id,
                OrderPdfDownload.file_kind.in_(sorted(ids_by_kind)),
                OrderPdfDownload.file_id.in_(
                    sorted({i for ids in ids_by_kind.values() for i in ids})
                ),
            )
        )
    ).all()
    current = {(e.kind, e.id): e.file_path for e in entries}
    return {
        (row.file_kind, row.file_id): row.downloaded_at
        for row in rows
        if current.get((row.file_kind, row.file_id)) == row.file_path
    }


async def record_downloads(
    db: AsyncSession, user_id: int, entries: list[OrderPdfEntry]
) -> None:
    if not entries:
        return
    unique = {(e.kind, e.id): e for e in entries}
    stmt = insert(OrderPdfDownload).values(
        [
            {
                "user_id": user_id,
                "file_kind": kind,
                "file_id": file_id,
                "file_path": entry.file_path,
            }
            for (kind, file_id), entry in unique.items()
        ]
    )
    await db.execute(
        stmt.on_conflict_do_update(
            index_elements=["user_id", "file_kind", "file_id"],
            set_={"file_path": stmt.excluded.file_path, "downloaded_at": func.now()},
        )
    )
