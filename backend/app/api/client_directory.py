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
    ClientPortfolioScopePlacementUpdate,
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

    # Effective placement: a manual override wins over the manifest ``category``
    # and the linked-MSA dates.  The manifest consistency invariant keeps
    # reading the raw base columns, so this display-time preference never trips
    # ``applied_manifest_state_inconsistent``.
    effective_category = func.coalesce(
        ClientPortfolioScope.category_override,
        ClientPortfolioScope.category,
    )
    effective_start = func.coalesce(
        ClientPortfolioScope.contract_start_override,
        ClientFrameworkContract.effective_date,
    )
    effective_end = func.coalesce(
        ClientPortfolioScope.contract_end_override,
        ClientFrameworkContract.expiry_date,
    )
    # A row carries a contract period if it links an MSA or pins either date.
    has_contract_period = or_(
        ClientPortfolioScope.framework_contract_id.is_not(None),
        ClientPortfolioScope.contract_start_override.is_not(None),
        ClientPortfolioScope.contract_end_override.is_not(None),
    )

    statement = (
        select(
            ClientPortfolioScope.id.label("scope_id"),
            Client.id.label("client_id"),
            canonical_name.label("display_name"),
            Client.legal_name.label("legal_name"),
            Client.nip.label("nip"),
            Client.regon.label("regon"),
            Client.industry.label("industry"),
            effective_category.label("category"),
            ClientPortfolioScope.category.label("category_base"),
            ClientPortfolioScope.category_override.label("category_override"),
            ClientPortfolioScope.contract_start_override.label(
                "contract_start_override"
            ),
            ClientPortfolioScope.contract_end_override.label("contract_end_override"),
            scope_label.label("scope_label"),
            ClientPortfolioScope.framework_contract_id.label("msa_id"),
            effective_start.label("effective_date"),
            effective_end.label("expiry_date"),
            has_contract_period.label("has_contract_period"),
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
            effective_category == category,
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
    # Group by the EFFECTIVE category so a manually-moved client is counted in
    # the tab it actually appears in (mirrors the row query's COALESCE).
    effective_category = func.coalesce(
        ClientPortfolioScope.category_override,
        ClientPortfolioScope.category,
    )
    return (
        select(
            effective_category.label("category"),
            func.count(distinct(ClientPortfolioScope.client_id)),
        )
        .select_from(ClientPortfolioScope)
        .join(Client, Client.id == ClientPortfolioScope.client_id)
        .where(
            ClientPortfolioScope.archived_at.is_(None),
            *_visible_client_filters(),
        )
        .group_by(effective_category)
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
            category_base=row.category_base,
            client_status=row.client_status,
            category_override=row.category_override,
            contract_start_override=row.contract_start_override,
            contract_end_override=row.contract_end_override,
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
    """Mirror the UI's "Koniec umowy" column: a scope with no contract period
    (no MSA and no manual date override) has no contract end, while a contract
    period with no end date is open-ended. ``expiry_date`` is already the
    effective (override-preferring) value."""
    if not row.has_contract_period:
        return ""
    if row.expiry_date is None:
        return "Bezterminowa"
    return row.expiry_date.isoformat()


# Spreadsheet formula-injection guard. A free-text cell we write verbatim that
# begins with =, +, -, @ (or a tab/CR that can smuggle one in) is executed as a
# formula when the file is opened in Excel / Google Sheets. display_name /
# scope_label / industry / legal_name are user-settable DB values, so we prefix
# them with an apostrophe (the OWASP-standard mitigation) — the spreadsheet then
# renders the literal text. openpyxl also treats a leading "=" string as a
# formula, so this protects the xlsx path too. Ints and ISO dates pass through.
_FORMULA_INJECTION_PREFIXES = ("=", "+", "-", "@", "\t", "\r")


def _formula_safe(value):
    if isinstance(value, str) and value[:1] in _FORMULA_INJECTION_PREFIXES:
        return "'" + value
    return value


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
        values.extend([row.legal_name or "", row.nip or "", row.regon or ""])
    return [_formula_safe(value) for value in values]


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
    # Hitting ``limit`` means the file may be a partial view. Signal it in a
    # header (rather than silently) so the caller can warn — the FE surfaces a
    # toast. Realistic directories sit far below the 10k default, so this is a
    # safety net, not an expected path.
    truncated = len(rows) >= limit

    columns = list(_DIRECTORY_EXPORT_BASE_COLUMNS)
    if can_view_legal:
        columns += _DIRECTORY_EXPORT_LEGAL_COLUMNS
    data_rows = [
        _directory_export_row(row, can_view_legal=can_view_legal) for row in rows
    ]
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")

    def _export_headers(filename: str) -> dict:
        headers = {"Content-Disposition": f'attachment; filename="{filename}"'}
        if truncated:
            headers["X-Export-Truncated"] = "true"
        return headers

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
            headers=_export_headers(filename),
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
        headers=_export_headers(filename),
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

    # Manifest-owned scopes must not have their invariant columns rewritten in
    # place: ``get_client_portfolio_import_health`` compares live ``category`` /
    # ``framework_contract_id`` against the applied import rows, so an in-place
    # edit here reports the portfolio import as unhealthy (/api/health/deep 503)
    # and never self-heals on restart. Curate those through the placement
    # override (PATCH …/placement) instead; ``label`` stays freely editable.
    if scope.source_system != "manual" and (
        "category" in updates or "framework_contract_id" in updates
    ):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "Ten zakres pochodzi z manifestu portfela — zmiana kategorii "
                "lub umowy w miejscu rozjechałaby stan z manifestem. Użyj akcji "
                "„Przenieś w portfelu” (nakładka placementu)."
            ),
        )

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


@router.patch(
    "/{client_id}/portfolio-scopes/{scope_id}/placement",
    response_model=ClientPortfolioScopeResponse,
)
async def update_client_portfolio_scope_placement(
    client_id: int,
    scope_id: int,
    payload: ClientPortfolioScopePlacementUpdate,
    current_user: AdminUser,
    db: AsyncSession = Depends(get_db),
):
    """Curate a scope's directory placement without touching the manifest.

    Writes only the ``*_override`` columns, which the directory READ prefers but
    the manifest consistency invariant ignores. This is the safe way to move a
    client between the Aktywni/Relacyjni/Nieaktywni tabs or pin a contract
    period for a manifest-owned scope — it never causes portfolio drift. A field
    sent as ``null`` clears that override (the row falls back to the manifest /
    linked MSA); an absent field is left unchanged.
    """

    await _get_scope_client(db, client_id)
    scope = await _get_active_scope(db, client_id=client_id, scope_id=scope_id)
    updates = payload.model_dump(exclude_unset=True)
    if not updates:
        return ClientPortfolioScopeResponse.model_validate(scope)

    if "category" in updates:
        scope.category_override = updates["category"]
    if "contract_start" in updates:
        scope.contract_start_override = updates["contract_start"]
    if "contract_end" in updates:
        scope.contract_end_override = updates["contract_end"]

    # Guard the override pair up front (the DB CHECK is the backstop) so callers
    # get a clean 422 instead of an IntegrityError.
    if (
        scope.contract_start_override is not None
        and scope.contract_end_override is not None
        and scope.contract_end_override < scope.contract_start_override
    ):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Data zakończenia umowy nie może być wcześniejsza niż rozpoczęcia.",
        )

    db.add(
        Activity(
            entity_type="client",
            entity_id=client_id,
            action="portfolio_scope_placement_updated",
            user_id=current_user.id,
            details={"scope_id": scope.id, "fields": sorted(updates)},
        )
    )
    await db.flush()
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
    # Archiving a manifest-owned scope removes it from the live invariant join
    # entirely (live_portfolio_scopes < audit_rows) → /api/health/deep 503 with
    # no self-heal — this is exactly the 2026-08-03 outage. Manifest scopes are
    # curated via the placement override; true removal goes through the manifest.
    if scope.source_system != "manual":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "Ten zakres pochodzi z manifestu portfela — archiwizacja z UI "
                "rozjechałaby stan z manifestem. Zmień kategorię/umowę akcją "
                "„Przenieś w portfelu”; trwałe usunięcie zrób przez manifest."
            ),
        )
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
