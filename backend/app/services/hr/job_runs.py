"""Rezerwacje przebiegów zadań w tle w ``hr_job_runs`` — jedno miejsce.

Każde zadanie modułów „Ludzi” (przypomnienia, uzgadnianie M365, premie,
opieka, Intune…) rezerwuje przebieg wierszem (rodzaj, klucz okresu), żeby
nocny restart albo dwa procesy nie zrobiły tej samej pracy dwa razy:

* ``claim`` — przebieg okresu (dzień, tydzień, kwadrans). Przejmuje wiersz
  nieudany albo porzucony (``claimed`` dłużej niż ``STALE_CLAIM``);
  zakończonego nie, chyba że ``retake_done`` (ręczne „Odczytaj teraz”).
* ``finish`` — wynik przebiegu (status, liczby, błąd).
* ``mark_once`` — znacznik „już zrobione” dla pojedynczej rzeczy (jedno
  przypomnienie na osobę i miesiąc): wstawia wiersz albo mówi, że był.

Wcześniej każdy moduł miał własną kopię tego samego SQL-a.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Optional

from sqlalchemy import and_, func, or_, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.hr_ops import HrJobRun

#: Rezerwacja starsza niż tyle bez zakończenia = przebieg przerwany.
STALE_CLAIM = timedelta(hours=1)

_CONSTRAINT = "uq_hr_job_runs_kind_period"


async def claim(
    db: AsyncSession,
    kind: str,
    period_key: str,
    now: datetime,
    *,
    retake_done: bool = False,
    commit: bool = True,
) -> Optional[int]:
    """Id zarezerwowanego przebiegu albo ``None``, gdy ktoś go ma lub skończył."""

    stale = and_(HrJobRun.status == "claimed", HrJobRun.claimed_at < now - STALE_CLAIM)
    retake = (
        HrJobRun.status != "claimed" if retake_done else HrJobRun.status == "failed"
    )
    statement = (
        insert(HrJobRun)
        .values(kind=kind, period_key=period_key, status="claimed")
        .on_conflict_do_update(
            constraint=_CONSTRAINT,
            set_={
                "status": "claimed",
                "claimed_at": func.now(),
                "finished_at": None,
                "error": None,
            },
            where=or_(retake, stale),
        )
        .returning(HrJobRun.id)
    )
    claimed = await db.scalar(statement)
    if commit:
        await db.commit()
    return claimed


async def finish(
    db: AsyncSession,
    run_id: int,
    *,
    status: str,
    counts: dict[str, Any],
    error: Optional[str] = None,
    commit: bool = True,
) -> None:
    await db.execute(
        update(HrJobRun)
        .where(HrJobRun.id == run_id)
        .values(status=status, counts=counts, error=error, finished_at=func.now())
    )
    if commit:
        await db.commit()


async def mark_once(
    db: AsyncSession, kind: str, period_key: str, *, status: str = "done"
) -> bool:
    """``True`` = znacznik wstawiony teraz (rób), ``False`` = już był (pomiń).

    Bez commitu — znacznik wchodzi razem z pracą, którą pilnuje.
    """

    statement = (
        insert(HrJobRun)
        .values(kind=kind, period_key=period_key, status=status)
        .on_conflict_do_nothing(constraint=_CONSTRAINT)
        .returning(HrJobRun.id)
    )
    return (await db.scalar(statement)) is not None
