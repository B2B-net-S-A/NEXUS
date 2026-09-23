"""Podobne rekrutacje, przepięcia i status requestu (migracja 0341).

Prawdziwy Postgres. Baza testowa jest wspólna i nieczyszczona, więc każdy test
zakłada własnego klienta, rekrutacje i osoby, a asercje dotyczą tylko ich.
"""

import ast
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from httpx import AsyncClient
from sqlalchemy import select

import app.models  # noqa: F401  (zarejestruj wszystkie mappery)
from app.core.database import AsyncSessionLocal
from app.core.security import create_access_token, hash_password
from app.models.candidate import Candidate
from app.models.client import Client
from app.models.job import Job, JobStatus
from app.models.job_proposal import JobProposal
from app.models.job_similar_link import JobSimilarLink
from app.models.recruitment_pipeline import CandidateStage, PipelineStage
from app.models.user import User, UserRole
from app.services import job_similarity as sim

_BACKEND = Path(__file__).resolve().parents[1]


async def _user(role: UserRole) -> tuple[int, dict[str, str]]:
    tag = uuid.uuid4().hex[:8]
    async with AsyncSessionLocal() as db:
        user = User(
            email=f"similar-{role.value}-{tag}@example.com",
            password_hash=hash_password(f"T3st_{tag}!Similar"),
            name=f"Similar {role.value}",
            role=role,
            is_active=True,
        )
        db.add(user)
        await db.commit()
        return user.id, {
            "Authorization": f"Bearer {create_access_token(user.id, role.value)}"
        }


async def _world(*, recruiter_id: int | None = None) -> dict:
    """Dwie podobne rekrutacje (A starsza, B nowa) i trzy osoby w A."""
    tag = uuid.uuid4().hex[:8]
    async with AsyncSessionLocal() as db:
        client = Client(name=f"Similar client {tag}")
        db.add(client)
        await db.flush()
        a = Job(
            title=f"Senior Kotlin Developer {tag}",
            client_id=client.id,
            status=JobStatus.closed,
            must_skills=["Kotlin", "Spring Boot", "Kafka"],
            recruiter_id=recruiter_id,
        )
        b = Job(
            title=f"Kotlin Developer {tag}",
            client_id=client.id,
            status=JobStatus.published,
            must_skills=["Kotlin", "Spring Boot", "Kafka"],
            recruiter_id=recruiter_id,
        )
        people = [
            Candidate(
                name="Przepięcie",
                lastname=f"{index}-{tag}",
                email=f"similar-{index}-{tag}@example.com",
            )
            for index in range(3)
        ]
        db.add_all([a, b, *people])
        await db.flush()
        sent, hired, screening = people
        now = datetime.now(timezone.utc)
        db.add_all(
            [
                CandidateStage(
                    candidate_id=sent.id,
                    job_id=a.id,
                    stage=PipelineStage.screening,
                    moved_at=now - timedelta(days=10),
                ),
                CandidateStage(
                    candidate_id=sent.id,
                    job_id=a.id,
                    stage=PipelineStage.cv_sent,
                    moved_at=now - timedelta(days=5),
                ),
                CandidateStage(
                    candidate_id=hired.id,
                    job_id=a.id,
                    stage=PipelineStage.cv_sent,
                    moved_at=now - timedelta(days=9),
                ),
                CandidateStage(
                    candidate_id=hired.id,
                    job_id=a.id,
                    stage=PipelineStage.hired,
                    moved_at=now - timedelta(days=2),
                ),
                CandidateStage(
                    candidate_id=screening.id,
                    job_id=a.id,
                    stage=PipelineStage.screening,
                    moved_at=now - timedelta(days=3),
                ),
            ]
        )
        await db.commit()
        return {
            "a": a.id,
            "b": b.id,
            "sent": sent.id,
            "hired": hired.id,
            "screening": screening.id,
            "tag": tag,
        }


async def _reassigned(job_id: int) -> dict[int, dict]:
    async with AsyncSessionLocal() as db:
        rows = await db.execute(
            select(JobProposal.candidate_id, JobProposal.evidence).where(
                JobProposal.job_id == job_id, JobProposal.source == "reassign"
            )
        )
        return {cid: ev for cid, ev in rows.all()}


# ── Miara podobieństwa ────────────────────────────────────────────────────


def test_similarity_prefers_shared_must_have_and_title():
    java = sim.skill_set(["Java", "Spring"])
    kotlin = sim.skill_set(["Kotlin", "Kafka"])
    title = sim.title_tokens("Senior Java Developer")
    assert sim.title_tokens("Senior Java Developer (Spring)") == frozenset(
        {"java", "developer", "spring"}
    )
    same = sim.similarity_score(java, title, 2, java, title, 2)
    other = sim.similarity_score(java, title, 2, kotlin, sim.title_tokens("Tester"), 3)
    assert same == 100
    assert other < sim.MIN_SCORE


def test_similarity_without_skills_uses_title_and_category():
    tokens = sim.title_tokens("Analityk biznesowy")
    assert sim.similarity_score(frozenset(), tokens, 1, frozenset(), tokens, 1) == 100
    assert sim.similarity_score(frozenset(), tokens, 1, frozenset(), tokens, 2) == 70


# ── Przepięcia ────────────────────────────────────────────────────────────


async def test_link_reassigns_only_people_sent_to_client_and_not_hired():
    world = await _world()
    async with AsyncSessionLocal() as db:
        linked, reassigned = await sim.link_jobs(
            db, world["b"], [world["a"]], user_id=None
        )
        await db.commit()
    assert (linked, reassigned) == (1, 1)
    rows = await _reassigned(world["b"])
    assert set(rows) == {world["sent"]}
    assert rows[world["sent"]]["reassign"]["job_id"] == world["a"]
    assert rows[world["sent"]]["reassign"]["stage"] == "cv_sent"
    # Połączenie jest symetryczne; A zamknięta nie przyjmuje przepięć.
    async with AsyncSessionLocal() as db:
        pairs = set(
            (
                await db.execute(
                    select(JobSimilarLink.job_id, JobSimilarLink.similar_job_id).where(
                        JobSimilarLink.job_id.in_([world["a"], world["b"]])
                    )
                )
            ).all()
        )
    assert pairs == {(world["a"], world["b"]), (world["b"], world["a"])}
    assert await _reassigned(world["a"]) == {}


async def test_link_is_idempotent_and_skips_people_already_in_target():
    world = await _world()
    async with AsyncSessionLocal() as db:
        db.add(
            CandidateStage(
                candidate_id=world["sent"],
                job_id=world["b"],
                stage=PipelineStage.new,
                moved_at=datetime.now(timezone.utc),
            )
        )
        await db.commit()
        first = await sim.link_jobs(db, world["b"], [world["a"]], user_id=None)
        again = await sim.link_jobs(db, world["b"], [world["a"]], user_id=None)
        await db.commit()
    assert first == (1, 0)
    assert again == (0, 0)
    assert await _reassigned(world["b"]) == {}


async def test_person_sent_later_in_linked_job_is_reassigned_automatically():
    world = await _world()
    async with AsyncSessionLocal() as db:
        await sim.link_jobs(db, world["b"], [world["a"]], user_id=None)
        await db.commit()
        # Osoba ze screeningu w A trafia do klienta — hak ruchu przepina ją do B.
        written = await sim.on_candidate_sent(
            db,
            job_id=world["a"],
            candidate_id=world["screening"],
            stage=PipelineStage.cv_sent,
        )
        ignored = await sim.on_candidate_sent(
            db,
            job_id=world["a"],
            candidate_id=world["screening"],
            stage=PipelineStage.screening,
        )
        await db.commit()
    assert (written, ignored) == (1, 0)
    assert world["screening"] in await _reassigned(world["b"])


async def test_suggestions_find_similar_job_and_count_people_sent():
    world = await _world()
    sim.reset_pool_cache()
    async with AsyncSessionLocal() as db:
        job_b = await db.get(Job, world["b"])
        found = await sim.suggestions_for_job(db, job_b, limit=50)
        sent = await sim.sent_counts(db, [world["a"]])
    ids = [p.id for p, _ in found]
    assert world["a"] in ids
    assert world["b"] not in ids
    assert sent[world["a"]] == 2


# ── Status requestu ───────────────────────────────────────────────────────


async def test_request_status_rule():
    world = await _world()
    async with AsyncSessionLocal() as db:
        statuses = await sim.request_statuses(db, [world["a"], world["b"]])
        assert statuses == {world["a"]: "closed", world["b"]: "searching"}
        job_b = await db.get(Job, world["b"])
        job_b.champion_found_at = datetime.now(timezone.utc)
        await db.commit()
        assert (await sim.request_statuses(db, [world["b"]]))[world["b"]] == "champion"
        db.add(
            CandidateStage(
                candidate_id=world["sent"],
                job_id=world["b"],
                stage=PipelineStage.acceptance,
                moved_at=datetime.now(timezone.utc),
            )
        )
        await db.commit()
        assert (await sim.request_statuses(db, [world["b"]]))[world["b"]] == "contract"
        db.add(
            CandidateStage(
                candidate_id=world["sent"],
                job_id=world["b"],
                stage=PipelineStage.hired,
                moved_at=datetime.now(timezone.utc) + timedelta(seconds=1),
            )
        )
        await db.commit()
        assert (await sim.request_statuses(db, [world["b"]]))[world["b"]] == "filled"


# ── API ───────────────────────────────────────────────────────────────────


async def test_similar_api_links_and_lists_reassign_source(
    app_client: AsyncClient, app_auth_headers: dict
):
    world = await _world()
    sim.reset_pool_cache()
    got = await app_client.get(
        f"/api/jobs/{world['b']}/similar", headers=app_auth_headers
    )
    assert got.status_code == 200, got.text
    assert world["a"] in [s["id"] for s in got.json()["suggestions"]]

    linked = await app_client.post(
        f"/api/jobs/{world['b']}/similar",
        json={"job_ids": [world["a"]]},
        headers=app_auth_headers,
    )
    assert linked.status_code == 200, linked.text
    body = linked.json()
    assert body["reassigned_now"] == 1
    assert [x["id"] for x in body["linked"]] == [world["a"]]
    assert body["linked"][0]["sent_count"] == 2

    inbox = await app_client.get(
        f"/api/jobs/{world['b']}/proposal-inbox", headers=app_auth_headers
    )
    assert inbox.status_code == 200, inbox.text
    first = inbox.json()["items"][0]
    assert first["candidate"]["id"] == world["sent"]
    assert "reassign" in first["sources"]
    assert first["reassign_from"]["job_id"] == world["a"]

    unlinked = await app_client.delete(
        f"/api/jobs/{world['b']}/similar/{world['a']}", headers=app_auth_headers
    )
    assert unlinked.status_code == 200
    assert unlinked.json()["linked"] == []


async def test_similar_api_rejects_unknown_job(
    app_client: AsyncClient, app_auth_headers
):
    world = await _world()
    response = await app_client.post(
        f"/api/jobs/{world['b']}/similar",
        json={"job_ids": [2_000_000_000]},
        headers=app_auth_headers,
    )
    assert response.status_code == 404


async def test_recruiter_links_to_a_recruitment_outside_their_team(
    app_client: AsyncClient,
):
    """Od 23.09.2026 rekruter z zespołu B łączy B z rekrutacją A, w której
    zespole nie jest („nie musisz być przypisany"), a przepięcie idzie do B.
    Stara rola podglądu ``user`` nie łączy niczego."""
    recruiter_id, headers = await _user(UserRole.recruiter)
    _, viewer = await _user(UserRole.user)
    world = await _world()
    async with AsyncSessionLocal() as db:
        job_b = await db.get(Job, world["b"])
        job_b.recruiter_id = recruiter_id
        await db.commit()

    refused = await app_client.post(
        f"/api/jobs/{world['b']}/similar",
        json={"job_ids": [world["a"]]},
        headers=viewer,
    )
    assert refused.status_code == 403, refused.text
    assert await _reassigned(world["b"]) == {}

    response = await app_client.post(
        f"/api/jobs/{world['b']}/similar",
        json={"job_ids": [world["a"]]},
        headers=headers,
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert [x["id"] for x in body["linked"]] == [world["a"]]
    assert body["reassigned_now"] == 1
    async with AsyncSessionLocal() as db:
        rows = await db.execute(
            select(JobSimilarLink.job_id, JobSimilarLink.similar_job_id).where(
                JobSimilarLink.job_id.in_([world["a"], world["b"]])
            )
        )
        assert set(rows.all()) == {
            (world["b"], world["a"]),
            (world["a"], world["b"]),
        }
    assert set(await _reassigned(world["b"])) == {world["sent"]}


async def test_preview_suggests_for_unsaved_job(
    app_client: AsyncClient, app_auth_headers
):
    world = await _world()
    sim.reset_pool_cache()
    response = await app_client.post(
        "/api/job-similarity/preview",
        json={
            "title": f"Kotlin Developer {world['tag']}",
            "must_skills": ["Kotlin", "Kafka"],
        },
        headers=app_auth_headers,
    )
    assert response.status_code == 200, response.text
    ids = [s["id"] for s in response.json()["suggestions"]]
    assert world["a"] in ids and world["b"] in ids


async def test_champion_found_is_delivery_lead_decision(
    app_client: AsyncClient, app_auth_headers: dict
):
    recruiter_id, recruiter = await _user(UserRole.recruiter)
    world = await _world(recruiter_id=recruiter_id)
    denied = await app_client.post(
        f"/api/jobs/{world['b']}/champion-found",
        json={"found": True},
        headers=recruiter,
    )
    assert denied.status_code == 403
    ok = await app_client.post(
        f"/api/jobs/{world['b']}/champion-found",
        json={"found": True},
        headers=app_auth_headers,
    )
    assert ok.status_code == 200, ok.text
    assert ok.json()["champion_found"] is True

    listed = await app_client.get(
        "/api/jobs",
        params={
            "request_status": "champion",
            "q": world["tag"],
            "include_stage_counts": "true",
        },
        headers=app_auth_headers,
    )
    assert listed.status_code == 200, listed.text
    rows = {row["id"]: row for row in listed.json()["items"]}
    assert set(rows) == {world["b"]}
    assert rows[world["b"]]["request_status"] == "champion"
    assert rows[world["b"]]["champion_found_at"] is not None
    assert rows[world["b"]]["similar"]["linked_count"] == 0

    bad = await app_client.get(
        "/api/jobs", params={"request_status": "nope"}, headers=app_auth_headers
    )
    assert bad.status_code == 422


# ── Lustro DDL w entrypoint.sh ────────────────────────────────────────────


def _entrypoint_statements(list_name: str) -> list[str]:
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
            and node.targets[0].id == list_name
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
    raise AssertionError(f"entrypoint.sh: brak listy {list_name}")


def test_entrypoint_mirrors_0341():
    statements = _entrypoint_statements("_COLUMN_STATEMENTS")
    table = JobSimilarLink.__table__
    create = next(
        s
        for s in statements
        if s.startswith("CREATE TABLE IF NOT EXISTS job_similar_links (")
    )
    for column in table.columns:
        assert f" {column.name} " in create or f"({column.name} " in create, column.name
    for constraint in table.constraints:
        if constraint.name and constraint.name.startswith(("uq_", "ck_")):
            assert str(constraint.name) in create, constraint.name
    for index in table.indexes:
        assert any(
            s.startswith(f"CREATE INDEX IF NOT EXISTS {index.name} ")
            for s in statements
        )
    for column in ("champion_found_at", "champion_found_by"):
        assert any(f"ADD COLUMN IF NOT EXISTS {column}" in s for s in statements), (
            column
        )
    constraints = " ".join(_entrypoint_statements("_CONSTRAINT_STATEMENTS"))
    assert "'marketplace', 'reassign'" in constraints


@pytest.mark.parametrize("source", ["reassign"])
def test_reassign_is_a_known_proposal_source(source):
    from app.api.job_proposals import ProposalSource
    from app.models.job_proposal import JOB_PROPOSAL_SOURCES

    assert source in JOB_PROPOSAL_SOURCES
    assert source in ProposalSource.__args__


async def test_job_detail_carries_request_status(
    app_client: AsyncClient, app_auth_headers: dict
):
    world = await _world()
    response = await app_client.get(f"/api/jobs/{world['b']}", headers=app_auth_headers)
    assert response.status_code == 200, response.text
    assert response.json()["request_status"] == "searching"


@pytest.fixture
def _tech_taxonomy():
    from app.services import skill_normalize as sn

    saved = (
        set(sn.TECH_CANONICALS),
        dict(sn.ALIAS_TO_CANONICAL),
        dict(sn.CANONICAL_TO_ALIASES),
    )
    sn.set_tech_taxonomy(
        tech_canonicals=["react", "java", "selenium"],
        alias_to_canonical={"reactjs": "react", "react.js": "react"},
    )
    yield
    sn.set_tech_taxonomy(
        tech_canonicals=saved[0],
        alias_to_canonical=saved[1],
        canonical_to_aliases=saved[2],
    )


def test_skill_set_reads_champion_stack_and_canonical_tech_names(_tech_taxonomy):
    """22.09.2026: silnik podobnych czyta stack Championa, a nie tylko kolumnę.

    Aliasy technologii są jednym wymaganiem, a zdania opisowe z profilu nie
    zaniżają podobieństwa rekrutacji, które wymagają tych samych technologii.
    """
    profile = {
        "stack": {"must": [{"name": "React.js"}, {"name": "10 lat doświadczenia w IT"}]}
    }
    from_champion = sim.skill_set([], profile)
    from_column = sim.skill_set([{"name": "ReactJS"}])
    assert from_champion == from_column == frozenset({"react"})
    assert sim.skill_set(
        [{"name": "Java"}], {"stack": {"must": ["Selenium"]}}
    ) == frozenset({"java", "selenium"})
