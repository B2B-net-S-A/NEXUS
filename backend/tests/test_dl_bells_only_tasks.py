"""Delivery Lead dostaje dzwonek tylko wtedy, gdy ma coś do zrobienia (19.11.2026).

Decyzja Artura (wariant A): znika siedem informacji do DL-a, które nie mają
wcześniejszej decyzji. Reguła: docs/claude/powiadomienia/dl-tylko-dzwonki-z-zadaniem.md.
Testy bez bazy: zależności odbiorców są podmienione.
"""

from types import SimpleNamespace

import pytest

from app.services import candidate_rate_change as rate_change
from app.services import job_p0
from app.services import similar_job_notify
from app.services import stage_handoff_recipients as handoff

DL = 27
RECRUITER = 7
HOR = 40


def _async(value):
    async def _fn(*_args, **_kwargs):
        return value

    return _fn


def _job(**kw):
    base = dict(
        id=789221,
        client_id=None,
        delivery_lead_id=DL,
        recruiter_id=RECRUITER,
        created_by=RECRUITER,
        title="Project Manager · IT",
    )
    base.update(kw)
    return SimpleNamespace(**base)


# ── „CV wysłane” do osoby, która przekazała kartę ───────────────────────────


@pytest.fixture
def cv_sent(monkeypatch):
    monkeypatch.setattr(
        handoff, "handoff_kind", lambda *_a, **_k: handoff.REASON_CV_SENT
    )
    monkeypatch.setattr(handoff, "pair_recruiter_id", _async(RECRUITER))
    monkeypatch.setattr(handoff, "_dl_reviewers", _async([DL]))


async def _cv_sent_recipients(previous_stage):
    _kind, ids = await handoff.handoff_recipients(
        SimpleNamespace(),
        stage_def=SimpleNamespace(),
        job=_job(),
        candidate_id=19738,
        previous_stage=previous_stage,
    )
    return ids


@pytest.mark.asyncio
async def test_cv_sent_skips_the_delivery_lead_who_only_added_the_card(cv_sent):
    """203 z 206 „CV wysłane” u DL-i w 06–19.11: DL wstawił kartę do „Nowych”
    (Match, „Wyślij też do”), a CV wysłał rekruter."""

    ids = await _cv_sent_recipients(SimpleNamespace(moved_by=DL, stage="new"))
    assert ids == [RECRUITER]


@pytest.mark.asyncio
async def test_cv_sent_still_rings_a_recruiter_who_added_the_card(cv_sent):
    ids = await _cv_sent_recipients(SimpleNamespace(moved_by=8, stage="new"))
    assert ids == [RECRUITER, 8]


@pytest.mark.asyncio
async def test_cv_sent_still_rings_a_delivery_lead_who_screened_the_person(cv_sent):
    ids = await _cv_sent_recipients(SimpleNamespace(moved_by=DL, stage="screening"))
    assert ids == [RECRUITER, DL]


@pytest.mark.asyncio
async def test_cv_sent_rings_a_delivery_lead_who_is_the_persons_recruiter(
    cv_sent, monkeypatch
):
    monkeypatch.setattr(handoff, "pair_recruiter_id", _async(DL))
    ids = await _cv_sent_recipients(SimpleNamespace(moved_by=DL, stage="new"))
    assert ids == [DL]


# ── Zapasy za brak prowadzącego ─────────────────────────────────────────────


def _no_delivery_lead_fallback(*_args, **_kwargs):
    raise AssertionError("DL nie jest już zapasem tego dzwonka")


@pytest.mark.asyncio
async def test_match_digest_without_a_working_recruiter_goes_to_nobody(monkeypatch):
    from app.services import job_previous_recruiters, notification_triggers
    from app.tasks import match_digest

    monkeypatch.setattr(job_previous_recruiters, "working_owner_id", _async(None))
    monkeypatch.setattr(notification_triggers, "_operational_recipient", _async(None))
    monkeypatch.setattr(
        notification_triggers, "_delivery_lead_targets", _no_delivery_lead_fallback
    )
    assert await match_digest._digest_recipients(SimpleNamespace(), _job()) == set()


@pytest.mark.asyncio
async def test_match_digest_still_goes_to_the_working_recruiter(monkeypatch):
    from app.services import job_previous_recruiters, notification_triggers
    from app.tasks import match_digest

    monkeypatch.setattr(job_previous_recruiters, "working_owner_id", _async(RECRUITER))
    monkeypatch.setattr(
        notification_triggers, "_operational_recipient", _async(RECRUITER)
    )
    assert await match_digest._digest_recipients(SimpleNamespace(), _job()) == {
        RECRUITER
    }


async def _first(_db, ids):
    return ids[0]


@pytest.mark.asyncio
async def test_similar_job_skips_the_delivery_lead_who_created_the_job(monkeypatch):
    """Wszystkie 10 „Podobny request” u DL-i w 06–19.11 szły do twórcy-DL-a."""

    monkeypatch.setattr(similar_job_notify, "working_owner_id", _async(RECRUITER))
    monkeypatch.setattr(similar_job_notify, "_operational_recipient", _first)
    ids = await similar_job_notify._recipients(SimpleNamespace(), _job(created_by=DL))
    assert ids == [RECRUITER]


@pytest.mark.asyncio
async def test_similar_job_without_a_recruiter_goes_to_nobody(monkeypatch):
    monkeypatch.setattr(similar_job_notify, "working_owner_id", _async(None))
    monkeypatch.setattr(similar_job_notify, "_operational_recipient", _first)
    job = _job(recruiter_id=None, created_by=DL)
    assert await similar_job_notify._recipients(SimpleNamespace(), job) == []


@pytest.mark.asyncio
async def test_portal_application_without_a_recruiter_rings_nobody(monkeypatch):
    from app.services import job_previous_recruiters, notification_triggers
    from app.services import portal_application

    emitted: list[int] = []

    async def _emit(_db, *, user_id, **_kw):
        emitted.append(user_id)

    rows = iter([_job(), SimpleNamespace(name="Jan", lastname="Kalitka")])

    async def _scalar(_stmt):
        return next(rows)

    async def _commit():
        return None

    monkeypatch.setattr(job_previous_recruiters, "working_owner_id", _async(None))
    monkeypatch.setattr(notification_triggers, "emit", _emit)
    db = SimpleNamespace(scalar=_scalar, commit=_commit)
    await portal_application.notify_recruiter(
        db, job_id=789221, candidate_id=19738, portal="justjoinit"
    )
    assert emitted == []


@pytest.mark.asyncio
async def test_portal_application_still_rings_the_working_recruiter(monkeypatch):
    from app.services import job_previous_recruiters, notification_triggers
    from app.services import portal_application

    emitted: list[int] = []
    rows = iter([_job(), SimpleNamespace(name="Jan", lastname="Kalitka")])

    async def _emit(_db, *, user_id, **_kw):
        emitted.append(user_id)

    async def _scalar(_stmt):
        return next(rows)

    async def _commit():
        return None

    monkeypatch.setattr(job_previous_recruiters, "working_owner_id", _async(RECRUITER))
    monkeypatch.setattr(notification_triggers, "emit", _emit)
    db = SimpleNamespace(scalar=_scalar, commit=_commit)
    await portal_application.notify_recruiter(
        db, job_id=789221, candidate_id=19738, portal="justjoinit"
    )
    assert emitted == [RECRUITER]


# ── P0 i zmiana stawki ──────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_p0_bell_goes_to_the_recruiters_without_the_delivery_lead(monkeypatch):
    from app.services import job_team

    team = [SimpleNamespace(user_id=RECRUITER), SimpleNamespace(user_id=8)]
    monkeypatch.setattr(job_team, "recruiters_for_jobs", _async({789221: team}))
    monkeypatch.setattr(job_team, "working", lambda people: people)
    ids = await job_p0.team_recipients(SimpleNamespace(), _job(), actor_id=8)
    assert ids == [RECRUITER]


@pytest.mark.asyncio
async def test_p0_bell_reaches_a_delivery_lead_who_recruits_on_the_job(monkeypatch):
    from app.services import job_team

    team = [SimpleNamespace(user_id=DL)]
    monkeypatch.setattr(job_team, "recruiters_for_jobs", _async({789221: team}))
    monkeypatch.setattr(job_team, "working", lambda people: people)
    ids = await job_p0.team_recipients(SimpleNamespace(), _job(), actor_id=None)
    assert ids == [DL]


@pytest.fixture
def rate_people(monkeypatch):
    from app.services import notification_triggers

    monkeypatch.setattr(handoff, "_dl_reviewers", _async([DL]))
    monkeypatch.setattr(handoff, "pair_recruiter_id", _async(RECRUITER))
    monkeypatch.setattr(notification_triggers, "_hor_user_ids", _async([HOR]))


@pytest.mark.asyncio
async def test_rate_change_without_a_decision_skips_the_delivery_lead(rate_people):
    out = await rate_change._recipients(
        SimpleNamespace(),
        job=_job(),
        candidate_id=19738,
        actor_id=99,
        requires_decision=False,
    )
    assert out == [(HOR, "hor"), (RECRUITER, "recruiter")]


@pytest.mark.asyncio
async def test_rate_change_waiting_for_a_decision_still_asks_the_delivery_lead(
    rate_people,
):
    out = await rate_change._recipients(
        SimpleNamespace(),
        job=_job(),
        candidate_id=19738,
        actor_id=99,
        requires_decision=True,
    )
    assert out[0] == (DL, "dl")


# ── Terminy rekrutacji ──────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_job_deadline_alert_skips_the_delivery_lead(monkeypatch):
    from app.tasks import job_deadline_alerts as deadlines

    asked: list[set[int]] = []

    class _Rows:
        def __init__(self, rows):
            self._rows = rows

        def all(self):
            return self._rows

        def scalars(self):
            return self

    async def _execute(stmt):
        if not asked:
            asked.append(set())
            return _Rows([])  # bez współpracowników
        ids = set(stmt.compile().params.get("id_1", []))
        asked.append(ids)
        return _Rows([SimpleNamespace(id=uid) for uid in sorted(ids)])

    monkeypatch.setattr(deadlines, "load_parked", _async({}))
    monkeypatch.setattr(
        deadlines, "resolve_effective_section_access_for_users", _async(None)
    )
    monkeypatch.setattr(deadlines, "user_can_access_candidate_domain", lambda _u: True)
    monkeypatch.setattr(
        deadlines, "user_can_receive_notification", lambda *_a, **_k: True
    )
    job = _job(tac_id=None)
    ids = await deadlines._assigned_user_ids(SimpleNamespace(execute=_execute), job)
    assert ids == [RECRUITER]
    assert DL not in asked[-1]
