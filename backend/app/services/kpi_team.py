"""KPI Panel — wariant ZESPOŁOWY (lejek per osoba dla całego teamu).

Rozszerza panel „Moje KPI" (`kpi_panel.py`) na widok managerski: zamiast
filtrować lejek do jednego `:uid`, grupuje go po `credit_user` i zwraca wiersz
na każdą osobę z zespołu — w jednym przejściu po `candidate_stages`.

Atrybucja jest **identyczna** jak w panelu per-user (verifier-anchored — zasługę
za kamienie milowe pary kandydat×rekrutacja dostaje weryfikator), bo oba serwisy
dzielą to samo CTE `VERIFIER_ANCHORED_CTE`. Dzięki temu suma kolumny w widoku
zespołowym zgadza się z liczbami, które każdy widzi u siebie.

Filtry osoba/rola robi front (na zwróconej liście) — backend bierze tylko okno
czasu (`period`), bo to ono zmienia zapytanie SQL. Lista zawiera wszystkich
aktywnych userów z ról operacyjnych (także z zerami — manager widzi też kto
nic nie zrobił) plus dowolnego usera spoza tej puli, który ma jakąś aktywność.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Optional

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User
from app.services.kpi_catalog import KpiPeriod
from app.services.kpi_engine import WARSAW, period_bounds
from app.services.kpi_panel import (
    _ANCHOR_LOOKBACK_DAYS,
    _OPERATIONAL_ROLES,
    _PRECISION_MIN_DENOM,
    _PRECISION_WINDOW_DAYS,
    VERIFIER_ANCHORED_CTE,
)

# Cel precision (rekomendacje ÷ weryfikacje) — globalny dla widoku zespołu.
_PRECISION_TARGET_PCT = 75


# ── SQL ──────────────────────────────────────────────────────────────────────

# Team funnel: ten sam CTE atrybucji co per-user, ale GROUP BY (osoba, etap).
# Dla każdej osoby i etapu zwracamy licznik w wybranym oknie (`period_cnt`)
# oraz w oknie kroczącym 30 dni (`r30_cnt`, do precision).
_TEAM_FUNNEL_SQL = text(
    VERIFIER_ANCHORED_CTE
    + """
    SELECT credit_user AS uid, stage,
           count(*) FILTER (WHERE reached_at >= :period_start) AS period_cnt,
           count(*) FILTER (WHERE reached_at >= :rolling30)    AS r30_cnt
    FROM credited
    WHERE credit_user IS NOT NULL
    GROUP BY credit_user, stage
    """
)

# „CV do bazy" per osoba — nowi kandydaci utworzeni przez usera w oknie.
# Import masowy (Traffit/TalentRadar) ma created_by NULL → nie liczy się.
_TEAM_CV_SQL = text(
    """
    SELECT created_by AS uid, count(*) AS cnt
    FROM candidates
    WHERE created_by IS NOT NULL AND created_at >= :period_start
    GROUP BY created_by
    """
)


# ── Output dataclassy ────────────────────────────────────────────────────────


@dataclass(frozen=True)
class TeamMemberRow:
    """Lejek jednej osoby za wybrane okno + precision (zawsze 30 dni)."""

    user_id: int
    name: str
    role: str
    weryfikacje: int
    rekomendacje: int
    interview: int
    akceptacje: int
    placementy: int
    cv_to_base: int
    precision_pct: Optional[float]  # None gdy < _PRECISION_MIN_DENOM weryfikacji
    precision_verified_30d: int
    precision_sent_30d: int


@dataclass(frozen=True)
class TeamTotals:
    """Suma zespołu za okno (precision liczona z sum, nie ze średnich)."""

    weryfikacje: int
    rekomendacje: int
    interview: int
    akceptacje: int
    placementy: int
    cv_to_base: int
    precision_pct: Optional[float]
    people: int


@dataclass(frozen=True)
class TeamPanelResult:
    period: str
    precision_target_pct: int
    rows: tuple[TeamMemberRow, ...]
    totals: TeamTotals


# ── Główne API ───────────────────────────────────────────────────────────────


def _role_value(role) -> str:
    return (
        role.value if getattr(role, "value", None) else (str(role) if role else "user")
    )


async def compute_team_panel(
    db: AsyncSession, *, period: KpiPeriod, now: Optional[datetime] = None
) -> TeamPanelResult:
    """Lejek per osoba dla całego zespołu w oknie `period` (day/week/month)."""
    if now is None:
        now = datetime.now(WARSAW)

    period_start, _ = period_bounds(period, now)
    rolling30 = now - timedelta(days=_PRECISION_WINDOW_DAYS)
    lookback = now - timedelta(days=_ANCHOR_LOOKBACK_DAYS)

    funnel_rows = (
        (
            await db.execute(
                _TEAM_FUNNEL_SQL,
                {
                    "lookback": lookback,
                    "period_start": period_start,
                    "rolling30": rolling30,
                },
            )
        )
        .mappings()
        .all()
    )

    # agg[uid][stage] = {"p": period_cnt, "r30": r30_cnt}
    agg: dict[int, dict[str, dict[str, int]]] = {}
    for r in funnel_rows:
        agg.setdefault(int(r["uid"]), {})[r["stage"]] = {
            "p": int(r["period_cnt"]),
            "r30": int(r["r30_cnt"]),
        }

    cv_rows = (
        (await db.execute(_TEAM_CV_SQL, {"period_start": period_start}))
        .mappings()
        .all()
    )
    cv_by_uid: dict[int, int] = {int(r["uid"]): int(r["cnt"]) for r in cv_rows}

    # Pula bazowa: aktywni userzy z ról operacyjnych — pokazujemy zawsze (też 0).
    op_users = (
        await db.execute(
            select(User.id, User.name, User.role).where(
                User.is_active.is_(True),
                User.role.in_(_OPERATIONAL_ROLES),
            )
        )
    ).all()
    user_meta: dict[int, tuple[str, str]] = {
        u.id: (u.name or f"#{u.id}", _role_value(u.role)) for u in op_users
    }
    shown_uids: set[int] = set(user_meta)

    # Dołóż każdego usera spoza puli, który MA aktywność (np. admin ruszający etapy).
    extra_uids = (set(agg) | set(cv_by_uid)) - shown_uids
    if extra_uids:
        extra = (
            await db.execute(
                select(User.id, User.name, User.role).where(User.id.in_(extra_uids))
            )
        ).all()
        for u in extra:
            user_meta[u.id] = (u.name or f"#{u.id}", _role_value(u.role))
            shown_uids.add(u.id)

    rows: list[TeamMemberRow] = []
    sums = dict.fromkeys(
        ("weryfikacje", "rekomendacje", "interview", "akceptacje", "placementy", "cv"),
        0,
    )
    tot_verified30 = 0
    tot_sent30 = 0

    for uid in shown_uids:
        name, role = user_meta[uid]
        stages = agg.get(uid, {})

        def _p(stage: str) -> int:
            return stages.get(stage, {}).get("p", 0)

        weryf = _p("verified")
        rekom = _p("cv_sent")
        inter = _p("interview")
        akcept = _p("acceptance")
        plac = _p("hired")
        cv = cv_by_uid.get(uid, 0)

        v30 = stages.get("verified", {}).get("r30", 0)
        s30 = stages.get("cv_sent", {}).get("r30", 0)
        prec = round(100.0 * s30 / v30, 1) if v30 >= _PRECISION_MIN_DENOM else None

        rows.append(
            TeamMemberRow(
                user_id=uid,
                name=name,
                role=role,
                weryfikacje=weryf,
                rekomendacje=rekom,
                interview=inter,
                akceptacje=akcept,
                placementy=plac,
                cv_to_base=cv,
                precision_pct=prec,
                precision_verified_30d=v30,
                precision_sent_30d=s30,
            )
        )
        sums["weryfikacje"] += weryf
        sums["rekomendacje"] += rekom
        sums["interview"] += inter
        sums["akceptacje"] += akcept
        sums["placementy"] += plac
        sums["cv"] += cv
        tot_verified30 += v30
        tot_sent30 += s30

    # Sort: najwięcej placementów → weryfikacji → rekomendacji → alfabetycznie.
    rows.sort(
        key=lambda r: (
            -r.placementy,
            -r.weryfikacje,
            -r.rekomendacje,
            r.name.lower(),
        )
    )

    team_prec = (
        round(100.0 * tot_sent30 / tot_verified30, 1)
        if tot_verified30 >= _PRECISION_MIN_DENOM
        else None
    )

    totals = TeamTotals(
        weryfikacje=sums["weryfikacje"],
        rekomendacje=sums["rekomendacje"],
        interview=sums["interview"],
        akceptacje=sums["akceptacje"],
        placementy=sums["placementy"],
        cv_to_base=sums["cv"],
        precision_pct=team_prec,
        people=len(rows),
    )

    return TeamPanelResult(
        period=period.value,
        precision_target_pct=_PRECISION_TARGET_PCT,
        rows=tuple(rows),
        totals=totals,
    )


__all__ = [
    "TeamMemberRow",
    "TeamTotals",
    "TeamPanelResult",
    "compute_team_panel",
]
