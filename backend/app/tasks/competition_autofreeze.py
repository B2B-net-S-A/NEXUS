"""Background task: auto-freeze Liga Mistrzów + Wyścigi Miesięczne.

Odpala raz na godzinę i sprawdza, czy poprzedni miesiąc/kwartał jest już
zamknięty (wiersze podium w `competition_winners` ALBO zamknięcie w
`competition_period_closures`). Jeśli NIE — i okres jest „dojrzały" — liczy
ranking i zapisuje.

Okres jest dojrzały (decyzja 22.09.2026) dopiero gdy:

* `business_today()` (Warszawa, nie UTC) to co najmniej 3. polski dzień
  roboczy po końcu okresu, ORAZ
* przy włączonym syncu Traffita — dzienny import, który RUSZYŁ po końcu
  okresu, skończył się czysto (znacznik `__daily__`).

Wcześniej freeze szedł 1. dnia o 02:00–03:00 w Warszawie (`date.today()`
w UTC), zanim nocny import (04:00) dowiózł ruchy z ostatniego dnia okresu —
w kwietniu te ruchy przepadły z płatnego rozliczenia.

Zamrożony okres jest **niezmienny**: ponowny freeze (także ręczny przez
POST /api/competitions/freeze) nic nie nadpisuje. Okres bez zwycięzcy i okres
z remisem czekającym na admina też są zamknięte — nie liczymy ich od nowa.
"""

import asyncio
import calendar
import logging
from datetime import date

from sqlalchemy import exists, select

from app.core.database import AsyncSessionLocal
from app.core.scheduling import business_today
from app.models.competition_period_closure import CompetitionPeriodClosure
from app.models.competition_winner import CompetitionType, CompetitionWinner
from app.services import competition_rules
from app.services import competitions as comp_service

logger = logging.getLogger(__name__)

# Sprawdzamy co 1h — niski koszt, wystarczająca częstotliwość dla okresów
# mierzonych w miesiącach/kwartałach.
CHECK_INTERVAL_SECONDS = 3600


async def _is_period_frozen(db, competition_type: CompetitionType, period: str) -> bool:
    """Czy (typ, okres) jest zamknięty: podium ALBO wiersz zamknięcia.

    Pytamy o EXISTS, nie o wiersz: zamrożony okres ma do 3 zwycięzców
    (`rank IN (1,2,3)`), więc każde `scalar_one_or_none()` wywracało się na
    MultipleResultsFound i ubijało całą iterację autofreeze'a. Zamknięcie
    (0344) obejmuje okresy bez zwycięzcy i z remisem do decyzji admina —
    bez niego autofreeze liczył je od nowa co godzinę.
    """
    return bool(
        (
            await db.execute(
                select(
                    exists().where(
                        CompetitionWinner.competition_type == competition_type.value,
                        CompetitionWinner.period == period,
                    )
                    | exists().where(
                        CompetitionPeriodClosure.competition_type
                        == competition_type.value,
                        CompetitionPeriodClosure.period == period,
                    )
                )
            )
        ).scalar()
    )


def _month_period_end(period: str):
    """(ostatni dzień miesiąca, koniec okresu w UTC) dla '2026-04'."""
    year, month = comp_service.parse_month(period)
    last_day = date(year, month, calendar.monthrange(year, month)[1])
    _start, end_utc = comp_service.month_bounds(year, month)
    return last_day, end_utc


def _quarter_period_end(period: str):
    """(ostatni dzień kwartału, koniec okresu w UTC) dla 'Q2 2026'."""
    year, quarter = comp_service.parse_quarter(period)
    last_month = quarter * 3
    last_day = date(year, last_month, calendar.monthrange(year, last_month)[1])
    _start, end_utc = comp_service.quarter_bounds(year, quarter)
    return last_day, end_utc


async def _rollback_quietly(db) -> None:
    """Odblokuj sesję po nieudanym typie, żeby następny mógł jeszcze pytać.

    Bez tego sesja zostaje w stanie „pending rollback" i kolejny konkurs
    dostaje błąd, którego sam nie spowodował — containment byłby pozorny.
    """
    try:
        await db.rollback()
    except Exception as exc:  # noqa: BLE001
        logger.warning("auto-freeze rollback failed: %s", exc)


async def _freeze_if_ready(
    db,
    ctype: CompetitionType,
    period: str,
    period_end,
    today: date,
    results: dict[str, int],
) -> None:
    # Bramka W ŚRODKU try (u wołającego) — jej awaria ma degradować JEDEN typ
    # konkursu, a nie zjadać pozostałe typy w tej samej iteracji.
    if await _is_period_frozen(db, ctype, period):
        return
    last_day, end_utc = period_end
    readiness = await competition_rules.freeze_readiness(
        db, period_last_day=last_day, period_end_utc=end_utc, today=today
    )
    if not readiness.ready:
        logger.info(
            "auto-freeze %s for %s postponed: %s (earliest %s)",
            ctype.value,
            period,
            readiness.reason,
            readiness.earliest_day.isoformat(),
        )
        return
    created = await comp_service.freeze_competition(
        db, ctype, period, reason="autofreeze"
    )
    results[f"{ctype.value}:{period}"] = created.saved_count
    # `0 winners` jest dwuznaczne: nikt się nie zakwalifikował, remis czeka
    # na admina, czy okres był już zamrożony? Status zamknięcia to rozstrzyga.
    logger.info(
        "auto-freeze %s for %s: %d winners (%s, closure=%s)",
        ctype.value,
        period,
        created.saved_count,
        "already frozen" if created.already_frozen else "written",
        getattr(created, "closure_status", None),
    )


async def snapshot_current_month_thresholds(today: date | None = None) -> None:
    """Zapisz progi wyścigu bieżącego miesiąca (R3-15). Własna sesja, nie rzuca.

    Pierwszy zapis w miesiącu wygrywa, więc zmiana celu KPI w trakcie
    miesiąca obowiązuje dopiero od następnego — zwycięzcy wyścigu z nagrodą
    nie da się przestawić wstecz edycją celu.
    """
    period = comp_service.current_month_period(today or business_today())
    try:
        async with AsyncSessionLocal() as db:
            await comp_service.snapshot_monthly_race_thresholds(db, period)
            await db.commit()
    except asyncio.CancelledError:
        raise
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "monthly race thresholds snapshot for %s failed (%s)",
            period,
            type(exc).__name__,
        )


async def _run_once(today: date | None = None) -> dict:
    """Jedna iteracja — zwraca dict z opisem zamrożonych okresów."""
    today = today or business_today()
    results: dict[str, int] = {}

    prev_month_period = await comp_service.previous_month_period(today)
    prev_quarter_period = await comp_service.previous_quarter_period(today)
    current_q_period = comp_service.current_quarter_period(today)

    async with AsyncSessionLocal() as db:
        # Kwartał PRZED miesiącami: wykluczenie lidera kwartału z wyścigu
        # ostatniego miesiąca kwartału czyta wtedy zamrożonego zwycięzcę
        # (albo remis czekający na admina), a nie ranking liczony na żywo.
        if prev_quarter_period != current_q_period:
            for ctype in (
                CompetitionType.quarterly_champions_dl,
                CompetitionType.quarterly_champions_recruiter,
            ):
                try:
                    await _freeze_if_ready(
                        db,
                        ctype,
                        prev_quarter_period,
                        _quarter_period_end(prev_quarter_period),
                        today,
                        results,
                    )
                except Exception as exc:  # noqa: BLE001
                    logger.warning(
                        "auto-freeze failed for %s %s: %s",
                        ctype.value,
                        prev_quarter_period,
                        exc,
                    )
                    await _rollback_quietly(db)

        for ctype in (
            CompetitionType.monthly_recommendations,
            CompetitionType.monthly_placements,
        ):
            try:
                await _freeze_if_ready(
                    db,
                    ctype,
                    prev_month_period,
                    _month_period_end(prev_month_period),
                    today,
                    results,
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "auto-freeze failed for %s %s: %s",
                    ctype.value,
                    prev_month_period,
                    exc,
                )
                await _rollback_quietly(db)

    return results


async def competition_autofreeze_loop() -> None:
    """Pętla startowana z main.lifespan. Bezpieczna na CancelledError."""
    logger.info("competition_autofreeze_loop started")
    while True:
        # 0343: seria „Zatrudniony" bez CV ma zniknąć z rankingu ZANIM okres
        # zostanie zamrożony — zamrożone podium jest niezmienne i wypłaca
        # nagrody. Działa także przy wyłączonym imporcie Traffita (drugi punkt
        # wykrywania). Własna sesja, nigdy nie rzuca.
        from app.services.placement_exclusions import run_detection_safely

        await run_detection_safely("competition_autofreeze")
        await snapshot_current_month_thresholds()
        try:
            await _run_once()
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001
            logger.warning("competition_autofreeze iteration failed: %s", exc)
        try:
            await asyncio.sleep(CHECK_INTERVAL_SECONDS)
        except asyncio.CancelledError:
            break
    logger.info("competition_autofreeze_loop stopped")
