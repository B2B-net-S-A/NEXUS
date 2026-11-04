"""Admin endpoints for the scheduled Traffit → Nexus sync.

- ``POST /api/admin/traffit/sync?mode=delta|full`` — kick a run now (returns
  immediately; the import runs in the background). Used to activate / verify
  without waiting for the 02:00 UTC window.
- ``GET  /api/admin/traffit/sync/status`` — watermark + last-run stats per phase.

RBAC: admin z JWT **albo** konto serwisowe z odpowiednim scope'em
(``traffit:sync`` / ``traffit:read``) w nagłówku ``X-API-Key``.

To są endpointy odpalane operacyjnie poza przeglądarką — dokumentacja aktywacji
w CLAUDE.md każe „odpalić ``POST /api/admin/traffit/sync``", a pełny reconcile
domyka się przez kilkukrotne wywołanie. Robienie tego tokenem wyklikanym
w przeglądarce znaczyło, że automatyzacja podszywa się pod człowieka
poświadczeniem, które i tak umiera po 8 h. Scope'y są rozdzielone celowo:
klucz monitoringu czytający status nie ma prawa uruchomić pełnego importu.

Od 14.10.2026 Traffit jest wyłączony na stałe (decyzja Artura,
``app/services/traffit_retired.py``): każda trasa POST tego modułu — sync,
naprawy, przeniesienie fal, scalenie bliźniaków, także przebieg próbny —
odpowiada 410 z komunikatem po polsku, po bramce uprawnień, zanim cokolwiek
połączy się z Traffitem albo zapisze w bazie. Trasy GET ze stanem zostają:
czytają historię z bazy NEXUSA.
"""

# UWAGA: bez `from __future__ import annotations` — PEP 563 zamienia adnotacje
# FastAPI w ForwardRef, a `@limiter.limit` (slowapi #579) rozwiązuje je już
# w SWOICH globalsach, więc `TraffitSyncCaller` przestaje być rozpoznawany
# i ląduje jako wymagany parametr QUERY. Ten sam trap co w
# `candidate_activity_summary.py`.

from typing import Any, Dict, NoReturn, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import TraffitReadCaller, TraffitSyncCaller
from app.core.config import settings
from app.core.database import get_db
from app.core.rate_limit import limiter
from app.core.tasks import spawn
from app.tasks.traffit_sync import (
    run_traffit_sync,
    sync_is_running,
    validate_phases,
)

from app.services import job_twin_merge as twin_merge
from app.services import traffit_added_dates_repair as added_dates_repair
from app.services import traffit_file_dates_repair as file_dates_repair
from app.services import traffit_notes_repair as notes_repair
from app.services import traffit_transfer as transfer
from app.services.traffit.client import TraffitConfig
from app.services.traffit_retired import TraffitRetiredError, refuse_traffit
from app.services.traffit_status import read_traffit_status

router = APIRouter()


def _traffit_retired_410(entry: str) -> NoReturn:
    """Wejście do Traffita po 14.10.2026 → 410 z komunikatem dla operatora."""
    try:
        refuse_traffit(entry)
    except TraffitRetiredError as exc:
        raise HTTPException(status_code=status.HTTP_410_GONE, detail=str(exc)) from exc


def _service_rate_limit() -> str:
    """Limit czytany przy KAŻDYM requeście, nie w chwili importu modułu.

    slowapi przyjmuje tu callable, więc zmiana ``SERVICE_ACCOUNT_RATE_LIMIT``
    w Coolify działa po restarcie procesu, a nie dopiero po przebudowie obrazu.
    """
    return settings.SERVICE_ACCOUNT_RATE_LIMIT


@router.post("/sync")
@limiter.limit(_service_rate_limit)
async def trigger_traffit_sync(
    request: Request,
    _caller: TraffitSyncCaller,
    mode: str = Query("delta", pattern="^(delta|full)$"),
    phases: Optional[str] = Query(
        None,
        description=(
            "Comma-separated phase names to run INSTEAD of the whole plan, "
            "e.g. `candidate_files,candidates_cv`. A partial run deliberately "
            "does NOT advance the __daily__/__full__ markers."
        ),
    ),
) -> Dict[str, Any]:
    """Trigger a Traffit sync run in the background. Admin JWT or ``traffit:sync``.

    ``request`` jest w sygnaturze, bo wymaga go slowapi (kubełek limitu per IP).
    """
    _traffit_retired_410("POST /api/admin/traffit/sync")
    if not settings.TRAFFIT_SYNC_ENABLED:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Traffit sync disabled (TRAFFIT_SYNC_ENABLED=false)",
        )
    if sync_is_running():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A Traffit sync is already running",
        )

    # Walidacja MUSI się wydarzyć tutaj, przed `create_task`. Bieg jest
    # fire-and-forget, więc `ValueError` rzucony w tasku poleciałby wyłącznie do
    # logów, a wywołujący dostałby 200 "started" za literówkę w nazwie fazy.
    #
    # Parsowanie po stronie ciała funkcji, nie przez `Annotated`/typ listy —
    # ten moduł ma `@limiter.limit`, a slowapi (#579) w połączeniu z PEP 563
    # potrafi wyprowadzić takie parametry jako WYMAGANE query i zwracać 422 na
    # poprawnym wywołaniu. Ten sam trap opisuje CLAUDE.md.
    selected: Optional[list[str]] = None
    if phases is not None:
        try:
            validated = validate_phases(
                [p.strip() for p in phases.split(",") if p.strip()]
            )
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=str(exc),
            ) from exc
        # Z WALIDATORA, nie z surowego wejścia. Bieg i tak filtruje po zbiorze,
        # więc echo surowej listy pokazywałoby `?phases=a,a` jako dwie pozycje
        # przy jednym realnym przebiegu fazy — odpowiedź jest dla operatora
        # potwierdzeniem tego, co się uruchomi, i ma się z tym zgadzać.
        selected = sorted(validated)

    # Fire-and-forget: a full reconcile can take minutes/hours; don't block the
    # request. Progress is observable via GET /sync/status.
    spawn(run_traffit_sync(mode, phases=selected), f"traffit_sync(mode={mode})")
    out: Dict[str, Any] = {"status": "started", "mode": mode}
    if selected is not None:
        out["phases"] = selected
        out["markers_advanced"] = False
    return out


@router.get("/sync/status")
@limiter.limit(_service_rate_limit)
async def traffit_sync_status(
    request: Request,
    _caller: TraffitReadCaller,
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    return await read_traffit_status(db)


# ── Naprawa notatek z Traffita (29.09.2026) ─────────────────────────────────
#
# Jednorazowa, WYŁĄCZNIE ręczna: najpierw przebieg próbny (`dry_run=true`,
# zero zapisów w notatkach, raport w statusie), potem — po akceptacji liczb
# przez właściciela — zapis (`dry_run=false`). Rekrutacje notatek to osobny
# bieg z kursorem (zapytanie per osoba do Traffita). Szczegóły:
# `app/services/traffit_notes_repair.py`.


def _traffit_configured_or_503() -> None:
    try:
        TraffitConfig.from_env()
    except RuntimeError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Brak konfiguracji Traffita (TRAFFIT_TENANT/CLIENT_ID/CLIENT_SECRET).",
        ) from exc


@router.post("/notes-repair")
@limiter.limit(_service_rate_limit)
async def trigger_traffit_notes_repair(
    request: Request,
    _caller: TraffitSyncCaller,
    dry_run: bool = Query(True),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """Naprawa dat, autorów i wzmianek notatek z Traffita (w tle)."""
    _traffit_retired_410("POST /api/admin/traffit/notes-repair")
    _traffit_configured_or_503()
    reason = notes_repair.spawn_running_guard()
    if reason:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=reason)
    if not dry_run and not await notes_repair.fresh_dry_run_exists(db):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "Najpierw przebieg próbny (dry_run=true) — zapis wymaga raportu "
                "próbnego z ostatnich 7 dni."
            ),
        )
    spawn(
        notes_repair.run_notes_repair(dry_run_mode=dry_run),
        f"traffit_notes_repair(dry_run={dry_run})",
    )
    return {"status": "started", "dry_run": dry_run}


@router.post("/notes-repair/recruitments")
@limiter.limit(_service_rate_limit)
async def trigger_traffit_note_recruitments(
    request: Request,
    _caller: TraffitSyncCaller,
    dry_run: bool = Query(True),
    limit: int = Query(2000, ge=1, le=20000),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """Rekrutacje notatek z aktywności osoby w Traffit (w tle, z kursorem)."""
    _traffit_retired_410("POST /api/admin/traffit/notes-repair/recruitments")
    _traffit_configured_or_503()
    reason = notes_repair.spawn_running_guard()
    if reason:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=reason)
    if not dry_run:
        current = await notes_repair.read_status(db)
        if not current.get("applied"):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    "Najpierw zapis naprawy notatek (notes-repair?dry_run=false) — "
                    "rekrutacje dopasowujemy po source_ref, który ona nadaje."
                ),
            )
    spawn(
        notes_repair.run_recruitment_backfill(dry_run_mode=dry_run, limit=limit),
        f"traffit_note_recruitments(dry_run={dry_run}, limit={limit})",
    )
    return {"status": "started", "dry_run": dry_run, "limit": limit}


@router.get("/notes-repair/status")
@limiter.limit(_service_rate_limit)
async def traffit_notes_repair_status(
    request: Request,
    _caller: TraffitReadCaller,
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    return await notes_repair.read_status(db)


# ── Naprawa dat wgrania plików z Traffita (29.09.2026) ──────────────────────
#
# Jednorazowa, WYŁĄCZNIE ręczna: najpierw przebieg próbny (`dry_run=true`,
# zero zapisów w dokumentach, raport z liczbami i do 20 przykładami w
# statusie), potem — po akceptacji liczb — zapis (`dry_run=false`) partiami
# `limit` osób z Traffita, wznawialny kursorem. Zmienia tylko
# `candidate_documents.uploaded_at`. Szczegóły:
# `app/services/traffit_file_dates_repair.py`.


@router.post("/file-dates-repair")
@limiter.limit(_service_rate_limit)
async def trigger_traffit_file_dates_repair(
    request: Request,
    _caller: TraffitSyncCaller,
    dry_run: bool = Query(True),
    limit: int = Query(2000, ge=1, le=20000),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """Daty wgrania dokumentów z Traffita (w tle, z kursorem)."""
    _traffit_retired_410("POST /api/admin/traffit/file-dates-repair")
    _traffit_configured_or_503()
    reason = file_dates_repair.spawn_running_guard()
    if reason:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=reason)
    if not dry_run and not await file_dates_repair.fresh_dry_run_exists(db):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "Najpierw przebieg próbny (dry_run=true) — zapis wymaga raportu "
                "próbnego z ostatnich 7 dni."
            ),
        )
    spawn(
        file_dates_repair.run_file_dates_repair(dry_run_mode=dry_run, limit=limit),
        f"traffit_file_dates_repair(dry_run={dry_run}, limit={limit})",
    )
    return {"status": "started", "dry_run": dry_run, "limit": limit}


@router.get("/file-dates-repair/status")
@limiter.limit(_service_rate_limit)
async def traffit_file_dates_repair_status(
    request: Request,
    _caller: TraffitReadCaller,
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    return await file_dates_repair.read_status(db)


# ── Naprawa dat dodania kandydatów z Traffita (13.10.2026) ──────────────────
#
# „W bazie od”: jednorazowa, WYŁĄCZNIE ręczna. Najpierw przebieg próbny
# (`dry_run=true`, zero zapisów w kandydatach, raport z liczbami, zakresem dat
# i do 20 przykładami w statusie), potem zapis (`dry_run=false`) stronami listy
# `/employees/`, wznawialny kursorem. Zmienia tylko
# `candidates.source_created_at`. Szczegóły:
# `app/services/traffit_added_dates_repair.py`.


@router.post("/added-dates-repair")
@limiter.limit(_service_rate_limit)
async def trigger_traffit_added_dates_repair(
    request: Request,
    _caller: TraffitSyncCaller,
    dry_run: bool = Query(True),
    pages: int = Query(1000, ge=1, le=5000),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """Daty dodania kandydatów z Traffita (w tle, z kursorem po stronach)."""
    _traffit_retired_410("POST /api/admin/traffit/added-dates-repair")
    _traffit_configured_or_503()
    reason = added_dates_repair.spawn_running_guard()
    if reason:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=reason)
    if not dry_run and not await added_dates_repair.fresh_dry_run_exists(db):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "Najpierw przebieg próbny (dry_run=true) — zapis wymaga raportu "
                "próbnego z ostatnich 7 dni."
            ),
        )
    spawn(
        added_dates_repair.run_added_dates_repair(dry_run_mode=dry_run, pages=pages),
        f"traffit_added_dates_repair(dry_run={dry_run}, pages={pages})",
    )
    return {"status": "started", "dry_run": dry_run, "pages": pages}


@router.get("/added-dates-repair/status")
@limiter.limit(_service_rate_limit)
async def traffit_added_dates_repair_status(
    request: Request,
    _caller: TraffitReadCaller,
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    return await added_dates_repair.read_status(db)


# ── Przeniesienie otwartych rekrutacji z Traffita (11.10.2026) ──────────────
#
# Falami, WYŁĄCZNIE ręcznie: najpierw próba (`dry_run=true`, zero zmian, raport
# per rekrutacja w statusie), potem — po akceptacji raportu przez właściciela —
# wykonanie (`dry_run=false`) dla TEJ SAMEJ fali. Fala to klient (`client_id`)
# albo wskazane rekrutacje (`job_ids`, id NEXUSA po przecinku). Rekrutację,
# która ma bliźniaka założonego w NEXUSIE, bieg pomija, chyba że dostanie
# `include_twins=true` — wtedy otwiera kopię z Traffita z zespołem bliźniaka.
# Szczegóły: `app/services/traffit_transfer.py`.


def _transfer_scope(
    client_id: Optional[int],
    job_ids: Optional[str],
    active_days: int,
    include_twins: bool = False,
) -> transfer.Scope:
    ids: list[int] = []
    for part in (job_ids or "").split(","):
        part = part.strip()
        if not part:
            continue
        if not part.isdigit():
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="job_ids: lista id rekrutacji NEXUSA po przecinku.",
            )
        ids.append(int(part))
    if client_id is None and not ids:
        # Bez fali bieg objąłby wszystkie otwarte rekrutacje z Traffita naraz.
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Podaj falę: client_id albo job_ids.",
        )
    return transfer.Scope(
        client_id=client_id,
        job_ids=tuple(sorted(set(ids))),
        active_days=active_days,
        include_twins=include_twins,
    )


@router.post("/transfer")
@limiter.limit(_service_rate_limit)
async def trigger_traffit_transfer(
    request: Request,
    caller: TraffitSyncCaller,
    dry_run: bool = Query(True),
    client_id: Optional[int] = Query(None, ge=1),
    job_ids: Optional[str] = Query(None, max_length=4000),
    active_days: int = Query(transfer.ACTIVE_DAYS_DEFAULT, ge=1, le=365),
    include_twins: bool = Query(False),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """Przeniesienie fali rekrutacji z Traffita do NEXUSA (w tle)."""
    _traffit_retired_410("POST /api/admin/traffit/transfer")
    _traffit_configured_or_503()
    scope = _transfer_scope(client_id, job_ids, active_days, include_twins)
    if not dry_run and caller.user is None:
        # Otwarcie rekrutacji zapisuje, kto je wykonał (historia, przypisanie
        # prowadzącego) — klucz konta serwisowego może tylko zrobić próbę.
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Przeniesienie wykonuje zalogowany administrator, nie klucz API.",
        )
    reason = transfer.spawn_running_guard()
    if reason:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=reason)
    if not dry_run and not await transfer.fresh_dry_run_exists(db, scope):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "Najpierw próba (dry_run=true) dla tej samej fali — wykonanie "
                "wymaga raportu próbnego z ostatnich 24 godzin."
            ),
        )
    spawn(
        transfer.run_transfer(
            scope=scope,
            dry_run_mode=dry_run,
            actor_user_id=caller.user.id if caller.user is not None else None,
            actor_label=caller.audit_label,
        ),
        f"traffit_transfer(dry_run={dry_run}, scope={scope.key()})",
    )
    return {"status": "started", "dry_run": dry_run, "scope": scope.as_dict()}


@router.get("/transfer/status")
@limiter.limit(_service_rate_limit)
async def traffit_transfer_status(
    request: Request,
    _caller: TraffitReadCaller,
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    return await transfer.read_status(db)


# ── Scalenie rekrutacji-duplikatów po migracji (12.10.2026) ─────────────────
#
# Ten sam request istniał jako rekrutacja założona w NEXUSIE i jako kopia
# z Traffita. Zostaje rekrutacja NEXUSA: pary z kopii przechodzą do niej
# z historią, kopia się zamyka. Próba → wykonanie tego samego zakresu, jak
# przy przeniesieniu. Szczegóły: `app/services/job_twin_merge.py`.


def _merge_scope(job_ids: Optional[str]) -> twin_merge.Scope:
    ids: list[int] = []
    for part in (job_ids or "").split(","):
        part = part.strip()
        if not part:
            continue
        if not part.isdigit():
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="job_ids: lista id kopii z Traffita (id NEXUSA) po przecinku.",
            )
        ids.append(int(part))
    if job_ids is not None and not ids:
        # Pusty parametr nie może znaczyć „wszystkie pary”.
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="job_ids: podaj id albo pomiń parametr (wszystkie pewne pary).",
        )
    return twin_merge.Scope(job_ids=tuple(sorted(set(ids))))


@router.post("/twins-merge")
@limiter.limit(_service_rate_limit)
async def trigger_traffit_twins_merge(
    request: Request,
    caller: TraffitSyncCaller,
    dry_run: bool = Query(True),
    job_ids: Optional[str] = Query(None, max_length=4000),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """Scalenie kopii z Traffita z rekrutacjami NEXUSA (w tle)."""
    _traffit_retired_410("POST /api/admin/traffit/twins-merge")
    scope = _merge_scope(job_ids)
    if not dry_run and caller.user is None:
        # Zamknięcie kopii zapisuje, kto je wykonał — klucz API robi tylko próbę.
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Scalenie wykonuje zalogowany administrator, nie klucz API.",
        )
    reason = twin_merge.spawn_running_guard()
    if reason:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=reason)
    if not dry_run and not await twin_merge.fresh_dry_run_exists(db, scope):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "Najpierw próba (dry_run=true) dla tego samego zakresu — wykonanie "
                "wymaga raportu próbnego z ostatnich 24 godzin."
            ),
        )
    spawn(
        twin_merge.run_merge(
            scope=scope,
            dry_run_mode=dry_run,
            actor_user_id=caller.user.id if caller.user is not None else None,
            actor_label=caller.audit_label,
        ),
        f"traffit_twins_merge(dry_run={dry_run}, scope={scope.key()})",
    )
    return {"status": "started", "dry_run": dry_run, "scope": scope.as_dict()}


@router.get("/twins-merge/status")
@limiter.limit(_service_rate_limit)
async def traffit_twins_merge_status(
    request: Request,
    _caller: TraffitReadCaller,
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    return await twin_merge.read_status(db)
