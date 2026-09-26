"""Automatyczny pełny przegląd bazy (21.09.2026) — prawdziwy Postgres.

Kontrakty:

- okno nocne i „ta noc" liczą się w ``BUSINESS_TZ``;
- sygnałem jest zdarzenie rekrutacji nowsze niż ostatni przegląd automatyczny,
  najwyżej jeden przegląd na rekrutację na noc, ten sam odcisk = pominięcie;
- automat ustępuje przeglądom ręcznym, ma nocny sufit, a wywrotka jednej
  rekrutacji nie blokuje następnej;
- przegląd automatyczny nie zajmuje slotu autora, nie jest chroniony przez
  retencję i czyta go każdy, kto przechodzi bramkę rekrutacji — także osoba
  z własnym profilem punktacji; cudzy RĘCZNY przegląd zostaje prywatny;
- po zakończeniu top-K trafia do skrzynki „Propozycje" z dowodami bez tekstu
  z CV; awaria publikacji nie psuje przeglądu i jest domykana później;
- wyłącznik OFF = pętla nie robi nic.

Baza testowa jest wspólna i nieczyszczona: asercje dotyczą własnych wierszy,
a globalne sondy (`_search_busy`, `_started_since`) są podstawiane.
"""

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from httpx import AsyncClient
from sqlalchemy import select

import app.models  # noqa: F401
from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.core.security import create_access_token, hash_password
from app.models.activity import Activity
from app.models.candidate import Candidate
from app.models.candidate_auto_match import CandidateMatchOutbox
from app.models.candidate_search_run import CandidateSearchResult, CandidateSearchRun
from app.models.client import Client
from app.models.job import Job, JobStatus
from app.models.job_proposal import JobProposal
from app.models.scoring_weight_profile import ScoringWeightProfile
from app.models.user import User, UserRole
from app.services import auto_full_review as afr
from app.services import candidate_search_store as store
from app.tasks import candidate_search_retention as retention


def _at(hour: int) -> datetime:
    """Chwila o danej godzinie LOKALNEJ (Europe/Warsaw), dziś."""
    from zoneinfo import ZoneInfo

    local = datetime.now(ZoneInfo(settings.BUSINESS_TZ)).replace(
        hour=hour, minute=30, second=0, microsecond=0
    )
    return local.astimezone(timezone.utc)


async def _user(role: UserRole = UserRole.recruiter) -> tuple[int, dict[str, str]]:
    tag = uuid.uuid4().hex[:8]
    async with AsyncSessionLocal() as db:
        user = User(
            email=f"afr-{role.value}-{tag}@example.com",
            password_hash=hash_password(f"T3st_{tag}!Review"),
            name=f"AFR {role.value}",
            role=role,
            is_active=True,
        )
        db.add(user)
        await db.commit()
        return user.id, {
            "Authorization": f"Bearer {create_access_token(user.id, role.value)}"
        }


async def _job(*, owner_id: int | None, event: bool = True, people: int = 0) -> dict:
    tag = uuid.uuid4().hex[:8]
    async with AsyncSessionLocal() as db:
        client = Client(name=f"AFR client {tag}")
        db.add(client)
        await db.flush()
        job = Job(
            title=f"AFR job {tag}",
            client_id=client.id,
            status=JobStatus.published,
            recruiter_id=owner_id,
        )
        candidates = [
            Candidate(name="Przegląd", lastname=f"{i}-{tag}") for i in range(people)
        ]
        db.add_all([job, *candidates])
        await db.flush()
        if event:
            db.add(
                CandidateMatchOutbox(
                    job_id=job.id, trigger="job_publish", status="skipped"
                )
            )
        await db.commit()
        return {
            "job_id": job.id,
            "client_id": client.id,
            "candidate_ids": [c.id for c in candidates],
        }


async def _auto_runs(job_id: int) -> list[CandidateSearchRun]:
    async with AsyncSessionLocal() as db:
        return list(
            (
                await db.scalars(
                    select(CandidateSearchRun).where(
                        CandidateSearchRun.job_id == job_id,
                        store.auto_origin_clause(),
                    )
                )
            ).all()
        )


async def _finish_all(job_id: int, state: str = "failed") -> None:
    """Nie zostawiaj aktywnych przeglądów we wspólnej bazie testowej."""
    async with AsyncSessionLocal() as db:
        for run in (
            await db.scalars(
                select(CandidateSearchRun).where(
                    CandidateSearchRun.job_id == job_id,
                    CandidateSearchRun.state.in_(store.ACTIVE_STATES),
                )
            )
        ).all():
            run.state = state
            run.completed_at = datetime.now(timezone.utc)
        await db.commit()


def _open_gates(monkeypatch, *, busy: bool = False, started: int = 0) -> None:
    async def _busy(db):
        return busy

    async def _started(db, since):
        return started

    monkeypatch.setattr(afr, "_search_busy", _busy)
    monkeypatch.setattr(afr, "_started_since", _started)
    afr._skipped_tonight.clear()


# ── okno ────────────────────────────────────────────────────────────────────


def test_window_is_half_open_in_business_timezone(monkeypatch):
    monkeypatch.setattr(settings, "AUTO_FULL_REVIEW_WINDOW_START_HOUR", 1)
    monkeypatch.setattr(settings, "AUTO_FULL_REVIEW_WINDOW_END_HOUR", 5)
    assert afr.in_window(_at(1)) and afr.in_window(_at(4))
    assert not afr.in_window(_at(0)) and not afr.in_window(_at(5))
    assert not afr.in_window(_at(14))
    # „Ta noc" zaczyna się o 01:00 lokalnie — także oglądana o 04:30.
    start = afr.night_start(_at(4))
    assert start <= _at(4) and _at(4) - start < timedelta(hours=4)
    # Równe godziny = okno zamknięte (wyłącznik bez deployu).
    monkeypatch.setattr(settings, "AUTO_FULL_REVIEW_WINDOW_END_HOUR", 1)
    assert not afr.in_window(_at(1))


# ── wybór i start ───────────────────────────────────────────────────────────


async def test_event_makes_the_job_due_once_per_night():
    owner_id, _ = await _user()
    world = await _job(owner_id=owner_id)
    quiet = await _job(owner_id=owner_id, event=False)
    try:
        async with AsyncSessionLocal() as db:
            due = await afr.pending_job_ids(db, now=_at(2), limit=10_000)
            assert world["job_id"] in due
            # Bez zdarzenia (publikacja / istotna zmiana) nie ma przeglądu.
            assert quiet["job_id"] not in due
            run_id, reason = await afr.start_for_job(db, world["job_id"])
            assert reason == "started" and run_id
            await db.commit()
        [run] = await _auto_runs(world["job_id"])
        assert run.created_by == owner_id
        assert run.version_trace["origin"] == "auto"
        assert run.state == "queued"
        async with AsyncSessionLocal() as db:
            # Druga próba tej samej nocy: rekrutacja nie jest już należna…
            assert world["job_id"] not in await afr.pending_job_ids(
                db, now=_at(2), limit=10_000
            )
            # …a ten sam odcisk requestu i tak by ją pominął.
            assert await afr.start_for_job(db, world["job_id"]) == (None, "unchanged")
    finally:
        await _finish_all(world["job_id"])


async def test_review_memory_survives_retention_of_the_run():
    """Runda 6 audytu: retencja kasuje przegląd automatyczny po 2 dniach, a
    zdarzenie żyje 14. Wpis „Praca w tle” pamięta start i odcisk — bez niego
    rekrutacja wracała do kolejki co 2 noce."""
    owner_id, _ = await _user()
    world = await _job(owner_id=owner_id)
    async with AsyncSessionLocal() as db:
        db.add(
            Activity(
                entity_type=afr.ACTIVITY_ENTITY,
                entity_id=world["job_id"],
                action="auto_full_review_finished",
                details={
                    "run_id": "purged-run",
                    "state": "complete",
                    "run_created_at": (
                        datetime.now(timezone.utc) + timedelta(minutes=5)
                    ).isoformat(),
                    "fingerprint": "odcisk-sprzed-retencji",
                },
            )
        )
        await db.commit()
    async with AsyncSessionLocal() as db:
        assert world["job_id"] not in await afr.pending_job_ids(
            db, now=_at(2) + timedelta(days=3), limit=10_000
        )
        assert (
            await afr._last_successful_fingerprint(db, world["job_id"])
            == "odcisk-sprzed-retencji"
        )


async def test_failed_auto_run_does_not_close_the_event():
    """Przegląd, który się wywrócił, nie zamyka zdarzenia: następna noc
    próbuje ponownie (tej nocy chroni ``ran_tonight``)."""
    owner_id, _ = await _user()
    world = await _job(owner_id=owner_id)
    async with AsyncSessionLocal() as db:
        run_id, reason = await afr.start_for_job(db, world["job_id"])
        assert reason == "started"
        await db.commit()
    await _finish_all(world["job_id"], state="failed")
    async with AsyncSessionLocal() as db:
        assert world["job_id"] in await afr.pending_job_ids(
            db, now=_at(2) + timedelta(days=1), limit=10_000
        )


async def test_unchanged_request_closes_the_event(monkeypatch):
    """Runda 7 (A6): zdarzenie, które nie zmieniło requestu (np. „Klient
    milczy → Szukamy”), nie zapisywało pamięci przeglądu — rekrutacja wisiała
    w kolejce przez całe 14 dni i co noc zajmowała w niej miejsce."""
    owner_id, _ = await _user()
    world = await _job(owner_id=owner_id)
    async with AsyncSessionLocal() as db:
        run_id, reason = await afr.start_for_job(db, world["job_id"])
        assert reason == "started"
        await db.commit()
    async with AsyncSessionLocal() as db:
        run = await db.get(CandidateSearchRun, run_id)
        run.state = "complete"
        run.completed_at = datetime.now(timezone.utc)
        run.created_at = datetime.now(timezone.utc) - timedelta(days=2)
        await db.commit()
    async with AsyncSessionLocal() as db:
        # Zdarzenie jest nowsze niż przegląd sprzed dwóch dni → należna.
        assert world["job_id"] in await afr.pending_job_ids(
            db, now=_at(2), limit=10_000
        )

    async def _only_mine(db, *, now, limit=50):
        return [world["job_id"]]

    monkeypatch.setattr(afr, "pending_job_ids", _only_mine)
    monkeypatch.setattr(settings, "AUTO_FULL_REVIEW_ENABLED", True)
    monkeypatch.setattr(settings, "AUTO_FULL_REVIEW_WINDOW_START_HOUR", 1)
    monkeypatch.setattr(settings, "AUTO_FULL_REVIEW_WINDOW_END_HOUR", 5)
    _open_gates(monkeypatch)
    assert (await afr.tick(now=_at(2)))["skipped"] == "nothing_due"
    monkeypatch.undo()
    async with AsyncSessionLocal() as db:
        assert world["job_id"] not in await afr.pending_job_ids(
            db, now=_at(2) + timedelta(days=1), limit=10_000
        )
        # Wpis pamięci nie trafia do „Pracy w tle” i nie udaje odcisku.
        memo = (
            await db.scalars(
                select(Activity).where(
                    Activity.entity_type == afr.ACTIVITY_ENTITY,
                    Activity.entity_id == world["job_id"],
                    Activity.action == afr.UNCHANGED_ACTION,
                )
            )
        ).all()
        assert len(memo) == 1


async def test_job_without_owner_is_skipped():
    world = await _job(owner_id=None)
    async with AsyncSessionLocal() as db:
        assert world["job_id"] not in await afr.pending_job_ids(
            db, now=_at(2), limit=10_000
        )
        assert await afr.start_for_job(db, world["job_id"]) == (None, "no_owner")


async def test_tick_does_nothing_when_disabled_or_outside_the_window(monkeypatch):
    owner_id, _ = await _user()
    world = await _job(owner_id=owner_id)
    _open_gates(monkeypatch)
    monkeypatch.setattr(settings, "AUTO_FULL_REVIEW_ENABLED", False)
    assert await afr.tick(now=_at(2)) == {"skipped": "disabled"}
    monkeypatch.setattr(settings, "AUTO_FULL_REVIEW_ENABLED", True)
    assert (await afr.tick(now=_at(14)))["skipped"] == "outside_window"
    assert await _auto_runs(world["job_id"]) == []


async def test_tick_yields_to_manual_runs_and_respects_the_night_cap(monkeypatch):
    owner_id, _ = await _user()
    world = await _job(owner_id=owner_id)

    async def _only_mine(db, *, now, limit=50):
        return [world["job_id"]]

    monkeypatch.setattr(afr, "pending_job_ids", _only_mine)
    monkeypatch.setattr(settings, "AUTO_FULL_REVIEW_ENABLED", True)

    _open_gates(monkeypatch, busy=True)
    assert (await afr.tick(now=_at(2)))["skipped"] == "search_active"

    _open_gates(monkeypatch, started=3)
    monkeypatch.setattr(settings, "AUTO_FULL_REVIEW_MAX_PER_NIGHT", 3)
    assert (await afr.tick(now=_at(2)))["skipped"] == "night_cap"
    assert await _auto_runs(world["job_id"]) == []


async def test_real_busy_probe_sees_a_queued_manual_run():
    owner_id, _ = await _user()
    world = await _job(owner_id=owner_id, event=False)
    async with AsyncSessionLocal() as db:
        db.add(
            CandidateSearchRun(
                id=str(uuid.uuid4()),
                created_by=owner_id,
                client_id=world["client_id"],
                job_id=world["job_id"],
                state="queued",
                request_fingerprint="m" * 64,
                request_context={},
                version_trace={},
                population_size=0,
                metrics={},
            )
        )
        await db.commit()
    try:
        async with AsyncSessionLocal() as db:
            assert await afr._search_busy(db) is True
    finally:
        await _finish_all(world["job_id"])


async def test_one_broken_job_does_not_block_the_next(monkeypatch):
    owner_id, _ = await _user()
    broken = await _job(owner_id=owner_id)
    healthy = await _job(owner_id=owner_id)

    async def _both(db, *, now, limit=50):
        return [broken["job_id"], healthy["job_id"]]

    real_start = afr.start_for_job

    async def _start(db, job_id):
        if job_id == broken["job_id"]:
            raise RuntimeError("boom")
        return await real_start(db, job_id)

    monkeypatch.setattr(afr, "pending_job_ids", _both)
    monkeypatch.setattr(afr, "start_for_job", _start)
    monkeypatch.setattr(settings, "AUTO_FULL_REVIEW_ENABLED", True)
    _open_gates(monkeypatch)
    try:
        outcome = await afr.tick(now=_at(2))
        assert outcome["job_id"] == healthy["job_id"]
        assert await _auto_runs(broken["job_id"]) == []
        assert len(await _auto_runs(healthy["job_id"])) == 1
    finally:
        await _finish_all(healthy["job_id"])


# ── sloty autora ────────────────────────────────────────────────────────────


async def test_auto_runs_never_take_the_authors_two_slots(app_client: AsyncClient):
    owner_id, headers = await _user()
    worlds = [await _job(owner_id=owner_id) for _ in range(3)]
    try:
        async with AsyncSessionLocal() as db:
            for world in worlds[:2]:
                run_id, _ = await afr.start_for_job(db, world["job_id"])
                assert run_id
            await db.commit()
        # Dwa AKTYWNE przeglądy automatyczne „na koncie" autora — a ręczny
        # start nadal przechodzi (przed zmianą: 409 „Dwa wyszukiwania trwają").
        response = await app_client.post(
            "/api/candidate-search/runs",
            json={"job_id": worlds[2]["job_id"]},
            headers=headers,
        )
        assert response.status_code == 202, response.text
        # Nieudany przegląd automatyczny też niczego nie blokuje.
        await _finish_all(worlds[0]["job_id"], state="failed")
        again = await app_client.post(
            "/api/candidate-search/runs",
            json={"job_id": worlds[1]["job_id"]},
            headers=headers,
        )
        assert again.status_code == 202, again.text
    finally:
        for world in worlds:
            await _finish_all(world["job_id"])


# ── odczyt przez zespół ─────────────────────────────────────────────────────


async def test_teammate_reads_the_auto_run_but_not_a_foreign_manual_one(
    app_client: AsyncClient,
):
    owner_id, owner_headers = await _user()
    mate_id, mate_headers = await _user()
    world = await _job(owner_id=owner_id)
    try:
        async with AsyncSessionLocal() as db:
            auto_id, _ = await afr.start_for_job(db, world["job_id"])
            # Osobisty profil punktacji oglądającego nie może unieważnić
            # wspólnego wyniku (przegląd policzono profilem bez użytkownika).
            db.add(
                ScoringWeightProfile(
                    name=f"afr-{uuid.uuid4().hex[:8]}",
                    user_id=mate_id,
                    weights={
                        "semantic": 10,
                        "skills": 60,
                        "salary": 10,
                        "location": 10,
                        "availability": 10,
                    },
                    active=True,
                )
            )
            await db.commit()
        manual = await app_client.post(
            "/api/candidate-search/runs",
            json={"job_id": world["job_id"]},
            headers=owner_headers,
        )
        assert manual.status_code == 202, manual.text
        manual_id = manual.json()["run_id"]

        shared = await app_client.get(
            f"/api/candidate-search/runs/{auto_id}", headers=mate_headers
        )
        assert shared.status_code == 200, shared.text
        assert shared.json()["state"] == "queued"
        private = await app_client.get(
            f"/api/candidate-search/runs/{manual_id}", headers=mate_headers
        )
        assert private.status_code == 404, private.text
        latest = await app_client.get(
            f"/api/candidate-search/jobs/{world['job_id']}/latest-run",
            headers=mate_headers,
        )
        assert latest.status_code == 200
    finally:
        await _finish_all(world["job_id"])


async def test_auto_run_still_follows_the_job_gate(app_client: AsyncClient):
    from app.models.section_permission import UserSectionOverride

    owner_id, _ = await _user()
    world = await _job(owner_id=owner_id)
    outsider_id, outsider_headers = await _user()
    try:
        async with AsyncSessionLocal() as db:
            auto_id, _ = await afr.start_for_job(db, world["job_id"])
            db.add(
                UserSectionOverride(
                    user_id=outsider_id, section="pipeline", access="none"
                )
            )
            await db.commit()
        response = await app_client.get(
            f"/api/candidate-search/runs/{auto_id}", headers=outsider_headers
        )
        assert response.status_code == 403, response.text
    finally:
        await _finish_all(world["job_id"])


# ── retencja ────────────────────────────────────────────────────────────────


async def test_retention_never_protects_an_auto_run():
    now = datetime.now(timezone.utc)
    owner_id, _ = await _user()
    world = await _job(owner_id=owner_id, event=False)
    old = now - timedelta(days=10)

    def _run(origin: str | None, completed_at: datetime) -> CandidateSearchRun:
        return CandidateSearchRun(
            id=str(uuid.uuid4()),
            created_by=owner_id,
            client_id=world["client_id"],
            job_id=world["job_id"],
            state="complete",
            request_fingerprint="r" * 64,
            request_context={},
            version_trace={"origin": origin} if origin else {},
            population_size=0,
            metrics={},
            completed_at=completed_at,
            created_at=completed_at,
        )

    manual = _run(None, old)
    # Automat NOWSZY niż ręczny — gdyby wchodził do rankingu ochrony, zająłby
    # miejsce nr 1 i zdjął ochronę z ręcznego przeglądu właściciela.
    auto = _run("auto", old + timedelta(hours=1))
    async with AsyncSessionLocal() as db:
        db.add_all([manual, auto])
        await db.commit()
        expired = await retention.expired_run_ids(
            db,
            cutoff=now - timedelta(days=7),
            limit=100_000,
            protect_after=now - timedelta(days=90),
        )
    assert auto.id in expired
    assert manual.id not in expired
    async with AsyncSessionLocal() as db:
        await retention.purge_run(db, auto.id)
        await retention.purge_run(db, manual.id)


# ── publikacja propozycji ───────────────────────────────────────────────────


def _result(run_id, cid, score, *, met=True, measurement="measured", eligible=True):
    return CandidateSearchResult(
        run_id=run_id,
        candidate_id=cid,
        candidate_version="v",
        state="evaluated",
        eligible=eligible,
        fit_score=score,
        measurement=measurement,
        evidence={
            "requirements": [
                {
                    "id": "req-1",
                    "level": "must",
                    "status": "met" if met else "unknown",
                    "any_of": ["Python"],
                    "candidate_evidence": "cytat z CV, który nie może wyjść",
                    "usage_context": "projekt u klienta X",
                }
            ],
            "breakdown": {"total": score},
        },
        exclusion_reasons=[],
    )


async def _finished_auto_run(world: dict, owner_id: int) -> str:
    run_id = str(uuid.uuid4())
    good, below, gap, unmeasured, hidden = world["candidate_ids"]
    async with AsyncSessionLocal() as db:
        db.add(
            CandidateSearchRun(
                id=run_id,
                created_by=owner_id,
                client_id=world["client_id"],
                job_id=world["job_id"],
                state="complete",
                request_fingerprint="p" * 64,
                request_context={},
                version_trace={"origin": "auto"},
                population_size=5,
                metrics={},
                completed_at=datetime.now(timezone.utc),
            )
        )
        await db.flush()
        db.add_all(
            [
                _result(run_id, good, 91),
                _result(run_id, below, 55),
                _result(run_id, gap, 88, met=False),
                _result(run_id, unmeasured, 95, measurement="unavailable"),
                _result(run_id, hidden, 99, eligible=False),
            ]
        )
        await db.commit()
    return run_id


async def _proposals(job_id: int) -> list[JobProposal]:
    async with AsyncSessionLocal() as db:
        return list(
            (
                await db.scalars(
                    select(JobProposal).where(JobProposal.job_id == job_id)
                )
            ).all()
        )


async def test_finished_auto_run_publishes_only_good_matches(monkeypatch):
    monkeypatch.setattr(settings, "AUTO_FULL_REVIEW_MIN_SCORE", 70.0)
    monkeypatch.setattr(settings, "AUTO_MATCH_REQUIRE_MUST", True)
    owner_id, _ = await _user()
    world = await _job(owner_id=owner_id, event=False, people=5)
    run_id = await _finished_auto_run(world, owner_id)

    async with AsyncSessionLocal() as db:
        await afr.publish_on_finish(db, run_id, eligible=4)
        await db.commit()

    [proposal] = await _proposals(world["job_id"])
    assert proposal.candidate_id == world["candidate_ids"][0]
    assert (proposal.source, proposal.status) == ("full_base", "proposed")
    assert proposal.run_id == run_id and proposal.cv_revision
    assert float(proposal.score) == 91.0
    flat = str(proposal.evidence)
    assert "Python" in flat
    assert "cytat z CV" not in flat and "klienta X" not in flat
    # Nikt nie trafił do pipeline'u.
    from app.models.recruitment_pipeline import CandidateStage

    async with AsyncSessionLocal() as db:
        assert (
            await db.scalar(
                select(CandidateStage.id).where(
                    CandidateStage.job_id == world["job_id"]
                )
            )
        ) is None
        run = await db.get(CandidateSearchRun, run_id)
        assert run.metrics[afr.PROPOSALS_METRIC] == 1
        [event] = (
            await db.scalars(
                select(Activity).where(
                    Activity.entity_type == afr.ACTIVITY_ENTITY,
                    Activity.entity_id == world["job_id"],
                )
            )
        ).all()
        assert event.action == "auto_full_review_finished"
        assert event.details["proposals"] == 1 and event.details["run_id"] == run_id


async def test_top_k_caps_the_number_of_proposals(monkeypatch):
    monkeypatch.setattr(settings, "AUTO_FULL_REVIEW_TOP_K", 2)
    monkeypatch.setattr(settings, "AUTO_FULL_REVIEW_MIN_SCORE", 70.0)
    owner_id, _ = await _user()
    world = await _job(owner_id=owner_id, event=False, people=5)
    run_id = str(uuid.uuid4())
    async with AsyncSessionLocal() as db:
        db.add(
            CandidateSearchRun(
                id=run_id,
                created_by=owner_id,
                client_id=world["client_id"],
                job_id=world["job_id"],
                state="complete",
                request_fingerprint="k" * 64,
                request_context={},
                version_trace={"origin": "auto"},
                population_size=5,
                metrics={},
                completed_at=datetime.now(timezone.utc),
            )
        )
        await db.flush()
        db.add_all(
            [
                _result(run_id, cid, 80 + index)
                for index, cid in enumerate(world["candidate_ids"])
            ]
        )
        await db.commit()
        await afr.publish_on_finish(db, run_id, eligible=5)
        await db.commit()
    rows = await _proposals(world["job_id"])
    assert sorted(float(r.score) for r in rows) == [83.0, 84.0]


async def test_manual_run_publishes_nothing():
    owner_id, _ = await _user()
    world = await _job(owner_id=owner_id, event=False, people=5)
    run_id = await _finished_auto_run(world, owner_id)
    async with AsyncSessionLocal() as db:
        run = await db.get(CandidateSearchRun, run_id)
        run.version_trace = {}
        await db.commit()
        await afr.publish_on_finish(db, run_id, eligible=4)
        await db.commit()
    assert await _proposals(world["job_id"]) == []


async def test_publish_failure_never_raises_and_is_reconciled_later(monkeypatch):
    monkeypatch.setattr(settings, "AUTO_FULL_REVIEW_MIN_SCORE", 70.0)
    owner_id, _ = await _user()
    world = await _job(owner_id=owner_id, event=False, people=5)
    run_id = await _finished_auto_run(world, owner_id)
    real = afr.publish_run_proposals

    async def _boom(db, run):
        raise RuntimeError("storage down")

    monkeypatch.setattr(afr, "publish_run_proposals", _boom)
    async with AsyncSessionLocal() as db:
        await afr.publish_on_finish(db, run_id, eligible=4)  # nie rzuca
        await db.commit()  # sesja nadal używalna — przegląd by się zakończył
    assert await _proposals(world["job_id"]) == []

    monkeypatch.setattr(afr, "publish_run_proposals", real)
    async with AsyncSessionLocal() as db:
        assert await afr.reconcile_unpublished(db, now=datetime.now(timezone.utc)) >= 1
        await db.commit()
    assert len(await _proposals(world["job_id"])) == 1
    async with AsyncSessionLocal() as db:
        # Drugi bieg niczego nie dubluje (znacznik w metrics).
        before = len(await _proposals(world["job_id"]))
        await afr.reconcile_unpublished(db, now=datetime.now(timezone.utc))
        await db.commit()
    assert len(await _proposals(world["job_id"])) == before


async def test_auto_run_does_not_ring_the_owner():
    from app.models.notification import Notification
    from app.services.candidate_search_worker import _notify_search_finished

    owner_id, _ = await _user()
    world = await _job(owner_id=owner_id, event=False, people=5)
    run_id = await _finished_auto_run(world, owner_id)
    async with AsyncSessionLocal() as db:
        await _notify_search_finished(db, run_id, eligible=4, failed=False)
        await db.commit()
        assert (
            await db.scalar(
                select(Notification.id).where(Notification.user_id == owner_id)
            )
        ) is None


def test_loop_is_registered_with_a_heartbeat():
    from pathlib import Path

    backend = Path(__file__).resolve().parents[1]
    main = (backend / "app" / "main.py").read_text(encoding="utf-8")
    task = (backend / "app" / "tasks" / "auto_full_review.py").read_text(
        encoding="utf-8"
    )
    assert '"auto_full_review": asyncio.create_task(auto_full_review_loop())' in main
    assert 'loop_heartbeat.register(\n        "auto_full_review"' in task


@pytest.mark.parametrize("field", ["rate_budget_hourly", "salary_max"])
def test_budget_fields_are_part_of_job_change_detection(field):
    from app.api import jobs

    assert field in jobs._AUTO_REVIEW_EXTRA_FIELDS


# ── Runda 6 audytu: przegląd bez wektora, rekrutacja poza pracą ──────────────


async def test_run_without_query_vector_is_a_failure_not_unchanged(monkeypatch):
    """A6-4: `vector=None` kończy przegląd jako `partial` bez żadnego pomiaru.
    Liczony był jak sukces, a jego odcisk dawał następnej nocy `unchanged`."""
    from app.services import automation_failures as failures

    calls: list[str] = []

    async def failure(kind, code, *, job_id=None):
        calls.append(f"fail:{code}")

    async def success(kind):
        calls.append("ok")

    monkeypatch.setattr(failures, "record_failure", failure)
    monkeypatch.setattr(failures, "record_success", success)
    owner_id, _ = await _user()
    world = await _job(owner_id=owner_id, event=True, people=2)
    run_id = str(uuid.uuid4())
    async with AsyncSessionLocal() as db:
        db.add(
            CandidateSearchRun(
                id=run_id,
                created_by=owner_id,
                client_id=world["client_id"],
                job_id=world["job_id"],
                state="partial",
                request_fingerprint="b" * 64,
                request_context={},
                version_trace={"origin": "auto"},
                population_size=2,
                metrics={},
                completed_at=datetime.now(timezone.utc),
            )
        )
        await db.flush()
        db.add_all(
            [
                _result(run_id, cid, 0, measurement="unavailable")
                for cid in world["candidate_ids"]
            ]
        )
        await db.commit()
        await afr.publish_on_finish(db, run_id, eligible=2)
        await db.commit()

    assert calls == [f"fail:{failures.NO_QUERY_VECTOR}"]
    assert await _proposals(world["job_id"]) == []
    async with AsyncSessionLocal() as db:
        run = await db.get(CandidateSearchRun, run_id)
        assert run.metrics[afr.SEMANTIC_BLIND_METRIC] is True
        assert await afr._last_successful_fingerprint(db, world["job_id"]) is None
        actions = (
            await db.scalars(
                select(Activity.action).where(
                    Activity.entity_type == afr.ACTIVITY_ENTITY,
                    Activity.entity_id == world["job_id"],
                )
            )
        ).all()
        assert actions == ["auto_full_review_failed"]
        # Następna noc bierze rekrutację ponownie.
        assert world["job_id"] in await afr.pending_job_ids(
            db, now=_at(2) + timedelta(days=1), limit=10_000
        )


@pytest.mark.parametrize(
    "status,work_state",
    [(JobStatus.published, "client_silent"), (JobStatus.closed, "to_review")],
)
async def test_no_proposals_for_a_job_that_is_not_in_work(
    monkeypatch, status, work_state
):
    """A6-5: zaległa publikacja nie dosypuje propozycji rekrutacji zamkniętej
    ani takiej, nad którą nikt nie pracuje."""
    monkeypatch.setattr(settings, "AUTO_FULL_REVIEW_MIN_SCORE", 70.0)
    owner_id, _ = await _user()
    world = await _job(owner_id=owner_id, event=False, people=5)
    run_id = await _finished_auto_run(world, owner_id)
    async with AsyncSessionLocal() as db:
        job = await db.get(Job, world["job_id"])
        job.status = status
        job.work_state = work_state
        await db.commit()
    async with AsyncSessionLocal() as db:
        await afr.reconcile_unpublished(db, now=datetime.now(timezone.utc))
        await db.commit()
        run = await db.get(CandidateSearchRun, run_id)
        await afr.publish_run_proposals(db, run)
        await db.commit()
    assert await _proposals(world["job_id"]) == []
