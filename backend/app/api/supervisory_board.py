"""Rada nadzorcza (R1): dokumenty korporacyjne i odpis KRS spółki.

Decyzje Artura z 16.11.2026 (``docs/claude/rada/``): sekcja „Rada”, Rada
nadzorcza czyta, admini (Zarząd) wgrywają i poprawiają. Odczyt: rola
``board`` albo admin (``require_roles`` przepuszcza admina) — nie
„Wyniki firmy” ani „Moduł Finanse”, bo protokoły Zarządu to nie są
podsumowania przychodu. Router stoi za bramką sekcji Insights (Rada ma tylko
ją), więc konto bez Insights nie dojdzie tu nawet z rolą.
"""

from __future__ import annotations

import hashlib
import logging
from datetime import date, datetime, timezone
from typing import Annotated, Any, Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import AdminUser, require_roles
from app.api.section_access import INSIGHTS_SECTION_DEPENDENCIES
from app.core.database import get_db
from app.core.http_headers import content_disposition
from app.core.scheduling import business_today
from app.models.ai_feature import AIFeatureKey
from decimal import Decimal

from app.models.board_document import BoardBudget, BoardBudgetLine, BoardDocument
from app.models.user import User, UserRole
from app.services import storage_service
from app.services import board_documents_schema as schema
from app.services.ai_quota import ai_feature
from app.services.board import krs as krs_service
from app.services.board import reader
from app.services.board import budget as budget_service
from app.services.board import summary as summary_service
from app.services import board_budget_schema as budget_schema
from app.services.board.notify import notify_new_entries

logger = logging.getLogger(__name__)

router = APIRouter(dependencies=INSIGHTS_SECTION_DEPENDENCIES)

BoardViewer = Annotated[User, Depends(require_roles(UserRole.board))]

MAX_UPLOAD_BYTES = 25 * 1024 * 1024
UPLOAD_TYPES: dict[str, str] = {
    ".pdf": "application/pdf",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".webp": "image/webp",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".doc": "application/msword",
}


# ── Pulpit (R2) ──────────────────────────────────────────────────────────────


@router.get("/summary")
async def get_summary(
    current_user: BoardViewer,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Sprzedaż, koszty i wynik z faktur (3 lata + rok bieżący), koncentracja
    klientów, zamówienia kończące się do końca roku, braki w KRS i skanach."""

    today = business_today()
    data = await summary_service.company_summary(db, today)
    snapshot = await krs_service.latest_snapshot(db, krs_service.company_krs())
    missing = (
        krs_service.missing_filings(krs_service.parse_odpis(snapshot.payload))
        if snapshot
        else []
    )
    data["krs_missing"] = [m for m in missing if m["year"] >= today.year - 4]
    data["documents_without_file"] = (
        await db.execute(
            select(func.count())
            .select_from(BoardDocument)
            .where(BoardDocument.file_path.is_(None))
        )
    ).scalar_one()
    return data


# ── Budżet (R3) ──────────────────────────────────────────────────────────────

BUDGET_MAX_PLN = Decimal("10000000000")


def _budget_year(year: int) -> int:
    today = business_today()
    if not today.year - 1 <= year <= today.year + 1:
        raise HTTPException(
            422, "Budżet prowadzimy dla roku bieżącego, poprzedniego i następnego."
        )
    return year


@router.get("/budget/{year}")
async def get_budget(
    year: int,
    current_user: BoardViewer,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Plan, wykonanie z faktur i prognoza z kontraktów (dwa scenariusze)."""

    return await budget_service.budget_view(db, _budget_year(year), business_today())


class BudgetMonth(BaseModel):
    month: int = Field(..., ge=1, le=12)
    sales: Optional[Decimal] = Field(None, ge=0, le=BUDGET_MAX_PLN)
    costs: Optional[Decimal] = Field(None, ge=0, le=BUDGET_MAX_PLN)


class BudgetPut(BaseModel):
    status: str = "draft"
    resolution_document_id: Optional[int] = None
    note: Optional[str] = Field(None, max_length=4000)
    months: list[BudgetMonth] = Field(default_factory=list, max_length=12)


@router.put("/budget/{year}")
async def put_budget(
    year: int,
    body: BudgetPut,
    current_user: AdminUser,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Zapis planu roku (admin). Kwoty w PLN netto; puste pole usuwa wiersz planu."""

    year = _budget_year(year)
    if body.status not in budget_schema.STATUSES:
        raise HTTPException(422, "Status budżetu: szkic albo przyjęty.")
    if len({m.month for m in body.months}) != len(body.months):
        raise HTTPException(422, "Każdy miesiąc może wystąpić raz.")
    if body.resolution_document_id is not None:
        doc = await db.get(BoardDocument, body.resolution_document_id)
        if doc is None or doc.category != "resolution_supervisory":
            raise HTTPException(422, "Wskaż uchwałę Rady z dokumentów.")
    budget = (
        await db.execute(select(BoardBudget).where(BoardBudget.year == year))
    ).scalar_one_or_none()
    if budget is None:
        budget = BoardBudget(year=year)
        db.add(budget)
    budget.status = body.status
    budget.resolution_document_id = body.resolution_document_id
    budget.note = (body.note or "").strip() or None
    budget.updated_by = current_user.id
    budget.updated_at = datetime.now(timezone.utc)
    await db.flush()
    existing = {
        (line.month, line.line): line
        for line in (
            await db.execute(
                select(BoardBudgetLine).where(BoardBudgetLine.budget_id == budget.id)
            )
        ).scalars()
    }
    for item in body.months:
        for line_name, amount in (("sales", item.sales), ("costs", item.costs)):
            row = existing.get((item.month, line_name))
            if amount is None:
                if row is not None:
                    await db.delete(row)
                continue
            if row is None:
                db.add(
                    BoardBudgetLine(
                        budget_id=budget.id,
                        month=item.month,
                        line=line_name,
                        amount=amount,
                    )
                )
            else:
                row.amount = amount
    await db.commit()
    return await budget_service.budget_view(db, year, business_today())


# ── KRS ──────────────────────────────────────────────────────────────────────


def _iso(value: Optional[date | datetime]) -> Optional[str]:
    return value.isoformat() if value else None


def krs_view(snapshot: Any) -> dict[str, Any]:
    summary = krs_service.parse_odpis(snapshot.payload)
    by_year: dict[int, dict[str, Optional[str]]] = {}
    for filing in summary.filings:
        row = by_year.setdefault(filing.year, {})
        row[filing.kind] = _iso(filing.filed_on) or "tak"
    entries = sorted(summary.entries, key=lambda e: e.number, reverse=True)
    last_statute = max(
        (c for c in summary.statute_changes if c.entry_no is not None),
        key=lambda c: c.entry_no or 0,
        default=None,
    )
    return {
        "krs": snapshot.krs,
        "fetched_at": _iso(snapshot.fetched_at),
        "checked_at": _iso(snapshot.checked_at),
        "name": summary.name,
        "capital": summary.capital,
        "shares": summary.shares,
        "entries_count": len(summary.entries),
        "recent_entries": [
            {
                "number": e.number,
                "date": _iso(e.day),
                "description": e.description,
                "by_court": e.court.upper() != "SYSTEM",
            }
            for e in entries[:12]
        ],
        "management": {
            "count": len(summary.management_functions),
            "functions": summary.management_functions,
        },
        "supervisory_count": summary.supervisory_count,
        "statute": {
            "changes": len(summary.statute_changes),
            "last_act_date": _iso(last_statute.act_date) if last_statute else None,
            "last_entry_no": last_statute.entry_no if last_statute else None,
            "last_text": last_statute.text if last_statute else None,
        },
        "filings": [
            {"year": year, **by_year[year]} for year in sorted(by_year, reverse=True)
        ],
        "missing_filings": krs_service.missing_filings(summary),
    }


@router.get("/krs")
async def get_krs(
    current_user: BoardViewer,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Ostatni zapisany odpis KRS spółki; ``snapshot = null`` przed pierwszym pobraniem."""

    snapshot = await krs_service.latest_snapshot(db, krs_service.company_krs())
    return {"snapshot": krs_view(snapshot) if snapshot else None}


@router.post("/krs/refresh")
async def refresh_krs(
    current_user: AdminUser,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Pobierz odpis teraz (admin) — ta sama ścieżka co pętla nocna."""

    try:
        payload = await krs_service.fetch_full_extract(krs_service.company_krs())
    except Exception as exc:  # noqa: BLE001
        logger.warning("board: odpis KRS niedostępny (%s)", type(exc).__name__)
        raise HTTPException(
            503, "API KRS nie odpowiada. Spróbuj za kilka minut."
        ) from exc
    result = await krs_service.store_extract(db, payload)
    if result.new_entries:
        await notify_new_entries(db, result.snapshot_id, result.new_entries)
    await db.commit()
    snapshot = await krs_service.latest_snapshot(db, krs_service.company_krs())
    return {
        "changed": result.changed,
        "new_entries": len(result.new_entries),
        "documents_created": result.documents_created,
        "snapshot": krs_view(snapshot) if snapshot else None,
    }


# ── Dokumenty ────────────────────────────────────────────────────────────────


def document_view(doc: BoardDocument) -> dict[str, Any]:
    return {
        "id": doc.id,
        "category": doc.category,
        "organ": doc.organ,
        "number": doc.number,
        "title": doc.title,
        "subject": doc.subject,
        "doc_date": _iso(doc.doc_date),
        "source": doc.source,
        "krs_entry_no": doc.krs_entry_no,
        "krs_entry_date": _iso(doc.krs_entry_date),
        "has_file": bool(doc.file_path),
        "file_name": doc.file_name,
        "file_size": doc.file_size,
        "extraction_status": doc.extraction_status,
        "extraction": doc.extraction or {},
        "updated_at": _iso(doc.updated_at),
    }


@router.get("/documents")
async def list_documents(
    current_user: BoardViewer,
    category: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    if category is not None and category not in schema.CATEGORIES:
        raise HTTPException(422, "Nieznany rodzaj dokumentu.")
    counts_rows = await db.execute(
        select(
            BoardDocument.category,
            func.count(),
            func.count().filter(BoardDocument.file_path.is_(None)),
        ).group_by(BoardDocument.category)
    )
    counts = {
        row[0]: {"total": row[1], "without_file": row[2]} for row in counts_rows.all()
    }
    query = select(BoardDocument).order_by(
        BoardDocument.doc_date.desc().nulls_last(),
        BoardDocument.krs_entry_date.desc().nulls_last(),
        BoardDocument.id.desc(),
    )
    if category is not None:
        query = query.where(BoardDocument.category == category)
    docs = (await db.execute(query.limit(500))).scalars().all()
    return {
        "categories": [
            {"key": key, **counts.get(key, {"total": 0, "without_file": 0})}
            for key in schema.CATEGORIES
        ],
        "items": [document_view(doc) for doc in docs],
    }


async def _document(db: AsyncSession, document_id: int) -> BoardDocument:
    doc = await db.get(BoardDocument, document_id)
    if doc is None:
        raise HTTPException(404, "Nie ma takiego dokumentu.")
    return doc


@router.get("/documents/{document_id}/file")
async def download_document(
    document_id: int,
    current_user: BoardViewer,
    db: AsyncSession = Depends(get_db),
) -> Response:
    doc = await _document(db, document_id)
    if not doc.file_path:
        raise HTTPException(404, "Ten dokument nie ma jeszcze pliku.")
    try:
        content = storage_service.read_board_document_file(doc.file_path)
    except FileNotFoundError as exc:
        raise HTTPException(404, "Pliku nie ma w magazynie.") from exc
    return Response(
        content=content,
        media_type=doc.content_type or "application/octet-stream",
        headers={
            "Content-Disposition": content_disposition(
                doc.file_name or "dokument", disposition="inline"
            ),
            "Cache-Control": "no-store",
        },
    )


async def _read_upload(file: UploadFile) -> tuple[str, bytes, str]:
    name = (file.filename or "").strip()
    suffix = name[name.rfind(".") :].lower() if "." in name else ""
    if suffix not in UPLOAD_TYPES:
        raise HTTPException(
            422, "Dozwolone pliki: PDF, zdjęcie (JPG, PNG, WEBP) albo Word."
        )
    content = await file.read(MAX_UPLOAD_BYTES + 1)
    if len(content) > MAX_UPLOAD_BYTES:
        raise HTTPException(
            413, f"Plik większy niż {MAX_UPLOAD_BYTES // (1024 * 1024)} MB."
        )
    if not content:
        raise HTTPException(422, "Plik jest pusty.")
    return name, content, UPLOAD_TYPES[suffix]


def _attach(doc: BoardDocument, name: str, content: bytes, mime: str) -> Optional[str]:
    """Zapisz plik przy dokumencie; zwraca ścieżkę starego pliku do usunięcia."""

    old = doc.file_path
    path, size = storage_service.save_board_document_file(name, content)
    doc.file_name = name[: schema.NAME_MAX]
    doc.file_path = path
    doc.content_type = mime
    doc.file_size = size
    doc.file_sha256 = hashlib.sha256(content).hexdigest()
    doc.extraction_status = "none"
    doc.extraction = {}
    return old


def _validate_fields(category: str, organ: Optional[str]) -> None:
    if category not in schema.CATEGORIES:
        raise HTTPException(422, "Nieznany rodzaj dokumentu.")
    if organ is not None and organ not in schema.ORGANS:
        raise HTTPException(422, "Nieznany organ spółki.")


@router.post("/documents", status_code=201)
async def create_document(
    current_user: AdminUser,
    category: str = Form(...),
    title: str = Form(..., min_length=1, max_length=schema.TITLE_MAX),
    organ: Optional[str] = Form(None),
    number: Optional[str] = Form(None, max_length=schema.NUMBER_MAX),
    subject: Optional[str] = Form(None, max_length=4000),
    doc_date: Optional[date] = Form(None),
    file: Optional[UploadFile] = File(None),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Nowy dokument (admin). Plik opcjonalny — można dołączyć później."""

    organ = organ or None
    _validate_fields(category, organ)
    doc = BoardDocument(
        category=category,
        organ=organ,
        number=(number or "").strip() or None,
        title=title.strip(),
        subject=(subject or "").strip() or None,
        doc_date=doc_date,
        source="upload",
        created_by=current_user.id,
        updated_by=current_user.id,
    )
    if file is not None and file.filename:
        name, content, mime = await _read_upload(file)
        _attach(doc, name, content, mime)
    db.add(doc)
    try:
        await db.commit()
    except Exception:
        # Plik bez wiersza w bazie nie zostaje na dysku.
        if doc.file_path:
            storage_service.delete_board_document_file(doc.file_path)
        raise
    await db.refresh(doc)
    return document_view(doc)


@router.post("/documents/{document_id}/file")
async def attach_file(
    document_id: int,
    current_user: AdminUser,
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Dołącz albo podmień skan (admin), także przy wierszu z wzmianki KRS."""

    doc = await _document(db, document_id)
    name, content, mime = await _read_upload(file)
    old = _attach(doc, name, content, mime)
    doc.updated_by = current_user.id
    doc.updated_at = datetime.now(timezone.utc)
    await db.commit()
    if old:
        storage_service.delete_board_document_file(old)
    await db.refresh(doc)
    return document_view(doc)


class DocumentPatch(BaseModel):
    category: Optional[str] = None
    organ: Optional[str] = None
    number: Optional[str] = Field(None, max_length=schema.NUMBER_MAX)
    title: Optional[str] = Field(None, min_length=1, max_length=schema.TITLE_MAX)
    subject: Optional[str] = Field(None, max_length=4000)
    doc_date: Optional[date] = None


@router.patch("/documents/{document_id}")
async def update_document(
    document_id: int,
    body: DocumentPatch,
    current_user: AdminUser,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    doc = await _document(db, document_id)
    data = body.model_dump(exclude_unset=True)
    category = data.get("category", doc.category)
    organ = data["organ"] or None if "organ" in data else doc.organ
    _validate_fields(category, organ)
    doc.category = category
    doc.organ = organ
    if "number" in data:
        doc.number = (data["number"] or "").strip() or None
    if data.get("title"):
        doc.title = data["title"].strip()
    if "subject" in data:
        doc.subject = (data["subject"] or "").strip() or None
    if "doc_date" in data:
        doc.doc_date = data["doc_date"]
    doc.updated_by = current_user.id
    doc.updated_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(doc)
    return document_view(doc)


@router.delete("/documents/{document_id}", status_code=204)
async def delete_document(
    document_id: int,
    current_user: AdminUser,
    db: AsyncSession = Depends(get_db),
) -> Response:
    """Usuń dokument wgrany ręcznie. Wiersz z KRS wraca co noc — tylko bez pliku."""

    doc = await _document(db, document_id)
    if doc.source == "krs":
        raise HTTPException(
            409,
            "Wiersz z wzmianki KRS wraca co noc. Możesz podmienić albo poprawić jego plik.",
        )
    path = doc.file_path
    await db.delete(doc)
    await db.commit()
    if path:
        storage_service.delete_board_document_file(path)
    return Response(status_code=204)


@router.post("/documents/{document_id}/read")
async def read_document(
    document_id: int,
    current_user: AdminUser,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Propozycja pól ze skanu (F51). Nie nadpisuje pól — admin przyjmuje ją sam."""

    doc = await _document(db, document_id)
    if not doc.file_path:
        raise HTTPException(409, "Najpierw dołącz plik.")
    if doc.content_type not in reader.SUPPORTED_MIME:
        raise HTTPException(422, "Model czyta PDF i zdjęcia; plik Worda opisz ręcznie.")
    try:
        content = storage_service.read_board_document_file(doc.file_path)
    except FileNotFoundError as exc:
        raise HTTPException(404, "Pliku nie ma w magazynie.") from exc
    mime = doc.content_type
    result = reader.ReadResult("failed")
    try:
        async with ai_feature(
            db, AIFeatureKey.board_document_read, user_id=current_user.id
        ):
            await db.commit()  # połączenie wraca do puli na czas modelu
            result = await reader.read_document(content, mime)
    except Exception as exc:  # noqa: BLE001 — AI to dodatek, nigdy bramka
        logger.warning(
            "board: odczyt dokumentu %s nieudany (%s)", document_id, type(exc).__name__
        )
        await db.rollback()
        result = reader.ReadResult("skipped")
    doc = await _document(db, document_id)
    doc.extraction_status = (
        result.status if result.status in schema.EXTRACTION_STATUSES else "failed"
    )
    doc.extraction = result.as_json()
    await db.commit()
    await db.refresh(doc)
    return document_view(doc)
