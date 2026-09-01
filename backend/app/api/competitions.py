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
from app.services.insights_scoring_config import (
    get_scoring_config,
    league_points_formula,
)
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


# D7 (Artur, 2026-08-31): odczyty konkursow sa otwarte dla KAZDEJ zalogowanej
# roli — Liga Mistrzow, wyscigi i Hall of Fame sa czescia /insights.
#
# To jedyny wspoldzielony endpoint, ktory wolno bylo poszerzyc NA MIEJSCU:
# jego jedynym konsumentem we froncie jest ChampionsSection.tsx, czyli sama
# powierzchnia Insights (`grep -rn "/api/competitions" frontend/src`), a
# `/my-position` juz stalo na CurrentUser. Pozostale powierzchnie (/api/reports/*,
# /api/admin/clients-overview, /api/dashboard/v2/*) sa wspoldzielone z INNYMI
# stronami — tam Insights dostaje wlasne /api/insights/*, zamiast poszerzac cudzy
# guard. Zapisy (freeze) zostaja na AdminUser.
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

    hof_scope = None
    if ctype == CompetitionType.hall_of_fame:
        # Lista i podpis pod nią z JEDNEGO zapytania — dwa osobne biegłyby
        # na dwóch snapshotach (READ COMMITTED), więc zapis między nimi
        # rozjeżdżałby ranking z liczbą, która go opisuje.
        ranked, scope = await comp_service.hall_of_fame_with_scope(db, limit=5)
        hof_scope = scope.to_dict()
    else:
        ranked = await comp_service.compute_live(db, ctype, period)

    award_ranked = (
        comp_service.qualified_for_award(ranked)
        if ctype == CompetitionType.monthly_recommendations
        else ranked
    )
    top3 = award_ranked[:3]
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
            # Wagi i próg z konfiguracji (D3). Stała `QUARTERLY_MIN_PLACEMENTS`
            # została usunięta — sensem D3 jest JEDNO źródło reguły.
            config = await get_scoring_config(db)
            # Próg jest PROGRESYWNY (1/2/3 wg miesiąca kwartału), a napis musi
            # mówić to samo, co kwalifikacja. Płaskie „3" oświadczało w styczniu
            # wymóg, którego silnik wtedy nie stosuje — ekran opisywał regułę,
            # której nie ma, i nie drgnąłby po zmianie progu przez admina.
            _year, _quarter = comp_service.parse_quarter(period)
            required = comp_service.required_placements_for_quarter(
                _year, _quarter, config, today
            )
            requirement = (
                f"Wymagane minimum {required} "
                f"{'placement' if required == 1 else 'placementów'} "
                "w kwartale (próg rośnie z każdym miesiącem kwartału)."
            )
            points_formula = league_points_formula(config)
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
        # `null` dla wszystkich typów poza Hall of Fame — pozostałe rankingi są
        # okresowe i mają własny warunek udziału w `requirement`.
        "scope": hof_scope,
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
    # Kompozycja (rankingi + wykluczenie lidera kwartału) wyniesiona do
    # serwisu — composite dashboardu używa dokładnie tej samej funkcji.
    return await comp_service.compose_monthly_races(db, period)


@router.get("/history")
async def get_history(
    # D7, 2026-09-01: poszerzone do `CurrentUser` razem z /current
    # i /monthly-races. Poprzedni komentarz odmawial poszerzenia z JEDNEGO
    # powodu — „/history nie ma dzis zadnego konsumenta we froncie" — i ten
    # powod wlasnie wygasl: sekcja „Hall of Fame" na /insights
    # (InsightsHallOfFame.tsx) czyta wlasnie te trase.
    #
    # Alternatywa rozwazana i odrzucona: wlasna trasa /api/insights/hall-of-fame.
    # Byloby to opakowanie tego samego SELECT-a z `competition_winners` po to
    # tylko, zeby ominac guard — a `/history` nie jest wspoldzielone z zadna
    # inna strona (`grep -rn "/api/competitions/history" frontend/src`), wiec
    # poszerzenie nie zmienia widocznosci zadnej istniejacej powierzchni.
    # To ta sama sytuacja co /current, ktory poszerzono NA MIEJSCU.
    #
    # Co ta trasa oddaje: nazwiska podium i kwoty juz PRZYZNANYCH nagrod.
    # /current i /monthly-races oddaja ten sam material na zywo, wiec zamkniety
    # snapshot nie jest wezszy niz to, co kazda zalogowana rola widzi obok.
    # Zapis (POST /freeze) zostaje na AdminUser.
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
    """Zamyka okres — pierwszy zapis TOP 3 jest niezmiennym snapshotem."""
    ctype = _parse_type(type)
    # Hall of Fame NIE MA okresu do zamknięcia: jest rankingiem żywym, liczonym
    # z całej historii, i nie ma puli nagród. Bez tej bramki jeden admin
    # z curl-em zapisuje do `competition_winners` wiersze z `prize_pln = 0`,
    # których nie da się usunąć (write-once), a `/history` podaje je potem
    # KAŻDEJ zalogowanej roli jako „zamknięty okres". Kolumna
    # `competition_type` to `String(50)` bez CHECK-a, więc baza tego nie
    # zatrzyma — musi to zrobić API.
    if ctype == CompetitionType.hall_of_fame:
        raise HTTPException(
            status_code=422,
            detail=(
                "Hall of Fame to ranking żywy, liczony z całej historii — "
                "nie ma okresu do zamknięcia."
            ),
        )
    created = await comp_service.freeze_competition(db, ctype, period)
    # `len(created)` to rozmiar podium, nie liczba ZAPISANYCH wierszy — przy
    # ponownym zamrożeniu okresu serwis zwraca istniejący snapshot bez zapisu,
    # więc odpowiedź meldowała „saved_count: 3" mimo że nic się nie stało.
    return {
        "ok": True,
        "type": ctype.value,
        "period": period,
        "saved_count": created.saved_count,
        "already_frozen": created.already_frozen,
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
