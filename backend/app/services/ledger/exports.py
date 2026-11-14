"""Paczka księgi do Symfonii FK (K3b, zakładka „Do Symfonii”).

Do przełączenia (tryb roku „symfonia” albo „równolegle”) księgą urzędową
jest Symfonia. Dokumenty, które NEXUS robi sam, idą do niej plikiem, zamiast
być przepisywane: domyślnie PK cykliczne, RMK, rozliczenie kosztów na „5”
i PK z ręki. Faktury kosztowe (FVZ) mają własną paczkę E2, sprzedaż (FVS)
trafia do Symfonii z eBI24 do czasu wystawiania w NEXUSIE (E5), a bilans
otwarcia przychodzi z Symfonii — te rodzaje da się zaznaczyć, ale domyślnie
są poza paczką, bo Symfonia dostałaby je dwa razy. Storno ma rodzaj
dokumentu, który odwraca.

Paczka to zatwierdzone dokumenty okresu spoza aktywnych paczek (dokument
najwyżej w jednej — indeks unikalny częściowy), numer ``K/RRRR-MM/n``, plik
i jego SHA-256 w bazie: ponowne pobranie daje ten sam plik. „Zaksięgowana
w Symfonii” zamyka paczkę; „Anuluj” (tylko pobraną) zwalnia dokumenty do
następnej. Rok w trybie NEXUS paczek nie ma (409).

D2: dokumenty płacowe idą osobną paczką płacową, którą robi i widzi tylko
osoba z Płacami albo admin; zwykła paczka nigdy ich nie ma. Mieszana paczka
zabrałaby zwykłe dokumenty z widoku osoby bez Płac, a samej paczki ta osoba
by nie zobaczyła. Identyfikator kontrahenta w pliku to tylko NIP albo VAT UE
— PESEL z kartoteki nie wychodzi z NEXUSA.
"""

from __future__ import annotations

import hashlib
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Optional

from sqlalchemy import func, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.models.finance_ledger import FinanceCounterparty
from app.models.ledger import (
    LedgerDocument,
    LedgerExport,
    LedgerExportDocument,
    LedgerLine,
    LedgerPeriod,
    LedgerYear,
)
from app.models.user import User
from app.services.finance_ledger.costs import LedgerError
from app.services.ledger import engine, opening, sources
from app.services.ledger.documents import Viewer
from app.services.ledger.export_file import (
    DEFAULT_FORMAT,
    FORMATS,
    ExportLine,
    money,
)

#: Klucz blokady numeracji paczek (``pg_advisory_xact_lock``).
_NUMBER_LOCK = 702_0001

MANUAL = "manual"
OPENING = "opening"
OTHER = "other"
#: Rodzaje dokumentów w kolejności na ekranie.
KIND_LABELS: dict[str, str] = {
    MANUAL: "PK z ręki",
    sources.RECURRING: "PK cykliczne",
    sources.PREPAYMENTS: "RMK",
    sources.ALLOCATION: "Rozliczenie kosztów na „5”",
    sources.COSTS: "Faktury kosztowe (FVZ)",
    sources.SALES: "Faktury sprzedaży (FVS)",
    OPENING: "Bilans otwarcia",
    OTHER: "Inne źródła",
}
#: Rodzaje w paczce domyślnie — reszta trafia do Symfonii inną drogą.
DEFAULT_KINDS: frozenset[str] = frozenset(
    {MANUAL, sources.RECURRING, sources.PREPAYMENTS, sources.ALLOCATION}
)
KIND_NOTES: dict[str, str] = {
    sources.COSTS: "Mają własną paczkę E2 (Finanse → Księgowanie).",
    sources.SALES: "Do czasu wystawiania faktur w NEXUSIE trafiają do Symfonii z eBI24.",
    OPENING: "Bilans otwarcia przychodzi z Symfonii.",
}
_SOURCE_KINDS: dict[str, str] = {
    **{source_type: kind for kind, source_type in sources.SOURCE_TYPES.items()},
    opening.SOURCE_TYPE: OPENING,
}
#: Typy identyfikatora kontrahenta, które idą do pliku (PESEL nie).
_TAX_ID_TYPES = frozenset({"nip", "vat_eu"})
STATUS_LABELS: dict[str, str] = {
    "exported": "Pobrana — czeka na zaksięgowanie w Symfonii",
    "booked": "Zaksięgowana w Symfonii",
    "cancelled": "Anulowana",
}
NO_EXPORT = "Nie ma takiej paczki."
PAYROLL_ONLY = "Paczkę dokumentów płacowych robi osoba z Płacami albo administrator."
NEXUS_MODE = (
    "Rok {year} jest w trybie NEXUS — księgą urzędową jest NEXUS, paczek "
    "do Symfonii się nie robi."
)


def kind_of(doc_type: str, source_type: Optional[str]) -> str:
    """Rodzaj dokumentu w paczce (dla storna — rodzaj dokumentu odwracanego)."""

    if doc_type == "BO":
        return OPENING
    if source_type is None:
        return MANUAL
    return _SOURCE_KINDS.get(source_type, OTHER)


def chosen_kinds(raw: list[str]) -> frozenset[str]:
    chosen = frozenset(raw)
    unknown = sorted(chosen - set(KIND_LABELS))
    if unknown:
        raise LedgerError(
            f"Nieznany rodzaj dokumentów: {', '.join(unknown)}.", status=422
        )
    if not chosen:
        raise LedgerError("Zaznacz co najmniej jeden rodzaj dokumentów.", status=422)
    return chosen


@dataclass(frozen=True)
class Candidate:
    doc: LedgerDocument
    kind: str


def _document_scope(viewer: Viewer) -> list[Any]:
    return [] if viewer.payroll else [LedgerDocument.sensitivity.is_(None)]


def _payroll_condition(payroll: bool) -> Any:
    column = LedgerDocument.sensitivity
    return column.is_not(None) if payroll else column.is_(None)


def _export_scope(viewer: Viewer) -> list[Any]:
    return [] if viewer.payroll else [LedgerExport.has_payroll.is_(False)]


async def _period(
    db: AsyncSession, year: int, month: int
) -> tuple[Optional[LedgerYear], Optional[LedgerPeriod]]:
    year_row = await db.scalar(select(LedgerYear).where(LedgerYear.year == year))
    if year_row is None:
        return None, None
    period = await db.scalar(
        select(LedgerPeriod).where(
            LedgerPeriod.year_id == year_row.id, LedgerPeriod.month == month
        )
    )
    return year_row, period


async def _candidates(
    db: AsyncSession, period_id: int, *, payroll: bool
) -> list[Candidate]:
    """Zatwierdzone dokumenty okresu spoza aktywnych paczek, w kolejności dziennika.

    ``payroll`` wybiera dokumenty płacowe (D2) albo zwykłe — paczka nie miesza.
    """

    original = aliased(LedgerDocument)
    exported = (
        select(LedgerExportDocument.document_id)
        .where(
            LedgerExportDocument.active.is_(True),
            LedgerExportDocument.document_id == LedgerDocument.id,
        )
        .exists()
    )
    rows = await db.execute(
        select(LedgerDocument, original.doc_type, original.source_type)
        .outerjoin(original, original.id == LedgerDocument.reverses_id)
        .where(
            LedgerDocument.period_id == period_id,
            LedgerDocument.status == "approved",
            ~exported,
            _payroll_condition(payroll),
        )
        .order_by(LedgerDocument.journal_no)
    )
    out: list[Candidate] = []
    for doc, original_type, original_source in rows.all():
        if doc.reverses_id is not None and original_type is not None:
            kind = kind_of(original_type, original_source)
        else:
            kind = kind_of(doc.doc_type, doc.source_type)
        out.append(Candidate(doc=doc, kind=kind))
    return out


async def export_lines(
    db: AsyncSession, docs: list[LedgerDocument]
) -> list[ExportLine]:
    """Wiersze pliku: pozycje dokumentów w kolejności dziennika i numeru pozycji."""

    ids = [doc.id for doc in docs]
    lines = list(
        await db.scalars(
            select(LedgerLine)
            .where(LedgerLine.document_id.in_(ids or [0]))
            .order_by(LedgerLine.document_id, LedgerLine.line_no)
        )
    )
    by_doc: dict[int, list[LedgerLine]] = defaultdict(list)
    for line in lines:
        by_doc[line.document_id].append(line)
    party_ids = {doc.counterparty_id for doc in docs if doc.counterparty_id} | {
        line.counterparty_id for line in lines if line.counterparty_id
    }
    parties: dict[int, FinanceCounterparty] = {}
    if party_ids:
        rows = await db.scalars(
            select(FinanceCounterparty).where(FinanceCounterparty.id.in_(party_ids))
        )
        parties = {row.id: row for row in rows}
    reversed_ids = {doc.reverses_id for doc in docs if doc.reverses_id}
    originals: dict[int, str] = {}
    if reversed_ids:
        rows = await db.execute(
            select(LedgerDocument.id, LedgerDocument.number).where(
                LedgerDocument.id.in_(reversed_ids)
            )
        )
        originals = {row.id: row.number for row in rows.all()}
    out: list[ExportLine] = []
    for doc in docs:
        for line in by_doc[doc.id]:
            party = parties.get(line.counterparty_id or doc.counterparty_id or 0)
            tax_id = (
                party.id_value
                if party is not None and party.id_type in _TAX_ID_TYPES
                else None
            )
            out.append(
                ExportLine(
                    journal_no=int(doc.journal_no or 0),
                    number=doc.number,
                    doc_type=doc.doc_type,
                    doc_date=doc.doc_date,
                    op_date=doc.op_date,
                    document_description=doc.description,
                    line_no=line.line_no,
                    account=line.account,
                    debit=money(line.amount) if line.side == "debit" else None,
                    credit=money(line.amount) if line.side == "credit" else None,
                    description=line.description,
                    mpk=line.mpk,
                    counterparty=party.name if party else None,
                    tax_id=tax_id,
                    symfonia_id=party.symfonia_partner_id if party else None,
                    currency=line.currency,
                    amount_cur=money(line.amount_cur),
                    fx_rate=doc.fx_rate,
                    fx_date=doc.fx_date,
                    reverses=originals.get(doc.reverses_id or 0),
                    ksef_number=(doc.meta or {}).get("ksef_number"),
                )
            )
    return out


# ── Odczyt ───────────────────────────────────────────────────────────────────


def _iso(moment: Optional[datetime]) -> Optional[str]:
    return moment.isoformat() if moment else None


def _export_payload(export: LedgerExport, names: dict[int, str]) -> dict[str, Any]:
    fmt = FORMATS.get(export.file_format)
    return {
        "id": export.id,
        "number": export.number,
        "status": export.status,
        "status_label": STATUS_LABELS[export.status],
        "kinds": list(export.kinds or []),
        "kind_labels": [KIND_LABELS.get(kind, kind) for kind in export.kinds or []],
        "file_format": export.file_format,
        "file_format_label": fmt.label if fmt else export.file_format,
        "file_name": export.file_name,
        "file_sha256": export.file_sha256,
        "document_count": export.document_count,
        "debit_total": export.debit_total,
        "has_payroll": export.has_payroll,
        "created_at": _iso(export.created_at),
        "created_by": names.get(export.created_by or 0),
        "booked_at": _iso(export.booked_at),
        "booked_by": names.get(export.booked_by or 0),
        "cancelled_at": _iso(export.cancelled_at),
        "cancelled_by": names.get(export.cancelled_by or 0),
    }


async def _names(db: AsyncSession, exports: list[LedgerExport]) -> dict[int, str]:
    ids = {
        user_id
        for export in exports
        for user_id in (export.created_by, export.booked_by, export.cancelled_by)
        if user_id
    }
    if not ids:
        return {}
    rows = await db.execute(select(User.id, User.name).where(User.id.in_(ids)))
    return {row.id: row.name for row in rows.all()}


async def export_payload(db: AsyncSession, export: LedgerExport) -> dict[str, Any]:
    return _export_payload(export, await _names(db, [export]))


def _document_payload(candidate: Candidate) -> dict[str, Any]:
    doc = candidate.doc
    return {
        "id": doc.id,
        "journal_no": doc.journal_no,
        "number": doc.number,
        "doc_type": doc.doc_type,
        "op_date": doc.op_date.isoformat(),
        "description": doc.description,
        "debit_total": doc.debit_total,
        "kind": candidate.kind,
        "payroll": doc.sensitivity is not None,
    }


def _kind_counts(candidates: list[Candidate]) -> dict[str, list[int]]:
    counts: dict[str, list[int]] = {kind: [0, 0] for kind in KIND_LABELS}
    for candidate in candidates:
        item = counts[candidate.kind]
        item[0] += 1
        item[1] += candidate.doc.debit_total
    return counts


async def preview(
    db: AsyncSession, year: int, month: int, *, viewer: Viewer
) -> dict[str, Any]:
    """Co pójdzie do paczki: dokumenty per rodzaj, bufor okresu, paczki miesiąca."""

    year_row, period = await _period(db, year, month)
    base: dict[str, Any] = {
        "year": year,
        "month": month,
        "book_year": None,
        "period_status": None,
        "exportable": False,
        "refusal": f"Nie ma roku obrotowego {year} — załóż go w Ustawieniach Księgowości.",
        "kinds": [],
        "documents": [],
        "drafts": 0,
        "exports": [],
        "formats": [{"key": key, "label": fmt.label} for key, fmt in FORMATS.items()],
        "default_format": DEFAULT_FORMAT,
    }
    if year_row is None or period is None:
        return base
    nexus = year_row.mode == "nexus"
    candidates = await _candidates(db, period.id, payroll=False)
    payroll_candidates = (
        await _candidates(db, period.id, payroll=True) if viewer.payroll else []
    )
    counts = _kind_counts(candidates)
    payroll_counts = _kind_counts(payroll_candidates)
    drafts = await db.scalar(
        select(func.count())
        .select_from(LedgerDocument)
        .where(
            LedgerDocument.period_id == period.id,
            LedgerDocument.status == "draft",
            *_document_scope(viewer),
        )
    )
    exports = list(
        await db.scalars(
            select(LedgerExport)
            .where(LedgerExport.period_id == period.id, *_export_scope(viewer))
            .order_by(LedgerExport.id.desc())
        )
    )
    names = await _names(db, exports)
    return {
        **base,
        "book_year": {
            "mode": year_row.mode,
            "mode_label": engine.YEAR_MODE_LABELS[year_row.mode],
        },
        "period_status": period.status,
        "exportable": not nexus,
        "refusal": NEXUS_MODE.format(year=year) if nexus else None,
        "kinds": [
            {
                "key": kind,
                "label": label,
                "default": kind in DEFAULT_KINDS,
                "note": KIND_NOTES.get(kind),
                "count": counts[kind][0],
                "debit_total": counts[kind][1],
                "payroll_count": payroll_counts[kind][0],
                "payroll_debit_total": payroll_counts[kind][1],
            }
            for kind, label in KIND_LABELS.items()
            if kind != OTHER or counts[kind][0] or payroll_counts[kind][0]
        ],
        "documents": [
            _document_payload(item) for item in [*candidates, *payroll_candidates]
        ],
        "drafts": int(drafts or 0),
        "exports": [_export_payload(export, names) for export in exports],
    }


# ── Zapis ────────────────────────────────────────────────────────────────────


async def create(
    db: AsyncSession,
    year: int,
    month: int,
    kinds: list[str],
    file_format: str,
    *,
    payroll: bool = False,
    viewer: Viewer,
    now: datetime,
) -> LedgerExport:
    """Paczka z zatwierdzonych dokumentów okresu spoza paczek (bez commita).

    ``payroll`` = paczka płacowa (tylko dokumenty płacowe, D2).
    """

    if payroll and not viewer.payroll:
        raise LedgerError(PAYROLL_ONLY, status=403)
    fmt = FORMATS.get(file_format)
    if fmt is None:
        raise LedgerError("Nieznany format pliku.", status=422)
    chosen = chosen_kinds(kinds)
    year_row, period = await _period(db, year, month)
    if year_row is None or period is None:
        raise LedgerError(
            f"Nie ma roku obrotowego {year} — załóż go w Ustawieniach Księgowości.",
            status=409,
        )
    if year_row.mode == "nexus":
        raise LedgerError(NEXUS_MODE.format(year=year), status=409)
    # Jedna paczka naraz: numer bez dziur i dokument w jednej paczce (indeks
    # unikalny częściowy pilnuje tego także bez blokady).
    await db.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": _NUMBER_LOCK})
    picked = [
        item.doc
        for item in await _candidates(db, period.id, payroll=payroll)
        if item.kind in chosen
    ]
    if not picked:
        raise LedgerError(
            "Za ten miesiąc nie ma zatwierdzonych dokumentów spoza paczek "
            "w zaznaczonych rodzajach.",
            status=409,
        )
    content = fmt.render(await export_lines(db, picked))
    sequence = (
        await db.scalar(
            select(func.count())
            .select_from(LedgerExport)
            .where(LedgerExport.period_id == period.id)
        )
        or 0
    ) + 1
    export = LedgerExport(
        year_id=year_row.id,
        period_id=period.id,
        number=f"K/{year}-{month:02d}/{sequence}",
        status="exported",
        kinds=[kind for kind in KIND_LABELS if kind in chosen],
        file_format=fmt.key,
        file_name=(
            f"symfonia-ksiega-{year}-{month:02d}-{sequence}"
            f"{'-place' if payroll else ''}.{fmt.extension}"
        ),
        file_content=content,
        file_sha256=hashlib.sha256(content).hexdigest(),
        document_count=len(picked),
        debit_total=sum(doc.debit_total for doc in picked),
        has_payroll=payroll,
        created_by=viewer.user_id,
        created_at=now,
    )
    db.add(export)
    await db.flush()
    db.add_all(
        LedgerExportDocument(export_id=export.id, document_id=doc.id) for doc in picked
    )
    await db.flush()
    return export


async def _export(
    db: AsyncSession, export_id: int, viewer: Viewer, *, lock: bool = False
) -> LedgerExport:
    statement = select(LedgerExport).where(
        LedgerExport.id == export_id, *_export_scope(viewer)
    )
    if lock:
        statement = statement.with_for_update()
    export = await db.scalar(statement)
    if export is None:
        raise LedgerError(NO_EXPORT, status=404)
    return export


async def file_of(db: AsyncSession, export_id: int, *, viewer: Viewer) -> LedgerExport:
    return await _export(db, export_id, viewer)


async def book(
    db: AsyncSession, export_id: int, *, viewer: Viewer, now: datetime
) -> LedgerExport:
    """„Zaksięgowana w Symfonii” — paczka zamknięta, dokumenty zostają w niej."""

    export = await _export(db, export_id, viewer, lock=True)
    if export.status != "exported":
        raise LedgerError(
            f"Paczka {export.number} jest już „{STATUS_LABELS[export.status]}”.",
            status=409,
        )
    export.status = "booked"
    export.booked_by = viewer.user_id
    export.booked_at = now
    await db.flush()
    return export


async def cancel(
    db: AsyncSession, export_id: int, *, viewer: Viewer, now: datetime
) -> LedgerExport:
    """„Anuluj” pobraną paczkę — jej dokumenty wracają do następnej."""

    export = await _export(db, export_id, viewer, lock=True)
    if export.status != "exported":
        raise LedgerError(
            f"Paczka {export.number} jest „{STATUS_LABELS[export.status]}” — "
            "anulować można tylko pobraną.",
            status=409,
        )
    await db.execute(
        update(LedgerExportDocument)
        .where(LedgerExportDocument.export_id == export.id)
        .values(active=False)
    )
    export.status = "cancelled"
    export.cancelled_by = viewer.user_id
    export.cancelled_at = now
    await db.flush()
    return export
