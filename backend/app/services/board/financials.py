"""Zakładka „Analiza” (R4): lata ze sprawozdań i z księgi, zapis i import XML."""

from __future__ import annotations

import hashlib
import logging
from datetime import date, datetime, timezone
from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.board_document import BoardDocument, BoardFinancialStatement
from app.models.ledger import LedgerYear
from app.services import storage_service
from app.services.board import analysis
from app.services.board import statements as parser
from app.services.finance_ledger.costs import LedgerError
from app.services.ledger import statements as ledger_statements

logger = logging.getLogger(__name__)

#: Kolejność pierwszeństwa, gdy rok jest z kilku źródeł.
PRIORITY = {"manual": 3, "xml": 3, "ledger": 1, "xml_prev": 2}
SOURCE_LABELS = {
    "xml": "e-Sprawozdanie z eKRS",
    "xml_prev": "kolumna „rok poprzedni” z e-Sprawozdania za rok następny",
    "manual": "wpisane ręcznie przez Zarząd",
    "ledger": "księga NEXUSA (niezatwierdzone sprawozdanie)",
}


def _row(statement: BoardFinancialStatement) -> dict[str, Any]:
    return {
        "year": statement.year,
        "source": statement.source,
        "source_label": SOURCE_LABELS[statement.source],
        "period_start": statement.period_start.isoformat()
        if statement.period_start
        else None,
        "period_end": statement.period_end.isoformat()
        if statement.period_end
        else None,
        "document_id": statement.document_id,
        "schema_name": statement.schema_name,
        "note": statement.note,
        "amounts": {key: statement.amounts.get(key) for key in parser.FIELD_KEYS},
        "raw_count": len(statement.raw or {}),
        "partial_months": None,
        "updated_at": statement.updated_at.isoformat()
        if statement.updated_at
        else None,
    }


async def _ledger_rows(
    db: AsyncSession, today: date, skip: set[int]
) -> list[dict[str, Any]]:
    years = (
        await db.execute(select(LedgerYear.year).order_by(LedgerYear.year))
    ).scalars()
    rows: list[dict[str, Any]] = []
    for year in years:
        if year in skip or year > today.year:
            continue
        month_to = 12 if year < today.year else today.month - 1
        if month_to < 1:
            continue
        try:
            report = await ledger_statements.statements(
                db, year=year, month_to=month_to
            )
        except LedgerError:
            continue
        amounts = parser.normalize(parser.ledger_paths(report))
        if not amounts.get("total_assets") and not amounts.get("revenue"):
            continue
        rows.append(
            {
                "year": year,
                "source": "ledger",
                "source_label": SOURCE_LABELS["ledger"],
                "period_start": date(year, 1, 1).isoformat(),
                "period_end": None,
                "document_id": None,
                "schema_name": None,
                "note": None
                if report.get("complete")
                else "Księga ma konta bez pozycji sprawozdania — kwoty niepełne.",
                "amounts": amounts,
                "raw_count": 0,
                "partial_months": month_to if month_to < 12 else None,
                "updated_at": None,
            }
        )
    return rows


async def analysis_view(db: AsyncSession, today: date) -> dict[str, Any]:
    stored = list(
        (
            await db.execute(
                select(BoardFinancialStatement).order_by(BoardFinancialStatement.year)
            )
        ).scalars()
    )
    rows = [_row(statement) for statement in stored]
    rows += await _ledger_rows(db, today, {statement.year for statement in stored})
    return {
        "fields": [
            {"key": key, "label": label, "group": group}
            for key, label, group, _paths in parser.FIELDS
        ],
        "norms": analysis.RATIO_NORMS,
        "defaults": {
            "debt_to_ebitda": analysis.DEBT_TO_EBITDA,
            "factoring_share": analysis.FACTORING_SHARE,
            "financial_multiple": analysis.FINANCIAL_MULTIPLE,
            "financial_range": list(analysis.FINANCIAL_RANGE),
            "strategic_multiple": analysis.STRATEGIC_MULTIPLE,
            "strategic_range": list(analysis.STRATEGIC_RANGE),
        },
        "years": analysis.analyse_years(rows),
        "expected_years": list(range(today.year - 3, today.year)),
    }


async def _statement(db: AsyncSession, year: int) -> Optional[BoardFinancialStatement]:
    return (
        await db.execute(
            select(BoardFinancialStatement).where(BoardFinancialStatement.year == year)
        )
    ).scalar_one_or_none()


async def save_manual(
    db: AsyncSession,
    year: int,
    amounts: dict[str, Any],
    note: Optional[str],
    user_id: int,
) -> None:
    cleaned = parser.clean_manual(amounts)
    statement = await _statement(db, year)
    if statement is None:
        statement = BoardFinancialStatement(year=year, source="manual")
        db.add(statement)
    statement.source = "manual"
    statement.amounts = cleaned
    statement.raw = {}
    statement.schema_name = None
    statement.period_start = date(year, 1, 1)
    statement.period_end = date(year, 12, 31)
    statement.note = (note or "").strip() or None
    statement.updated_by = user_id
    statement.updated_at = datetime.now(timezone.utc)
    await db.commit()


async def import_xml(
    db: AsyncSession, name: str, content: bytes, user_id: int
) -> dict[str, Any]:
    """Plik e-Sprawozdania: wiersz roku z pliku, rok poprzedni gdy go brak, dokument."""

    parsed = parser.parse_xml(content)
    year = parsed.year
    now = datetime.now(timezone.utc)

    # Ten sam dokument przy ponownym imporcie: najpierw ten z wiersza roku,
    # potem wiersz wzmianki KRS bez PDF-u; dopiero gdy obu brak — nowy.
    doc = None
    existing = await _statement(db, year)
    if existing is not None and existing.document_id and existing.source == "xml":
        doc = await db.get(BoardDocument, existing.document_id)
    if doc is None:
        doc = (
            await db.execute(
                select(BoardDocument).where(
                    BoardDocument.krs_key == f"financial_statement:{year}"
                )
            )
        ).scalar_one_or_none()
        if doc is not None and doc.file_path and doc.content_type != "application/xml":
            doc = None  # przy wzmiance jest już PDF — XML idzie jako osobny dokument
    if doc is None:
        doc = BoardDocument(
            category="financial_statement",
            title=f"Sprawozdanie finansowe za {year} (e-Sprawozdanie XML)",
            doc_date=parsed.period_end,
            source="upload",
            created_by=user_id,
        )
        db.add(doc)
    old_path = doc.file_path
    path, size = storage_service.save_board_document_file(name, content)
    doc.file_name = name[:255]
    doc.file_path = path
    doc.content_type = "application/xml"
    doc.file_size = size
    doc.file_sha256 = hashlib.sha256(content).hexdigest()
    doc.updated_by = user_id
    doc.updated_at = now
    try:
        await db.flush()
        statement = await _statement(db, year)
        if statement is None:
            statement = BoardFinancialStatement(year=year, source="xml")
            db.add(statement)
        statement.source = "xml"
        statement.period_start = parsed.period_start
        statement.period_end = parsed.period_end
        statement.schema_name = parsed.schema_name[:120]
        statement.document_id = doc.id
        statement.amounts = parsed.amounts(0)
        statement.raw = parsed.raw_json()
        statement.note = None
        statement.updated_by = user_id
        statement.updated_at = now

        previous_amounts = parsed.amounts(1)
        filled_previous = False
        if any(value is not None for value in previous_amounts.values()):
            previous = await _statement(db, year - 1)
            if previous is None or previous.source == "xml_prev":
                if previous is None:
                    previous = BoardFinancialStatement(year=year - 1, source="xml_prev")
                    db.add(previous)
                previous.period_start = date(year - 1, 1, 1)
                previous.period_end = date(year - 1, 12, 31)
                previous.schema_name = parsed.schema_name[:120]
                previous.document_id = doc.id
                previous.amounts = previous_amounts
                previous.raw = {}
                previous.updated_by = user_id
                previous.updated_at = now
                filled_previous = True
        await db.commit()
    except Exception:
        await db.rollback()
        storage_service.delete_board_document_file(path)
        raise
    if old_path and old_path != path:
        storage_service.delete_board_document_file(old_path)
    found = sum(1 for value in statement.amounts.values() if value is not None)
    logger.info(
        "board statement xml imported year=%s fields=%s raw=%s",
        year,
        found,
        len(parsed.raw),
    )
    return {
        "year": year,
        "fields_found": found,
        "fields_total": len(parser.FIELD_KEYS),
        "raw_count": len(parsed.raw),
        "previous_year_filled": filled_previous,
        "document_id": doc.id,
    }


async def delete_statement(db: AsyncSession, year: int) -> bool:
    statement = await _statement(db, year)
    if statement is None:
        return False
    await db.delete(statement)
    await db.commit()
    return True
