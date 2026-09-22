"""Nowa rekrutacja z requestu klienta (/jobs/new) — odczyt przed zapisem."""

import pytest

from app.services import job_request_intake as intake
from app.services.job_request_intake import normalize_model_output

REQUEST = (
    "Szukamy Senior Java Developera do projektu migracji płatności. "
    "Wymagania: Java 17+, Spring Boot, Kafka. Mile widziane: Kubernetes. "
    "Praca hybrydowa — 2 dni w biurze w Warszawie. Budżet do 170 zł/h netto."
)

FULL = {
    "role_name": "Senior Java Developer",
    "must": ["Java 17+", "Spring Boot", "Kafka", "java 17+"],
    "nice": ["Kubernetes", "Kafka"],
    "rate_quote": "do 170 zł/h netto",
    "work_mode": "hybrydowo",
    "onsite_days_per_week": 2,
    "office_city": "Warszawa",
    "project_about": "Migracja systemu płatności.",
    "screening_questions": [
        {
            "question": "Jak skalowałeś Kafkę?",
            "ideal_answer": "partycje",
            "from_request": True,
        },
        {
            "question": "Czy 2 dni w biurze pasują?",
            "ideal_answer": "tak",
            "from_request": False,
        },
    ],
    "evidence": ["Java 17+", "Spring Boot", "zmyślony fragment"],
}


def test_complete_request_has_nothing_missing() -> None:
    result = normalize_model_output(FULL, REQUEST)
    assert result.missing == []
    assert result.rate_budget_hourly == 170.0
    assert result.remote_policy == "hybrid"
    assert result.must == ["Java 17+", "Spring Boot", "Kafka"]
    # Must-have nie jest powtarzany w „mile widzianych”.
    assert result.nice == ["Kubernetes"]
    assert [q.from_request for q in result.screening_questions] == [True, False]


def test_budget_is_derived_from_the_quote_not_from_the_model() -> None:
    # Stawka dzienna nie jest budżetem PLN/h — żadnego przeliczania ÷ 8.
    text = "Stawka 1360 zł/MD netto, praca zdalna."
    result = normalize_model_output({"rate_quote": "1360 zł/MD netto"}, text)
    assert result.rate_budget_hourly is None
    assert "PLN/h" in (result.rate_note or "")
    assert intake.MISSING_BUDGET in result.missing


def test_bare_number_without_unit_is_not_a_budget() -> None:
    """REC-07: „1100” bez waluty i jednostki to często stawka za MD —
    nie wolno zapisać jej jako 1100 PLN/h."""
    text = REQUEST + "\nStawka: 1100"
    result = normalize_model_output({"rate_quote": "1100"}, text)
    assert result.rate_budget_hourly is None
    assert result.rate_note and "1100" in result.rate_note


def test_unit_and_currency_still_give_a_budget() -> None:
    text = REQUEST + "\nBudżet 150 PLN/h netto"
    result = normalize_model_output({"rate_quote": "150 PLN/h netto"}, text)
    assert result.rate_budget_hourly == 150


def test_quote_absent_from_the_request_is_ignored() -> None:
    result = normalize_model_output({"rate_quote": "do 200 zł/h"}, REQUEST)
    assert result.rate_budget_hourly is None
    assert result.rate_quote is None


def test_evidence_keeps_only_fragments_present_in_the_request() -> None:
    result = normalize_model_output(FULL, REQUEST)
    assert "zmyślony fragment" not in result.evidence
    assert "do 170 zł/h netto" in result.evidence


def test_remote_role_needs_no_office() -> None:
    raw = {**FULL, "work_mode": "zdalnie", "onsite_days_per_week": 3}
    result = normalize_model_output(raw, REQUEST)
    assert result.remote_policy == "remote"
    assert result.onsite_days_per_week is None and result.office_city is None
    assert result.missing == []


def test_hybrid_without_days_and_city_is_reported() -> None:
    raw = {**FULL, "onsite_days_per_week": None, "office_city": None}
    result = normalize_model_output(raw, REQUEST)
    assert intake.MISSING_OFFICE_DAYS in result.missing
    assert intake.MISSING_OFFICE_CITY in result.missing


def test_one_question_is_not_enough() -> None:
    raw = {**FULL, "screening_questions": FULL["screening_questions"][:1]}
    assert intake.MISSING_QUESTIONS in normalize_model_output(raw, REQUEST).missing


def test_garbage_from_the_model_yields_an_empty_honest_form() -> None:
    result = normalize_model_output("nie JSON", REQUEST)
    assert result.role_name is None and result.must == []
    assert intake.MISSING_ROLE in result.missing


@pytest.mark.asyncio
async def test_read_route_returns_the_intake_without_creating_a_job(
    app_client, app_auth_headers, monkeypatch
) -> None:
    from sqlalchemy import func, select

    from app.core.database import AsyncSessionLocal
    from app.models.client import Client
    from app.models.job import Job

    async def fake_read(db, *, client_id, request_text):
        return normalize_model_output(FULL, request_text)

    monkeypatch.setattr(intake, "read_request", fake_read)

    async with AsyncSessionLocal() as db:
        client = Client(name="Intake Test Sp. z o.o.")
        db.add(client)
        await db.commit()
        await db.refresh(client)
        jobs_before = await db.scalar(select(func.count(Job.id)))

    resp = await app_client.post(
        "/api/job-intake/read",
        json={"client_id": client.id, "text": REQUEST},
        headers=app_auth_headers,
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["intake"]["rate_budget_hourly"] == 170.0
    assert body["intake"]["missing"] == []

    async with AsyncSessionLocal() as db:
        assert await db.scalar(select(func.count(Job.id))) == jobs_before


@pytest.mark.asyncio
async def test_read_route_rejects_unknown_client(app_client, app_auth_headers) -> None:
    resp = await app_client.post(
        "/api/job-intake/read",
        json={"client_id": 987654321, "text": REQUEST},
        headers=app_auth_headers,
    )
    assert resp.status_code == 404
