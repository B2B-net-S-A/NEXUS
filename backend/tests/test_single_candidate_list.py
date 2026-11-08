"""Jedna lista kandydatów (``SINGLE_CANDIDATE_LIST_ENABLED``, 08.11.2026).

Prawdziwy Postgres, baza wspólna i nieczyszczona: każdy test zakłada własną
rekrutację i osoby. Kontrakty: jeden wiersz na osobę, pula zachowuje się jak
``full_base``, wyłączona flaga to dzisiejszy panel, stara liczba scrapera nie
wchodzi na skalę „Dop.”, silnik kart czyta tę samą definicję co lista.
"""

import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace

import pytest
from httpx import AsyncClient
from sqlalchemy import select

import app.models  # noqa: F401  (zarejestruj wszystkie mappery)
from app.api.proposals_bulk import propose_candidates_for_job
from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.core.security import create_access_token, hash_password
from app.models.candidate import Candidate, CandidateStatus
from app.models.candidate_stage_removal import CandidateStageRemoval
from app.models.client import Client
from app.models.job import Job, JobStatus
from app.models.job_autofill_pool import JobAutofillPool
from app.models.job_proposal import JobProposal
from app.models.recruitment_pipeline import CandidateStage, PipelineStage
from app.models.user import User, UserRole
from app.services import job_proposals as proposals
from app.services import new_column_autofill as autofill
from app.services import single_candidate_list as single_list


@pytest.fixture(autouse=True)
def _flag_on(monkeypatch):
    monkeypatch.setattr(settings, "SINGLE_CANDIDATE_LIST_ENABLED", True)
    # Próg 70 niezależnie od panelu „Ranking kandydatów” w bazie testowej.
    monkeypatch.setattr(settings, "AUTO_FULL_REVIEW_MIN_SCORE", 70)


async def _world(people: int = 3) -> tuple[int, list[int]]:
    tag = uuid.uuid4().hex[:8]
    async with AsyncSessionLocal() as db:
        client = Client(name=f"Single list {tag}")
        db.add(client)
        await db.flush()
        job = Job(
            title=f"Single list {tag}",
            client_id=client.id,
            status=JobStatus.published,
        )
        candidates = [
            Candidate(
                name="Lista",
                lastname=f"{index}-{tag}",
                email=f"single-{index}-{tag}@example.com",
                city="Gdańsk",
            )
            for index in range(people)
        ]
        db.add_all([job, *candidates])
        await db.commit()
        return job.id, [c.id for c in candidates]


async def _pool(job_id: int, scores: dict[int, float]) -> None:
    async with AsyncSessionLocal() as db:
        db.add_all(
            [
                JobAutofillPool(
                    job_id=job_id,
                    candidate_id=cid,
                    score=Decimal(str(score)),
                    run_id="pool-run",
                    evidence={"matched_must": ["Java"], "missing_must": []},
                )
                for cid, score in scores.items()
            ]
        )
        await db.commit()


async def _propose(job_id: int, source: str, rows: list[dict]) -> None:
    async with AsyncSessionLocal() as db:
        await proposals.upsert_proposals(db, job_id, rows, source)
        await db.commit()


async def _page(job_id: int, list_filter: str = "all", **kw) -> single_list.ListPage:
    async with AsyncSessionLocal() as db:
        job = await db.get(Job, job_id)
        return await single_list.page(
            db,
            job=job,
            threshold=70.0,
            first_ids=kw.get("first_ids", ()),
            limit=kw.get("limit", 50),
            offset=kw.get("offset", 0),
            list_filter=list_filter,
            now=datetime.now(timezone.utc),
        )


def _ids(page: single_list.ListPage) -> list[int]:
    return [row.candidate_id for row in page.rows]


# ── Jeden wiersz na osobę ───────────────────────────────────────────────────


async def test_three_sources_and_the_pool_give_one_row():
    job_id, (person, *_rest) = await _world(1)
    await _pool(job_id, {person: 81})
    await _propose(job_id, "full_base", [{"candidate_id": person, "score": 76}])
    await _propose(job_id, "new_cv", [{"candidate_id": person, "score": 74}])
    await _propose(job_id, "reassign", [{"candidate_id": person, "score": None}])

    page = await _page(job_id)

    assert _ids(page) == [person]
    assert page.total == 1
    row = page.rows[0]
    assert row.sources == ["full_base", "new_cv", "reassign"]
    assert row.score == 81.0
    assert single_list.SIMILAR in row.labels


async def test_pool_only_person_counts_like_full_base():
    job_id, (above, below) = await _world(2)
    await _pool(job_id, {above: 75, below: 55})

    page = await _page(job_id)

    by_id = {row.candidate_id: row for row in page.rows}
    assert by_id[above].sources == ["full_base"]
    assert by_id[above].below_threshold is False
    assert by_id[below].below_threshold is True
    assert _ids(page) == [above, below]
    assert page.counts["all"] == 1


async def test_evidence_prefers_the_proposal_over_the_pool():
    job_id, (person,) = await _world(1)
    await _pool(job_id, {person: 80})
    await _propose(
        job_id,
        "full_base",
        [
            {
                "candidate_id": person,
                "score": 72,
                "evidence": {"requirements": [{"key": "java", "status": "met"}]},
            }
        ],
    )
    row = (await _page(job_id)).rows[0]
    assert row.evidence.get("requirements")


async def test_pool_row_never_marks_a_person_as_new():
    job_id, (person,) = await _world(1)
    await _pool(job_id, {person: 80})
    assert (await _page(job_id)).rows[0].is_new is False


# ── Kto nie stoi na liście ──────────────────────────────────────────────────


async def test_people_in_the_recruitment_and_dismissed_are_off_the_list():
    job_id, (in_job, dismissed, kept) = await _world(3)
    await _pool(job_id, {in_job: 90, dismissed: 89, kept: 88})
    await _propose(job_id, "full_base", [{"candidate_id": dismissed, "score": 89}])
    async with AsyncSessionLocal() as db:
        db.add(
            CandidateStage(candidate_id=in_job, job_id=job_id, stage=PipelineStage.new)
        )
        await proposals.dismiss(db, job_id=job_id, candidate_id=dismissed, user_id=None)
        await db.commit()

    assert _ids(await _page(job_id)) == [kept]


async def test_pool_row_does_not_bring_back_a_removed_or_blacklisted_person():
    job_id, (removed, blacklisted, kept) = await _world(3)
    await _pool(job_id, {removed: 90, blacklisted: 89, kept: 88})
    async with AsyncSessionLocal() as db:
        db.add(
            CandidateStageRemoval(
                candidate_id=removed,
                job_id=job_id,
                removed_by=None,
                reason="remove_from_recruitment: test",
                last_stage="new",
                stage_count=1,
                stages_snapshot=[],
            )
        )
        person = await db.get(Candidate, blacklisted)
        person.status = CandidateStatus.blacklisted
        await db.commit()

    assert _ids(await _page(job_id)) == [kept]


async def test_expired_proposal_with_a_pool_row_stays_on_the_list():
    job_id, (person,) = await _world(1)
    await _propose(job_id, "full_base", [{"candidate_id": person, "score": 71}])
    async with AsyncSessionLocal() as db:
        await proposals.expire_open_for_job(db, job_id=job_id)
        await db.commit()
    assert _ids(await _page(job_id)) == []

    await _pool(job_id, {person: 71})
    assert _ids(await _page(job_id)) == [person]


# ── Filtry i liczby ─────────────────────────────────────────────────────────


async def test_filter_narrows_the_page_but_not_the_counts():
    job_id, (portal, similar, base) = await _world(3)
    await _propose(job_id, "job_board", [{"candidate_id": portal, "score": 66}])
    await _propose(job_id, "reassign", [{"candidate_id": similar, "score": None}])
    await _pool(job_id, {base: 80})

    everyone = await _page(job_id)
    only_portal = await _page(job_id, "portal")

    assert set(_ids(everyone)) == {portal, similar, base}
    assert _ids(only_portal) == [portal]
    assert only_portal.total == 1
    assert only_portal.counts == everyone.counts
    assert everyone.counts["portal"] == 1
    assert everyone.counts["similar"] == 1


async def test_portal_label_ends_with_the_posting_window():
    job_id, (old, fresh) = await _world(2)
    await _propose(
        job_id,
        "job_board",
        [
            {"candidate_id": old, "score": 66},
            {"candidate_id": fresh, "score": 66},
        ],
    )
    async with AsyncSessionLocal() as db:
        row = await db.scalar(
            select(JobProposal).where(
                JobProposal.job_id == job_id, JobProposal.candidate_id == old
            )
        )
        row.first_seen_at = datetime.now(timezone.utc) - timedelta(days=8)
        await db.commit()

    assert _ids(await _page(job_id, "portal")) == [fresh]


async def test_new_in_base_filter_uses_the_first_ids():
    job_id, (fresh, other) = await _world(2)
    await _pool(job_id, {fresh: 72, other: 90})

    page = await _page(job_id, first_ids=[fresh])

    assert _ids(page) == [fresh, other]
    assert _ids(await _page(job_id, "new_in_base", first_ids=[fresh])) == [fresh]
    assert page.counts["new_in_base"] == 1


async def test_paging_is_stable_and_complete():
    job_id, people = await _world(5)
    await _pool(job_id, {cid: 90 - i for i, cid in enumerate(people)})

    first = await _page(job_id, limit=2)
    second = await _page(job_id, limit=2, offset=2)
    third = await _page(job_id, limit=2, offset=4)

    assert _ids(first) + _ids(second) + _ids(third) == people
    assert first.total == 5


async def test_split_counts_match_the_list():
    job_id, (portal, above, below) = await _world(3)
    await _propose(job_id, "job_board", [{"candidate_id": portal, "score": 66}])
    await _pool(job_id, {above: 80, below: 40})

    async with AsyncSessionLocal() as db:
        split = await single_list.split_counts(
            db,
            job_id=job_id,
            since=datetime.now(timezone.utc) - timedelta(days=7),
            min_score=70.0,
        )
    page = await _page(job_id)

    assert split == {"postings_recent": 1, "base": 1, "below_threshold": 1}
    assert split["postings_recent"] + split["base"] == page.counts["all"]


# ── Kolejność ───────────────────────────────────────────────────────────────


async def test_order_reassign_then_new_in_base_then_score_then_below():
    job_id, (below, top, fresh, moved) = await _world(4)
    await _pool(job_id, {below: 50, top: 95, fresh: 71})
    await _propose(job_id, "reassign", [{"candidate_id": moved, "score": None}])

    assert _ids(await _page(job_id, first_ids=[fresh])) == [moved, fresh, top, below]


async def test_missing_critical_goes_to_the_end_of_the_counted_people(monkeypatch):
    from app.services import critical_skills

    monkeypatch.setattr(
        critical_skills,
        "effective_critical",
        lambda job: critical_skills.CriticalResolution(
            labels=("SailPoint",), source="none", suggested=(), decided=False
        ),
    )
    job_id, (lacking, plain) = await _world(2)
    await _propose(
        job_id,
        "new_cv",
        [
            {
                "candidate_id": lacking,
                "score": 90,
                "evidence": {"missing_must": ["SailPoint"]},
            },
            {"candidate_id": plain, "score": 75, "evidence": {"missing_must": []}},
        ],
    )

    assert _ids(await _page(job_id)) == [plain, lacking]


def test_missing_ordinary_must_is_not_a_missing_critical(monkeypatch):
    from app.services import critical_skills

    monkeypatch.setattr(
        critical_skills,
        "effective_critical",
        lambda job: SimpleNamespace(labels=["SailPoint"]),
    )
    job = SimpleNamespace()
    assert single_list._missing_critical(job, {"missing_must": ["Excel"]}) == ()
    assert single_list._missing_critical(job, {"missing_must": ["sailpoint"]}) == (
        "sailpoint",
    )
    assert single_list._missing_critical(job, None) == ()


# ── Skala „Dop.” i portale ──────────────────────────────────────────────────


def test_portal_score_with_the_flag_off_changes_nothing(monkeypatch):
    monkeypatch.setattr(settings, "SINGLE_CANDIDATE_LIST_ENABLED", False)
    evidence = {"auto_match": {"score": 66}}
    assert single_list.portal_score(1, 66, evidence, {1: 80.0}) == (66, evidence)


def test_portal_score_without_a_current_vector_stays_empty():
    evidence = {"auto_match": {"score": 66}}
    assert single_list.portal_score(1, 66, evidence, {}) == (None, evidence)


def test_portal_score_with_a_vector_marks_the_scale():
    score, evidence = single_list.portal_score(
        1, 66, {"auto_match": {"score": 66}}, {1: 80.5}
    )
    assert score == 80.5
    assert evidence == {"auto_match": {"score": 66}, "dop_scale": True}


def test_integration_without_a_result_still_gets_the_scale_marker():
    assert single_list.portal_score(1, None, None, {1: 72.0}) == (
        72.0,
        {"dop_scale": True},
    )


def test_only_true_survives_as_the_scale_marker():
    assert proposals.sanitize_evidence({"dop_scale": True}) == {"dop_scale": True}
    assert proposals.sanitize_evidence({"dop_scale": "tak"}) is None


async def test_old_scraper_score_never_shows_as_dop():
    job_id, (old,) = await _world(1)
    await _propose(
        job_id,
        "job_board",
        [
            {
                "candidate_id": old,
                "score": 66,
                "evidence": {"auto_match": {"score": 66}},
            }
        ],
    )
    row = (await _page(job_id)).rows[0]
    assert row.score is None
    assert row.board_score == 66.0


async def test_marked_portal_row_shows_dop_and_keeps_the_scraper_number():
    job_id, (person,) = await _world(1)
    await _propose(
        job_id,
        "job_board",
        [
            {
                "candidate_id": person,
                "score": 80.5,
                "evidence": {"auto_match": {"score": 66}, "dop_scale": True},
            }
        ],
    )
    row = (await _page(job_id)).rows[0]
    assert row.score == 80.5
    assert row.board_score == 66.0


async def test_proposals_bulk_writes_dop_when_the_vector_is_current(monkeypatch):
    job_id, (scored, waiting) = await _world(2)

    async def fake_scores(_db, _job, candidates):
        return {c.id: 77.0 for c in candidates if c.id == scored}

    monkeypatch.setattr(single_list, "dop_scores", fake_scores)
    async with AsyncSessionLocal() as db:
        job = await db.get(Job, job_id)
        await propose_candidates_for_job(
            db,
            job=job,
            candidate_ids=[scored, waiting],
            entry_meta={"score": 66, "source": "jjit"},
        )
        await db.commit()
    async with AsyncSessionLocal() as db:
        rows = {
            r.candidate_id: r
            for r in (
                await db.scalars(
                    select(JobProposal).where(JobProposal.job_id == job_id)
                )
            ).all()
        }
    assert rows[scored].score == Decimal("77.00")
    assert rows[scored].evidence["dop_scale"] is True
    assert rows[scored].evidence["auto_match"]["score"] == 66
    assert rows[waiting].score is None
    assert "dop_scale" not in rows[waiting].evidence


async def test_proposals_bulk_with_the_flag_off_stores_the_scraper_score(monkeypatch):
    monkeypatch.setattr(settings, "SINGLE_CANDIDATE_LIST_ENABLED", False)
    job_id, (person,) = await _world(1)
    async with AsyncSessionLocal() as db:
        job = await db.get(Job, job_id)
        await propose_candidates_for_job(
            db, job=job, candidate_ids=[person], entry_meta={"score": 66}
        )
        await db.commit()
    async with AsyncSessionLocal() as db:
        row = await db.scalar(select(JobProposal).where(JobProposal.job_id == job_id))
    assert row.score == Decimal("66.00")
    assert "dop_scale" not in (row.evidence or {})


async def test_failed_scoring_leaves_the_row_without_a_number(monkeypatch):
    job_id, (person,) = await _world(1)

    async def boom(*_a, **_k):
        raise RuntimeError("wektor")

    monkeypatch.setattr("app.services.canonical_fit.score_candidates", boom)
    async with AsyncSessionLocal() as db:
        job = await db.get(Job, job_id)
        candidate = await db.get(Candidate, person)
        assert await single_list.dop_scores(db, job, [candidate]) == {}


async def test_cv_queue_fills_only_waiting_portal_rows():
    job_id, (waiting, old) = await _world(2)
    await _propose(
        job_id,
        "job_board",
        [
            {"candidate_id": waiting, "score": None},
            {"candidate_id": old, "score": 66},
        ],
    )
    async with AsyncSessionLocal() as db:
        filled = await single_list.fill_portal_scores(
            db,
            [
                SimpleNamespace(job_id=job_id, candidate_id=waiting, score=78.0),
                SimpleNamespace(job_id=job_id, candidate_id=old, score=78.0),
            ],
        )
        await db.commit()
    assert filled == 1
    page = await _page(job_id)
    by_id = {row.candidate_id: row for row in page.rows}
    assert by_id[waiting].score == 78.0
    assert by_id[old].score is None
    assert by_id[old].board_score == 66.0


async def test_cv_queue_fill_with_the_flag_off_is_a_no_op(monkeypatch):
    monkeypatch.setattr(settings, "SINGLE_CANDIDATE_LIST_ENABLED", False)
    job_id, (waiting,) = await _world(1)
    await _propose(job_id, "job_board", [{"candidate_id": waiting, "score": None}])
    async with AsyncSessionLocal() as db:
        assert (
            await single_list.fill_portal_scores(
                db, [SimpleNamespace(job_id=job_id, candidate_id=waiting, score=78.0)]
            )
            == 0
        )


# ── Silnik kart ─────────────────────────────────────────────────────────────


async def test_engine_gives_the_same_picks_with_and_without_the_flag(monkeypatch):
    job_id, (pooled, proposed, portal) = await _world(3)
    await _pool(job_id, {pooled: 88})
    await _propose(job_id, "new_cv", [{"candidate_id": proposed, "score": 77}])
    await _propose(
        job_id,
        "job_board",
        [
            {
                "candidate_id": portal,
                "score": 95,
                "evidence": {"dop_scale": True},
            }
        ],
    )

    async def picks() -> list[tuple[int, float]]:
        async with AsyncSessionLocal() as db:
            return [
                (p.candidate_id, p.score)
                for p in await autofill.ranked_picks(db, job_id, limit=20)
            ]

    with_flag = await picks()
    monkeypatch.setattr(settings, "SINGLE_CANDIDATE_LIST_ENABLED", False)
    without_flag = await picks()

    assert with_flag == without_flag == [(pooled, 88.0), (proposed, 77.0)]


async def test_by_rules_keep_all_turns_refusals_into_cautions():
    job_id, (dear,) = await _world(1)
    async with AsyncSessionLocal() as db:
        job = await db.get(Job, job_id)
        job.rate_budget_hourly = Decimal("100")
        person = await db.get(Candidate, dear)
        person.rate_from_hourly = Decimal("200")
        person.rate_from_computed_at = datetime.now(timezone.utc)
        await db.commit()
    pick = autofill.Pick(dear, 80.0, None, (), ())
    async with AsyncSessionLocal() as db:
        job = await db.get(Job, job_id)
        strict = await autofill._by_rules(db, job, [pick])
        kept = await autofill._by_rules(db, job, [pick], keep_all=True)
    assert strict == []
    assert [p.candidate_id for p in kept] == [dear]
    assert kept[0].cautions[0]["key"] == "budget"


# ── Pomiń i Cofnij ──────────────────────────────────────────────────────────


async def test_reopen_pool_only_brings_the_person_back_after_undo():
    job_id, (person,) = await _world(1)
    await _pool(job_id, {person: 83})
    async with AsyncSessionLocal() as db:
        assert (
            await single_list.reopen_pool_only(db, job_id=job_id, candidate_id=person)
            == 1
        )
        await db.commit()
    async with AsyncSessionLocal() as db:
        row = await db.scalar(select(JobProposal).where(JobProposal.job_id == job_id))
    assert (row.source, row.status, row.score) == (
        "full_base",
        "proposed",
        Decimal("83.00"),
    )


async def test_reopen_pool_only_leaves_people_with_a_proposal_alone():
    job_id, (person,) = await _world(1)
    await _pool(job_id, {person: 83})
    await _propose(job_id, "new_cv", [{"candidate_id": person, "score": 80}])
    async with AsyncSessionLocal() as db:
        assert (
            await single_list.reopen_pool_only(db, job_id=job_id, candidate_id=person)
            == 0
        )


async def test_reopen_pool_only_with_the_flag_off_is_a_no_op(monkeypatch):
    monkeypatch.setattr(settings, "SINGLE_CANDIDATE_LIST_ENABLED", False)
    job_id, (person,) = await _world(1)
    await _pool(job_id, {person: 83})
    async with AsyncSessionLocal() as db:
        assert (
            await single_list.reopen_pool_only(db, job_id=job_id, candidate_id=person)
            == 0
        )


# ── Trasy ───────────────────────────────────────────────────────────────────


async def _recruiter(job_id: int) -> tuple[int, dict[str, str]]:
    tag = uuid.uuid4().hex[:8]
    async with AsyncSessionLocal() as db:
        user = User(
            email=f"single-{tag}@example.com",
            password_hash=hash_password(f"T3st_{tag}!Single"),
            name="Single list",
            role=UserRole.recruiter,
            is_active=True,
        )
        db.add(user)
        await db.flush()
        job = await db.get(Job, job_id)
        job.recruiter_id = user.id
        await db.commit()
        return user.id, {
            "Authorization": f"Bearer {create_access_token(user.id, 'recruiter')}"
        }


def _inbox(job_id: int) -> str:
    return f"/api/jobs/{job_id}/proposal-inbox"


async def test_route_returns_labels_and_counts(
    app_client: AsyncClient, app_auth_headers: dict
):
    job_id, (portal, base) = await _world(2)
    await _propose(job_id, "job_board", [{"candidate_id": portal, "score": 66}])
    await _pool(job_id, {base: 80})

    response = await app_client.get(_inbox(job_id), headers=app_auth_headers)

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["single_list"] is True
    assert body["label_counts"]["portal"] == 1
    by_id = {item["candidate"]["id"]: item for item in body["items"]}
    assert by_id[portal]["labels"] == ["portal"]
    assert "portal" not in by_id[base]["labels"]

    narrowed = await app_client.get(
        _inbox(job_id), params={"list": "portal"}, headers=app_auth_headers
    )
    assert [i["candidate"]["id"] for i in narrowed.json()["items"]] == [portal]


async def test_route_with_the_flag_off_is_todays_inbox(
    app_client: AsyncClient, app_auth_headers: dict, monkeypatch
):
    monkeypatch.setattr(settings, "SINGLE_CANDIDATE_LIST_ENABLED", False)
    job_id, (pooled, proposed) = await _world(2)
    await _pool(job_id, {pooled: 80})
    await _propose(job_id, "new_cv", [{"candidate_id": proposed, "score": 75}])

    body = (await app_client.get(_inbox(job_id), headers=app_auth_headers)).json()
    counts = (
        await app_client.get(
            f"/api/jobs/{job_id}/proposal-counts", headers=app_auth_headers
        )
    ).json()

    assert [i["candidate"]["id"] for i in body["items"]] == [proposed]
    assert "single_list" not in body
    assert "labels" not in body["items"][0]
    assert "single_list" not in counts


async def test_route_refuses_an_unknown_filter(
    app_client: AsyncClient, app_auth_headers: dict
):
    job_id, _people = await _world(1)
    response = await app_client.get(
        _inbox(job_id), params={"list": "kogos"}, headers=app_auth_headers
    )
    assert response.status_code == 422


async def test_route_needs_a_login(app_client: AsyncClient):
    job_id, _people = await _world(1)
    response = await app_client.get(_inbox(job_id), params={"list": "portal"})
    assert response.status_code == 401


async def test_bulk_dismiss_covers_pool_only_people(app_client: AsyncClient):
    job_id, (pooled, stranger) = await _world(2)
    await _pool(job_id, {pooled: 80})
    _user_id, headers = await _recruiter(job_id)

    response = await app_client.post(
        f"{_inbox(job_id)}/dismiss-bulk",
        json={
            "candidate_ids": [pooled, stranger],
            "reason": "too_expensive",
        },
        headers=headers,
    )

    assert response.status_code == 200, response.text
    assert response.json()["dismissed"] == [pooled]
    assert response.json()["skipped"] == [stranger]
    assert _ids(await _page(job_id)) == []


def test_flag_is_off_by_default():
    assert type(settings).model_fields["SINGLE_CANDIDATE_LIST_ENABLED"].default is False
