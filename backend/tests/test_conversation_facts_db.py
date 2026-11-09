"""Rejestr faktów z rozmów na prawdziwym Postgresie (08.11.2026)."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from decimal import Decimal

import pytest
from httpx import AsyncClient
from sqlalchemy import false, select

import app.models  # noqa: F401
from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.models.candidate import Candidate
from app.models.candidate_auto_match import CandidateMatchOutbox
from app.models.candidate_conversation_fact import CandidateConversationFact as Fact
from app.models.client import Client
from app.models.job import Job, JobStatus
from app.models.job_autofill_pool import JobAutofillPool
from app.models.user import User
from app.services import conversation_facts as facts
from app.services import new_column_autofill as autofill
from app.services import scoring_service, skill_normalize
from app.services.candidate_search_predicates import Semantics, skill_match
from tests.test_screening_form import _put, _world


@pytest.fixture(autouse=True)
def facts_on(monkeypatch):
    aliases = {"kafka": "kafka", "java": "java", "pl/sql": "pl/sql"}
    monkeypatch.setattr(skill_normalize, "ALIAS_TO_CANONICAL", aliases)
    monkeypatch.setattr(scoring_service, "ALIAS_MAP", aliases)
    monkeypatch.setattr(skill_normalize, "TECH_CANONICALS", set(aliases))
    monkeypatch.setattr(scoring_service, "_CHAMPION_ALIAS_PATTERN", None)
    monkeypatch.setattr(settings, "CONVERSATION_FACTS_ENABLED", True)
    monkeypatch.setattr(settings, "AUTO_MATCH_ENABLED", True)
    yield
    scoring_service._CHAMPION_ALIAS_PATTERN = None


def _sheet(*checks: dict) -> dict:
    return {
        "answers": [{"question_id": "q1", "response": "Tak"}],
        "experience_checks": list(checks),
        "overall_fit": "fit",
    }


def _check(name: str, status: str, kind: str = "skills", note: str = "") -> dict:
    return {"kind": kind, "name": name, "status": status, "note": note}


async def _facts(candidate_id: int, *, active: bool = True) -> list[Fact]:
    async with AsyncSessionLocal() as db:
        query = select(Fact).where(Fact.candidate_id == candidate_id)
        if active:
            query = query.where(Fact.retired_at.is_(None))
        return list((await db.scalars(query.order_by(Fact.id))).all())


async def _candidate(candidate_id: int) -> Candidate:
    async with AsyncSessionLocal() as db:
        return await db.get(Candidate, candidate_id)


async def test_saved_sheet_reaches_register_profile_and_queue(app_client: AsyncClient):
    world = await _world()
    await _put(
        app_client,
        world,
        expected=0,
        sheet=_sheet(
            _check("Kafka", "confirmed", note="3 lata w banku"),
            _check("Java", "not_confirmed"),
            _check("Prowadzenie warsztatów", "confirmed"),
            _check("Energetyka", "unknown", kind="domains"),
        ),
    )
    rows = {row.value: row for row in await _facts(world["cand_id"])}
    assert set(rows) == {"Kafka", "Java", "Prowadzenie warsztatów"}
    assert rows["Kafka"].evidence == "3 lata w banku"
    assert rows["Kafka"].source == "sheet"
    assert rows["Kafka"].job_id == world["job_id"]
    assert rows["Kafka"].author_id == world["rec_id"]
    assert rows["Java"].status == "absent"
    assert rows["Prowadzenie warsztatów"].canonical_terms == []

    candidate = await _candidate(world["cand_id"])
    assert [s["name"] for s in candidate.skills] == ["Kafka"]
    projection = candidate.cv_extracted_data[facts.PROJECTION_KEY]
    assert projection["absent"] == ["java"]
    assert projection["confirmed"] == ["kafka"]

    async with AsyncSessionLocal() as db:
        events = (
            await db.scalars(
                select(CandidateMatchOutbox).where(
                    CandidateMatchOutbox.candidate_id == world["cand_id"]
                )
            )
        ).all()
    assert [event.trigger for event in events] == ["conversation"]


async def test_withdrawn_click_retires_the_fact_and_the_skill(app_client: AsyncClient):
    world = await _world()
    await _put(
        app_client, world, expected=0, sheet=_sheet(_check("Kafka", "confirmed"))
    )
    await _put(app_client, world, expected=1, sheet=_sheet(_check("Kafka", "unknown")))

    assert await _facts(world["cand_id"]) == []
    assert len(await _facts(world["cand_id"], active=False)) == 1
    candidate = await _candidate(world["cand_id"])
    assert candidate.skills == []
    assert candidate.cv_extracted_data[facts.PROJECTION_KEY]["confirmed"] == []


async def test_saving_the_same_sheet_keeps_one_row(app_client: AsyncClient):
    world = await _world()
    sheet = _sheet(_check("Kafka", "confirmed"))
    await _put(app_client, world, expected=0, sheet=sheet)
    await _put(app_client, world, expected=1, sheet=sheet)
    assert len(await _facts(world["cand_id"], active=False)) == 1


async def test_curated_skill_list_stays_untouched(app_client: AsyncClient):
    world = await _world()
    async with AsyncSessionLocal() as db:
        candidate = await db.get(Candidate, world["cand_id"])
        candidate.skills = [{"name": "Python", "level": None}]
        candidate.cv_extracted_data = {"_manual_override_skills": True}
        await db.commit()
    await _put(
        app_client, world, expected=0, sheet=_sheet(_check("Kafka", "confirmed"))
    )
    candidate = await _candidate(world["cand_id"])
    assert [s["name"] for s in candidate.skills] == ["Python"]
    assert len(await _facts(world["cand_id"])) == 1


async def test_flag_off_leaves_no_trace(app_client: AsyncClient, monkeypatch):
    monkeypatch.setattr(settings, "CONVERSATION_FACTS_ENABLED", False)
    world = await _world()
    await _put(
        app_client, world, expected=0, sheet=_sheet(_check("Kafka", "confirmed"))
    )
    assert await _facts(world["cand_id"], active=False) == []
    candidate = await _candidate(world["cand_id"])
    assert not candidate.skills
    assert facts.PROJECTION_KEY not in (candidate.cv_extracted_data or {})


async def test_route_shows_origin_and_hides_behind_the_flag(
    app_client: AsyncClient, monkeypatch
):
    world = await _world()
    await _put(
        app_client, world, expected=0, sheet=_sheet(_check("Kafka", "confirmed"))
    )
    url = f"/api/candidates/{world['cand_id']}/conversation-facts"
    body = (await app_client.get(url, headers=world["rec_h"])).json()
    assert body["enabled"] is True
    assert body["facts"][0]["value"] == "Kafka"
    assert body["facts"][0]["source"] == "sheet"
    assert body["facts"][0]["job_only"] is False

    monkeypatch.setattr(settings, "CONVERSATION_FACTS_ENABLED", False)
    body = (await app_client.get(url, headers=world["rec_h"])).json()
    assert body == {"candidate_id": world["cand_id"], "enabled": False, "facts": []}


async def test_sheet_fields_write_to_the_profile(app_client: AsyncClient):
    world = await _world()
    body = await _put(
        app_client,
        world,
        expected=0,
        profile={
            "notice_period": 1,
            "notice_period_unit": "months",
            "max_onsite_days": 2,
        },
    )
    assert body["profile_fields"]["notice_period"] == 1
    assert body["profile_fields"]["work_modes"] == ["remote", "hybrid"]
    candidate = await _candidate(world["cand_id"])
    assert candidate.notice_period == 1
    assert candidate.notice_period_unit == "months"
    assert candidate.max_onsite_days_per_week == 2


async def test_sheet_fields_are_ignored_with_flag_off(
    app_client: AsyncClient, monkeypatch
):
    monkeypatch.setattr(settings, "CONVERSATION_FACTS_ENABLED", False)
    world = await _world()
    body = await _put(app_client, world, expected=0, profile={"notice_period": 1})
    assert body["profile_fields"] is None
    assert (await _candidate(world["cand_id"])).notice_period is None


async def _search_ids(sem, skill: str, ids: list[int]) -> set[int]:
    async with AsyncSessionLocal() as db:
        return set(
            (
                await db.scalars(
                    select(Candidate.id).where(
                        Candidate.id.in_(ids), skill_match(skill, sem)
                    )
                )
            ).all()
        )


@pytest.mark.parametrize("engine", ["list", "search"])
async def test_both_search_engines_answer_alike(engine: str):
    tag = uuid.uuid4().hex[:8]
    async with AsyncSessionLocal() as db:
        confirmed = Candidate(
            name="Potwierdzona",
            lastname=tag,
            skills=[],
            cv_extracted_data={
                facts.PROJECTION_KEY: {"confirmed": ["kafka"], "absent": []}
            },
        )
        absent = Candidate(
            name="Brak",
            lastname=tag,
            skills=[{"name": "kafka"}],
            cv_extracted_data={
                facts.PROJECTION_KEY: {"confirmed": [], "absent": ["kafka"]}
            },
        )
        plain = Candidate(name="Zwykła", lastname=tag, skills=[{"name": "kafka"}])
        other = Candidate(name="Inna", lastname=tag, skills=[], cv_extracted_data=None)
        db.add_all([confirmed, absent, plain, other])
        await db.commit()
        ids = [confirmed.id, absent.id, plain.id, other.id]
    sem = Semantics(version=2, engine=engine)
    assert await _search_ids(sem, "Kafka", ids) == {confirmed.id, plain.id}


async def _autofill_world() -> dict:
    tag = uuid.uuid4().hex[:8]
    async with AsyncSessionLocal() as db:
        client = Client(name=f"WetoKlient {tag}")
        db.add(client)
        await db.flush()
        job = Job(
            title=f"Weto {tag}",
            client_id=client.id,
            status=JobStatus.published,
            work_state="searching",
        )
        vetoed = Candidate(
            name="Weto",
            lastname=tag,
            cv_extracted_data={
                "_notes_insights": {
                    "client_vetoes": [{"client": client.name, "reason": "Nie chce"}]
                }
            },
        )
        not_looking = Candidate(
            name="Nie szuka",
            lastname=tag,
            cv_extracted_data={"_notes_insights": {"not_looking_until": "2099-01"}},
        )
        free = Candidate(name="Wolna", lastname=tag, cv_extracted_data={})
        db.add_all([job, vetoed, not_looking, free])
        await db.flush()
        db.add_all(
            [
                JobAutofillPool(
                    job_id=job.id,
                    candidate_id=person.id,
                    score=Decimal("80"),
                    run_id="run-weto",
                    evidence={"matched_must": [], "missing_must": []},
                )
                for person in (vetoed, not_looking, free)
            ]
        )
        await db.commit()
        return {
            "job_id": job.id,
            "vetoed": vetoed.id,
            "not_looking": not_looking.id,
            "free": free.id,
        }


async def _picked(job_id: int) -> set[int]:
    async with AsyncSessionLocal() as db:
        picks = await autofill.ranked_picks(db, job_id, limit=20)
    return {pick.candidate_id for pick in picks}


async def test_veto_and_not_looking_stay_out_of_card_picks():
    world = await _autofill_world()
    assert await _picked(world["job_id"]) == {world["free"]}


async def test_flag_off_picks_them_as_before(monkeypatch):
    monkeypatch.setattr(settings, "CONVERSATION_FACTS_ENABLED", False)
    world = await _autofill_world()
    assert await _picked(world["job_id"]) == {
        world["vetoed"],
        world["not_looking"],
        world["free"],
    }


async def test_note_reading_respects_a_curated_list_on_a_dirty_candidate():
    """UPDATE przy flushu wygasza `skills_manually_curated`; blokada ma zostać."""
    from app.models.activity import Activity

    tag = uuid.uuid4().hex[:8]
    async with AsyncSessionLocal() as db:
        person = Candidate(
            name="Kuratorka",
            lastname=tag,
            skills=[{"name": "Python", "level": None}],
            cv_extracted_data={},
        )
        db.add(person)
        await db.flush()
        reviewer = (await db.execute(select(User.id).limit(1))).scalar_one()
        db.add(
            Activity(
                entity_type="candidate",
                entity_id=person.id,
                action="updated",
                external_source="manual",
                user_id=reviewer,
                details={"skills": ["Python"]},
            )
        )
        await db.commit()
        person_id = person.id

    async with AsyncSessionLocal() as db:
        person = await db.get(Candidate, person_id)
        person.cv_extracted_data = {"_notes_insights": {"matching_facts": "x"}}
        await facts.record_note_facts(
            db,
            candidate=person,
            parsed={"skills_evidenced": [{"name": "Kafka", "evidence": "rozmowa"}]},
            note_id=None,
            noted_at=datetime.now(timezone.utc),
        )
        await db.commit()

    person = await _candidate(person_id)
    assert [s["name"] for s in person.skills] == ["Python"]
    assert len(await _facts(person_id)) == 1


async def test_route_hides_details_of_a_recruitment_out_of_scope(
    app_client: AsyncClient,
):
    world = await _world()
    await _put(
        app_client,
        world,
        expected=0,
        sheet=_sheet(
            _check("Kafka", "confirmed", note="poufny dopisek"),
            _check("Prowadzenie warsztatów", "confirmed"),
        ),
    )
    # Rekruter i Delivery Lead omijają zakres, więc sprawdzamy sam filtr.
    async with AsyncSessionLocal() as db:
        listed = await facts.list_for_profile(
            db, candidate_id=world["cand_id"], job_scope=false()
        )
    rows = {row["value"]: row for row in listed}
    assert set(rows) == {"Kafka"}
    assert rows["Kafka"]["evidence"] is None
    assert rows["Kafka"]["job_id"] is None
    assert rows["Kafka"]["job_title"] is None
