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

import hashlib
import io
import logging
from datetime import datetime, timezone
from decimal import Decimal
from typing import Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from fastapi import status as http_status
from fastapi.responses import FileResponse
from sqlalchemy import String, cast, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from starlette.concurrency import run_in_threadpool

from app.api.deps import FinanceModuleUser
from app.core.database import get_db
from app.models.activity import Activity
from app.models.finance import (
    FinanceImportRun,
    FinanceImportRunStatus,
    FinanceMonthlyResult,
)
from app.models.user import User
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
from app.services import storage_service
from app.services.finance_import import (
    FinanceHeaderError,
    FinanceWorkbookError,
    parse_finance_workbook,
)

logger = logging.getLogger(__name__)

router = APIRouter()

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


def _row_to_read(row: FinanceMonthlyResult) -> FinanceResultRow:
    return FinanceResultRow.model_validate(row)


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
    _user: FinanceModuleUser,
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
    _user: FinanceModuleUser,
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
    pct_values = [r.margin_pct for r in all_rows if r.margin_pct is not None]
    avg_pct = (
        sum(pct_values, Decimal(0)) / Decimal(len(pct_values)) if pct_values else None
    )

    return FinanceResultsResponse(
        year=year,
        month=month,
        run_id=run.id,
        rows=[_row_to_read(r) for r in rows],
        totals=FinanceTotals(
            cost=cost, revenue=revenue, margin=margin, avg_margin_pct=avg_pct
        ),
        needs_completion_count=run.needs_completion_count,
    )


@router.patch("/results/{row_id}", response_model=FinanceResultRow)
async def update_result_row(
    row_id: int,
    payload: FinanceRowUpdate,
    user: FinanceModuleUser,
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
    user: FinanceModuleUser,
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
    _user: FinanceModuleUser,
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
    _user: FinanceModuleUser,
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
    user: FinanceModuleUser,
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
