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

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Optional

from sqlalchemy import or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.competition_winner import CompetitionType, CompetitionWinner
from app.models.job import Job, RecruitmentType
from app.models.recruitment_pipeline import PipelineStage
from app.models.user import User, UserRole
from app.analytics.periods import WARSAW


# ── Konfiguracja nagród ──────────────────────────────────────────────────

HIT_RATIO_TARGET = 30.0  # % — próg wejścia na podium DL
QUARTERLY_MIN_PLACEMENTS = 3
MONTHLY_RACE_MIN_PLACEMENTS = 2

QUARTERLY_PRIZES_PLN = {1: 5000, 2: 3000, 3: 2000}
MONTHLY_RACE_PRIZE_PLN = 1500
MONTHLY_RACE_PRIZE_NAME = "Voucher 1 500 PLN (Modivo, Douglas, Media Markt)"

# System punktowy Liga Mistrzów Rekrutacja (port z InfraReportera).
# Marlena 5P/8I/22R = 5·150 + 8·15 + 22·5 = 980 pkt ✓
POINTS_PER_PLACEMENT = 150
POINTS_PER_INTERVIEW = 15
POINTS_PER_RECOMMENDATION = 5

POINTS_FORMULA = {
    "placement": POINTS_PER_PLACEMENT,
    "interview": POINTS_PER_INTERVIEW,
    "recommendation": POINTS_PER_RECOMMENDATION,
}

# Wymóg tygodniowej aktywności dla Wyścigu Rekomendacji.
MONTHLY_RACE_MIN_VERIFICATIONS_PER_DAY = 4
MONTHLY_RACE_MIN_PRECISION_PCT = 75.0


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


def quarter_bounds(year: int, quarter: int) -> tuple[datetime, datetime]:
    """Zwraca [start, end_exclusive) dla kwartału (Q1..Q4)."""
    if not 1 <= quarter <= 4:
        raise ValueError(f"Invalid quarter: {quarter}")
    month_start = (quarter - 1) * 3 + 1
    start = datetime(year, month_start, 1, tzinfo=WARSAW)
    month_end = month_start + 3
    if month_end > 12:
        end = datetime(year + 1, 1, 1, tzinfo=WARSAW)
    else:
        end = datetime(year, month_end, 1, tzinfo=WARSAW)
    return start, end


def month_bounds(year: int, month: int) -> tuple[datetime, datetime]:
    if not 1 <= month <= 12:
        raise ValueError(f"Invalid month: {month}")
    start = datetime(year, month, 1, tzinfo=WARSAW)
    if month == 12:
        end = datetime(year + 1, 1, 1, tzinfo=WARSAW)
    else:
        end = datetime(year, month + 1, 1, tzinfo=WARSAW)
    return start, end


def current_quarter_period(today: Optional[date] = None) -> str:
    today = today or date.today()
    q = (today.month - 1) // 3 + 1
    return f"Q{q} {today.year}"


def current_month_period(today: Optional[date] = None) -> str:
    today = today or date.today()
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
    """Rank operational recruiters by canonical first milestone.

    Credit is resolved by ``analytics_first_candidate_milestones``: verifier
    first, otherwise the mover of that milestone. Secondary roles participate.
    """
    limit_clause = "LIMIT :limit" if limit else ""
    rows = (
        await db.execute(
            text(
                f"""
                SELECT u.id, u.name, u.role::text AS role, count(*) AS cnt
                FROM analytics_first_candidate_milestones m
                JOIN users u ON u.id = m.credited_user_id
                WHERE m.stage = :stage
                  AND m.reached_at >= :start AND m.reached_at < :end
                  AND u.is_active IS TRUE
                  AND (
                    u.role::text IN ('sourcer', 'tac', 'recruiter')
                    OR u.roles ?| ARRAY['sourcer', 'tac', 'recruiter']
                  )
                GROUP BY u.id, u.name, u.role
                HAVING count(*) >= :minimum
                ORDER BY count(*) DESC, u.name ASC
                {limit_clause}
                """
            ),
            {
                "stage": stage.value,
                "start": start,
                "end": end,
                "minimum": min_value,
                "limit": limit,
            },
        )
    ).mappings().all()
    return [
        RankedUser(
            user_id=int(r["id"]),
            name=str(r["name"]),
            metric_value=int(r["cnt"]),
            extras={"role": str(r["role"])},
        )
        for r in rows
    ]


async def _rank_recruiters_by_points(
    db: AsyncSession,
    *,
    start: datetime,
    end: datetime,
    min_placements: int = 0,
    limit: Optional[int] = None,
) -> list[RankedUser]:
    """Ranking po systemie punktowym (placement=150, interview=15, rekomendacja=5).

    Zwraca RankedUser z metric_value=points i extras={placements, interviews,
    recommendations, verifications, role}."""
    rows = (
        await db.execute(
            text(
                """
                SELECT u.id, u.name, u.role::text AS role, m.stage, count(*) AS cnt
                FROM analytics_first_candidate_milestones m
                JOIN users u ON u.id = m.credited_user_id
                WHERE m.reached_at >= :start AND m.reached_at < :end
                  AND m.stage IN (
                    'verified', 'cv_sent', 'client_interview', 'hired'
                  )
                  AND u.is_active IS TRUE
                  AND (
                    u.role::text IN ('sourcer', 'tac', 'recruiter')
                    OR u.roles ?| ARRAY['sourcer', 'tac', 'recruiter']
                  )
                GROUP BY u.id, u.name, u.role, m.stage
                """
            ),
            {"start": start, "end": end},
        )
    ).mappings().all()

    per_user: dict[int, dict] = {}
    for r in rows:
        bucket = per_user.setdefault(
            int(r["id"]),
            {
                "name": str(r["name"]),
                "role": str(r["role"]),
                "placements": 0,
                "interviews": 0,
                "client_interviews": 0,
                "recommendations": 0,
                "verifications": 0,
            },
        )
        cnt = int(r["cnt"])
        stage_value = str(r["stage"])
        if stage_value == PipelineStage.hired.value:
            bucket["placements"] += cnt
        elif stage_value == PipelineStage.client_interview.value:
            bucket["client_interviews"] += cnt
        elif stage_value == PipelineStage.cv_sent.value:
            bucket["recommendations"] += cnt
        elif stage_value == PipelineStage.verified.value:
            bucket["verifications"] += cnt

    ranked: list[RankedUser] = []
    for user_id, data in per_user.items():
        if data["placements"] < min_placements:
            continue
        points = (
            data["placements"] * POINTS_PER_PLACEMENT
            + data["client_interviews"] * POINTS_PER_INTERVIEW
            + data["recommendations"] * POINTS_PER_RECOMMENDATION
        )
        ranked.append(
            RankedUser(
                user_id=user_id,
                name=data["name"],
                metric_value=points,
                extras={
                    "role": data["role"],
                    "placements": data["placements"],
                    "interviews": data["client_interviews"],
                    "recommendations": data["recommendations"],
                    "verifications": data["verifications"],
                },
            )
        )

    ranked.sort(key=lambda r: r.metric_value, reverse=True)
    if limit:
        ranked = ranked[:limit]
    return ranked


# ── Countdown helpers ───────────────────────────────────────────────────


def days_left_in_quarter(today: Optional[date] = None) -> int:
    today = today or date.today()
    q = (today.month - 1) // 3 + 1
    end_month = q * 3
    if end_month == 12:
        end = date(today.year + 1, 1, 1)
    else:
        end = date(today.year, end_month + 1, 1)
    return max((end - today).days, 0)


def days_left_in_month(today: Optional[date] = None) -> int:
    today = today or date.today()
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
    rows = (
        await db.execute(
            text(
                """
                SELECT j.id AS job_id, j.delivery_lead_id, j.client_id,
                       count(*) AS cnt
                FROM jobs j
                JOIN analytics_first_candidate_milestones m ON m.job_id = j.id
                WHERE m.stage = 'hired'
                  AND m.reached_at >= :start AND m.reached_at < :end
                  AND j.recruitment_type::text = 'body_leasing'
                GROUP BY j.id, j.delivery_lead_id, j.client_id
                """
            ),
            {"start": start, "end": end},
        )
    ).mappings().all()
    placements_by_dl: dict[int, int] = {}
    for r in rows:
        dl_id = _resolve_dl_id(r["delivery_lead_id"], r["client_id"], fallback)
        if dl_id is None:
            continue
        placements_by_dl[dl_id] = placements_by_dl.get(dl_id, 0) + int(r["cnt"])

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
                User.is_active.is_(True),
                or_(
                    User.role == UserRole.delivery_lead,
                    User.roles.contains([UserRole.delivery_lead.value]),
                ),
            )
        )
    ).all()
    name_map = {int(u.id): str(u.name) for u in users_rows}

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


async def quarterly_champions_recruiter(
    db: AsyncSession, period: str
) -> list[RankedUser]:
    """Liga Mistrzów Rekrutacja — ranking po PUNKTACH (placement=150 + interview=15
    + rekomendacja=5), min 3 placementy jako warunek udziału."""
    year, q = parse_quarter(period)
    start, end = quarter_bounds(year, q)
    return await _rank_recruiters_by_points(
        db,
        start=start,
        end=end,
        min_placements=QUARTERLY_MIN_PLACEMENTS,
        limit=10,
    )


async def monthly_most_recommendations(
    db: AsyncSession, period: str
) -> list[RankedUser]:
    year, month = parse_month(period)
    start, end = month_bounds(year, month)
    metrics = await _rank_recruiters_by_points(
        db, start=start, end=end, min_placements=0
    )
    elapsed_end = min(end, datetime.now(WARSAW))
    cursor = start.date()
    elapsed_workdays = 0
    while cursor < elapsed_end.date():
        if cursor.weekday() < 5:
            elapsed_workdays += 1
        cursor += timedelta(days=1)
    # Include the current working day in the pace denominator.
    if elapsed_end.date() < end.date() and elapsed_end.weekday() < 5:
        elapsed_workdays += 1
    minimum_verifications = (
        elapsed_workdays * MONTHLY_RACE_MIN_VERIFICATIONS_PER_DAY
    )

    ranked: list[RankedUser] = []
    for row in metrics:
        verified = int(row.extras.get("verifications", 0))
        recommendations = int(row.extras.get("recommendations", 0))
        precision = recommendations * 100 / verified if verified else 0.0
        if verified < minimum_verifications or precision < MONTHLY_RACE_MIN_PRECISION_PCT:
            continue
        ranked.append(
            RankedUser(
                user_id=row.user_id,
                name=row.name,
                metric_value=recommendations,
                extras={**row.extras, "precision_pct": round(precision, 1)},
            )
        )
    ranked.sort(key=lambda r: (-r.metric_value, r.name))
    return ranked[:10]


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


async def hall_of_fame(db: AsyncSession, limit: int = 5) -> list[RankedUser]:
    rows = (
        await db.execute(
            text(
                """
                SELECT u.id, u.name, count(*) AS cnt
                FROM analytics_first_candidate_milestones m
                JOIN users u ON u.id = m.credited_user_id
                WHERE m.stage = 'hired' AND u.is_active IS TRUE
                GROUP BY u.id, u.name
                ORDER BY count(*) DESC, u.name ASC
                LIMIT :limit
                """
            ),
            {"limit": limit},
        )
    ).mappings().all()
    return [
        RankedUser(
            user_id=int(r["id"]),
            name=str(r["name"]),
            metric_value=int(r["cnt"]),
        )
        for r in rows
    ]


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


async def freeze_competition(
    db: AsyncSession,
    type_: CompetitionType,
    period: str,
) -> list[CompetitionWinner]:
    """Oblicza i zapisuje TOP 3 do `competition_winners`. Idempotentne —
    kasuje istniejące rekordy dla (type, period) i pisze od nowa."""
    ranked = await compute_live(db, type_, period)
    top3 = ranked[:3]
    full_snapshot = [r.to_dict() for r in ranked[:10]]

    # Delete existing.
    existing = (
        (
            await db.execute(
                select(CompetitionWinner).where(
                    CompetitionWinner.competition_type == type_.value,
                    CompetitionWinner.period == period,
                )
            )
        )
        .scalars()
        .all()
    )
    for e in existing:
        await db.delete(e)

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
    return created


async def previous_quarter_period(today: Optional[date] = None) -> str:
    today = today or date.today()
    q = (today.month - 1) // 3 + 1
    year = today.year
    prev_q = q - 1
    if prev_q == 0:
        prev_q = 4
        year -= 1
    return f"Q{prev_q} {year}"


async def previous_month_period(today: Optional[date] = None) -> str:
    today = today or date.today()
    first_of_month = today.replace(day=1)
    last_prev_month = first_of_month - timedelta(days=1)
    return last_prev_month.strftime("%Y-%m")
