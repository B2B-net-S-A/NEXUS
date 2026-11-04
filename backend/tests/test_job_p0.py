"""P0 — ultrapilne przez 24 h (decyzje Artura 27.10.2026): reguły bez bazy."""

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from app.models.job import JobStatus
from app.models.user import UserRole
from app.services import job_p0
from app.services import notification_delivery as delivery

NOW = datetime(2026, 10, 27, 9, 9, tzinfo=timezone.utc)  # wtorek 10:09 w Warszawie


def _job(**kw):
    base = dict(
        id=789160,
        status=JobStatus.published,
        p0_until=NOW + timedelta(hours=23),
        p0_reason="Orlen chce 2 CV do jutra",
        p0_set_at=NOW - timedelta(hours=1),
        p0_set_by=11,
    )
    base.update(kw)
    return SimpleNamespace(**base)


def _user(*roles):
    return SimpleNamespace(has_any_role=lambda *wanted: any(r in roles for r in wanted))


def test_twenty_four_and_forty_eight_hours_from_now():
    assert job_p0.until_for("24h", NOW) == NOW + timedelta(hours=24)
    assert job_p0.until_for("48h", NOW) == NOW + timedelta(hours=48)


def test_friday_means_this_friday_18_warsaw():
    # Wtorek → piątek 30.10 18:00 CET (po zmianie czasu 25.10) = 17:00 UTC.
    assert job_p0.until_for("friday", NOW) == datetime(
        2026, 10, 30, 17, 0, tzinfo=timezone.utc
    )


def test_friday_after_18_on_friday_rolls_to_next_week():
    friday_evening = datetime(2026, 10, 30, 18, 30, tzinfo=timezone.utc)
    assert job_p0.until_for("friday", friday_evening) == datetime(
        2026, 11, 6, 17, 0, tzinfo=timezone.utc
    )


def test_friday_from_saturday_is_next_friday():
    saturday = datetime(2026, 10, 31, 10, 0, tzinfo=timezone.utc)
    assert job_p0.until_for("friday", saturday).date().isoformat() == "2026-11-06"


def test_unknown_duration_is_refused():
    with pytest.raises(job_p0.P0Error) as exc:
        job_p0.until_for("tydzień", NOW)
    assert exc.value.status == 422


@pytest.mark.parametrize("raw", [None, "", "  ", "ok"])
def test_reason_is_required(raw):
    with pytest.raises(job_p0.P0Error) as exc:
        job_p0.normalize_reason(raw)
    assert exc.value.status == 422


def test_reason_is_trimmed_and_capped():
    assert job_p0.normalize_reason("  Orlen   chce\n2 CV ") == "Orlen chce 2 CV"
    with pytest.raises(job_p0.P0Error):
        job_p0.normalize_reason("x" * (job_p0.REASON_MAX + 1))


def test_active_only_for_open_job_before_deadline():
    assert job_p0.is_active(_job(), NOW)
    assert not job_p0.is_active(_job(p0_until=NOW - timedelta(seconds=1)), NOW)
    assert not job_p0.is_active(_job(p0_until=None), NOW)
    assert not job_p0.is_active(_job(status=JobStatus.closed), NOW)


def test_expired_p0_returns_empty_fields():
    fields = job_p0.fields(_job(p0_until=datetime(2020, 1, 1, tzinfo=timezone.utc)))
    assert fields == {
        "is_p0": False,
        "p0_until": None,
        "p0_reason": None,
        "p0_set_at": None,
        "p0_set_by_name": None,
    }


def test_active_p0_fields_carry_reason_and_setter():
    job = _job(p0_until=datetime.now(timezone.utc) + timedelta(hours=2))
    fields = job_p0.fields(job, set_by_name="Olaf M.")
    assert fields["is_p0"] is True
    assert fields["p0_reason"] == "Orlen chce 2 CV do jutra"
    assert fields["p0_set_by_name"] == "Olaf M."


@pytest.mark.parametrize(
    ("roles", "allowed"),
    [
        ((UserRole.head_of_recruitment,), True),
        ((UserRole.admin,), True),
        ((UserRole.delivery_lead,), False),
        ((UserRole.recruiter,), False),
        ((UserRole.finance,), False),
        ((), False),
    ],
)
def test_only_head_of_recruitment_and_admin_set_p0(roles, allowed):
    assert job_p0.can_set_p0(_user(*roles)) is allowed


def test_nobody_without_account_sets_p0():
    assert job_p0.can_set_p0(None) is False


@pytest.mark.asyncio
async def test_set_refuses_closed_job():
    db = SimpleNamespace()
    with pytest.raises(job_p0.P0Error) as exc:
        await job_p0.set_p0(
            db, _job(status=JobStatus.closed), actor_id=11, reason="Pilne"
        )
    assert exc.value.status == 409


@pytest.mark.asyncio
async def test_extend_refuses_expired_p0():
    with pytest.raises(job_p0.P0Error) as exc:
        await job_p0.extend_p0(
            SimpleNamespace(),
            _job(p0_until=NOW - timedelta(minutes=1)),
            actor_id=11,
            now=NOW,
        )
    assert exc.value.status == 409


class _Db:
    def __init__(self):
        self.added = []

    def add(self, row):
        self.added.append(row)

    async def flush(self):
        return None


@pytest.mark.asyncio
async def test_set_writes_deadline_reason_and_trace():
    db = _Db()
    job = _job(p0_until=None, p0_reason=None, p0_set_at=None, p0_set_by=None)
    await job_p0.set_p0(
        db, job, actor_id=11, reason=" Orlen chce 2 CV ", duration="48h", now=NOW
    )
    assert job.p0_until == NOW + timedelta(hours=48)
    assert job.p0_reason == "Orlen chce 2 CV"
    assert job.p0_set_by == 11
    assert [a.action for a in db.added] == [job_p0.ACTION_SET]


@pytest.mark.asyncio
async def test_extend_adds_24h_to_current_deadline_not_to_now():
    db = _Db()
    job = _job(p0_until=NOW + timedelta(hours=3))
    await job_p0.extend_p0(db, job, actor_id=11, now=NOW)
    assert job.p0_until == NOW + timedelta(hours=27)


@pytest.mark.asyncio
async def test_clear_reports_whether_p0_was_active():
    db = _Db()
    job = _job()
    assert await job_p0.clear_p0(db, job, actor_id=11, now=NOW) is True
    assert job.p0_until is None and job.p0_reason is None
    assert await job_p0.clear_p0(db, job, actor_id=11, now=NOW) is False
    assert [a.action for a in db.added] == [job_p0.ACTION_CLEARED]


def test_p0_mail_is_required_and_sent_immediately():
    assert delivery.JOB_P0_KIND in delivery.REQUIRED_KINDS
    assert delivery.JOB_P0_KIND in delivery.IMMEDIATE_KINDS
    assert delivery.notification_kind("job_p0_set") == delivery.JOB_P0_KIND


# ── 28.10.2026: P0 widzi zespół rekrutacji, DL prosi, HoR zatwierdza ─────────


def _person(user_id, *roles):
    return SimpleNamespace(
        id=user_id, has_any_role=lambda *wanted: any(r in roles for r in wanted)
    )


@pytest.mark.parametrize(
    ("viewer", "visible"),
    [
        (_person(1, UserRole.head_of_recruitment), True),
        (_person(2, UserRole.admin), True),
        (_person(27, UserRole.delivery_lead), True),  # DL tej rekrutacji
        (_person(255, UserRole.recruiter), True),  # pracuje nad rekrutacją
        (_person(85, UserRole.recruiter), False),  # cudza rekrutacja
        (_person(28, UserRole.delivery_lead), False),  # inny DL
        (None, False),
    ],
)
def test_p0_is_visible_only_to_the_team_hor_and_admin(viewer, visible):
    assert (
        job_p0.visible_to(viewer, delivery_lead_id=27, working_ids=[255, 101])
        is visible
    )


def test_only_the_jobs_delivery_lead_requests_p0():
    job = _job(delivery_lead_id=27)
    assert job_p0.can_request_p0(_person(27, UserRole.delivery_lead), job) is True
    assert job_p0.can_request_p0(_person(28, UserRole.delivery_lead), job) is False
    assert job_p0.can_request_p0(_person(255, UserRole.recruiter), job) is False
    assert job_p0.can_request_p0(_person(27), _job(delivery_lead_id=None)) is False
    assert job_p0.can_request_p0(None, job) is False


def _requestable(**kw):
    base = dict(
        p0_until=None,
        p0_reason=None,
        p0_set_at=None,
        p0_set_by=None,
        delivery_lead_id=27,
        p0_request_reason=None,
        p0_request_duration=None,
        p0_requested_at=None,
        p0_requested_by=None,
    )
    base.update(kw)
    return _job(**base)


@pytest.mark.asyncio
async def test_request_stores_reason_duration_and_trace_without_setting_p0():
    db = _Db()
    job = _requestable()
    await job_p0.request_p0(
        db, job, actor_id=27, reason=" Klient zamyka listę ", duration="48h", now=NOW
    )
    assert job.p0_until is None
    assert job.p0_request_reason == "Klient zamyka listę"
    assert job.p0_request_duration == "48h"
    assert job.p0_requested_by == 27 and job.p0_requested_at == NOW
    assert [a.action for a in db.added] == [job_p0.ACTION_REQUESTED]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("job_kw", "body", "status"),
    [
        ({"p0_until": NOW + timedelta(hours=3)}, {}, 409),  # już jest P0
        ({"status": JobStatus.closed}, {}, 409),
        ({}, {"duration": "tydzień"}, 422),
        ({}, {"reason": "ok"}, 422),
    ],
)
async def test_request_refusals(job_kw, body, status):
    args = {"reason": "Klient zamyka listę", "duration": "24h", **body}
    with pytest.raises(job_p0.P0Error) as exc:
        await job_p0.request_p0(
            _Db(), _requestable(**job_kw), actor_id=27, now=NOW, **args
        )
    assert exc.value.status == status


@pytest.mark.asyncio
async def test_approve_sets_p0_from_the_request_and_closes_it():
    db = _Db()
    job = _requestable(
        p0_request_reason="Klient zamyka listę",
        p0_request_duration="48h",
        p0_requested_at=NOW - timedelta(minutes=5),
        p0_requested_by=27,
    )
    await job_p0.approve_request(db, job, actor_id=11, now=NOW)
    assert job.p0_until == NOW + timedelta(hours=48)
    assert job.p0_reason == "Klient zamyka listę"
    assert job.p0_set_by == 11
    assert not job_p0.has_request(job)
    assert job.p0_request_reason is None


@pytest.mark.asyncio
async def test_reject_clears_the_request_and_leaves_no_p0():
    db = _Db()
    job = _requestable(
        p0_request_reason="Klient zamyka listę",
        p0_request_duration="24h",
        p0_requested_at=NOW,
        p0_requested_by=27,
    )
    await job_p0.reject_request(db, job, actor_id=11)
    assert job.p0_until is None
    assert not job_p0.has_request(job)
    assert [a.action for a in db.added] == [job_p0.ACTION_REQUEST_REJECTED]
    assert db.added[0].details["requested_by"] == 27


@pytest.mark.asyncio
async def test_settled_request_cannot_be_approved_or_rejected_twice():
    for action in (job_p0.approve_request, job_p0.reject_request):
        with pytest.raises(job_p0.P0Error) as exc:
            await action(_Db(), _requestable(), actor_id=11)
        assert exc.value.status == 409


@pytest.mark.asyncio
async def test_direct_p0_by_hor_also_closes_a_pending_request():
    job = _requestable(
        p0_request_reason="Klient zamyka listę",
        p0_request_duration="24h",
        p0_requested_at=NOW,
        p0_requested_by=27,
    )
    await job_p0.set_p0(_Db(), job, actor_id=11, reason="Inny powód HoR", now=NOW)
    assert not job_p0.has_request(job)


def test_p0_request_mail_is_the_required_p0_mail():
    assert delivery.notification_kind("job_p0_requested") == delivery.JOB_P0_KIND
