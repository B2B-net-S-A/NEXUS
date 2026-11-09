"""Sprzątanie listy „Zadania” (``scripts/sales_cleanup.py``) i filtr sierot na trasie.

Baza testowa jest wspólna dla przebiegu, więc testy sprawdzają własne wiersze (po id),
a licznik do ``--expect-close`` biorą z biegu na sucho, tak jak operator.
"""

from __future__ import annotations

import dataclasses
import json
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

import pytest
from sqlalchemy import select

from app.core.database import AsyncSessionLocal
from app.models.sales import SalesActivity, SalesOpportunity, SalesOpportunityEvent
from scripts import sales_cleanup as cleanup
from tests.test_sales_companies_api import _headers, _user
from tests.test_sales_last_touch import _company, _opportunity, _touch

NOW = datetime(2026, 11, 9, 12, 0, tzinfo=timezone.utc)
CREATED = NOW - timedelta(days=400)
SYNCED = NOW - timedelta(days=11)
TASKS_URL = "/api/sales/activities/tasks"

#: Pozycje tego modułu; skrypt widzi tylko je, bo inne testy też zakładają wiersze importu.
_own: set[int] = set()


@pytest.fixture(autouse=True)
def only_own_items(monkeypatch):
    original = cleanup._closable
    _own.clear()
    monkeypatch.setattr(
        cleanup,
        "_closable",
        lambda assignee_id: [*original(assignee_id), SalesActivity.id.in_(set(_own))],
    )


async def _item(
    *,
    kind: str = "task",
    company_id: Optional[int] = None,
    opportunity_id: Optional[int] = None,
    assignee_user_id: Optional[int] = None,
    due_at: Optional[datetime] = CREATED,
    external_source: Optional[str] = "atlas",
    synced_at: Optional[datetime] = SYNCED,
    updated_at: datetime = SYNCED,
    created_at: datetime = CREATED,
    **fields: Any,
) -> int:
    async with AsyncSessionLocal() as db:
        activity = SalesActivity(
            kind=kind,
            company_id=company_id,
            opportunity_id=opportunity_id,
            assignee_user_id=assignee_user_id,
            due_at=due_at,
            external_source=external_source,
            synced_at=synced_at,
            updated_at=updated_at,
            created_at=created_at,
            **fields,
        )
        db.add(activity)
        await db.commit()
        _own.add(activity.id)
        return activity.id


async def _state(activity_id: int) -> tuple[Optional[datetime], datetime]:
    async with AsyncSessionLocal() as db:
        row = await db.get(SalesActivity, activity_id)
        assert row is not None
        return row.done_at, row.updated_at


async def _opportunity_row(opportunity_id: int) -> SalesOpportunity:
    async with AsyncSessionLocal() as db:
        row = await db.get(SalesOpportunity, opportunity_id)
        assert row is not None
        return row


async def _events(opportunity_id: int) -> list[SalesOpportunityEvent]:
    async with AsyncSessionLocal() as db:
        return list(
            (
                await db.execute(
                    select(SalesOpportunityEvent).where(
                        SalesOpportunityEvent.opportunity_id == opportunity_id
                    )
                )
            ).scalars()
        )


async def _apply(**options: Any) -> cleanup.Report:
    """Bieg na sucho, potem ``--apply`` z licznikiem, jak w instrukcji skryptu."""

    planned = await cleanup.run(cleanup.Options(**options), now=NOW)
    return await cleanup.run(
        cleanup.Options(apply=True, expect_close=planned.to_close, **options), now=NOW
    )


def test_cli_default_is_a_dry_run() -> None:
    assert cleanup._parse([]).apply is False


async def test_dry_run_writes_nothing() -> None:
    assignee = await _user()
    owner = await _user()
    opportunity_id, company_id = await _opportunity(owner_user_id=owner.id)
    item = await _item(company_id=company_id, assignee_user_id=assignee.id)
    target = await _user("sales_edit")
    admin = await _user(role="admin")
    before = await _state(item)

    report = await cleanup.run(
        cleanup.Options(
            assignee_id=assignee.id,
            former_owner_id=owner.id,
            transfer_to=target.id,
            actor_id=admin.id,
        ),
        now=NOW,
    )

    assert report.mode == "dry-run"
    assert report.to_close >= 1
    assert report.closed == 0
    assert report.transferred == 0
    assert opportunity_id in report.handover_opportunity_ids
    assert await _state(item) == before
    assert (await _opportunity_row(opportunity_id)).owner_user_id == owner.id
    assert await _events(opportunity_id) == []


async def test_dry_run_transaction_refuses_writes(monkeypatch) -> None:
    """Sucho to nie umowa w kodzie: sama baza odrzuca zapis w tej transakcji."""

    async def write_anyway(db, options, users, moment):
        await db.execute(
            cleanup.update(SalesActivity)
            .values(subject="x")
            .where(SalesActivity.id == 0)
        )

    monkeypatch.setattr(cleanup, "_build_report", write_anyway)
    with pytest.raises(Exception, match="read-only"):
        await cleanup.run(cleanup.Options(), now=NOW)


async def test_apply_closes_only_import_rows_of_the_account_and_unassigned() -> None:
    assignee = await _user()
    colleague = await _user()
    _, company_id = await _opportunity()
    of_account = await _item(company_id=company_id, assignee_user_id=assignee.id)
    planned_call = await _item(
        kind="call", company_id=company_id, assignee_user_id=assignee.id
    )
    unassigned = await _item(company_id=company_id)
    of_colleague = await _item(company_id=company_id, assignee_user_id=colleague.id)
    edited_in_nexus = await _item(
        company_id=company_id,
        assignee_user_id=assignee.id,
        updated_at=SYNCED + timedelta(days=1),
    )
    created_in_nexus = await _item(
        company_id=company_id,
        assignee_user_id=assignee.id,
        external_source=None,
        synced_at=None,
    )
    history_call = await _item(
        kind="call", company_id=company_id, assignee_user_id=assignee.id, due_at=None
    )

    report = await _apply(assignee_id=assignee.id, former_owner_id=colleague.id)

    assert report.closed == report.to_close
    for closed in (of_account, planned_call, unassigned):
        done_at, updated_at = await _state(closed)
        assert done_at == CREATED
        assert updated_at == NOW  # po ``synced_at``, więc ponowny import nie cofnie
    for untouched in (of_colleague, edited_in_nexus, created_in_nexus, history_call):
        done_at, _ = await _state(untouched)
        assert done_at is None


async def test_second_apply_closes_nothing() -> None:
    assignee = await _user()
    owner = await _user()
    _, company_id = await _opportunity()
    item = await _item(company_id=company_id, assignee_user_id=assignee.id)

    first = await _apply(assignee_id=assignee.id, former_owner_id=owner.id)
    after_first = await _state(item)
    later = NOW + timedelta(hours=1)
    planned = await cleanup.run(
        cleanup.Options(assignee_id=assignee.id, former_owner_id=owner.id), now=later
    )
    second = await cleanup.run(
        cleanup.Options(
            assignee_id=assignee.id,
            former_owner_id=owner.id,
            apply=True,
            expect_close=planned.to_close,
        ),
        now=later,
    )

    assert first.closed >= 1
    assert planned.to_close == 0
    assert second.closed == 0
    assert await _state(item) == after_first


@pytest.mark.parametrize("expect_close", [None, 987654])
async def test_apply_without_the_accepted_count_is_refused(
    expect_close: Optional[int],
) -> None:
    assignee = await _user()
    owner = await _user()
    _, company_id = await _opportunity()
    item = await _item(company_id=company_id, assignee_user_id=assignee.id)
    before = await _state(item)

    with pytest.raises(cleanup.Refused):
        await cleanup.run(
            cleanup.Options(
                assignee_id=assignee.id,
                former_owner_id=owner.id,
                apply=True,
                expect_close=expect_close,
            ),
            now=NOW,
        )

    assert await _state(item) == before


async def test_closing_does_not_wake_the_opportunity() -> None:
    assignee = await _user()
    owner = await _user()
    opportunity_id, company_id = await _opportunity(last_activity_at=CREATED)
    item = await _item(
        company_id=company_id,
        opportunity_id=opportunity_id,
        assignee_user_id=assignee.id,
        created_at=CREATED - timedelta(days=5),
    )
    later = NOW + timedelta(hours=1)  # zamknięcie „teraz” byłoby już w przeszłości
    before = await _touch(opportunity_id, later)

    await _apply(assignee_id=assignee.id, former_owner_id=owner.id)

    assert (await _state(item))[0] is not None
    assert await _touch(opportunity_id, later) == before
    assert (await _opportunity_row(opportunity_id)).last_activity_at == CREATED


async def test_apply_stops_when_a_touch_would_move() -> None:
    assignee = await _user()
    owner = await _user()
    _, company_id = await _opportunity()
    item = await _item(
        company_id=company_id,
        assignee_user_id=assignee.id,
        created_at=NOW - timedelta(days=10),
    )
    before = await _state(item)
    options = {"assignee_id": assignee.id, "former_owner_id": owner.id}

    planned = await cleanup.run(cleanup.Options(**options), now=NOW)
    assert planned.open_opportunities_with_moved_touch >= 1
    with pytest.raises(cleanup.TouchWouldMove):
        await cleanup.run(
            cleanup.Options(apply=True, expect_close=planned.to_close, **options),
            now=NOW,
        )

    assert await _state(item) == before


async def test_transfer_records_history_and_leaves_stage_and_archive() -> None:
    former = await _user()
    target = await _user("sales_edit")
    admin = await _user(role="admin")
    live, _ = await _opportunity(owner_user_id=former.id)
    archived, _ = await _opportunity(owner_user_id=former.id, archived_at=SYNCED)
    won, _ = await _opportunity(owner_user_id=former.id, status="won")
    before = await _opportunity_row(live)
    options = {
        "assignee_id": admin.id,
        "former_owner_id": former.id,
        "transfer_to": target.id,
        "actor_id": admin.id,
    }

    planned = await cleanup.run(cleanup.Options(**options), now=NOW)
    assert planned.handover_opportunity_ids == [live]
    report = await cleanup.run(
        cleanup.Options(
            apply=True,
            expect_close=planned.to_close,
            expect_transfer=1,
            **options,
        ),
        now=NOW,
    )

    assert report.transferred == 1
    after = await _opportunity_row(live)
    assert after.owner_user_id == target.id
    assert (
        after.stage_id,
        after.status,
        after.archived_at,
        after.last_activity_at,
    ) == (
        before.stage_id,
        before.status,
        before.archived_at,
        before.last_activity_at,
    )
    events = await _events(live)
    assert [(e.field, e.old_value, e.new_value, e.user_id) for e in events] == [
        ("owner_user_id", str(former.id), str(target.id), admin.id)
    ]
    assert (await _opportunity_row(archived)).owner_user_id == former.id
    assert (await _opportunity_row(won)).owner_user_id == former.id

    planned_again = await cleanup.run(cleanup.Options(**options), now=NOW)
    assert planned_again.handover_opportunity_ids == []


@pytest.mark.parametrize("problem", ["target_inactive", "target_no_edit", "not_admin"])
async def test_transfer_needs_active_seller_and_admin(problem: str) -> None:
    former = await _user()
    target = await _user(*([] if problem == "target_no_edit" else ["sales_edit"]))
    actor = await _user(role="recruiter" if problem == "not_admin" else "admin")
    if problem == "target_inactive":
        async with AsyncSessionLocal() as db:
            row = await db.get(type(target), target.id)
            row.is_active = False
            await db.commit()
    opportunity_id, _ = await _opportunity(owner_user_id=former.id)

    with pytest.raises(cleanup.Refused):
        await cleanup.run(
            cleanup.Options(
                assignee_id=actor.id,
                former_owner_id=former.id,
                transfer_to=target.id,
                actor_id=actor.id,
            ),
            now=NOW,
        )

    assert (await _opportunity_row(opportunity_id)).owner_user_id == former.id


async def test_report_has_only_numbers_and_ids() -> None:
    assignee = await _user()
    owner = await _user()
    _, company_id = await _opportunity(owner_user_id=owner.id, value=123456)
    await _item(
        company_id=company_id,
        assignee_user_id=assignee.id,
        subject="Temat z nazwiskiem",
    )

    report = await cleanup.run(
        cleanup.Options(assignee_id=assignee.id, former_owner_id=owner.id), now=NOW
    )
    text = json.dumps(dataclasses.asdict(report), ensure_ascii=False)

    for secret in ("Temat z nazwiskiem", assignee.name, owner.name, "123456"):
        assert secret not in text


async def test_task_list_hides_orphans_of_closed_opportunities(app_client) -> None:
    user = await _user("sales_view")
    live, company_id = await _opportunity()
    won, _ = await _opportunity(company_id, status="won")
    lost, _ = await _opportunity(company_id, status="lost")
    archived, _ = await _opportunity(company_id, archived_at=SYNCED)
    company_only = await _company()
    visible_live = await _item(
        company_id=company_id, opportunity_id=live, assignee_user_id=user.id
    )
    visible_company = await _item(company_id=company_only, assignee_user_id=user.id)
    hidden = [
        await _item(company_id=company_id, opportunity_id=opp, assignee_user_id=user.id)
        for opp in (won, lost, archived)
    ]
    done_orphan = await _item(
        company_id=company_id,
        opportunity_id=won,
        assignee_user_id=user.id,
        done_at=SYNCED,
    )

    for bucket in ("open", "overdue"):
        resp = await app_client.get(
            TASKS_URL, params={"bucket": bucket}, headers=_headers(user)
        )
        assert resp.status_code == 200
        body = resp.json()
        ids = {item["id"] for item in body["items"]}
        assert ids == {visible_live, visible_company}
        assert body["total"] == 2
        assert not ids & set(hidden)

    resp = await app_client.get(
        TASKS_URL, params={"bucket": "done"}, headers=_headers(user)
    )
    assert {item["id"] for item in resp.json()["items"]} == {done_orphan}
