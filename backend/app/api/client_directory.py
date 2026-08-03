"""Client portfolio directory and manually managed portfolio scopes.

The directory is deliberately scope-shaped: one client may appear in more than
one row when it has more than one commercial scope.  Tile counters, however,
count distinct clients so a multi-scope client does not inflate the headline
number.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from io import BytesIO
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import StreamingResponse
from sqlalchemy import and_, distinct, exists, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import AdminUser, OperationalUser
from app.core.database import get_db
from app.models.activity import Activity
from app.models.client import Client
from app.models.client_directory import (
    ClientAlias,
    ClientPortfolioScope,
    PortfolioCategory,
)
from app.models.client_framework_contract import ClientFrameworkContract
from app.models.contract import Contract, ContractStatus
from app.schemas.client_directory import (
    ClientDirectoryCategoryCounts,
    ClientDirectoryItem,
    ClientDirectoryResponse,
    ClientPortfolioScopeCreate,
    ClientPortfolioScopeResponse,
    ClientPortfolioScopeUpdate,
)
from app.services.client_access import ADMIN_LIKE_ROLES, CLIENT_TEAM_ROLES

router = APIRouter()


def _effective_client_name():
    """SQL expression for the NEXUS-owned canonical display name."""

    return func.coalesce(
        func.nullif(func.btrim(Client.display_name), ""),
        Client.name,
    )


def _escaped_like_pattern(value: str) -> str:
    """Treat user-entered SQL wildcard characters as ordinary characters."""

    escaped = value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


def _visible_client_filters() -> tuple:
    return (
        Client.hidden.is_(False),
        Client.archived_at.is_(None),
        Client.merged_into_client_id.is_(None),
    )


def _active_consultants_subquery(as_of: date):
    """Client-wide date-effective consultant count, deduplicated by person."""

    return (
        select(
            Contract.client_id.label("client_id"),
            func.count(distinct(Contract.candidate_id)).label("active_consultants"),
        )
        .where(
            Contract.status.in_((ContractStatus.active, ContractStatus.ending)),
            Contract.start_date.is_not(None),
            Contract.start_date <= as_of,
            or_(Contract.end_date.is_(None), Contract.end_date >= as_of),
        )
        .group_by(Contract.client_id)
        .subquery()
    )


def _directory_rows_statement(
    *,
    category: PortfolioCategory,
    q: Optional[str],
    as_of: date,
):
    canonical_name = _effective_client_name()
    scope_label = func.nullif(func.btrim(ClientPortfolioScope.label), "")
    active_consultants = _active_consultants_subquery(as_of)

    statement = (
        select(
            ClientPortfolioScope.id.label("scope_id"),
            Client.id.label("client_id"),
            canonical_name.label("display_name"),
            Client.legal_name.label("legal_name"),
            Client.nip.label("nip"),
            Client.regon.label("regon"),
            Client.industry.label("industry"),
            ClientPortfolioScope.category.label("category"),
            scope_label.label("scope_label"),
            ClientPortfolioScope.framework_contract_id.label("msa_id"),
            ClientFrameworkContract.effective_date.label("effective_date"),
            ClientFrameworkContract.expiry_date.label("expiry_date"),
            Client.status.label("client_status"),
            func.coalesce(active_consultants.c.active_consultants, 0).label(
                "active_consultants_count"
            ),
        )
        .select_from(ClientPortfolioScope)
        .join(Client, Client.id == ClientPortfolioScope.client_id)
        .outerjoin(
            ClientFrameworkContract,
            and_(
                ClientFrameworkContract.id
                == ClientPortfolioScope.framework_contract_id,
                ClientFrameworkContract.client_id == Client.id,
            ),
        )
        .outerjoin(
            active_consultants,
            active_consultants.c.client_id == Client.id,
        )
        .where(
            ClientPortfolioScope.archived_at.is_(None),
            ClientPortfolioScope.category == category,
            *_visible_client_filters(),
        )
    )

    normalized_q = (q or "").strip()
    if normalized_q:
        pattern = _escaped_like_pattern(normalized_q)
        statement = statement.where(
            or_(
                canonical_name.ilike(pattern, escape="\\"),
                Client.legal_name.ilike(pattern, escape="\\"),
                Client.name.ilike(pattern, escape="\\"),
                Client.industry.ilike(pattern, escape="\\"),
                ClientPortfolioScope.label.ilike(pattern, escape="\\"),
                exists(
                    select(ClientAlias.id).where(
                        ClientAlias.client_id == Client.id,
                        ClientAlias.archived_at.is_(None),
                        ClientAlias.alias.ilike(pattern, escape="\\"),
                    )
                ),
            )
        )

    return statement.order_by(
        func.lower(canonical_name).asc(),
        func.lower(func.coalesce(scope_label, "")).asc(),
        ClientPortfolioScope.id.asc(),
    )


def _directory_counts_statement():
    return (
        select(
            ClientPortfolioScope.category,
            func.count(distinct(ClientPortfolioScope.client_id)),
        )
        .select_from(ClientPortfolioScope)
        .join(Client, Client.id == ClientPortfolioScope.client_id)
        .where(
            ClientPortfolioScope.archived_at.is_(None),
            *_visible_client_filters(),
        )
        .group_by(ClientPortfolioScope.category)
    )


@router.get("/directory", response_model=ClientDirectoryResponse)
async def list_client_directory(
    current_user: OperationalUser,
    db: AsyncSession = Depends(get_db),
    category: PortfolioCategory = Query(PortfolioCategory.active),
    q: Optional[str] = Query(None, max_length=200),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=100),
):
    """Return one row per portfolio scope for the selected category.

    Search is intentionally limited to the selected category.  Tile counts are
    not affected by search and represent unique visible clients in every
    category.
    """

    as_of = date.today()
    rows_statement = _directory_rows_statement(
        category=category,
        q=q,
        as_of=as_of,
    )
    filtered_rows = rows_statement.order_by(None).subquery()
    total_rows = int(
        (await db.execute(select(func.count()).select_from(filtered_rows))).scalar_one()
    )
    total_clients = int(
        (
            await db.execute(
                select(func.count(distinct(filtered_rows.c.client_id))).select_from(
                    filtered_rows
                )
            )
        ).scalar_one()
    )

    result = await db.execute(
        rows_statement.offset((page - 1) * page_size).limit(page_size)
    )
    can_view_legal = current_user.has_any_role(
        *ADMIN_LIKE_ROLES,
        *CLIENT_TEAM_ROLES,
    )
    items = [
        ClientDirectoryItem(
            scope_id=row.scope_id,
            client_id=row.client_id,
            msa_id=row.msa_id,
            display_name=row.display_name,
            legal_name=row.legal_name if can_view_legal else None,
            scope_label=row.scope_label,
            industry=row.industry,
            active_consultants_count=int(row.active_consultants_count or 0),
            effective_date=row.effective_date,
            expiry_date=row.expiry_date,
            category=row.category,
            client_status=row.client_status,
        )
        for row in result.all()
    ]

    raw_counts = (await db.execute(_directory_counts_statement())).all()
    category_counts = ClientDirectoryCategoryCounts(
        **{
            (
                category_value.value
                if hasattr(category_value, "value")
                else category_value
            ): int(count)
            for category_value, count in raw_counts
        }
    )

    return ClientDirectoryResponse(
        items=items,
        total_rows=total_rows,
        total_clients=total_clients,
        page=page,
        page_size=page_size,
        category_counts=category_counts,
        as_of=as_of,
    )


# ── Export (CSV / XLSX) ───────────────────────────────────────────────────────
# Business-facing Polish labels for the enum columns — the directory export
# lands in delivery / finance spreadsheets, so we render labels instead of the
# raw enum values.
_CATEGORY_LABELS = {
    "active": "Aktywny",
    "relationship": "Relacyjny",
    "inactive": "Nieaktywny",
}
_CLIENT_STATUS_LABELS = {
    "active": "Aktywny",
    "inactive": "Nieaktywny",
    "prospect": "Prospekt",
}

# Columns every operational user may export — mirror the on-screen directory.
_DIRECTORY_EXPORT_BASE_COLUMNS = [
    "ID klienta",
    "Klient",
    "Zakres",
    "Kategoria",
    "Branża",
    "Status klienta",
    "Aktywni konsultanci",
    "Start umowy ramowej",
    "Koniec umowy ramowej",
]
# Legal columns — only for roles that already see legal data in the directory
# (admin / HoR / delivery_lead / tac). The export never widens that access.
_DIRECTORY_EXPORT_LEGAL_COLUMNS = ["Nazwa prawna", "NIP", "REGON"]


def _directory_enum_label(value, labels: dict) -> str:
    """Polish label for an enum value; falls back to the raw value, "" for None."""
    if value is None:
        return ""
    raw = value.value if hasattr(value, "value") else str(value)
    return labels.get(raw, raw)


def _directory_contract_end_cell(row) -> str:
    """Mirror the UI's "Koniec umowy" column: a scope without an MSA has no
    contract end, an MSA with no expiry date is open-ended."""
    if row.msa_id is None:
        return ""
    if row.expiry_date is None:
        return "Bezterminowa"
    return row.expiry_date.isoformat()


def _directory_export_row(row, *, can_view_legal: bool) -> list:
    values = [
        row.client_id,
        row.display_name or "",
        row.scope_label or "",
        _directory_enum_label(row.category, _CATEGORY_LABELS),
        row.industry or "",
        _directory_enum_label(row.client_status, _CLIENT_STATUS_LABELS),
        int(row.active_consultants_count or 0),
        row.effective_date.isoformat() if row.effective_date else "",
        _directory_contract_end_cell(row),
    ]
    if can_view_legal:
        values.extend(
            [row.legal_name or "", row.nip or "", row.regon or ""]
        )
    return values


@router.get("/directory/export")
async def export_client_directory(
    current_user: OperationalUser,
    db: AsyncSession = Depends(get_db),
    format: str = Query("xlsx", pattern="^(csv|xlsx)$"),
    category: PortfolioCategory = Query(PortfolioCategory.active),
    q: Optional[str] = Query(None, max_length=200),
    limit: int = Query(10000, ge=1, le=50000),
):
    """Export the client directory to CSV or Excel — one row per portfolio scope.

    Honours the same ``category`` + ``q`` filters as the list endpoint (so
    "eksportuj to, co widzę" holds) but ignores pagination — every matching row
    up to ``limit``. Legal columns (Nazwa prawna / NIP / REGON) appear only for
    roles that already see them in the directory; the export never widens access.
    """
    can_view_legal = current_user.has_any_role(*ADMIN_LIKE_ROLES, *CLIENT_TEAM_ROLES)
    statement = _directory_rows_statement(
        category=category,
        q=q,
        as_of=date.today(),
    ).limit(limit)
    rows = (await db.execute(statement)).all()

    columns = list(_DIRECTORY_EXPORT_BASE_COLUMNS)
    if can_view_legal:
        columns += _DIRECTORY_EXPORT_LEGAL_COLUMNS
    data_rows = [
        _directory_export_row(row, can_view_legal=can_view_legal) for row in rows
    ]
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")

    if format == "xlsx":
        from openpyxl import Workbook
        from openpyxl.styles import Font

        wb = Workbook()
        ws = wb.active
        ws.title = "Klienci"
        ws.append(columns)
        for cell in ws[1]:
            cell.font = Font(bold=True)
        ws.freeze_panes = "A2"  # keep the header row visible while scrolling
        for data_row in data_rows:
            ws.append(data_row)

        buf = BytesIO()
        wb.save(buf)
        buf.seek(0)
        filename = f"klienci_{ts}.xlsx"
        return StreamingResponse(
            buf,
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )

    # CSV (UTF-8). Prepend a BOM so Excel on Windows renders the Polish
    # diacritics correctly instead of mojibake.
    import csv
    from io import StringIO

    buf = StringIO()
    writer = csv.writer(buf, quoting=csv.QUOTE_MINIMAL)
    writer.writerow(columns)
    for data_row in data_rows:
        writer.writerow(data_row)
    filename = f"klienci_{ts}.csv"
    return StreamingResponse(
        iter(["\ufeff" + buf.getvalue()]),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


async def _get_scope_client(db: AsyncSession, client_id: int) -> Client:
    client = await db.scalar(
        select(Client).where(
            Client.id == client_id,
            *_visible_client_filters(),
        )
    )
    if client is None:
        raise HTTPException(status_code=404, detail="Client not found")
    return client


async def _get_active_scope(
    db: AsyncSession,
    *,
    client_id: int,
    scope_id: int,
) -> ClientPortfolioScope:
    scope = await db.scalar(
        select(ClientPortfolioScope).where(
            ClientPortfolioScope.id == scope_id,
            ClientPortfolioScope.client_id == client_id,
            ClientPortfolioScope.archived_at.is_(None),
        )
    )
    if scope is None:
        raise HTTPException(status_code=404, detail="Portfolio scope not found")
    return scope


async def _validate_framework_contract(
    db: AsyncSession,
    *,
    client_id: int,
    framework_contract_id: Optional[int],
    exclude_scope_id: Optional[int] = None,
) -> None:
    if framework_contract_id is None:
        return
    contract_id = await db.scalar(
        select(ClientFrameworkContract.id).where(
            ClientFrameworkContract.id == framework_contract_id,
            ClientFrameworkContract.client_id == client_id,
        )
    )
    if contract_id is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Framework contract does not belong to this client",
        )
    occupied = select(ClientPortfolioScope.id).where(
        ClientPortfolioScope.framework_contract_id == framework_contract_id,
        ClientPortfolioScope.archived_at.is_(None),
    )
    if exclude_scope_id is not None:
        occupied = occupied.where(ClientPortfolioScope.id != exclude_scope_id)
    occupied_scope_id = await db.scalar(occupied)
    if occupied_scope_id is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Framework contract already belongs to an active portfolio scope",
        )


@router.post(
    "/{client_id}/portfolio-scopes",
    response_model=ClientPortfolioScopeResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_client_portfolio_scope(
    client_id: int,
    payload: ClientPortfolioScopeCreate,
    current_user: AdminUser,
    db: AsyncSession = Depends(get_db),
):
    await _get_scope_client(db, client_id)
    await _validate_framework_contract(
        db,
        client_id=client_id,
        framework_contract_id=payload.framework_contract_id,
    )

    scope = ClientPortfolioScope(
        client_id=client_id,
        framework_contract_id=payload.framework_contract_id,
        category=payload.category,
        label=payload.label,
        source_system="manual",
    )
    db.add(scope)
    try:
        await db.flush()
    except IntegrityError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Framework contract already belongs to an active portfolio scope",
        ) from exc
    db.add(
        Activity(
            entity_type="client",
            entity_id=client_id,
            action="portfolio_scope_created",
            user_id=current_user.id,
            details={
                "scope_id": scope.id,
                "category": payload.category.value,
            },
        )
    )
    await db.flush()
    await db.refresh(scope)
    return ClientPortfolioScopeResponse.model_validate(scope)


@router.patch(
    "/{client_id}/portfolio-scopes/{scope_id}",
    response_model=ClientPortfolioScopeResponse,
)
async def update_client_portfolio_scope(
    client_id: int,
    scope_id: int,
    payload: ClientPortfolioScopeUpdate,
    current_user: AdminUser,
    db: AsyncSession = Depends(get_db),
):
    await _get_scope_client(db, client_id)
    scope = await _get_active_scope(db, client_id=client_id, scope_id=scope_id)
    updates = payload.model_dump(exclude_unset=True)
    if not updates:
        return ClientPortfolioScopeResponse.model_validate(scope)

    if "framework_contract_id" in updates:
        await _validate_framework_contract(
            db,
            client_id=client_id,
            framework_contract_id=updates["framework_contract_id"],
            exclude_scope_id=scope.id,
        )

    for field, value in updates.items():
        setattr(scope, field, value)
    db.add(
        Activity(
            entity_type="client",
            entity_id=client_id,
            action="portfolio_scope_updated",
            user_id=current_user.id,
            details={"scope_id": scope.id, "fields": sorted(updates)},
        )
    )
    try:
        await db.flush()
    except IntegrityError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Framework contract already belongs to an active portfolio scope",
        ) from exc
    await db.refresh(scope)
    return ClientPortfolioScopeResponse.model_validate(scope)


@router.delete(
    "/{client_id}/portfolio-scopes/{scope_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def archive_client_portfolio_scope(
    client_id: int,
    scope_id: int,
    current_user: AdminUser,
    db: AsyncSession = Depends(get_db),
):
    await _get_scope_client(db, client_id)
    scope = await _get_active_scope(db, client_id=client_id, scope_id=scope_id)
    scope.archived_at = datetime.now(timezone.utc)
    db.add(
        Activity(
            entity_type="client",
            entity_id=client_id,
            action="portfolio_scope_archived",
            user_id=current_user.id,
            details={"scope_id": scope.id},
        )
    )
    await db.flush()
