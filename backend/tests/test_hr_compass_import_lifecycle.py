"""Import spraw wejścia i odejścia z Compassa — bez przekazania pracy i wyłączania kont.

Pętla ``lifecycle_jobs`` przekazuje pracę i wyłącza konta tylko w sprawach
``active``. Import zakłada sprawy ``done``, ``cancelled`` albo ``draft``;
test woła pętlę z podmienionym wykonaniem i sprawdza, że żadna zaimportowana
sprawa do niej nie trafia. Paczki fikcyjne, rollback na końcu.

Pętla sama robi ``commit``/``rollback`` per sprawa i widzi żywe sprawy odejścia
innych testów (wspólna baza). Dlatego test biegnie w transakcji zewnętrznej
z sesją na punktach zapisu: ``rollback`` pętli przy cudzej sprawie cofa tylko
jej punkt zapisu, a nie zaimportowane dane testu, i nic nie zostaje w bazie.
"""

from __future__ import annotations

import uuid
from contextlib import asynccontextmanager
from datetime import date, datetime
from typing import AsyncIterator
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import AsyncSessionLocal, engine
from app.models.hr_lifecycle import LifecycleCase, LifecycleTask
from app.models.user import User
from app.services.hr import compass_import, lifecycle_jobs
from app.services.hr.compass_import import lifecycle as lifecycle_import
from tests.test_hr_compass_import_leave import (
    assert_report_clean,
    make_bundle,
    make_person,
    run_import,
)


@asynccontextmanager
async def _isolated_session() -> AsyncIterator[AsyncSession]:
    """Sesja w transakcji zewnętrznej; jej commit i rollback to punkty zapisu."""

    async with engine.connect() as conn:
        outer = await conn.begin()
        db = AsyncSessionLocal(bind=conn, join_transaction_mode="create_savepoint")
        try:
            yield db
        finally:
            await db.close()
            await outer.rollback()


def _exit(person, **values) -> dict:
    return {
        "id": str(uuid.uuid4()),
        "user_id": person,
        "is_anonymous": False,
        "role_snapshot": "internal",
        "manager_snapshot": None,
        "exit_reason": None,
        "exit_reason_detail": None,
        "status": "scheduled",
        "cancelled_at": None,
        "cancelled_by": None,
        "created_at": "2026-09-01T08:00:00+00:00",
        "updated_at": "2026-09-30T16:00:00+00:00",
        **values,
    }


def _offboarding_task(person, title: str, **values) -> dict:
    return {
        "id": str(uuid.uuid4()),
        "user_id": person,
        "category": "equipment_return",
        "title": title,
        "responsible_role": "manager",
        "due_date": "2026-09-30",
        "completed_at": None,
        "completed_by": None,
        "notes": None,
        "position": 0,
        **values,
    }


@pytest.mark.asyncio
async def test_lifecycle_import_never_reaches_handover_or_deactivation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tag = uuid.uuid4().hex[:8]
    async with _isolated_session() as db:
        exited, x_id, x_row = await make_person(
            db,
            f"{tag}-exited",
            employment_status="exited",
            last_working_day=date(2026, 9, 30),
        )
        leaving, y_id, y_row = await make_person(
            db,
            f"{tag}-leaving",
            employment_status="offboarding",
            last_working_day=date(2026, 10, 1),
        )
        boss, b_id, b_row = await make_person(db, f"{tag}-boss")
        cancelled_person, z_id, z_row = await make_person(
            db, f"{tag}-stays", last_working_day=date(2026, 8, 31)
        )
        _, w_id, w_row = await make_person(
            db, f"{tag}-nodate", employment_status="offboarding"
        )
        live, l_id, l_row = await make_person(
            db,
            f"{tag}-live",
            employment_status="offboarding",
            last_working_day=date(2026, 11, 30),
        )
        newcomer, o_id, o_row = await make_person(db, f"{tag}-new")
        o_row["work_start_date"] = "2026-05-18"
        _, n_id, n_row = await make_person(db, f"{tag}-none", with_profile=False)

        native = LifecycleCase(
            user_id=live.id,
            kind="offboarding",
            status="draft",
            last_working_day=date(2026, 11, 30),
        )
        db.add(native)
        await db.flush()

        done_exit = _exit(
            x_id,
            manager_snapshot=b_id,
            exit_reason="personal",
            exit_reason_detail="Powód opisany wolnym tekstem",
        )
        open_exit = _exit(y_id, manager_snapshot=b_id)
        cancelled_mirror = {
            "id": str(uuid.uuid4()),
            "person_type": "employee",
            "person_id": z_id,
            "status": "cancelled",
            "cancelled_at": "2026-08-20T08:00:00+00:00",
            "cancelled_by": b_id,
            "created_at": "2026-08-01T08:00:00+00:00",
        }
        contractor_exit = {
            "id": str(uuid.uuid4()),
            "person_type": "contractor",
            "person_id": str(uuid.uuid4()),
            "status": "scheduled",
        }
        anonymous = _exit(None, is_anonymous=True, status="submitted")
        no_profile = _exit(n_id)
        no_date = _exit(w_id)
        live_clash = _exit(l_id)
        onboarding = {
            "id": str(uuid.uuid4()),
            "user_id": o_id,
            "template_id": str(uuid.uuid4()),
            "started_at": "2026-05-18T08:00:00+00:00",
            "completed_at": "2026-06-30T08:00:00+00:00",
            "cancelled_at": None,
            "created_at": "2026-05-15T08:00:00+00:00",
        }
        tasks = [
            _offboarding_task(x_id, "Zwrot laptopa"),
            _offboarding_task(x_id, "Wyłączenie kont", category="access_revoke"),
            _offboarding_task(
                y_id,
                "Rozliczenie",
                category="final_settlement",
                responsible_role="finanse",
                completed_at="2026-09-29T10:00:00+00:00",
                completed_by=b_id,
            ),
            _offboarding_task(
                y_id, "Przekazanie wiedzy", category="knowledge_transfer"
            ),
        ]
        onboarding_tasks = [
            {
                "id": str(uuid.uuid4()),
                "progress_id": onboarding["id"],
                "title": "Spotkanie z opiekunem",
                "category": "meeting",
                "responsible_role": "buddy",
                "due_date": "2026-05-19",
                "completed_at": "2026-05-19T10:00:00+00:00",
                "completed_by": o_id,
                "notes": None,
                "position": 0,
            }
        ]
        bundle = make_bundle(
            {
                "profiles": [
                    x_row,
                    y_row,
                    b_row,
                    z_row,
                    w_row,
                    l_row,
                    o_row,
                    n_row,
                ],
                "exit_interviews": [
                    done_exit,
                    open_exit,
                    anonymous,
                    no_profile,
                    no_date,
                    live_clash,
                ],
                "exit_cases": [cancelled_mirror, contractor_exit],
                "offboarding_tasks": tasks,
                "onboarding_progress": [onboarding],
                "onboarding_tasks": onboarding_tasks,
            }
        )
        importer = compass_import.IMPORTERS["lifecycle"]

        batch, report, written = await run_import(db, "lifecycle", bundle)
        assert report["counts"] == {"create": 4, "skip": 4, "conflict": 1}
        reasons = report["reasons"]
        assert reasons["odejście bez ostatniego dnia pracy"] == 1
        assert reasons["sprawa kontraktora — poza kartoteką pracowników"] == 1
        assert reasons["anonimowa ankieta — bez osoby"] == 1
        assert reasons["osoba bez kartoteki w NEXUSIE"] == 1
        assert reasons["sprawa tej osoby w toku jest już w NEXUSIE"] == 1
        assert reasons[lifecycle_import.DRAFT_NOTE] == 1
        assert_report_clean(batch.report, "Powód opisany wolnym tekstem", "laptopa")
        assert written == {
            "cases_created": 4,
            "cases_updated": 0,
            "tasks_written": 5,
        }

        cases = {
            case.user_id: case
            for case in await db.scalars(
                select(LifecycleCase).where(
                    LifecycleCase.user_id.in_(
                        [exited.id, leaving.id, cancelled_person.id, newcomer.id]
                    )
                )
            )
        }
        done = cases[exited.id]
        assert (done.kind, done.status) == ("offboarding", "done")
        assert done.last_working_day == date(2026, 9, 30)
        assert done.exit_reason == "other"
        assert done.exit_note is None
        assert done.manager_user_id == boss.id
        assert done.handover_executed_at is None
        assert done.account_closed_at is None
        done_tasks = list(
            await db.scalars(
                select(LifecycleTask).where(LifecycleTask.case_id == done.id)
            )
        )
        assert {t.status for t in done_tasks} == {"skipped"}
        assert all(t.done_at is not None for t in done_tasks)

        draft = cases[leaving.id]
        assert draft.status == "draft"
        assert draft.deactivate_on is None
        draft_tasks = {
            t.title: t
            for t in await db.scalars(
                select(LifecycleTask).where(LifecycleTask.case_id == draft.id)
            )
        }
        assert draft_tasks["Rozliczenie"].status == "done"
        assert draft_tasks["Rozliczenie"].assignee_kind == "people_admin"
        assert draft_tasks["Rozliczenie"].done_by == boss.id
        assert draft_tasks["Przekazanie wiedzy"].status == "open"
        assert draft_tasks["Przekazanie wiedzy"].assignee_user_id == boss.id

        assert cases[cancelled_person.id].status == "cancelled"
        assert cases[cancelled_person.id].cancelled_by == boss.id
        joined = cases[newcomer.id]
        assert (joined.kind, joined.status) == ("onboarding", "done")
        assert joined.start_date == date(2026, 5, 18)
        buddy_task = await db.scalar(
            select(LifecycleTask).where(LifecycleTask.case_id == joined.id)
        )
        assert buddy_task.assignee_kind == "manager"
        assert buddy_task.status == "done"

        # Drugi zapis tej samej paczki: bez zmian.
        batch2, _ = await compass_import.dry_run(
            db,
            module="lifecycle",
            bundle=bundle,
            planner=importer.plan,
            actor_user_id=None,
        )
        assert batch2.report["dry_run"]["counts"] == {
            "unchanged": 4,
            "skip": 4,
            "conflict": 1,
        }
        written2 = await compass_import.apply(
            db,
            batch=batch2,
            bundle=bundle,
            planner=importer.plan,
            applier=importer.apply,
            actor_user_id=None,
        )
        assert written2 == {
            "cases_created": 0,
            "cases_updated": 0,
            "tasks_written": 0,
        }

        # Pętla: żadna zaimportowana sprawa nie trafia do przekazania pracy
        # ani do wyłączenia konta — nawet gdy ostatni dzień dawno minął.
        # Zapis do transakcji zewnętrznej: rollback pętli przy cudzej
        # sprawie nie cofa danych testu.
        await db.commit()
        ours = {case.id for case in cases.values()}
        # Rollback pętli wygasza obiekty sesji — dalej tylko identyfikatory.
        imported_people = [exited.id, leaving.id]
        far = datetime(2027, 3, 1, 20, 0, tzinfo=ZoneInfo("Europe/Warsaw"))
        assert ours.isdisjoint(
            await lifecycle_jobs.due_deactivation_ids(db, far.date())
        )
        touched: list[int] = []

        async def refuse_handover(_db, case, *, now):
            touched.append(case.id)
            raise RuntimeError("import nie może uruchomić przekazania pracy")

        async def refuse_close(_db, case, *, now):
            touched.append(case.id)
            raise RuntimeError("import nie może wyłączyć konta")

        monkeypatch.setattr(lifecycle_jobs, "execute_handover", refuse_handover)
        monkeypatch.setattr(lifecycle_jobs, "close_account", refuse_close)
        await lifecycle_jobs.run_handovers(db, far)
        await lifecycle_jobs.run_deactivations(db, far)
        assert ours.isdisjoint(touched)
        active = await db.scalars(
            select(User.is_active).where(User.id.in_(imported_people))
        )
        assert list(active) == [True, True]


@pytest.mark.asyncio
async def test_lifecycle_dry_run_writes_nothing() -> None:
    tag = uuid.uuid4().hex[:8]
    async with AsyncSessionLocal() as db:
        try:
            person, x_id, x_row = await make_person(
                db,
                f"{tag}-exited",
                employment_status="exited",
                last_working_day=date(2026, 9, 30),
            )
            bundle = make_bundle(
                {"profiles": [x_row], "exit_interviews": [_exit(x_id)]}
            )
            importer = compass_import.IMPORTERS["lifecycle"]
            _, plan = await compass_import.dry_run(
                db,
                module="lifecycle",
                bundle=bundle,
                planner=importer.plan,
                actor_user_id=None,
            )
            assert plan.counts() == {"create": 1}
            assert (
                await db.scalar(
                    select(LifecycleCase.id).where(LifecycleCase.user_id == person.id)
                )
                is None
            )
        finally:
            await db.rollback()
