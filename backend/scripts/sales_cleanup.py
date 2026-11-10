#!/usr/bin/env python3
"""Jednorazowe sprzątanie listy „Zadania” po imporcie z Atlasa.

Domyślnie NA SUCHO: transakcja ``READ ONLY``, raport, wycofanie. ``--apply`` zapisuje
w jednej transakcji i tylko z licznikiem zaakceptowanym przez Artura (``--expect-close``),
więc dane, które zmieniły się od akceptacji, kończą bieg bez zapisu. Drugi bieg nie
ma już czego zamknąć.

Co robi:

1. zamyka otwarte pozycje z importu przypisane do wskazanego konta (domyślnie 30)
   oraz bez przypisania; pozycja zmieniona w NEXUSIE po imporcie zostaje;
2. pokazuje otwarte szanse po opiekunie, który odszedł (domyślnie konto 159), a z
   ``--transfer-to`` i ``--actor-id`` przekazuje je, zapisując historię zmian;
   otwarte zadania byłego opiekuna przy tych szansach idą razem z nimi
   (``owner_tasks.hand_over``), a raport podaje ich liczbę;
   ``--pipeline-key`` zawęża obie rzeczy do jednego lejka (np. ``atlas-it-factories``),
   gdy szanse z różnych lejków przejmują różne osoby.

Nie rusza etapu, statusu ani archiwum szans. Sieroty po zamkniętych szansach znikają
z listy dzięki filtrowi trasy (``task_scope.not_orphaned``), tu zamykane są tylko te
z pkt 1.

Data zamknięcia to ``created_at`` pozycji, nie „teraz”, bo zrobione zadanie jest
dotykiem szansy i jej firmy (``touch.py``): sprzątanie obudziłoby szanse, przy których
nikt nie pracował, i przesłoniło automat archiwizacji. Z tego samego powodu bieg nie
zmienia ``last_activity_at``. Gdyby mimo to dotyk którejś otwartej szansy się przesunął,
``--apply`` kończy się kodem 3 bez zapisu.

Uruchomienie (z ``backend/``, baza z ``DATABASE_URL``)::

    python -m scripts.sales_cleanup
    python -m scripts.sales_cleanup --apply --expect-close 106

Raport to same liczby i identyfikatory, bez nazw i kwot: repo i logi Actions są publiczne.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from collections import Counter
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Optional, Sequence

from sqlalchemy import case, distinct, func, or_, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import AsyncSessionLocal
from app.models.sales import SalesActivity, SalesOpportunity, SalesPipeline
from app.models.user import User, UserRole
from app.services.action_permissions import ProductAction, has_permission
from app.services.effective_access import resolve_effective_access
from app.services.sales import history, owner_tasks
from app.services.sales.task_scope import live_opportunity, not_orphaned, task_items
from app.services.sales.touch import last_touch_at

DEFAULT_ASSIGNEE_ID = 30
DEFAULT_FORMER_OWNER_ID = 159

EXIT_OK = 0
EXIT_ERROR = 1
EXIT_REFUSED = 2
EXIT_TOUCH_MOVED = 3


class Refused(Exception):
    """Warunek biegu niespełniony; nic nie zostało zapisane."""


@dataclass(frozen=True)
class Options:
    assignee_id: int = DEFAULT_ASSIGNEE_ID
    former_owner_id: int = DEFAULT_FORMER_OWNER_ID
    apply: bool = False
    expect_close: Optional[int] = None
    transfer_to: Optional[int] = None
    actor_id: Optional[int] = None
    expect_transfer: Optional[int] = None
    pipeline_key: Optional[str] = None


@dataclass
class Report:
    mode: str = "dry-run"
    list_open_before: int = 0
    list_orphans_hidden_by_filter: int = 0
    to_close: int = 0
    to_close_by_group: dict[str, int] = field(default_factory=dict)
    to_close_by_opportunity_state: dict[str, int] = field(default_factory=dict)
    to_close_by_kind: dict[str, int] = field(default_factory=dict)
    list_open_after: int = 0
    closed: int = 0
    open_opportunities_with_moved_touch: int = 0
    assignee_active: bool = False
    assignee_sales_view: bool = False
    former_owner_active: bool = False
    handover_opportunity_ids: list[int] = field(default_factory=list)
    handover_open_tasks: int = 0
    transferred: int = 0
    transferred_tasks: int = 0


class TouchWouldMove(Exception):
    """Zamknięcie przesunęłoby dotyk otwartej szansy; nic nie zostało zapisane."""

    def __init__(self, report: Report) -> None:
        super().__init__("touch would move")
        self.report = report


def _closable(assignee_id: int) -> list:
    """Otwarta pozycja z importu, nieruszana w NEXUSIE, konta albo bez przypisania."""

    return [
        task_items(),
        SalesActivity.done_at.is_(None),
        or_(
            SalesActivity.assignee_user_id == assignee_id,
            SalesActivity.assignee_user_id.is_(None),
        ),
        SalesActivity.external_source.is_not(None),
        SalesActivity.synced_at.is_not(None),
        SalesActivity.updated_at <= SalesActivity.synced_at,
    ]


def _opportunity_state():
    return case(
        (SalesActivity.opportunity_id.is_(None), "bez_szansy"),
        (SalesOpportunity.archived_at.is_not(None), "archiwum"),
        (SalesOpportunity.status != "open", "zamknieta"),
        else_="otwarta",
    )


def _touch_after_closing():
    """Dotyk, którym stanie się pozycja po zamknięciu datą ``created_at``."""

    return case(
        (
            SalesActivity.kind == "call",
            func.coalesce(SalesActivity.occurred_at, SalesActivity.created_at),
        ),
        else_=SalesActivity.created_at,
    )


async def _moved_touches(
    db: AsyncSession, activity_ids: Sequence[int], now: datetime
) -> int:
    """Ile otwartych szans miałoby późniejszy dotyk po zamknięciu tych pozycji."""

    if not activity_ids:
        return 0
    moved = _touch_after_closing()
    return int(
        await db.scalar(
            select(func.count(distinct(SalesOpportunity.id)))
            .join(
                SalesActivity,
                or_(
                    SalesActivity.opportunity_id == SalesOpportunity.id,
                    SalesActivity.company_id == SalesOpportunity.company_id,
                ),
            )
            .where(
                SalesActivity.id.in_(activity_ids),
                live_opportunity(),
                moved < now,
                moved > last_touch_at(now),
            )
        )
        or 0
    )


async def _users(db: AsyncSession, ids: set[int]) -> dict[int, User]:
    users = list((await db.execute(select(User).where(User.id.in_(ids)))).scalars())
    await resolve_effective_access(db, users)
    return {user.id: user for user in users}


def _check_transfer(options: Options, users: dict[int, User]) -> None:
    if options.actor_id is None:
        raise Refused("--transfer-to wymaga --actor-id")
    target = users.get(int(options.transfer_to))  # type: ignore[arg-type]
    if target is None or not target.is_active:
        raise Refused("--transfer-to: konto nie istnieje albo jest nieaktywne")
    if not has_permission(target, ProductAction.sales_edit):
        raise Refused("--transfer-to: konto bez uprawnienia „Sprzedaż: edycja”")
    actor = users.get(options.actor_id)
    if actor is None or not actor.is_active or not actor.has_role(UserRole.admin):
        raise Refused("--actor-id: potrzebne aktywne konto administratora")


def _check_counters(options: Options, report: Report) -> None:
    if options.expect_close is None:
        raise Refused("--apply wymaga --expect-close z liczbą z biegu na sucho")
    if options.expect_close != report.to_close:
        raise Refused(
            f"--expect-close {options.expect_close}, a jest {report.to_close}"
        )
    if options.transfer_to is None:
        return
    if options.expect_transfer != len(report.handover_opportunity_ids):
        raise Refused(
            f"--expect-transfer {options.expect_transfer}, "
            f"a jest {len(report.handover_opportunity_ids)}"
        )


async def _handover_scope(db: AsyncSession, options: Options) -> list:
    """Otwarte szanse byłego opiekuna; z ``--pipeline-key`` tylko w tym lejku."""

    scope = [
        SalesOpportunity.owner_user_id == options.former_owner_id,
        live_opportunity(),
    ]
    if options.pipeline_key is None:
        return scope
    pipeline_id = await db.scalar(
        select(SalesPipeline.id).where(SalesPipeline.key == options.pipeline_key)
    )
    if pipeline_id is None:
        raise Refused("--pipeline-key: nie ma lejka o takim kluczu")
    return [*scope, SalesOpportunity.pipeline_id == pipeline_id]


async def _handover_open_tasks(
    db: AsyncSession,
    opportunity_ids: Sequence[int],
    closing: Sequence[int],
    former_owner_id: int,
) -> int:
    """Otwarte zadania byłego opiekuna, które pójdą za szansami; bez zamykanych w pkt 1."""

    if not opportunity_ids:
        return 0
    return int(
        await db.scalar(
            select(func.count())
            .select_from(SalesActivity)
            .where(
                SalesActivity.opportunity_id.in_(opportunity_ids),
                owner_tasks.open_items_of(former_owner_id),
                SalesActivity.id.not_in(closing),
            )
        )
        or 0
    )


async def _build_report(
    db: AsyncSession, options: Options, users: dict[int, User], now: datetime
) -> tuple[Report, list[int]]:
    listed = (
        select(SalesActivity.id)
        .outerjoin(
            SalesOpportunity, SalesOpportunity.id == SalesActivity.opportunity_id
        )
        .where(task_items(), SalesActivity.done_at.is_(None))
    )
    list_open = int(
        await db.scalar(select(func.count()).select_from(listed.subquery())) or 0
    )
    visible = listed.where(not_orphaned())
    list_visible = int(
        await db.scalar(select(func.count()).select_from(visible.subquery())) or 0
    )
    rows = (
        await db.execute(
            select(
                SalesActivity.id,
                SalesActivity.kind,
                SalesActivity.assignee_user_id,
                _opportunity_state().label("state"),
            )
            .outerjoin(
                SalesOpportunity, SalesOpportunity.id == SalesActivity.opportunity_id
            )
            .where(*_closable(options.assignee_id))
            .order_by(SalesActivity.id)
        )
    ).all()
    closing = [row.id for row in rows]
    closing_visible = sum(1 for row in rows if row.state in {"bez_szansy", "otwarta"})
    handover = list(
        (
            await db.execute(
                select(SalesOpportunity.id)
                .where(*await _handover_scope(db, options))
                .order_by(SalesOpportunity.id)
            )
        ).scalars()
    )
    assignee = users.get(options.assignee_id)
    former_owner = users.get(options.former_owner_id)
    return (
        Report(
            mode="apply" if options.apply else "dry-run",
            list_open_before=list_open,
            list_orphans_hidden_by_filter=list_open - list_visible,
            to_close=len(closing),
            to_close_by_group=dict(
                Counter(
                    "konto" if row.assignee_user_id is not None else "bez_przypisania"
                    for row in rows
                )
            ),
            to_close_by_opportunity_state=dict(Counter(row.state for row in rows)),
            to_close_by_kind=dict(Counter(row.kind for row in rows)),
            list_open_after=list_visible - closing_visible,
            open_opportunities_with_moved_touch=await _moved_touches(db, closing, now),
            assignee_active=bool(assignee and assignee.is_active),
            assignee_sales_view=bool(
                assignee and has_permission(assignee, ProductAction.sales_view)
            ),
            former_owner_active=bool(former_owner and former_owner.is_active),
            handover_opportunity_ids=handover,
            handover_open_tasks=await _handover_open_tasks(
                db, handover, closing, options.former_owner_id
            ),
        ),
        closing,
    )


async def _close(db: AsyncSession, activity_ids: Sequence[int], now: datetime) -> int:
    if not activity_ids:
        return 0
    done = await db.execute(
        update(SalesActivity)
        .where(SalesActivity.id.in_(activity_ids), SalesActivity.done_at.is_(None))
        .values(done_at=SalesActivity.created_at, updated_at=now)
        .execution_options(synchronize_session=False)
    )
    return int(done.rowcount or 0)


async def _transfer(db: AsyncSession, options: Options) -> tuple[int, int]:
    """Przekaż szanse; zwraca liczbę szans i liczbę zadań, które poszły za nimi."""

    opportunities = list(
        (
            await db.execute(
                select(SalesOpportunity)
                .where(*await _handover_scope(db, options))
                .with_for_update()
            )
        ).scalars()
    )
    tasks = 0
    for opportunity in opportunities:
        before = history.snapshot(opportunity)
        opportunity.owner_user_id = options.transfer_to
        history.record_changes(db, opportunity, before, user_id=options.actor_id)
        tasks += await owner_tasks.hand_over(
            db,
            opportunity.id,
            previous_owner_id=options.former_owner_id,
            new_owner_id=options.transfer_to,
        )
    return len(opportunities), tasks


async def run(options: Options, now: Optional[datetime] = None) -> Report:
    moment = now or datetime.now(timezone.utc)
    async with AsyncSessionLocal() as db:
        if not options.apply:
            await db.execute(text("SET TRANSACTION READ ONLY"))
        ids = {options.assignee_id, options.former_owner_id}
        ids |= {i for i in (options.transfer_to, options.actor_id) if i is not None}
        users = await _users(db, ids)
        report, closing = await _build_report(db, options, users, moment)
        if options.transfer_to is not None:
            _check_transfer(options, users)
        if not options.apply:
            await db.rollback()
            return report
        _check_counters(options, report)
        if report.open_opportunities_with_moved_touch:
            raise TouchWouldMove(report)
        report.closed = await _close(db, closing, moment)
        if options.transfer_to is not None:
            report.transferred, report.transferred_tasks = await _transfer(db, options)
        await db.commit()
        return report


def _parse(argv: Sequence[str]) -> Options:
    parser = argparse.ArgumentParser(description="Sprzątanie listy Zadania po imporcie")
    parser.add_argument("--assignee-id", type=int, default=DEFAULT_ASSIGNEE_ID)
    parser.add_argument("--former-owner-id", type=int, default=DEFAULT_FORMER_OWNER_ID)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--expect-close", type=int)
    parser.add_argument("--transfer-to", type=int)
    parser.add_argument("--actor-id", type=int)
    parser.add_argument("--expect-transfer", type=int)
    parser.add_argument("--pipeline-key")
    args = parser.parse_args(argv)
    return Options(**vars(args))


def main(argv: Optional[Sequence[str]] = None) -> int:
    options = _parse(sys.argv[1:] if argv is None else argv)
    try:
        report = asyncio.run(run(options))
    except Refused as exc:
        print(f"Odmowa, nic nie zapisano: {exc}", file=sys.stderr)
        return EXIT_REFUSED
    except TouchWouldMove as exc:
        print(json.dumps(asdict(exc.report), ensure_ascii=False, indent=2))
        print(
            "Odmowa, nic nie zapisano: dotyk szansy by się przesunął", file=sys.stderr
        )
        return EXIT_TOUCH_MOVED
    except Exception as exc:  # log może być publiczny, więc bez treści wyjątku
        print(f"Błąd: {type(exc).__name__}", file=sys.stderr)
        return EXIT_ERROR
    print(json.dumps(asdict(report), ensure_ascii=False, indent=2))
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
