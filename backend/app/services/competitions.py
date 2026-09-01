"""Silnik Liga Mistrzów (kwartalne) + Wyścigi Miesięczne (monthly races).

Port formuł z InfraReportera (dynareporter), źródło:
  - kpi.ts:136-142 (calculatePoints)
  - deliveryLead.ts:576-629 (quarterly champions DL)

Formuły:
  - Quarterly DL: hit_ratio >= 30% AND placements >= 3, ORDER BY placements DESC
    LIMIT 3. Nagrody: 5000 / 3000 / 2000 PLN.
  - Quarterly Recruiter (TAC+recruiter+sourcer): min 3 placements.
    Ranking po placements, nagrody jak DL.
  - Monthly Most Recommendations: TOP 1, nagroda 1500 PLN.
  - Monthly Most Placements: TOP 1 z min 2 placementami, nagroda 1500 PLN.
  - Hall of Fame: all-time TOP 5 po placement count.

`freeze_competition(type, period)` zapisuje wynik do `competition_winners` —
snapshot z `frozen_snapshot` JSONB, żeby historia była stabilna.
"""

import logging
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from typing import Iterable, Optional
from zoneinfo import ZoneInfo

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.scheduling import (
    DEFAULT_TZ,
    business_today,
    is_business_day,
    local_month_bounds,
    local_quarter_bounds,
)
from app.models.competition_winner import CompetitionType, CompetitionWinner
from app.models.job import Job, RecruitmentType
from app.models.recruitment_pipeline import CandidateStage, PipelineStage
from app.models.user import User, UserRole
from app.services.insights_scoring_config import (
    get_scoring_config,
    league_points_formula,
)

logger = logging.getLogger(__name__)


# ── Konfiguracja nagród ──────────────────────────────────────────────────

HIT_RATIO_TARGET = 30.0  # % — próg wejścia na podium DL
QUARTERLY_MIN_PLACEMENTS = 3
MONTHLY_RACE_MIN_PLACEMENTS = 2

QUARTERLY_PRIZES_PLN = {1: 5000, 2: 3000, 3: 2000}
MONTHLY_RACE_PRIZE_PLN = 1500
MONTHLY_RACE_PRIZE_NAME = "Voucher 1 500 PLN (Modivo, Douglas, Media Markt)"

# System punktowy Liga Mistrzów Rekrutacja — wagi i warunek udziału są
# KONFIGUROWALNE (decyzja D3, tabela `insights_scoring_config`). Stałe zniknęły
# stąd celowo: dopóki żyły w kodzie, każde strojenie formuły rozdzielającej
# 5000/3000/2000 PLN wymagało deployu i nie zostawiało śladu, kto je zmienił.
# Wartości domyślne (150/15/5) mieszkają w `SCORING_DEFAULTS` — jednym miejscu
# na całe repozytorium.
#
# Progu DL (`QUARTERLY_MIN_PLACEMENTS`) to NIE dotyczy: liga Delivery Leadów
# ma własny, dwuczłonowy warunek (hit ratio ≥ 30% ORAZ ≥ 3 placementy), nie ma
# klucza w konfiguracji i D3 jej nie obejmuje.

# Wymóg tygodniowej aktywności dla Wyścigu Rekomendacji.
MONTHLY_RACE_MIN_VERIFICATIONS_PER_DAY = 4
MONTHLY_RACE_MIN_PRECISION_PCT = 75.0

# Ile pozycji pokazujemy w rankingu wyścigu miesięcznego.
MONTHLY_RACE_RANKING_SIZE = 10

_WARSAW = ZoneInfo(DEFAULT_TZ)


@dataclass
class RankedUser:
    """Jedna pozycja w rankingu konkursu."""

    user_id: int
    name: str
    metric_value: int
    # Dla DL: hit_ratio, dla recruiterów: placement count (= metric_value).
    hit_ratio: Optional[float] = None
    # Dodatkowe metadane do frozen_snapshot.
    extras: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "user_id": self.user_id,
            "name": self.name,
            "metric_value": self.metric_value,
            "hit_ratio": self.hit_ratio,
            **self.extras,
        }


# ── Period helpers ───────────────────────────────────────────────────────


# Granice okresów liczymy w kalendarzu WARSZAWSKIM, nie UTC. Granica UTC
# opisywała polski miesiąc jako [1. dnia 02:00, 1. dnia następnego 02:00), więc
# zdarzenie z pierwszych godzin miesiąca lądowało w miesiącu poprzednim — a te
# same zdarzenia `hired`/`cv_sent` panel KPI rekrutera kubełkuje już po miesiącu
# warszawskim (`kpi_engine.period_bounds`). Dwie powierzchnie liczące to samo
# podawały różne liczby, a wynik konkursu jest potem ZAMRAŻANY niezmiennie,
# z nagrodą pieniężną. Zwracamy dalej UTC-aware datetime, bo porównania idą
# przeciw kolumnom `timestamptz` — poza granicą nic się nie zmienia.


def quarter_bounds(year: int, quarter: int) -> tuple[datetime, datetime]:
    """Zwraca [start, end_exclusive) dla kwartału (Q1..Q4), w UTC."""
    if not 1 <= quarter <= 4:
        raise ValueError(f"Invalid quarter: {quarter}")
    month_start = (quarter - 1) * 3 + 1
    bounds = local_quarter_bounds(date(year, month_start, 1))
    return bounds.start_utc, bounds.end_utc


def month_bounds(year: int, month: int) -> tuple[datetime, datetime]:
    """Zwraca [start, end_exclusive) dla miesiąca kalendarzowego, w UTC."""
    if not 1 <= month <= 12:
        raise ValueError(f"Invalid month: {month}")
    bounds = local_month_bounds(date(year, month, 1))
    return bounds.start_utc, bounds.end_utc


def current_quarter_period(today: Optional[date] = None) -> str:
    today = today or business_today()
    q = (today.month - 1) // 3 + 1
    return f"Q{q} {today.year}"


def current_month_period(today: Optional[date] = None) -> str:
    today = today or business_today()
    return today.strftime("%Y-%m")


def parse_quarter(period: str) -> tuple[int, int]:
    """'Q2 2026' → (2026, 2)."""
    parts = period.split()
    if len(parts) != 2 or not parts[0].startswith("Q"):
        raise ValueError(f"Invalid quarter period: {period}")
    q = int(parts[0][1:])
    year = int(parts[1])
    return year, q


def parse_month(period: str) -> tuple[int, int]:
    """'2026-04' → (2026, 4)."""
    parts = period.split("-")
    if len(parts) != 2:
        raise ValueError(f"Invalid month period: {period}")
    return int(parts[0]), int(parts[1])


# ── Ranking queries ──────────────────────────────────────────────────────


async def _rank_recruiters_by_stage(
    db: AsyncSession,
    *,
    stage: PipelineStage,
    start: datetime,
    end: datetime,
    min_value: int = 0,
    limit: Optional[int] = None,
) -> list[RankedUser]:
    """Ranking milestone'ów z tą samą verifier-anchored atrybucją co KPI.

    Surowe ``CandidateStage.moved_by`` było niespójne z panelem KPI i pozwalało
    osobie klikającej końcowy etap przejąć credit pierwszego verifiera.
    """
    from app.services.kpi_panel import VERIFIER_ANCHORED_CTE

    limit_sql = "LIMIT :limit" if limit else ""
    rows = (
        await db.execute(
            text(
                VERIFIER_ANCHORED_CTE
                + f"""
                SELECT u.id, u.name, u.role::text AS role, count(*) AS cnt
                FROM credited c
                JOIN users u ON u.id = c.credit_user
                WHERE c.stage = :stage
                  AND c.reached_at >= :start
                  AND c.reached_at < :end
                  AND (
                      u.role::text IN ('sourcer', 'tac', 'recruiter')
                      OR u.roles ?| ARRAY['sourcer', 'tac', 'recruiter']
                  )
                  AND u.is_active IS TRUE
                GROUP BY u.id, u.name, u.role
                HAVING count(*) >= :min_value
                -- Remis rozstrzyga `u.id`, NIE `u.name`: pod musl porównanie
                -- tekstu jest porządkiem bajtowym, więc „Łukasz" przegrywał
                -- z „Zbigniewem" ZAWSZE — a pierwszy wiersz tego rankingu to
                -- nazwisko przypisane do nagrody, potem zamrażane niezmiennie.
                ORDER BY count(*) DESC, u.id ASC
                {limit_sql}
                """
            ),
            {
                "stage": stage.value,
                "start": start,
                "end": end,
                "min_value": min_value,
                **({"limit": limit} if limit else {}),
            },
        )
    ).all()
    return [
        RankedUser(
            user_id=r.id,
            name=r.name,
            metric_value=int(r.cnt),
            extras={"role": str(r.role)},
        )
        for r in rows
    ]


async def _rank_recruiters_by_points(
    db: AsyncSession,
    *,
    start: datetime,
    end: datetime,
    weights: dict[str, int],
    min_placements: int = 0,
    limit: Optional[int] = None,
) -> list[RankedUser]:
    """Ranking po systemie punktowym; wagi przychodzą z konfiguracji (D3).

    PR 4 (plan analytics §3.2): konkursy używają TEJ SAMEJ funkcji milestone
    i atrybucji co KPI — pierwsze osiągnięcie stage'a per (kandydat, job)
    z atrybucją verifier-anchored (VERIFIER_ANCHORED_CTE), zamiast surowego
    `moved_by` liczonego per KAŻDY ruch. „Weryfikacje" = stage `verified`
    (wcześniej: new/screening — inna definicja niż wszędzie indziej).

    **Niezakwalifikowani NIE wypadają z listy** — dostają `qualified=False`
    i powód. Twardy `continue` sprawiał, że osoba bez wymaganego placementu
    znikała z rankingu bez śladu, więc jedyną informacją, jaką dostawała, było
    „nie ma cię tu". Oryginał (`competitions.ts:107-137`) pokazywał ją na
    pomarańczowo z adnotacją „(brakuje placementu)". Nagrodę filtruje
    `qualified_for_award`, wołane przy każdym wyprowadzeniu podium.

    Zwraca RankedUser z metric_value=points i extras={placements, interviews,
    recommendations, verifications, role, qualified, required_placements,
    disqualification_reasons}."""
    from app.services.kpi_panel import VERIFIER_ANCHORED_CTE

    rows = (
        await db.execute(
            text(
                VERIFIER_ANCHORED_CTE
                + """
                SELECT u.id, u.name, u.role::text AS role, c.stage,
                       count(*) AS cnt
                FROM credited c
                JOIN users u ON u.id = c.credit_user
                WHERE c.reached_at >= :start
                  AND c.reached_at < :end
              AND (
                  u.role::text IN ('sourcer', 'tac', 'recruiter')
                  OR u.roles ?| ARRAY['sourcer', 'tac', 'recruiter']
              )
                  AND u.is_active IS TRUE
                GROUP BY u.id, u.name, u.role, c.stage
                """
            ),
            {"start": start, "end": end},
        )
    ).all()

    per_user: dict[int, dict] = {}
    for r in rows:
        bucket = per_user.setdefault(
            r.id,
            {
                "name": r.name,
                "role": r.role,
                "placements": 0,
                "interviews": 0,
                "recommendations": 0,
                "verifications": 0,
            },
        )
        cnt = int(r.cnt)
        if r.stage == "hired":
            bucket["placements"] += cnt
        elif r.stage == "interview":
            # D3: składnik „interview" liczy stage `interview`, NIE
            # `client_interview`. Import z Traffita nie mapuje
            # `client_interview` na nic (`traffit/mappers.py:404-449`), więc
            # ten składnik formuły był W PRAKTYCE ZAWSZE ZEROWY — przy
            # nagrodach 5000/3000/2000 PLN liczonych z tej sumy.
            bucket["interviews"] += cnt
        elif r.stage == "cv_sent":
            bucket["recommendations"] += cnt
        elif r.stage == "verified":
            bucket["verifications"] += cnt

    ranked: list[RankedUser] = []
    for user_id, data in per_user.items():
        points = (
            data["placements"] * weights["placement"]
            + data["interviews"] * weights["interview"]
            + data["recommendations"] * weights["recommendation"]
        )
        reasons: list[str] = []
        if data["placements"] < min_placements:
            reasons.append("MIN_PLACEMENTS_NOT_MET")
        ranked.append(
            RankedUser(
                user_id=user_id,
                name=data["name"],
                metric_value=points,
                extras={
                    "role": data["role"],
                    "placements": data["placements"],
                    "interviews": data["interviews"],
                    "recommendations": data["recommendations"],
                    "verifications": data["verifications"],
                    "qualified": not reasons,
                    "required_placements": min_placements,
                    "disqualification_reasons": reasons,
                },
            )
        )

    # Remis rozstrzyga `user_id`, jak w rankingach SQL-owych obok. Bez jawnego
    # tie-breaku kolejność brała się z kolejności wierszy zwróconych przez bazę
    # (zapytanie nie ma ORDER BY), więc przy równych punktach podium mogło się
    # różnić między odczytami — a jego pierwszy wiersz to nazwisko przypisane
    # do nagrody, potem zamrażane niezmiennie.
    ranked.sort(key=lambda r: (-r.metric_value, r.user_id))
    if limit:
        ranked = ranked[:limit]
    return ranked


# ── Countdown helpers ───────────────────────────────────────────────────


def days_left_in_quarter(today: Optional[date] = None) -> int:
    today = today or business_today()
    q = (today.month - 1) // 3 + 1
    end_month = q * 3
    if end_month == 12:
        end = date(today.year + 1, 1, 1)
    else:
        end = date(today.year, end_month + 1, 1)
    return max((end - today).days, 0)


def days_left_in_month(today: Optional[date] = None) -> int:
    today = today or business_today()
    if today.month == 12:
        end = date(today.year + 1, 1, 1)
    else:
        end = date(today.year, today.month + 1, 1)
    return max((end - today).days, 0)


async def _rank_dls_by_placements(
    db: AsyncSession,
    *,
    start: datetime,
    end: datetime,
    min_placements: int = QUARTERLY_MIN_PLACEMENTS,
    limit: Optional[int] = None,
) -> list[RankedUser]:
    """Ranking DL-i po placementach w okresie.

    Używa `Job.delivery_lead_id` bezpośrednio. Dla Jobów bez `delivery_lead_id`
    stosuje fallback przez `delivery_lead_client_assignments.is_head=true`
    (zobacz reports._dl_head_fallback_map)."""
    from app.api.reports import _dl_head_fallback_map, _resolve_dl_id

    fallback = await _dl_head_fallback_map(db)

    # Placements per Job w okresie.
    placements_q = (
        select(
            Job.id.label("job_id"),
            Job.delivery_lead_id,
            Job.client_id,
            func.count(CandidateStage.id).label("cnt"),
        )
        .join(CandidateStage, CandidateStage.job_id == Job.id)
        .where(
            CandidateStage.stage == PipelineStage.hired,
            CandidateStage.moved_at >= start,
            CandidateStage.moved_at < end,
            Job.recruitment_type == RecruitmentType.body_leasing,
        )
        .group_by(Job.id, Job.delivery_lead_id, Job.client_id)
    )
    rows = (await db.execute(placements_q)).all()
    placements_by_dl: dict[int, int] = {}
    for r in rows:
        dl_id = _resolve_dl_id(r.delivery_lead_id, r.client_id, fallback)
        if dl_id is None:
            continue
        placements_by_dl[dl_id] = placements_by_dl.get(dl_id, 0) + int(r.cnt)

    # Requests per DL (dla hit_ratio).
    req_q = select(Job.id, Job.delivery_lead_id, Job.client_id).where(
        Job.recruitment_type == RecruitmentType.body_leasing,
        Job.created_at >= start,
        Job.created_at < end,
    )
    req_rows = (await db.execute(req_q)).all()
    requests_by_dl: dict[int, int] = {}
    for r in req_rows:
        dl_id = _resolve_dl_id(r.delivery_lead_id, r.client_id, fallback)
        if dl_id is None:
            continue
        requests_by_dl[dl_id] = requests_by_dl.get(dl_id, 0) + 1

    # Users
    dl_ids = set(placements_by_dl.keys()) | set(requests_by_dl.keys())
    if not dl_ids:
        return []
    users_rows = (
        await db.execute(
            select(User.id, User.name).where(
                User.id.in_(dl_ids),
                User.is_active == True,  # noqa: E712
                User.role == UserRole.delivery_lead,
            )
        )
    ).all()
    name_map = {u.id: u.name for u in users_rows}

    ranked: list[RankedUser] = []
    for dl_id, placements in placements_by_dl.items():
        if placements < min_placements:
            continue
        if dl_id not in name_map:
            continue
        requests = requests_by_dl.get(dl_id, 0)
        hit_ratio = round(placements / requests * 100, 1) if requests else 0.0
        if hit_ratio < HIT_RATIO_TARGET:
            continue
        ranked.append(
            RankedUser(
                user_id=dl_id,
                name=name_map[dl_id],
                metric_value=placements,
                hit_ratio=hit_ratio,
                extras={"requests": requests},
            )
        )

    ranked.sort(key=lambda r: r.metric_value, reverse=True)
    if limit:
        ranked = ranked[:limit]
    return ranked


# ── Public API: live rankings (bez zapisu) ──────────────────────────────


async def quarterly_champions_dl(db: AsyncSession, period: str) -> list[RankedUser]:
    year, q = parse_quarter(period)
    start, end = quarter_bounds(year, q)
    return await _rank_dls_by_placements(db, start=start, end=end, limit=10)


def required_placements_for_quarter(
    year: int,
    quarter: int,
    config: dict[str, int],
    today: Optional[date] = None,
) -> int:
    """Warunek udziału w Lidze — PROGRESYWNY wg miesiąca kwartału (D3).

    Płaskie „3 placementy" znaczyło, że przez pierwsze dwa miesiące kwartału
    ranking pokazywał podium wyliczone z warunku, którego przy tym tempie
    nie dało się jeszcze spełnić — nikt nie kwalifikował się w styczniu, bo
    styczeń nie zdążył dać trzech placementów. Oryginał
    (`competitions.ts`, „Warunek udziału") liczy `monthInQuarter`: 1 / 2 / 3.

    Kwartał ZAMKNIĘTY dostaje próg trzeciego miesiąca — pełny kwartał ocenia
    się pełnym warunkiem, inaczej patrząc wstecz zobaczylibyśmy kwalifikacje
    przyznane taryfą ulgową ze stycznia.
    """
    today = today or business_today()
    current = ((today.month - 1) // 3 + 1, today.year)
    if (quarter, year) == current:
        month_in_quarter = ((today.month - 1) % 3) + 1
    elif (year, quarter) < (today.year, current[0]):
        month_in_quarter = 3
    else:
        # Kwartał, który się jeszcze nie zaczął: próg pierwszego miesiąca.
        # Zero nie wchodzi w grę — brak warunku udziału to inna reguła gry,
        # nie „warunek jeszcze nieosiągalny".
        month_in_quarter = 1
    return int(config[f"league_min_placements_month{month_in_quarter}"])


async def quarterly_champions_recruiter(
    db: AsyncSession, period: str
) -> list[RankedUser]:
    """Liga Mistrzów Rekrutacja — ranking punktowy z wagami z konfiguracji.

    Zwraca CAŁY ranking, także niezakwalifikowanych (`qualified=False`).
    `limit=10` zniknęło świadomie: przy zachowanym limicie osoba z nagrodą
    mogła wypaść z wyniku wypchnięta przez kogoś głośniejszego, kto warunku
    udziału nie spełnia — dokładnie ten defekt, który w Wyścigu Rekomendacji
    rozwiązuje podwójny ROW_NUMBER. Podium i tak tnie `qualified_for_award`,
    a populacja to kilkadziesiąt osób, nie tysiące.
    """
    year, q = parse_quarter(period)
    start, end = quarter_bounds(year, q)
    config = await get_scoring_config(db)
    return await _rank_recruiters_by_points(
        db,
        start=start,
        end=end,
        weights=league_points_formula(config),
        min_placements=required_placements_for_quarter(year, q, config),
        limit=None,
    )


async def monthly_most_recommendations(
    db: AsyncSession, period: str
) -> list[RankedUser]:
    year, month = parse_month(period)
    start, end = month_bounds(year, month)
    required_verifications = (
        MONTHLY_RACE_MIN_VERIFICATIONS_PER_DAY
        * business_days_elapsed_in_month(year, month)
    )
    from app.services.kpi_panel import VERIFIER_ANCHORED_CTE

    # Warunki nagrody liczymy jako kolumnę `qualified`, NIE w HAVING: HAVING
    # wycinałby niezakwalifikowanych z samego RANKINGU, więc widget „Wyścig
    # Rekomendacji" świecił pustką póki nikt nie dobił progu. Nagrodę i tak
    # filtruje `qualified_for_award`.
    # Podwójny ROW_NUMBER, bo LIMIT dotyczy teraz listy wyświetlanej: bierzemy
    # TOP N do pokazania **oraz** TOP N zakwalifikowanych, żeby ktoś z nagrodą
    # nie wypadł z wyniku wypchnięty przez głośniejszą, niekwalifikującą się
    # osobę. Werdykt nagrodowy zostaje taki sam jak przed zmianą.
    rows = (
        await db.execute(
            text(
                VERIFIER_ANCHORED_CTE
                + """
                , race_totals AS (
                    SELECT u.id, u.name, u.role::text AS role,
                           count(*) FILTER (
                               WHERE c.stage = 'verified'
                           ) AS verifications,
                           count(*) FILTER (
                               WHERE c.stage = 'cv_sent'
                           ) AS recommendations,
                           (
                               count(*) FILTER (WHERE c.stage = 'verified')
                                   >= :required_verifications
                               AND 100.0 * count(*) FILTER (WHERE c.stage = 'cv_sent')
                                   >= CAST(:min_precision_pct AS NUMERIC)
                                      * count(*) FILTER (WHERE c.stage = 'verified')
                           ) AS qualified
                    FROM credited c
                    JOIN users u ON u.id = c.credit_user
                    WHERE c.reached_at >= :start
                      AND c.reached_at < :end
                      AND c.stage IN ('verified', 'cv_sent')
                      AND (
                          u.role::text IN ('sourcer', 'tac', 'recruiter')
                          OR u.roles ?| ARRAY['sourcer', 'tac', 'recruiter']
                      )
                      AND u.is_active IS TRUE
                    GROUP BY u.id, u.name, u.role
                    HAVING count(*) FILTER (WHERE c.stage = 'cv_sent') >= 1
                ),
                race_ranked AS (
                    -- Remis rozstrzyga `id`, NIE `name` (patrz komentarz przy
                    -- `_rank_recruiters_by_stage`): tie-break po tekście pod
                    -- musl systematycznie wypycha nazwy z polskimi
                    -- diakrytykami na koniec, a tu decyduje o nagrodzie
                    -- i o cięciu TOP-10.
                    SELECT t.*,
                           ROW_NUMBER() OVER (
                               ORDER BY t.recommendations DESC, t.id ASC
                           ) AS display_rank,
                           ROW_NUMBER() OVER (
                               PARTITION BY t.qualified
                               ORDER BY t.recommendations DESC, t.id ASC
                           ) AS rank_in_group
                    FROM race_totals t
                )
                SELECT id, name, role, verifications, recommendations, qualified
                FROM race_ranked
                WHERE display_rank <= :ranking_size
                   OR (qualified AND rank_in_group <= :ranking_size)
                ORDER BY recommendations DESC, id ASC
                """
            ),
            {
                "start": start,
                "end": end,
                "required_verifications": required_verifications,
                "min_precision_pct": MONTHLY_RACE_MIN_PRECISION_PCT,
                "ranking_size": MONTHLY_RACE_RANKING_SIZE,
            },
        )
    ).all()

    ranked: list[RankedUser] = []
    for row in rows:
        verified = int(row.verifications)
        recommendations = int(row.recommendations)
        precision_pct = (
            round(100.0 * recommendations / verified, 1) if verified else 0.0
        )
        # Powody liczone bez zaokrąglenia, żeby nie rozjechały się z kolumną
        # `qualified` (round(74.999, 1) == 75.0, a SQL widzi 74.999 < 75).
        reasons: list[str] = []
        if verified < required_verifications:
            reasons.append("MIN_VERIFICATIONS_NOT_MET")
        if 100.0 * recommendations < MONTHLY_RACE_MIN_PRECISION_PCT * verified:
            reasons.append("MIN_PRECISION_NOT_MET")
        ranked.append(
            RankedUser(
                user_id=row.id,
                name=row.name,
                metric_value=recommendations,
                extras={
                    "role": str(row.role),
                    "verifications": verified,
                    "recommendations": recommendations,
                    "precision_pct": precision_pct,
                    "required_verifications": required_verifications,
                    "qualified": bool(row.qualified) and not reasons,
                    "disqualification_reasons": reasons,
                },
            )
        )
    return ranked


def business_days_elapsed_in_month(
    year: int, month: int, today: Optional[date] = None
) -> int:
    """Dni robocze, które upłynęły w wybranym miesiącu.

    „Dzień roboczy" to ta sama definicja co w reszcie systemu — Pon–Pt **minus**
    polskie święta ustawowe (`app.core.scheduling.is_business_day`). Bez tego
    próg „4 weryfikacje / dzień roboczy" liczyłby np. styczeń jako 22 dni zamiast
    20 i wykluczał z nagrody osobę, która trafiła w target każdego realnego dnia.
    """
    today = today or business_today()
    # Ostatni dzień miesiąca liczymy z kalendarza, NIE z `month_bounds`:
    # tamten zwraca granicę warszawską przeliczoną do UTC (1.09 00:00 lokalnie
    # = 31.08 22:00Z), więc odjęcie doby dałoby 30., a nie 31. sierpnia.
    next_first = date(year + 1, 1, 1) if month == 12 else date(year, month + 1, 1)
    month_last = next_first - timedelta(days=1)
    if (year, month) == (today.year, today.month):
        last = min(today, month_last)
    elif (year, month) < (today.year, today.month):
        last = month_last
    else:
        return 0
    cursor = date(year, month, 1)
    count = 0
    while cursor <= last:
        # Południe lokalne: `is_business_day` czyta datę kalendarzową po
        # konwersji do strefy, więc punkt w środku doby jest odporny na DST.
        if is_business_day(datetime.combine(cursor, time(12), tzinfo=_WARSAW)):
            count += 1
        cursor += timedelta(days=1)
    return count


def qualified_for_award(ranked: list[RankedUser]) -> list[RankedUser]:
    """Return entries eligible for an award while preserving displayed ranking."""
    return [r for r in ranked if r.extras.get("qualified", True)]


async def monthly_most_placements(db: AsyncSession, period: str) -> list[RankedUser]:
    year, month = parse_month(period)
    start, end = month_bounds(year, month)
    return await _rank_recruiters_by_stage(
        db,
        stage=PipelineStage.hired,
        start=start,
        end=end,
        min_value=MONTHLY_RACE_MIN_PLACEMENTS,
        limit=10,
    )


# Role, które WCHODZĄ do Hall of Fame. Świadomie SZERSZE niż w wyścigach
# (`_rank_recruiters_by_stage`: sourcer/tac/recruiter): po przejściu na
# atrybucję D2 placement przypisuje się osobie, która PRZESUNĘŁA etap, a etap
# „Zatrudniony" domyka w tej firmie także delivery. Wąski filtr wycinałby
# 69 z 314 placementów ostatniego roku (10 osób delivery z 2186 weryfikacjami)
# — czyli ludzi, którzy tę pracę realnie wykonali.
#
# Konta ADMINISTRACYJNE zostają poza rankingiem i to jest cała różnica między
# „kto dowiózł" a „kto kliknął": w ostatnim roku 5 kont `admin` zebrało
# 147 z 314 placementów przy CZTERECH weryfikacjach łącznie. To podpis
# masowego domykania pipeline'u, a nie dorobku rekrutacyjnego — dokładnie ta
# patologia, przed którą broni verifier-anchored atrybucja w wyścigach
# (patrz docstring `_rank_recruiters_by_stage`). Tutaj zamyka ją filtr ról,
# bo Hall of Fame nie wypłaca nagród i może pozwolić sobie na prostszą regułę.
# Kod definicji w odpowiedzi — DOKŁADNIE ten sam string co
# `placements_definition` w `/api/insights/charts/placement-analysis`,
# `/api/insights/board` i banerze kampanii. Cały sens tego pola polega na tym,
# że konsument może PORÓWNAĆ dwa kody i dostać odpowiedź „ta sama reguła".
# Własny wariant („..._by_mover") wyglądałby na precyzyjniejszy, a dawałby
# maszynowo „różne" tam, gdzie reguła jest identyczna — czyli odwrotność tego,
# do czego to pole służy. Rozjazdu pilnuje test.
HALL_OF_FAME_ATTRIBUTION = "first_hired_per_candidate_job"


HALL_OF_FAME_ROLES = [
    "sourcer",
    "tac",
    "recruiter",
    "delivery_lead",
    "head_of_recruitment",
]


@dataclass
class HallOfFameScope:
    """Ile dorobku stoi POZA rankingiem — lista bez tego czyta się jak komplet."""

    ranked_placements: int
    outside_role_placements: int
    unattributed_placements: int
    # Mianownik dla „TOP 5". Bez niego pod listą pięciu wierszy stoi liczba
    # placementów, której te wiersze NIE sumują — czyli ten sam defekt co
    # „donut nie sumuje się do kafla nad nim".
    ranked_people: int
    roles: list[str]

    def to_dict(self) -> dict:
        return {
            "ranked_placements": self.ranked_placements,
            "outside_role_placements": self.outside_role_placements,
            "unattributed_placements": self.unattributed_placements,
            "ranked_people": self.ranked_people,
            "roles": self.roles,
            "attribution": HALL_OF_FAME_ATTRIBUTION,
        }


# Wspólny predykat ról — jeden literał dla rankingu i dla licznika „poza
# rankingiem". Rozjazd między nimi dałby sumę, która się nie domyka.
_HOF_ROLE_PREDICATE = """
    (
        u.role::text = ANY(:roles)
        OR u.roles ?| :roles
    )
"""


async def hall_of_fame_with_scope(
    db: AsyncSession, limit: int = 5
) -> tuple[list[RankedUser], HallOfFameScope]:
    """Ranking wszech czasów wg definicji D2 — jak „Analiza placementów".

    ATRYBUCJA: `analytics_first_milestones.first_moved_by`, czyli osoba, która
    przesunęła parę (kandydat, oferta) na etap „Zatrudniony" PIERWSZY raz.
    Ta sama reguła, którą stosuje `/api/insights/charts/placement-analysis`
    i tabela „Performance per osoba" — dzięki temu trzy liczby podpisane
    „placementy" na jednym ekranie znaczą to samo.

    ŚWIADOMA RÓŻNICA WOBEC WYŚCIGÓW. `monthly_most_placements` i mistrzowie
    kwartału liczą verifier-anchored (`_rank_recruiters_by_stage`) i tak
    zostaje: tamte WYPŁACAJĄ nagrody (1500 zł / 10 000 zł) i mają zamrożoną
    historię, więc zmiana ich formuły przesuwałaby pieniądze. Hall of Fame nie
    ma puli nagród ani ani jednego zamrożonego okresu, więc może iść za
    kanoniczną definicją D2. UI mówi o tej różnicy wprost.

    BEZ FILTRA `is_active`. Ranking WSZECH CZASÓW mówi, co ktoś osiągnął —
    odejście z firmy tego nie cofa. Zgodnie z tabelą „Performance per osoba"
    obok, która zostawia byłych pracowników z chipem. `is_active` wraca
    w `extras`, żeby UI mogło ich oznaczyć zamiast ukryć.

    JEDNO ZAPYTANIE na listę I liczniki. Dwa osobne skany widoku biegłyby
    w READ COMMITTED na DWÓCH snapshotach, więc zapis między nimi rozjeżdżałby
    listę z podpisem pod nią — a podpis mówi właśnie, ile placementów ta lista
    obejmuje. To ta sama reguła, przez którą kafle w innych sekcjach są foldem
    po tej samej liście, którą renderują, a nie drugim zapytaniem.
    """
    rows = (
        await db.execute(
            text(
                f"""
                WITH hired AS (
                    SELECT fm.first_moved_by AS uid
                    FROM analytics_first_milestones fm
                    WHERE fm.stage::text = 'hired'
                ),
                classified AS (
                    SELECT h.uid,
                           u.id   AS user_id,
                           u.name AS name,
                           u.is_active,
                           -- `COALESCE(..., FALSE)`, nie `NOT (predykat)`:
                           -- kamień przypisany do konta, którego JUŻ NIE MA
                           -- w `users`, ma predykat NULL i wypadałby z OBU
                           -- kubełków przez trójwartościową logikę. Suma
                           -- trzech liczb ma się domykać do wszystkich
                           -- placementów, bo inaczej podpis „poza rankingiem"
                           -- jest po cichu zaniżony.
                           COALESCE({_HOF_ROLE_PREDICATE}, FALSE) AS in_scope
                    FROM hired h
                    LEFT JOIN users u ON u.id = h.uid
                ),
                totals AS (
                    SELECT
                        count(*) FILTER (WHERE in_scope)              AS ranked,
                        count(*) FILTER (
                            WHERE uid IS NOT NULL AND NOT in_scope
                        )                                            AS outside_role,
                        count(*) FILTER (WHERE uid IS NULL)          AS unattributed,
                        count(DISTINCT user_id) FILTER (WHERE in_scope)
                                                                     AS ranked_people
                    FROM classified
                ),
                ranking AS (
                    SELECT user_id, name, is_active, count(*) AS cnt
                    FROM classified
                    WHERE in_scope
                    GROUP BY user_id, name, is_active
                    -- Tie-break po `user_id`, nie po nazwie — jak w pozostałych
                    -- rankingach; porządek bajtowy pod musl nie jest neutralny.
                    ORDER BY count(*) DESC, user_id ASC
                    LIMIT :limit
                )
                SELECT r.user_id, r.name, r.is_active, r.cnt,
                       t.ranked, t.outside_role, t.unattributed, t.ranked_people
                FROM totals t
                LEFT JOIN ranking r ON TRUE
                ORDER BY r.cnt DESC NULLS LAST, r.user_id ASC
                """
            ),
            {"limit": limit, "roles": HALL_OF_FAME_ROLES},
        )
    ).all()

    # `totals` to agregat bez GROUP BY, więc zawsze daje dokładnie jeden
    # wiersz, a `LEFT JOIN ranking ON TRUE` go zachowuje — nawet gdy ranking
    # jest pusty (wtedy `user_id IS NULL`). Pusty wynik znaczy więc, że
    # zapytanie przestało mieć ten kształt.
    #
    # Podnosimy błąd zamiast zwracać zera: zera wyrenderowałyby się jako
    # „nikt nie ma placementu", czyli awaria udająca wynik. Sekcja pokazuje
    # wtedy komunikat z ponowieniem — to jest uczciwa odpowiedź.
    if not rows:
        raise RuntimeError(
            "hall_of_fame: zapytanie nie zwróciło wiersza `totals` — "
            "kształt SQL-a przestał gwarantować agregat bez GROUP BY"
        )
    head = rows[0]
    scope = HallOfFameScope(
        ranked_placements=int(head.ranked or 0),
        outside_role_placements=int(head.outside_role or 0),
        unattributed_placements=int(head.unattributed or 0),
        ranked_people=int(head.ranked_people or 0),
        roles=list(HALL_OF_FAME_ROLES),
    )
    ranked = [
        RankedUser(
            user_id=r.user_id,
            name=r.name,
            metric_value=int(r.cnt),
            extras={"is_active": bool(r.is_active)},
        )
        for r in rows
        if r.user_id is not None
    ]
    return ranked, scope


async def hall_of_fame(db: AsyncSession, limit: int = 5) -> list[RankedUser]:
    """Sam ranking — dla konsumentów, którzy nie renderują podpisu o zakresie.

    Cienka nakładka na `hall_of_fame_with_scope`: JEDNO zapytanie i jedna
    definicja w całym repo. Osobny SQL „tylko na listę" byłby drugim miejscem,
    w którym trzeba pamiętać o filtrze ról.
    """
    ranked, _scope = await hall_of_fame_with_scope(db, limit=limit)
    return ranked


async def compose_monthly_races(
    db: AsyncSession, month_period: Optional[str] = None
) -> dict:
    """Oba wyścigi miesięczne + wykluczenie lidera kwartału, w jednym dictcie.

    Jedno źródło prawdy dla API `/api/competitions/monthly-races` ORAZ
    composite'u `/api/dashboard/v2/recruitment-stats` — logika wykluczenia
    lidera kwartalnego i wyboru „zakwalifikowanego lidera" nie może się
    rozjechać między powierzchniami.
    """
    month_period = month_period or current_month_period()
    quarter_period = current_quarter_period()

    rec_ranked = await monthly_most_recommendations(db, month_period)
    pl_ranked = await monthly_most_placements(db, month_period)

    # Wykluczenie: lider kwartalny (rank 1 w quarterly_champions_recruiter)
    # nie może wygrać wyścigu miesięcznego — ale z rankingu nie wypada.
    # `qualified_for_award`, bo ranking kwartalny niesie teraz także
    # niezakwalifikowanych. Bez tego filtra „lider kwartału" bywałby osobą,
    # która nagrody kwartalnej nie dostanie — a wykluczenie z wyścigu
    # miesięcznego istnieje wyłącznie po to, żeby ta sama osoba nie brała obu.
    quarterly = qualified_for_award(
        await quarterly_champions_recruiter(db, quarter_period)
    )
    excluded_ids = {quarterly[0].user_id} if quarterly else set()

    days_left = days_left_in_month(business_today())

    def _format(ranked: list[RankedUser], extra_reqs: list[str]) -> dict:
        ranking = [
            {
                **r.to_dict(),
                "rank": idx + 1,
                "excluded": r.user_id in excluded_ids,
            }
            for idx, r in enumerate(ranked)
        ]
        # Zakwalifikowany lider = pierwszy spełniający warunki i niewykluczony.
        qualified = next(
            (
                entry
                for entry in ranking
                if not entry["excluded"] and entry.get("qualified", True)
            ),
            None,
        )
        return {
            "period": month_period,
            "days_remaining": days_left,
            "prize": {
                "amount_pln": MONTHLY_RACE_PRIZE_PLN,
                "name": MONTHLY_RACE_PRIZE_NAME,
            },
            "requirements": extra_reqs
            + ["Lider kwartalny wykluczony z nagrody miesięcznej"],
            "ranking": ranking,
            "excluded_user_ids": list(excluded_ids),
            "qualified_leader": qualified,
        }

    return {
        "recommendations": _format(
            rec_ranked,
            [
                (
                    f"Wymóg: min. {MONTHLY_RACE_MIN_VERIFICATIONS_PER_DAY} "
                    "weryfikacji/dzień roboczy w tym miesiącu"
                ),
                (
                    f"Wymóg: min. {int(MONTHLY_RACE_MIN_PRECISION_PCT)}% "
                    "precision rate (rekomendacje / weryfikacje)"
                ),
            ],
        ),
        "placements": _format(
            pl_ranked,
            [f"Minimum {MONTHLY_RACE_MIN_PLACEMENTS} placementy do kwalifikacji"],
        ),
    }


# ── Compute by CompetitionType ──────────────────────────────────────────


async def compute_live(
    db: AsyncSession, type_: CompetitionType, period: str
) -> list[RankedUser]:
    if type_ == CompetitionType.quarterly_champions_dl:
        return await quarterly_champions_dl(db, period)
    if type_ == CompetitionType.quarterly_champions_recruiter:
        return await quarterly_champions_recruiter(db, period)
    if type_ == CompetitionType.monthly_recommendations:
        return await monthly_most_recommendations(db, period)
    if type_ == CompetitionType.monthly_placements:
        return await monthly_most_placements(db, period)
    if type_ == CompetitionType.hall_of_fame:
        return await hall_of_fame(db)
    raise ValueError(f"Unknown competition type: {type_}")


def _prize_for(type_: CompetitionType, rank: int) -> int:
    if type_ in (
        CompetitionType.quarterly_champions_dl,
        CompetitionType.quarterly_champions_recruiter,
    ):
        return QUARTERLY_PRIZES_PLN.get(rank, 0)
    if type_ in (
        CompetitionType.monthly_recommendations,
        CompetitionType.monthly_placements,
    ):
        return MONTHLY_RACE_PRIZE_PLN if rank == 1 else 0
    return 0


# ── Freeze snapshot ─────────────────────────────────────────────────────


class FrozenPodium(list):
    """Podium zwrócone przez `freeze_competition` + czy ten call COŚ zapisał.

    Podklasa `list`, bo write-once znaczy, że wywołanie na już zamrożonym
    okresie zwraca komplet zwycięzców i wygląda dla wołającego identycznie
    jak świeży zapis — `len()`, indeksowanie i porównanie z listą działają
    jak dotąd, a `already_frozen` / `saved_count` pozwalają odróżnić realny
    zapis od no-opu bez zmiany kontraktu istniejących wywołań.
    """

    __slots__ = ("already_frozen",)

    def __init__(
        self, winners: Iterable[CompetitionWinner], *, already_frozen: bool
    ) -> None:
        super().__init__(winners)
        self.already_frozen = already_frozen

    @property
    def saved_count(self) -> int:
        """Ile wierszy ten call REALNIE wstawił — 0, gdy okres był zamrożony."""
        return 0 if self.already_frozen else len(self)


async def freeze_competition(
    db: AsyncSession,
    type_: CompetitionType,
    period: str,
) -> FrozenPodium:
    """Write a podium once; a frozen historical period is immutable.

    Zwraca `FrozenPodium` — write-once ZOSTAJE (zamrożonej historii nie
    przeliczamy), ale wołający musi umieć odróżnić „zapisałem podium" od
    „nic nie zrobiłem, bo już było": patrz `already_frozen` / `saved_count`.
    """
    await db.execute(
        text("SELECT pg_advisory_xact_lock(hashtext(:freeze_key))"),
        {"freeze_key": f"competition:{type_.value}:{period}"},
    )
    existing = (
        (
            await db.execute(
                select(CompetitionWinner)
                .where(
                    CompetitionWinner.competition_type == type_.value,
                    CompetitionWinner.period == period,
                )
                .order_by(CompetitionWinner.rank)
            )
        )
        .scalars()
        .all()
    )
    if existing:
        # Świadomy no-op. Logujemy, bo bez tego jedynym śladem po „freeze,
        # który nic nie zmienił" byłaby odpowiedź nieodróżnialna od sukcesu.
        logger.warning(
            "freeze_competition no-op: %s %s already frozen (%d winners) — "
            "podium is immutable, nothing was written",
            type_.value,
            period,
            len(existing),
        )
        await db.commit()
        return FrozenPodium(existing, already_frozen=True)

    ranked = await compute_live(db, type_, period)
    # Filtr kwalifikacji jest BEZWARUNKOWY, nie zawężony do jednego typu:
    # `qualified_for_award` domyślnie przepuszcza wiersze bez flagi, więc
    # rankingi, które jej nie ustawiają (DL, wyścig placementów), zachowują
    # się dokładnie jak dotąd. Lista typów byłaby kolejnym miejscem do
    # zaktualizowania przy każdym nowym warunku udziału — a pominięcie go
    # znaczy nagrodę dla kogoś, kto warunku nie spełnił.
    #
    # Reszta `freeze_competition` jest NIETKNIĘTA: write-once zostaje, zamrożone
    # podia nie są przeliczane, nowa formuła obowiązuje od najbliższego
    # niezamkniętego kwartału (D3).
    ranked = qualified_for_award(ranked)
    top3 = ranked[:3]
    full_snapshot = [r.to_dict() for r in ranked[:10]]

    created: list[CompetitionWinner] = []
    for idx, r in enumerate(top3, start=1):
        winner = CompetitionWinner(
            competition_type=type_.value,
            period=period,
            user_id=r.user_id,
            rank=idx,
            metric_value=r.metric_value,
            points=r.metric_value,
            prize_pln=_prize_for(type_, idx),
            frozen_snapshot={"top": full_snapshot},
        )
        db.add(winner)
        created.append(winner)

    await db.commit()
    return FrozenPodium(created, already_frozen=False)


async def previous_quarter_period(today: Optional[date] = None) -> str:
    today = today or business_today()
    q = (today.month - 1) // 3 + 1
    year = today.year
    prev_q = q - 1
    if prev_q == 0:
        prev_q = 4
        year -= 1
    return f"Q{prev_q} {year}"


async def previous_month_period(today: Optional[date] = None) -> str:
    today = today or business_today()
    first_of_month = today.replace(day=1)
    last_prev_month = first_of_month - timedelta(days=1)
    return last_prev_month.strftime("%Y-%m")
