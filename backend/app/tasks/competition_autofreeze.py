"""Background task: auto-freeze Liga Mistrzów + Wyścigi Miesięczne.

Odpala raz na godzinę i sprawdza czy dla poprzedniego miesiąca/kwartału
istnieje już zamrożony snapshot w `competition_winners`. Jeśli NIE — liczy
ranking i zapisuje (idempotent — `freeze_competition` kasuje poprzednie
przed wstawieniem).

Dzięki temu każdy kwartał/miesiąc automatycznie zostaje rozliczony bez
ingerencji admina. Admin może zawsze **ręcznie** wymusić re-freeze przez
POST /api/competitions/freeze.
"""

import asyncio
import logging
from datetime import date

from sqlalchemy import select

from app.core.database import AsyncSessionLocal
from app.models.competition_winner import CompetitionType, CompetitionWinner
from app.services import competitions as comp_service

logger = logging.getLogger(__name__)

# Sprawdzamy co 1h — niski koszt, wystarczająca częstotliwość dla okresów
# mierzonych w miesiącach/kwartałach.
CHECK_INTERVAL_SECONDS = 3600


async def _is_period_frozen(db, competition_type: CompetitionType, period: str) -> bool:
    existing = (
        await db.execute(
            select(CompetitionWinner).where(
                CompetitionWinner.competition_type == competition_type.value,
                CompetitionWinner.period == period,
            )
        )
    ).scalar_one_or_none()
    return existing is not None


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
            if not await _is_period_frozen(db, ctype, prev_month_period):
                try:
                    created = await comp_service.freeze_competition(
                        db, ctype, prev_month_period
                    )
                    results[f"{ctype.value}:{prev_month_period}"] = len(created)
                    logger.info(
                        "auto-freeze %s for %s: %d winners",
                        ctype.value,
                        prev_month_period,
                        len(created),
                    )
                except Exception as exc:  # noqa: BLE001
                    logger.warning(
                        "auto-freeze failed for %s %s: %s",
                        ctype.value,
                        prev_month_period,
                        exc,
                    )

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
                if not await _is_period_frozen(db, ctype, prev_quarter_period):
                    try:
                        created = await comp_service.freeze_competition(
                            db, ctype, prev_quarter_period
                        )
                        results[f"{ctype.value}:{prev_quarter_period}"] = len(created)
                        logger.info(
                            "auto-freeze %s for %s: %d winners",
                            ctype.value,
                            prev_quarter_period,
                            len(created),
                        )
                    except Exception as exc:  # noqa: BLE001
                        logger.warning(
                            "auto-freeze failed for %s %s: %s",
                            ctype.value,
                            prev_quarter_period,
                            exc,
                        )

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
