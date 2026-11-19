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
from datetime import date, datetime, timedelta, timezone
from typing import Annotated, Any, Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import AdminUser, require_roles
from app.api.section_access import (
    INSIGHTS_SECTION_DEPENDENCIES,
    require_section_access_any_read,
)
from app.core.database import get_db
from app.core.http_headers import content_disposition
from app.core.scheduling import business_today
from app.models.ai_feature import AIFeatureKey
from decimal import Decimal

from app.models.board_document import (
    BoardBudget,
    BoardBudgetLine,
    BoardCashPosition,
    BoardDocument,
    BoardReport,
    BoardMeeting,
    BoardVote,
    BoardVoteBallot,
)
from app.models.finance_archive import FinanceArchiveDocument
from app.models.user import User, UserRole
from app.services import storage_service
from app.services import board_documents_schema as schema
from app.services.ai_quota import ai_feature
from app.services.board import krs as krs_service
from app.services.board import reader
from app.services.board import budget as budget_service
from app.services.board import financials
from app.services.board import meetings as meetings_service
from app.services.board import votes as votes_service
from app.services import board_votes_schema as votes_schema
from app.services import board_meetings_schema as meetings_schema
from app.services.board.statements import StatementError
from app.services.board import summary as summary_service
from app.services.board import outlook as outlook_service
from app.services.board import people as people_service
from app.services.board import reports as reports_service
from app.services import board_reports_schema as reports_schema
from app.analytics.periods import PeriodError, resolve_period
from app.services.insights_team_signals import previous_matching_window
from app.services import board_budget_schema as budget_schema
from app.services.board.notify import notify_new_entries
from app.services.section_permissions import ProductSection

logger = logging.getLogger(__name__)

router = APIRouter(dependencies=INSIGHTS_SECTION_DEPENDENCIES)
# Oddanie głosu (R6) to zapis członka Rady, który w sekcji Insights ma tylko
# odczyt: bramka sekcji na poziomie „odczyt”, a uprawnienie do głosu (członek
# ze składu uchwały) sprawdza trasa. Konto bez Insights nie dojdzie i tu.
ballot_router = APIRouter(
    dependencies=[Depends(require_section_access_any_read(ProductSection.insights))]
)

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


# ── Pulpit: gotówka, zdolność kredytowa, wycena, symulacja roku (R7) ────────


@router.get("/outlook")
async def get_outlook(
    current_user: BoardViewer,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Kafle pulpitu: gotówka, zdolność kredytowa, wycena, symulacja roku."""

    return await outlook_service.outlook(db, business_today())


def cash_view(row: BoardCashPosition) -> dict[str, Any]:
    return {
        "id": row.id,
        "as_of": row.as_of.isoformat(),
        "amount": float(row.amount),
        "note": row.note,
        "updated_at": _iso(row.updated_at),
    }


@router.get("/cash")
async def list_cash(
    current_user: BoardViewer,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    rows = (
        await db.execute(
            select(BoardCashPosition).order_by(BoardCashPosition.as_of.desc()).limit(24)
        )
    ).scalars()
    return {"items": [cash_view(row) for row in rows]}


class CashBody(BaseModel):
    as_of: date
    amount: Decimal = Field(ge=Decimal("-1000000000"), le=Decimal("10000000000"))
    note: Optional[str] = Field(default=None, max_length=reports_schema.NOTE_MAX)


@router.put("/cash")
async def put_cash(
    body: CashBody,
    current_user: AdminUser,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Stan gotówki na dzień — jeden wpis na dzień, ponowny zapis go poprawia."""

    if body.as_of > business_today():
        raise HTTPException(422, "Stan gotówki podaje się na dzień, który minął.")
    row = (
        await db.execute(
            select(BoardCashPosition).where(BoardCashPosition.as_of == body.as_of)
        )
    ).scalar_one_or_none()
    if row is None:
        row = BoardCashPosition(as_of=body.as_of)
        db.add(row)
    row.amount = body.amount
    row.note = (body.note or "").strip() or None
    row.updated_by = current_user.id
    row.updated_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(row)
    return cash_view(row)


@router.delete("/cash/{cash_id}", status_code=204)
async def delete_cash(
    cash_id: int,
    current_user: AdminUser,
    db: AsyncSession = Depends(get_db),
) -> Response:
    row = await db.get(BoardCashPosition, cash_id)
    if row is None:
        raise HTTPException(404, "Nie ma takiego wpisu.")
    await db.delete(row)
    await db.commit()
    return Response(status_code=204)


# ── Raporty PDF i archiwum (R7) ──────────────────────────────────────────────


def report_view(row: BoardReport) -> dict[str, Any]:
    return {
        "id": row.id,
        "kind": row.kind,
        "year": row.year,
        "month": row.month,
        "title": reports_service.title(row.kind, row.year, row.month),
        "file_name": reports_service.file_name(row.kind, row.year, row.month),
        "file_size": row.file_size,
        "created_at": _iso(row.created_at),
    }


@router.get("/reports")
async def list_reports(
    current_user: BoardViewer,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Archiwum zapisanych raportów i okresy, za które raport można pobrać."""

    today = business_today()
    rows = (
        await db.execute(
            select(BoardReport).order_by(
                BoardReport.created_at.desc(), BoardReport.id.desc()
            )
        )
    ).scalars()
    first = (
        await db.execute(select(func.min(FinanceArchiveDocument.issue_date)))
    ).scalar_one_or_none()
    first_year = max(first.year if first else today.year, today.year - 4)
    return {
        "items": [report_view(row) for row in rows],
        "years": list(range(today.year, first_year - 1, -1)),
        "today": today.isoformat(),
    }


async def _render(
    db: AsyncSession, kind: str, year: int, month: Optional[int]
) -> bytes:
    try:
        html = await reports_service.render_html(
            db, kind, year, month, business_today(), datetime.now(timezone.utc)
        )
    except reports_service.ReportError as exc:
        raise HTTPException(422, str(exc)) from exc
    return reports_service.render_pdf(html)


def _pdf(content: bytes, name: str) -> Response:
    return Response(
        content=content,
        media_type="application/pdf",
        headers={
            "Content-Disposition": content_disposition(name, disposition="inline"),
            "Cache-Control": "no-store",
        },
    )


@router.get("/reports/render")
async def render_report(
    current_user: BoardViewer,
    kind: str = Query(..., pattern="^(monthly|annual|budget)$"),
    year: int = Query(..., ge=2000, le=2100),
    month: Optional[int] = Query(None, ge=1, le=12),
    db: AsyncSession = Depends(get_db),
) -> Response:
    """Raport z bieżących danych (PDF)."""

    content = await _render(db, kind, year, month)
    return _pdf(content, reports_service.file_name(kind, year, month))


class ReportBody(BaseModel):
    kind: str = Field(pattern="^(monthly|annual|budget)$")
    year: int = Field(ge=2000, le=2100)
    month: Optional[int] = Field(default=None, ge=1, le=12)


@router.post("/reports", status_code=201)
async def archive_report(
    body: ReportBody,
    current_user: AdminUser,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Zapisz raport z bieżących danych w archiwum Rady."""

    content = await _render(db, body.kind, body.year, body.month)
    name = reports_service.file_name(body.kind, body.year, body.month)
    path, size = storage_service.save_board_document_file(name, content)
    row = BoardReport(
        kind=body.kind,
        year=body.year,
        month=body.month,
        file_path=path,
        file_size=size,
        created_by=current_user.id,
    )
    db.add(row)
    try:
        await db.commit()
    except Exception:
        await db.rollback()
        storage_service.delete_board_document_file(path)
        raise
    await db.refresh(row)
    return report_view(row)


@router.get("/reports/{report_id}/file")
async def download_report(
    report_id: int,
    current_user: BoardViewer,
    db: AsyncSession = Depends(get_db),
) -> Response:
    row = await db.get(BoardReport, report_id)
    if row is None:
        raise HTTPException(404, "Nie ma takiego raportu.")
    try:
        content = storage_service.read_board_document_file(row.file_path)
    except FileNotFoundError as exc:
        raise HTTPException(404, "Pliku nie ma w magazynie.") from exc
    return _pdf(content, reports_service.file_name(row.kind, row.year, row.month))


@router.delete("/reports/{report_id}", status_code=204)
async def delete_report(
    report_id: int,
    current_user: AdminUser,
    db: AsyncSession = Depends(get_db),
) -> Response:
    row = await db.get(BoardReport, report_id)
    if row is None:
        raise HTTPException(404, "Nie ma takiego raportu.")
    path = row.file_path
    await db.delete(row)
    await db.commit()
    try:
        storage_service.delete_board_document_file(path)
    except OSError:
        logger.warning("board report file not removed: report_id=%s", report_id)
    return Response(status_code=204)


# ── Firma: placementy, kontraktorzy, zejścia (R7) ────────────────────────────


@router.get("/people")
async def get_people(
    current_user: BoardViewer,
    period: str = Query("quarter", pattern="^(month|quarter|year|custom)$"),
    offset: int = Query(0, ge=-40, le=0),
    date_from: Optional[date] = Query(None),
    date_to: Optional[date] = Query(None),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Placementy, kontraktorzy na projektach i zejścia z powodami w okresie."""

    try:
        resolved = resolve_period(
            period, offset=offset, date_from=date_from, date_to=date_to
        )
    except PeriodError as exc:
        raise HTTPException(422, str(exc)) from exc
    today = business_today()
    now = datetime.now(timezone.utc)
    first = resolved.start.date()
    last = min((resolved.end - timedelta(days=1)).date(), today)
    prev_start, prev_end = previous_matching_window(resolved, now)
    data = await people_service.people_view(
        db,
        window=(first, last),
        previous=(prev_start.date(), (prev_end - timedelta(days=1)).date()),
        bounds=(resolved.start, min(resolved.end, now)),
        previous_bounds=(prev_start, prev_end),
    )
    return {"period": resolved.as_payload(), **data}


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


# ── Analiza finansowa (R4) ───────────────────────────────────────────────────

MAX_XML_BYTES = 10 * 1024 * 1024
XML_SUFFIXES = (".xml", ".xades")


def _statement_year(year: int) -> int:
    if not 2000 <= year <= business_today().year:
        raise HTTPException(
            422, "Sprawozdanie dotyczy roku zakończonego albo bieżącego."
        )
    return year


@router.get("/analysis")
async def get_analysis(
    current_user: BoardViewer,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Sprawozdania roczne (XML, wpis ręczny, księga), wskaźniki, kredyt, wycena."""

    return await financials.analysis_view(db, business_today())


class StatementPut(BaseModel):
    amounts: dict[str, Optional[float]] = Field(default_factory=dict)
    note: Optional[str] = Field(None, max_length=4000)


@router.put("/statements/{year}")
async def put_statement(
    year: int,
    body: StatementPut,
    current_user: AdminUser,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Wpis ręczny roku z papierowego sprawozdania (admin), PLN."""

    try:
        await financials.save_manual(
            db, _statement_year(year), body.amounts, body.note, current_user.id
        )
    except StatementError as exc:
        raise HTTPException(422, str(exc)) from exc
    return await financials.analysis_view(db, business_today())


@router.delete("/statements/{year}", status_code=204)
async def delete_statement(
    year: int,
    current_user: AdminUser,
    db: AsyncSession = Depends(get_db),
) -> Response:
    if not await financials.delete_statement(db, year):
        raise HTTPException(404, "Nie ma sprawozdania za ten rok.")
    return Response(status_code=204)


@router.post("/statements/import")
async def import_statement(
    current_user: AdminUser,
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Plik e-Sprawozdania z eKRS (XML albo podpisany XAdES), admin."""

    name = (file.filename or "").strip()
    if not name.lower().endswith(XML_SUFFIXES):
        raise HTTPException(422, "Wgraj plik e-Sprawozdania: XML albo XADES z eKRS.")
    content = await file.read(MAX_XML_BYTES + 1)
    if len(content) > MAX_XML_BYTES:
        raise HTTPException(413, "Plik większy niż 10 MB.")
    if not content:
        raise HTTPException(422, "Plik jest pusty.")
    try:
        result = await financials.import_xml(db, name, content, current_user.id)
    except StatementError as exc:
        raise HTTPException(422, str(exc)) from exc
    return result


# ── Posiedzenia (R5) ─────────────────────────────────────────────────────────


def meeting_view(meeting: BoardMeeting, *, with_pack: bool = False) -> dict[str, Any]:
    out: dict[str, Any] = {
        "id": meeting.id,
        "held_on": meeting.held_on.isoformat(),
        "kind": meeting.kind,
        "status": meeting.status,
        "title": meeting.title,
        "place": meeting.place,
        "agenda": meeting.agenda or [],
        "note": meeting.note,
        "minutes_document_id": meeting.minutes_document_id,
        "pack_frozen_at": _iso(meeting.pack_frozen_at),
        "has_pack": meeting.pack is not None,
    }
    if with_pack:
        out["pack"] = meeting.pack
    return out


async def _meeting(db: AsyncSession, meeting_id: int) -> BoardMeeting:
    meeting = await db.get(BoardMeeting, meeting_id)
    if meeting is None:
        raise HTTPException(404, "Nie ma takiego posiedzenia.")
    return meeting


@router.get("/meetings")
async def list_meetings(
    current_user: BoardViewer,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Posiedzenia (najnowsze pierwsze) i obowiązki korporacyjne roku."""

    rows = (
        await db.execute(
            select(BoardMeeting).order_by(BoardMeeting.held_on.desc(), BoardMeeting.id)
        )
    ).scalars()
    return {
        "items": [meeting_view(meeting) for meeting in rows],
        "obligations": await meetings_service.obligations_view(db, business_today()),
    }


@router.get("/meetings/{meeting_id}")
async def get_meeting(
    meeting_id: int,
    current_user: BoardViewer,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return meeting_view(await _meeting(db, meeting_id), with_pack=True)


class AgendaItem(BaseModel):
    title: str = Field(..., min_length=1, max_length=500)
    document_ids: list[int] = Field(default_factory=list, max_length=20)


class MeetingBody(BaseModel):
    held_on: date
    kind: str = "meeting"
    status: str = "planned"
    title: str = Field(..., min_length=1, max_length=meetings_schema.TITLE_MAX)
    place: Optional[str] = Field(None, max_length=meetings_schema.PLACE_MAX)
    agenda: list[AgendaItem] = Field(
        default_factory=list, max_length=meetings_schema.AGENDA_MAX
    )
    note: Optional[str] = Field(None, max_length=4000)
    minutes_document_id: Optional[int] = None


async def _apply_meeting(
    db: AsyncSession, meeting: BoardMeeting, body: MeetingBody, user_id: int
) -> None:
    if body.kind not in meetings_schema.KINDS:
        raise HTTPException(422, "Tryb: posiedzenie, zdalnie albo pisemnie.")
    if body.status not in meetings_schema.STATUSES:
        raise HTTPException(422, "Status: zaplanowane, odbyte albo odwołane.")
    referenced = {doc_id for item in body.agenda for doc_id in item.document_ids}
    if body.minutes_document_id is not None:
        referenced.add(body.minutes_document_id)
    if referenced:
        found = set(
            (
                await db.execute(
                    select(BoardDocument.id).where(BoardDocument.id.in_(referenced))
                )
            ).scalars()
        )
        if found != referenced:
            raise HTTPException(
                422, "Porządek obrad wskazuje dokument, którego nie ma."
            )
    meeting.held_on = body.held_on
    meeting.kind = body.kind
    meeting.status = body.status
    meeting.title = body.title.strip()
    meeting.place = (body.place or "").strip() or None
    meeting.agenda = [
        {"title": item.title.strip(), "document_ids": item.document_ids}
        for item in body.agenda
    ]
    meeting.note = (body.note or "").strip() or None
    meeting.minutes_document_id = body.minutes_document_id
    meeting.updated_by = user_id
    meeting.updated_at = datetime.now(timezone.utc)


@router.post("/meetings", status_code=201)
async def create_meeting(
    body: MeetingBody,
    current_user: AdminUser,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    meeting = BoardMeeting(created_by=current_user.id)
    await _apply_meeting(db, meeting, body, current_user.id)
    db.add(meeting)
    await db.commit()
    await db.refresh(meeting)
    return meeting_view(meeting)


@router.put("/meetings/{meeting_id}")
async def update_meeting(
    meeting_id: int,
    body: MeetingBody,
    current_user: AdminUser,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    meeting = await _meeting(db, meeting_id)
    await _apply_meeting(db, meeting, body, current_user.id)
    await db.commit()
    await db.refresh(meeting)
    return meeting_view(meeting)


@router.delete("/meetings/{meeting_id}", status_code=204)
async def delete_meeting(
    meeting_id: int,
    current_user: AdminUser,
    db: AsyncSession = Depends(get_db),
) -> Response:
    """Usuń wpis bez pakietu. Posiedzenie z wysłanym pakietem tylko odwołaj."""

    meeting = await _meeting(db, meeting_id)
    if meeting.pack is not None:
        raise HTTPException(
            409, "Pakiet poszedł już do Rady — zmień status na „odwołane”."
        )
    await db.delete(meeting)
    await db.commit()
    return Response(status_code=204)


@router.post("/meetings/{meeting_id}/pack")
async def freeze_pack(
    meeting_id: int,
    current_user: AdminUser,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Zamroź pakiet na dziś i daj znać Radzie (ponowne zamrożenie podmienia)."""

    meeting = await _meeting(db, meeting_id)
    if meeting.status == "cancelled":
        raise HTTPException(409, "Posiedzenie jest odwołane.")
    meeting.pack = await meetings_service.build_pack(db, meeting, business_today())
    meeting.pack_frozen_at = datetime.now(timezone.utc)
    meeting.pack_frozen_by = current_user.id
    await db.flush()
    notified = await meetings_service.notify_pack(db, meeting)
    await db.commit()
    await db.refresh(meeting)
    return {**meeting_view(meeting, with_pack=True), "notified": notified}


# ── Uchwały w trybie pisemnym (R6) ───────────────────────────────────────────


async def _ballots(db: AsyncSession, vote_ids: list[int]) -> dict[int, dict[int, str]]:
    out: dict[int, dict[int, str]] = {vote_id: {} for vote_id in vote_ids}
    if not vote_ids:
        return out
    rows = await db.execute(
        select(
            BoardVoteBallot.vote_id, BoardVoteBallot.user_id, BoardVoteBallot.choice
        ).where(BoardVoteBallot.vote_id.in_(vote_ids))
    )
    for vote_id, user_id, choice in rows.all():
        out[vote_id][user_id] = choice
    return out


def _vote_open(vote: BoardVote) -> bool:
    return vote.status == "open" and business_today() <= vote.deadline


async def vote_view(
    db: AsyncSession, vote: BoardVote, ballots: dict[int, str], viewer: User
) -> dict[str, Any]:
    current = votes_service.tally(vote.member_ids, ballots, vote.chair_user_id)
    members = await votes_service.board_members(db, list(vote.member_ids))
    return {
        "id": vote.id,
        "number": vote.number,
        "title": vote.title,
        "draft": vote.draft,
        "document_id": vote.document_id,
        "meeting_id": vote.meeting_id,
        "deadline": vote.deadline.isoformat(),
        "status": vote.status,
        "accepting": _vote_open(vote),
        "chair_user_id": vote.chair_user_id,
        "members": [
            {**member, "choice": ballots.get(member["id"])} for member in members
        ],
        "tally": current.as_dict(),
        "result": vote.result,
        "resolution_document_id": vote.resolution_document_id,
        "my_choice": ballots.get(viewer.id),
        "can_vote": viewer.id in vote.member_ids and _vote_open(vote),
        # Zamknięcie: po terminie albo gdy zagłosowali wszyscy ze składu.
        "closable": vote.status == "open"
        and (
            business_today() > vote.deadline
            or all(uid in ballots for uid in vote.member_ids)
        ),
        "created_at": _iso(vote.created_at),
        "closed_at": _iso(vote.closed_at),
    }


async def _vote(db: AsyncSession, vote_id: int, *, lock: bool = False) -> BoardVote:
    """Uchwała; ``lock`` = wiersz zablokowany do końca transakcji (głos,
    zamknięcie, wycofanie idą po kolei — bez głosu po wyniku, podwójnego
    zamknięcia i 500 przy podwójnym kliknięciu pierwszego głosu)."""

    query = select(BoardVote).where(BoardVote.id == vote_id)
    if lock:
        query = query.with_for_update()
    vote = (await db.execute(query)).scalar_one_or_none()
    if vote is None:
        raise HTTPException(404, "Nie ma takiej uchwały.")
    return vote


@router.get("/votes")
async def list_votes(
    current_user: BoardViewer,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Uchwały w trybie pisemnym, najnowsze pierwsze, z głosami członków."""

    votes = list(
        (
            await db.execute(
                select(BoardVote).order_by(BoardVote.created_at.desc(), BoardVote.id)
            )
        ).scalars()
    )
    ballots = await _ballots(db, [vote.id for vote in votes])
    members = await votes_service.board_member_ids(db)
    return {
        "items": [
            await vote_view(db, vote, ballots[vote.id], current_user) for vote in votes
        ],
        "board": await votes_service.board_members(db, members),
        "excluded_matters": list(votes_service.EXCLUDED_MATTERS),
    }


class VoteCreate(BaseModel):
    number: Optional[str] = Field(None, max_length=votes_schema.NUMBER_MAX)
    title: str = Field(..., min_length=1, max_length=votes_schema.TITLE_MAX)
    draft: str = Field(..., min_length=1, max_length=20000)
    document_id: Optional[int] = None
    meeting_id: Optional[int] = None
    deadline: date
    chair_user_id: Optional[int] = None
    #: Admin potwierdza, że sprawa nie jest wyłączona z trybu pisemnego (§ 25 ust. 5).
    not_excluded_matter: bool = False


@router.post("/votes", status_code=201)
async def create_vote(
    body: VoteCreate,
    current_user: AdminUser,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Projekt uchwały do głosowania pisemnego; każdy członek Rady dostaje dzwonek."""

    if not body.not_excluded_matter:
        raise HTTPException(
            422,
            "Potwierdź, że uchwała nie dotyczy spraw wyłączonych z trybu pisemnego "
            "(§ 25 ust. 5 statutu).",
        )
    if body.deadline < business_today():
        raise HTTPException(422, "Termin głosowania nie może być w przeszłości.")
    members = await votes_service.board_member_ids(db)
    if not members:
        raise HTTPException(409, "W NEXUSIE nie ma aktywnych kont członków Rady.")
    if body.chair_user_id is not None and body.chair_user_id not in members:
        raise HTTPException(422, "Przewodniczący musi być członkiem Rady.")
    if (
        body.document_id is not None
        and await db.get(BoardDocument, body.document_id) is None
    ):
        raise HTTPException(422, "Wskazany dokument nie istnieje.")
    if (
        body.meeting_id is not None
        and await db.get(BoardMeeting, body.meeting_id) is None
    ):
        raise HTTPException(422, "Wskazane posiedzenie nie istnieje.")
    vote = BoardVote(
        number=(body.number or "").strip() or None,
        title=body.title.strip(),
        draft=body.draft.strip(),
        document_id=body.document_id,
        meeting_id=body.meeting_id,
        deadline=body.deadline,
        member_ids=members,
        chair_user_id=body.chair_user_id,
        created_by=current_user.id,
    )
    db.add(vote)
    await db.flush()
    await votes_service.notify_opened(db, vote)
    await db.commit()
    await db.refresh(vote)
    return await vote_view(db, vote, {}, current_user)


class BallotBody(BaseModel):
    choice: str


@ballot_router.post("/votes/{vote_id}/ballot")
async def cast_ballot(
    vote_id: int,
    body: BallotBody,
    current_user: BoardViewer,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Głos członka Rady ze składu; do zamknięcia i terminu można go zmienić."""

    if body.choice not in votes_schema.CHOICES:
        raise HTTPException(422, "Głos: za, przeciw albo wstrzymuję się.")
    vote = await _vote(db, vote_id, lock=True)
    if current_user.id not in vote.member_ids:
        raise HTTPException(403, "Głosują członkowie Rady, którzy dostali projekt.")
    if not _vote_open(vote):
        raise HTTPException(409, "Głosowanie jest zamknięte albo minął termin.")
    ballot = (
        await db.execute(
            select(BoardVoteBallot).where(
                BoardVoteBallot.vote_id == vote.id,
                BoardVoteBallot.user_id == current_user.id,
            )
        )
    ).scalar_one_or_none()
    now = datetime.now(timezone.utc)
    if ballot is None:
        db.add(
            BoardVoteBallot(
                vote_id=vote.id,
                user_id=current_user.id,
                choice=body.choice,
                cast_at=now,
            )
        )
    else:
        ballot.choice = body.choice
        ballot.cast_at = now
    await db.commit()
    ballots = (await _ballots(db, [vote.id]))[vote.id]
    return await vote_view(db, vote, ballots, current_user)


@router.post("/votes/{vote_id}/close")
async def close_vote(
    vote_id: int,
    current_user: AdminUser,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Zamknij głosowanie: wynik według § 25; podjęta uchwała trafia do Dokumentów."""

    vote = await _vote(db, vote_id, lock=True)
    if vote.status != "open":
        raise HTTPException(409, "Głosowanie jest już zamknięte.")
    ballots = (await _ballots(db, [vote.id]))[vote.id]
    missing = [uid for uid in vote.member_ids if uid not in ballots]
    if business_today() <= vote.deadline and missing:
        # Każdy członek, który dostał projekt, ma czas do terminu (§ 25 ust. 4).
        raise HTTPException(
            409,
            f"Termin mija {vote.deadline.strftime('%d.%m.%Y')}, a nie głosowało "
            f"{len(missing)} z {len(vote.member_ids)} członków. Zamknąć można po "
            "terminie albo gdy zagłosują wszyscy; wcześniej — tylko wycofać.",
        )
    result = votes_service.tally(vote.member_ids, ballots, vote.chair_user_id)
    vote.status = "closed"
    vote.result = result.as_dict()
    vote.closed_by = current_user.id
    vote.closed_at = datetime.now(timezone.utc)
    if result.passed:
        doc = BoardDocument(
            category="resolution_supervisory",
            organ="supervisory",
            number=vote.number,
            title=vote.title[: schema.TITLE_MAX],
            subject=(
                f"Podjęta w trybie pisemnym (§ 25 ust. 4 statutu): za {result.votes_for}, "
                f"przeciw {result.against}, wstrzymało się {result.abstain}; "
                f"głosowało {result.voted} z {result.members}."
            ),
            doc_date=business_today(),
            source="upload",
            created_by=current_user.id,
            updated_by=current_user.id,
        )
        db.add(doc)
        await db.flush()
        vote.resolution_document_id = doc.id
    await votes_service.notify_closed(db, vote, result)
    await db.commit()
    await db.refresh(vote)
    return await vote_view(db, vote, ballots, current_user)


@router.post("/votes/{vote_id}/withdraw")
async def withdraw_vote(
    vote_id: int,
    current_user: AdminUser,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    vote = await _vote(db, vote_id, lock=True)
    if vote.status != "open":
        raise HTTPException(409, "Głosowanie jest już zamknięte.")
    vote.status = "withdrawn"
    vote.closed_by = current_user.id
    vote.closed_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(vote)
    ballots = (await _ballots(db, [vote.id]))[vote.id]
    return await vote_view(db, vote, ballots, current_user)


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
    year: Optional[int] = Query(None, ge=1990, le=2100),
    month: Optional[int] = Query(None, ge=1, le=12),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Dokumenty z filtrem rodzaju oraz roku i miesiąca powstania dokumentu
    (data dokumentu, a bez niej data wpisu w KRS) — R7, uwaga Rady 18.11.2026:
    „dokumenty z czerwca 2026 — wszystkie protokoły i uchwały z tego miesiąca”."""

    if category is not None and category not in schema.CATEGORIES:
        raise HTTPException(422, "Nieznany rodzaj dokumentu.")
    if month is not None and year is None:
        raise HTTPException(422, "Miesiąc wybiera się razem z rokiem.")
    day = func.coalesce(BoardDocument.doc_date, BoardDocument.krs_entry_date)
    period = []
    if year is not None:
        period.append(func.extract("year", day) == year)
    if month is not None:
        period.append(func.extract("month", day) == month)
    counts_rows = await db.execute(
        select(
            BoardDocument.category,
            func.count(),
            func.count().filter(BoardDocument.file_path.is_(None)),
        )
        .where(*period)
        .group_by(BoardDocument.category)
    )
    counts = {
        row[0]: {"total": row[1], "without_file": row[2]} for row in counts_rows.all()
    }
    years = (
        await db.execute(
            select(func.extract("year", day).label("y"))
            .where(day.is_not(None))
            .group_by("y")
            .order_by(func.extract("year", day).desc())
        )
    ).scalars()
    query = (
        select(BoardDocument)
        .where(*period)
        .order_by(
            BoardDocument.doc_date.desc().nulls_last(),
            BoardDocument.krs_entry_date.desc().nulls_last(),
            BoardDocument.id.desc(),
        )
    )
    if category is not None:
        query = query.where(BoardDocument.category == category)
    docs = (await db.execute(query.limit(500))).scalars().all()
    return {
        "categories": [
            {"key": key, **counts.get(key, {"total": 0, "without_file": 0})}
            for key in schema.CATEGORIES
        ],
        "years": [int(y) for y in years],
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
