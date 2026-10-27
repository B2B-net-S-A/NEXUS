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
