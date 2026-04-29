"""Router `/api/competitions/*` — Liga Mistrzów kwartalna + Wyścigi Miesięczne
+ Hall of Fame.

Dostęp: GET dla wszystkich zalogowanych; POST /freeze tylko admin.
"""

from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import AdminUser, CurrentUser
from app.core.database import get_db
from app.models.competition_winner import CompetitionType, CompetitionWinner
from app.models.user import User
from app.services import competitions as comp_service

router = APIRouter()


def _parse_type(type_str: str) -> CompetitionType:
    try:
        return CompetitionType(type_str)
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail=(
                "Invalid competition type. Allowed: "
                + ", ".join(t.value for t in CompetitionType)
            ),
        )


@router.get("/current")
async def get_current(
    _user: CurrentUser,
    db: AsyncSession = Depends(get_db),
    type: str = Query(..., description="CompetitionType value"),
    period: Optional[str] = Query(
        None,
        description="Opcjonalny okres (np. 'Q2 2026' lub '2026-04'). "
        "Domyślnie: bieżący kwartał/miesiąc.",
    ),
):
    """Live ranking (bez zapisu do DB). Pokazuje TOP 10 + meta (countdown,
    system punktowy, pula nagród, warunek udziału)."""
    ctype = _parse_type(type)
    if period is None:
        if ctype in (
            CompetitionType.quarterly_champions_dl,
            CompetitionType.quarterly_champions_recruiter,
        ):
            period = comp_service.current_quarter_period()
        elif ctype == CompetitionType.hall_of_fame:
            period = "all_time"
        else:
            period = comp_service.current_month_period()

    if ctype == CompetitionType.hall_of_fame:
        ranked = await comp_service.hall_of_fame(db, limit=5)
    else:
        ranked = await comp_service.compute_live(db, ctype, period)

    top3 = ranked[:3]
    # Dopasuj nagrody live (dla preview).
    top3_with_prizes = [
        {
            **r.to_dict(),
            "rank": idx + 1,
            "prize_pln": comp_service._prize_for(ctype, idx + 1),
        }
        for idx, r in enumerate(top3)
    ]

    # Meta fields (gamifikacja jak w InfraReporterze).
    today = date.today()
    days_remaining: Optional[int] = None
    prize_pool: Optional[int] = None
    requirement: Optional[str] = None
    points_formula: Optional[dict] = None

    if ctype in (
        CompetitionType.quarterly_champions_dl,
        CompetitionType.quarterly_champions_recruiter,
    ):
        days_remaining = comp_service.days_left_in_quarter(today)
        prize_pool = sum(comp_service.QUARTERLY_PRIZES_PLN.values())
        if ctype == CompetitionType.quarterly_champions_dl:
            requirement = (
                f"Wymagane hit ratio ≥ {int(comp_service.HIT_RATIO_TARGET)}% "
                f"oraz minimum {comp_service.QUARTERLY_MIN_PLACEMENTS} placementy "
                "w kwartale."
            )
        else:
            requirement = (
                f"Wymagane minimum {comp_service.QUARTERLY_MIN_PLACEMENTS} "
                "placementów w kwartale (łącznie 1 miesięcznie)."
            )
            points_formula = comp_service.POINTS_FORMULA
    elif ctype in (
        CompetitionType.monthly_recommendations,
        CompetitionType.monthly_placements,
    ):
        days_remaining = comp_service.days_left_in_month(today)
        prize_pool = comp_service.MONTHLY_RACE_PRIZE_PLN

    return {
        "type": ctype.value,
        "period": period,
        "top3": top3_with_prizes,
        "full_ranking": [r.to_dict() for r in ranked],
        "is_frozen": False,
        "target_pct": (
            comp_service.HIT_RATIO_TARGET
            if ctype == CompetitionType.quarterly_champions_dl
            else None
        ),
        "days_remaining": days_remaining,
        "prize_pool_pln": prize_pool,
        "requirement": requirement,
        "points_formula": points_formula,
        "quarterly_prizes_pln": (
            comp_service.QUARTERLY_PRIZES_PLN
            if ctype
            in (
                CompetitionType.quarterly_champions_dl,
                CompetitionType.quarterly_champions_recruiter,
            )
            else None
        ),
    }


@router.get("/monthly-races")
async def monthly_races(
    _user: CurrentUser,
    db: AsyncSession = Depends(get_db),
    period: Optional[str] = None,
):
    """Dwa wyścigi miesięczne w jednym response (dla hero dashboard):
    Wyścig Rekomendacji + Wyścig Placementów. Każdy z warunkami kwal +
    oznaczeniem czyją nagrodę wyklucza lider kwartału.
    """
    month_period = period or comp_service.current_month_period()
    quarter_period = comp_service.current_quarter_period()

    rec_ranked = await comp_service.monthly_most_recommendations(db, month_period)
    pl_ranked = await comp_service.monthly_most_placements(db, month_period)

    # Wykluczenie: lider kwartalny (rank 1 w quarterly_champions_recruiter)
    # nie może wygrać wyścigu miesięcznego — tylko z ranking nie wypadamy.
    quarterly = await comp_service.quarterly_champions_recruiter(db, quarter_period)
    excluded_ids = {quarterly[0].user_id} if quarterly else set()

    days_left = comp_service.days_left_in_month(date.today())

    def _format(ranked, extra_reqs: list[str]) -> dict:
        ranking = [
            {
                **r.to_dict(),
                "rank": idx + 1,
                "excluded": r.user_id in excluded_ids,
            }
            for idx, r in enumerate(ranked)
        ]
        # Zakwalifikowany lider = pierwszy niewykluczony.
        qualified = next((entry for entry in ranking if not entry["excluded"]), None)
        return {
            "period": month_period,
            "days_remaining": days_left,
            "prize": {
                "amount_pln": comp_service.MONTHLY_RACE_PRIZE_PLN,
                "name": comp_service.MONTHLY_RACE_PRIZE_NAME,
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
                    f"Wymóg: min. {comp_service.MONTHLY_RACE_MIN_VERIFICATIONS_PER_DAY} "
                    "weryfikacji/dzień roboczy w tym miesiącu"
                ),
                (
                    f"Wymóg: min. {int(comp_service.MONTHLY_RACE_MIN_PRECISION_PCT)}% "
                    "precision rate (rekomendacje / weryfikacje)"
                ),
            ],
        ),
        "placements": _format(
            pl_ranked,
            [
                (
                    f"Minimum {comp_service.MONTHLY_RACE_MIN_PLACEMENTS} "
                    "placementy do kwalifikacji"
                )
            ],
        ),
    }


@router.get("/history")
async def get_history(
    _user: CurrentUser,
    db: AsyncSession = Depends(get_db),
    type: str = Query(...),
    limit: int = Query(10, ge=1, le=100),
):
    """Historia zamrożonych wyników z `competition_winners`."""
    ctype = _parse_type(type)
    q = (
        select(CompetitionWinner, User.name.label("user_name"))
        .join(User, CompetitionWinner.user_id == User.id)
        .where(CompetitionWinner.competition_type == ctype.value)
        .order_by(desc(CompetitionWinner.period), CompetitionWinner.rank)
        .limit(limit * 3)  # 3 pozycje per period
    )
    rows = (await db.execute(q)).all()
    by_period: dict[str, list[dict]] = {}
    for w, user_name in rows:
        by_period.setdefault(w.period, []).append(
            {
                "rank": w.rank,
                "user_id": w.user_id,
                "user_name": user_name,
                "metric_value": w.metric_value,
                "points": w.points,
                "prize_pln": w.prize_pln,
                "created_at": w.created_at.isoformat(),
            }
        )
    return {
        "type": ctype.value,
        "periods": [
            {"period": p, "top3": by_period[p]}
            for p in sorted(by_period.keys(), reverse=True)[:limit]
        ],
    }


@router.post("/freeze")
async def freeze(
    _user: AdminUser,
    db: AsyncSession = Depends(get_db),
    type: str = Query(...),
    period: str = Query(..., description="Okres do zamrożenia, np. 'Q1 2026'"),
):
    """Zamyka okres — zapisuje TOP 3 do `competition_winners` (idempotent)."""
    ctype = _parse_type(type)
    created = await comp_service.freeze_competition(db, ctype, period)
    return {
        "ok": True,
        "type": ctype.value,
        "period": period,
        "saved_count": len(created),
    }


@router.get("/my-position")
async def my_position(
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
    type: str = Query(...),
    period: Optional[str] = None,
):
    """Pozycja zalogowanego usera w bieżącym konkursie + kontekst (±2)."""
    ctype = _parse_type(type)
    if period is None:
        if ctype in (
            CompetitionType.quarterly_champions_dl,
            CompetitionType.quarterly_champions_recruiter,
        ):
            period = comp_service.current_quarter_period()
        elif ctype == CompetitionType.hall_of_fame:
            period = "all_time"
        else:
            period = comp_service.current_month_period()

    if ctype == CompetitionType.hall_of_fame:
        ranked = await comp_service.hall_of_fame(db, limit=50)
    else:
        ranked = await comp_service.compute_live(db, ctype, period)

    my_idx = next(
        (i for i, r in enumerate(ranked) if r.user_id == current_user.id), None
    )
    if my_idx is None:
        return {
            "type": ctype.value,
            "period": period,
            "rank": None,
            "me": None,
            "context": [],
            "total": len(ranked),
        }

    # Kontekst: ja ± 2 pozycje.
    ctx_start = max(0, my_idx - 2)
    ctx_end = min(len(ranked), my_idx + 3)
    context = [
        {**r.to_dict(), "rank": i + 1}
        for i, r in enumerate(ranked)
        if ctx_start <= i < ctx_end
    ]
    return {
        "type": ctype.value,
        "period": period,
        "rank": my_idx + 1,
        "me": ranked[my_idx].to_dict(),
        "context": context,
        "total": len(ranked),
    }
