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
        (UserRole.sourcer, None, 200),
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


async def test_inbox_lists_narrow_identity_and_redacts_the_rate(
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
    # Rekruter nie ma odczytu finansów: stawka zredagowana, klucz zostaje.
    assert candidate["expected_rate_hourly"] is None
    assert candidate["expected_rate_redacted"] is True

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
    refused = await app_client.post(f"{_inbox(job_id)}/{first}/dismiss", headers=viewer)
    assert refused.status_code == 403, refused.text
    assert (await _statuses(job_id))[(first, "full_base")] == "proposed"

    # Od 23.09.2026 pomija każdy rekruter — także spoza zespołu rekrutacji.
    done = await app_client.post(f"{_inbox(job_id)}/{first}/dismiss", headers=outsider)
    assert done.status_code == 200, done.text
    assert done.json()["dismissed"] == 1
    again = await app_client.post(
        f"{_inbox(job_id)}/{first}/dismiss", headers=recruiter
    )
    assert again.status_code == 200 and again.json()["dismissed"] == 0
    unknown = await app_client.post(
        f"{_inbox(job_id)}/2000000000/dismiss", headers=recruiter
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
        f"{_inbox(job_id)}/{searched}/dismiss", headers=viewer
    )
    assert refused.status_code == 403, refused.text
    _, no_pipeline = await _user(UserRole.recruiter, pipeline="none")
    assert (
        await app_client.post(
            f"{_inbox(job_id)}/{searched}/dismiss", headers=no_pipeline
        )
    ).status_code == 403
    assert await _statuses(job_id) == {}

    # Bez ciała → domyślne źródło; z ciałem → wskazane; spoza CHECK-a → 422.
    plain = await app_client.post(
        f"{_inbox(job_id)}/{searched}/dismiss", headers=recruiter
    )
    assert plain.status_code == 200 and plain.json()["dismissed"] == 1, plain.text
    chosen = await app_client.post(
        f"{_inbox(job_id)}/{recommended}/dismiss",
        json={"source": "recommendation"},
        headers=recruiter,
    )
    assert chosen.status_code == 200 and chosen.json()["dismissed"] == 1, chosen.text
    bad = await app_client.post(
        f"{_inbox(job_id)}/{recommended}/dismiss",
        json={"source": "cokolwiek"},
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

    # Idempotentne: druga próba nie zakłada drugiego wiersza.
    again = await app_client.post(
        f"{_inbox(job_id)}/{searched}/dismiss", headers=recruiter
    )
    assert again.status_code == 200 and again.json()["dismissed"] == 0
    assert len(await _statuses(job_id)) == 2

    # Osoba już w rekrutacji → 409 po polsku, bez wiersza; brak kandydata → 404.
    conflict = await app_client.post(
        f"{_inbox(job_id)}/{in_pipeline}/dismiss", headers=recruiter
    )
    assert conflict.status_code == 409, conflict.text
    assert "już w tej rekrutacji" in conflict.json()["detail"]
    assert (
        await app_client.post(f"{_inbox(job_id)}/2000000000/dismiss", headers=recruiter)
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

    done = await app_client.post(f"{_inbox(job_id)}/{first}/dismiss", headers=recruiter)
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
    assert empty.json() == {"job_id": job_id, "run": None}

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
