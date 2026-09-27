"""Background task: auto-freeze Liga Mistrzów + Wyścigi Miesięczne.

Odpala raz na godzinę i sprawdza, czy zakończone miesiące/kwartały (od rundy 9
kilka wstecz, nie tylko poprzedni) są już
zamknięte (wiersze podium w `competition_winners` ALBO zamknięcie w
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

# Runda 9 (R9-N6-6): pętla patrzyła wyłącznie na POPRZEDNI miesiąc i kwartał.
# Okres, który nie dojrzał na czas (import Traffita stał kilka dni na przełomie
# miesięcy), wypadał z przeglądu następnego miesiąca i nigdy nie był zamrażany —
# nagrody za niego nie powstawały. Przeglądamy kilka zakończonych okresów wstecz
# (najstarsze najpierw, kwartały przed miesiącami — reguła bez zmian).
MONTHS_LOOKBACK = 3
QUARTERS_LOOKBACK = 2
OVERDUE_WARNING_DAYS = 31


def _closed_months(today: date, count: int) -> list[str]:
    """`count` ostatnich ZAKOŃCZONYCH miesięcy, najstarszy pierwszy."""
    year, month = today.year, today.month
    periods: list[str] = []
    for _ in range(count):
        month -= 1
        if month == 0:
            month, year = 12, year - 1
        periods.append(f"{year}-{month:02d}")
    return list(reversed(periods))


def _closed_quarters(today: date, count: int) -> list[str]:
    """`count` ostatnich ZAKOŃCZONYCH kwartałów, najstarszy pierwszy."""
    year, quarter = today.year, (today.month - 1) // 3 + 1
    periods: list[str] = []
    for _ in range(count):
        quarter -= 1
        if quarter == 0:
            quarter, year = 4, year - 1
        periods.append(f"Q{quarter} {year}")
    return list(reversed(periods))


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
        # Runda 9 (R9-N6-6): okres czekający ponad miesiąc po końcu to sygnał
        # dla człowieka (zwykle import Traffita stoi), nie rutyna.
        overdue = (today - last_day).days > OVERDUE_WARNING_DAYS
        (logger.warning if overdue else logger.info)(
            "auto-freeze %s for %s postponed: %s (earliest %s)%s",
            ctype.value,
            period,
            readiness.reason,
            readiness.earliest_day.isoformat(),
            " — okres czeka na zamrożenie ponad miesiąc" if overdue else "",
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
    today = today or business_today()
    period = comp_service.current_month_period(today)
    try:
        async with AsyncSessionLocal() as db:
            await comp_service.snapshot_monthly_race_thresholds(db, period)
            # Punktacja Ligi bieżącego kwartału (R4-16): zmiana wag albo progów
            # placementów w trakcie kwartału obowiązuje od następnego — Ligi
            # z nagrodą i wykluczenia lidera z wyścigów nie da się przestawić
            # wstecz edycją konfiguracji.
            await comp_service.snapshot_league_scoring_config(
                db, comp_service.current_quarter_period(today)
            )
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

    async with AsyncSessionLocal() as db:
        # Kwartał PRZED miesiącami: wykluczenie lidera kwartału z wyścigu
        # ostatniego miesiąca kwartału czyta wtedy zamrożonego zwycięzcę
        # (albo remis czekający na admina), a nie ranking liczony na żywo.
        for quarter_period in _closed_quarters(today, QUARTERS_LOOKBACK):
            for ctype in (
                CompetitionType.quarterly_champions_dl,
                CompetitionType.quarterly_champions_recruiter,
            ):
                try:
                    await _freeze_if_ready(
                        db,
                        ctype,
                        quarter_period,
                        _quarter_period_end(quarter_period),
                        today,
                        results,
                    )
                except Exception as exc:  # noqa: BLE001
                    logger.warning(
                        "auto-freeze failed for %s %s: %s",
                        ctype.value,
                        quarter_period,
                        exc,
                    )
                    await _rollback_quietly(db)

        for month_period in _closed_months(today, MONTHS_LOOKBACK):
            for ctype in (
                CompetitionType.monthly_recommendations,
                CompetitionType.monthly_placements,
            ):
                try:
                    await _freeze_if_ready(
                        db,
                        ctype,
                        month_period,
                        _month_period_end(month_period),
                        today,
                        results,
                    )
                except Exception as exc:  # noqa: BLE001
                    logger.warning(
                        "auto-freeze failed for %s %s: %s",
                        ctype.value,
                        month_period,
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
