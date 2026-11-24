"""Osoby mieszkające poza Polską (decyzja Artura 24.11.2026).

Kontrakty:

- mieszka poza Polską = kraj w profilu inny niż PL i miasto spoza słownika
  polskich miejscowości; miasto w Polsce wygrywa z krajem (kraj bywa
  obywatelstwem), profil bez kraju przechodzi;
- warunek SQL (``abroad_ids``) liczy tak samo jak Python
  (``lives_outside_poland``);
- silnik „Nowych” takich osób nie dodaje, a lista propozycji ich nie pokazuje,
  chyba że osoba sama zgłosiła się z ogłoszenia;
- odrzucenie „Mieszka poza Polską” zapisuje kraj na profilu z blokadą przed
  nadpisaniem z CV i zdejmuje nietknięte karty od systemu z innych
  rekrutacji; kraj przy innym powodzie albo „PL” → 422.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from sqlalchemy import select

import app.models  # noqa: F401
from app.core.database import AsyncSessionLocal
from app.models.activity import Activity
from app.models.candidate import Candidate
from app.models.pipeline_template import RejectionReason
from app.services import autofill_withdraw, candidate_audit, residence
from app.services import new_column_autofill as autofill
from tests.test_autofill_feedback import (  # noqa: F401 — fikstura
    _client_with_jobs,
    _open_system_jobs,
    _world,
    api_client,
)
from tests.test_new_column_autofill import _fill, _pool


def _person(country, city=None, location=None) -> SimpleNamespace:
    return SimpleNamespace(country=country, city=city, location=location)


@pytest.mark.parametrize(
    ("country", "city", "location", "abroad"),
    [
        ("IN", "Bhubaneswar", "Bhubaneswar, IN", True),
        ("GB", "London", None, True),
        ("de", None, "Berlin, DE", True),
        ("US", None, None, True),
        # Kraj bywa obywatelstwem: miasto w Polsce wygrywa.
        ("BY", "Warszawa", None, False),
        ("CH", None, "Wiskitki, CH", False),
        ("UA", "Gdansk", None, False),
        ("PL", "London", None, False),
        (None, "Dublin", None, False),
        ("", None, None, False),
        ("  ", None, None, False),
    ],
)
def test_lives_outside_poland(country, city, location, abroad):
    assert residence.lives_outside_poland(_person(country, city, location)) is abroad


class _Db:
    def __init__(self) -> None:
        self.added: list = []

    def add(self, row) -> None:
        self.added.append(row)


def test_record_from_rejection_sets_country_locks_it_and_drops_polish_city():
    person = SimpleNamespace(
        id=7,
        country="PL",
        city="Warszawa",
        location="Warszawa, PL",
        cv_extracted_data={"name": "x"},
    )
    db = _Db()
    assert residence.record_from_rejection(
        db, person, country="in", user_id=1, job_id=2, stage_id=3
    )
    assert (person.country, person.city, person.location) == ("IN", None, "IN")
    assert person.cv_extracted_data["_manual_override_country"] is True
    assert person.cv_extracted_data["_manual_override_city"] is True
    assert residence.lives_outside_poland(person)
    (audit,) = db.added
    assert audit.action == candidate_audit.LOCATION_CHANGED
    assert audit.details["source"] == "rejection"
    assert audit.details["changed_fields"] == ["city", "country"]


def test_record_from_rejection_keeps_foreign_city_and_skips_no_change():
    person = SimpleNamespace(
        id=7, country="IN", city="Pune", location="Pune, IN", cv_extracted_data=None
    )
    db = _Db()
    assert not residence.record_from_rejection(
        db, person, country="IN", user_id=1, job_id=2, stage_id=3
    )
    assert db.added == []
    assert residence.record_from_rejection(
        db, person, country="GB", user_id=1, job_id=2, stage_id=3
    )
    assert (person.city, person.location) == ("Pune", "Pune, GB")


@pytest.mark.parametrize("country", ["PL", "pl", "", None])
def test_record_from_rejection_refuses_poland_and_empty(country):
    person = _person("PL")
    with pytest.raises(ValueError):
        residence.record_from_rejection(
            _Db(), person, country=country, user_id=1, job_id=2, stage_id=3
        )


# ── Baza: SQL = Python, silnik, lista propozycji, ruch karty ─────────────────


async def _people_at(*places: tuple) -> list[int]:
    tag = uuid.uuid4().hex[:8]
    async with AsyncSessionLocal() as db:
        rows = [
            Candidate(
                name="Mieszka",
                lastname=f"{i}-{tag}",
                country=country,
                city=city,
                location=location,
            )
            for i, (country, city, location) in enumerate(places)
        ]
        db.add_all(rows)
        await db.commit()
        return [c.id for c in rows]


async def test_sql_rule_matches_python_rule():
    places = [
        ("IN", "Bhubaneswar", "Bhubaneswar, IN"),
        ("BY", "Warszawa", None),
        ("CH", None, "Wiskitki, CH"),
        ("gb", None, "London, GB"),
        ("PL", None, None),
        (None, "Dublin", None),
        (" ", None, None),
    ]
    ids = await _people_at(*places)
    async with AsyncSessionLocal() as db:
        sql = set(
            (
                await db.scalars(residence.abroad_ids().where(Candidate.id.in_(ids)))
            ).all()
        )
    python = {
        cid
        for cid, (country, city, location) in zip(ids, places)
        if residence.lives_outside_poland(_person(country, city, location))
    }
    assert sql == python == {ids[0], ids[3]}


async def test_engine_never_adds_people_living_abroad(monkeypatch):
    monkeypatch.setattr(autofill, "TARGET", 5)
    _client, (job_id,) = await _client_with_jobs(1)
    india, minsk_in_warsaw, poland, unknown = await _people_at(
        ("IN", "Pune", "Pune, IN"),
        ("BY", "Warszawa", None),
        ("PL", "Kraków", None),
        (None, None, None),
    )
    await _pool(job_id, {india: 95, minsk_in_warsaw: 90, poland: 85, unknown: 80})

    assert await _fill(job_id) == [minsk_in_warsaw, poland, unknown]


async def test_proposals_list_hides_abroad_unless_they_applied():
    from app.services import job_proposals

    _client, (job_id,) = await _client_with_jobs(1)
    from_base, applied, at_home = await _people_at(
        ("IN", "Pune", None), ("IN", "Delhi", None), ("PL", "Gdańsk", None)
    )
    async with AsyncSessionLocal() as db:
        await job_proposals.upsert_proposals(
            db,
            job_id=job_id,
            source="full_base",
            rows=[
                {"candidate_id": from_base, "score": 90},
                {"candidate_id": at_home, "score": 80},
            ],
        )
        await job_proposals.upsert_proposals(
            db,
            job_id=job_id,
            source="job_board",
            rows=[{"candidate_id": applied, "score": 70}],
        )
        await db.commit()
        listed = set(
            (
                await db.scalars(
                    select(
                        job_proposals._pairs_for_job(job_id, "proposed")
                        .subquery()
                        .c.candidate_id
                    )
                )
            ).all()
        )
    assert listed == {applied, at_home}


async def _reason(name: str) -> int:
    """Wiersz szablonu o tej nazwie (0768 dokłada ``outside_poland`` do każdego
    szablonu); brak — dopisany do pierwszego szablonu. Ruch szuka powodu po id."""
    from app.models.pipeline_template import PipelineTemplate

    async with AsyncSessionLocal() as db:
        found = await db.scalar(
            select(RejectionReason.id)
            .where(
                RejectionReason.category == "rejected",
                RejectionReason.name == name,
                RejectionReason.active.is_(True),
            )
            .limit(1)
        )
        if found is not None:
            return found
        template_id = await db.scalar(select(PipelineTemplate.id).limit(1))
        if template_id is None:
            template = PipelineTemplate(name=f"Rezydencja {uuid.uuid4().hex[:6]}")
            db.add(template)
            await db.flush()
            template_id = template.id
        row = RejectionReason(
            template_id=template_id, name=name, category="rejected", order=50
        )
        db.add(row)
        await db.commit()
        return row.id


async def test_rejection_saves_country_and_takes_cards_elsewhere(
    api_client,  # noqa: F811 — fikstura z importu
    monkeypatch,
):
    monkeypatch.setattr(autofill, "TARGET", 1)
    world = await _world()
    _other, (elsewhere,) = await _client_with_jobs(1)
    await _pool(elsewhere, {world["system"]: 70})
    async with AsyncSessionLocal() as db:
        now = datetime.now(timezone.utc)
        assert await autofill.fill_job(db, world["job_id"], now=now) == [
            world["system"]
        ]
        assert await autofill.fill_job(db, elsewhere, now=now) == [world["system"]]
        await db.commit()
    login = await api_client.post(
        "/api/auth/login",
        json={"email": world["email"], "password": world["password"]},
    )
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
    base = {
        "candidate_id": world["system"],
        "job_id": world["job_id"],
        "stage": "rejected",
        "notes": "Mieszka w Indiach.",
        "autofill_learned_from": "profile",
    }
    other_reason = await _reason("outside_poland")
    generic = await _reason("Nie spełnia wymagań technicznych")

    # Kraj przy innym powodzie i Polska jako „poza Polską” — odmowa.
    wrong_reason = await api_client.post(
        "/api/pipeline/move",
        headers=headers,
        json={
            **base,
            "rejection_reason_id": generic,
            "autofill_reason": "missing_skill",
            "residence_country": "IN",
        },
    )
    assert wrong_reason.status_code == 422, wrong_reason.text
    poland = await api_client.post(
        "/api/pipeline/move",
        headers=headers,
        json={
            **base,
            "rejection_reason_id": other_reason,
            "autofill_reason": "outside_poland",
            "residence_country": "PL",
        },
    )
    assert poland.status_code == 422, poland.text

    moved = await api_client.post(
        "/api/pipeline/move",
        headers=headers,
        json={
            **base,
            "rejection_reason_id": other_reason,
            "autofill_reason": "outside_poland",
            "residence_country": "IN",
        },
    )
    assert moved.status_code == 200, moved.text
    async with AsyncSessionLocal() as db:
        person = await db.get(Candidate, world["system"])
        audit = await db.scalar(
            select(Activity).where(
                Activity.action == candidate_audit.LOCATION_CHANGED,
                Activity.entity_id == world["system"],
            )
        )
        why = (
            await db.scalars(
                select(Activity.details["why"].astext).where(
                    Activity.entity_type == autofill_withdraw.ACTIVITY_ENTITY,
                    Activity.entity_id == elsewhere,
                    Activity.action == autofill_withdraw.ACTION,
                )
            )
        ).all()
    assert person.country == "IN"
    assert person.cv_extracted_data["_manual_override_country"] is True
    assert audit is not None and audit.user_id == world["user_id"]
    assert audit.details["source"] == "rejection"
    assert elsewhere not in await _open_system_jobs(world["system"])
    assert why == ["abroad"]
