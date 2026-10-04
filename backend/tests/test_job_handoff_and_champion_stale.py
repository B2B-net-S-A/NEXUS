"""P0-A: create→handoff reorder + Champion-edit staleness.

The operational ranking is no longer produced at job-create time (it would be a
pre-Champion ranking that then persisted). It is produced by the explicit
"Przekaż do searchu" handoff, which requires a filled Champion (readiness gate)
and binds a recruiter via ``recruiter_id``. Separately, editing a Champion now
re-embeds the job and marks its cached match scores stale, so the Delivery
Lead's work reaches the recruiter's ranking.

Uses the in-process ``app_client`` / ``app_auth_headers`` (admin) fixtures.
"""

from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient

from app.core.database import AsyncSessionLocal
from tests._job_factory import competence_category_id, complete_job_payload

_READY_CHAMPION = {
    "project_context": {
        "about": "Platforma płatności B2B",
        "responsibilities": "Rozwój usług backendowych",
    },
    "screening_questions": [
        {
            "id": "q1",
            "question": "Doświadczenie z Pythonem?",
            "deal_breaker": "Brak komercyjnego projektu w Pythonie.",
        },
        {
            "id": "q2",
            "question": "Doświadczenie z Postgres?",
            "deal_breaker": "Nie pracował z relacyjną bazą.",
        },
    ],
    # 0278: sekcje rubryk (must-have / budżet / tryb pracy) — obok jawnych
    # kolumn ustawianych w `_seed_job` (na wypadek testów, które PUT-ują ten
    # słownik jako nowy profil zamiast polegać na kolumnach z seeda).
    "stack": {"must": [{"name": "Python"}], "critical": []},
    "basics": {"rate_value": 150, "work_mode": "zdalnie"},
    # Wymagania do wyszukiwania w bazie — bramka handoffu od 25.09.2026.
    "search": {"requirements": [["Python"]]},
}


async def _seed_client() -> int:
    from app.models.client import Client

    async with AsyncSessionLocal() as db:
        cli = Client(name=f"HandoffClient-{uuid.uuid4().hex[:6]}")
        db.add(cli)
        await db.commit()
        await db.refresh(cli)
        return cli.id


async def _seed_job(*, champion: dict | None = None, status=None) -> int:
    from app.models.job import Job, JobStatus, RemotePolicy

    client_id = await _seed_client()
    async with AsyncSessionLocal() as db:
        job = Job(
            title=f"Handoff-Job-{uuid.uuid4().hex[:6]}",
            status=status or JobStatus.published,
            client_id=client_id,
            champion_profile=champion,
            # 0278: kolumny jawne, NIEZALEŻNE od CHAMPION_MATCH_SIGNALS_ENABLED
            # (w testach domyślnie False) — bramka gotowości ma trzy dodatkowe
            # rubryki, a te testy sprawdzają ścieżkę Championa (kontekst +
            # pytania), nie te rubryki. `champion=None` przypadki (test
            # „zablokowane bez Championa") i tak zostają zablokowane przez
            # brakujący kontekst/pytania — dodatkowe „gotowe" kolumny im nie
            # przeszkadzają.
            remote_policy=RemotePolicy.remote,
            rate_budget_hourly=150,
            must_skills=[{"name": "Python"}],
            # 0415: decyzje bramki przekazania (rekrutacja bez szkiców).
            competence_category_id=await competence_category_id(),
            hiring_manager_not_provided=True,
            deadline_not_provided=True,
        )
        db.add(job)
        await db.commit()
        await db.refresh(job)
        return job.id


async def _seed_recruiter() -> int:
    from app.models.user import User, UserRole
    from app.core.security import hash_password

    async with AsyncSessionLocal() as db:
        u = User(
            email=f"ho-rec-{uuid.uuid4().hex[:8]}@example.com",
            password_hash=hash_password("x"),
            name="Handoff Recruiter",
            role=UserRole.recruiter,
            roles=["recruiter"],
            is_active=True,
        )
        db.add(u)
        await db.commit()
        await db.refresh(u)
        return u.id


async def _seed_candidate() -> int:
    from app.models.candidate import Candidate, CandidateStatus

    async with AsyncSessionLocal() as db:
        c = Candidate(
            name="Ho",
            lastname=f"Cand-{uuid.uuid4().hex[:6]}",
            email=f"ho-{uuid.uuid4().hex[:8]}@example.com",
            status=CandidateStatus.active,
        )
        db.add(c)
        await db.commit()
        await db.refresh(c)
        return c.id


# ── handoff readiness + binding ──────────────────────────────────────────────


async def test_handoff_blocked_without_champion(
    app_client: AsyncClient, app_auth_headers: dict
):
    job_id = await _seed_job(champion=None)
    recruiter_id = await _seed_recruiter()

    resp = await app_client.post(
        f"/api/jobs/{job_id}/handoff",
        headers=app_auth_headers,
        json={"recruiter_id": recruiter_id},
    )

    assert resp.status_code == 422, resp.text
    blockers = resp.json()["detail"]["blockers"]
    assert any("Champion" in b for b in blockers)


async def test_handoff_binds_recruiter_and_creates_snapshot(
    app_client: AsyncClient, app_auth_headers: dict, monkeypatch
):
    # Keep the background compute offline + fast.
    from app.services import embedding_service, canonical_fit

    async def _empty(*_a, **_k):
        return []

    async def _noop(*_a, **_k):
        return None

    monkeypatch.setattr(embedding_service, "search_candidates_semantic", _empty)
    monkeypatch.setattr(embedding_service, "embed_job", _noop)
    monkeypatch.setattr(canonical_fit, "score_candidates", _empty)

    job_id = await _seed_job(champion=_READY_CHAMPION)
    recruiter_id = await _seed_recruiter()

    resp = await app_client.post(
        f"/api/jobs/{job_id}/handoff",
        headers=app_auth_headers,
        json={"recruiter_id": recruiter_id},
    )

    assert resp.status_code == 202, resp.text
    body = resp.json()
    assert body["status"] == "handed_off"
    assert body["recruiter_id"] == recruiter_id

    from sqlalchemy import select
    from app.models.job import Job
    from app.models.proposal_snapshot import ProposalSnapshot

    async with AsyncSessionLocal() as db:
        job = await db.get(Job, job_id)
        assert job.recruiter_id == recruiter_id  # bound → job member
        snap = await db.scalar(
            select(ProposalSnapshot).where(ProposalSnapshot.job_id == job_id)
        )
        assert snap is not None
        assert snap.source == "handoff"


async def test_second_handoff_replaces_the_recruiter(
    app_client: AsyncClient, app_auth_headers: dict, monkeypatch
):
    """Ponowne przekazanie innej osobie ZASTĘPUJE rekrutera, nie dokłada drugiego.

    Poprzednia osoba ma aktywne przypisanie do requestu. Bez zwolnienia go przy
    drugim przekazaniu obie osoby byłyby „Rekruterem” (lista, pulpit,
    obłożenie), choć Delivery Lead wskazał jedną.
    """
    from app.services import embedding_service, canonical_fit
    from app.services.job_team import recruiters_for_jobs

    async def _empty(*_a, **_k):
        return []

    async def _noop(*_a, **_k):
        return None

    monkeypatch.setattr(embedding_service, "search_candidates_semantic", _empty)
    monkeypatch.setattr(embedding_service, "embed_job", _noop)
    monkeypatch.setattr(canonical_fit, "score_candidates", _empty)

    job_id = await _seed_job(champion=_READY_CHAMPION)
    first_id = await _seed_recruiter()
    second_id = await _seed_recruiter()

    async def handoff(recruiter_id: int) -> None:
        resp = await app_client.post(
            f"/api/jobs/{job_id}/handoff",
            headers=app_auth_headers,
            json={"recruiter_id": recruiter_id},
        )
        assert resp.status_code == 202, resp.text

    await handoff(first_id)
    # Aktywne przypisanie pierwszej osoby (tak samo zostawia je `/owner`
    # i akceptacja propozycji automatu).
    added = await app_client.post(
        f"/api/request-board/jobs/{job_id}/people",
        headers=app_auth_headers,
        json={"user_id": first_id, "role": "recruiter"},
    )
    assert added.status_code == 200, added.text
    await handoff(second_id)

    async with AsyncSessionLocal() as db:
        team = await recruiters_for_jobs(db, [job_id])
    working = [person.user_id for person in team[job_id] if not person.proposed]
    assert working == [second_id]


async def test_manual_handoff_rings_the_chosen_recruiter_once(
    app_client: AsyncClient, app_auth_headers: dict, monkeypatch
):
    """Rekruter wskazany ręcznie dostaje dzwonek „Nowy request do pracy”.

    Do 04.10.2026 dzwonek wychodził tylko przy przydziale przez automat
    i akceptacji propozycji — osoba wskazana w „Przekaż do searchu” nie
    wiedziała, że dostała rekrutację. Ponowne przekazanie tej samej osobie
    nie dzwoni drugi raz.
    """
    from sqlalchemy import func, select

    from app.models.notification import Notification, NotificationType
    from app.services import embedding_service, canonical_fit

    async def _empty(*_a, **_k):
        return []

    async def _noop(*_a, **_k):
        return None

    monkeypatch.setattr(embedding_service, "search_candidates_semantic", _empty)
    monkeypatch.setattr(embedding_service, "embed_job", _noop)
    monkeypatch.setattr(canonical_fit, "score_candidates", _empty)

    job_id = await _seed_job(champion=_READY_CHAMPION)
    recruiter_id = await _seed_recruiter()

    async def rings() -> int:
        async with AsyncSessionLocal() as db:
            return await db.scalar(
                select(func.count(Notification.id)).where(
                    Notification.user_id == recruiter_id,
                    Notification.notification_type
                    == NotificationType.request_assignment_changed,
                    Notification.related_entity_type == "job",
                    Notification.related_entity_id == job_id,
                )
            )

    for _ in range(2):
        resp = await app_client.post(
            f"/api/jobs/{job_id}/handoff",
            headers=app_auth_headers,
            json={"recruiter_id": recruiter_id},
        )
        assert resp.status_code == 202, resp.text
        assert await rings() == 1


async def test_handoff_rejects_non_operational_recruiter(
    app_client: AsyncClient, app_auth_headers: dict
):
    from app.models.user import User, UserRole
    from app.core.security import hash_password

    # Finance jest od 19.08 rolą operacyjną (może być odbiorcą handoffu) —
    # nie-operacyjnym odbiorcą pozostaje wycofywany viewer `user`.
    job_id = await _seed_job(champion=_READY_CHAMPION)
    async with AsyncSessionLocal() as db:
        viewer = User(
            email=f"viewer-{uuid.uuid4().hex[:8]}@example.com",
            password_hash=hash_password("x"),
            name="Viewer",
            role=UserRole.user,
            roles=["user"],
            is_active=True,
        )
        db.add(viewer)
        await db.commit()
        await db.refresh(viewer)
        viewer_id = viewer.id

    resp = await app_client.post(
        f"/api/jobs/{job_id}/handoff",
        headers=app_auth_headers,
        json={"recruiter_id": viewer_id},
    )

    assert resp.status_code == 422, resp.text


async def test_handoff_rejects_closed_job(
    app_client: AsyncClient, app_auth_headers: dict
):
    from app.models.job import JobStatus

    job_id = await _seed_job(champion=_READY_CHAMPION, status=JobStatus.closed)
    recruiter_id = await _seed_recruiter()

    resp = await app_client.post(
        f"/api/jobs/{job_id}/handoff",
        headers=app_auth_headers,
        json={"recruiter_id": recruiter_id},
    )

    assert resp.status_code == 409, resp.text


# ── handoff „Zaproponuje automat” (gałąź automatyczna, 02.10.2026) ───────────


async def _swap_allocation_mode(mode: str | None) -> str | None:
    """Ustawia tryb automatu przydziału; zwraca poprzedni (``None`` = brak wiersza).

    Wiersz jest singletonem wspólnym dla całej bazy testowej, więc każdy test
    przywraca poprzednią wartość w ``finally``.
    """
    from app.models.recruitment_allocation import RecruitmentAllocationState

    async with AsyncSessionLocal() as db:
        state = await db.get(RecruitmentAllocationState, 1)
        previous = state.mode if state is not None else None
        if mode is None:
            if state is not None:
                await db.delete(state)
        elif state is None:
            db.add(RecruitmentAllocationState(id=1, mode=mode))
        else:
            state.mode = mode
        await db.commit()
        return previous


async def _handoff_trace(job_id: int) -> dict:
    """Co przekazanie zostawiło w bazie: stan rekrutacji, migawki, historia."""
    from sqlalchemy import select

    from app.models.activity import Activity
    from app.models.job import Job
    from app.models.proposal_snapshot import ProposalSnapshot

    async with AsyncSessionLocal() as db:
        job = await db.get(Job, job_id)
        snapshots = (
            await db.scalars(
                select(ProposalSnapshot).where(ProposalSnapshot.job_id == job_id)
            )
        ).all()
        handoffs = (
            await db.scalars(
                select(Activity).where(
                    Activity.entity_type == "job",
                    Activity.entity_id == job_id,
                    Activity.action == "handed_off_to_search",
                )
            )
        ).all()
        return {
            "work_state": job.work_state,
            "is_open": job.is_open,
            "recruiter_id": job.recruiter_id,
            "snapshots": [(snap.id, snap.source) for snap in snapshots],
            "handoff_details": [activity.details for activity in handoffs],
        }


async def _take_out_of_the_pool(job_id: int) -> None:
    """Request przekazany automatowi zostaje w puli przydziału — a przebiegi
    automatu z innych plików liczą całą (wspólną) bazę."""
    from app.models.job import Job, JobStatus

    async with AsyncSessionLocal() as db:
        job = await db.get(Job, job_id)
        job.status = JobStatus.closed
        await db.commit()


@pytest.mark.parametrize(
    ("enabled", "stored", "expected"),
    [
        # Flaga wygrywa z zapisanym trybem — bez niej pętla w ogóle nie chodzi.
        (False, "auto", "off"),
        # Bez wiersza stanu: pierwszy przebieg pętli zakłada go w trybie cienia.
        (True, None, "shadow"),
        (True, "off", "off"),
        (True, "shadow", "shadow"),
        (True, "auto", "auto"),
    ],
)
async def test_allocation_mode_is_the_flag_and_then_the_stored_row(
    monkeypatch, enabled: bool, stored: str | None, expected: str
):
    """Bez bazy: jedna reguła dla `readiness.allocation_mode` i odmowy 409."""
    from types import SimpleNamespace
    from unittest.mock import AsyncMock

    from app.api import jobs as jobs_api
    from app.core.config import settings

    monkeypatch.setattr(settings, "RECRUITMENT_ALLOCATION_ENABLED", enabled)
    db = AsyncMock()
    db.get.return_value = SimpleNamespace(mode=stored) if stored else None

    assert await jobs_api._allocation_mode(db) == expected
    if not enabled:
        db.get.assert_not_awaited()


async def test_automatic_handoff_is_refused_while_the_flag_is_off(
    app_client: AsyncClient, app_auth_headers: dict, monkeypatch
):
    from app.core.config import settings

    monkeypatch.setattr(settings, "RECRUITMENT_ALLOCATION_ENABLED", False)
    job_id = await _seed_job(champion=_READY_CHAMPION)

    readiness = await app_client.get(
        f"/api/jobs/{job_id}/readiness", headers=app_auth_headers
    )
    assert readiness.status_code == 200, readiness.text
    assert readiness.json()["allocation_enabled"] is False
    # Bez flagi tryb to zawsze „off” — niezależnie od zapisanego wiersza.
    assert readiness.json()["allocation_mode"] == "off"

    resp = await app_client.post(
        f"/api/jobs/{job_id}/handoff",
        headers=app_auth_headers,
        json={"assignment_mode": "automatic"},
    )

    assert resp.status_code == 409, resp.text
    trace = await _handoff_trace(job_id)
    assert trace["work_state"] == "to_review"
    assert trace["snapshots"] == []
    assert trace["handoff_details"] == []


async def test_automatic_handoff_is_refused_when_the_allocator_is_switched_off(
    app_client: AsyncClient, app_auth_headers: dict, monkeypatch
):
    """Tryb ``off``: pętla nikogo nie zaproponuje ani nie przydzieli, więc
    request stałby w „Szukamy” bez rekrutera i bez sygnału dla kogokolwiek."""
    from app.core.config import settings

    monkeypatch.setattr(settings, "RECRUITMENT_ALLOCATION_ENABLED", True)
    job_id = await _seed_job(champion=_READY_CHAMPION)
    previous = await _swap_allocation_mode("off")
    try:
        readiness = await app_client.get(
            f"/api/jobs/{job_id}/readiness", headers=app_auth_headers
        )
        assert readiness.status_code == 200, readiness.text
        assert readiness.json()["ready"] is True
        assert readiness.json()["allocation_enabled"] is True
        assert readiness.json()["allocation_mode"] == "off"

        resp = await app_client.post(
            f"/api/jobs/{job_id}/handoff",
            headers=app_auth_headers,
            json={"assignment_mode": "automatic"},
        )

        assert resp.status_code == 409, resp.text
        assert "wybierz rekrutera ręcznie" in resp.json()["detail"]
        trace = await _handoff_trace(job_id)
        assert trace["work_state"] == "to_review"
        assert trace["is_open"] is False
        assert trace["snapshots"] == []
        assert trace["handoff_details"] == []
    finally:
        await _swap_allocation_mode(previous)


async def test_automatic_handoff_queues_the_ranking_and_leaves_history(
    app_client: AsyncClient, app_auth_headers: dict, monkeypatch
):
    """Do 02.10.2026 przekazanie „automatowi” nie liczyło dopasowań i nie
    zostawiało wpisu w historii — osoba zaakceptowana później zastawała pustą
    listę, a w historii rekrutacji nie było śladu, kto ją przekazał."""
    from app.core.config import settings
    from app.services import canonical_fit, embedding_service

    async def _empty(*_a, **_k):
        return []

    async def _noop(*_a, **_k):
        return None

    # Liczenie migawki w tle zostaje offline i szybkie.
    monkeypatch.setattr(embedding_service, "search_candidates_semantic", _empty)
    monkeypatch.setattr(embedding_service, "embed_job", _noop)
    monkeypatch.setattr(canonical_fit, "score_candidates", _empty)
    monkeypatch.setattr(settings, "RECRUITMENT_ALLOCATION_ENABLED", True)
    job_id = await _seed_job(champion=_READY_CHAMPION)
    previous = await _swap_allocation_mode("shadow")
    try:
        readiness = await app_client.get(
            f"/api/jobs/{job_id}/readiness", headers=app_auth_headers
        )
        assert readiness.status_code == 200, readiness.text
        assert readiness.json()["allocation_mode"] == "shadow"

        resp = await app_client.post(
            f"/api/jobs/{job_id}/handoff",
            headers=app_auth_headers,
            json={"assignment_mode": "automatic"},
        )

        assert resp.status_code == 202, resp.text
        body = resp.json()
        assert body["status"] == "queued"
        assert body["job_id"] == job_id
        assert body["recruiter_id"] is None
        assert body["allocation_request_id"] is None

        trace = await _handoff_trace(job_id)
        assert trace["work_state"] == "searching"
        assert trace["is_open"] is True
        # Rekrutera wybierze automat (propozycja) i Head of Recruitment.
        assert trace["recruiter_id"] is None
        assert trace["snapshots"] == [(body["snapshot_id"], "handoff")]
        assert trace["handoff_details"] == [{"assignment_mode": "automatic"}]
    finally:
        await _swap_allocation_mode(previous)
        await _take_out_of_the_pool(job_id)


# ── create = handoff: one handoff ranking, never a pre-Champion one ──────────


async def test_create_job_ranks_only_as_the_handoff(
    app_client: AsyncClient, app_auth_headers: dict, monkeypatch
):
    """Od 04.10.2026 utworzenie = przekazanie do searchu: Champion jest w tym
    samym żądaniu, więc jedyna migawka ma źródło ``handoff``."""
    from sqlalchemy import select
    from app.models.proposal_snapshot import ProposalSnapshot
    from app.services import canonical_fit, embedding_service

    async def _empty(*_a, **_k):
        return []

    async def _noop(*_a, **_k):
        return None

    monkeypatch.setattr(embedding_service, "search_candidates_semantic", _empty)
    monkeypatch.setattr(embedding_service, "embed_job", _noop)
    monkeypatch.setattr(canonical_fit, "score_candidates", _empty)

    client_id = await _seed_client()
    resp = await app_client.post(
        "/api/jobs",
        headers=app_auth_headers,
        json=await complete_job_payload(
            client_id, title=f"NoSnap-{uuid.uuid4().hex[:6]}"
        ),
    )
    assert resp.status_code == 201, resp.text
    job_id = resp.json()["id"]

    async with AsyncSessionLocal() as db:
        sources = (
            await db.scalars(
                select(ProposalSnapshot.source).where(ProposalSnapshot.job_id == job_id)
            )
        ).all()
    assert list(sources) == ["handoff"]
    assert resp.json()["snapshot_id"] is not None


# ── Champion edit invalidates cached scores ──────────────────────────────────


async def test_champion_edit_marks_cached_scores_stale(
    app_client: AsyncClient, app_auth_headers: dict
):
    from sqlalchemy import select
    from app.models.match_score import CandidateJobMatchScore

    job_id = await _seed_job(champion=None)
    candidate_id = await _seed_candidate()
    async with AsyncSessionLocal() as db:
        db.add(
            CandidateJobMatchScore(
                candidate_id=candidate_id,
                job_id=job_id,
                profile_id=0,
                total_score=55.0,
                breakdown={},
                scoring_algorithm_version="test",
                stale=False,
            )
        )
        await db.commit()

    resp = await app_client.put(
        f"/api/jobs/{job_id}/champion-profile",
        headers=app_auth_headers,
        json=_READY_CHAMPION,
    )
    assert resp.status_code == 200, resp.text

    async with AsyncSessionLocal() as db:
        row = await db.scalar(
            select(CandidateJobMatchScore).where(
                CandidateJobMatchScore.job_id == job_id,
                CandidateJobMatchScore.candidate_id == candidate_id,
            )
        )
        assert row.stale is True
