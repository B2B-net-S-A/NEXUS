"""Cele liderów — Delivery Lead (portfel) i HoR / TCM (zespół) — 22.09.2026.

Decyzja Artura (22.09.2026, punkt 7 audytu ról i targetów):

- **Delivery Lead**: hit ratio 30% i placementy w portfelu. Liczby i okno są
  TE SAME co w Lidze Mistrzów DL (`competitions.dl_portfolio_counts`: kwartał
  kalendarzowy, oferty body leasing, DL oferty albo head DL klienta; próg
  `HIT_RATIO_TARGET` i `QUARTERLY_MIN_PLACEMENTS`). Dzięki temu „twoje hit
  ratio" na pulpicie i miejsce na podium liczą się z jednego zapytania.
- **Head of Recruitment i TCM**: cele ZESPOŁOWE, bez osobistych. Zespół to
  operatorzy rekrutacji z zakresu pulpitu (`resolve_dashboard_scope` →
  `recruitment_org`). Cel zespołu = suma celów ludzi (`kpi_targets`), wynik =
  suma pracy TYCH SAMYCH ludzi (osoba bez celu danego KPI nie wchodzi ani do
  celu, ani do wyniku — inaczej porównywalibyśmy pracę sourcerów z celem, który
  ich nie obejmuje). Liczniki z `kpi_team.compute_team_panel` — ta sama
  atrybucja verifier-anchored co widget i panel „Moje KPI".

„Niepoliczony" nigdy nie jest zerem: hit ratio bez requestów w kwartale
i precyzja poniżej 5 weryfikacji mają `current=None` i opis w `note`.
"""

from __future__ import annotations

import hashlib
from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Literal, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.cache import cache_get, cache_set
from app.core.scheduling import local_quarter_bounds
from app.models.user import User
from app.services.access_scope import ScopeKind, resolve_dashboard_scope
from app.services.kpi_catalog import KPI_CATALOG, KpiMetric, KpiPeriod, kpi_available
from app.services.kpi_engine import (
    WARSAW,
    KpiState,
    derive_state,
    expected_progress_ratio,
)
from app.services.kpi_targets import resolve_kpi_targets_bulk, resolve_org_target

GoalsKind = Literal["delivery_lead", "team", "none"]

_CACHE_TTL_SECONDS = 120
_PRECISION_MIN_DENOM = 5

# KPI zespołowe (licznik z panelu zespołu) → (okno, pole wiersza panelu).
_TEAM_COUNT_FIELDS: dict[KpiMetric, str] = {
    KpiMetric.first_verifications: "weryfikacje",
    KpiMetric.new_candidates: "cv_to_base",
    KpiMetric.first_recommendations: "rekomendacje",
    KpiMetric.first_placements: "placementy",
}

_TEAM_TITLES: dict[str, str] = {
    "daily_first_verifications": "Weryfikacje zespołu dziś",
    "daily_new_candidates": "Nowi kandydaci zespołu dziś",
    "weekly_cvs_sent": "Rekomendacje zespołu w tygodniu",
    "monthly_placements": "Placementy zespołu w tym miesiącu",
    "monthly_precision": "Precyzja zespołu (30 dni)",
}


@dataclass(frozen=True)
class GoalRow:
    goal_id: str
    title_pl: str
    period: str  # "day" | "week" | "month" | "quarter"
    unit: str  # "count" | "pct"
    target: float
    current: Optional[float]
    progress_pct: Optional[float]
    state: Optional[KpiState]
    note: Optional[str] = None


@dataclass(frozen=True)
class GoalsResult:
    kind: GoalsKind
    scope_label: str
    people: Optional[int]
    goals: tuple[GoalRow, ...]

    def as_dict(self) -> dict:
        return {
            "kind": self.kind,
            "scope_label": self.scope_label,
            "people": self.people,
            "goals": [asdict(g) for g in self.goals],
        }

    @classmethod
    def from_dict(cls, data: dict) -> "GoalsResult":
        return cls(
            kind=data["kind"],
            scope_label=data["scope_label"],
            people=data["people"],
            goals=tuple(GoalRow(**g) for g in data["goals"]),
        )


_NONE = GoalsResult(kind="none", scope_label="", people=None, goals=())


def _progress(current: Optional[float], target: float) -> Optional[float]:
    if current is None or target <= 0:
        return None
    return round(100.0 * current / target, 1)


def _ratio_state(current: Optional[float], target: float) -> Optional[KpiState]:
    """Stan wskaźnika jakości: brak narastania w okresie, więc hit / behind."""
    if current is None:
        return None
    return "hit" if current >= target else "behind"


def _quarter_ratio(now: datetime) -> float:
    """Jaka część kwartału minęła (0..1) — tempo celu kwartalnego."""
    bounds = local_quarter_bounds(now.astimezone(WARSAW).date())
    total = (bounds.end_utc - bounds.start_utc).total_seconds()
    elapsed = (now - bounds.start_utc).total_seconds()
    return min(1.0, max(0.0, elapsed / total)) if total > 0 else 1.0


# ── Delivery Lead ─────────────────────────────────────────────────────────────


async def _delivery_lead_goals(
    db: AsyncSession, *, user: User, now: datetime
) -> GoalsResult:
    # Import leniwy: `competitions` importuje `api.reports` w środku funkcji.
    from app.services.competitions import (
        HIT_RATIO_TARGET,
        QUARTERLY_MIN_PLACEMENTS,
        current_quarter_period,
        dl_portfolio_counts,
    )

    bounds = local_quarter_bounds(now.astimezone(WARSAW).date())
    placements_by_dl, requests_by_dl = await dl_portfolio_counts(
        db, start=bounds.start_utc, end=bounds.end_utc
    )
    placements = int(placements_by_dl.get(user.id, 0))
    requests = int(requests_by_dl.get(user.id, 0))
    hit_ratio = round(100.0 * placements / requests, 1) if requests else None
    target_hr = float(HIT_RATIO_TARGET)
    target_pl = float(QUARTERLY_MIN_PLACEMENTS)

    goals = (
        GoalRow(
            goal_id="dl_hit_ratio_quarter",
            title_pl="Hit ratio portfela w kwartale",
            period="quarter",
            unit="pct",
            target=target_hr,
            current=hit_ratio,
            progress_pct=_progress(hit_ratio, target_hr),
            state=_ratio_state(hit_ratio, target_hr),
            note=(
                None
                if hit_ratio is not None
                else "Niepoliczony — w tym kwartale nie ma nowych requestów "
                "w Twoim portfelu."
            ),
        ),
        GoalRow(
            goal_id="dl_placements_quarter",
            title_pl="Placementy portfela w kwartale",
            period="quarter",
            unit="count",
            target=target_pl,
            current=float(placements),
            progress_pct=_progress(float(placements), target_pl),
            state=derive_state(
                current=placements,
                target=int(target_pl),
                expected_ratio=_quarter_ratio(now),
            ),
            note=f"Nowe requesty w kwartale: {requests}",
        ),
    )
    return GoalsResult(
        kind="delivery_lead",
        # Etykieta okna („Q3 2026") — front dopisuje „Cele portfela".
        scope_label=current_quarter_period(now.astimezone(WARSAW).date()),
        people=None,
        goals=goals,
    )


# ── Zespół (HoR / TCM) ────────────────────────────────────────────────────────


async def _team_goals(
    db: AsyncSession, *, operator_ids: frozenset[int], now: datetime
) -> GoalsResult:
    from app.services.kpi_team import compute_team_panel

    members = (
        (
            await db.execute(
                select(User).where(
                    User.id.in_(sorted(operator_ids)), User.is_active.is_(True)
                )
            )
        )
        .scalars()
        .all()
    )
    if not members:
        return GoalsResult(
            kind="team",
            scope_label="Zespół rekrutacji",
            people=0,
            goals=(),
        )

    kpis = [
        k
        for k in KPI_CATALOG
        if kpi_available(k)
        and (k.metric in _TEAM_COUNT_FIELDS or k.metric is KpiMetric.precision)
    ]
    targets = await resolve_kpi_targets_bulk(db, members, [k.kpi_id for k in kpis])
    member_ids = {m.id for m in members}

    panels = {}
    for period in {k.period for k in kpis if k.metric is not KpiMetric.precision}:
        panel = await compute_team_panel(db, period=period, now=now)
        panels[period] = {row.user_id: row for row in panel.rows}

    goals: list[GoalRow] = []
    for kpi in kpis:
        if kpi.metric is KpiMetric.precision:
            continue
        field = _TEAM_COUNT_FIELDS[kpi.metric]
        rows = panels[kpi.period]
        with_goal = [uid for uid in member_ids if targets[uid][kpi.kpi_id] > 0]
        if not with_goal:
            continue
        target = sum(targets[uid][kpi.kpi_id] for uid in with_goal)
        current = sum(
            int(getattr(rows[uid], field)) for uid in with_goal if uid in rows
        )
        goals.append(
            GoalRow(
                goal_id=f"team_{kpi.kpi_id}",
                title_pl=_TEAM_TITLES.get(kpi.kpi_id, kpi.title_pl),
                period=kpi.period.value,
                unit="count",
                target=float(target),
                current=float(current),
                progress_pct=_progress(float(current), float(target)),
                state=derive_state(
                    current=current,
                    target=target,
                    expected_ratio=expected_progress_ratio(kpi.period, now),
                ),
                note=f"Suma celów osób z tym celem: {len(with_goal)}",
            )
        )

    # Precyzja nie sumuje się z celów — to wskaźnik jakości całego zespołu
    # z okna kroczącego 30 dni, porównany z celem organizacyjnym.
    if any(k.metric is KpiMetric.precision for k in kpis):
        month_rows = panels.get(KpiPeriod.month)
        if month_rows is None:
            panel = await compute_team_panel(db, period=KpiPeriod.month, now=now)
            month_rows = {row.user_id: row for row in panel.rows}
        verified = sum(
            month_rows[uid].precision_verified_30d
            for uid in member_ids
            if uid in month_rows
        )
        sent = sum(
            month_rows[uid].precision_sent_30d
            for uid in member_ids
            if uid in month_rows
        )
        target = float(await resolve_org_target(db, "monthly_precision"))
        value = (
            round(100.0 * sent / verified, 1)
            if verified >= _PRECISION_MIN_DENOM
            else None
        )
        goals.append(
            GoalRow(
                goal_id="team_monthly_precision",
                title_pl=_TEAM_TITLES["monthly_precision"],
                period=KpiPeriod.month.value,
                unit="pct",
                target=target,
                current=value,
                progress_pct=_progress(value, target),
                state=_ratio_state(value, target),
                note=(
                    f"Rekomendacje / weryfikacje (30 dni): {sent} / {verified}"
                    if value is not None
                    else "Niepoliczony — mniej niż 5 weryfikacji w 30 dni."
                ),
            )
        )

    return GoalsResult(
        kind="team",
        scope_label="Zespół rekrutacji",
        people=len(members),
        goals=tuple(goals),
    )


# ── API ──────────────────────────────────────────────────────────────────────


async def compute_my_goals(
    db: AsyncSession, *, user: User, now: Optional[datetime] = None
) -> GoalsResult:
    """Cele lidera dla `user`: portfel (DL), zespół (HoR/TCM) albo brak.

    Rodzaj wynika z zakresu pulpitu (`resolve_dashboard_scope`), a nie z listy
    ról obok — ta sama osoba nie może mieć na pulpicie „zespołu" innego niż
    w statystykach. Admin i Finanse (zakres organizacji) nie mają celów lidera.
    """
    if now is None:
        now = datetime.now(WARSAW)
    scope = await resolve_dashboard_scope(user, db)

    if scope.kind is ScopeKind.recruitment_org:
        digest = hashlib.sha256(
            ",".join(str(i) for i in sorted(scope.allowed_operator_user_ids)).encode()
        ).hexdigest()[:16]
        cache_key = f"kpis:goals:team:{digest}"
        cached = await cache_get(cache_key)
        if isinstance(cached, dict):
            return GoalsResult.from_dict(cached)
        result = await _team_goals(
            db, operator_ids=scope.allowed_operator_user_ids, now=now
        )
        await cache_set(cache_key, result.as_dict(), ttl_seconds=_CACHE_TTL_SECONDS)
        return result

    if scope.kind is ScopeKind.delivery_clients:
        cache_key = f"kpis:goals:dl:{user.id}"
        cached = await cache_get(cache_key)
        if isinstance(cached, dict):
            return GoalsResult.from_dict(cached)
        result = await _delivery_lead_goals(db, user=user, now=now)
        await cache_set(cache_key, result.as_dict(), ttl_seconds=_CACHE_TTL_SECONDS)
        return result

    return _NONE


__all__ = ["GoalRow", "GoalsResult", "compute_my_goals"]
