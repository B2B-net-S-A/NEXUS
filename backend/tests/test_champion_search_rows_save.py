"""Zapis samych wymagań do wyszukiwania w bazie (sekcja 2 Championa,
25.09.2026) nie przelicza dopasowań i nie budzi automatów — „Szukaj ręcznie”
jest ich jedynym czytelnikiem. `intake` zostaje, więc odcisk pełnego
przeglądu też (inaczej odczyt wyników kończył się 409). Zmiana opisu projektu
nadal przelicza — to kontrola, że pominięcie jest wąskie."""

import uuid

import pytest

from app.core.database import AsyncSessionLocal
from app.models.client import Client
from app.models.job import Job, JobStatus


async def _seed() -> int:
    async with AsyncSessionLocal() as db:
        client = Client(name=f"Synthetic Search Rows {uuid.uuid4().hex[:8]}")
        db.add(client)
        await db.flush()
        job = Job(
            title="Synthetic Java role",
            status=JobStatus.published,
            client_id=client.id,
            champion_profile={
                "basics": {"role_name": "Java Developer"},
                "stack": {"must": [{"name": "Java"}], "nice": [], "notes": ""},
                "project": {"about": "Migracja systemu płatności."},
            },
            must_skills=[{"name": "Java", "level": None}],
        )
        db.add(job)
        await db.commit()
        return job.id


@pytest.mark.asyncio
async def test_rows_only_save_skips_matching_refresh_and_automations(
    app_client, app_auth_headers, monkeypatch
):
    refreshed: list[int] = []
    enqueued: list[int] = []

    async def fake_refresh(job_id, db):
        refreshed.append(job_id)

    async def fake_enqueue(job_id, *args, **kwargs):
        enqueued.append(job_id)

    monkeypatch.setattr(
        "app.services.job_matching_refresh.refresh_job_matching", fake_refresh
    )
    monkeypatch.setattr("app.services.auto_match_outbox.enqueue_job_safe", fake_enqueue)

    jid = await _seed()
    route = f"/api/jobs/{jid}/champion-profile"
    first = await app_client.put(
        route, json={"project": {"about": "Migracja płatności kartowych."}},
        headers=app_auth_headers,
    )
    assert first.status_code == 200, first.text
    # Kontrola: zmiana opisu projektu przelicza i budzi automaty.
    assert refreshed == [jid]
    assert enqueued == [jid]
    before = first.json()["champion_profile"]

    refreshed.clear()
    enqueued.clear()
    rows = await app_client.put(
        route,
        json={
            "search": {
                "requirements": [["Java"], ["Kafka", "RabbitMQ"], []],
                "exclude": ["junior"],
            }
        },
        headers=app_auth_headers,
    )
    assert rows.status_code == 200, rows.text
    saved = rows.json()["champion_profile"]
    assert saved["search"]["requirements"] == [["Java"], ["Kafka", "RabbitMQ"]]
    assert saved["search"]["exclude"] == ["junior"]
    assert saved["intake"] == before["intake"]
    assert refreshed == []
    assert enqueued == []

    # Ponowny zapis z samym pustym wierszem to brak zmiany.
    again = await app_client.put(
        route,
        json={"search": {"requirements": [["Java"], ["Kafka", "RabbitMQ"], []]}},
        headers=app_auth_headers,
    )
    assert again.status_code == 200, again.text
    assert again.json()["champion_profile"] == saved
    assert refreshed == []
    assert enqueued == []
