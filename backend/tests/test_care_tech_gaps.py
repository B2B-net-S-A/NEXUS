"""Mapa technologii po działach i „Luki do dopytania” (D16, 17.10.2026).

Zakres: dział = ``client_areas``; do działu trafia karta z obszarem,
rekrutacja z hiring managerem z działu i konsultant, którego menedżer u klienta
jest z działu; menedżer działu z drzewa; „Nasi / w bazie” (osoby z dwiema
najmocniejszymi technologiami działu); luki: dział bez źródła z 18 miesięcy,
technologia znana z jednego źródła, menedżer bez „podlega pod”. Reguła luk
także jako czysta funkcja.

Dane fikcyjne (repo jest publiczne).
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Optional

import pytest
import pytest_asyncio
from sqlalchemy import update

import app.models  # noqa: F401  (rejestracja wszystkich mapperów)
from app.core.database import AsyncSessionLocal
from app.core.scheduling import business_today
from app.models.candidate import Candidate
from app.models.contract import Contract
from app.models.job import Job, JobStatus
from app.models.user import UserRole
from app.services.care.tech_map import base_counts, gaps_for
from app.services.hr_foundation_schema import HR_MODULE_KEYS
from tests.test_care_api import (
    _previous_modules,
    _tag,
    headers,
    make_client,
    make_contract,
    make_skill,
    make_user,
    set_modules,
)
from tests.test_care_client_people import make_area, make_contact

pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture
async def care_on():
    previous = await _previous_modules()
    await set_modules({key: True for key in HR_MODULE_KEYS})
    yield
    await set_modules(previous or {key: False for key in HR_MODULE_KEYS})


def _tech(
    skill_id: int,
    name: str,
    counts: tuple[int, int, int, int],
    last_seen: Optional[date],
    *,
    stale: bool = False,
) -> dict:
    keyed = dict(zip(("cards", "jobs", "consultants", "notes"), counts))
    return {
        "skill_id": skill_id,
        "name": name,
        "counts": keyed,
        "source_count": sum(1 for value in counts if value),
        "last_seen": last_seen,
        "stale": stale,
        "areas": [],
    }


async def test_gap_rule_without_database() -> None:
    today = date(2026, 10, 19)
    departments = [
        {
            "area": {"id": 1, "name": "Data"},
            "has_fresh_source": True,
            "last_seen": today,
        },
        {
            "area": {"id": 2, "name": "CI/CD i chmura"},
            "has_fresh_source": False,
            "last_seen": today - timedelta(days=700),
        },
    ]
    technologies = [
        _tech(10, "Spark", (2, 1, 1, 0), today),
        _tech(11, "Databricks", (0, 1, 0, 0), today - timedelta(days=200)),
        _tech(12, "Kotlin", (0, 0, 3, 0), None),  # tylko CV naszych — to nie luka
        _tech(13, "Cobol", (1, 0, 0, 0), today - timedelta(days=900), stale=True),
        _tech(14, "Terraform", (0, 0, 0, 1), today - timedelta(days=20)),
    ]
    managers = [
        {
            "id": 7,
            "name": "Michał Przykładowy",
            "position": "QA Lead",
            "area": {"id": 3, "name": "QA"},
            "reports_to_id": None,
            "consultants": 1,
        },
        {
            "id": 8,
            "name": "Piotr Wzorcowy",
            "position": None,
            "area": None,
            "reports_to_id": 7,
            "consultants": 2,
        },
    ]
    gaps = gaps_for(
        departments=departments, technologies=technologies, managers=managers
    )
    assert [
        (gap["kind"], gap.get("name") or gap.get("area", {}).get("name"))
        for gap in gaps
    ] == [
        ("area_no_source", "CI/CD i chmura"),
        ("manager_unplaced", "QA"),
        ("single_source", "Terraform"),
        ("single_source", "Databricks"),
    ]
    assert gaps[1]["contact"] == {"id": 7, "name": "Michał Przykładowy"}
    assert gaps[3]["source"] == "jobs" and gaps[3]["refs"] == 1


class _FailingSession:
    """Sesja, której zapytanie przekracza limit czasu (liczy wywołania)."""

    def __init__(self) -> None:
        self.calls = 0

    def begin_nested(self):
        self.calls += 1
        raise TimeoutError("statement timeout")


async def test_base_count_failure_is_a_dash_and_not_retried_at_once() -> None:
    db = _FailingSession()
    group = [f"umiejetnosc-{_tag()}"]
    assert await base_counts(db, [group, []]) == [None, None]
    assert db.calls == 1
    # Kolejne przeliczenie mapy w ciągu 10 minut nie powtarza drogiego zapytania.
    assert await base_counts(db, [group]) == [None]
    assert db.calls == 1


async def _candidate_with_skills(names: list[str]) -> int:
    tag = _tag()
    async with AsyncSessionLocal() as db:
        candidate = Candidate(
            name="Baza",
            lastname=f"Przykładowa-{tag}",
            email=f"base-{tag}@example.com",
            skills=names,
        )
        db.add(candidate)
        await db.commit()
        return candidate.id


async def test_map_by_departments_with_managers_base_and_gaps(
    app_client, care_on
) -> None:
    dl = await make_user(UserRole.delivery_lead)
    client_id = await make_client(dl=dl)
    data = await make_area(client_id, "Data")
    qa = await make_area(client_id, "QA")
    empty = await make_area(client_id, "CI/CD i chmura")
    spark, spark_name = await make_skill("spark")
    kafka, kafka_name = await make_skill("kafka")
    lead = await make_contact(client_id, "Piotr Zieliński-Przykładowy", area_id=data)
    qa_lead = await make_contact(
        client_id, "Michał Rogalski-Przykładowy", area_id=qa, reports_to=lead
    )

    # Data: karta (Spark), rekrutacja z hiring managerem z Data (Kafka)
    # i nasz konsultant pod Piotrem (Spark w profilu).
    contract_id, candidate_id = await make_contract(client_id, started_days_ago=50)
    qa_contract, _ = await make_contract(client_id, started_days_ago=20)
    async with AsyncSessionLocal() as db:
        await db.execute(
            update(Contract)
            .where(Contract.id == contract_id)
            .values(client_pm_contact_id=lead)
        )
        await db.execute(
            update(Contract)
            .where(Contract.id == qa_contract)
            .values(client_pm_contact_id=qa_lead)
        )
        await db.execute(
            update(Candidate)
            .where(Candidate.id == candidate_id)
            .values(skills=[spark_name])
        )
        db.add(
            Job(
                title=f"Inżynier danych {_tag()}",
                status=JobStatus.published,
                client_id=client_id,
                hiring_manager_contact_id=lead,
                must_skills=[{"name": kafka_name}],
            )
        )
        await db.commit()
    card = await app_client.post(
        f"/api/care/contracts/{contract_id}/tech-cards",
        headers=headers(dl),
        json={
            "interview_on": business_today().isoformat(),
            "finalize": True,
            "status": "ok",
            "skill_ids": [spark],
            "client_area_id": data,
        },
    )
    assert card.status_code == 201, card.text
    # „W bazie”: dwie osoby mają oba języki działu, trzecia tylko jeden.
    await _candidate_with_skills([spark_name, kafka_name])
    await _candidate_with_skills([kafka_name, spark_name, "Excel"])
    await _candidate_with_skills([kafka_name])

    response = await app_client.get(
        f"/api/care/clients/{client_id}/tech-map", headers=headers(dl)
    )
    assert response.status_code == 200, response.text
    body = response.json()
    departments = {dept["area"]["name"]: dept for dept in body["departments"]}
    assert set(departments) == {"Data", "QA", "CI/CD i chmura"}

    data_row = departments["Data"]
    techs = {tech["skill_id"]: tech for tech in data_row["technologies"]}
    assert techs[spark]["counts"] == {
        "cards": 1,
        "jobs": 0,
        "consultants": 1,
        "notes": 0,
    }
    assert techs[kafka]["counts"]["jobs"] == 1
    assert data_row["technologies"][0]["skill_id"] == spark
    assert [m["id"] for m in data_row["managers"]] == [lead]
    assert data_row["managers"][0]["consultants"] == 1
    assert data_row["consultants"] == 1
    assert data_row["has_fresh_source"] is True
    assert [name.lower() for name in data_row["base"]["skills"]] == [
        spark_name,
        kafka_name,
    ]
    assert data_row["base"]["count"] == 2

    qa_row = departments["QA"]
    assert qa_row["technologies"] == [] and qa_row["has_fresh_source"] is True
    assert qa_row["managers"][0]["name"] == "Michał Rogalski-Przykładowy"
    assert departments["CI/CD i chmura"]["managers"] == []
    assert departments["CI/CD i chmura"]["base"] == {"skills": [], "count": None}

    # Obszar rekrutacji trafia też do filtra obszarów pełnej listy technologii.
    by_id = {tech["skill_id"]: tech for tech in body["technologies"]}
    assert by_id[kafka]["areas"] == ["Data"]

    gaps = body["gaps"]
    assert {
        "kind": "area_no_source",
        "area": {"id": empty, "name": "CI/CD i chmura"},
        "last_seen": None,
    } in gaps
    unplaced = [gap for gap in gaps if gap["kind"] == "manager_unplaced"]
    # Piotr nie ma „podlega pod”; Michał podlega pod Piotra — nie jest luką.
    assert [gap["contact"]["id"] for gap in unplaced] == [lead]
    assert unplaced[0]["area"] == {"id": data, "name": "Data"}
    single = [gap for gap in gaps if gap["kind"] == "single_source"]
    assert [(gap["skill_id"], gap["source"], gap["refs"]) for gap in single] == [
        (kafka, "jobs", 1)
    ]
