"""Archiwum dokumentów z eBI24 w Finansach (E5, 16.11.2026).

Eksport z eBI24 (tylko odczyt, przez przeglądarkę) daje metadane ok. 50 tys.
dokumentów i ich pliki: PDF/HTML dokumentów wgranych do eBI24 oraz JSON faktur
wystawionych w eBI24 (``archive/getDocument``). Skrypt
``scripts/pack_ebi24_archive.py`` pakuje je w paczki ZIP:

* ``metadane.json`` — lista wierszy metadanych (pola z ``KEEP_META``),
* ``pliki/<id eBI24>.<rozszerzenie>`` — plik dokumentu.

``import_package`` zapisuje pliki pod ``UPLOADS_DIR/ebi24_archive/<rok>/`` i
wiersze ``finance_archive_documents``; ten sam dokument drugi raz (to samo id
eBI24) jest pomijany, więc paczkę można wgrać ponownie po przerwie. Kwoty w
eBI24 są w groszach. Podgląd faktury z eBI24 (JSON) renderuje ``render_html``.
"""

from __future__ import annotations

import hashlib
import io
import json
import os
import re
import zipfile
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from html import escape
from pathlib import Path
from typing import Any, Optional

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.finance_archive import FinanceArchiveDocument
from app.services import storage_service
from app.services.finance_archive_schema import (
    AMOUNT_MAX,
    NAME_MAX,
    NUMBER_MAX,
    TEXT_MAX,
)

SUBDIR = "ebi24_archive"
MAX_PACKAGE_BYTES = 120 * 1024 * 1024
MAX_UNCOMPRESSED = 400 * 1024 * 1024
MAX_FILE_BYTES = 60 * 1024 * 1024
MAX_ENTRIES = 5_000
_SOURCE_ID = re.compile(r"^[0-9a-f]{24}$")
EXTENSIONS = {
    "json": "ebi",
    "pdf": "pdf",
    "html": "html",
    "xml": "xml",
    "jpg": "image",
    "png": "image",
}
MIME = {
    "pdf": "application/pdf",
    "html": "text/html; charset=utf-8",
    "xml": "application/xml",
    "image": "application/octet-stream",
    "other": "application/octet-stream",
}

#: Pola metadanych eBI24, które zostają w ``meta`` (reszta to stan obiegu eBI24).
KEEP_META = (
    "_id",
    "_bucketNumber",
    "_schemaName",
    "_title",
    "_documentFolderNamePath",
    "_accountancyStatus",
    "_partner",
    "_ksefReferenceNumber",
    "_ksefStatus",
    "_ksefDate",
    "_plnNettAmount",
    "_plnTaxAmount",
    "_plnGrossAmount",
    "_documentsMetaData",
    "_createdDate",
    "_archivedDate",
    "invoiceNumber",
    "invoiceType",
    "documentDate",
    "issuedDate",
    "dueDate",
    "transactionDate",
    "receiptDate",
    "currency",
    "nettAmount",
    "taxAmount",
    "grossAmount",
    "paid",
    "paidAmount",
    "paidDate",
    "paymentMethod",
    "bankAccountNumber",
    "taxRatesSummary",
    "externalData",
)

SALE_PREFIXES = ("INCOME", "EUROPEAN_INCOME", "VAT_EXPORT")
COST_PREFIXES = ("COST", "OTHER_EXPENSE")
KIND_LABELS = {"sale": "sprzedaż", "cost": "koszt", "other": "inny"}


class ArchiveError(ValueError):
    def __init__(self, message: str, status_code: int = 422) -> None:
        self.status_code = status_code
        super().__init__(message)


@dataclass
class ImportResult:
    created: int = 0
    skipped: int = 0
    errors: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "created": self.created,
            "skipped": self.skipped,
            "errors": self.errors[:50],
            "error_count": len(self.errors),
        }


# ── Mapowanie metadanych ────────────────────────────────────────────────────


def kind_of(schema_name: str) -> str:
    if schema_name.startswith(SALE_PREFIXES) or schema_name == "CORRECTION_NOTE":
        return "sale"
    if schema_name.startswith(COST_PREFIXES):
        return "cost"
    return "other"


def _date(raw: Any) -> Optional[date]:
    try:
        return date.fromisoformat(str(raw)[:10]) if raw else None
    except ValueError:
        return None


def _grosze(raw: Any) -> Optional[Decimal]:
    """Kwota eBI24 w groszach → złote (do grosza); śmieci = brak."""

    if raw in (None, "") or isinstance(raw, bool):
        return None
    try:
        value = (Decimal(str(raw)) / 100).quantize(Decimal("0.01"))
    except ArithmeticError:
        return None
    return value if abs(value) <= AMOUNT_MAX else None


def _text(raw: Any, limit: int) -> Optional[str]:
    value = " ".join(str(raw or "").split())[:limit]
    return value or None


def trim_meta(row: dict[str, Any]) -> dict[str, Any]:
    return {key: row[key] for key in KEEP_META if key in row}


def _fields(row: dict[str, Any]) -> dict[str, Any]:
    schema_name = str(row.get("_schemaName") or "FILE")[:64]
    partner = row.get("_partner") if isinstance(row.get("_partner"), dict) else {}
    number = row.get("invoiceNumber") or row.get("_title")
    issue = _date(row.get("issuedDate")) or _date(row.get("documentDate"))
    return {
        "bucket_number": row.get("_bucketNumber")
        if isinstance(row.get("_bucketNumber"), int)
        else None,
        "schema_name": schema_name,
        "kind": kind_of(schema_name),
        "invoice_number": _text(number, NUMBER_MAX),
        "title": _text(row.get("_title"), TEXT_MAX),
        "issue_date": issue,
        "document_date": _date(row.get("documentDate")),
        "due_date": _date(row.get("dueDate")),
        "partner_name": _text(partner.get("name"), NAME_MAX),
        "partner_id": _text(partner.get("officialId"), 64),
        "currency": _text(row.get("currency"), 3),
        "net_amount": _grosze(row.get("nettAmount")),
        "vat_amount": _grosze(row.get("taxAmount")),
        "gross_amount": _grosze(row.get("grossAmount")),
        "gross_pln": _grosze(row.get("_plnGrossAmount")),
        "paid": row.get("paid") if isinstance(row.get("paid"), bool) else None,
        "ksef_number": _text(row.get("_ksefReferenceNumber"), 64),
        "folder": _text(row.get("_documentFolderNamePath"), TEXT_MAX),
    }


def _file_name(row: dict[str, Any]) -> Optional[str]:
    meta = (row.get("_documentsMetaData") or {}).get("document") or {}
    return _text(meta.get("fileName"), TEXT_MAX) if isinstance(meta, dict) else None


# ── Import paczki ───────────────────────────────────────────────────────────


def _read_package(
    content: bytes,
) -> tuple[list[dict[str, Any]], dict[str, zipfile.ZipInfo], zipfile.ZipFile]:
    if len(content) > MAX_PACKAGE_BYTES:
        raise ArchiveError("Paczka jest za duża (najwyżej 120 MB).", 413)
    try:
        archive = zipfile.ZipFile(io.BytesIO(content))
    except zipfile.BadZipFile:
        raise ArchiveError("To nie jest paczka ZIP z eksportu eBI24.") from None
    entries = archive.infolist()
    if len(entries) > MAX_ENTRIES:
        raise ArchiveError("Paczka ma za dużo plików.")
    if sum(entry.file_size for entry in entries) > MAX_UNCOMPRESSED:
        raise ArchiveError("Paczka po rozpakowaniu jest za duża.")
    try:
        rows = json.loads(archive.read("metadane.json"))
    except (KeyError, ValueError):
        raise ArchiveError("Paczka nie ma czytelnego pliku metadane.json.") from None
    if not isinstance(rows, list):
        raise ArchiveError("metadane.json: oczekiwana lista dokumentów.")
    files: dict[str, zipfile.ZipInfo] = {}
    for entry in entries:
        name = entry.filename
        if not name.startswith("pliki/") or entry.is_dir():
            continue
        stem, _, ext = name[len("pliki/") :].rpartition(".")
        if _SOURCE_ID.match(stem) and ext.lower() in EXTENSIONS:
            files[stem] = entry
    return rows, files, archive


def _store(year: str, source_id: str, ext: str, data: bytes) -> str:
    relative = f"{SUBDIR}/{year}/{source_id}.{ext}"
    target = Path(storage_service.STORAGE_ROOT) / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(f"{target.name}.part")
    temporary.write_bytes(data)
    os.replace(temporary, target)
    return relative


async def import_package(
    db: AsyncSession, content: bytes, *, actor_id: int
) -> ImportResult:
    """Zapisuje dokumenty z paczki (bez commita); istniejące id eBI24 pomija."""

    rows, files, archive = _read_package(content)
    wanted = [
        str(row.get("_id"))
        for row in rows
        if isinstance(row, dict) and _SOURCE_ID.match(str(row.get("_id") or ""))
    ]
    existing = set(
        await db.scalars(
            select(FinanceArchiveDocument.source_id).where(
                FinanceArchiveDocument.source == "ebi24",
                FinanceArchiveDocument.source_id.in_(wanted),
            )
        )
    )
    result = ImportResult()
    for row in rows:
        source_id = str(row.get("_id") or "") if isinstance(row, dict) else ""
        if not _SOURCE_ID.match(source_id):
            result.errors.append("wiersz bez poprawnego id eBI24")
            continue
        if source_id in existing:
            result.skipped += 1
            continue
        entry = files.get(source_id)
        if entry is None:
            result.errors.append(f"{source_id}: brak pliku w paczce")
            continue
        if entry.file_size > MAX_FILE_BYTES:
            result.errors.append(f"{source_id}: plik większy niż 60 MB")
            continue
        data = archive.read(entry)
        ext = entry.filename.rpartition(".")[2].lower()
        fields = _fields(row)
        year = str(fields["issue_date"].year) if fields["issue_date"] else "brak-daty"
        relative = _store(year, source_id, ext, data)
        db.add(
            FinanceArchiveDocument(
                source="ebi24",
                source_id=source_id,
                file_type=EXTENSIONS[ext],
                file_name=_file_name(row),
                file_path=relative,
                file_size=len(data),
                file_sha256=hashlib.sha256(data).hexdigest(),
                meta=trim_meta(row),
                imported_by=actor_id,
                **fields,
            )
        )
        existing.add(source_id)
        result.created += 1
    await db.flush()
    return result


# ── Odczyt ──────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class Filters:
    q: Optional[str] = None
    kind: Optional[str] = None
    year: Optional[int] = None
    month: Optional[int] = None


def _query(filters: Filters):
    query = select(FinanceArchiveDocument)
    if filters.kind:
        query = query.where(FinanceArchiveDocument.kind == filters.kind)
    if filters.year:
        start = date(filters.year, filters.month or 1, 1)
        if filters.month:
            end = date(filters.year + (filters.month == 12), filters.month % 12 + 1, 1)
        else:
            end = date(filters.year + 1, 1, 1)
        query = query.where(
            FinanceArchiveDocument.issue_date >= start,
            FinanceArchiveDocument.issue_date < end,
        )
    term = " ".join((filters.q or "").split())
    if term:
        like = f"%{term.lower()}%"
        digits = "".join(ch for ch in term if ch.isdigit())
        conditions = [
            func.lower(FinanceArchiveDocument.invoice_number).like(like),
            func.lower(FinanceArchiveDocument.partner_name).like(like),
            func.lower(FinanceArchiveDocument.ksef_number).like(like),
        ]
        if len(digits) >= 5:
            conditions.append(FinanceArchiveDocument.partner_id.like(f"%{digits}%"))
        query = query.where(or_(*conditions))
    return query


def _amount(value: Optional[Decimal]) -> Optional[str]:
    return f"{value:.2f}" if value is not None else None


def row_payload(doc: FinanceArchiveDocument) -> dict[str, Any]:
    return {
        "id": doc.id,
        "source_id": doc.source_id,
        "kind": doc.kind,
        "kind_label": KIND_LABELS[doc.kind],
        "schema_name": doc.schema_name,
        "invoice_number": doc.invoice_number,
        "issue_date": doc.issue_date.isoformat() if doc.issue_date else None,
        "due_date": doc.due_date.isoformat() if doc.due_date else None,
        "partner_name": doc.partner_name,
        "partner_id": doc.partner_id,
        "currency": doc.currency,
        "net": _amount(doc.net_amount),
        "gross": _amount(doc.gross_amount),
        "gross_pln": _amount(doc.gross_pln),
        "paid": doc.paid,
        "ksef_number": doc.ksef_number,
        "folder": doc.folder,
        "file_type": doc.file_type,
        "file_name": doc.file_name,
        "file_size": doc.file_size,
    }


async def listing(
    db: AsyncSession, filters: Filters, *, limit: int, offset: int
) -> dict[str, Any]:
    base = _query(filters)
    total = await db.scalar(select(func.count()).select_from(base.subquery()))
    rows = await db.scalars(
        base.order_by(
            FinanceArchiveDocument.issue_date.desc().nulls_last(),
            FinanceArchiveDocument.bucket_number.desc().nulls_last(),
            FinanceArchiveDocument.id.desc(),
        )
        .limit(limit)
        .offset(offset)
    )
    return {"total": int(total or 0), "documents": [row_payload(doc) for doc in rows]}


async def summary(db: AsyncSession) -> dict[str, Any]:
    year = func.extract("year", FinanceArchiveDocument.issue_date)
    rows = await db.execute(
        select(year.label("year"), FinanceArchiveDocument.kind, func.count())
        .group_by(year, FinanceArchiveDocument.kind)
        .order_by(year.desc())
    )
    years: dict[str, dict[str, int]] = {}
    for value, kind, count in rows.all():
        key = str(int(value)) if value is not None else "brak daty"
        years.setdefault(key, {"sale": 0, "cost": 0, "other": 0})[kind] = int(count)
    total = sum(sum(entry.values()) for entry in years.values())
    last = await db.scalar(select(func.max(FinanceArchiveDocument.imported_at)))
    return {
        "total": total,
        "years": [{"year": key, **value} for key, value in years.items()],
        "last_import_at": last.isoformat() if last else None,
    }


def read_path(relative: str) -> bytes:
    """Plik archiwum po ``file_path`` dokumentu; ścieżka spoza katalogu archiwum — brak pliku."""

    root = Path(storage_service.STORAGE_ROOT).resolve()
    path = (root / relative).resolve()
    try:
        path.relative_to(root / SUBDIR)
    except ValueError:
        raise FileNotFoundError("poza katalogiem archiwum") from None
    return path.read_bytes()


def read_file(doc: FinanceArchiveDocument) -> bytes:
    return read_path(doc.file_path)


# ── Podgląd faktury wystawionej w eBI24 (JSON) ──────────────────────────────


def _money(raw: Any, currency: str) -> str:
    value = _grosze(raw)
    if value is None:
        return "—"
    text_ = f"{value:,.2f}".replace(",", " ").replace(".", ",")
    return f"{text_} {escape(currency)}"


def _party(raw: Any) -> str:
    party = raw if isinstance(raw, dict) else {}
    lines = [
        party.get("name"),
        party.get("address"),
        " ".join(str(x) for x in (party.get("postalCode"), party.get("city")) if x),
        party.get("country"),
        f"{party.get('officialIdType') or 'NIP'}: {party.get('officialId')}"
        if party.get("officialId")
        else None,
    ]
    return "<br>".join(escape(str(line)) for line in lines if line)


def render_html(doc: FinanceArchiveDocument, data: dict[str, Any]) -> str:
    """Czytelny podgląd faktury z eBI24 (dane z archiwum, nie nowy dokument)."""

    currency = str(data.get("currency") or doc.currency or "PLN")
    items = data.get("items") if isinstance(data.get("items"), list) else []
    rows = "".join(
        "<tr>"
        f"<td>{index}</td><td>{escape(str(item.get('name') or ''))}</td>"
        f"<td class='r'>{escape(str(item.get('amountOfUnits') or ''))} "
        f"{escape(str(item.get('amountUnitType') or ''))}</td>"
        f"<td class='r'>{_money(item.get('unitNettPrice'), currency)}</td>"
        f"<td class='r'>{escape(str(item.get('taxRate') or ''))}</td>"
        f"<td class='r'>{_money(item.get('nettAmount'), currency)}</td>"
        f"<td class='r'>{_money(item.get('grossAmount'), currency)}</td>"
        "</tr>"
        for index, item in enumerate(items, start=1)
        if isinstance(item, dict)
    )
    dates = [
        ("Data wystawienia", data.get("issuedDate")),
        ("Data sprzedaży", data.get("transactionDate")),
        ("Termin płatności", data.get("dueDate")),
    ]
    date_rows = "".join(
        f"<div><b>{label}:</b> {escape(str(value)[:10])}</div>"
        for label, value in dates
        if value
    )
    footer = (
        (data.get("footer") or {}).get("content")
        if isinstance(data.get("footer"), dict)
        else None
    )
    ksef = (
        f"<div><b>Numer KSeF:</b> {escape(doc.ksef_number)}</div>"
        if doc.ksef_number
        else ""
    )
    account = (
        f"<div><b>Rachunek:</b> {escape(str(data.get('bankAccountNumber')))}</div>"
        if data.get("bankAccountNumber")
        else ""
    )
    return f"""<!doctype html><html lang="pl"><head><meta charset="utf-8">
<title>{escape(str(data.get("invoiceNumber") or doc.invoice_number or "Dokument eBI24"))}</title>
<style>
body{{font:13px/1.45 system-ui,sans-serif;color:#1a1a1a;max-width:900px;margin:24px auto;padding:0 16px}}
h1{{font-size:20px;margin:0 0 4px}} .note{{color:#666;font-size:12px;margin-bottom:16px}}
.cols{{display:grid;grid-template-columns:1fr 1fr;gap:24px;margin:16px 0}}
table{{width:100%;border-collapse:collapse;margin-top:12px}} th,td{{border-bottom:1px solid #ddd;padding:6px 4px;text-align:left;vertical-align:top}}
.r{{text-align:right;white-space:nowrap}} .sum{{margin-top:12px;text-align:right;font-size:14px}}
</style></head><body>
<h1>Faktura {escape(str(data.get("invoiceNumber") or doc.invoice_number or ""))}</h1>
<div class="note">Podgląd z archiwum eBI24 (dane dokumentu z eksportu, 16.11.2026). Oryginał faktury: KSeF albo PDF wysłany nabywcy.</div>
{date_rows}{ksef}
<div class="cols"><div><b>Sprzedawca</b><br>{_party(data.get("vendor"))}</div><div><b>Nabywca</b><br>{_party(data.get("customer"))}</div></div>
<table><thead><tr><th>Lp.</th><th>Nazwa</th><th class="r">Ilość</th><th class="r">Cena netto</th><th class="r">VAT</th><th class="r">Netto</th><th class="r">Brutto</th></tr></thead>
<tbody>{rows}</tbody></table>
<div class="sum">Netto {_money(data.get("nettAmount"), currency)} · VAT {_money(data.get("taxAmount"), currency)} · <b>Brutto {_money(data.get("grossAmount"), currency)}</b></div>
{account}
{f"<p>{escape(str(footer))}</p>" if footer else ""}
</body></html>"""


__all__ = [
    "ArchiveError",
    "Filters",
    "ImportResult",
    "import_package",
    "kind_of",
    "listing",
    "read_file",
    "read_path",
    "render_html",
    "summary",
    "trim_meta",
]
