"""Background task: auto-freeze Liga Mistrzów + Wyścigi Miesięczne.

Odpala raz na godzinę i sprawdza czy dla poprzedniego miesiąca/kwartału
istnieje już zamrożony snapshot w `competition_winners`. Jeśli NIE — liczy
ranking i zapisuje.

Dzięki temu każdy kwartał/miesiąc automatycznie zostaje rozliczony bez
ingerencji admina. Zamrożony okres jest **niezmienny**: ponowny freeze
(także ręczny przez POST /api/competitions/freeze) nic nie nadpisuje —
zwraca istniejące podium z `already_frozen=True`. Poprawienie błędnego
podium wymaga świadomej, osobnej interwencji na danych, nie re-freeze'a.
"""

import asyncio
import logging
from datetime import date

from sqlalchemy import exists, select

from app.core.database import AsyncSessionLocal
from app.models.competition_winner import CompetitionType, CompetitionWinner
from app.services import competitions as comp_service

logger = logging.getLogger(__name__)

# Sprawdzamy co 1h — niski koszt, wystarczająca częstotliwość dla okresów
# mierzonych w miesiącach/kwartałach.
CHECK_INTERVAL_SECONDS = 3600


async def _is_period_frozen(db, competition_type: CompetitionType, period: str) -> bool:
    """Czy (typ, okres) ma JAKIKOLWIEK zamrożony wiersz.

    Pytamy o EXISTS, nie o wiersz: zamrożony okres ma do 3 zwycięzców
    (`rank IN (1,2,3)`), więc każde `scalar_one_or_none()` wywracało się na
    MultipleResultsFound i ubijało całą iterację autofreeze'a.
    """
    return bool(
        (
            await db.execute(
                select(
                    exists().where(
                        CompetitionWinner.competition_type == competition_type.value,
                        CompetitionWinner.period == period,
                    )
                )
            )
        ).scalar()
    )


async def _rollback_quietly(db) -> None:
    """Odblokuj sesję po nieudanym typie, żeby następny mógł jeszcze pytać.

    Bez tego sesja zostaje w stanie „pending rollback" i kolejny konkurs
    dostaje błąd, którego sam nie spowodował — containment byłby pozorny.
    """
    try:
        await db.rollback()
    except Exception as exc:  # noqa: BLE001
        logger.warning("auto-freeze rollback failed: %s", exc)


async def _run_once(today: date | None = None) -> dict:
    """Jedna iteracja — zwraca dict z opisem zamrożonych okresów."""
    today = today or date.today()
    results: dict[str, int] = {}

    # Monthly races — poprzedni miesiąc.
    prev_month_period = await comp_service.previous_month_period(today)
    # Quarterly champions — tylko gdy weszliśmy w nowy kwartał (bieżący Q
    # ma inny number niż poprzedni) — czyli w styczniu/kwietniu/lipcu/październiku.
    prev_quarter_period = await comp_service.previous_quarter_period(today)
    current_q_period = comp_service.current_quarter_period(today)

    async with AsyncSessionLocal() as db:
        # Monthly — zawsze sprawdzamy poprzedni miesiąc.
        for ctype in (
            CompetitionType.monthly_recommendations,
            CompetitionType.monthly_placements,
        ):
            # Bramka W ŚRODKU try — jej awaria ma degradować JEDEN typ
            # konkursu, a nie zjadać pozostałe typy w tej samej iteracji.
            try:
                if await _is_period_frozen(db, ctype, prev_month_period):
                    continue
                created = await comp_service.freeze_competition(
                    db, ctype, prev_month_period
                )
                results[f"{ctype.value}:{prev_month_period}"] = created.saved_count
                logger.info(
                    "auto-freeze %s for %s: %d winners",
                    ctype.value,
                    prev_month_period,
                    created.saved_count,
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "auto-freeze failed for %s %s: %s",
                    ctype.value,
                    prev_month_period,
                    exc,
                )
                await _rollback_quietly(db)

        # Quarterly — tylko gdy bieżący kwartał != poprzedni (czyli weszliśmy
        # w nowy). Próbujemy freeze'a poprzedniego kwartału.
        # prev_quarter_period to zawsze poprzedni względem today; gdy jesteśmy
        # w środku Q2, poprzedni to Q1 — i chcemy go zamrozić.
        # _is_period_frozen ochrania przed duplikatem.
        if prev_quarter_period != current_q_period:
            for ctype in (
                CompetitionType.quarterly_champions_dl,
                CompetitionType.quarterly_champions_recruiter,
            ):
                try:
                    if await _is_period_frozen(db, ctype, prev_quarter_period):
                        continue
                    created = await comp_service.freeze_competition(
                        db, ctype, prev_quarter_period
                    )
                    results[f"{ctype.value}:{prev_quarter_period}"] = (
                        created.saved_count
                    )
                    logger.info(
                        "auto-freeze %s for %s: %d winners",
                        ctype.value,
                        prev_quarter_period,
                        created.saved_count,
                    )
                except Exception as exc:  # noqa: BLE001
                    logger.warning(
                        "auto-freeze failed for %s %s: %s",
                        ctype.value,
                        prev_quarter_period,
                        exc,
                    )
                    await _rollback_quietly(db)

    return results


async def competition_autofreeze_loop() -> None:
    """Pętla startowana z main.lifespan. Bezpieczna na CancelledError."""
    logger.info("competition_autofreeze_loop started")
    while True:
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
