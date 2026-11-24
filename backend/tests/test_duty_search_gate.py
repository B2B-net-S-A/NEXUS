"""„Kto już to robił” — bramka dopuszczalności z prawdziwą rekrutacją (bez bazy).

Audyt 24.11.2026: przebieg z rekrutacji bramkował osoby ofertą efemeryczną
(``hiring_manager_contact_id=None``, ``id=None``), więc weto hiring managera
i „już w procesie” nie działały, plakietki konfliktów klienta przepadały,
a „Dodaj do Nowych” kończyło się 409 z twardej bramki. Ranking kanoniczny
w ogóle nie przechodził przez bramkę z rekrutacją.

Reguła: docs/claude/kandydaci-wyszukiwanie/kto-juz-to-robil-wyszukiwanie-po-celu.md
"""

from types import SimpleNamespace

import pytest

from app.models.job import Job
from app.services import duty_search as ds
from app.services.talent_radar_search import RadarQuery, build_ephemeral_job

JOB_ID = 42
CLIENT_ID = 3
HM_ID = 7
VETOED = 2
HIDDEN = 4

VETO = {
    "reason_code": "hiring_manager_rejected",
    "reason": "Hiring manager odrzucił tę osobę",
    "assignment_allowed": False,
    "visibility": "warn",
    "severity": "hard",
    "secondary": [],
}
CONFLICT = {
    "reason_code": "client_nda",
    "reason": "Konflikt z klientem",
    "assignment_allowed": True,
    "visibility": "warn",
    "severity": "soft",
    "secondary": [],
}


def _real_job():
    job = build_ephemeral_job(
        RadarQuery(client_id=CLIENT_ID, text="Migracja aplikacji do chmury")
    )
    job.id = JOB_ID
    job.hiring_manager_contact_id = HM_ID
    job.work_mode = None
    job.train_name = None
    return job


class _Nested:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


class _FakeDb:
    def __init__(self, job):
        self.job = job
        self.added = []

    async def get(self, model, pk):
        if model is Job and self.job is not None and pk == self.job.id:
            return self.job
        return None

    async def execute(self, *_args, **_kwargs):
        return None

    def add(self, obj):
        self.added.append(obj)

    def begin_nested(self):
        return _Nested()


def _run(job_id):
    return SimpleNamespace(
        id="run-1",
        created_by=5,
        client_id=CLIENT_ID,
        job_id=job_id,
        goal_title="Migracja do chmury",
        goal_text="Przenieść 40 aplikacji z serwerowni do chmury publicznej.",
        metrics={},
        plan=None,
    )


@pytest.fixture
def gate_calls(monkeypatch):
    calls = []

    async def fake_gate(_db, *, job, ordered, now, inputs=None, **_kw):
        calls.append((job.id, job.hiring_manager_contact_id, [c.id for c in ordered]))
        annotations = {}
        for c in ordered:
            if job.hiring_manager_contact_id == HM_ID and c.id == VETOED:
                annotations[c.id] = VETO
            elif c.id == 3:
                annotations[c.id] = CONFLICT
        # „Już w tej rekrutacji” bramka ukrywa tylko z prawdziwym ``job.id``.
        kept = [c for c in ordered if not (job.id == JOB_ID and c.id == HIDDEN)]
        return kept, annotations, {}, 0, inputs

    async def fake_load(_db, ids):
        return [SimpleNamespace(id=cid) for cid in ids]

    async def fake_profile(_db, **_kw):
        from app.services.scoring_service import DEFAULT_PROFILE

        return DEFAULT_PROFILE

    async def fake_canonical(_db, _query, *, user_id):
        return SimpleNamespace(
            breakdowns=[
                SimpleNamespace(
                    breakdown=SimpleNamespace(candidate_id=cid), fit_score=80.0 - cid
                )
                for cid in (1, VETOED, HIDDEN)
            ],
            degraded=False,
        )

    async def fake_plan(_db, _run):
        return ds.GoalPlan(summary="Migracja"), True

    async def fake_pool(_db, _run, _plan):
        return [3, 5], {"goal": 2}

    async def fake_judge(_db, _run, _plan, people):
        return {
            p.candidate_id: ds.Assessment(tier="ma_klocki", confidence=50)
            for p in people
        }

    async def fake_cvs(_db, ids):
        return {cid: "" for cid in ids}

    async def nobody_in_job(_db, _job_id):
        return set()

    monkeypatch.setattr("app.api.matching._gate_and_dealbreakers", fake_gate)
    monkeypatch.setattr("app.services.talent_radar_search._load_candidates", fake_load)
    monkeypatch.setattr(
        "app.services.talent_radar_search.canonical_search", fake_canonical
    )
    monkeypatch.setattr(
        "app.services.scoring_service.resolve_active_profile", fake_profile
    )
    monkeypatch.setattr(ds, "_plan", fake_plan)
    monkeypatch.setattr(ds, "_goal_pool", fake_pool)
    monkeypatch.setattr(ds, "_judge", fake_judge)
    monkeypatch.setattr(ds, "_load_cvs", fake_cvs)
    monkeypatch.setattr(ds, "_already_in_job", nobody_in_job)
    return calls


def _stored(db):
    return {r.candidate_id: r for r in db.added}


@pytest.mark.asyncio
async def test_job_run_gates_canonical_and_goal_pool_with_real_job(gate_calls):
    db = _FakeDb(_real_job())

    await ds.execute_run(db, _run(JOB_ID))

    assert gate_calls, "bramka nie została wywołana"
    assert {(job_id, hm) for job_id, hm, _ in gate_calls} == {(JOB_ID, HM_ID)}
    gated = {cid for _, _, ids in gate_calls for cid in ids}
    assert {1, VETOED, HIDDEN, 3, 5} <= gated

    stored = _stored(db)
    assert HIDDEN not in stored
    # Weto HM: osoba widoczna z plakietką i zablokowanym dodaniem — jak pełny przegląd.
    assert stored[VETOED].assessment["eligibility"]["assignment_allowed"] is False
    assert stored[3].assessment["eligibility"]["reason_code"] == "client_nda"
    assert "eligibility" not in stored[1].assessment


@pytest.mark.asyncio
async def test_run_without_job_keeps_client_conflict_badges(gate_calls):
    db = _FakeDb(None)

    await ds.execute_run(db, _run(None))

    assert {(job_id, hm) for job_id, hm, _ in gate_calls} == {(None, None)}
    stored = _stored(db)
    assert stored[3].assessment["eligibility"]["reason_code"] == "client_nda"
    assert HIDDEN in stored
    assert "eligibility" not in stored[VETOED].assessment


@pytest.mark.asyncio
async def test_job_run_falls_back_to_ephemeral_when_job_is_gone(gate_calls):
    db = _FakeDb(None)

    await ds.execute_run(db, _run(JOB_ID))

    assert {(job_id, hm) for job_id, hm, _ in gate_calls} == {(None, None)}
