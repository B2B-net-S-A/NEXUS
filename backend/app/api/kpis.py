"""KPI Coach API.

Endpoint `GET /api/kpis/me/today` — zwraca bieżący progres current_user
względem wszystkich KPI z katalogu. Używane przez widget `MyKpiWidget`
w TopbarV2 i DashboardV2.

Inne endpointy (targets CRUD, historia nudge'y, per-user lookup dla
delivery_leada) dodawane w kolejnych fazach.
"""

from __future__ import annotations

import logging
from typing import List

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import (
    AdminUser,
    CurrentUser,
    OperationalUser,
    RecruiterPlus,
)
from app.core.cache import cache_get, cache_set
from app.core.config import settings
from app.core.database import get_db
from app.models.kpi_nudge_log import KpiNudgeType
from app.models.user import User, UserRole
from app.services.kpi_catalog import KpiPeriod, get_kpi
from app.services.kpi_coach_service import run_scheduled_sweep
from app.services.kpi_coach_service import _try_emit as _try_emit_nudge
from app.services.kpi_engine import KpiResult, evaluate_user_kpis, period_bucket_label
from app.services.kpi_panel import PanelResult, compute_my_panel
from app.services.kpi_team import TeamPanelResult, compute_team_panel

logger = logging.getLogger(__name__)
router = APIRouter()


class KpiResultSchema(BaseModel):
    """DTO zwracany do frontendu. Lustro dla `KpiResult` z kpi_engine."""

    kpi_id: str
    period: str  # "day" | "week" | "month"
    title_pl: str
    description_pl: str
    target: int
    current: int
    progress_pct: float
    state: str  # "on_track" | "ahead" | "behind" | "hit" | "missed"
    deadline_hours_left: float


def _to_schema(kpi_result) -> KpiResultSchema:
    return KpiResultSchema(
        kpi_id=kpi_result.kpi_id,
        period=kpi_result.period.value,
        title_pl=kpi_result.title_pl,
        description_pl=kpi_result.description_pl,
        target=kpi_result.target,
        current=kpi_result.current,
        progress_pct=round(kpi_result.progress_pct, 1),
        state=kpi_result.state,
        deadline_hours_left=round(kpi_result.deadline_hours_left, 2),
    )


# Role, które nie wykonują pracy operacyjnej — nie pokazujemy im widgeta.
# Role, które MAJĄ własne KPI rekrutacyjne. Zapisane jako zbiór pozytywny,
# bo lista zabroniona źle się zachowuje przy schemacie multi-role: użytkownik z
# primary=delivery_lead i secondary=recruiter realnie rekrutuje i POWINIEN
# widzieć swoje KPI, a sprawdzenie "czy jest na liście zabronionych" wyklucza
# go przez samą rolę główną. Pytanie brzmi "czy masz JAKĄKOLWIEK rolę z KPI",
# nie "czy twoja główna rola jest na czarnej liście".
_KPI_BEARING_ROLES = {
    UserRole.tac,
    UserRole.recruiter,
    UserRole.sourcer,
}


@router.get("/me/today", response_model=List[KpiResultSchema])
async def get_my_kpis_today(
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> list[KpiResultSchema]:
    """Bieżący progres current_user względem wszystkich KPI.

    - Filtruje KPI dla których target==0 (rola nie dotyczy).
    - Dla ról nie-operacyjnych (admin, delivery_lead, ...) zwraca pustą
      listę — widget nie powinien im się pokazywać.
    """
    if not current_user.has_any_role(*_KPI_BEARING_ROLES):
        return []

    results = await evaluate_user_kpis(db, user=current_user)
    return [_to_schema(r) for r in results if r.target > 0]


# ── „Moje KPI" panel (verifier-anchored funnel) ────────────────────────────


class FunnelCountsSchema(BaseModel):
    day: int
    week: int
    month: int


class PrecisionSchema(BaseModel):
    value_pct: float | None  # null gdy < 5 weryfikacji w oknie (za mała próbka)
    verified: int
    sent: int
    target_pct: int
    window_days: int


class MyPanelSchema(BaseModel):
    """DTO dla widgetu „Moje KPI" na panelu głównym."""

    role: str
    applies: bool  # czy panel ma się w ogóle pokazać tej roli
    weryfikacje: FunnelCountsSchema
    rekomendacje: FunnelCountsSchema
    interview_month: int
    akceptacje_month: int
    placementy_month: int
    cv_to_base: FunnelCountsSchema | None  # tylko recruiter/TAC
    precision: PrecisionSchema
    target_verifications_daily: int
    target_placements_monthly: int
    target_cv_added_daily: int | None
    target_precision_pct: int


def _panel_to_schema(p: PanelResult) -> MyPanelSchema:
    def _fc(fc) -> FunnelCountsSchema:
        return FunnelCountsSchema(day=fc.day, week=fc.week, month=fc.month)

    return MyPanelSchema(
        role=p.role,
        applies=p.applies,
        weryfikacje=_fc(p.weryfikacje),
        rekomendacje=_fc(p.rekomendacje),
        interview_month=p.interview_month,
        akceptacje_month=p.akceptacje_month,
        placementy_month=p.placementy_month,
        cv_to_base=_fc(p.cv_to_base) if p.cv_to_base is not None else None,
        precision=PrecisionSchema(
            value_pct=p.precision.value_pct,
            verified=p.precision.verified,
            sent=p.precision.sent,
            target_pct=p.precision.target_pct,
            window_days=p.precision.window_days,
        ),
        target_verifications_daily=p.target_verifications_daily,
        target_placements_monthly=p.target_placements_monthly,
        target_cv_added_daily=p.target_cv_added_daily,
        target_precision_pct=p.target_precision_pct,
    )


@router.get("/me/panel", response_model=MyPanelSchema)
async def get_my_panel(
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> MyPanelSchema:
    """„Moje KPI" dla zalogowanego usera: weryfikacje/rekomendacje (dzień/
    tydzień/miesiąc) + interview/akceptacje/placementy (miesiąc) + precision
    (30 dni) + CV do bazy (recruiter/TAC). Atrybucja verifier-anchored —
    zasługa idzie na osobę, która przeniosła kandydata na „Zweryfikowany".
    """
    result = await compute_my_panel(db, user=current_user)
    return _panel_to_schema(result)


# ── „KPI zespołu" panel (verifier-anchored funnel per osoba) ───────────────


class TeamMemberSchema(BaseModel):
    """Lejek jednej osoby za wybrane okno + precision (30 dni)."""

    user_id: int
    name: str
    role: str
    weryfikacje: int
    rekomendacje: int
    interview: int
    akceptacje: int
    placementy: int
    cv_to_base: int
    precision_pct: float | None
    precision_verified_30d: int
    precision_sent_30d: int


class TeamTotalsSchema(BaseModel):
    weryfikacje: int
    rekomendacje: int
    interview: int
    akceptacje: int
    placementy: int
    cv_to_base: int
    precision_pct: float | None
    people: int


class TeamPanelSchema(BaseModel):
    """DTO dla widgetu „KPI zespołu" — wiersz na osobę + suma zespołu."""

    period: str  # "day" | "week" | "month"
    precision_target_pct: int
    rows: List[TeamMemberSchema]
    totals: TeamTotalsSchema


_PERIOD_MAP = {
    "day": KpiPeriod.day,
    "week": KpiPeriod.week,
    "month": KpiPeriod.month,
}

# Widok zespołowy — pełny per-person breakdown dla KAŻDEJ roli operacyjnej.
# Decyzja właściciela 2026-08-07 (sekcja „Statystyki rekrutacji" na /dashboard):
# cały zespół widzi imienne wyniki wszystkich, jak w InfraReporterze. Finance
# i legacy `user` pozostają odcięci (OperationalUser ich nie zawiera).
TeamPanelViewer = OperationalUser


def _team_to_schema(result: TeamPanelResult) -> TeamPanelSchema:
    return TeamPanelSchema(
        period=result.period,
        precision_target_pct=result.precision_target_pct,
        rows=[
            TeamMemberSchema(
                user_id=r.user_id,
                name=r.name,
                role=r.role,
                weryfikacje=r.weryfikacje,
                rekomendacje=r.rekomendacje,
                interview=r.interview,
                akceptacje=r.akceptacje,
                placementy=r.placementy,
                cv_to_base=r.cv_to_base,
                precision_pct=r.precision_pct,
                precision_verified_30d=r.precision_verified_30d,
                precision_sent_30d=r.precision_sent_30d,
            )
            for r in result.rows
        ],
        totals=TeamTotalsSchema(
            weryfikacje=result.totals.weryfikacje,
            rekomendacje=result.totals.rekomendacje,
            interview=result.totals.interview,
            akceptacje=result.totals.akceptacje,
            placementy=result.totals.placementy,
            cv_to_base=result.totals.cv_to_base,
            precision_pct=result.totals.precision_pct,
            people=result.totals.people,
        ),
    )


@router.get("/team/panel", response_model=TeamPanelSchema)
async def get_team_panel(
    _: TeamPanelViewer,
    period: str = "week",
    db: AsyncSession = Depends(get_db),
) -> TeamPanelSchema:
    """„KPI zespołu" — lejek per osoba dla całego zespołu w wybranym oknie.

    Atrybucja verifier-anchored (identyczna z „Moje KPI"), więc kolumny sumują
    się do tych samych liczb, które każdy widzi u siebie. Filtry osoba/rola
    realizuje front na zwróconej liście; backend bierze tylko okno czasu.

    `period`: day | week | month (default week). Cache 120 s per okno.
    """
    kp = _PERIOD_MAP.get(period, KpiPeriod.week)
    cache_key = f"kpis:team:panel:{kp.value}"

    cached = await cache_get(cache_key)
    if cached:
        return TeamPanelSchema(**cached)

    result = await compute_team_panel(db, period=kp)
    schema = _team_to_schema(result)
    await cache_set(cache_key, schema.model_dump(), ttl_seconds=120)
    return schema


@router.get("/users/{user_id}/today", response_model=List[KpiResultSchema])
async def get_user_kpis_today(
    user_id: int,
    current_user: RecruiterPlus,
    db: AsyncSession = Depends(get_db),
) -> list[KpiResultSchema]:
    """Progres KPI usera.

    R0 (plan 2026-07-16): koniec MVP-owego IDOR-a — cudze KPI wymagają
    VIEW_TEAM_KPI (admin / head_of_recruitment / delivery_lead); rekruter
    i sourcer widzą wyłącznie własne. Scoping DL→przypisany zespół dojdzie
    z kanonicznym modelem zespołu (plan PR 4).
    """
    from sqlalchemy import select

    from app.analytics.capabilities import (
        AnalyticsCapability,
        user_has_capability,
    )
    from app.models.user import User

    if user_id != current_user.id and not user_has_capability(
        current_user, AnalyticsCapability.VIEW_TEAM_KPI
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="KPI innego użytkownika wymagają uprawnień zespołowych",
        )

    user = await db.scalar(select(User).where(User.id == user_id))
    if not user or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Użytkownik nie znaleziony",
        )
    results = await evaluate_user_kpis(db, user=user)
    return [_to_schema(r) for r in results if r.target > 0]


# ── Admin: manual trigger for E2E smoke-tests ──────────────────────────────


class SweepCountersSchema(BaseModel):
    users: int
    praise: int
    remind: int
    eod: int
    skipped_dedup: int
    skipped_optout: int


@router.post("/admin/trigger-sweep", response_model=SweepCountersSchema)
async def admin_trigger_kpi_coach_sweep(
    _: AdminUser,
    db: AsyncSession = Depends(get_db),
    force: bool = True,
    target_user_id: int | None = None,
) -> SweepCountersSchema:
    """Admin-only: ręcznie odpala jeden cykl `run_scheduled_sweep`.

    Przydatne do:
    - Smoke-testów po godzinach pracy (domyślnie `force=true` obchodzi
      gate quiet hours 09:00–17:30 Warsaw).
    - Targetowanego testu per user (`target_user_id=N`) — emituje nudge'e
      tylko dla wskazanego usera, np. dla smoke-test account'u Marta.

    Zwraca counters (users processed, praise/remind/eod emitted, skipped).
    """
    counters = await run_scheduled_sweep(db, force=force, target_user_id=target_user_id)
    await db.commit()
    return SweepCountersSchema(**counters)


class DebugFireNudgeResponse(BaseModel):
    emitted: bool
    user_id: int
    kpi_id: str
    nudge_type: str
    period_bucket: str
    notice: str


@router.post("/admin/debug-fire-nudge", response_model=DebugFireNudgeResponse)
async def admin_debug_fire_nudge(
    _: AdminUser,
    target_user_id: int,
    db: AsyncSession = Depends(get_db),
    kpi_id: str = "daily_new_candidates",
    nudge_type: str = "praise_hit",
    current: int = 3,
    target: int = 3,
) -> DebugFireNudgeResponse:
    """**SMOKE TEST ONLY** — wymusza emisję jednego nudge'a end-to-end
    (kpi_nudge_log + Notification + WS event) dla `target_user_id`.

    Audyt M7 PR-05 (P1.15): w produkcji dostępne WYŁĄCZNIE przez break-glass
    (`KPI_COACH_DEBUG_BREAKGLASS`), NIE kasuje logu dedupe (wcześniej DELETE
    niszczyło historię) i NIE zwraca tracebacku (sanitized 500). Jeśli nudge
    dla (user, kpi, type, bucket) już istnieje, dedup zwróci emitted=False —
    użyj innego usera/kpi zamiast czyścić historię.

    Args:
      target_user_id: komu emitować.
      kpi_id: musi być w KPI_CATALOG (np. daily_new_candidates, weekly_cvs_sent).
      nudge_type: praise_hit | remind_behind | eod_summary | streak_bonus.
      current, target: wartości do renderowania szablonu (body będzie mieć "{current}/{target}").
    """
    from datetime import datetime
    from sqlalchemy import select

    from app.services.kpi_coach_service import WARSAW

    # Break-glass: smoke-test emituje realne powiadomienie — w prod tylko za
    # jawną flagą (DEBUG w dev). Bez niej udajemy, że endpoint nie istnieje.
    if not settings.DEBUG and not settings.KPI_COACH_DEBUG_BREAKGLASS:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")

    user = await db.scalar(select(User).where(User.id == target_user_id))
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="user not found"
        )

    kpi_def = get_kpi(kpi_id)
    if kpi_def is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"unknown kpi_id '{kpi_id}'",
        )

    try:
        nudge_enum = KpiNudgeType(nudge_type)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"unknown nudge_type '{nudge_type}'",
        )

    now = datetime.now(WARSAW)
    bucket = period_bucket_label(kpi_def.period, now)

    # Audyt M7 PR-05 (P1.15): historii nudge'y NIE kasujemy — wcześniejszy
    # DELETE "sidestep the dedup UniqueConstraint" niszczył audit trail i
    # pozwalał smoke-testowi dublować realne powiadomienia. Jeśli wpis
    # (user, kpi, type, bucket) już istnieje, emit zwróci emitted=False.

    fake_result = KpiResult(
        kpi_id=kpi_id,
        period=kpi_def.period,
        title_pl=kpi_def.title_pl,
        description_pl=kpi_def.description_pl,
        target=target,
        current=current,
        progress_pct=(100.0 * current / target) if target > 0 else 0.0,
        state="hit" if current >= target else "behind",
        deadline_hours_left=0.0,
    )

    try:
        ok = await _try_emit_nudge(
            db,
            user=user,
            kpi_result=fake_result,
            nudge_type=nudge_enum,
            now=now,
        )
        await db.commit()
    except Exception:
        await db.rollback()
        # Audyt M7 PR-05 (P1.15): traceback/exc_repr NIE wychodzi w response —
        # szczegóły tylko do logów serwera (Sentry i tak złapie exception).
        logger.exception(
            "debug-fire-nudge failed (user_id=%s kpi_id=%s nudge_type=%s)",
            user.id,
            kpi_id,
            nudge_type,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="debug-fire-nudge failed — szczegóły w logach serwera",
        )

    return DebugFireNudgeResponse(
        emitted=bool(ok),
        user_id=user.id,
        kpi_id=kpi_id,
        nudge_type=nudge_type,
        period_bucket=bucket,
        notice="SMOKE TEST — forged KpiResult; dedup log NIE jest czyszczony.",
    )
