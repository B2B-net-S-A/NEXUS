"""KPI Panel — „Moje KPI" per zalogowany user.

Liczy lejek rekrutacyjny dla usera wg modelu atrybucji **verifier-anchored**
(decyzja Artura): zasługę za WSZYSTKIE kamienie milowe pary
(kandydat × rekrutacja) — rekomendacja, interview, akceptacja, placement —
dostaje osoba, która przeniosła kandydata na etap `verified` (Zweryfikowany),
niezależnie kto klikał późniejsze etapy. Dla historycznych par bez jawnej
decyzji Priority Work pozostaje dotychczasowy fallback do autora milestone'u.
Proces z kotwicą (zaakceptowany `verified` + `credit_user_id`) nie kredytuje
milestone'ów sprzed niej — kotwica nie odblokowuje historii wstecz. Proces bez
kotwicy nie znika z KPI: milestone dostaje autor ruchu, tak jak przed
wprowadzeniem tego modelu.

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

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User, UserRole
from app.services.kpi_catalog import KpiPeriod
from app.services.kpi_engine import WARSAW, period_bounds
from app.services.kpi_targets import resolve_kpi_targets_bulk

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

# Cele panelu czytamy z JEDNEGO katalogu (`kpi_catalog`) przez resolver
# `kpi_targets` — do 22.09.2026 panel miał własne `PANEL_KPI_DEFAULTS` z innymi
# liczbami niż widget KPI Coach (placementy 1/1/1 vs 2/3/1). Kanoniczne id:
_PANEL_KPI_IDS = (
    "daily_first_verifications",
    "monthly_precision",
    "monthly_placements",
    "daily_new_candidates",
)


# ── SQL: verifier-anchored funnel ────────────────────────────────────────────

# Wspólne CTE atrybucji (reużywane przez panel per-user, panel zespołowy
# w `kpi_team.py`, reports per-recruiter i KPI Coach v2 — żeby liczby
# zgadzały się co do jednego). PR 4 planu analytics (2026-07-16): źródłem
# jest kanoniczny view ``analytics_first_milestones`` (migracja 0174/0175) —
# pierwsze osiągnięcie stage'a per (kandydat, job). Zniknął lookback 400 dni
# (plan §3.2: arbitralny cutoff potrafił zgubić właściwego weryfikatora).
# Dla każdej próby procesu (kandydat, job, attempt):
#   1) `process_windows` — nieprzecinające się okna prób; także voided attempt
#      wyznacza granicę, żeby jego eventy nie przeciekły do kolejnej próby.
#   2) `classified_mf` — pierwszy zaakceptowany milestone w każdym natywnym
#      attempt. Pending/rejected `verified` nie jest kamieniem milowym KPI,
#      a akceptacja pending liczy się od `approved_at`, nie od pierwotnego ruchu.
#   3) `classified_credited` — zamrożone `kpi_eligible=true` (albo obserwacja
#      z importu, patrz niżej) i `credit_user_id`; handoff ownera nigdy nie
#      zmienia creditu.
#
# DECYZJA WŁAŚCICIELA 2026-08-13 — obserwacje z importu LICZĄ SIĘ do KPI.
# Do tej pory obie gałęzie „classified" wymagały `kpi_eligible IS TRUE`, a
# `_open_process_for_external_stage` stempluje każdy proces powstały z importu
# jako `kpi_eligible=False` (`recruitment_process_commands.py:548`). Ponieważ
# 99,5% ruchu w pipelinie pochodzi z Traffita (144 ruchy „manual" na 31 572
# w 90 dni, zmierzone `/api/admin/process-adoption`), reguła zamieniała panel
# firmy w miernik 0,5% jej pracy: kafle pokazywały 18 placementów rocznie przy
# 315 w surowym widoku, a w sierpniu 2026 zeszły do 15 weryfikacji przy 387
# realnych. Kamień milowy przechodził tylko wtedy, gdy wypadł PRZED otwarciem
# procesu obserwacyjnego swojej pary (łapała go wtedy gałąź `legacy_*`), więc
# im świeższy miesiąc, tym mniej było widać — zjazd 92% → 69% → 4%.
#
# Warunek celowo nazywa `origin_kind = 'external_observed'` zamiast po prostu
# zdejmować predykat: `kpi_eligible=False` bywa ustawiane także przez moduł
# priority work jako ŚWIADOME wykluczenie procesu (`priority_work_policy.py:538`
# i `:551`) i te mają nadal nie liczyć się do KPI.
#   4) `classified_fallback` — proces BEZ kotwicy (`classified_anchor`), czyli
#      bez zaakceptowanego `verified` albo bez `credit_user_id`. Zamiast gubić
#      kamień milowy (przed tym CTE dostawał go `COALESCE(verifier, first_mover)`)
#      wracamy do atrybucji sprzed verifier-anchored. Kotwica i fallback wykluczają
#      się nawzajem po `process_id`, więc milestone liczy się dokładnie raz.
#   5) `legacy_mf` / `legacy_credited` — dotychczasowy fallback wyłącznie dla
#      historii sprzed pierwszego sklasyfikowanego procesu. Dzięki temu nowy
#      attempt nie może odziedziczyć milestone'ów ani verifiera z poprzedniego.
#
# WYKLUCZONE PLACEMENTY (0343, `services/placement_exclusions.py`): wiersze
# `hired` par z `placement_exclusions` nie są kredytowane w ŻADNEJ gałęzi —
# `classified_stage_ranked` filtruje je wprost, a `legacy_mf` czyta widok,
# który pomija je w definicji. Tylko `hired`; pozostałe etapy bez zmian.
# Konsument dokleja własny SELECT … FROM credited.
VERIFIER_ANCHORED_CTE = """
    WITH process_windows AS (
        SELECT rp.*,
               LEAD(rp.opened_at) OVER (
                   PARTITION BY rp.candidate_id, rp.job_id
                   ORDER BY rp.attempt_no, rp.id
               ) AS next_opened_at
        FROM recruitment_processes rp
        WHERE rp.opened_at IS NOT NULL
    ),
    first_classified AS (
        SELECT candidate_id, job_id, MIN(opened_at) AS first_opened_at
        FROM process_windows
        WHERE origin_kind IS NOT NULL
          AND origin_kind::text <> 'legacy'
        GROUP BY candidate_id, job_id
    ),
    classified_process AS (
        SELECT *
        FROM process_windows
        WHERE status::text <> 'voided'
          AND origin_kind IS NOT NULL
          AND origin_kind::text <> 'legacy'
    ),
    classified_stage_ranked AS (
        SELECT cp.id AS process_id,
               cs.candidate_id,
               cs.job_id,
               cs.stage::text AS stage,
               cs.moved_by AS first_mover,
               CASE
                   WHEN cs.stage::text = 'verified'
                       THEN COALESCE(cs.approved_at, cs.moved_at)
                   ELSE cs.moved_at
               END AS reached_at,
               ROW_NUMBER() OVER (
                   PARTITION BY cp.id, cs.stage
                   ORDER BY
                       CASE
                           WHEN cs.stage::text = 'verified'
                               THEN COALESCE(cs.approved_at, cs.moved_at)
                           ELSE cs.moved_at
                       END,
                       cs.id
               ) AS rn
        FROM classified_process cp
        JOIN candidate_stages cs
          ON cs.candidate_id = cp.candidate_id
         AND cs.job_id = cp.job_id
         AND cs.moved_at >= cp.opened_at
         AND (cp.next_opened_at IS NULL OR cs.moved_at < cp.next_opened_at)
        WHERE cs.stage::text IN (
                  'verified', 'cv_sent', 'interview',
                  'client_interview', 'acceptance', 'hired'
              )
          AND (
              cs.stage::text <> 'verified'
              OR cs.verification_status::text = 'active'
          )
          -- 0343: „Zatrudniony" pary z listy wykluczeń (seria bez CV) nie jest
          -- placementem. Inne etapy tej pary liczą się bez zmian.
          AND (
              cs.stage::text <> 'hired'
              OR NOT EXISTS (
                  SELECT 1 FROM placement_exclusions pe
                  WHERE pe.candidate_id = cs.candidate_id
                    AND pe.job_id = cs.job_id
              )
          )
    ),
    classified_mf AS (
        SELECT process_id, candidate_id, job_id, stage, first_mover, reached_at
        FROM classified_stage_ranked
        WHERE rn = 1
    ),
    classified_verified AS (
        SELECT process_id, first_mover, reached_at
        FROM classified_mf
        WHERE stage = 'verified'
    ),
    classified_anchor AS (
        SELECT cp.id AS process_id, verified.reached_at
        FROM classified_process cp
        JOIN classified_verified verified ON verified.process_id = cp.id
        WHERE cp.credit_user_id IS NOT NULL
    ),
    classified_credited AS (
        SELECT mf.stage,
               mf.reached_at,
               mf.candidate_id,
               mf.job_id,
               cp.credit_user_id AS credit_user
        FROM classified_mf mf
        JOIN classified_process cp ON cp.id = mf.process_id
        JOIN classified_anchor verified
          ON verified.process_id = mf.process_id
        WHERE (cp.kpi_eligible IS TRUE OR cp.origin_kind::text = 'external_observed')
          AND mf.reached_at >= verified.reached_at
    ),
    classified_fallback AS (
        SELECT mf.stage,
               mf.reached_at,
               mf.candidate_id,
               mf.job_id,
               COALESCE(verified.first_mover, mf.first_mover) AS credit_user
        FROM classified_mf mf
        JOIN classified_process cp ON cp.id = mf.process_id
        LEFT JOIN classified_verified verified
          ON verified.process_id = mf.process_id
        LEFT JOIN classified_anchor anchored
          ON anchored.process_id = mf.process_id
        WHERE (cp.kpi_eligible IS TRUE OR cp.origin_kind::text = 'external_observed')
          AND anchored.process_id IS NULL
    ),
    legacy_mf AS (
        SELECT afm.candidate_id, afm.job_id, afm.stage::text AS stage,
               afm.first_moved_by AS first_mover,
               afm.first_reached_at AS reached_at
        FROM analytics_first_milestones afm
        LEFT JOIN candidate_stages milestone_stage
          ON milestone_stage.id = afm.candidate_stage_id
        LEFT JOIN first_classified fc
          ON fc.candidate_id = afm.candidate_id
         AND fc.job_id = afm.job_id
        WHERE (
                  afm.stage::text <> 'verified'
                  OR milestone_stage.verification_status::text = 'active'
              )
          AND (
              fc.first_opened_at IS NULL
              OR afm.first_reached_at < fc.first_opened_at
          )
    ),
    legacy_process AS (
        SELECT DISTINCT ON (candidate_id, job_id)
               candidate_id, job_id, kpi_eligible
        FROM recruitment_processes
        WHERE origin_kind IS NULL OR origin_kind::text = 'legacy'
        ORDER BY candidate_id, job_id, attempt_no DESC, id DESC
    ),
    legacy_anchor AS (
        SELECT pairs.candidate_id, pairs.job_id,
               verified.first_mover AS verifier,
               verified.reached_at AS verified_at,
               lp.kpi_eligible
        FROM (
            SELECT DISTINCT candidate_id, job_id
            FROM legacy_mf
        ) pairs
        LEFT JOIN legacy_process lp USING (candidate_id, job_id)
        LEFT JOIN legacy_mf verified
          ON verified.candidate_id = pairs.candidate_id
         AND verified.job_id = pairs.job_id
         AND verified.stage = 'verified'
    ),
    legacy_credited AS (
        SELECT mf.stage,
               mf.reached_at,
               mf.candidate_id,
               mf.job_id,
               COALESCE(a.verifier, mf.first_mover) AS credit_user
        FROM legacy_mf mf
        LEFT JOIN legacy_anchor a USING (candidate_id, job_id)
        WHERE a.kpi_eligible IS DISTINCT FROM FALSE
    ),
    credited AS (
        SELECT * FROM classified_credited
        UNION ALL
        SELECT * FROM classified_fallback
        UNION ALL
        SELECT * FROM legacy_credited
    )
"""

# Precyzja (30 dni) = KOHORTA: z par (kandydat, rekrutacja), które osoba
# zweryfikowała w ostatnich 30 dniach, ile doszło potem do „CV wysłane"
# przypisanego tej samej osobie. Licznik i mianownik z tych samych par i tego
# samego okna, więc wynik z definicji nie przekracza 100%.
#
# Do 24.09.2026 licznik brał każde „CV wysłane" z ostatnich 30 dni, także dla
# par zweryfikowanych wcześniej: Insights → Zespół pokazywał 900% (45
# rekomendacji przy 5 weryfikacjach), 200% i 161%. `credit_user IS NULL`
# (kamień bez autora) nie ma wiersza w tabeli, więc tu go pomijamy.
PRECISION_COHORT_CTE = """
    ,
    precision_verified AS (
        SELECT credit_user, candidate_id, job_id, min(reached_at) AS verified_at
        FROM credited
        WHERE stage = 'verified'
          AND reached_at >= :rolling30
          AND credit_user IS NOT NULL
        GROUP BY credit_user, candidate_id, job_id
    ),
    precision_sent AS (
        SELECT credit_user, candidate_id, job_id, max(reached_at) AS last_sent_at
        FROM credited
        WHERE stage = 'cv_sent'
          AND credit_user IS NOT NULL
        GROUP BY credit_user, candidate_id, job_id
    ),
    precision_cohort AS (
        SELECT v.credit_user,
               count(*) AS verified_pairs,
               count(*) FILTER (WHERE s.last_sent_at >= v.verified_at) AS sent_pairs
        FROM precision_verified v
        LEFT JOIN precision_sent s
          ON s.credit_user = v.credit_user
         AND s.candidate_id = v.candidate_id
         AND s.job_id = v.job_id
        GROUP BY v.credit_user
    )
"""

# `r30` niesie liczby kohorty precyzji (tylko dla `verified` i `cv_sent`);
# dla pozostałych etapów 0 — nikt ich nie czyta.
PRECISION_R30_SQL = """
    CASE f.stage
        WHEN 'verified' THEN COALESCE(p.verified_pairs, 0)
        WHEN 'cv_sent' THEN COALESCE(p.sent_pairs, 0)
        ELSE 0
    END
"""

# Per-user: zliczamy kamienie milowe przypisane do :uid w 3 oknach czasu
# + kohortę precyzji z 30 dni.
_FUNNEL_SQL = text(
    VERIFIER_ANCHORED_CTE
    + PRECISION_COHORT_CTE
    + """
    SELECT f.stage, f.d, f.w, f.mo,
           """
    + PRECISION_R30_SQL
    + """ AS r30
    FROM (
        SELECT stage,
               count(*) FILTER (WHERE reached_at >= :day_start)   AS d,
               count(*) FILTER (WHERE reached_at >= :week_start)  AS w,
               count(*) FILTER (WHERE reached_at >= :month_start) AS mo
        FROM credited
        WHERE credit_user = :uid
        GROUP BY stage
    ) f
    LEFT JOIN precision_cohort p ON p.credit_user = :uid
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
    """Precision = z par zweryfikowanych w 30 dniach, ile ma „CV wysłane".

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
    targets = (await resolve_kpi_targets_bulk(db, [user], _PANEL_KPI_IDS))[user.id]
    precision_target = targets["monthly_precision"]
    precision_value: Optional[float] = (
        round(100.0 * sent_30d / verified_30d, 1)
        if verified_30d >= _PRECISION_MIN_DENOM
        else None
    )

    # CV do bazy — tylko gdy osoba ma cel (którakolwiek z jej ról).
    cv_target = targets["daily_new_candidates"]
    cv_to_base: Optional[FunnelCounts] = None
    if cv_target > 0:
        cv_params = {
            "uid": user.id,
            "day_start": day_start,
            "week_start": week_start,
            "month_start": month_start,
        }
        cv_row = (await db.execute(_CV_SQL, cv_params)).mappings().one()
        cv_to_base = _funnel_counts(dict(cv_row))

    verifications_target = targets["daily_first_verifications"]
    placements_target = targets["monthly_placements"]

    total_activity = (
        weryfikacje.month + rekomendacje.month + interview_month + placementy_month
    )
    applies = user.has_any_role(*_OPERATIONAL_ROLES) or total_activity > 0

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
    "PRECISION_COHORT_CTE",
    "PRECISION_R30_SQL",
    "FunnelCounts",
    "PanelResult",
    "PrecisionResult",
    "VERIFIER_ANCHORED_CTE",
    "compute_my_panel",
]
