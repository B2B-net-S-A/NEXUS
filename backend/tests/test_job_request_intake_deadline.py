"""Odczyt maila v11 (04.10.2026): termin i liczba osób tylko z dosłownym cytatem.

Maile są fikcyjne. Bez bazy.
"""

from __future__ import annotations

from datetime import date

import pytest

from app.services import job_request_intake as intake
from app.services.job_request_intake import normalize_model_output, parse_deadline_date

TODAY = date(2026, 10, 4)


@pytest.fixture(autouse=True)
def _pin_business_today(monkeypatch):
    monkeypatch.setattr("app.core.scheduling.business_today", lambda *a, **k: TODAY)


MAIL = (
    "Dzień dobry, szukamy dwóch testerów automatyzujących do projektu "
    "w bankowości. CV prosimy przesłać do 17.10 do godz. 12:00. "
    "Pozdrawiam, Anna Fikcyjna"
)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("17.10", "2026-10-17"),
        ("do 17.10.2027", "2027-10-17"),
        ("17/10/27", "2027-10-17"),
        ("do 17 października", "2026-10-17"),
        ("17 pazdziernika 2026", "2026-10-17"),
        ("2026-11-03", "2026-11-03"),
        # Dzień już minął w tym roku → następny rok.
        ("do 20.09", "2027-09-20"),
        ("do 2 stycznia", "2027-01-02"),
        # Dziś to jeszcze nie przeszłość.
        ("4.10", "2026-10-04"),
        ("ASAP", None),
        ("jak najszybciej", None),
        ("31.02", None),
        ("bez daty", None),
        # Godzina przed datą nie myli się z datą.
        ("do godz. 12.00 dnia 17.10", "2026-10-17"),
    ],
)
def test_parse_deadline_date(raw, expected) -> None:
    assert parse_deadline_date(raw, today=TODAY) == expected


def test_deadline_and_time_come_only_from_a_quote_in_the_mail() -> None:
    result = normalize_model_output(
        {
            "deadline_quote": "CV prosimy przesłać do 17.10 do godz. 12:00",
            "deadline": "17.10",
            "deadline_time": "12:00",
        },
        MAIL,
    )
    assert result.deadline == "2026-10-17"
    assert result.deadline_time == "12:00"
    assert result.provenance["deadline"] == "request"
    assert "CV prosimy przesłać do 17.10 do godz. 12:00" in result.evidence


def test_quote_absent_from_the_mail_gives_no_deadline() -> None:
    result = normalize_model_output(
        {"deadline_quote": "CV do 20.10", "deadline": "20.10"}, MAIL
    )
    assert result.deadline is None
    assert result.deadline_time is None
    assert "deadline" not in result.provenance


def test_model_date_outside_the_quote_is_replaced_by_the_quote() -> None:
    # Model „poprawił” datę — liczy się to, co stoi w cytacie.
    result = normalize_model_output(
        {
            "deadline_quote": "CV prosimy przesłać do 17.10 do godz. 12:00",
            "deadline": "18.10",
        },
        MAIL,
    )
    assert result.deadline == "2026-10-17"


def test_time_not_in_the_quote_is_dropped() -> None:
    result = normalize_model_output(
        {
            "deadline_quote": "CV prosimy przesłać do 17.10 do godz. 12:00",
            "deadline": "17.10",
            "deadline_time": "15:30",
        },
        MAIL,
    )
    assert result.deadline == "2026-10-17"
    assert result.deadline_time is None


def test_asap_is_not_a_deadline() -> None:
    mail = "Potrzebujemy developera Java ASAP, praca zdalna."
    result = normalize_model_output(
        {"deadline_quote": "developera Java ASAP", "deadline": "ASAP"}, mail
    )
    assert result.deadline is None


def test_headcount_needs_the_number_in_the_quote() -> None:
    result = normalize_model_output(
        {"headcount_quote": "szukamy dwóch testerów", "headcount": 2}, MAIL
    )
    assert result.headcount == 2
    assert result.provenance["headcount"] == "request"

    wrong = normalize_model_output(
        {"headcount_quote": "szukamy dwóch testerów", "headcount": 3}, MAIL
    )
    assert wrong.headcount is None

    invented = normalize_model_output(
        {"headcount_quote": "szukamy trzech testerów", "headcount": 3}, MAIL
    )
    assert invented.headcount is None


@pytest.mark.parametrize("value", [0, 51, "dużo", True])
def test_headcount_outside_one_to_fifty_is_dropped(value) -> None:
    mail = "Szukamy 60 osób do projektu."
    result = normalize_model_output(
        {"headcount_quote": "Szukamy 60 osób", "headcount": value}, mail
    )
    assert result.headcount is None


def test_headcount_in_digits() -> None:
    mail = "Rekrutujemy 3 osoby na stanowisko analityka."
    result = normalize_model_output(
        {"headcount_quote": "Rekrutujemy 3 osoby", "headcount": 3}, mail
    )
    assert result.headcount == 3


def test_fields_are_part_of_the_api_shape() -> None:
    data = intake.RequestIntake().as_dict()
    assert {"deadline", "deadline_time", "headcount"} <= set(data)
    assert data["deadline"] is None and data["headcount"] is None


def test_prompt_asks_for_deadline_and_headcount_quotes() -> None:
    from app.services.llm_prompts import JOB_REQUEST_INTAKE

    rendered = JOB_REQUEST_INTAKE.render(
        client_name="Klient", client_context="brak", request_text="mail"
    )
    assert JOB_REQUEST_INTAKE.version == 11
    for key in ('"deadline_quote"', '"deadline"', '"deadline_time"', '"headcount"'):
        assert key in rendered
