"""Proces u klienta (18.11.2026): etapy po wysłaniu CV i czas zmierzony.

Część bez bazy: mediany, walidacja, profil bez klucza, odcisk rankingu.
Część z bazą (CI): zapis z bramką Championa, odmowa obcemu rekruterowi,
podpowiedź z poprzedniej rekrutacji klienta i mediany z ruchów kart.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from pydantic import ValidationError
from sqlalchemy import select

from app.schemas.champion import ChampionProfile, ClientProcessIn
from app.services import champion_view
from app.services.champion_intake import user_edit
from app.services.job_client_process import (
    MIN_DECISIONS,
    StagePair,
    stamp,
    stored_process,
    summarize,
    with_process,
)

T0 = datetime(2026, 9, 1, 9, 0, tzinfo=timezone.utc)
PROCESS = {
    "steps": [
        {"kind": "tech_interview", "format": "remote", "duration": "60 min"},
        {"kind": "home_task", "format": "remote", "duration": "ok. 3 h"},
    ],
    "decision_workdays": 10,
}


def _pair(interview_day: int | None, decision_day: int | None) -> StagePair:
    return StagePair(
        cv_sent=T0,
        client_interview=T0 + timedelta(days=interview_day)
        if interview_day is not None
        else None,
        acceptance=None,
        hired=T0 + timedelta(days=decision_day) if decision_day is not None else None,
    )


# ── mediany ──────────────────────────────────────────────────────────────────


def test_summary_needs_minimum_decisions():
    pairs = [_pair(7, 20)] * (MIN_DECISIONS - 1) + [_pair(5, None)] * 10
    assert summarize(pairs) is None


def test_summary_medians_in_calendar_days():
    pairs = [_pair(7, 20), _pair(9, 30), _pair(8, 29), _pair(6, 25), _pair(10, 40)]
    out = summarize(pairs)
    assert out == {
        "cv_to_interview_days": 8,
        "interview_to_decision_days": 21,
        "cv_to_decision_days": 29,
        "decisions": 5,
        "months": 18,
    }


def test_summary_ignores_backward_moves_and_missing_cv():
    good = [_pair(7, 20)] * MIN_DECISIONS
    # Karta cofnięta: „decyzja” przed wysłaniem CV nie daje ujemnego czasu.
    backward = StagePair(
        cv_sent=T0,
        client_interview=T0 - timedelta(days=3),
        acceptance=None,
        hired=T0 - timedelta(days=1),
    )
    no_cv = StagePair(
        cv_sent=None,
        client_interview=T0,
        acceptance=None,
        hired=T0 + timedelta(days=2),
    )
    out = summarize([*good, backward, no_cv])
    assert out["decisions"] == MIN_DECISIONS
    assert out["cv_to_interview_days"] == 7


def test_acceptance_before_client_interview_is_not_a_decision():
    # KIR na stagingu 18.11.2026: „Akceptacja” kilka godzin po wysłaniu CV,
    # rozmowa u klienta 16 dni później — mediana „decyzji” wychodziła 0 dni.
    early = StagePair(
        cv_sent=T0,
        client_interview=T0 + timedelta(days=16),
        acceptance=T0 + timedelta(hours=3),
        hired=T0 + timedelta(days=20),
    )
    out = summarize([early] * MIN_DECISIONS)
    assert out["cv_to_decision_days"] == 20
    assert out["interview_to_decision_days"] == 4
    # Akceptacja PO rozmowie jest decyzją, nawet gdy zatrudnienie przyszło później.
    late = StagePair(
        cv_sent=T0,
        client_interview=T0 + timedelta(days=7),
        acceptance=T0 + timedelta(days=10),
        hired=T0 + timedelta(days=30),
    )
    assert summarize([late] * MIN_DECISIONS)["cv_to_decision_days"] == 10


def test_summary_without_interview_still_counts_decision():
    out = summarize([_pair(None, 12)] * MIN_DECISIONS)
    assert out["cv_to_decision_days"] == 12
    assert out["cv_to_interview_days"] is None
    assert out["interview_to_decision_days"] is None


# ── walidacja i zapis ────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "bad",
    [
        {"steps": [{"kind": "coffee", "format": "remote"}]},
        {"steps": [{"kind": "tech_interview", "format": "moon"}]},
        {"steps": [{"kind": "tech_interview"}] * 7},
        {"steps": [{"kind": "tech_interview", "duration": "x" * 81}]},
        {"steps": [], "decision_workdays": 0},
        {"steps": [], "decision_workdays": 61},
    ],
)
def test_input_rejects_out_of_range(bad):
    with pytest.raises(ValidationError):
        ClientProcessIn.model_validate(bad)


def test_stamp_sets_author_and_empty_list_clears():
    user = type("U", (), {"id": 7, "name": "Delivery Lead"})()
    process = stamp(ClientProcessIn.model_validate(PROCESS), user)
    assert process["set_by_id"] == 7
    assert process["set_by_name"] == "Delivery Lead"
    assert process["set_at"]
    assert [s["kind"] for s in process["steps"]] == ["tech_interview", "home_task"]
    assert stamp(ClientProcessIn(steps=[]), user) is None
    assert "client_process" not in with_process({"client_process": process}, None)


def test_stored_process_tolerates_broken_entries():
    assert stored_process(None) is None
    assert stored_process({"client_process": "tekst"}) is None
    assert stored_process({"client_process": {"steps": [{"kind": "coffee"}]}}) is None
    assert stored_process({"client_process": {"steps": []}}) is None
    assert stored_process({"client_process": PROCESS})["decision_workdays"] == 10


# ── profil Championa ─────────────────────────────────────────────────────────


def test_profile_without_process_has_no_key():
    # Profile sprzed 18.11.2026 nie dostają klucza `null` przy zapisie —
    # inaczej zmieniłby się ich skrót i odcisk.
    assert "client_process" not in ChampionProfile.model_validate({}).model_dump(
        mode="json"
    )


def test_plain_profile_save_keeps_process():
    stored = with_process(
        ChampionProfile.model_validate({}).model_dump(mode="json"), PROCESS
    )
    saved = user_edit(stored, {"project": {"about": "Nowy opis projektu"}}, actor_id=1)
    assert saved["client_process"]["steps"][1]["kind"] == "home_task"
    # Zapis edytora nie może podrobić ani skasować procesu.
    forged = user_edit(
        stored, {"client_process": None, "project": {"about": "x"}}, actor_id=1
    )
    assert forged["client_process"]["decision_workdays"] == 10


def test_process_is_not_a_requirement():
    base = ChampionProfile.model_validate({}).model_dump(mode="json")
    with_it = with_process(base, PROCESS)
    for ignored in (
        champion_view.RANKING_IGNORED_KEYS,
        champion_view._NON_REQUIREMENT_KEYS,
    ):
        assert champion_view.requirement_source(
            base, ignored=ignored
        ) == champion_view.requirement_source(with_it, ignored=ignored)


# ── trasy (CI z PostgreSQL) ──────────────────────────────────────────────────


async def _seed_jobs(n: int = 2):
    from app.core.database import AsyncSessionLocal
    from app.models.client import Client
    from app.models.job import Job, JobStatus

    async with AsyncSessionLocal() as db:
        client = Client(name=f"Synthetic Process {uuid.uuid4().hex[:8]}")
        db.add(client)
        await db.flush()
        jobs = [
            Job(
                title=f"Synthetic role {i}",
                status=JobStatus.draft,
                client_id=client.id,
                champion_profile={},
            )
            for i in range(n)
        ]
        db.add_all(jobs)
        await db.commit()
        return client.id, [j.id for j in jobs]


async def test_put_saves_process_and_hint_suggests_it_for_next_job(
    app_client, app_auth_headers
):
    client_id, (first, second) = await _seed_jobs()
    saved = await app_client.put(
        f"/api/jobs/{first}/client-process", headers=app_auth_headers, json=PROCESS
    )
    assert saved.status_code == 200, saved.text
    assert saved.json()["client_process"]["steps"][0]["kind"] == "tech_interview"

    hints = await app_client.get(
        "/api/jobs/client-process",
        headers=app_auth_headers,
        params={"client_id": client_id, "job_id": second},
    )
    assert hints.status_code == 200, hints.text
    body = hints.json()
    assert body["suggested"]["from_job_id"] == first
    assert body["suggested"]["decision_workdays"] == 10
    assert body["measured"] is None  # brak ruchów kart

    # Podpowiedź nigdy nie wskazuje rekrutacji, o którą pyta.
    own = await app_client.get(
        "/api/jobs/client-process",
        headers=app_auth_headers,
        params={"client_id": client_id, "job_id": first},
    )
    assert own.json()["suggested"] is None

    cleared = await app_client.put(
        f"/api/jobs/{first}/client-process",
        headers=app_auth_headers,
        json={"steps": []},
    )
    assert cleared.json()["client_process"] is None


async def test_put_follows_the_champion_gate_and_refusal_writes_nothing(app_client):
    # Ta sama bramka co zapis Championa — rekruter spoza rekrutacji może tyle,
    # ile przy Championie (decyzja 22.09.2026: Champion redaguje też zespół
    # rekrutacji), a rola bez edycji rekrutacji dostaje odmowę i nic nie zapisuje.
    from app.core.database import AsyncSessionLocal
    from app.models.job import Job
    from app.models.user import UserRole
    from tests._jarvis_helpers import make_user

    _, (job_id,) = await _seed_jobs(1)
    _, recruiter = await make_user(UserRole.recruiter)
    champion = await app_client.put(
        f"/api/jobs/{job_id}/champion-profile", headers=recruiter, json={}
    )
    process = await app_client.put(
        f"/api/jobs/{job_id}/client-process", headers=recruiter, json={"steps": []}
    )
    refused = (401, 403, 404)
    assert (process.status_code in refused) == (champion.status_code in refused), (
        champion.text,
        process.text,
    )

    _, employee = await make_user(UserRole.employee)
    denied = await app_client.put(
        f"/api/jobs/{job_id}/client-process", headers=employee, json=PROCESS
    )
    assert denied.status_code == 403, denied.text
    async with AsyncSessionLocal() as db:
        profile = await db.scalar(select(Job.champion_profile).where(Job.id == job_id))
    assert "client_process" not in (profile or {})


async def test_put_rejects_invalid_body(app_client, app_auth_headers):
    _, (job_id,) = await _seed_jobs(1)
    bad = await app_client.put(
        f"/api/jobs/{job_id}/client-process",
        headers=app_auth_headers,
        json={"steps": [{"kind": "coffee"}]},
    )
    assert bad.status_code == 422


async def test_hint_measures_client_stage_moves(app_client, app_auth_headers):
    from app.core.database import AsyncSessionLocal
    from app.core.scheduling import local_now
    from app.models.candidate import Candidate
    from app.models.recruitment_pipeline import CandidateStage, PipelineStage

    client_id, (job_id,) = await _seed_jobs(1)
    start = local_now() - timedelta(days=60)
    async with AsyncSessionLocal() as db:
        for i in range(MIN_DECISIONS):
            cand = Candidate(name="Anna", lastname=f"Proces-{uuid.uuid4().hex[:6]}")
            db.add(cand)
            await db.flush()
            for stage, day in (
                (PipelineStage.cv_sent, 0),
                (PipelineStage.client_interview, 7),
                (PipelineStage.hired, 21 + i),
            ):
                db.add(
                    CandidateStage(
                        candidate_id=cand.id,
                        job_id=job_id,
                        stage=stage,
                        moved_at=start + timedelta(days=day),
                    )
                )
        await db.commit()
    hints = await app_client.get(
        "/api/jobs/client-process",
        headers=app_auth_headers,
        params={"client_id": client_id},
    )
    measured = hints.json()["measured"]
    assert measured["decisions"] == MIN_DECISIONS
    assert measured["cv_to_interview_days"] == 7
    assert measured["cv_to_decision_days"] == 23


# ── regresje z przeglądu (18.11.2026) ────────────────────────────────────────


def test_every_create_field_is_a_job_column_or_excluded():
    # `POST /api/jobs` robi `Job(**data.model_dump(exclude=...))` — pole spoza
    # kolumn i spoza wykluczeń kończy KAŻDE założenie rekrutacji błędem 500.
    from app.models.job import Job
    from app.schemas.job import JobCreate
    from app.services.job_lifecycle import _CREATE_EXCLUDED_FIELDS

    stray = [
        name
        for name in JobCreate.model_fields
        if name not in _CREATE_EXCLUDED_FIELDS and not hasattr(Job, name)
    ]
    assert stray == []


def test_process_does_not_change_editor_hashes():
    # Zapis procesu z nagłówka nie może dać edytorowi Championa ani importowi
    # fałszywego konfliktu (409), ani przywrócić odrzuconych porządków wymagań.
    from types import SimpleNamespace

    from app.services.champion_intake import fingerprint, profile_hash

    base = ChampionProfile.model_validate({}).model_dump(mode="json")
    before = SimpleNamespace(champion_profile=base, title="Java")
    after = SimpleNamespace(champion_profile=with_process(base, PROCESS), title="Java")
    assert profile_hash(before) == profile_hash(after)
    assert fingerprint(before) == fingerprint(after)


def test_template_copy_does_not_carry_process():
    # Proces przenosi tylko „Użyj” z podpowiedzi — kopia z szablonu nie może
    # przemycić cudzego procesu ze stemplem autora źródła.
    from app.services.champion_intake import copy_profile

    source = with_process(
        ChampionProfile.model_validate({}).model_dump(mode="json"), PROCESS
    )
    assert "client_process" not in copy_profile(source, actor_id=1)
