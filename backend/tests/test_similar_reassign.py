"""Panel przepięć (25.09.2026): ludzie wysłani do klienta w podobnych
rekrutacjach i przepięcie ich do „Nowych" jednym kliknięciem.

Decyzje Artura: rekrutacja nigdy nie jest zaznaczona sama (incydent 23.09),
kliknięcie rekrutacji zaznacza jej wysłanych — także odrzuconych przez
klienta; zatrudnionych widać, ale nie da się ich przepiąć.

Prawdziwy Postgres, baza wspólna i nieczyszczona: każdy test zakłada własny
świat (``_world`` z testów połączeń) i sprawdza tylko swoje wiersze.
"""

from datetime import datetime, timedelta, timezone

from httpx import AsyncClient
from sqlalchemy import select

from app.core.database import AsyncSessionLocal
from app.models.candidate import Candidate
from app.models.job_proposal import JobProposal
from app.models.job_similar_link import JobSimilarLink
from app.models.recruitment_pipeline import CandidateStage, PipelineStage
from app.models.recruitment_process import RecruitmentProcess
from app.services import job_similarity as sim
from tests.test_job_similar_links import _world


async def _world_with_outcomes() -> dict:
    """Świat z testów połączeń + osoba odrzucona przez klienta w A
    i osoba wysłana w A, która już jest w B."""
    world = await _world()
    now = datetime.now(timezone.utc)
    async with AsyncSessionLocal() as db:
        rejected = Candidate(
            name="Odrzucona",
            lastname=f"Klient-{world['tag']}",
            email=f"similar-rej-{world['tag']}@example.com",
        )
        in_target = Candidate(
            name="Już",
            lastname=f"WCelu-{world['tag']}",
            email=f"similar-in-{world['tag']}@example.com",
        )
        db.add_all([rejected, in_target])
        await db.flush()
        db.add_all(
            [
                CandidateStage(
                    candidate_id=rejected.id,
                    job_id=world["a"],
                    stage=PipelineStage.cv_sent,
                    moved_at=now - timedelta(days=8),
                ),
                CandidateStage(
                    candidate_id=rejected.id,
                    job_id=world["a"],
                    stage=PipelineStage.rejected,
                    moved_at=now - timedelta(days=6),
                    ended_by="client",
                ),
                CandidateStage(
                    candidate_id=in_target.id,
                    job_id=world["a"],
                    stage=PipelineStage.client_interview,
                    moved_at=now - timedelta(days=7),
                ),
                CandidateStage(
                    candidate_id=in_target.id,
                    job_id=world["b"],
                    stage=PipelineStage.new,
                    moved_at=now - timedelta(days=1),
                ),
            ]
        )
        await db.commit()
        return {**world, "rejected": rejected.id, "in_target": in_target.id}


async def _process(candidate_id: int, job_id: int) -> RecruitmentProcess | None:
    async with AsyncSessionLocal() as db:
        return await db.scalar(
            select(RecruitmentProcess)
            .where(
                RecruitmentProcess.candidate_id == candidate_id,
                RecruitmentProcess.job_id == job_id,
            )
            .order_by(RecruitmentProcess.attempt_no.desc())
            .limit(1)
        )


async def _links(job_id: int) -> set[int]:
    async with AsyncSessionLocal() as db:
        rows = await db.execute(
            select(JobSimilarLink.similar_job_id).where(JobSimilarLink.job_id == job_id)
        )
        return set(rows.scalars())


# ── Miara: ten sam klient ─────────────────────────────────────────────────


def test_same_client_counts_like_same_category():
    """ZOB-3006 i ZOB-1725 (PKO BP, różne kategorie) — przypadek z produkcji."""
    a = sim.title_tokens("Analityk Systemowy AI/LLM (ZOB-3006)")
    b = sim.title_tokens("PKO BP: Analityk Systemowy / ZOB-1725")
    empty = frozenset()
    assert sim.similarity_score(empty, a, 1, empty, b, 5) < sim.MIN_SCORE
    same_client = sim.similarity_score(
        empty, a, 1, empty, b, 5, a_client=26, b_client=26
    )
    assert same_client >= sim.MIN_SCORE
    # Klient i kategoria to jedno „tło" — bez wspólnego tytułu nie przechodzą.
    java = sim.title_tokens("PKO BP: Java Developer / ZOB-1")
    assert (
        sim.similarity_score(empty, a, 1, empty, java, 1, a_client=26, b_client=26)
        < sim.MIN_SCORE
    )
    assert sim.similarity_score(
        empty, a, 1, empty, b, 5, a_client=26, b_client=27
    ) == sim.similarity_score(empty, a, 1, empty, b, 5)


# ── Kto był u klienta ─────────────────────────────────────────────────────


async def test_sent_people_marks_outcome_and_selectable():
    world = await _world_with_outcomes()
    async with AsyncSessionLocal() as db:
        people = await sim.sent_people(db, world["b"], [world["a"]])
    by_id = {p["candidate_id"]: p for p in people[world["a"]]}
    assert set(by_id) == {
        world["sent"],
        world["hired"],
        world["rejected"],
        world["in_target"],
    }
    assert world["screening"] not in by_id  # nie doszedł do klienta
    assert by_id[world["sent"]]["outcome"] == "in_progress"
    assert by_id[world["sent"]]["selectable"] is True
    assert by_id[world["rejected"]]["outcome"] == "rejected_by_client"
    assert by_id[world["rejected"]]["selectable"] is True
    assert by_id[world["hired"]]["outcome"] == "hired"
    assert by_id[world["hired"]]["selectable"] is False
    assert by_id[world["in_target"]]["already_in_job"] is True
    assert by_id[world["in_target"]]["selectable"] is False
    assert by_id[world["in_target"]]["furthest_stage"] == "client_interview"
    # Zaznaczalni pierwsi.
    order = [p["selectable"] for p in people[world["a"]]]
    assert order == sorted(order, reverse=True)


# ── API ───────────────────────────────────────────────────────────────────


async def test_people_endpoint_lists_people_per_job(
    app_client: AsyncClient, app_auth_headers: dict
):
    world = await _world_with_outcomes()
    response = await app_client.get(
        f"/api/jobs/{world['b']}/similar/people",
        params={"job_ids": [world["a"]]},
        headers=app_auth_headers,
    )
    assert response.status_code == 200, response.text
    jobs = response.json()["jobs"]
    assert [j["job_id"] for j in jobs] == [world["a"]]
    people = {p["candidate_id"]: p for p in jobs[0]["people"]}
    assert people[world["sent"]]["name"].startswith("Przepięcie")
    assert "reassign_at" not in people[world["sent"]]


async def test_search_finds_closed_jobs_with_sent_count(
    app_client: AsyncClient, app_auth_headers: dict
):
    world = await _world()
    response = await app_client.get(
        f"/api/jobs/{world['b']}/similar/search",
        params={"q": f"kotlin {world['tag']}"},
        headers=app_auth_headers,
    )
    assert response.status_code == 200, response.text
    items = {item["id"]: item for item in response.json()["items"]}
    assert world["b"] not in items  # bez rekrutacji, w której jesteśmy
    assert items[world["a"]]["sent_count"] == 2
    assert items[world["a"]]["status"] == "closed"
    short = await app_client.get(
        f"/api/jobs/{world['b']}/similar/search",
        params={"q": "k"},
        headers=app_auth_headers,
    )
    assert short.json() == {"items": []}


async def test_reassign_links_and_adds_selected_people_to_new(
    app_client: AsyncClient, app_auth_headers: dict
):
    world = await _world_with_outcomes()
    # Wcześniej ktoś pominął przepięcie tej osoby — ręczny wybór je wskrzesza.
    async with AsyncSessionLocal() as db:
        await sim.propose_selected(
            db,
            world["b"],
            [
                {
                    "candidate_id": world["sent"],
                    "source_job_id": world["a"],
                    "reassign_stage": "cv_sent",
                    "reassign_at": None,
                }
            ],
        )
        await db.execute(
            JobProposal.__table__.update()
            .where(
                JobProposal.job_id == world["b"],
                JobProposal.candidate_id == world["sent"],
            )
            .values(status="dismissed")
        )
        await db.commit()

    response = await app_client.post(
        f"/api/jobs/{world['b']}/similar/reassign",
        json={
            "job_ids": [world["a"]],
            "candidate_ids": [world["sent"], world["rejected"]],
        },
        headers=app_auth_headers,
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert sorted(body["added"]) == sorted([world["sent"], world["rejected"]])
    assert body["linked_now"] == [world["a"]]
    assert await _links(world["b"]) == {world["a"]}

    for candidate_id in (world["sent"], world["rejected"]):
        process = await _process(candidate_id, world["b"])
        assert process is not None
        assert process.entry_source == "reassign"
        assert process.reassign_from_job_id == world["a"]
        assert process.claimed_by_user_id is not None
        async with AsyncSessionLocal() as db:
            stage = await db.scalar(
                select(CandidateStage.stage).where(
                    CandidateStage.candidate_id == candidate_id,
                    CandidateStage.job_id == world["b"],
                )
            )
        assert stage == PipelineStage.new


async def test_reassign_refuses_hired_and_writes_nothing(
    app_client: AsyncClient, app_auth_headers: dict
):
    world = await _world_with_outcomes()
    response = await app_client.post(
        f"/api/jobs/{world['b']}/similar/reassign",
        json={"job_ids": [world["a"]], "candidate_ids": [world["hired"]]},
        headers=app_auth_headers,
    )
    assert response.status_code == 422, response.text
    assert await _links(world["b"]) == set()
    assert await _process(world["hired"], world["b"]) is None


async def test_reassign_without_people_only_links(
    app_client: AsyncClient, app_auth_headers: dict
):
    world = await _world()
    response = await app_client.post(
        f"/api/jobs/{world['b']}/similar/reassign",
        json={"job_ids": [world["a"]], "candidate_ids": []},
        headers=app_auth_headers,
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["added"] == []
    assert body["linked_now"] == [world["a"]]
    assert await _links(world["b"]) == {world["a"]}
    # Połączenie działa jak dotąd: wysłani czekają w „Do przejrzenia".
    assert await _process(world["sent"], world["b"]) is None


async def test_reassignable_counts_match_selectable_people(
    app_client: AsyncClient, app_auth_headers: dict
):
    """Odznaka i „Najbliższy krok” liczą tylko tych, których da się przepiąć
    — nie zatrudnionych i nie obecnych już w rekrutacji (przegląd 25.09)."""
    world = await _world_with_outcomes()
    async with AsyncSessionLocal() as db:
        per_job, people = await sim.reassignable_counts(db, world["b"], [world["a"]])
    assert per_job == {world["a"]: 2}  # w toku + odrzucona przez klienta
    assert people == 2

    sim.reset_pool_cache()
    response = await app_client.get(
        f"/api/jobs/{world['b']}/similar", headers=app_auth_headers
    )
    assert response.status_code == 200, response.text
    body = response.json()
    item = next(s for s in body["suggestions"] if s["id"] == world["a"])
    assert item["sent_count"] == 4
    assert item["reassignable_count"] == 2
    assert body["reassignable_people"] >= 2


async def test_reassign_again_after_undo_stays_a_reassign(
    app_client: AsyncClient, app_auth_headers: dict
):
    """„Cofnij” zdejmuje osobę z rekrutacji, a propozycja zostaje `added`;
    ponowne przepięcie nadal zapisuje wejście jako przepięcie."""
    world = await _world()
    body = {"job_ids": [world["a"]], "candidate_ids": [world["sent"]]}
    first = await app_client.post(
        f"/api/jobs/{world['b']}/similar/reassign", json=body, headers=app_auth_headers
    )
    assert first.status_code == 200, first.text

    undo = await app_client.delete(
        f"/api/candidates/{world['sent']}/recruitments/{world['b']}",
        headers=app_auth_headers,
    )
    assert undo.status_code in (200, 204), undo.text
    async with AsyncSessionLocal() as db:
        left = await db.scalar(
            select(CandidateStage.id).where(
                CandidateStage.candidate_id == world["sent"],
                CandidateStage.job_id == world["b"],
            )
        )
    assert left is None  # proces unieważniony, etapów nie ma

    again = await app_client.post(
        f"/api/jobs/{world['b']}/similar/reassign", json=body, headers=app_auth_headers
    )
    assert again.status_code == 200, again.text
    assert again.json()["added"] == [world["sent"]]
    process = await _process(world["sent"], world["b"])
    assert process is not None
    assert process.entry_source == "reassign"
    assert process.reassign_from_job_id == world["a"]
