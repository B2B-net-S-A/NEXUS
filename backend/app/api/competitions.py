"""Router `/api/competitions/*` — Liga Mistrzów kwartalna + Wyścigi Miesięczne
+ Hall of Fame.

Dostęp: sekcja Insights; POST /freeze dodatkowo tylko admin.
"""

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import AdminUser, CurrentUser
from app.api.section_access import INSIGHTS_SECTION_DEPENDENCIES
from app.core.cache import cache_get, cache_invalidate, cache_set, cache_single_flight
from app.core.database import get_db
from app.core.scheduling import business_today
from app.services.insights_scoring_config import league_points_formula
from app.models.competition_winner import CompetitionType, CompetitionWinner
from app.models.user import User
from app.services import competitions as comp_service

router = APIRouter(dependencies=INSIGHTS_SECTION_DEPENDENCIES)


def _check_period_format(ctype: CompetitionType, period: Optional[str]) -> None:
    """Zły format okresu = 422 po polsku, nie 500 z `parse_month`."""
    if period is None or ctype == CompetitionType.hall_of_fame:
        return
    try:
        comp_service.validate_period_format(ctype, period)
    except comp_service.PeriodValidationError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message)


# Marża/h z rozstrzygania remisu wyścigu placementów (`award_order`) to
# pieniądze — ranking czyta każdy zalogowany (lustro `_MARGIN_EXTRAS`
# w `compose_monthly_races`).
def _public_entry(entry: dict) -> dict:
    return {k: v for k, v in entry.items() if k not in comp_service._MARGIN_EXTRAS}


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


# D7 (Artur, 2026-08-31): odczyty konkursow sa czescia /insights i domyslna
# macierz nadal otwiera Insights kazdej aktywnej roli. Konfigurowalna bramka
# sekcji moze jednak ten domyslny dostep jawnie wycofac.
#
# To jedyny wspoldzielony endpoint, ktory wolno bylo poszerzyc NA MIEJSCU:
# jego jedynym konsumentem we froncie jest ChampionsSection.tsx, czyli sama
# powierzchnia Insights (`grep -rn "/api/competitions" frontend/src`), a
# `/my-position` juz stalo na CurrentUser. Pozostale powierzchnie (/api/reports/*,
# /api/admin/clients-overview, /api/dashboard/v2/*) sa wspoldzielone z INNYMI
# stronami — tam Insights dostaje wlasne /api/insights/*, zamiast poszerzac cudzy
# guard. Zapisy (freeze) zostaja na AdminUser.
# Rankingi na żywo są takie same dla każdego oglądającego, a jedno przeliczenie
# to kilka sekund pracy Postgresa (`VERIFIER_ANCHORED_CTE`). Test obciążeniowy
# 24.09.2026: przy 30 osobach `/monthly-races` p50 5,9 s i `/current` ~3 s,
# liczone od nowa przy każdym wejściu na Insights. Minuta opóźnienia rankingu
# nie zmienia niczego w konkursie (nagrody wypłaca zamrożenie, nie ten widok);
# zamrożenie i rozstrzygnięcie remisu czyszczą cache od razu.
_CACHE_PREFIX = "competitions:"
_CACHE_TTL_SECONDS = 60


async def _remember(key: str, value: dict) -> None:
    # Rozrzut wygaśnięcia tylko przy dodatnim TTL — testy wyłączają cache
    # ujemnym TTL-em i rozrzut przywróciłby wtedy kilka sekund ważności.
    jitter = 10 if _CACHE_TTL_SECONDS > 0 else 0
    await cache_set(key, value, ttl_seconds=_CACHE_TTL_SECONDS, jitter_seconds=jitter)


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
    _check_period_format(ctype, period)
    key = f"{_CACHE_PREFIX}current:{ctype.value}:{period or ''}"
    async with cache_single_flight(key, db=db):
        cached = await cache_get(key)
        if cached is not None:
            return cached
        result = await _compute_current(db, ctype, period)
        await _remember(key, result)
        return result


async def _compute_current(
    db: AsyncSession, ctype: CompetitionType, period: Optional[str]
) -> dict:
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

    # Podium liczy TA SAMA funkcja co zamrożenie (`award_order`): kwalifikacja,
    # wykluczenie lidera kwartału z wyścigu miesięcznego i remisy. Do 25.09.2026
    # ekran brał `ranked[:3]` (poza wyścigiem rekomendacji) — podium i kwoty
    # różniły się od tego, co potem wypłacało zamrożenie. Miejsce objęte
    # remisem, którego regulamin nie rozstrzyga, nie ma kwoty (`tied`).
    order = await comp_service.award_order(db, ctype, period, ranked)
    # Lista pod podium i podium z JEDNEJ numeracji (`award_ranked_rows`):
    # osoba bez miejsca w klasyfikacji ma `rank: null`, nie „#1".
    rows = comp_service.award_ranked_rows(ctype, ranked, order)
    top3_with_prizes = [
        row for row in rows if row["rank"] is not None and row["rank"] <= 3
    ]

    # Meta fields (gamifikacja jak w InfraReporterze).
    # Kalendarz warszawski, nie UTC — ten sam, którym liczone są okresy.
    today = business_today()
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
            # Punktacja tego kwartału (migawka, R4-16) — ta sama, którą
            # zamrożenie rozlicza Ligę.
            config = await comp_service.league_scoring_config(db, period)
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
        "full_ranking": rows,
        # Remisy na płatnych miejscach, o których zdecyduje admin przy
        # zamknięciu okresu — same pozycje i osoby, bez marży.
        "ties": [
            {"positions": tie.positions, "user_ids": tie.user_ids} for tie in order.ties
        ],
        "excluded_user_ids": order.excluded_user_ids,
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
    _check_period_format(CompetitionType.monthly_recommendations, period)
    key = f"{_CACHE_PREFIX}monthly-races:{period or ''}"
    async with cache_single_flight(key, db=db):
        cached = await cache_get(key)
        if cached is not None:
            return cached
        result = await comp_service.compose_monthly_races(db, period)
        await _remember(key, result)
        return result


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
    # Zamrożenie jest nieodwracalne (write-once), więc okres musi mieć
    # właściwy format i być zakończony (R3-14, audyt 25.09.2026).
    try:
        comp_service.validate_period_format(ctype, period)
        comp_service.ensure_period_ended(ctype, period, business_today())
    except comp_service.PeriodValidationError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message)
    created = await comp_service.freeze_competition(db, ctype, period)
    await cache_invalidate(_CACHE_PREFIX)
    # `len(created)` to rozmiar podium, nie liczba ZAPISANYCH wierszy — przy
    # ponownym zamrożeniu okresu serwis zwraca istniejący snapshot bez zapisu,
    # więc odpowiedź meldowała „saved_count: 3" mimo że nic się nie stało.
    return {
        "ok": True,
        "type": ctype.value,
        "period": period,
        "saved_count": created.saved_count,
        "already_frozen": created.already_frozen,
        # frozen | no_winner | tie_pending | tie_resolved; null = okres
        # zamrożony przed 0344 (same wiersze podium).
        "closure_status": created.closure_status,
    }


@router.get("/ties")
async def list_pending_ties(
    _user: AdminUser,
    db: AsyncSession = Depends(get_db),
):
    """Remisy na płatnych miejscach czekające na decyzję admina.

    Miejsca objęte remisem nie mają wierszy podium (0 zł), dopóki admin nie
    ustali kolejności — `POST /{type}/{period}/resolve-tie`.
    """
    return {"items": await comp_service.pending_competition_ties(db)}


class ResolveTieRequest(BaseModel):
    # Wszyscy remisujący ze wszystkich remisów okresu, w kolejności remisów
    # z `GET /ties` i — w obrębie remisu — w kolejności decyzji.
    user_ids: list[int] = Field(..., min_length=2, max_length=50)


@router.post("/{type}/{period}/resolve-tie")
async def resolve_tie(
    type: str,
    period: str,
    payload: ResolveTieRequest,
    user: AdminUser,
    db: AsyncSession = Depends(get_db),
):
    """Admin rozstrzyga remis: kolejność → wiersze podium z nagrodą."""
    ctype = _parse_type(type)
    try:
        result = await comp_service.resolve_competition_tie(
            db, ctype, period, payload.user_ids, actor_id=user.id
        )
    except comp_service.TieResolutionError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message)
    await cache_invalidate(_CACHE_PREFIX)
    return result


@router.get("/my-position")
async def my_position(
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
    type: str = Query(...),
    period: Optional[str] = None,
):
    """Pozycja zalogowanego usera w bieżącym konkursie + kontekst (±2)."""
    ctype = _parse_type(type)
    _check_period_format(ctype, period)
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

    hof_total: int | None = None
    if ctype == CompetitionType.hall_of_fame:
        # PEŁNY ranking, nie `limit=50`. Hall of Fame liczy dziś 59 osób, więc
        # sztywne 50 odpowiadało 51. osobie „nie ma cię w rankingu", mimo że ma
        # placementy — a `total` opisywał długość PRZYCIĘTEJ listy, nie liczbę
        # osób w rankingu. Odpowiedź o własnej pozycji nie może zależeć od tego,
        # gdzie ktoś postawił limit prezentacyjny.
        ranked, scope = await comp_service.hall_of_fame_with_scope(db, limit=None)
        hof_total = scope.ranked_people
    else:
        ranked = await comp_service.compute_live(db, ctype, period)

    # Ta sama numeracja co podium i lista pod nim (`award_ranked_rows`):
    # niezakwalifikowany i wykluczony lider kwartału są na liście, ale bez
    # miejsca (`rank: null`). Do 25.09.2026 numer brano z pozycji w surowym
    # rankingu, więc „Mój miesiąc” mówił „1. miejsce” osobie bez nagrody.
    order = await comp_service.award_order(db, ctype, period, ranked)
    rows = comp_service.award_ranked_rows(ctype, ranked, order)
    total = hof_total if hof_total is not None else len(rows)
    my_idx = next(
        (i for i, row in enumerate(rows) if row["user_id"] == current_user.id), None
    )
    if my_idx is None:
        return {
            "type": ctype.value,
            "period": period,
            "rank": None,
            "me": None,
            "context": [],
            "total": total,
        }

    # Kontekst: ja ± 2 pozycje.
    ctx_start = max(0, my_idx - 2)
    ctx_end = min(len(rows), my_idx + 3)
    return {
        "type": ctype.value,
        "period": period,
        "rank": rows[my_idx]["rank"],
        "me": rows[my_idx],
        "context": rows[ctx_start:ctx_end],
        "total": total,
    }
