"""/jobs/new — podpowiedź kategorii i wiersze wymagań przed założeniem rekrutacji."""

import pytest

from app.models.user import UserRole
from tests._jarvis_helpers import make_user
from tests.taxonomy_fixture import hydrated_taxonomy

CATEGORY_URL = "/api/job-intake/category-suggestion"
ROWS_URL = "/api/job-intake/requirement-rows"
CRITICAL_URL = "/api/job-intake/critical-suggestion"


@pytest.mark.asyncio
async def test_category_is_suggested_from_the_role_name(app_client) -> None:
    _, headers = await make_user(UserRole.delivery_lead)

    resp = await app_client.post(
        CATEGORY_URL,
        json={"role": "Tester automatyzujący", "client_title": "QA Engineer (ZOB 1)"},
        headers=headers,
    )

    assert resp.status_code == 200, resp.text
    body = resp.json()
    by_id = {category["id"]: category for category in body["categories"]}
    assert body["suggested_id"] in by_id
    # Kategoria QA (slug sprzed 0371) — ta sama reguła nazwy co przy zapisie.
    assert by_id[body["suggested_id"]]["slug"] == "security_quality"
    assert all(
        set(category) == {"id", "slug", "name", "participants"}
        and isinstance(category["participants"], int)
        for category in body["categories"]
    )


@pytest.mark.asyncio
async def test_no_role_means_no_suggestion_but_the_list_is_there(app_client) -> None:
    _, headers = await make_user(UserRole.delivery_lead)

    resp = await app_client.post(CATEGORY_URL, json={}, headers=headers)

    assert resp.status_code == 200, resp.text
    assert resp.json()["suggested_id"] is None
    assert resp.json()["categories"]


@pytest.mark.asyncio
async def test_recruiter_cannot_ask_for_a_category(app_client) -> None:
    # Kategorię potwierdza osoba zakładająca rekrutację (admin, Delivery Lead).
    _, headers = await make_user(UserRole.recruiter)

    resp = await app_client.post(
        CATEGORY_URL, json={"role": "Java Developer"}, headers=headers
    )

    assert resp.status_code == 403, resp.text


@pytest.mark.asyncio
async def test_legacy_fields_convert_to_rows_without_writing(app_client) -> None:
    _, headers = await make_user(UserRole.recruiter)

    with hydrated_taxonomy():
        resp = await app_client.post(
            ROWS_URL,
            json={
                "must": ["Java 17+", "Doświadczenie w dużych projektach bankowych"],
                "nice": ["Kubernetes"],
                "requirements": [["bankow*", "banking"]],
                "critical": [],
            },
            headers=headers,
        )

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["rows"] == [
        {"words": ["bankow*", "banking"], "level": "must"},
        {"words": ["Java"], "level": "must"},
        {"words": ["Kubernetes"], "level": "nice"},
    ]
    assert body["descriptive"] == [
        "Java 17+",
        "Doświadczenie w dużych projektach bankowych",
    ]
    assert body["no_critical"] is True


@pytest.mark.asyncio
async def test_critical_suggestion_labels_rows_like_the_saved_profile(
    app_client,
) -> None:
    _, headers = await make_user(UserRole.recruiter)

    with hydrated_taxonomy():
        resp = await app_client.post(
            CRITICAL_URL,
            json={
                "title": "Java Developer",
                "rows": [["Kafka", "Docker"], ["płatności", "płatnoś*"], []],
            },
            headers=headers,
        )

    assert resp.status_code == 200, resp.text
    body = resp.json()
    # Etykieta per wiersz, w kolejności żądania; pusty wiersz = pusta etykieta.
    assert body["labels"] == ["Kafka lub Docker", "płatności", ""]
    # Technologie ze słownika (wymóg decyzji, tytuł dla rekrutera).
    assert body["eligible"] == ["Kafka lub Docker"]
    # Oznaczyć wolno każdą pozycję — decyduje Delivery Lead (09.10.2026).
    assert body["selectable"] == ["Kafka lub Docker", "płatności"]
    assert body["blocked"] == {}


@pytest.mark.asyncio
async def test_any_position_may_be_marked_critical(app_client) -> None:
    _, headers = await make_user(UserRole.recruiter)

    with hydrated_taxonomy():
        resp = await app_client.post(
            CRITICAL_URL,
            json={"rows": [["Java"], ["Temenos T24"], ["English B2"]]},
            headers=headers,
        )

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["eligible"] == ["Java"]
    assert body["selectable"] == ["Java", "Temenos T24", "English B2"]
    assert body["blocked"] == {}


@pytest.mark.asyncio
async def test_rows_come_back_with_readings_per_word(app_client) -> None:
    """13.10.2026 (wariant A): edytor dostaje odczyt każdego słowa wiersza."""
    _, headers = await make_user(UserRole.delivery_lead)

    with hydrated_taxonomy():
        resp = await app_client.post(
            CRITICAL_URL,
            json={
                "rows": [
                    ["Java"],
                    ["doświadczenie w przetargach"],
                    ["angielski B2"],
                    [],
                ]
            },
            headers=headers,
        )

    assert resp.status_code == 200, resp.text
    readings = resp.json()["readings"]
    assert [len(row) for row in readings] == [1, 1, 1, 0]
    java, tender, english = readings[0][0], readings[1][0], readings[2][0]
    assert (java["kind"], java["needs_decision"], java["keyword"]) == (
        "technology",
        False,
        "Java",
    )
    assert tender["kind"] == "prose" and tender["needs_decision"] is True
    assert tender["talk"] == "skills" and "przetarg*" in tender["suggestions"]
    assert english["talk"] == "language" and english["needs_decision"] is True


@pytest.mark.asyncio
async def test_rows_are_bounded_and_read_after_the_row_sieve(app_client) -> None:
    """Przegląd bezpieczeństwa 13.10.2026: surowy tekst wiersza szedł do odczytu
    frazy bez limitu — jedno żądanie zamrażało API. Schemat ogranicza słowa,
    a odczyt dostaje słowa po sicie zapisu (≤ 100 znaków)."""
    _, headers = await make_user(UserRole.delivery_lead)

    with hydrated_taxonomy():
        too_long = await app_client.post(
            CRITICAL_URL, json={"rows": [["x" * 1001]]}, headers=headers
        )
        too_many = await app_client.post(
            CRITICAL_URL,
            json={"rows": [[f"słowo{i}" for i in range(51)]]},
            headers=headers,
        )
        resp = await app_client.post(
            CRITICAL_URL,
            json={"rows": [["doświadczenie " * 70]]},
            headers=headers,
        )

    assert too_long.status_code == 422
    assert too_many.status_code == 422
    assert resp.status_code == 200, resp.text
    readings = resp.json()["readings"]
    assert len(readings) == 1 and readings[0]
    assert max(len(reading["text"]) for reading in readings[0]) <= 100
