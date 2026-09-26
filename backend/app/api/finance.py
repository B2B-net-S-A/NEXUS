"""Router `/api/finance` — moduł „Finanse" (miesięczne wyniki kontraktorów).

UWAGA przy dokładaniu endpointów: ten moduł NIE MOŻE dostać
``from __future__ import annotations``, jeśli kiedykolwiek pojawi się w nim
``@limiter.limit`` — PEP 563 + slowapi #579 zamieniają wtedy guardy
``Annotated`` w wymagane parametry QUERY i poprawne żądanie dostaje 422
(ten sam trap co w ``candidate_activity_summary.py`` i ``talent_radar.py``).

Dane tego modułu są NIEZALEŻNE od reszty systemu: „Imię i nazwisko" oraz
„Klient" to wolny tekst z arkusza, bez FK do kandydatów/klientów, a import nie
modyfikuje niczego poza dwiema tabelami ``finance_*``.
"""

import asyncio
import hashlib
import io
import logging
from datetime import date, datetime, timezone
from decimal import ROUND_HALF_UP, Decimal
from typing import Optional

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    HTTPException,
    Query,
    Request,
    UploadFile,
)
from fastapi import status as http_status
from fastapi.responses import FileResponse, Response
from sqlalchemy import String, cast, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from starlette.background import BackgroundTask
from starlette.concurrency import run_in_threadpool

from app.api.deps import FinanceModuleUser
from app.api.section_access import FINANCE_SECTION_DEPENDENCIES, FinanceSectionUser
from app.core.database import get_db
from app.models.activity import Activity
from app.models.finance import (
    FinanceImportRun,
    FinanceImportRunStatus,
    FinanceMonthlyResult,
)
from app.models.user import User, UserRole
from app.schemas.finance import (
    EDITABLE_NUMERIC_FIELDS,
    FinanceHeaderMismatch,
    FinanceImportRejection,
    FinanceImportResult,
    FinanceImportRunRead,
    FinancePeriod,
    FinancePeriodConflict,
    FinanceResultRow,
    FinanceResultsResponse,
    FinanceRowUpdate,
    FinanceTotals,
)
from app.schemas.finance_order_changes import (
    InvoiceLine,
    InvoiceLinesResponse,
    InvoiceLineUpdate,
    OrderChangesPeriod,
    OrderChangesResponse,
    OrderChangesSummaryResponse,
    OrderCheckRequest,
    OrderCheckResponse,
    OrderHistoryResponse,
)
from app.schemas.finance_order_pdfs import (
    OrderPdfClient,
    OrderPdfFile,
    OrderPdfMonth,
    OrderPdfMonthsResponse,
    OrderPdfsResponse,
)
from app.core.http_headers import content_disposition_attachment
from app.services import finance_order_pdfs
from app.services import nordea_invoice_lines, order_change_checks
from app.services import storage_service
from app.services.section_permissions import (
    ProductSection,
    SectionAccess,
    section_access_for_user,
)
from app.services.finance_order_changes import (
    OrderChangesFilters,
    OrderChangesTab,
    apply_filters,
    build_order_changes,
    build_order_changes_workbook,
    order_changes_filename,
    period_label,
)
from app.services.finance_import import (
    FinanceHeaderError,
    FinanceWorkbookError,
    parse_finance_workbook,
)

logger = logging.getLogger(__name__)

router = APIRouter(dependencies=FINANCE_SECTION_DEPENDENCIES)

MAX_UPLOAD_BYTES = 15 * 1024 * 1024
_ALLOWED_EXT = (".xlsx",)

MONTH_LABELS_PL = (
    "Styczeń",
    "Luty",
    "Marzec",
    "Kwiecień",
    "Maj",
    "Czerwiec",
    "Lipiec",
    "Sierpień",
    "Wrzesień",
    "Październik",
    "Listopad",
    "Grudzień",
)

SORTABLE_COLUMNS = {
    "consultant_name": FinanceMonthlyResult.consultant_name,
    "client_name": FinanceMonthlyResult.client_name,
    "cost_rate_md": FinanceMonthlyResult.cost_rate_md,
    "md_count": FinanceMonthlyResult.md_count,
    "compensation": FinanceMonthlyResult.compensation,
    "revenue_rate_md": FinanceMonthlyResult.revenue_rate_md,
    "invoice_amount": FinanceMonthlyResult.invoice_amount,
    "margin_pln": FinanceMonthlyResult.margin_pln,
    "margin_pct": FinanceMonthlyResult.margin_pct,
}


def _period_label(year: int, month: int) -> str:
    return f"{MONTH_LABELS_PL[month - 1]} {year}"


def _validate_period(year: int, month: int) -> None:
    if not 1 <= month <= 12:
        raise HTTPException(422, detail="Miesiąc musi być z zakresu 1–12.")
    if not 2000 <= year <= 2100:
        raise HTTPException(422, detail="Rok musi być z zakresu 2000–2100.")


async def _lock_period(db: AsyncSession, year: int, month: int) -> None:
    """Serializuj operacje na jednym okresie.

    Bez tego dwa równoległe importy tego samego miesiąca ścigałyby się
    o indeks częściowy „jedna aktualna wersja" i jeden z nich padłby
    IntegrityError zamiast poczekać. Lock jest transakcyjny — zwalnia się
    z COMMIT/ROLLBACK, więc nie ma czego sprzątać.

    Bramka dialektu jest tu FAIL-OPEN CO DO PRÓBY, nie co do skutku: gdy nie
    umiemy rozpoznać silnika, i tak próbujemy wziąć blokadę. ``AsyncSession.bind``
    jest w SQLAlchemy 2.0 wycofywane i w części konfiguracji zwraca ``None``;
    warunek „pomiń, jeśli to nie postgres" zamieniłby taki przypadek w CICHY
    brak blokady — najgorszy możliwy tryb awarii, bo objawia się dopiero
    losowym 500 przy dwóch równoległych importach. Silnik bez advisory locków
    (SQLite w testach) rzuci wyjątek, który świadomie połykamy.
    """

    bind = getattr(db, "bind", None)
    if bind is None:
        try:
            bind = db.get_bind()
        except Exception:  # sesja bez rozstrzygalnego bindu
            bind = None
    dialect_name = getattr(getattr(bind, "dialect", None), "name", None)
    if dialect_name is not None and dialect_name != "postgresql":
        return
    try:
        await db.execute(
            text("SELECT pg_advisory_xact_lock(:key1, :key2)"),
            {"key1": year, "key2": month},
        )
    except Exception:
        # Silnik nie zna advisory locków. Import nadal chroni indeks
        # częściowy — po prostu kolizja wyjdzie błędem, a nie czekaniem.
        logger.warning(
            "advisory lock niedostępny (dialekt=%s) — import %04d-%02d bez serializacji",
            dialect_name,
            year,
            month,
        )


_PCT_QUANT = Decimal("0.1")


def _margin_percent(row: FinanceMonthlyResult) -> Optional[Decimal]:
    """Marża % wiersza w PUNKTACH PROCENTOWYCH (21.4 = 21,4%).

    Kolumna ``margin_pct`` jest niejednoznaczna: komórka Excela sformatowana
    jako procent przychodzi z openpyxl jako UŁAMEK (0.214), a tekst „20,2%"
    jako punkty (20.2). Do tego kolumna ma 2 miejsca po przecinku, więc ułamek
    traci precyzję do pełnego punktu (0.17 zamiast 0.1667). Front doklejał
    „%" do ułamka i pokazywał „0,2%" zamiast ~21%.

    Kolejność źródeł:
    1. wartość wpisana RĘCZNIE (``edited_fields``) — człowiek wpisuje punkty
       procentowe i jego korekta wygrywa;
    2. „Marża PLN" / „Faktura" — dokładne i niezależne od formatu komórki;
    3. zapisana wartość z importu: |v| ≤ 1 to ułamek z komórki procentowej.
    """
    if row.margin_pct is not None and "margin_pct" in (row.edited_fields or []):
        return Decimal(row.margin_pct)
    if row.margin_pln is not None and row.invoice_amount:
        return (Decimal(row.margin_pln) / Decimal(row.invoice_amount) * 100).quantize(
            _PCT_QUANT, rounding=ROUND_HALF_UP
        )
    if row.margin_pct is None:
        return None
    value = Decimal(row.margin_pct)
    return value * 100 if abs(value) <= 1 else value


def _weighted_margin_percent(
    rows: list[FinanceMonthlyResult],
) -> Optional[Decimal]:
    """Marża % miesiąca = Σ„Marża PLN" / Σ„Faktura" (punkty procentowe).

    Liczona z wierszy, które mają OBA pola (faktura ≠ 0) — ta sama para, na
    której kafle „Przychód" i „Marża" opierają swój stosunek. Do 24.09.2026
    była tu średnia procentów wierszy: 100 000 zł z 5% i 1 000 zł z 40%
    dawało 22,5% zamiast 5,35% — mały kontrakt ważył tyle co duży.
    ``None``, gdy nie ma z czego liczyć (nie zero).
    """

    margin = Decimal(0)
    revenue = Decimal(0)
    for row in rows:
        if row.margin_pln is None or not row.invoice_amount:
            continue
        margin += Decimal(row.margin_pln)
        revenue += Decimal(row.invoice_amount)
    if not revenue:
        return None
    return (margin / revenue * 100).quantize(_PCT_QUANT, rounding=ROUND_HALF_UP)


def _needs_completion(row: FinanceMonthlyResult) -> bool:
    """Wiersz z pustym polem liczbowym, którego nikt jeszcze nie poprawił.

    Lustro reguły importu (``FinanceRowDraft.missing_fields``: pole liczbowe
    puste w arkuszu). Pole poprawione ręcznie (``edited_fields``) jest
    decyzją człowieka — także gdy celowo zostawił je puste.
    """

    edited = set(row.edited_fields or [])
    return any(
        getattr(row, field) is None and field not in edited
        for field in EDITABLE_NUMERIC_FIELDS
    )


def _needs_completion_count(rows: list[FinanceMonthlyResult]) -> int:
    """Liczone przy odczycie — licznik z importu nie malał po korekcie komórki."""

    return sum(1 for row in rows if _needs_completion(row))


def _row_to_read(row: FinanceMonthlyResult) -> FinanceResultRow:
    read = FinanceResultRow.model_validate(row)
    read.margin_percent = _margin_percent(row)
    return read


def _run_to_read(run: FinanceImportRun) -> FinanceImportRunRead:
    creator = run.creator
    return FinanceImportRunRead(
        id=run.id,
        year=run.period_year,
        month=run.period_month,
        label=_period_label(run.period_year, run.period_month),
        status=(
            run.status.value
            if isinstance(run.status, FinanceImportRunStatus)
            else str(run.status)
        ),
        source_filename=run.source_filename,
        size_bytes=run.size_bytes,
        row_count=run.row_count,
        needs_completion_count=run.needs_completion_count,
        rejected_count=run.rejected_count,
        created_at=run.created_at,
        superseded_at=run.superseded_at,
        created_by_email=creator.email if creator else None,
    )


async def _current_run(
    db: AsyncSession, year: int, month: int
) -> Optional[FinanceImportRun]:
    return await db.scalar(
        select(FinanceImportRun).where(
            FinanceImportRun.period_year == year,
            FinanceImportRun.period_month == month,
            FinanceImportRun.status == FinanceImportRunStatus.current,
        )
    )


# ── Okresy ──────────────────────────────────────────────────────────────────


@router.get("/periods", response_model=list[FinancePeriod])
async def list_periods(
    _user: FinanceSectionUser,
    db: AsyncSession = Depends(get_db),
):
    """Miesiące, które MAJĄ aktualny import — nic więcej.

    Selektor pokazujący miesiące bez danych obiecywałby widok, który zawsze
    będzie pusty; pustka czyta się wtedy jak awaria, a nie jak „nie wgrano".
    """
    runs = (
        (
            await db.execute(
                select(FinanceImportRun)
                .where(FinanceImportRun.status == FinanceImportRunStatus.current)
                .order_by(
                    FinanceImportRun.period_year.desc(),
                    FinanceImportRun.period_month.desc(),
                )
            )
        )
        .scalars()
        .all()
    )
    return [
        FinancePeriod(
            year=run.period_year,
            month=run.period_month,
            label=_period_label(run.period_year, run.period_month),
            run_id=run.id,
            row_count=run.row_count,
        )
        for run in runs
    ]


# ── Wyniki miesiąca ─────────────────────────────────────────────────────────


@router.get("/results", response_model=FinanceResultsResponse)
async def get_results(
    _user: FinanceSectionUser,
    year: int = Query(...),
    month: int = Query(...),
    q: Optional[str] = Query(None, description="Szukaj po konsultancie lub kliencie"),
    sort: str = Query("row_number"),
    direction: str = Query("asc", pattern="^(asc|desc)$"),
    db: AsyncSession = Depends(get_db),
):
    _validate_period(year, month)
    run = await _current_run(db, year, month)
    if run is None:
        raise HTTPException(404, detail="Brak importu za wskazany miesiąc.")

    query = select(FinanceMonthlyResult).where(
        FinanceMonthlyResult.import_run_id == run.id
    )
    if q and q.strip():
        # Escapujemy wildcardy, żeby „%" szukało znaku, a nie zwracało całości.
        needle = q.strip().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        pattern = f"%{needle}%"
        query = query.where(
            FinanceMonthlyResult.consultant_name.ilike(pattern, escape="\\")
            | FinanceMonthlyResult.client_name.ilike(pattern, escape="\\")
        )

    column = SORTABLE_COLUMNS.get(sort, FinanceMonthlyResult.row_number)
    # NULL-e (pola „do uzupełnienia") zawsze na końcu — inaczej sortowanie po
    # kwocie wypychałoby na górę wiersze, które właśnie nie mają kwoty.
    ordering = (
        column.desc().nullslast() if direction == "desc" else column.asc().nullslast()
    )
    query = query.order_by(ordering, FinanceMonthlyResult.row_number.asc())

    rows = (await db.execute(query)).scalars().all()
    if sort == "margin_pct":
        # Tabela pokazuje ``_margin_percent`` (punkty procentowe), a surowa
        # kolumna miesza ułamki z komórek procentowych (0.21) z punktami (20.2).
        # Sortowanie po kolumnie stawiałoby 21% poniżej 5%, więc porządek
        # liczymy z tej samej wartości, którą widzi użytkownik.
        present = [r for r in rows if _margin_percent(r) is not None]
        missing = [r for r in rows if _margin_percent(r) is None]
        present.sort(
            key=lambda r: _margin_percent(r) or Decimal(0),
            reverse=direction == "desc",
        )
        rows = present + missing

    # Kafle liczone z TYCH SAMYCH wierszy co tabela (bez filtra szukania —
    # kafle opisują miesiąc, nie bieżące wyszukiwanie).
    all_rows = (
        (
            await db.execute(
                select(FinanceMonthlyResult).where(
                    FinanceMonthlyResult.import_run_id == run.id
                )
            )
        )
        .scalars()
        .all()
    )
    cost = sum((r.compensation or Decimal(0) for r in all_rows), Decimal(0))
    revenue = sum((r.invoice_amount or Decimal(0) for r in all_rows), Decimal(0))
    margin = sum((r.margin_pln or Decimal(0) for r in all_rows), Decimal(0))
    avg_pct = _weighted_margin_percent(all_rows)
    # Kafel „Marża" to suma kolumny „Marża PLN" z arkusza Finansów, a NIE
    # „Przychód" − „Koszt": wiersze z wynagrodzeniem bez faktury mają marżę
    # pustą i nie obniżają sumy marży, choć ich koszt jest w kaflu „Koszt".
    # Liczby poniżej pozwalają frontowi to powiedzieć wprost zamiast udawać,
    # że trzy kafle się sumują.
    without_margin = [r for r in all_rows if r.margin_pln is None]
    cost_without_margin = sum(
        (r.compensation or Decimal(0) for r in without_margin), Decimal(0)
    )

    return FinanceResultsResponse(
        year=year,
        month=month,
        run_id=run.id,
        rows=[_row_to_read(r) for r in rows],
        totals=FinanceTotals(
            cost=cost,
            revenue=revenue,
            margin=margin,
            avg_margin_pct=avg_pct,
            rows_without_margin=len(without_margin),
            cost_without_margin=cost_without_margin,
        ),
        needs_completion_count=_needs_completion_count(all_rows),
    )


@router.patch("/results/{row_id}", response_model=FinanceResultRow)
async def update_result_row(
    row_id: int,
    payload: FinanceRowUpdate,
    user: FinanceSectionUser,
    db: AsyncSession = Depends(get_db),
):
    """Ręczna korekta jednej komórki — WYŁĄCZNIE w aktualnej wersji miesiąca.

    NIE modyfikuje oryginalnego arkusza w Archiwum (pkt 4.4 ticketu) — plik
    jest zapisem tego, co przysłano, a nie tego, co po korekcie obowiązuje.

    Wiersze wersji ZASTĄPIONEJ są zamrożone. Pobranie po samym PK pozwalało je
    edytować, a to wprost łamało obietnicę, na której stoi „Przywróć jako
    aktualny": przywrócony bieg wracałby ze zmianami wprowadzonymi już PO jego
    zarchiwizowaniu, czyli nie w tym stanie, w jakim go porzucono. Archiwum ma
    być zapisem historii, a nie drugą, edytowalną kopią danych.
    """
    row = await db.scalar(
        select(FinanceMonthlyResult)
        .join(
            FinanceImportRun,
            FinanceImportRun.id == FinanceMonthlyResult.import_run_id,
        )
        .where(FinanceMonthlyResult.id == row_id)
        .where(FinanceImportRun.status == FinanceImportRunStatus.current)
    )
    if row is None:
        # Rozróżniamy „nie ma takiego wiersza" od „jest, ale w zamrożonej
        # wersji" — inaczej edycja archiwum wyglądałaby jak zniknięcie danych.
        exists = await db.scalar(
            select(FinanceMonthlyResult.id).where(FinanceMonthlyResult.id == row_id)
        )
        if exists is not None:
            raise HTTPException(
                409,
                detail=(
                    "Ten wiersz należy do zastąpionej wersji miesiąca. "
                    "Przywróć ją jako aktualną, żeby móc ją edytować."
                ),
            )
        raise HTTPException(404, detail="Nie znaleziono wiersza.")

    supplied = payload.model_fields_set & set(EDITABLE_NUMERIC_FIELDS)
    if not supplied:
        raise HTTPException(422, detail="Brak pól do zaktualizowania.")

    data = payload.model_dump(exclude_unset=True)
    for field_name in supplied:
        setattr(row, field_name, data[field_name])

    # `edited_fields` musi być podmieniony na NOWĄ listę, nie mutowany w
    # miejscu — SQLAlchemy nie wykrywa mutacji zwykłego JSON-a i zmiana
    # przepadałaby przy commicie.
    row.edited_fields = sorted(set(row.edited_fields or []) | supplied)

    # Archiwum czyta licznik z wiersza biegu — trzymamy go zgodnego z tabelą
    # (ta sama reguła co odczyt ``/results``).
    await db.flush()
    run = await db.get(FinanceImportRun, row.import_run_id)
    if run is not None:
        run_rows = (
            await db.scalars(
                select(FinanceMonthlyResult).where(
                    FinanceMonthlyResult.import_run_id == row.import_run_id
                )
            )
        ).all()
        run.needs_completion_count = _needs_completion_count(list(run_rows))

    db.add(
        Activity(
            entity_type="finance_monthly_result",
            entity_id=row.id,
            action="finance_row_edited",
            user_id=user.id,
            details={"fields": sorted(supplied), "import_run_id": row.import_run_id},
        )
    )
    await db.commit()
    await db.refresh(row)
    return _row_to_read(row)


# ── Import ──────────────────────────────────────────────────────────────────


@router.post(
    "/imports",
    response_model=FinanceImportResult,
    status_code=http_status.HTTP_201_CREATED,
)
async def import_workbook(
    user: FinanceSectionUser,
    db: AsyncSession = Depends(get_db),
    file: UploadFile = File(...),
    year: int = Form(...),
    month: int = Form(...),
    replace: bool = Form(False),
):
    """Wgraj arkusz za wskazany miesiąc.

    Okres wybiera CZŁOWIEK (pkt 6 ticketu) — arkusz nie niesie jednoznacznej
    informacji o miesiącu, więc nie zgadujemy go z nazwy pliku ani z zawartości.

    Gdy miesiąc ma już aktualną wersję, a ``replace`` jest False, zwracamy 409
    z liczbą wierszy i liczbą wierszy z ręcznymi poprawkami. Front zamienia to
    na pytanie „Zastąpić?" i wysyła ponownie z ``replace=true``. Dwa kroki
    zamiast preflightu, żeby plik szedł przez sieć raz.
    """
    _validate_period(year, month)

    filename = file.filename or "wyniki.xlsx"
    if not filename.lower().endswith(_ALLOWED_EXT):
        raise HTTPException(415, detail="Dozwolone są wyłącznie pliki .xlsx")

    payload = await file.read(MAX_UPLOAD_BYTES + 1)
    if len(payload) > MAX_UPLOAD_BYTES:
        raise HTTPException(413, detail="Plik przekracza 15 MB.")

    # Parsujemy PRZED dotknięciem bazy i dysku: odrzucony arkusz nie ma
    # zostawiać ani wiersza, ani pliku.
    try:
        parsed = await run_in_threadpool(parse_finance_workbook, payload)
    except FinanceHeaderError as exc:
        raise HTTPException(
            422,
            detail=FinanceHeaderMismatch(
                missing=exc.missing, unexpected=exc.unexpected
            ).model_dump(),
        ) from exc
    except FinanceWorkbookError as exc:
        raise HTTPException(
            422, detail="Nie udało się odczytać pliku jako arkusza .xlsx."
        ) from exc

    if not parsed.rows:
        raise HTTPException(
            422, detail="Arkusz nie zawiera żadnego wiersza z danymi konsultanta."
        )

    await _lock_period(db, year, month)
    existing = await _current_run(db, year, month)
    if existing is not None and not replace:
        # Porównanie przez CAST na tekst, nie `!= "[]"` wprost: kolumna jest
        # JSONB, a Postgres nie ma operatora `jsonb <> varchar` — surowe
        # porównanie wywalało tu 500 dokładnie w ścieżce, która ma OSTRZEC
        # użytkownika przed utratą ręcznych poprawek.
        edited_row_count = (
            await db.scalar(
                select(func.count())
                .select_from(FinanceMonthlyResult)
                .where(
                    FinanceMonthlyResult.import_run_id == existing.id,
                    cast(FinanceMonthlyResult.edited_fields, String) != "[]",
                )
            )
            or 0
        )
        raise HTTPException(
            http_status.HTTP_409_CONFLICT,
            detail=FinancePeriodConflict(
                run_id=existing.id,
                year=year,
                month=month,
                row_count=existing.row_count,
                edited_row_count=int(edited_row_count),
            ).model_dump(),
        )

    replaced_run_id: Optional[int] = None
    if existing is not None:
        # Poprzednia wersja NIE jest kasowana — ląduje w Archiwum ze statusem
        # „Zastąpiony" wraz z własnymi ręcznymi poprawkami, więc „Przywróć"
        # oddaje dokładnie ten stan, w jakim ją porzucono.
        existing.status = FinanceImportRunStatus.superseded
        existing.superseded_at = datetime.now(timezone.utc)
        replaced_run_id = existing.id
        await db.flush()

    # Plik musi być na dysku, zanim powstanie wiersz (`file_path` jest NOT
    # NULL), więc nie da się odwrócić kolejności — ale nieudany commit nie ma
    # zostawiać na wolumenie arkusza, do którego nic nie prowadzi. Stąd
    # sprzątanie w `except`: przy 15 MB na plik i miesięcznym rytmie importów
    # osierocone kopie zbierałyby się cicho i bezterminowo.
    rel_path, size = storage_service.save_finance_import(
        period_year=year,
        period_month=month,
        upload_filename=filename,
        source=io.BytesIO(payload),
    )
    try:
        return await _persist_import(
            db,
            user=user,
            year=year,
            month=month,
            filename=filename,
            rel_path=rel_path,
            size=size,
            payload=payload,
            parsed=parsed,
            replaced_run_id=replaced_run_id,
        )
    except Exception:
        storage_service.delete_finance_import(rel_path)
        raise


async def _persist_import(
    db: AsyncSession,
    *,
    user: User,
    year: int,
    month: int,
    filename: str,
    rel_path: str,
    size: int,
    payload: bytes,
    parsed,
    replaced_run_id: Optional[int],
) -> FinanceImportResult:
    run = FinanceImportRun(
        period_year=year,
        period_month=month,
        status=FinanceImportRunStatus.current,
        source_filename=filename,
        file_path=rel_path,
        file_sha256=hashlib.sha256(payload).hexdigest(),
        size_bytes=size,
        row_count=len(parsed.rows),
        needs_completion_count=parsed.needs_completion,
        rejected_count=len(parsed.critical_errors),
        rejected_details=[
            {"row_number": e.row_number, "reason": e.reason}
            for e in parsed.critical_errors
        ],
        created_by=user.id,
    )
    db.add(run)
    await db.flush()

    db.add_all(
        [
            FinanceMonthlyResult(
                import_run_id=run.id,
                row_number=draft.row_number,
                consultant_name=draft.consultant_name,
                client_name=draft.client_name,
                cost_rate_md=draft.cost_rate_md,
                md_count=draft.md_count,
                compensation=draft.compensation,
                revenue_rate_md=draft.revenue_rate_md,
                invoice_amount=draft.invoice_amount,
                margin_pln=draft.margin_pln,
                margin_pct=draft.margin_pct,
                edited_fields=[],
            )
            for draft in parsed.rows
        ]
    )
    db.add(
        Activity(
            entity_type="finance_import_run",
            entity_id=run.id,
            action="finance_import_created",
            user_id=user.id,
            details={
                "year": year,
                "month": month,
                "rows": len(parsed.rows),
                "replaced_run_id": replaced_run_id,
            },
        )
    )
    await db.commit()

    return FinanceImportResult(
        run_id=run.id,
        year=year,
        month=month,
        imported=len(parsed.rows),
        needs_completion=parsed.needs_completion,
        rejected=len(parsed.critical_errors),
        rejections=[
            FinanceImportRejection(row_number=e.row_number, reason=e.reason)
            for e in parsed.critical_errors
        ],
        replaced_run_id=replaced_run_id,
    )


# ── Archiwum ────────────────────────────────────────────────────────────────


@router.get("/imports", response_model=list[FinanceImportRunRead])
async def list_imports(
    _user: FinanceSectionUser,
    db: AsyncSession = Depends(get_db),
):
    runs = (
        (
            await db.execute(
                select(FinanceImportRun)
                .options(selectinload(FinanceImportRun.creator))
                .order_by(
                    FinanceImportRun.period_year.desc(),
                    FinanceImportRun.period_month.desc(),
                    FinanceImportRun.created_at.desc(),
                )
            )
        )
        .scalars()
        .all()
    )
    return [_run_to_read(run) for run in runs]


@router.get("/imports/{run_id}/file")
async def download_import(
    run_id: int,
    _user: FinanceSectionUser,
    db: AsyncSession = Depends(get_db),
):
    """Pobierz ORYGINALNY arkusz.

    To jedyne miejsce, w którym sześć kolumn spoza tabeli wynikowej w ogóle
    istnieje — dlatego endpoint siedzi za tą samą bramką co reszta modułu.
    """
    run = await db.scalar(select(FinanceImportRun).where(FinanceImportRun.id == run_id))
    if run is None:
        raise HTTPException(404, detail="Nie znaleziono importu.")
    try:
        abs_path = storage_service.get_finance_import_path(run.file_path)
    except FileNotFoundError as exc:
        raise HTTPException(410, detail="Plik nie jest już dostępny na dysku.") from exc
    return FileResponse(
        path=str(abs_path),
        filename=run.source_filename,
        media_type=(
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        ),
    )


@router.post("/imports/{run_id}/restore", response_model=FinanceImportRunRead)
async def restore_import(
    run_id: int,
    user: FinanceSectionUser,
    db: AsyncSession = Depends(get_db),
):
    """Przywróć zastąpioną wersję miesiąca jako aktualną.

    Bez tego „Zastąp" jest praktycznie nieodwracalne, a to jedyny bezpiecznik
    po pomyłkowym imporcie. Przełączamy WYŁĄCZNIE statusy — wiersze obu wersji
    są zapisane osobno i nigdy nie były nadpisywane, więc przywrócona wersja
    wraca z własnymi ręcznymi poprawkami.
    """
    run = await db.scalar(
        select(FinanceImportRun)
        .options(selectinload(FinanceImportRun.creator))
        .where(FinanceImportRun.id == run_id)
    )
    if run is None:
        raise HTTPException(404, detail="Nie znaleziono importu.")
    if run.status == FinanceImportRunStatus.current:
        raise HTTPException(409, detail="Ta wersja jest już aktualna.")

    await _lock_period(db, run.period_year, run.period_month)
    current = await _current_run(db, run.period_year, run.period_month)
    if current is not None:
        # Zdejmujemy aktualną PRZED podniesieniem przywracanej i flushujemy —
        # indeks częściowy dopuszcza jedną wersję `current` na miesiąc, więc
        # stan pośredni z dwiema wywaliłby IntegrityError.
        current.status = FinanceImportRunStatus.superseded
        current.superseded_at = datetime.now(timezone.utc)
        await db.flush()

    run.status = FinanceImportRunStatus.current
    run.superseded_at = None
    db.add(
        Activity(
            entity_type="finance_import_run",
            entity_id=run.id,
            action="finance_import_restored",
            user_id=user.id,
            details={
                "year": run.period_year,
                "month": run.period_month,
                "superseded_run_id": current.id if current else None,
            },
        )
    )
    await db.commit()
    await db.refresh(run)
    creator = await db.scalar(select(User).where(User.id == run.created_by))
    run.creator = creator
    return _run_to_read(run)


# ── Zmiany w zamówieniach ───────────────────────────────────────────────────


def _order_changes_period(year: Optional[int], month: Optional[int]) -> tuple[int, int]:
    """Domyślnie bieżący miesiąc — rozliczenia przygotowuje się w jego trakcie."""

    from app.core.scheduling import business_today

    today = business_today()
    resolved_year = year if year is not None else today.year
    resolved_month = month if month is not None else today.month
    _validate_period(resolved_year, resolved_month)
    return resolved_year, resolved_month


def _order_changes_filters(
    q: Optional[str],
    client_id: Optional[int],
    date_from: Optional[date],
    date_to: Optional[date],
) -> OrderChangesFilters:
    if date_from is not None and date_to is not None and date_from > date_to:
        raise HTTPException(
            status_code=422,
            detail="Data „od” nie może być późniejsza niż data „do”.",
        )
    query = (q or "").strip()
    return OrderChangesFilters(
        query=query or None,
        client_id=client_id,
        date_from=date_from,
        date_to=date_to,
    )


@router.get("/order-changes", response_model=OrderChangesResponse)
async def get_order_changes(
    request: Request,
    user: FinanceSectionUser,
    year: Optional[int] = Query(None),
    month: Optional[int] = Query(None),
    q: Optional[str] = Query(None, max_length=200),
    client_id: Optional[int] = Query(None),
    date_from: Optional[date] = Query(None),
    date_to: Optional[date] = Query(None),
    db: AsyncSession = Depends(get_db),
):
    """Zmiany · Wejścia · Zejścia · Braki w zamówieniach dla jednego miesiąca.

    Liczone przy odczycie z bieżącego stanu zamówień i dziennika zmian, więc
    zamówienie dodane minutę temu jest już w odpowiedzi. Filtry zawężają
    wszystkie listy i liczniki przy podzakładkach — badge nie może obiecywać
    wierszy, których pod nim nie ma.
    """

    resolved_year, resolved_month = _order_changes_period(year, month)
    filters = _order_changes_filters(q, client_id, date_from, date_to)
    # Dekoracja na PEŁNYM audycie, filtry dopiero potem — pozycja ukryta
    # filtrem nie może wyglądać jak odhaczenie, które zniknęło.
    full = await build_order_changes(db, resolved_year, resolved_month)
    decorated = await order_change_checks.decorate(
        db, full, can_check=_can_check(request, user)
    )
    return apply_filters(decorated, filters)


def _impersonating(request: Request) -> bool:
    return getattr(request.state, "impersonator_id", None) is not None


def _can_check(request: Request, user: User) -> bool:
    """Odhaczać mogą role Admin i Finanse z ZAPISEM sekcji Finanse.

    Lustro bramek ``POST /order-changes/checks`` (rola + zapis sekcji z
    ``FINANCE_SECTION_DEPENDENCIES``). Sama rola nie wystarczała: osoba
    z sekcją odebraną do odczytu widziała aktywne checkboxy, a każde
    kliknięcie kończyło się 403. Nigdy w trybie „podgląd jako".
    """

    return (
        not _impersonating(request)
        and user.has_any_role(UserRole.admin, UserRole.finance)
        and section_access_for_user(user, ProductSection.finance) >= SectionAccess.write
    )


@router.get("/order-changes/summary", response_model=OrderChangesSummaryResponse)
async def get_order_changes_summary(
    _user: FinanceSectionUser,
    db: AsyncSession = Depends(get_db),
):
    """Liczniki „Do zrobienia" bieżącego miesiąca — badge przy zakładce w menu.

    Badge liczy podzakładkę Zmiany (to są „zmiany do zrobienia"), a ``tabs``
    niesie liczniki wszystkich pięciu podzakładek.
    """

    year, month = _order_changes_period(None, None)
    response = await build_order_changes(db, year, month)
    tabs = await order_change_checks.tab_summary(db, response)
    return OrderChangesSummaryResponse(
        period=OrderChangesPeriod(
            year=year, month=month, label=period_label(year, month)
        ),
        tabs={tab: value for tab, value in tabs.items()},
        todo=tabs["changes"].todo,
    )


@router.post("/order-changes/checks", response_model=OrderCheckResponse)
async def set_order_change_check(
    payload: OrderCheckRequest,
    user: FinanceModuleUser,
    db: AsyncSession = Depends(get_db),
):
    """Odhacza pozycję jako „Zrobione" albo cofa odhaczenie (Admin i Finanse).

    Pozycja musi istnieć w audycie wskazanego miesiąca — klucz spoza niego
    to nieaktualny widok (zamówienie zmieniono w międzyczasie), nie zapis.
    Każde odhaczenie i cofnięcie zostaje w historii.
    """

    _validate_period(payload.year, payload.month)
    response = await build_order_changes(db, payload.year, payload.month)
    found = order_change_checks.find_item(response, payload.item_key)
    if found is None:
        raise HTTPException(
            status_code=409,
            detail=(
                "Tej pozycji nie ma już w wybranym miesiącu — zamówienie zmieniło "
                "się w międzyczasie. Odśwież widok."
            ),
        )
    tab, item = found
    done = await order_change_checks.set_check(
        db,
        year=payload.year,
        month=payload.month,
        tab=tab,
        item=item,
        done=payload.done,
        user=user,
    )
    await db.commit()
    return OrderCheckResponse(item_key=payload.item_key, done=done)


@router.put(
    "/order-changes/invoice-lines/{order_id}", response_model=InvoiceLinesResponse
)
async def update_invoice_line(
    order_id: int,
    payload: InvoiceLineUpdate,
    request: Request,
    user: FinanceModuleUser,
    db: AsyncSession = Depends(get_db),
):
    """Ręczna poprawka pozycji faktury Nordei (ticket 8) — zapis przy zamówieniu.

    Te same osoby co „Zrobione" (``_can_check``). Poprawka zostaje przy
    zamówieniu także po odhaczeniu wejścia i w kolejnych miesiącach.
    """

    if _impersonating(request):
        raise HTTPException(
            status_code=403, detail="W trybie podglądu nie można zapisywać zmian."
        )
    try:
        lines = await nordea_invoice_lines.save_line(
            db,
            order_id,
            index=payload.index,
            text=payload.text,
            user_id=user.id,
            user_name=user.name or user.email,
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except nordea_invoice_lines.InvoiceLineError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    await db.commit()
    return InvoiceLinesResponse(
        order_id=order_id,
        lines=[InvoiceLine.model_validate(line) for line in lines],
    )


@router.get("/order-changes/history", response_model=OrderHistoryResponse)
async def get_order_change_history(
    _user: FinanceSectionUser,
    order_id: Optional[int] = Query(None),
    order_group_id: Optional[int] = Query(None),
    db: AsyncSession = Depends(get_db),
):
    """Historia (audyt) zamówienia: zmiany z dziennika i odhaczenia pozycji."""

    if order_id is None and order_group_id is None:
        raise HTTPException(
            status_code=422, detail="Podaj zamówienie albo zamówienie zbiorcze."
        )
    return OrderHistoryResponse(
        items=await order_change_checks.order_history(
            db, order_id=order_id, order_group_id=order_group_id
        )
    )


@router.get("/order-changes/export")
async def export_order_changes(
    _user: FinanceSectionUser,
    year: Optional[int] = Query(None),
    month: Optional[int] = Query(None),
    tab: Optional[OrderChangesTab] = Query(None),
    q: Optional[str] = Query(None, max_length=200),
    client_id: Optional[int] = Query(None),
    date_from: Optional[date] = Query(None),
    date_to: Optional[date] = Query(None),
    db: AsyncSession = Depends(get_db),
):
    """Ten sam widok jako XLSX — z tymi samymi filtrami, co ekran.

    ``tab`` wskazuje jedną podzakładkę; pominięty daje cały audyt (pięć
    arkuszy), jak dotąd. Liczniki są w nazwach arkuszy, a każdy arkusz ma
    kolumny „Zrobione" / „Odhaczył(a)" / „Odhaczono".
    """

    resolved_year, resolved_month = _order_changes_period(year, month)
    filters = _order_changes_filters(q, client_id, date_from, date_to)
    # Ta sama kolejność co ekran: dekoracja (stan „Zrobione", autor) na PEŁNYM
    # audycie, filtry dopiero potem — plik niesie to, co widać przy wierszu.
    full = await build_order_changes(db, resolved_year, resolved_month)
    decorated = await order_change_checks.decorate(db, full, can_check=False)
    data = apply_filters(decorated, filters)
    content = await run_in_threadpool(
        build_order_changes_workbook, data, (tab,) if tab else None
    )
    filename = order_changes_filename(resolved_year, resolved_month, tab)
    return Response(
        content=content,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# ── Zamówienia PDF ──────────────────────────────────────────────────────────


def _order_pdf_file(
    entry: finance_order_pdfs.OrderPdfEntry,
    *,
    downloaded_at: Optional[datetime] = None,
    pending_change: bool = False,
) -> OrderPdfFile:
    return OrderPdfFile(
        kind=entry.kind,
        id=entry.id,
        download_name=entry.download_name,
        original_name=entry.original_name,
        consultant_name=entry.consultant_name,
        start=entry.start,
        end=entry.end,
        entry_type=entry.entry_type,
        status=entry.status,
        order_number=entry.order_number,
        uploaded_at=entry.uploaded_at,
        downloaded_at=downloaded_at,
        pending_change=pending_change,
    )


@router.get("/order-pdfs/months", response_model=OrderPdfMonthsResponse)
async def get_order_pdf_months(
    _user: FinanceSectionUser,
    db: AsyncSession = Depends(get_db),
):
    """Miesiące startu zamówień z PDF-em — z liczbą klientów i plików.

    Liczone przy odczycie z całej historii, więc obejmuje też zamówienia
    wgrane przed powstaniem tego widoku.
    """

    entries = await finance_order_pdfs.collect_entries(db)
    return OrderPdfMonthsResponse(
        items=[
            OrderPdfMonth(**item)
            for item in finance_order_pdfs.summarize_months(entries)
        ]
    )


async def _pending_change_orders(
    db: AsyncSession, year: int, month: int
) -> tuple[set[int], set[int]]:
    """Zamówienia i grupy z pozycją „Do zrobienia" w Zmianach tego miesiąca."""

    audit = await build_order_changes(db, year, month)
    items = list(order_change_checks.iter_items(audit))
    states = await order_change_checks.latest_states(
        db, (order_change_checks.item_key(tab, item) for tab, item in items)
    )
    return order_change_checks.todo_orders(audit, states)


@router.get("/order-pdfs", response_model=OrderPdfsResponse)
async def get_order_pdfs(
    user: FinanceSectionUser,
    year: Optional[int] = Query(None),
    month: Optional[int] = Query(None),
    db: AsyncSession = Depends(get_db),
):
    """Klienci z PDF-ami zamówień, które ZACZYNAJĄ się w danym miesiącu.

    Każdy plik niesie status pobrania ZALOGOWANEJ osoby (pobranie przez kogoś
    innego nic tu nie zmienia) i znacznik „zmiana do rozliczenia", gdy jego
    zamówienie ma w Zmianach tego miesiąca pozycję „Do zrobienia".
    """

    resolved_year, resolved_month = _order_changes_period(year, month)
    entries = await finance_order_pdfs.collect_entries(
        db, window=finance_order_pdfs.month_bounds(resolved_year, resolved_month)
    )
    downloads = await finance_order_pdfs.downloads_for_user(db, user.id, entries)
    todo_orders, todo_groups = await _pending_change_orders(
        db, resolved_year, resolved_month
    )

    def pending(entry: finance_order_pdfs.OrderPdfEntry) -> bool:
        if entry.kind == "order":
            return entry.id in todo_orders
        if entry.kind == "group":
            return entry.id in todo_groups
        return False

    clients = [
        OrderPdfClient(
            client_id=bucket["client_id"],
            client_name=bucket["client_name"],
            files=[
                _order_pdf_file(
                    entry,
                    downloaded_at=downloads.get((entry.kind, entry.id)),
                    pending_change=pending(entry),
                )
                for entry in bucket["files"]
            ],
        )
        for bucket in finance_order_pdfs.group_by_client(entries)
    ]
    return OrderPdfsResponse(year=resolved_year, month=resolved_month, clients=clients)


_ORDER_PDF_PATH_GETTERS = {
    "order": storage_service.get_client_order_po_path,
    "group": storage_service.get_client_order_group_po_path,
    "amendment": storage_service.get_contract_document_path,
}

# Sufit plików w jednym ZIP-ie — miesiąc ma dziś kilkadziesiąt PDF-ów, a
# archiwum budowane jest w pamięci.
MAX_ZIP_FILES = 500


def _entry_path(entry: finance_order_pdfs.OrderPdfEntry) -> Optional[str]:
    try:
        abs_path = _ORDER_PDF_PATH_GETTERS[entry.kind](entry.file_path)
    except FileNotFoundError:
        return None
    return str(abs_path) if abs_path.is_file() else None


async def _record_downloads(
    request: Request,
    db: AsyncSession,
    user: User,
    entries: list[finance_order_pdfs.OrderPdfEntry],
) -> None:
    """Pobranie zapisuje się na koncie osoby — nigdy w „podglądzie jako"
    (tam efektywny użytkownik jest kimś innym niż ten, kto klika)."""

    if _impersonating(request) or not entries:
        return
    await finance_order_pdfs.record_downloads(db, user.id, entries)
    await db.commit()


def _parse_file_refs(raw: str) -> list[tuple[str, int]]:
    refs: list[tuple[str, int]] = []
    for token in raw.split(","):
        token = token.strip()
        if not token:
            continue
        kind, _, raw_id = token.partition(":")
        if kind not in _ORDER_PDF_PATH_GETTERS or not raw_id.isdigit():
            raise HTTPException(
                status_code=422, detail=f"Nieprawidłowy plik na liście: {token[:40]}"
            )
        refs.append((kind, int(raw_id)))
    return refs


@router.get("/order-pdfs/zip")
async def download_order_pdfs_zip(
    request: Request,
    user: FinanceSectionUser,
    year: int = Query(...),
    month: int = Query(...),
    client_id: Optional[int] = Query(None),
    files: Optional[str] = Query(None, max_length=20000),
    db: AsyncSession = Depends(get_db),
):
    """ZIP z PDF-ami zamówień miesiąca.

    * ``client_id`` — pliki jednego klienta: ``[Klient]_[RRRR-MM].zip``;
    * bez klienta — cały miesiąc z podfolderem na klienta:
      ``Zamowienia_[RRRR-MM].zip``;
    * ``files`` (``order:1,group:2``) — wybrane pliki z tego zakresu
      („Pobierz zaznaczone", „Pobierz nowe").

    Pliki w środku: ``[Klient]_[NrZam]_[Nazwisko]_[Typ]_[DataOd]-[DataDo].pdf``.
    Każdy plik w archiwum liczy się jako pobrany przez zalogowaną osobę.
    """

    _validate_period(year, month)
    entries = await finance_order_pdfs.collect_entries(
        db, window=finance_order_pdfs.month_bounds(year, month)
    )
    if client_id is not None:
        entries = [entry for entry in entries if entry.client_id == client_id]
    if files is not None:
        wanted = set(_parse_file_refs(files))
        entries = [entry for entry in entries if (entry.kind, entry.id) in wanted]
    if not entries:
        raise HTTPException(status_code=404, detail="Brak plików do spakowania.")
    if len(entries) > MAX_ZIP_FILES:
        raise HTTPException(
            status_code=422,
            detail=f"Za dużo plików w jednym archiwum (limit {MAX_ZIP_FILES}).",
        )
    members = [(entry, _entry_path(entry)) for entry in entries]
    # Archiwum w pliku tymczasowym oddawanym strumieniem i usuwanym po
    # wysłaniu — w pamięci szczyt był ~2× archiwum (runda 6 audytu).
    zip_path = await asyncio.to_thread(
        finance_order_pdfs.build_zip_file, members, client_folders=client_id is None
    )
    try:
        await _record_downloads(
            request, db, user, [entry for entry, path in members if path is not None]
        )
    except BaseException:
        finance_order_pdfs.remove_file_quietly(zip_path)
        raise
    filename = (
        finance_order_pdfs.client_zip_name(entries[0].client_name, year, month)
        if client_id is not None
        else finance_order_pdfs.month_zip_name(year, month)
    )
    return FileResponse(
        zip_path,
        media_type="application/zip",
        headers={
            "Content-Disposition": content_disposition_attachment(
                filename, fallback="zamowienia.zip"
            )
        },
        background=BackgroundTask(finance_order_pdfs.remove_file_quietly, zip_path),
    )


@router.get("/order-pdfs/{kind}/{entry_id}/file")
async def download_order_pdf(
    request: Request,
    kind: finance_order_pdfs.PdfKind,
    entry_id: int,
    user: FinanceSectionUser,
    preview: bool = Query(False),
    db: AsyncSession = Depends(get_db),
):
    """PDF zamówienia pod nazwą z nazwiskiem konsultanta i okresem.

    Nazwa liczona jest tą samą funkcją co lista, więc plik zapisuje się
    dokładnie tak, jak widać go w widoku. ``preview=true`` (podgląd w panelu)
    nie liczy się jako pobranie — status „Nowy" zmienia wyłącznie pobranie.
    """

    entry = await finance_order_pdfs.find_entry(db, kind, entry_id)
    if entry is None:
        raise HTTPException(404, detail="Nie znaleziono pliku zamówienia.")
    abs_path = _entry_path(entry)
    if abs_path is None:
        raise HTTPException(404, detail="Plik nie jest już dostępny na dysku.")
    if not preview:
        await _record_downloads(request, db, user, [entry])
    download_name = entry.download_name
    return FileResponse(
        path=abs_path,
        media_type=entry.content_type or "application/pdf",
        headers={
            "Content-Disposition": content_disposition_attachment(
                download_name, fallback="zamowienie.pdf"
            )
        },
    )
