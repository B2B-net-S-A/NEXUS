"""Skrzynka „Propozycje" rekrutacji (migracja 0333) — serwis, API, RODO, lustro DDL.

Prawdziwy Postgres i prawdziwa autoryzacja. Baza testowa jest wspólna
i nieczyszczona, więc każdy test zakłada własnego klienta, rekrutację i osoby,
a asercje dotyczą wyłącznie tych wierszy.
"""

import ast
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

import pytest
from httpx import AsyncClient
from sqlalchemy import select

import app.models  # noqa: F401  (zarejestruj wszystkie mappery)
from app.core.database import AsyncSessionLocal
from app.core.security import create_access_token, hash_password
from app.models.application_screening import ApplicationScreening
from app.models.candidate import Candidate, CandidateStatus
from app.models.client import Client
from app.models.job import Job, JobStatus
from app.models.job_proposal import JobProposal
from app.models.recruitment_pipeline import CandidateStage, PipelineStage
from app.models.section_permission import UserSectionOverride
from app.models.user import User, UserRole
from app.services import job_proposals as proposals

_BACKEND = Path(__file__).resolve().parents[1]


async def _user(
    role: UserRole, *, pipeline: str | None = None
) -> tuple[int, dict[str, str]]:
    tag = uuid.uuid4().hex[:8]
    async with AsyncSessionLocal() as db:
        user = User(
            email=f"proposals-{role.value}-{tag}@example.com",
            password_hash=hash_password(f"T3st_{tag}!Proposals"),
            name=f"Proposals {role.value}",
            role=role,
            is_active=True,
        )
        db.add(user)
        await db.flush()
        if pipeline is not None:
            db.add(
                UserSectionOverride(
                    user_id=user.id, section="pipeline", access=pipeline
                )
            )
        await db.commit()
        return user.id, {
            "Authorization": f"Bearer {create_access_token(user.id, role.value)}"
        }


async def _world(*, people: int = 3, recruiter_id: int | None = None) -> dict:
    tag = uuid.uuid4().hex[:8]
    async with AsyncSessionLocal() as db:
        client = Client(name=f"Proposals client {tag}")
        db.add(client)
        await db.flush()
        job = Job(
            title=f"Proposals job {tag}",
            client_id=client.id,
            status=JobStatus.published,
            recruiter_id=recruiter_id,
        )
        candidates = [
            Candidate(
                name="Propozycja",
                lastname=f"{index}-{tag}",
                email=f"proposal-{index}-{tag}@example.com",
                expected_rate_hourly=Decimal("150"),
                city="Gdańsk",
            )
            for index in range(people)
        ]
        db.add_all([job, *candidates])
        await db.commit()
        return {
            "job_id": job.id,
            "client_id": client.id,
            "candidate_ids": [c.id for c in candidates],
        }


async def _statuses(job_id: int) -> dict[tuple[int, str], str]:
    async with AsyncSessionLocal() as db:
        rows = await db.execute(
            select(
                JobProposal.candidate_id, JobProposal.source, JobProposal.status
            ).where(JobProposal.job_id == job_id)
        )
        return {(cid, source): status for cid, source, status in rows.all()}


# ── Serwis ──────────────────────────────────────────────────────────────────


async def test_upsert_is_idempotent_and_keeps_first_seen():
    world = await _world(people=2)
    first, second = world["candidate_ids"]
    async with AsyncSessionLocal() as db:
        assert (
            await proposals.upsert_proposals(
                db,
                world["job_id"],
                [
                    {"candidate_id": first, "score": 71.256},
                    {"candidate_id": second, "score": None},
                    # Duplikat pary w jednej paczce nie wywraca INSERT-u.
                    {"candidate_id": first, "score": 80},
                ],
                "full_base",
                run_id="run-a",
            )
            == 2
        )
        await db.commit()
    async with AsyncSessionLocal() as db:
        before = (
            (
                await db.execute(
                    select(JobProposal).where(JobProposal.job_id == world["job_id"])
                )
            )
            .scalars()
            .all()
        )
    assert len(before) == 2
    by_candidate = {p.candidate_id: p for p in before}
    assert by_candidate[first].score == Decimal("80.00")
    assert by_candidate[first].status == "proposed"

    async with AsyncSessionLocal() as db:
        await proposals.upsert_proposals(
            db, world["job_id"], [{"candidate_id": first, "score": 55}], "full_base"
        )
        await db.commit()
    async with AsyncSessionLocal() as db:
        after = (
            (
                await db.execute(
                    select(JobProposal).where(JobProposal.job_id == world["job_id"])
                )
            )
            .scalars()
            .all()
        )
    assert len(after) == 2
    row = next(p for p in after if p.candidate_id == first)
    assert row.score == Decimal("55.00")
    assert row.first_seen_at == by_candidate[first].first_seen_at
    assert row.last_seen_at >= by_candidate[first].last_seen_at
    # Brak `run_id` w kolejnym zapisie nie kasuje poprzedniego.
    assert row.run_id == "run-a"


async def test_unknown_source_is_refused():
    world = await _world(people=1)
    async with AsyncSessionLocal() as db:
        with pytest.raises(ValueError):
            await proposals.upsert_proposals(
                db, world["job_id"], [{"candidate_id": 1}], "guesswork"
            )


async def _pair_state(job_id: int, user_id: int) -> dict[str, list[int]]:
    async with AsyncSessionLocal() as db:
        out = {}
        for status in ("proposed", "dismissed", "added"):
            rows, _ = await proposals.list_for_job(db, job_id=job_id, status=status)
            out[status] = [r.candidate_id for r in rows]
        out["open"] = (await proposals.open_counts_for_jobs(db, [job_id])).get(
            job_id, 0
        )
        return out


async def test_same_cv_revision_never_resurrects_a_dismissed_person():
    user_id, _ = await _user(UserRole.recruiter)
    world = await _world(people=1)
    (gone,) = world["candidate_ids"]
    job_id = world["job_id"]
    rows = [{"candidate_id": gone, "score": 60, "cv_revision": "cv-v1"}]
    async with AsyncSessionLocal() as db:
        await proposals.upsert_proposals(db, job_id, rows, "full_base")
        assert (
            await proposals.dismiss(
                db, job_id=job_id, candidate_id=gone, user_id=user_id
            )
            == 1
        )
        await db.commit()

    async with AsyncSessionLocal() as db:
        # Kolejny przegląd TEJ SAMEJ wersji CV: to samo źródło, nowe źródło,
        # wiersz bez wersji i wersja podana argumentem — nic nie wskrzesza.
        await proposals.upsert_proposals(db, job_id, rows, "full_base")
        await proposals.upsert_proposals(db, job_id, rows, "new_cv")
        await proposals.upsert_proposals(
            db, job_id, [{"candidate_id": gone, "score": 61}], "recommendation"
        )
        await proposals.upsert_proposals(
            db, job_id, [{"candidate_id": gone}], "marketplace", cv_revision="cv-v1"
        )
        await db.commit()

    state = await _pair_state(job_id, user_id)
    assert state == {"proposed": [], "dismissed": [gone], "added": [], "open": 0}
    async with AsyncSessionLocal() as db:
        row = await db.scalar(
            select(JobProposal).where(
                JobProposal.job_id == job_id, JobProposal.source == "full_base"
            )
        )
    assert row.status == "dismissed"
    assert row.dismissed_by == user_id and row.dismissed_at is not None
    # Bez wersji od wołającego stemplujemy tę, dla której policzono propozycję.
    assert row.dismissed_cv_revision == "cv-v1"


async def test_a_new_cv_revision_re_proposes_a_dismissed_person():
    user_id, _ = await _user(UserRole.recruiter)
    world = await _world(people=1)
    (back,) = world["candidate_ids"]
    job_id = world["job_id"]
    async with AsyncSessionLocal() as db:
        await proposals.upsert_proposals(
            db,
            job_id,
            [{"candidate_id": back, "score": 60, "cv_revision": "cv-v1"}],
            "full_base",
        )
        await proposals.upsert_proposals(
            db,
            job_id,
            [{"candidate_id": back, "score": 40, "cv_revision": "cv-v1"}],
            "recommendation",
        )
        await proposals.dismiss(
            db, job_id=job_id, candidate_id=back, user_id=user_id, cv_revision="cv-v1"
        )
        # „Dawno temu" — żeby było widać, że powrót stempluje `first_seen_at`.
        await db.execute(
            JobProposal.__table__.update()
            .where(JobProposal.job_id == job_id)
            .values(first_seen_at=datetime.now(timezone.utc) - timedelta(days=30))
        )
        await db.commit()
    before = await _pair_state(job_id, user_id)
    assert before["dismissed"] == [back] and before["open"] == 0

    async with AsyncSessionLocal() as db:
        await proposals.upsert_proposals(
            db,
            job_id,
            [
                {
                    "candidate_id": back,
                    "score": 77,
                    "cv_revision": "cv-v2",
                    # Producent nie może sam podrobić flagi…
                    "evidence": {"missing_must": ["Kafka"]},
                }
            ],
            "new_cv",
        )
        await db.commit()

    after = await _pair_state(job_id, user_id)
    assert after == {"proposed": [back], "dismissed": [], "added": [], "open": 1}
    async with AsyncSessionLocal() as db:
        rows, _ = await proposals.list_for_job(db, job_id=job_id)
        stored = (
            (await db.execute(select(JobProposal).where(JobProposal.job_id == job_id)))
            .scalars()
            .all()
        )
    (row,) = rows
    assert row.is_new is True
    assert row.score == 77.0
    assert row.evidence == {"missing_must": ["Kafka"], "previously_dismissed": True}
    by_source = {p.source: p for p in stored}
    for source in ("full_base", "recommendation"):
        revived = by_source[source]
        assert revived.status == "proposed"
        assert revived.dismissed_at is None and revived.dismissed_by is None
        assert revived.dismissed_cv_revision is None
        assert revived.evidence == {"previously_dismissed": True}
        assert revived.first_seen_at > datetime.now(timezone.utc) - timedelta(hours=1)

    # Flaga przeżywa kolejny przegląd tego samego źródła.
    async with AsyncSessionLocal() as db:
        await proposals.upsert_proposals(
            db,
            job_id,
            [{"candidate_id": back, "score": 70, "cv_revision": "cv-v2"}],
            "full_base",
        )
        await db.commit()
        kept = await db.scalar(
            select(JobProposal.evidence).where(
                JobProposal.job_id == job_id, JobProposal.source == "full_base"
            )
        )
    assert kept == {"previously_dismissed": True}

    # Ponowne „Pomiń" przy v2 znowu trzyma — aż do v3.
    async with AsyncSessionLocal() as db:
        await proposals.dismiss(
            db, job_id=job_id, candidate_id=back, user_id=user_id, cv_revision="cv-v2"
        )
        await proposals.upsert_proposals(
            db,
            job_id,
            [{"candidate_id": back, "score": 70, "cv_revision": "cv-v2"}],
            "full_base",
        )
        await db.commit()
    assert (await _pair_state(job_id, user_id))["dismissed"] == [back]


async def test_added_is_never_downgraded_even_by_a_new_cv():
    user_id, _ = await _user(UserRole.recruiter)
    world = await _world(people=1)
    (hired,) = world["candidate_ids"]
    job_id = world["job_id"]
    async with AsyncSessionLocal() as db:
        await proposals.upsert_proposals(
            db, job_id, [{"candidate_id": hired, "cv_revision": "cv-v1"}], "full_base"
        )
        assert await proposals.mark_added(db, job_id=job_id, candidate_ids=[hired]) == 1
        await proposals.upsert_proposals(
            db, job_id, [{"candidate_id": hired, "cv_revision": "cv-v2"}], "full_base"
        )
        await proposals.upsert_proposals(
            db, job_id, [{"candidate_id": hired, "cv_revision": "cv-v2"}], "new_cv"
        )
        # „Pomiń" na osobie już dodanej rusza najwyżej świeży wiersz źródła.
        await proposals.dismiss(db, job_id=job_id, candidate_id=hired, user_id=user_id)
        await proposals.upsert_proposals(
            db, job_id, [{"candidate_id": hired, "cv_revision": "cv-v3"}], "new_cv"
        )
        await db.commit()
    assert (await _statuses(job_id))[(hired, "full_base")] == "added"
    state = await _pair_state(job_id, user_id)
    assert state["added"] == [hired]
    assert state["proposed"] == [] and state["open"] == 0


async def test_open_count_is_team_wide_and_matches_the_visible_list():
    world = await _world(people=4)
    job_id = world["job_id"]
    first, second, in_pipeline, blacklisted = world["candidate_ids"]
    async with AsyncSessionLocal() as db:
        await proposals.upsert_proposals(
            db,
            job_id,
            [{"candidate_id": c, "score": 50} for c in world["candidate_ids"]],
            "full_base",
        )
        # Ta sama osoba z dwóch źródeł liczy się RAZ.
        await proposals.upsert_proposals(
            db, job_id, [{"candidate_id": first, "score": 90}], "recommendation"
        )
        db.add(
            CandidateStage(
                candidate_id=in_pipeline,
                job_id=job_id,
                stage=PipelineStage.rejected,
                moved_at=datetime.now(timezone.utc),
            )
        )
        (await db.get(Candidate, blacklisted)).status = CandidateStatus.blacklisted
        await db.commit()

    async with AsyncSessionLocal() as db:
        assert await proposals.open_counts_for_jobs(db, [job_id]) == {job_id: 2}
        assert await proposals.open_counts_for_jobs(db, []) == {}
        rows, total = await proposals.list_for_job(db, job_id=job_id)
    # Plakietka nie obiecuje wierszy, których lista nie pokaże.
    assert total == 2
    assert [r.candidate_id for r in rows] == [first, second]
    assert rows[0].sources == ["full_base", "recommendation"]
    assert rows[0].score == 90.0
    assert all(r.is_new for r in rows)

    # `is_new` to okno 24 h od pierwszego zaproponowania — nic per użytkownik.
    async with AsyncSessionLocal() as db:
        await db.execute(
            JobProposal.__table__.update()
            .where(JobProposal.job_id == job_id, JobProposal.candidate_id == second)
            .values(first_seen_at=datetime.now(timezone.utc) - timedelta(hours=25))
        )
        await db.commit()
        rows, _ = await proposals.list_for_job(db, job_id=job_id)
    assert {r.candidate_id: r.is_new for r in rows} == {first: True, second: False}


def test_evidence_keeps_requirement_names_and_drops_free_text():
    clean = proposals.sanitize_evidence(
        {
            "requirements": [
                {
                    "id": 7,
                    "level": "must",
                    "status": "met",
                    "any_of": ["Python", "  "],
                    "candidate_evidence": "Pracował w Banku X nad systemem Y",
                    "usage_context": "cytat z CV",
                    "matched": ["python 3.11 w projekcie Z"],
                }
            ],
            "missing_must": ["Kafka"],
            "counts": {"must_met": 3, "note": "tekst"},
            "summary": "Jan Kowalski, 10 lat w bankowości",
            "breakdown": {"reason": "wolny tekst"},
            "previously_dismissed": True,
        }
    )
    assert clean == {
        "requirements": [
            {"id": 7, "level": "must", "status": "met", "any_of": ["Python"]}
        ],
        "missing_must": ["Kafka"],
        "counts": {"must_met": 3},
        "previously_dismissed": True,
    }
    # Flaga to wyłącznie literalne `True` — nie dowolna „prawdziwa" wartość.
    assert proposals.sanitize_evidence({"previously_dismissed": "tak"}) is None
    assert proposals.sanitize_evidence({"summary": "sam tekst"}) is None
    assert proposals.sanitize_evidence("tekst") is None


def test_trainee_evidence_keeps_the_employment_only_flag():
    clean = proposals.sanitize_evidence(
        {"trainee": {"user_id": 5, "note": " Szuka ", "employment_only": True}}
    )
    assert clean == {
        "trainee": {"user_id": 5, "note": "Szuka", "employment_only": True}
    }
    # Flaga to wyłącznie literalne `True`.
    assert proposals.sanitize_evidence(
        {"trainee": {"user_id": 5, "employment_only": "tak"}}
    ) == {"trainee": {"user_id": 5}}


# ── API ─────────────────────────────────────────────────────────────────────


def _inbox(job_id: int) -> str:
    return f"/api/jobs/{job_id}/proposal-inbox"


# Od 30.09.2026 „Pomiń" wymaga powodu (0405).
_REASON = {"reason": "too_expensive"}


async def _seed_inbox(world: dict) -> None:
    async with AsyncSessionLocal() as db:
        await proposals.upsert_proposals(
            db,
            world["job_id"],
            [
                {
                    "candidate_id": cid,
                    "score": 90 - index,
                    "evidence": {"missing_must": ["Kafka"]},
                }
                for index, cid in enumerate(world["candidate_ids"])
            ],
            "full_base",
        )
        await db.commit()


@pytest.mark.parametrize(
    "role,pipeline,expected",
    [
        (UserRole.recruiter, None, 200),
        # Odebrana sekcja rekrutacji = brak skrzynki, niezależnie od roli.
        (UserRole.recruiter, "none", 403),
        # Finanse: organizacyjny odczyt rekrutacji (bez prawa zapisu).
        (UserRole.finance, None, 200),
    ],
)
async def test_inbox_follows_the_full_search_guard(
    app_client: AsyncClient, role, pipeline, expected
):
    world = await _world(people=1)
    await _seed_inbox(world)
    _, headers = await _user(role, pipeline=pipeline)
    response = await app_client.get(_inbox(world["job_id"]), headers=headers)
    assert response.status_code == expected, response.text


async def test_inbox_requires_login_and_an_existing_recruitment(
    app_client: AsyncClient,
):
    _, headers = await _user(UserRole.recruiter)
    assert (await app_client.get(_inbox(1))).status_code == 401
    missing = await app_client.get(_inbox(2_000_000_000), headers=headers)
    assert missing.status_code == 404, missing.text
    # Licznik jest zespołowy — znacznika „widziane" per użytkownik nie ma.
    gone = await app_client.post(f"{_inbox(1)}/seen", headers=headers)
    assert gone.status_code in (404, 405), gone.text


async def test_inbox_lists_narrow_identity_and_shows_the_candidate_rate(
    app_client: AsyncClient, app_auth_headers: dict
):
    world = await _world(people=2)
    await _seed_inbox(world)
    _, recruiter = await _user(UserRole.recruiter)

    as_recruiter = await app_client.get(_inbox(world["job_id"]), headers=recruiter)
    as_admin = await app_client.get(_inbox(world["job_id"]), headers=app_auth_headers)
    assert as_recruiter.status_code == 200, as_recruiter.text
    assert as_admin.status_code == 200, as_admin.text

    body = as_recruiter.json()
    assert body["total"] == 2 and body["next_offset"] is None
    assert [i["candidate"]["id"] for i in body["items"]] == world["candidate_ids"]
    item = body["items"][0]
    assert item["sources"] == ["full_base"]
    assert item["score"] == 90.0
    assert item["evidence"] == {"missing_must": ["Kafka"]}
    assert item["is_new"] is True
    candidate = item["candidate"]
    assert candidate["city"] == "Gdańsk"
    assert "email" not in candidate and "phone" not in candidate
    # R10-N7-10: stawka KANDYDATA jawna także dla rekrutera (decyzja 27.09).
    assert candidate["expected_rate_hourly"] == 150.0
    assert candidate["expected_rate_redacted"] is False

    admin_candidate = as_admin.json()["items"][0]["candidate"]
    assert admin_candidate["expected_rate_hourly"] == 150.0
    assert admin_candidate["expected_rate_redacted"] is False


async def test_dismiss_flow(app_client: AsyncClient):
    recruiter_id, recruiter = await _user(UserRole.recruiter)
    outsider_id, outsider = await _user(UserRole.recruiter)
    _, viewer = await _user(UserRole.user)
    world = await _world(people=2, recruiter_id=recruiter_id)
    await _seed_inbox(world)
    job_id = world["job_id"]
    first, second = world["candidate_ids"]

    listed = await app_client.get(_inbox(job_id), headers=recruiter)
    assert [i["is_new"] for i in listed.json()["items"]] == [True, True]

    # Stara rola podglądu nie zmienia skrzynki zespołu.
    refused = await app_client.post(
        f"{_inbox(job_id)}/{first}/dismiss", json=_REASON, headers=viewer
    )
    assert refused.status_code == 403, refused.text
    assert (await _statuses(job_id))[(first, "full_base")] == "proposed"

    # Od 23.09.2026 pomija każdy rekruter — także spoza zespołu rekrutacji.
    done = await app_client.post(
        f"{_inbox(job_id)}/{first}/dismiss", json=_REASON, headers=outsider
    )
    assert done.status_code == 200, done.text
    assert done.json()["dismissed"] == 1
    again = await app_client.post(
        f"{_inbox(job_id)}/{first}/dismiss", json=_REASON, headers=recruiter
    )
    assert again.status_code == 200 and again.json()["dismissed"] == 0
    unknown = await app_client.post(
        f"{_inbox(job_id)}/2000000000/dismiss", json=_REASON, headers=recruiter
    )
    assert unknown.status_code == 404, unknown.text

    remaining = await app_client.get(_inbox(job_id), headers=recruiter)
    assert [i["candidate"]["id"] for i in remaining.json()["items"]] == [second]
    dismissed = await app_client.get(
        _inbox(job_id), params={"status": "dismissed"}, headers=recruiter
    )
    assert [i["candidate"]["id"] for i in dismissed.json()["items"]] == [first]
    async with AsyncSessionLocal() as db:
        row = await db.scalar(
            select(JobProposal).where(
                JobProposal.job_id == job_id, JobProposal.candidate_id == first
            )
        )
    assert row.dismissed_by == outsider_id
    assert row.dismissed_at is not None
    # Trasa stempluje BIEŻĄCĄ wersję profilu (ta sama funkcja co auto-match).
    assert row.dismissed_cv_revision == "unparsed"

    # „Pomiń" jest zespołowe: licznik listy spada dla każdego, nie tylko autora.
    rows = await app_client.get(
        "/api/jobs",
        params={"include_stage_counts": "true", "client_id": world["client_id"]},
        headers=outsider,
    )
    row_json = next(r for r in rows.json()["items"] if r["id"] == job_id)
    assert row_json["open_proposals_count"] == 1
    assert "new_proposals_count" not in row_json


async def test_dismiss_works_for_a_person_the_inbox_never_listed(
    app_client: AsyncClient,
):
    recruiter_id, recruiter = await _user(UserRole.recruiter)
    _, viewer = await _user(UserRole.user)
    world = await _world(people=3, recruiter_id=recruiter_id)
    job_id = world["job_id"]
    searched, recommended, in_pipeline = world["candidate_ids"]
    async with AsyncSessionLocal() as db:
        db.add(
            CandidateStage(
                candidate_id=in_pipeline, job_id=job_id, stage=PipelineStage.new
            )
        )
        await db.commit()

    # Ta sama bramka co dotąd: rola wewnętrzna i sekcja rekrutacji (przypisanie
    # do zespołu od 23.09.2026 nie jest wymagane).
    refused = await app_client.post(
        f"{_inbox(job_id)}/{searched}/dismiss", json=_REASON, headers=viewer
    )
    assert refused.status_code == 403, refused.text
    _, no_pipeline = await _user(UserRole.recruiter, pipeline="none")
    assert (
        await app_client.post(
            f"{_inbox(job_id)}/{searched}/dismiss", json=_REASON, headers=no_pipeline
        )
    ).status_code == 403
    assert await _statuses(job_id) == {}

    # Bez źródła → domyślne; ze źródłem → wskazane; spoza CHECK-a → 422.
    plain = await app_client.post(
        f"{_inbox(job_id)}/{searched}/dismiss", json=_REASON, headers=recruiter
    )
    assert plain.status_code == 200 and plain.json()["dismissed"] == 1, plain.text
    chosen = await app_client.post(
        f"{_inbox(job_id)}/{recommended}/dismiss",
        json={"source": "recommendation", "reason": "outdated_cv"},
        headers=recruiter,
    )
    assert chosen.status_code == 200 and chosen.json()["dismissed"] == 1, chosen.text
    bad = await app_client.post(
        f"{_inbox(job_id)}/{recommended}/dismiss",
        json={"source": "cokolwiek", "reason": "outdated_cv"},
        headers=recruiter,
    )
    assert bad.status_code == 422, bad.text
    assert await _statuses(job_id) == {
        (searched, "full_base"): "dismissed",
        (recommended, "recommendation"): "dismissed",
    }
    async with AsyncSessionLocal() as db:
        row = await db.scalar(
            select(JobProposal).where(
                JobProposal.job_id == job_id, JobProposal.candidate_id == searched
            )
        )
    assert row.dismissed_by == recruiter_id and row.dismissed_at is not None
    assert row.dismissed_cv_revision == "unparsed" == row.cv_revision

    # R10-N7-1: skrzynka niesie listę pominiętych — front odsiewa ich z żywego
    # przeglądu, podobnych projektów i rekomendacji (te źródła nie czytają
    # `job_proposals`). Tylko pierwsza strona `proposed`.
    listed = await app_client.get(_inbox(job_id), headers=recruiter)
    assert listed.status_code == 200, listed.text
    assert sorted(listed.json()["dismissed_candidate_ids"]) == sorted(
        [searched, recommended]
    )
    later_page = await app_client.get(
        _inbox(job_id), params={"offset": 20}, headers=recruiter
    )
    assert later_page.json()["dismissed_candidate_ids"] == []

    # Idempotentne: druga próba nie zakłada drugiego wiersza.
    again = await app_client.post(
        f"{_inbox(job_id)}/{searched}/dismiss", json=_REASON, headers=recruiter
    )
    assert again.status_code == 200 and again.json()["dismissed"] == 0
    assert len(await _statuses(job_id)) == 2

    # Osoba już w rekrutacji → 409 po polsku, bez wiersza; brak kandydata → 404.
    conflict = await app_client.post(
        f"{_inbox(job_id)}/{in_pipeline}/dismiss", json=_REASON, headers=recruiter
    )
    assert conflict.status_code == 409, conflict.text
    assert "już w tej rekrutacji" in conflict.json()["detail"]
    assert (
        await app_client.post(
            f"{_inbox(job_id)}/2000000000/dismiss", json=_REASON, headers=recruiter
        )
    ).status_code == 404
    assert len(await _statuses(job_id)) == 2

    # Ta sama wersja CV nie wskrzesza osoby pominiętej „z zewnątrz", nowa — tak.
    async with AsyncSessionLocal() as db:
        await proposals.upsert_proposals(
            db,
            job_id,
            [{"candidate_id": searched}],
            "full_base",
            cv_revision="unparsed",
        )
        await db.commit()
    assert (await _statuses(job_id))[(searched, "full_base")] == "dismissed"
    async with AsyncSessionLocal() as db:
        await proposals.upsert_proposals(
            db, job_id, [{"candidate_id": searched}], "full_base", cv_revision="v2"
        )
        await db.commit()
    assert (await _statuses(job_id))[(searched, "full_base")] == "proposed"


async def test_dismiss_requires_a_reason_and_stores_it(app_client: AsyncClient):
    recruiter_id, recruiter = await _user(UserRole.recruiter)
    world = await _world(people=3, recruiter_id=recruiter_id)
    await _seed_inbox(world)
    job_id = world["job_id"]
    first, second, unlisted = world["candidate_ids"]
    async with AsyncSessionLocal() as db:
        # `unlisted` nie ma wiersza — „Pomiń" z wyszukiwarki zakłada go od razu.
        await db.execute(
            JobProposal.__table__.delete().where(
                JobProposal.job_id == job_id, JobProposal.candidate_id == unlisted
            )
        )
        await db.commit()

    # Bez ciała i bez powodu → 422 po polsku, nic się nie zmienia.
    for payload in (None, {"source": "full_base"}):
        missing = await app_client.post(
            f"{_inbox(job_id)}/{first}/dismiss", json=payload, headers=recruiter
        )
        assert missing.status_code == 422, missing.text
        assert "powód" in missing.json()["detail"]
    unknown = await app_client.post(
        f"{_inbox(job_id)}/{first}/dismiss",
        json={"reason": "bo tak"},
        headers=recruiter,
    )
    assert unknown.status_code == 422, unknown.text
    other = await app_client.post(
        f"{_inbox(job_id)}/{first}/dismiss",
        json={"reason": "other", "note": "   "},
        headers=recruiter,
    )
    assert other.status_code == 422 and "Inne" in other.json()["detail"]
    assert (await _statuses(job_id))[(first, "full_base")] == "proposed"

    ok = await app_client.post(
        f"{_inbox(job_id)}/{first}/dismiss",
        json={"reason": "other", "note": "  Klient nie chce freelancerów  "},
        headers=recruiter,
    )
    assert ok.status_code == 200 and ok.json()["dismissed"] == 1, ok.text
    await app_client.post(
        f"{_inbox(job_id)}/{second}/dismiss",
        json={"reason": "missing_critical", "note": ""},
        headers=recruiter,
    )
    await app_client.post(
        f"{_inbox(job_id)}/{unlisted}/dismiss",
        json={"reason": "location_office", "source": "recommendation"},
        headers=recruiter,
    )
    async with AsyncSessionLocal() as db:
        rows = {
            r.candidate_id: (r.dismiss_reason, r.dismiss_note)
            for r in (
                await db.scalars(
                    select(JobProposal).where(JobProposal.job_id == job_id)
                )
            ).all()
        }
    assert rows == {
        first: ("other", "Klient nie chce freelancerów"),
        second: ("missing_critical", None),
        unlisted: ("location_office", None),
    }


async def test_restore_undoes_a_dismiss(app_client: AsyncClient):
    recruiter_id, recruiter = await _user(UserRole.recruiter)
    _, outsider = await _user(UserRole.recruiter)
    _, viewer = await _user(UserRole.user)
    world = await _world(people=2, recruiter_id=recruiter_id)
    await _seed_inbox(world)
    job_id = world["job_id"]
    first, second = world["candidate_ids"]
    async with AsyncSessionLocal() as db:
        await proposals.upsert_proposals(
            db, job_id, [{"candidate_id": first, "score": 50}], "new_cv"
        )
        await db.commit()

    done = await app_client.post(
        f"{_inbox(job_id)}/{first}/dismiss", json=_REASON, headers=recruiter
    )
    assert done.json()["dismissed"] == 2

    refused = await app_client.post(f"{_inbox(job_id)}/{first}/restore", headers=viewer)
    assert refused.status_code == 403, refused.text
    assert (await _statuses(job_id))[(first, "full_base")] == "dismissed"

    # „Cofnij" robi każdy rekruter, także spoza zespołu (23.09.2026).
    restored = await app_client.post(
        f"{_inbox(job_id)}/{first}/restore", headers=outsider
    )
    assert restored.status_code == 200, restored.text
    assert restored.json() == {"job_id": job_id, "candidate_id": first, "restored": 2}
    async with AsyncSessionLocal() as db:
        rows = (
            await db.scalars(
                select(JobProposal).where(
                    JobProposal.job_id == job_id, JobProposal.candidate_id == first
                )
            )
        ).all()
    assert {r.status for r in rows} == {"proposed"}
    assert all(
        r.dismissed_at is None
        and r.dismissed_by is None
        and r.dismissed_cv_revision is None
        and r.dismiss_reason is None
        and r.dismiss_note is None
        for r in rows
    )
    listed = await app_client.get(_inbox(job_id), headers=recruiter)
    assert [i["candidate"]["id"] for i in listed.json()["items"]] == [first, second]

    # Nic do cofnięcia = 0 (także dla osoby nigdy niepominiętej); brak osoby = 404.
    again = await app_client.post(
        f"{_inbox(job_id)}/{first}/restore", headers=recruiter
    )
    assert again.status_code == 200 and again.json()["restored"] == 0
    assert (
        await app_client.post(f"{_inbox(job_id)}/2000000000/restore", headers=recruiter)
    ).status_code == 404

    # `added` nigdy się nie cofa — także przez „Cofnij".
    async with AsyncSessionLocal() as db:
        await proposals.mark_added(db, job_id=job_id, candidate_ids=[second])
        await db.commit()
    await app_client.post(f"{_inbox(job_id)}/{second}/restore", headers=recruiter)
    assert (await _statuses(job_id))[(second, "full_base")] == "added"


async def test_inbox_rows_carry_the_run_of_the_best_scoring_source(
    app_client: AsyncClient,
):
    recruiter_id, recruiter = await _user(UserRole.recruiter)
    world = await _world(people=2, recruiter_id=recruiter_id)
    job_id = world["job_id"]
    with_run, without_run = world["candidate_ids"]
    run_id = str(uuid.uuid4())
    async with AsyncSessionLocal() as db:
        await proposals.upsert_proposals(
            db,
            job_id,
            [{"candidate_id": with_run, "score": 80}],
            "full_base",
            run_id=run_id,
        )
        # Wyższy wynik, ale źródło bez przeglądu — `run_id` i tak ma dojechać.
        await proposals.upsert_proposals(
            db, job_id, [{"candidate_id": with_run, "score": 95}], "new_cv"
        )
        await proposals.upsert_proposals(
            db, job_id, [{"candidate_id": without_run, "score": 10}], "new_cv"
        )
        await db.commit()

    listed = await app_client.get(_inbox(job_id), headers=recruiter)
    assert listed.status_code == 200, listed.text
    by_id = {i["candidate"]["id"]: i for i in listed.json()["items"]}
    assert by_id[with_run]["run_id"] == run_id
    assert "run_id" in by_id[without_run] and by_id[without_run]["run_id"] is None


async def test_adding_to_the_recruitment_marks_the_proposal_added(
    app_client: AsyncClient,
):
    recruiter_id, recruiter = await _user(UserRole.recruiter)
    world = await _world(people=2, recruiter_id=recruiter_id)
    await _seed_inbox(world)
    job_id = world["job_id"]
    first, second = world["candidate_ids"]

    added = await app_client.post(
        f"/api/jobs/{job_id}/proposals/bulk",
        json={"candidate_ids": [first]},
        headers=recruiter,
    )
    assert added.status_code == 200, added.text
    assert added.json()["added"] == [first]

    statuses = await _statuses(job_id)
    assert statuses[(first, "full_base")] == "added"
    assert statuses[(second, "full_base")] == "proposed"

    rows = await app_client.get(
        "/api/jobs",
        params={"include_stage_counts": "true", "client_id": world["client_id"]},
        headers=recruiter,
    )
    assert rows.status_code == 200, rows.text
    row = next(r for r in rows.json()["items"] if r["id"] == job_id)
    assert row["open_proposals_count"] == 1


async def test_latest_run_shows_own_and_automatic_runs_only(app_client: AsyncClient):
    from app.models.candidate_search_run import CandidateSearchRun

    me_id, me = await _user(UserRole.recruiter)
    other_id, _ = await _user(UserRole.recruiter)
    world = await _world(people=0)
    job_id = world["job_id"]
    url = f"/api/candidate-search/jobs/{job_id}/latest-run"

    empty = await app_client.get(url, headers=me)
    assert empty.status_code == 200, empty.text
    assert empty.json() == {"job_id": job_id, "run": None, "latest_failure": None}

    now = datetime.now(timezone.utc)

    def run(created_by, state, completed_at, trace=None, metrics=None):
        return CandidateSearchRun(
            id=str(uuid.uuid4()),
            created_by=created_by,
            client_id=world["client_id"],
            job_id=job_id,
            state=state,
            request_fingerprint="f" * 64,
            request_context={},
            version_trace=trace or {},
            population_size=0,
            completed_at=completed_at,
            metrics=metrics or {},
        )

    mine = run(me_id, "complete", now - timedelta(hours=5))
    foreign = run(other_id, "complete", now - timedelta(hours=1))
    running = run(me_id, "running", None)
    async with AsyncSessionLocal() as db:
        db.add_all([mine, foreign, running])
        await db.commit()

    # Cudzy ręczny przegląd jest prywatny, a trwający nie jest „zakończony".
    body = (await app_client.get(url, headers=me)).json()
    assert body["run"]["run_id"] == mine.id
    assert body["run"]["own"] is True and body["run"]["origin"] == "manual"

    auto = run(other_id, "partial", now - timedelta(minutes=5), {"origin": "auto"})
    async with AsyncSessionLocal() as db:
        db.add(auto)
        await db.commit()
    body = (await app_client.get(url, headers=me)).json()
    assert body["run"]["run_id"] == auto.id
    assert body["run"]["state"] == "partial"
    assert body["run"]["own"] is False and body["run"]["origin"] == "auto"
    assert body["latest_failure"] is None

    # Runda 9 (R9-N5-5): nowsza awaria nie przykrywa udanego rankingu.
    broken = run(other_id, "failed", now, {"origin": "auto"})
    async with AsyncSessionLocal() as db:
        db.add(broken)
        await db.commit()
    body = (await app_client.get(url, headers=me)).json()
    assert body["run"]["run_id"] == auto.id
    assert body["latest_failure"]["run_id"] == broken.id

    _, no_pipeline = await _user(UserRole.recruiter, pipeline="none")
    assert (await app_client.get(url, headers=no_pipeline)).status_code == 403


# ── RODO ────────────────────────────────────────────────────────────────────


async def test_hard_delete_removes_the_candidates_proposals(
    app_client: AsyncClient, app_auth_headers: dict
):
    world = await _world(people=2)
    await _seed_inbox(world)
    erased, kept = world["candidate_ids"]

    response = await app_client.delete(
        f"/api/candidates/{erased}", headers=app_auth_headers
    )
    assert response.status_code == 204, response.text

    async with AsyncSessionLocal() as db:
        left = (
            await db.scalars(
                select(JobProposal.candidate_id).where(
                    JobProposal.job_id == world["job_id"]
                )
            )
        ).all()
    assert left == [kept]


# ── Lustro DDL w entrypoint.sh ──────────────────────────────────────────────


def _entrypoint_column_statements() -> list[str]:
    lines = (_BACKEND / "entrypoint.sh").read_text(encoding="utf-8").split("\n")
    start = next(
        i + 1
        for i, line in enumerate(lines)
        if line.startswith("python - <<'PY'") and "column backfill" in line
    )
    end = start
    while lines[end] != "PY":
        end += 1
    tree = ast.parse("\n".join(lines[start:end]))
    for node in tree.body:
        if (
            isinstance(node, ast.Assign)
            and isinstance(node.targets[0], ast.Name)
            and node.targets[0].id == "_COLUMN_STATEMENTS"
        ):
            out = []
            for element in node.value.elts:
                try:
                    value = ast.literal_eval(element)
                except (ValueError, TypeError):
                    continue
                if isinstance(value, str):
                    out.append(" ".join(value.split()))
            return out
    raise AssertionError("entrypoint.sh: brak listy _COLUMN_STATEMENTS")


def test_entrypoint_mirrors_the_0333_tables():
    """Prod alembic bywa osierocony — lustro w entrypoincie JEST wdrożeniem."""
    statements = _entrypoint_column_statements()
    for model in (JobProposal,):
        table = model.__table__
        create = next(
            (
                s
                for s in statements
                if s.startswith(f"CREATE TABLE IF NOT EXISTS {table.name} (")
            ),
            None,
        )
        assert create is not None, f"entrypoint.sh nie zakłada tabeli {table.name}"
        for column in table.columns:
            assert f" {column.name} " in create or f"({column.name} " in create, (
                f"{table.name}.{column.name} nie ma w lustrze DDL"
            )
        for constraint in table.constraints:
            if constraint.name and constraint.name.startswith(("uq_", "ck_")):
                assert str(constraint.name) in create, constraint.name
        for fk in table.foreign_keys:
            target = fk.column.table.name
            rule = (fk.ondelete or "").upper()
            assert f"REFERENCES {target}(id) ON DELETE {rule}" in create
        for index in table.indexes:
            assert any(
                s.startswith(f"CREATE INDEX IF NOT EXISTS {index.name} ")
                for s in statements
            ), index.name
    # `run_id` celowo bez FK — przeglądy kasuje retencja.
    assert not JobProposal.__table__.c.run_id.foreign_keys


# ── Podział licznika: świeże z ogłoszeń / z bazy (02.10.2026) ───────────────


def _counts(job_id: int) -> str:
    return f"/api/jobs/{job_id}/proposal-counts"


async def _age_proposal(job_id: int, candidate_id: int, source: str, days: int) -> None:
    async with AsyncSessionLocal() as db:
        await db.execute(
            JobProposal.__table__.update()
            .where(
                JobProposal.job_id == job_id,
                JobProposal.candidate_id == candidate_id,
                JobProposal.source == source,
            )
            .values(first_seen_at=datetime.now(timezone.utc) - timedelta(days=days))
        )
        await db.commit()


async def _seed_split(world: dict) -> dict[str, int]:
    """Sześć osób: po jednej na każdy przypadek podziału."""
    job_id = world["job_id"]
    fresh_cv, old_cv, base_and_board, base_only, in_pipeline, dismissed = world[
        "candidate_ids"
    ]
    async with AsyncSessionLocal() as db:
        await proposals.upsert_proposals(
            db,
            job_id,
            [{"candidate_id": c, "score": 60} for c in (fresh_cv, old_cv, dismissed)],
            "new_cv",
        )
        await proposals.upsert_proposals(
            db,
            job_id,
            [{"candidate_id": c, "score": 70} for c in (base_and_board, base_only)],
            "full_base",
        )
        await proposals.upsert_proposals(
            db,
            job_id,
            [{"candidate_id": c, "score": 80} for c in (base_and_board, in_pipeline)],
            "job_board",
        )
        db.add(
            CandidateStage(
                candidate_id=in_pipeline,
                job_id=job_id,
                stage=PipelineStage.new,
                moved_at=datetime.now(timezone.utc),
            )
        )
        await proposals.dismiss(db, job_id=job_id, candidate_id=dismissed, user_id=None)
        await db.commit()
    await _age_proposal(job_id, fresh_cv, "new_cv", 6)
    await _age_proposal(job_id, old_cv, "new_cv", 8)
    await _age_proposal(job_id, base_and_board, "full_base", 30)
    await _age_proposal(job_id, base_only, "full_base", 1)
    return {
        "fresh_cv": fresh_cv,
        "old_cv": old_cv,
        "base_and_board": base_and_board,
        "base_only": base_only,
    }


async def test_split_counts_sum_to_the_list_total_and_follow_the_window():
    world = await _world(people=6)
    job_id = world["job_id"]
    people = await _seed_split(world)
    week_ago = datetime.now(timezone.utc) - timedelta(days=7)

    async with AsyncSessionLocal() as db:
        split = await proposals.open_split_counts(db, job_id=job_id, since=week_ago)
        rows, total = await proposals.list_for_job(db, job_id=job_id)
        wide = await proposals.open_split_counts(
            db, job_id=job_id, since=datetime.now(timezone.utc) - timedelta(days=10)
        )
        empty = await proposals.open_split_counts(db, job_id=-1, since=week_ago)

    # Nowe CV sprzed 6 dni i świeży portal obok starego przeglądu bazy = „z
    # ogłoszeń”; nowe CV sprzed 8 dni i sam przegląd bazy = „z bazy”. Osoba
    # w rekrutacji i osoba pominięta nie liczą się wcale — jak na liście.
    assert split == {"postings_recent": 2, "base": 2}
    assert split["postings_recent"] + split["base"] == total == 4
    # Szersze okno przenosi ósmy dzień na stronę ogłoszeń; suma zostaje.
    assert wide == {"postings_recent": 3, "base": 1}
    assert empty == {"postings_recent": 0, "base": 0}

    by_id = {row.candidate_id: row for row in rows}
    assert by_id[people["base_only"]].posting_seen_at is None
    assert by_id[people["fresh_cv"]].posting_seen_at >= week_ago
    assert by_id[people["old_cv"]].posting_seen_at < week_ago
    # Data pochodzi z wiersza OGŁOSZENIA, nie ze starego przeglądu bazy.
    assert by_id[people["base_and_board"]].posting_seen_at >= week_ago
    assert by_id[people["base_and_board"]].sources == ["full_base", "job_board"]


async def test_inbox_items_and_counts_endpoint_agree_on_postings(
    app_client: AsyncClient,
):
    world = await _world(people=6)
    job_id = world["job_id"]
    people = await _seed_split(world)
    prose = "Minimum 5 lat doświadczenia w analizie biznesowej procesów bankowych"
    async with AsyncSessionLocal() as db:
        job = await db.get(Job, job_id)
        job.must_skills = ["Python", "Kafka", prose]
        db.add_all(
            [
                ApplicationScreening(
                    candidate_id=people["fresh_cv"],
                    job_id=job_id,
                    status="done",
                    verdict="not_fit",
                    outcome="screened_out",
                ),
                # Dodana „mimo to” — nie stoi już na liście odrzuconych.
                ApplicationScreening(
                    candidate_id=people["old_cv"],
                    job_id=job_id,
                    status="done",
                    verdict="not_fit",
                    outcome="screened_out",
                    overridden_at=datetime.now(timezone.utc),
                ),
            ]
        )
        await db.commit()
    _, headers = await _user(UserRole.recruiter)

    inbox = await app_client.get(_inbox(job_id), headers=headers)
    assert inbox.status_code == 200, inbox.text
    items = {i["candidate"]["id"]: i for i in inbox.json()["items"]}
    assert items[people["base_only"]]["posting_seen_at"] is None
    assert items[people["base_only"]]["posting_recent"] is False
    assert items[people["fresh_cv"]]["posting_recent"] is True
    assert items[people["old_cv"]]["posting_seen_at"] is not None
    assert items[people["old_cv"]]["posting_recent"] is False
    assert items[people["base_and_board"]]["posting_recent"] is True

    response = await app_client.get(_counts(job_id), headers=headers)
    assert response.status_code == 200, response.text
    body = response.json()
    assert set(body) == {
        "job_id",
        "days",
        "postings_recent",
        "base",
        "screened_out",
        "not_searchable_must",
    }
    assert (body["job_id"], body["days"]) == (job_id, 7)
    assert (body["postings_recent"], body["base"]) == (2, 2)
    assert body["postings_recent"] + body["base"] == inbox.json()["total"]
    assert sum(i["posting_recent"] for i in items.values()) == body["postings_recent"]
    # Ta sama liczba co `total` listy „Odrzuceni przez AI”.
    screened = await app_client.get(f"/api/jobs/{job_id}/screened-out", headers=headers)
    assert body["screened_out"] == screened.json()["total"] == 1
    # Zdanie nie jest technologią — ta sama reguła co `/scores`.
    assert [m.lower() for m in body["not_searchable_must"]] == [prose.lower()]

    wide = await app_client.get(_counts(job_id), params={"days": 10}, headers=headers)
    assert wide.status_code == 200, wide.text
    assert (wide.json()["days"], wide.json()["postings_recent"]) == (10, 3)
    assert wide.json()["base"] == 1
    for days in (0, 31):
        refused = await app_client.get(
            _counts(job_id), params={"days": days}, headers=headers
        )
        assert refused.status_code == 422, refused.text


@pytest.mark.parametrize(
    "role,pipeline",
    [
        (UserRole.recruiter, None),
        (UserRole.recruiter, "none"),
        (UserRole.finance, None),
    ],
)
async def test_counts_follow_the_inbox_guard(app_client: AsyncClient, role, pipeline):
    world = await _world(people=1)
    await _seed_inbox(world)
    _, headers = await _user(role, pipeline=pipeline)
    inbox = await app_client.get(_inbox(world["job_id"]), headers=headers)
    counts = await app_client.get(_counts(world["job_id"]), headers=headers)
    assert counts.status_code == inbox.status_code, counts.text
    assert counts.status_code == (403 if pipeline == "none" else 200)


async def test_counts_require_login_and_an_existing_recruitment(
    app_client: AsyncClient,
):
    _, headers = await _user(UserRole.recruiter)
    assert (await app_client.get(_counts(1))).status_code == 401
    missing = await app_client.get(_counts(2_000_000_000), headers=headers)
    assert missing.status_code == 404, missing.text


# ── 0422: `expired`, `added` tylko z człowieka, telemetria (07.10.2026) ─────


async def _set_status(job_id: int, candidate_id: int, status: str) -> None:
    async with AsyncSessionLocal() as db:
        row = await db.scalar(
            select(JobProposal).where(
                JobProposal.job_id == job_id,
                JobProposal.candidate_id == candidate_id,
                JobProposal.source == "full_base",
            )
        )
        row.status = status
        await db.commit()


async def test_expired_rows_are_invisible_and_revive_on_return():
    world = await _world(people=3)
    await _seed_inbox(world)
    job_id = world["job_id"]
    gone, kept, mixed = world["candidate_ids"]
    await _set_status(job_id, gone, "expired")
    await _set_status(job_id, mixed, "expired")
    async with AsyncSessionLocal() as db:
        # Para z żywym wierszem innego źródła nadal czeka — wygasły wiersz
        # nie głosuje ani nie dokłada wyniku.
        await proposals.upsert_proposals(
            db, job_id, [{"candidate_id": mixed, "score": 40}], "new_cv"
        )
        await db.commit()
    async with AsyncSessionLocal() as db:
        rows, total = await proposals.list_for_job(db, job_id=job_id)
        assert total == 2
        by_id = {r.candidate_id: r for r in rows}
        assert set(by_id) == {kept, mixed}
        assert by_id[mixed].sources == ["new_cv"] and by_id[mixed].score == 40.0
        assert (await proposals.open_counts_for_jobs(db, [job_id]))[job_id] == 2
        assert (await proposals.open_counts_for_jobs(db, [job_id], source="full_base"))[
            job_id
        ] == 1
        split = await proposals.open_split_counts(
            db, job_id=job_id, since=datetime.now(timezone.utc) - timedelta(days=7)
        )
        assert split["postings_recent"] + split["base"] == 2
        assert await proposals.dismissed_candidate_ids(db, job_id=job_id) == []

    # Kolejny przegląd znowu proponuje osobę → wraca do skrzynki.
    async with AsyncSessionLocal() as db:
        await proposals.upsert_proposals(
            db, job_id, [{"candidate_id": gone, "score": 77}], "full_base"
        )
        await db.commit()
    assert (await _statuses(job_id))[(gone, "full_base")] == "proposed"
    # Bez wskrzeszania (zaległa publikacja starszego przeglądu) zostaje wygasła.
    async with AsyncSessionLocal() as db:
        await proposals.upsert_proposals(
            db,
            job_id,
            [{"candidate_id": mixed, "score": 77}],
            "full_base",
            revive_expired=False,
        )
        await db.commit()
    assert (await _statuses(job_id))[(mixed, "full_base")] == "expired"


async def test_expire_full_base_touches_only_open_rows_of_other_runs():
    world = await _world(people=4)
    job_id = world["job_id"]
    current, stale, dismissed, other_source = world["candidate_ids"]
    async with AsyncSessionLocal() as db:
        await proposals.upsert_proposals(
            db,
            job_id,
            [{"candidate_id": c, "score": 80} for c in (stale, dismissed)],
            "full_base",
            run_id="run-old",
        )
        await proposals.upsert_proposals(
            db,
            job_id,
            [{"candidate_id": current, "score": 90}],
            "full_base",
            run_id="run-new",
        )
        await proposals.upsert_proposals(
            db, job_id, [{"candidate_id": other_source, "score": 70}], "new_cv"
        )
        await proposals.dismiss(db, job_id=job_id, candidate_id=dismissed, user_id=None)
        expired = await proposals.expire_full_base(db, job_id=job_id, run_id="run-new")
        await db.commit()
    assert expired == 1
    statuses = await _statuses(job_id)
    assert statuses[(current, "full_base")] == "proposed"
    assert statuses[(stale, "full_base")] == "expired"
    assert statuses[(dismissed, "full_base")] == "dismissed"
    assert statuses[(other_source, "new_cv")] == "proposed"


async def test_top_open_by_job_uses_the_inbox_visibility():
    world = await _world(people=5)
    job_id = world["job_id"]
    best, second, third, fourth, in_pipeline = world["candidate_ids"]
    async with AsyncSessionLocal() as db:
        await proposals.upsert_proposals(
            db,
            job_id,
            [
                {"candidate_id": best, "score": 95},
                {"candidate_id": second, "score": 90},
                {"candidate_id": third, "score": 85},
                {"candidate_id": fourth, "score": 80},
                {"candidate_id": in_pipeline, "score": 99},
            ],
            "full_base",
        )
        db.add(
            CandidateStage(
                candidate_id=in_pipeline, job_id=job_id, stage=PipelineStage.new
            )
        )
        await db.commit()
    await _set_status(job_id, second, "expired")
    async with AsyncSessionLocal() as db:
        top = await proposals.top_open_by_job(db, [job_id], per_job=3)
    assert [(t.job_id, t.candidate_id, t.score) for t in top] == [
        (job_id, best, 95.0),
        (job_id, third, 85.0),
        (job_id, fourth, 80.0),
    ]


async def test_only_a_human_add_marks_the_proposal_added():
    from app.api import proposals_bulk

    recruiter_id, _ = await _user(UserRole.recruiter)
    world = await _world(people=2, recruiter_id=recruiter_id)
    await _seed_inbox(world)
    job_id = world["job_id"]
    by_integration, by_human = world["candidate_ids"]
    async with AsyncSessionLocal() as db:
        job = await db.get(Job, job_id)
        auto = await proposals_bulk.add_candidates_to_job(
            db,
            job=job,
            candidate_ids=[by_integration],
            actor_user_id=recruiter_id,
            entry_source="auto_match",
            claim=False,
        )
        human = await proposals_bulk.add_candidates_to_job(
            db,
            job=job,
            candidate_ids=[by_human],
            actor_user_id=recruiter_id,
            mark_proposals=True,
        )
        await db.commit()
    assert auto.added == [by_integration] and human.added == [by_human]
    statuses = await _statuses(job_id)
    assert statuses[(by_integration, "full_base")] == "proposed"
    assert statuses[(by_human, "full_base")] == "added"


async def test_opening_the_inbox_is_recorded_once_a_day(app_client: AsyncClient):
    from app.models.activity import Activity

    recruiter_id, recruiter = await _user(UserRole.recruiter)
    world = await _world(people=0, recruiter_id=recruiter_id)
    job_id = world["job_id"]
    url = f"/api/jobs/{job_id}/proposal-inbox/opened"
    first = await app_client.post(url, headers=recruiter)
    assert first.status_code == 200, first.text
    assert first.json() == {"job_id": job_id, "recorded": True}
    again = await app_client.post(url, headers=recruiter)
    assert again.status_code == 200, again.text
    assert again.json()["recorded"] is False
    async with AsyncSessionLocal() as db:
        rows = (
            await db.scalars(
                select(Activity).where(
                    Activity.entity_type == "job",
                    Activity.entity_id == job_id,
                    Activity.action == "proposal_inbox_opened",
                )
            )
        ).all()
    assert len(rows) == 1 and rows[0].user_id == recruiter_id
    # GET listy nadal niczego nie zapisuje.
    listed = await app_client.get(_inbox(job_id), headers=recruiter)
    assert listed.status_code == 200, listed.text


async def test_integration_added_proposals_repair_is_one_shot():
    from app.models.app_setting import AppSetting
    from app.models.recruitment_process import RecruitmentProcess
    from app.services import proposal_added_repair as repair

    recruiter_id, _ = await _user(UserRole.recruiter)
    world = await _world(people=2, recruiter_id=recruiter_id)
    await _seed_inbox(world)
    job_id = world["job_id"]
    by_card, by_human = world["candidate_ids"]
    from app.api import proposals_bulk

    async with AsyncSessionLocal() as db:
        job = await db.get(Job, job_id)
        await proposals_bulk.add_candidates_to_job(
            db,
            job=job,
            candidate_ids=[by_card],
            actor_user_id=recruiter_id,
            entry_source="auto_match",
            claim=False,
        )
        await proposals_bulk.add_candidates_to_job(
            db,
            job=job,
            candidate_ids=[by_human],
            actor_user_id=recruiter_id,
            mark_proposals=True,
        )
        # Stan sprzed 07.10.2026: karta z integracji też stawiała `added`.
        await proposals.mark_added(db, job_id=job_id, candidate_ids=[by_card])
        await db.commit()
        sources = dict(
            (
                await db.execute(
                    select(
                        RecruitmentProcess.candidate_id, RecruitmentProcess.entry_source
                    ).where(RecruitmentProcess.job_id == job_id)
                )
            ).all()
        )
    assert sources[by_card] == "auto_match" and sources[by_human] != "auto_match"

    async with AsyncSessionLocal() as db:
        marker = await db.get(AppSetting, repair.REPAIR_MARKER)
        if marker is not None:
            # Baza testowa jest wspólna — wcześniejszy przebieg zostawił znacznik.
            await db.delete(marker)
            await db.commit()
    async with AsyncSessionLocal() as db:
        summary = await repair.run_proposal_added_repair(db)
        await db.commit()
    assert summary is not None and [job_id, by_card] in summary["pair_ids"]
    assert [job_id, by_human] not in summary["pair_ids"]
    statuses = await _statuses(job_id)
    assert statuses[(by_card, "full_base")] == "proposed"
    assert statuses[(by_human, "full_base")] == "added"
    async with AsyncSessionLocal() as db:
        assert await repair.run_proposal_added_repair(db) is None


def test_statuses_agree_everywhere() -> None:
    from app.models.job_proposal import JOB_PROPOSAL_STATUSES
    from app.services import job_proposal_feedback_schema as schema

    assert tuple(JOB_PROPOSAL_STATUSES) == schema.STATUSES
    check = next(
        str(c.sqltext)
        for c in JobProposal.__table__.constraints
        if c.name == "ck_job_proposals_status"
    )
    for status in schema.STATUSES:
        assert f"'{status}'" in check
    entry = (_BACKEND / "entrypoint.sh").read_text(encoding="utf-8")
    assert "*_JOB_PROPOSAL_STATUS_CONSTRAINTS," in entry
    assert "status IN ('proposed', 'dismissed', 'added', 'expired')" in entry
    migration = (_BACKEND / "alembic/versions/0422_job_proposals_expired.py").read_text(
        encoding="utf-8"
    )
    assert "STATUS_CONSTRAINT_DDL" in migration
