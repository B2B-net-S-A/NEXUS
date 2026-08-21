"""Projekcja listy /api/jobs nie wozi Profilu Championa ani notatek zamknięcia.

Dlaczego to ma własny plik i własny test: regresja jest CICHA. Odpowiedź ma
200, ma poprawną liczbę wierszy, front wygląda identycznie — a w payloadzie
jedzie JSONB z nazwiskiem naszego konsultanta u klienta, poprawkami klienta do
zapytania, listą firm docelowych i wzorcowymi odpowiedziami screeningowymi.
Nikt tego nie zobaczy patrząc na ekran; widać to tylko w treści odpowiedzi.

Druga połowa kontraktu jest równie ważna: detal MUSI dalej oddawać Championa.
Bez tej asercji „naprawa" polegająca na wyczyszczeniu pola wszędzie przeszłaby
na zielono i zabrałaby edytorowi Championa jego dane.
"""

from __future__ import annotations

import pytest


_CHAMPION_PROFILE = {
    "internal_consultant_insight": "SEKRET-INSIGHT",
    "sourcing": {"target_companies": "SEKRET-FIRMA"},
    "screening_questions": [
        {"question": "Doświadczenie z Kafką?", "ideal_answer": "SEKRET-ODPOWIEDZ"}
    ],
    "verification": {
        "consultant": {"consultant_name": "SEKRET-KONSULTANT"},
        "client": {"key_corrections": "SEKRET-KOREKTA"},
    },
}


async def _seed_job_with_champion() -> int:
    """Zasiej klienta + rekrutację z wypełnionym Championem prosto w bazie.

    Świadomie z pominięciem `POST /api/jobs` — interesuje nas kształt ODCZYTU,
    a droga zapisu ma własną walidację, która by ten test tylko uzależniła od
    niepowiązanych zmian w formularzu.
    """

    from app.core.database import AsyncSessionLocal
    from app.models.client import Client
    from app.models.job import Job

    async with AsyncSessionLocal() as db:
        client = Client(name="Champion Projection Sp. z o.o.")
        db.add(client)
        await db.flush()
        job = Job(
            title="Champion Projection Probe",
            client_id=client.id,
            description="",
            requirements="",
            champion_profile=_CHAMPION_PROFILE,
            close_notes="SEKRET-NOTATKA",
        )
        db.add(job)
        await db.commit()
        await db.refresh(job)
        return job.id


def _find_row(items: list[dict], job_id: int) -> dict:
    for row in items:
        if row.get("id") == job_id:
            return row
    raise AssertionError(f"Rekrutacja {job_id} nie wróciła z listy /api/jobs")


@pytest.mark.asyncio
async def test_jobs_list_does_not_carry_champion_profile(
    app_client, app_auth_headers
) -> None:
    job_id = await _seed_job_with_champion()

    resp = await app_client.get(
        "/api/jobs", params={"page_size": 100}, headers=app_auth_headers
    )
    assert resp.status_code == 200, resp.text
    row = _find_row(resp.json()["items"], job_id)

    # Klucze ZOSTAJĄ (kształt odpowiedzi bez zmian), treść znika.
    assert "champion_profile" in row
    assert row["champion_profile"] is None
    assert row["close_notes"] is None

    # Asercja domykająca: żaden z sekretów nie może przeciec inną drogą —
    # np. gdyby ktoś w przyszłości dołożył do wiersza spłaszczoną kopię
    # któregoś pola Championa (nazwisko konsultanta, firmy docelowe).
    assert "SEKRET-" not in resp.text


@pytest.mark.asyncio
async def test_job_detail_still_returns_champion_profile(
    app_client, app_auth_headers
) -> None:
    """Kontrapunkt: zdjęcie pola z LISTY nie może okaleczyć DETALU.

    Detal pyta o jedną rekrutację, więc ma gdzie sprawdzić zakres pytającego —
    i to on zasila edytor Championa oraz arkusz screeningowy.
    """

    job_id = await _seed_job_with_champion()

    resp = await app_client.get(f"/api/jobs/{job_id}", headers=app_auth_headers)
    assert resp.status_code == 200, resp.text
    payload = resp.json()

    assert payload["champion_profile"] is not None
    assert (
        payload["champion_profile"]["internal_consultant_insight"] == "SEKRET-INSIGHT"
    )
    assert payload["close_notes"] == "SEKRET-NOTATKA"
