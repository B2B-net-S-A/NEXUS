from __future__ import annotations

import asyncio
import os
import re
import uuid
from unittest.mock import AsyncMock, Mock

import app.models  # noqa: F401
import pytest
from sqlalchemy import select

from app.models.candidate import Candidate
from app.models.user import User, UserRole
from app.services.candidate_location_writer import (
    apply_candidate_location_from_source,
    normalize_candidate_location,
    project_candidate_location,
    sync_candidate_location_from_source,
)


def test_normalizes_traffit_json_blob_into_canonical_facts():
    location = normalize_candidate_location(
        raw_location={
            "locality": " Warszawa ",
            "region1": "Mazowieckie",
            "country": "Polska",
        }
    )

    assert location.city == "Warszawa"
    assert location.country == "PL"
    assert location.projection == "Warszawa, PL"


def test_parses_country_suffix_and_projection_is_deterministic():
    location = normalize_candidate_location(raw_location="Berlin, de")

    assert location.city == "Berlin"
    assert location.country == "DE"
    assert project_candidate_location(location.city, location.country) == "Berlin, DE"


def test_automated_source_cannot_overwrite_manual_city_or_country_locks():
    candidate = Candidate(
        id=1,
        name="Jan",
        lastname="Nowak",
        city="Kraków",
        country="PL",
        location="stale legacy text",
        cv_extracted_data={
            "_manual_override_city": True,
            "_manual_override_country": True,
        },
    )

    changed = apply_candidate_location_from_source(
        candidate,
        city="Berlin",
        country="DE",
        overwrite_existing=True,
    )

    assert changed is True  # only the stale compatibility projection changed
    assert candidate.city == "Kraków"
    assert candidate.country == "PL"
    assert candidate.location == "Kraków, PL"


def test_city_lock_does_not_block_unlocked_country_update():
    candidate = Candidate(
        id=2,
        name="Anna",
        lastname="Nowak",
        city="Kraków",
        country="PL",
        location="Kraków, PL",
        cv_extracted_data={"_manual_override_city": "true"},
    )

    apply_candidate_location_from_source(
        candidate,
        city="Berlin",
        country="DE",
        overwrite_existing=True,
    )

    assert candidate.city == "Kraków"
    assert candidate.country == "DE"
    assert candidate.location == "Kraków, DE"


def test_cv_style_fill_only_preserves_existing_city_and_repairs_projection():
    candidate = Candidate(
        id=3,
        name="Ola",
        lastname="Nowak",
        city="Gdańsk",
        country="PL",
        location="old",
        cv_extracted_data={},
    )

    apply_candidate_location_from_source(
        candidate,
        city="Warszawa",
        overwrite_existing=False,
    )

    assert candidate.city == "Gdańsk"
    assert candidate.country == "PL"
    assert candidate.location == "Gdańsk, PL"


@pytest.mark.asyncio
async def test_db_location_writer_refreshes_locked_candidate_before_manual_lock_check():
    candidate = Candidate(
        id=3,
        name="Ola",
        lastname="Nowak",
        city="Kraków",
        country="PL",
        location="Kraków, PL",
        cv_extracted_data={
            "_manual_override_city": True,
            "_manual_override_country": True,
        },
    )
    db = Mock()
    db.scalar = AsyncMock(return_value=candidate)
    db.flush = AsyncMock()

    changed = await sync_candidate_location_from_source(
        db,
        candidate_id=3,
        city="Berlin",
        country="DE",
        overwrite_existing=True,
    )

    statement = db.scalar.await_args.args[0]
    assert statement.get_execution_options()["populate_existing"] is True
    assert statement._for_update_arg is not None
    assert changed is False
    assert candidate.city == "Kraków"
    assert candidate.country == "PL"
    db.flush.assert_not_awaited()


@pytest.mark.skipif(
    not os.environ.get("DATABASE_URL"),
    reason="PostgreSQL concurrency test; hosted CI provides DATABASE_URL",
)
@pytest.mark.asyncio
async def test_manual_location_and_parser_serialize_without_losing_locks_or_provenance():
    from app.api.candidates import update_candidate_location
    from app.core.database import AsyncSessionLocal
    from app.schemas.candidate import CandidateLocationUpdate

    marker = uuid.uuid4().hex[:10]
    async with AsyncSessionLocal() as seed_db:
        actor = User(
            email=f"location-race-{marker}@example.com",
            name="Location Race",
            role=UserRole.admin,
            roles=[UserRole.admin.value],
            is_active=True,
        )
        candidate = Candidate(
            name="Location",
            lastname=f"Race-{marker}",
            cv_extracted_data={},
        )
        seed_db.add_all([actor, candidate])
        await seed_db.commit()
        await seed_db.refresh(actor)
        await seed_db.refresh(candidate)
        actor_id = actor.id
        candidate_id = candidate.id

    # Parser owns the row first. The manual PATCH must wait, then merge its
    # locks into the parser's freshly committed provenance instead of an old
    # JSONB snapshot.
    async with AsyncSessionLocal() as parser_db, AsyncSessionLocal() as manual_db:
        parser_candidate = await parser_db.scalar(
            select(Candidate).where(Candidate.id == candidate_id).with_for_update()
        )
        assert parser_candidate is not None
        parser_candidate.cv_extracted_data = {
            "cv_highlights": {"source_document_id": 777},
            "_source": "race-parser",
        }
        await parser_db.flush()

        manual_task = asyncio.create_task(
            update_candidate_location(
                candidate_id=candidate_id,
                data=CandidateLocationUpdate(city="Kraków", country="PL"),
                current_user=User(id=actor_id),  # type: ignore[arg-type]
                db=manual_db,
            )
        )
        await asyncio.sleep(0.05)
        assert not manual_task.done()
        await parser_db.commit()
        await asyncio.wait_for(manual_task, timeout=5)
        await manual_db.commit()

    async with AsyncSessionLocal() as verify_db:
        verified = await verify_db.get(Candidate, candidate_id)
        assert verified is not None
        assert verified.city == "Kraków"
        assert verified.country == "PL"
        assert verified.location == "Kraków, PL"
        assert verified.cv_extracted_data["cv_highlights"] == {
            "source_document_id": 777
        }
        assert verified.cv_extracted_data["_source"] == "race-parser"
        assert verified.cv_extracted_data["_manual_override_city"] is True
        assert verified.cv_extracted_data["_manual_override_country"] is True

    # Manual PATCH owns the row first. The automated writer waits and then
    # observes both locks, so neither canonical location value can be replaced.
    async with AsyncSessionLocal() as manual_db, AsyncSessionLocal() as parser_db:
        await update_candidate_location(
            candidate_id=candidate_id,
            data=CandidateLocationUpdate(city="Gdańsk", country="PL"),
            current_user=User(id=actor_id),  # type: ignore[arg-type]
            db=manual_db,
        )

        async def parser_after_manual_lock() -> None:
            await sync_candidate_location_from_source(
                parser_db,
                candidate_id=candidate_id,
                city="Berlin",
                country="DE",
                overwrite_existing=True,
            )
            refreshed = await parser_db.get(Candidate, candidate_id)
            assert refreshed is not None
            extracted = dict(refreshed.cv_extracted_data or {})
            extracted["cv_highlights"] = {"source_document_id": 888}
            refreshed.cv_extracted_data = extracted
            await parser_db.commit()

        parser_task = asyncio.create_task(parser_after_manual_lock())
        await asyncio.sleep(0.05)
        assert not parser_task.done()
        await manual_db.commit()
        await asyncio.wait_for(parser_task, timeout=5)

    async with AsyncSessionLocal() as verify_db:
        verified = await verify_db.get(Candidate, candidate_id)
        assert verified is not None
        assert (verified.city, verified.country, verified.location) == (
            "Gdańsk",
            "PL",
            "Gdańsk, PL",
        )
        assert verified.cv_extracted_data["cv_highlights"] == {
            "source_document_id": 888
        }
        assert verified.cv_extracted_data["_manual_override_city"] is True
        assert verified.cv_extracted_data["_manual_override_country"] is True


def test_importer_raw_sql_never_authors_location_columns():
    from app.services.talent_radar_importer import (
        _MERGE_CV_INTO_EXISTING,
        TalentRadarImporter,
    )
    from app.services.traffit.importer import (
        _UPDATE_CANDIDATE_ADOPT,
        _UPSERT_CANDIDATE,
    )

    authored_location = re.compile(
        r"(?<![a-z_])(city|country|location)(?![a-z_])",
        re.IGNORECASE,
    )
    statements = (
        _UPSERT_CANDIDATE,
        _UPDATE_CANDIDATE_ADOPT,
        _MERGE_CV_INTO_EXISTING,
        TalentRadarImporter._INSERT_SQL,
    )

    for statement in statements:
        assert authored_location.search(str(statement)) is None

    # The statements that replace imported metadata preserve canonical manual
    # locks before the location writer evaluates them.
    for statement in (_UPSERT_CANDIDATE, _UPDATE_CANDIDATE_ADOPT):
        sql = str(statement)
        assert "_manual_override_city" in sql
        assert "_manual_override_country" in sql
    talent_sql = str(TalentRadarImporter._INSERT_SQL)
    assert "_manual_override_city" in talent_sql
    assert "_manual_override_country" in talent_sql
