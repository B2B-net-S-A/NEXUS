"""KPI Panel — „Moje KPI" per zalogowany user.

Liczy lejek rekrutacyjny dla usera wg modelu atrybucji **verifier-anchored**
(decyzja Artura): zasługę za WSZYSTKIE kamienie milowe pary
(kandydat × rekrutacja) — rekomendacja, interview, akceptacja, placement —
dostaje osoba, która przeniosła kandydata na etap `verified` (Zweryfikowany),
niezależnie kto klikał późniejsze etapy. Gdy para nigdy nie przeszła przez
`verified` (przeciągnięta na skróty), dany kamień milowy liczy się temu, kto
wykonał ten konkretny ruch (fallback — ~10% cv_sent, ~29% hired na prod).

Źródło prawdy: `candidate_stages` (żywa tabela) — NIE martwy log
`user_activities`, na którym opierał się stary KPI Coach.

Strefa czasu: Europe/Warsaw (reużyte `period_bounds`/`WARSAW` z kpi_engine).
Czysta biblioteka bez HTTP/DI — wejście `AsyncSession` + `User`, wyjście
frozen dataclassy. Mapowanie na Pydantic robi warstwa API.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Optional

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.kpi_target import KpiRoleDefault, UserKpiTarget
from app.models.user import User, UserRole
from app.services.kpi_catalog import KpiPeriod
from app.services.kpi_engine import WARSAW, period_bounds

# Minimalna liczba weryfikacji w oknie, by pokazać precision (mniej = szum).
_PRECISION_MIN_DENOM = 5
_PRECISION_WINDOW_DAYS = 30
# PR 4 (plan analytics): kotwica atrybucji przychodzi z kanonicznego view
# analytics_first_milestones — bez limitu czasowego (_ANCHOR_LOOKBACK_DAYS
# usunięty; plan §3.2 wskazywał go jako źródło gubienia weryfikatorów).

# Role operacyjne — panel pokazuje się zawsze (reszta tylko gdy ma aktywność).
_OPERATIONAL_ROLES = {
    UserRole.sourcer,
    UserRole.tac,
    UserRole.recruiter,
    UserRole.delivery_lead,
}

# Role z licencją LinkedIn Recruiter → target „5 CV do bazy / dzień".
_CV_TARGET_ROLES = {UserRole.recruiter, UserRole.tac}

# Code-level default targety. DB (`kpi_role_defaults`) nadpisuje; per-user
# override (`user_kpi_targets`) ma najwyższy priorytet. Trzymane też tu, żeby
# panel działał zanim migracja zaseeduje DB.
PANEL_KPI_DEFAULTS: dict[str, dict[UserRole, int]] = {
    "verifications_daily": {
        UserRole.sourcer: 4,
        UserRole.tac: 4,
        UserRole.recruiter: 4,
    },
    "precision_monthly": {
        UserRole.sourcer: 75,
        UserRole.tac: 75,
        UserRole.recruiter: 75,
    },
    "placements_monthly": {
        UserRole.sourcer: 1,
        UserRole.tac: 1,
        UserRole.recruiter: 1,
    },
    "cv_added_daily": {
        UserRole.recruiter: 5,
        UserRole.tac: 5,
    },
}


# ── SQL: verifier-anchored funnel ────────────────────────────────────────────

# Wspólne CTE atrybucji (reużywane przez panel per-user, panel zespołowy
# w `kpi_team.py`, reports per-recruiter i KPI Coach v2 — żeby liczby
# zgadzały się co do jednego). PR 4 planu analytics (2026-07-16): źródłem
# jest kanoniczny view ``analytics_first_milestones`` (migracja 0174/0175) —
# pierwsze osiągnięcie stage'a per (kandydat, job). Zniknął lookback 400 dni
# (plan §3.2: arbitralny cutoff potrafił zgubić właściwego weryfikatora).
# Dla każdej pary (kandydat, job):
#   1) `mf`       — pierwszy ruch na każdy istotny etap (kto + kiedy) = view.
#   2) `anchor`   — weryfikator = first_moved_by etapu `verified`.
#   3) `credited` — credit_user = COALESCE(weryfikator, mover tego kamienia)
#      (plan §4.2: atrybucja = osoba pierwszej weryfikacji; bez weryfikacji
#      wykonawca milestone'u).
# Konsument dokleja własny SELECT … FROM credited.
VERIFIER_ANCHORED_CTE = """
    WITH mf AS (
        SELECT candidate_id, job_id, stage::text AS stage,
               first_moved_by AS first_mover, first_reached_at AS reached_at
        FROM analytics_first_milestones
    ),
    anchor AS (
        SELECT candidate_id, job_id, first_mover AS verifier
        FROM mf
        WHERE stage = 'verified'
    ),
    credited AS (
        SELECT mf.stage, mf.reached_at, mf.candidate_id, mf.job_id,
               COALESCE(a.verifier, mf.first_mover) AS credit_user
        FROM mf
        LEFT JOIN anchor a USING (candidate_id, job_id)
    )
"""

# Per-user: zliczamy kamienie milowe przypisane do :uid w 4 oknach czasu.
_FUNNEL_SQL = text(
    VERIFIER_ANCHORED_CTE
    + """
    SELECT stage,
           count(*) FILTER (WHERE reached_at >= :day_start)   AS d,
           count(*) FILTER (WHERE reached_at >= :week_start)  AS w,
           count(*) FILTER (WHERE reached_at >= :month_start) AS mo,
           count(*) FILTER (WHERE reached_at >= :rolling30)   AS r30
    FROM credited
    WHERE credit_user = :uid
    GROUP BY stage
    """
)

# „5 CV do bazy / dzień" = nowe rekordy kandydatów utworzone przez usera.
# Import masowy (Traffit/TalentRadar) ma created_by NULL → nie liczy się.
_CV_SQL = text(
    """
    SELECT
        count(*) FILTER (WHERE created_at >= :day_start)   AS d,
        count(*) FILTER (WHERE created_at >= :week_start)  AS w,
        count(*) FILTER (WHERE created_at >= :month_start) AS mo
    FROM candidates
    WHERE created_by = :uid
    """
)


# ── Output dataclassy ────────────────────────────────────────────────────────


@dataclass(frozen=True)
class FunnelCounts:
    """Licznik kamienia milowego w trzech oknach (dzień/tydzień/miesiąc)."""

    day: int
    week: int
    month: int


@dataclass(frozen=True)
class PrecisionResult:
    """Precision = rekomendacje ÷ weryfikacje w oknie kroczącym (30 dni).

    `value_pct` jest None gdy mianownik < _PRECISION_MIN_DENOM (za mała próbka
    — pokazujemy „—" zamiast mylącego odsetka).
    """

    value_pct: Optional[float]
    verified: int
    sent: int
    target_pct: int
    window_days: int


@dataclass(frozen=True)
class PanelResult:
    """Komplet „Moje KPI" dla jednego usera w jednym momencie."""

    role: str
    applies: bool
    weryfikacje: FunnelCounts
    rekomendacje: FunnelCounts
    interview_month: int
    akceptacje_month: int
    placementy_month: int
    cv_to_base: Optional[FunnelCounts]
    precision: PrecisionResult
    target_verifications_daily: int
    target_placements_monthly: int
    target_cv_added_daily: Optional[int]
    target_precision_pct: int


# ── Helpers ──────────────────────────────────────────────────────────────────


async def _resolve_target(db: AsyncSession, *, user: User, kpi_id: str) -> int:
    """Target dla (user, kpi_id): user override → role default → code default."""
    row = await db.scalar(
        select(UserKpiTarget.target_value).where(
            UserKpiTarget.user_id == user.id,
            UserKpiTarget.kpi_id == kpi_id,
        )
    )
    if row is not None:
        return int(row)

    row = await db.scalar(
        select(KpiRoleDefault.target_value).where(
            KpiRoleDefault.role == user.role,
            KpiRoleDefault.kpi_id == kpi_id,
        )
    )
    if row is not None:
        return int(row)

    return int(PANEL_KPI_DEFAULTS.get(kpi_id, {}).get(user.role, 0))


def _funnel_counts(row: Optional[dict], *, key_month: str = "mo") -> FunnelCounts:
    if row is None:
        return FunnelCounts(day=0, week=0, month=0)
    return FunnelCounts(
        day=int(row["d"]),
        week=int(row["w"]),
        month=int(row[key_month]),
    )


# ── Główne API ───────────────────────────────────────────────────────────────


async def compute_my_panel(
    db: AsyncSession, *, user: User, now: Optional[datetime] = None
) -> PanelResult:
    """Oblicza „Moje KPI" dla `user` w chwili `now` (default: teraz, Warsaw)."""
    if now is None:
        now = datetime.now(WARSAW)

    day_start, _ = period_bounds(KpiPeriod.day, now)
    week_start, _ = period_bounds(KpiPeriod.week, now)
    month_start, _ = period_bounds(KpiPeriod.month, now)
    rolling30 = now - timedelta(days=_PRECISION_WINDOW_DAYS)

    funnel_params = {
        "uid": user.id,
        "day_start": day_start,
        "week_start": week_start,
        "month_start": month_start,
        "rolling30": rolling30,
    }
    rows = (await db.execute(_FUNNEL_SQL, funnel_params)).mappings().all()
    by_stage: dict[str, dict] = {r["stage"]: dict(r) for r in rows}

    weryfikacje = _funnel_counts(by_stage.get("verified"))
    rekomendacje = _funnel_counts(by_stage.get("cv_sent"))
    interview_month = int(by_stage["interview"]["mo"]) if "interview" in by_stage else 0
    akceptacje_month = (
        int(by_stage["acceptance"]["mo"]) if "acceptance" in by_stage else 0
    )
    placementy_month = int(by_stage["hired"]["mo"]) if "hired" in by_stage else 0

    # Precision — okno kroczące 30 dni (stabilniejsze niż month-to-date).
    verified_30d = int(by_stage["verified"]["r30"]) if "verified" in by_stage else 0
    sent_30d = int(by_stage["cv_sent"]["r30"]) if "cv_sent" in by_stage else 0
    precision_target = await _resolve_target(db, user=user, kpi_id="precision_monthly")
    precision_value: Optional[float] = (
        round(100.0 * sent_30d / verified_30d, 1)
        if verified_30d >= _PRECISION_MIN_DENOM
        else None
    )

    # CV do bazy — tylko dla ról z targetem (recruiter/TAC) lub gdy target ustawiony.
    cv_target = await _resolve_target(db, user=user, kpi_id="cv_added_daily")
    cv_to_base: Optional[FunnelCounts] = None
    if cv_target > 0 or user.role in _CV_TARGET_ROLES:
        cv_params = {
            "uid": user.id,
            "day_start": day_start,
            "week_start": week_start,
            "month_start": month_start,
        }
        cv_row = (await db.execute(_CV_SQL, cv_params)).mappings().one()
        cv_to_base = _funnel_counts(dict(cv_row))

    verifications_target = await _resolve_target(
        db, user=user, kpi_id="verifications_daily"
    )
    placements_target = await _resolve_target(
        db, user=user, kpi_id="placements_monthly"
    )

    total_activity = (
        weryfikacje.month + rekomendacje.month + interview_month + placementy_month
    )
    applies = user.role in _OPERATIONAL_ROLES or total_activity > 0

    return PanelResult(
        role=user.role.value if user.role else "user",
        applies=applies,
        weryfikacje=weryfikacje,
        rekomendacje=rekomendacje,
        interview_month=interview_month,
        akceptacje_month=akceptacje_month,
        placementy_month=placementy_month,
        cv_to_base=cv_to_base,
        precision=PrecisionResult(
            value_pct=precision_value,
            verified=verified_30d,
            sent=sent_30d,
            target_pct=precision_target,
            window_days=_PRECISION_WINDOW_DAYS,
        ),
        target_verifications_daily=verifications_target,
        target_placements_monthly=placements_target,
        target_cv_added_daily=(cv_target if cv_to_base is not None else None),
        target_precision_pct=precision_target,
    )


__all__ = [
    "FunnelCounts",
    "PanelResult",
    "PrecisionResult",
    "PANEL_KPI_DEFAULTS",
    "VERIFIER_ANCHORED_CTE",
    "compute_my_panel",
]
