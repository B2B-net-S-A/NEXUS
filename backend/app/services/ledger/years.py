"""Rok obrotowy i okresy księgi (K1).

* Rok = rok kalendarzowy (firma ma rok obrotowy równy kalendarzowemu) z 12
  okresami. Zakłada go osoba z listy „Księgowi” albo admin; tryb roku
  (``symfonia`` / ``parallel`` / ``nexus``) zmienia tylko admin — tryb
  ``nexus`` znaczy, że NEXUS jest księgą urzędową (decyzja po miesiącach
  równoległych, 13.11.2026).
* Okres zamyka osoba z listy „Księgowi”, gdy w buforze nie ma dokumentów z tego
  miesiąca. Zamknięty okres nie przyjmuje dokumentów ani zatwierdzeń. Otwiera
  go ponownie tylko admin, z powodem w śladzie.
* Zmiany stanu okresu i numeracja dziennika idą pod blokadą wiersza roku
  (``FOR UPDATE``) — zatwierdzenie i zamknięcie tego samego okresu nie mijają
  się w połowie.
"""

from __future__ import annotations

from calendar import monthrange
from datetime import date, datetime
from typing import Any, Optional

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.ledger import LedgerDocument, LedgerEvent, LedgerPeriod, LedgerYear
from app.services.finance_ledger.costs import LedgerError
from app.services.ledger import engine
from app.services.ledger_schema import REASON_MAX, YEAR_MODES

YEAR_MIN = 2020
YEAR_MAX = 2100


def _period_label(year: int, month: int) -> str:
    return f"{month:02d}.{year}"


async def ensure_year(
    db: AsyncSession, year: int, *, actor_id: Optional[int], mode: str = "symfonia"
) -> LedgerYear:
    """Rok z 12 okresami (bez commita); istniejący zostaje bez zmian."""

    if not YEAR_MIN <= year <= YEAR_MAX:
        raise LedgerError("Niepoprawny rok obrotowy.", status=422)
    if mode not in YEAR_MODES:
        raise LedgerError("Niepoprawny tryb roku.", status=422)
    row = await db.scalar(select(LedgerYear).where(LedgerYear.year == year))
    if row is not None:
        return row
    row = LedgerYear(
        year=year,
        starts_on=date(year, 1, 1),
        ends_on=date(year, 12, 31),
        mode=mode,
        status="open",
        next_journal_no=1,
        created_by=actor_id,
    )
    db.add(row)
    await db.flush()
    for month in range(1, 13):
        db.add(
            LedgerPeriod(
                year_id=row.id,
                month=month,
                starts_on=date(year, month, 1),
                ends_on=date(year, month, monthrange(year, month)[1]),
                status="open",
            )
        )
    await db.flush()
    return row


async def lock_year(db: AsyncSession, year_id: int) -> LedgerYear:
    row = await db.get(LedgerYear, year_id, with_for_update=True)
    if row is None:
        raise LedgerError("Nie ma takiego roku obrotowego.", status=404)
    return row


async def period_for(
    db: AsyncSession, day: date, *, require_open: bool = True
) -> tuple[LedgerYear, LedgerPeriod]:
    """Rok i okres daty operacji; brak roku albo zamknięty okres = 409."""

    year = await db.scalar(select(LedgerYear).where(LedgerYear.year == day.year))
    if year is None:
        raise LedgerError(
            f"Nie ma roku obrotowego {day.year} — załóż go w Ustawieniach Księgowości.",
            status=409,
        )
    period = await db.scalar(
        select(LedgerPeriod).where(
            LedgerPeriod.year_id == year.id, LedgerPeriod.month == day.month
        )
    )
    if period is None:  # pragma: no cover — rok zawsze ma 12 okresów
        raise LedgerError("Brak okresu w roku obrotowym.", status=409)
    if require_open and (year.status != "open" or period.status != "open"):
        raise LedgerError(
            f"Okres {_period_label(day.year, day.month)} jest zamknięty — "
            "dokumentów w nim nie dodaje się ani nie zatwierdza.",
            status=409,
        )
    return year, period


def period_payload(
    period: LedgerPeriod, *, drafts: int = 0, approved: int = 0
) -> dict[str, Any]:
    return {
        "id": period.id,
        "month": period.month,
        "starts_on": period.starts_on.isoformat(),
        "ends_on": period.ends_on.isoformat(),
        "status": period.status,
        "closed_at": period.closed_at.isoformat() if period.closed_at else None,
        "reopened_at": period.reopened_at.isoformat() if period.reopened_at else None,
        "reopen_reason": period.reopen_reason,
        "drafts": drafts,
        "approved": approved,
    }


async def list_years(db: AsyncSession) -> list[dict[str, Any]]:
    years = (
        await db.scalars(select(LedgerYear).order_by(LedgerYear.year.desc()))
    ).all()
    if not years:
        return []
    periods = (
        await db.scalars(
            select(LedgerPeriod)
            .where(LedgerPeriod.year_id.in_([y.id for y in years]))
            .order_by(LedgerPeriod.year_id, LedgerPeriod.month)
        )
    ).all()
    counts = {
        (period_id, status): count
        for period_id, status, count in (
            await db.execute(
                select(LedgerDocument.period_id, LedgerDocument.status, func.count())
                .where(LedgerDocument.year_id.in_([y.id for y in years]))
                .group_by(LedgerDocument.period_id, LedgerDocument.status)
            )
        ).all()
    }
    by_year: dict[int, list[dict[str, Any]]] = {}
    for period in periods:
        by_year.setdefault(period.year_id, []).append(
            period_payload(
                period,
                drafts=counts.get((period.id, "draft"), 0),
                approved=counts.get((period.id, "approved"), 0),
            )
        )
    return [
        {
            "id": year.id,
            "year": year.year,
            "mode": year.mode,
            "mode_label": engine.YEAR_MODE_LABELS[year.mode],
            "status": year.status,
            "journal_entries": year.next_journal_no - 1,
            "periods": by_year.get(year.id, []),
        }
        for year in years
    ]


async def _event(
    db: AsyncSession,
    action: str,
    *,
    actor_id: int,
    period_id: Optional[int] = None,
    detail: Optional[dict[str, Any]] = None,
) -> None:
    db.add(
        LedgerEvent(
            action=action, period_id=period_id, actor_id=actor_id, detail=detail or {}
        )
    )


async def close_period(
    db: AsyncSession, period_id: int, *, actor_id: int, now: datetime
) -> LedgerPeriod:
    """Zamknięcie okresu (bez commita): bufor z tego miesiąca musi być pusty."""

    period = await db.get(LedgerPeriod, period_id)
    if period is None:
        raise LedgerError("Nie ma takiego okresu.", status=404)
    year = await lock_year(db, period.year_id)
    period = await db.get(
        LedgerPeriod, period_id, with_for_update=True, populate_existing=True
    )
    assert period is not None
    if period.status == "closed":
        raise LedgerError("Ten okres jest już zamknięty.", status=409)
    drafts = await db.scalar(
        select(func.count())
        .select_from(LedgerDocument)
        .where(LedgerDocument.period_id == period.id, LedgerDocument.status == "draft")
    )
    if drafts:
        raise LedgerError(
            f"W buforze są dokumenty z tego miesiąca ({drafts}) — zatwierdź albo usuń "
            "je przed zamknięciem okresu.",
            status=409,
        )
    period.status = "closed"
    period.closed_by = actor_id
    period.closed_at = now
    await _event(
        db,
        "close",
        actor_id=actor_id,
        period_id=period.id,
        detail={"period": _period_label(year.year, period.month)},
    )
    await db.flush()
    return period


async def reopen_period(
    db: AsyncSession, period_id: int, reason: str, *, actor_id: int, now: datetime
) -> LedgerPeriod:
    """Ponowne otwarcie (bez commita, tylko admin — bramka w trasie)."""

    reason = " ".join((reason or "").split())
    if len(reason) < 3:
        raise LedgerError("Podaj powód ponownego otwarcia okresu.", status=422)
    period = await db.get(LedgerPeriod, period_id)
    if period is None:
        raise LedgerError("Nie ma takiego okresu.", status=404)
    year = await lock_year(db, period.year_id)
    period = await db.get(
        LedgerPeriod, period_id, with_for_update=True, populate_existing=True
    )
    assert period is not None
    if period.status != "closed":
        raise LedgerError("Ten okres jest otwarty.", status=409)
    if year.status != "open":
        raise LedgerError("Rok obrotowy jest zamknięty.", status=409)
    period.status = "open"
    period.reopened_by = actor_id
    period.reopened_at = now
    period.reopen_reason = reason[:REASON_MAX]
    await _event(
        db,
        "reopen",
        actor_id=actor_id,
        period_id=period.id,
        detail={
            "period": _period_label(year.year, period.month),
            "reason": reason[:REASON_MAX],
        },
    )
    await db.flush()
    return period


async def set_mode(
    db: AsyncSession, year_id: int, mode: str, *, actor_id: int
) -> LedgerYear:
    """Tryb roku (bez commita, tylko admin — bramka w trasie)."""

    if mode not in YEAR_MODES:
        raise LedgerError("Niepoprawny tryb roku.", status=422)
    year = await lock_year(db, year_id)
    if year.mode == mode:
        return year
    previous = year.mode
    year.mode = mode
    await _event(
        db,
        "mode",
        actor_id=actor_id,
        detail={"year": year.year, "from": previous, "to": mode},
    )
    await db.flush()
    return year
