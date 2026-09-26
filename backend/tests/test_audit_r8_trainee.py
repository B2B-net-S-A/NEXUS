"""Audyt 26.09.2026, runda 8 — praktykant (R8-N3-1…5, R8-X1-4).

- R8-N3-1: „Resync AAD” synchronizuje program praktykanta jak panel i SSO;
- R8-N3-2: tryby pracy z telefonu bez liczby dni nie zostawiają starej
  liczby dni w biurze, która im przeczy (bramki biura czytają tylko dni);
- R8-N3-3: norma „zaliczonych dni” nie liczy dzisiejszej listy w trakcie
  ani list bez pozycji;
- R8-N3-4: niewykonane oddzwonienie „później” wraca na kolejną listę;
- R8-N3-5: przedłużenie ponad limit bazy = 422, nie 500;
- R8-X1-4: konto wyłączone nie dostaje powiadomienia o decyzji ani
  statusu „Do decyzji” w panelu.
"""

from __future__ import annotations

import json
import os
import uuid
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException

from app.models.candidate import Candidate
from app.services import trainee_program
from app.services import trainee_rules as rules_mod

USER = SimpleNamespace(id=7)


# ── R8-N3-2: dni w biurze z trybów pracy ─────────────────────────────────


@pytest.mark.parametrize(
    ("modes", "previous", "expected"),
    [
        (["remote"], 2, 0),
        (["remote"], None, 0),
        (["onsite"], 0, 5),
        (["hybrid", "onsite"], 1, 5),
        (["remote", "hybrid"], 3, 3),
        (["hybrid"], 0, None),
        (["hybrid"], 5, None),
        (["hybrid"], None, None),
    ],
)
def test_onsite_days_follow_the_modes_from_the_call(modes, previous, expected):
    assert rules_mod.onsite_days_for_call_modes(modes, previous) == expected


def _candidate(**kw) -> Candidate:
    base = dict(
        expected_rate_hourly=Decimal("150.00"),
        expected_rate_currency="PLN",
        profile_rate_version=1,
        cv_extracted_data={},
        preferences={},
    )
    base.update(kw)
    return Candidate(**base)


def _facts(**kw) -> trainee_program.CallFacts:
    base = dict(b2b_willingness="b2b")
    base.update(kw)
    return trainee_program.CallFacts(**base)


def test_office_only_call_replaces_zero_office_days():
    """„Tylko zdalnie” z notatek (0 dni), a na telefonie „Biuro” — kandydat
    nie może zostać ukryty w rekrutacjach wymagających biura."""
    cand = _candidate(max_onsite_days_per_week=0)
    trainee_program._apply_facts(cand, _facts(remote_modes=("onsite",)), USER)
    assert cand.max_onsite_days_per_week == 5
    assert cand.preferences["remote_modes"] == ["onsite"]


def test_remote_only_call_clears_old_office_days():
    cand = _candidate(
        max_onsite_days_per_week=2, preferences={"remote_modes": ["remote", "hybrid"]}
    )
    trainee_program._apply_facts(cand, _facts(remote_modes=("remote",)), USER)
    assert cand.max_onsite_days_per_week == 0


def test_explicit_days_from_the_call_still_win():
    cand = _candidate(max_onsite_days_per_week=0)
    trainee_program._apply_facts(
        cand, _facts(remote_modes=("hybrid",), max_onsite_days=2), USER
    )
    assert cand.max_onsite_days_per_week == 2


def test_office_only_call_passes_the_office_gate():
    from app.services.dealbreaker_filters import DealbreakerInputs, apply_dealbreakers

    cand = _candidate(max_onsite_days_per_week=0)
    cand.id = 991_001
    trainee_program._apply_facts(cand, _facts(remote_modes=("onsite",)), USER)
    result = apply_dealbreakers(
        [cand], inputs=DealbreakerInputs(onsite_days_per_week=3)
    )
    assert [c.id for c in result.kept] == [cand.id]


# ── R8-N3-5: przedłużenie ponad limit ─────────────────────────────────────


@pytest.mark.asyncio
async def test_extension_over_the_database_limit_is_422(monkeypatch):
    program = SimpleNamespace(status="active", extended_days=200)
    monkeypatch.setattr(
        trainee_program, "_program_or_404", AsyncMock(return_value=program)
    )
    db = SimpleNamespace(scalar=AsyncMock(return_value=SimpleNamespace(id=5)))
    with pytest.raises(HTTPException) as exc:
        await trainee_program.decide(
            db,
            SimpleNamespace(id=1),
            5,
            action="extend",
            role=None,
            add_to_my_people=False,
            extend_days=60,
        )
    assert exc.value.status_code == 422
    assert "250" in exc.value.detail
    assert program.extended_days == 200


# ── R8-X1-4: konto wyłączone ──────────────────────────────────────────────


def _due_program():
    from app.core.scheduling import business_today

    today = business_today()
    # Start tak, by do końca zostało mniej niż 5 dni roboczych.
    start = today
    while (
        rules_mod.workdays_left(today, rules_mod.program_end_date(start, 40))
        >= trainee_program.DECISION_NOTICE_WORKDAYS
    ):
        start -= timedelta(days=1)
    program = SimpleNamespace(
        user_id=11,
        start_date=start,
        workdays=40,
        extended_days=0,
        total_workdays=40,
        daily_list_size=70,
        status="active",
        decision=None,
        decided_at=None,
        decision_notified_at=None,
    )
    return program, today


def test_panel_does_not_ask_for_a_decision_about_a_disabled_account():
    program, today = _due_program()
    assert trainee_program.program_view(program, today=today)["decision_due"]
    view = trainee_program._panel_program_view(
        SimpleNamespace(is_active=False), program, today=today
    )
    assert view["decision_due"] is False


@pytest.mark.asyncio
async def test_no_decision_notification_for_a_disabled_trainee(monkeypatch):
    import app.services.notification_triggers as triggers

    program, today = _due_program()

    def _rows(values):
        return SimpleNamespace(all=lambda: values)

    db = SimpleNamespace(
        scalars=AsyncMock(side_effect=[_rows([program]), _rows([1, 2])]),
        get=AsyncMock(return_value=SimpleNamespace(id=11, name="X", is_active=False)),
    )
    emit = AsyncMock()
    monkeypatch.setattr(triggers, "emit", emit)

    sent = await trainee_program.notify_due_decisions(db, today=today)

    assert sent == 0
    emit.assert_not_called()
    assert program.decision_notified_at is None


def test_callback_owed_until_a_followup_has_an_outcome():
    """`_pin_people` i `_scheduled_later` — ta sama reguła wykonania."""
    import inspect

    from app.services import trainee_call_list

    for source in (
        inspect.getsource(trainee_program._pin_people),
        inspect.getsource(trainee_call_list._scheduled_later),
    ):
        assert "followup.outcome.is_not(None)" in source
    assert "later_date <= today" in inspect.getsource(
        trainee_call_list._scheduled_later
    )


# ── Na bazie ──────────────────────────────────────────────────────────────

_DB_URL = os.environ.get("DATABASE_URL", "")
needs_db = pytest.mark.skipif(
    not _DB_URL or "@localhost/z" in _DB_URL or "@localhost:5432/x" in _DB_URL,
    reason="wymaga PostgreSQL",
)


async def _user(db, role: str, **kw):
    from app.models.user import User, UserRole

    marker = uuid.uuid4().hex[:10]
    user = User(
        email=f"r8-trainee-{marker}@example.com",
        name=f"R8 {marker}",
        role=UserRole(role),
        roles=[role],
        is_active=True,
        profile_completed=True,
        **kw,
    )
    db.add(user)
    await db.flush()
    return user


async def _cand(db):
    cand = Candidate(
        name="Tomasz",
        lastname=f"R8{uuid.uuid4().hex[:8]}",
        phone=f"+48 6{uuid.uuid4().int % 10**8:08d}",
    )
    db.add(cand)
    await db.flush()
    return cand


@needs_db
@pytest.mark.asyncio
async def test_days_norm_skips_todays_open_list_and_empty_lists() -> None:
    from app.core.database import AsyncSessionLocal
    from app.core.scheduling import business_today
    from app.models.trainee import TraineeCallItem, TraineeCallList

    today = business_today()
    closed = datetime.now(timezone.utc)
    async with AsyncSessionLocal() as db:
        trainee = await _user(db, "trainee")
        cand = await _cand(db)
        for offset in (3, 2, 1, 0):
            day = today - timedelta(days=offset)
            lst = TraineeCallList(user_id=trainee.id, list_date=day, size=1)
            db.add(lst)
            await db.flush()
            db.add(
                TraineeCallItem(
                    list_id=lst.id,
                    user_id=trainee.id,
                    candidate_id=cand.id,
                    list_date=day,
                    position=1,
                    reasons={},
                    outcome=None if offset == 0 else "call",
                    closed_at=None if offset == 0 else closed,
                )
            )
        # Lista bez pozycji (pula pusta) — nie z winy praktykanta.
        db.add(
            TraineeCallList(
                user_id=trainee.id, list_date=today - timedelta(days=4), size=0
            )
        )
        await db.flush()

        stats = await trainee_program._item_stats(db, [trainee.id], today)
        await db.rollback()

    entry = stats[trainee.id]
    assert entry["days_with_list"] == 3
    assert entry["days_completed"] == 3
    assert entry["calls_on_counted_days"] == 3


@needs_db
@pytest.mark.asyncio
async def test_missed_callback_returns_on_the_next_list() -> None:
    from sqlalchemy import select

    from app.core.database import AsyncSessionLocal
    from app.core.scheduling import business_today
    from app.models.trainee import TraineeCallItem, TraineeCallList, TraineeProgram
    from app.services import trainee_call_list as lists

    today = business_today()
    closed = datetime.now(timezone.utc) - timedelta(days=7)
    async with AsyncSessionLocal() as db:
        trainee = await _user(db, "trainee")
        db.add(
            TraineeProgram(
                user_id=trainee.id,
                start_date=today - timedelta(days=14),
                daily_list_size=5,
            )
        )
        missed = await _cand(db)
        done = await _cand(db)
        first = TraineeCallList(
            user_id=trainee.id, list_date=today - timedelta(days=7), size=2
        )
        callback_day = TraineeCallList(
            user_id=trainee.id, list_date=today - timedelta(days=1), size=2
        )
        db.add_all([first, callback_day])
        await db.flush()
        for pos, cand in enumerate((missed, done), start=1):
            db.add(
                TraineeCallItem(
                    list_id=first.id,
                    user_id=trainee.id,
                    candidate_id=cand.id,
                    list_date=first.list_date,
                    position=pos,
                    reasons={},
                    outcome="later",
                    closed_at=closed,
                    later_date=callback_day.list_date,
                )
            )
        # Dzień oddzwonienia: jedno niewykonane, drugie wykonane.
        db.add(
            TraineeCallItem(
                list_id=callback_day.id,
                user_id=trainee.id,
                candidate_id=missed.id,
                list_date=callback_day.list_date,
                position=1,
                reasons={"callback": True},
            )
        )
        db.add(
            TraineeCallItem(
                list_id=callback_day.id,
                user_id=trainee.id,
                candidate_id=done.id,
                list_date=callback_day.list_date,
                position=2,
                reasons={"callback": True},
                outcome="declined",
                closed_at=datetime.now(timezone.utc),
            )
        )
        await db.flush()
        programs = [
            p
            for p in await lists.active_programs(db, today=today)
            if p.user_id == trainee.id
        ]
        await lists.generate_lists(db, programs, today=today, ranked=[])
        rows = (
            await db.scalars(
                select(TraineeCallItem.candidate_id).where(
                    TraineeCallItem.user_id == trainee.id,
                    TraineeCallItem.list_date == today,
                )
            )
        ).all()
        await db.rollback()

    assert missed.id in rows
    assert done.id not in rows


async def _drop_users(*user_ids: int) -> None:
    """Konta z testów resync — bez aktywnych programów na wspólnej bazie."""
    from sqlalchemy import delete

    from app.core.database import AsyncSessionLocal
    from app.models.activity import Activity
    from app.models.user import User

    async with AsyncSessionLocal() as db:
        await db.execute(delete(Activity).where(Activity.user_id.in_(user_ids)))
        await db.execute(
            delete(Activity).where(
                Activity.entity_type == "user", Activity.entity_id.in_(user_ids)
            )
        )
        await db.execute(delete(User).where(User.id.in_(user_ids)))
        await db.commit()


def _admin_headers(admin_id: int) -> dict:
    from app.core.security import create_access_token

    return {"Authorization": f"Bearer {create_access_token(admin_id, 'admin')}"}


@needs_db
@pytest.mark.asyncio
async def test_aad_resync_promotion_closes_the_trainee_program(
    app_client, monkeypatch
) -> None:
    from app.core.config import settings
    from app.core.database import AsyncSessionLocal
    from app.core.scheduling import business_today
    from app.models.trainee import TraineeProgram

    group = f"grp-r8-{uuid.uuid4().hex[:8]}"
    async with AsyncSessionLocal() as db:
        admin = await _user(db, "admin")
        target = await _user(db, "trainee", aad_group_ids=[{"id": group}])
        db.add(TraineeProgram(user_id=target.id, start_date=business_today()))
        await db.commit()
        admin_id, target_id = admin.id, target.id

    monkeypatch.setattr(settings, "AAD_GROUP_RBAC_ENABLED", True)
    monkeypatch.setattr(
        settings, "AAD_GROUP_ROLE_MAP_JSON", json.dumps({group: "recruiter"})
    )
    resp = await app_client.post(
        f"/api/admin/users/{target_id}/resync-aad-groups",
        headers=_admin_headers(admin_id),
    )
    assert resp.status_code == 200, resp.text

    async with AsyncSessionLocal() as db:
        program = await trainee_program.program_for(db, target_id)
    await _drop_users(admin_id, target_id)
    assert program.status == "completed"
    assert program.decision == "promoted"
    assert program.decided_by_user_id == admin_id


@needs_db
@pytest.mark.asyncio
async def test_aad_resync_back_to_trainee_restarts_the_program(
    app_client, monkeypatch
) -> None:
    from app.core.config import settings
    from app.core.database import AsyncSessionLocal
    from app.models.trainee import TraineeProgram

    group = f"grp-r8-{uuid.uuid4().hex[:8]}"
    async with AsyncSessionLocal() as db:
        admin = await _user(db, "admin")
        target = await _user(db, "recruiter", aad_group_ids=[{"id": group}])
        db.add(
            TraineeProgram(
                user_id=target.id,
                start_date=date(2026, 1, 5),
                status="completed",
                decision="promoted",
                decided_at=datetime.now(timezone.utc),
            )
        )
        await db.commit()
        admin_id, target_id = admin.id, target.id

    monkeypatch.setattr(settings, "AAD_GROUP_RBAC_ENABLED", True)
    monkeypatch.setattr(
        settings, "AAD_GROUP_ROLE_MAP_JSON", json.dumps({group: "trainee"})
    )
    resp = await app_client.post(
        f"/api/admin/users/{target_id}/resync-aad-groups",
        headers=_admin_headers(admin_id),
    )
    assert resp.status_code == 200, resp.text

    async with AsyncSessionLocal() as db:
        program = await trainee_program.program_for(db, target_id)
    await _drop_users(admin_id, target_id)
    assert program.status == "active"
    assert program.decision is None
