"""Okno „Dodaj kandydatów do pipeline”: imiennicy z kartą w rekrutacji i ostatnia rekrutacja.

``POST /api/search/candidates`` z ``exclude_in_job_id`` pomija osoby, które
mają kartę w tej rekrutacji. Przy dosłownej frazie (imię i nazwisko, telefon,
e-mail) odpowiedź mówi teraz, kto z pasujących już tam jest
(``in_job_matches``, z celem „Przywróć” przy zamkniętej karcie), a każdy
wiersz niesie ostatnią rekrutację osoby gdzie indziej (``last_recruitment``).
Reguła: ``docs/claude/rekrutacja-tablica/imiennicy-w-oknie-dodawania.md``.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from httpx import AsyncClient

SEARCH = "/api/search/candidates"


def _token() -> str:
    # same litery — fraza „Imiennik <token>” ma wyglądać na osobę
    return "imien" + "".join(
        chr(ord("a") + int(c, 16) % 26) for c in uuid.uuid4().hex[:10]
    )


async def _seed(token: str) -> dict:
    from app.core.database import AsyncSessionLocal
    from app.models.candidate import Candidate, CandidateStatus
    from app.models.client import Client
    from app.models.job import Job, JobStatus
    from app.models.recruitment_pipeline import CandidateStage, PipelineStage

    async with AsyncSessionLocal() as db:
        client = Client(name=f"Imiennicy-{token}")
        db.add(client)
        await db.flush()
        job = Job(
            title=f"Bieżąca {token}", status=JobStatus.published, client_id=client.id
        )
        other = Job(
            title=f"Wcześniejsza {token}",
            status=JobStatus.published,
            client_id=client.id,
        )
        people = {
            key: Candidate(
                name="Imiennik",
                lastname=token,
                email=f"{token}-{key}@example.com",
                status=CandidateStatus.active,
            )
            for key in ("free", "closed", "active")
        }
        db.add_all([job, other, *people.values()])
        await db.flush()

        def stage(key: str, job_id: int, code: PipelineStage, at: datetime) -> None:
            db.add(
                CandidateStage(
                    candidate_id=people[key].id, job_id=job_id, stage=code, moved_at=at
                )
            )

        # „free” nie ma karty w bieżącej rekrutacji; ostatnio odrzucony gdzie indziej.
        stage(
            "free",
            other.id,
            PipelineStage.new,
            datetime(2026, 3, 1, 9, tzinfo=timezone.utc),
        )
        stage(
            "free",
            other.id,
            PipelineStage.rejected,
            datetime(2026, 3, 15, 9, tzinfo=timezone.utc),
        )
        # „closed” odrzucony w bieżącej — wcześniej był w innej.
        stage(
            "closed",
            other.id,
            PipelineStage.new,
            datetime(2026, 1, 5, 9, tzinfo=timezone.utc),
        )
        stage(
            "closed",
            job.id,
            PipelineStage.new,
            datetime(2026, 10, 1, 9, tzinfo=timezone.utc),
        )
        stage(
            "closed",
            job.id,
            PipelineStage.rejected,
            datetime(2026, 10, 8, 10, tzinfo=timezone.utc),
        )
        # „active” w toku w bieżącej.
        stage(
            "active",
            job.id,
            PipelineStage.screening,
            datetime(2026, 10, 9, 10, tzinfo=timezone.utc),
        )
        await db.commit()
        return {
            "job_id": job.id,
            "other_id": other.id,
            **{key: person.id for key, person in people.items()},
        }


async def _search(app_client, headers, body: dict) -> dict:
    payload = {
        "page_size": 25,
        "search_mode": "hybrid",
        "semantics_version": 2,
        "text_mode": "auto",
        **body,
    }
    resp = await app_client.post(SEARCH, headers=headers, json=payload)
    assert resp.status_code == 200, resp.text
    return resp.json()


async def test_name_search_lists_people_already_in_the_job(
    app_client: AsyncClient, app_auth_headers: dict
):
    token = _token()
    world = await _seed(token)

    data = await _search(
        app_client,
        app_auth_headers,
        {"q": f"Imiennik {token}", "exclude_in_job_id": world["job_id"]},
    )

    assert [item["id"] for item in data["items"]] == [world["free"]]
    matches = {m["id"]: m for m in data["in_job_matches"]}
    assert set(matches) == {world["closed"], world["active"]}

    closed = matches[world["closed"]]
    assert closed["card_column"] == "closed"
    assert closed["card_label"] == "Odrzucony 08.10.2026"
    assert closed["closed"] == {
        "candidate_name": f"Imiennik {token}",
        "state_version": 0,
        "restore_stage": "new",
        "restore_stage_def_id": None,
    }
    assert closed["email"] == f"{token}-closed@example.com"

    active = matches[world["active"]]
    assert active["card_column"] == "screening"
    assert active["card_label"] == "Screening od 09.10.2026"
    assert active["closed"] is None


async def test_last_recruitment_skips_the_current_job(
    app_client: AsyncClient, app_auth_headers: dict
):
    token = _token()
    world = await _seed(token)

    data = await _search(
        app_client,
        app_auth_headers,
        {"q": f"Imiennik {token}", "exclude_in_job_id": world["job_id"]},
    )

    last = data["items"][0]["last_recruitment"]
    assert last == {
        "job_id": world["other_id"],
        "job_title": f"Wcześniejsza {token}",
        # Numer u klienta obok tytułu, jak w nagłówku rekrutacji (16.10.2026).
        "job_client_reference": None,
        "stage_label": "Odrzucony",
        "column": "closed",
        "moved_on": "2026-03-15",
    }


async def test_person_without_history_has_no_last_recruitment(
    app_client: AsyncClient, app_auth_headers: dict
):
    from app.core.database import AsyncSessionLocal
    from app.models.candidate import Candidate, CandidateStatus

    token = _token()
    world = await _seed(token)
    async with AsyncSessionLocal() as db:
        fresh = Candidate(
            name="Nowy",
            lastname=token,
            email=f"{token}-fresh@example.com",
            status=CandidateStatus.active,
        )
        db.add(fresh)
        await db.commit()
        fresh_id = fresh.id

    data = await _search(
        app_client,
        app_auth_headers,
        {"q": f"Nowy {token}", "exclude_in_job_id": world["job_id"]},
    )

    assert [item["id"] for item in data["items"]] == [fresh_id]
    assert data["items"][0]["last_recruitment"] is None
    assert data["in_job_matches"] == []


async def test_without_job_context_nothing_extra_is_computed(
    app_client: AsyncClient, app_auth_headers: dict
):
    token = _token()
    world = await _seed(token)

    data = await _search(app_client, app_auth_headers, {"q": f"Imiennik {token}"})

    ids = {item["id"] for item in data["items"]}
    assert {world["free"], world["closed"], world["active"]} <= ids
    assert data["in_job_matches"] == []
    assert all(item["last_recruitment"] is None for item in data["items"])


async def test_keyword_search_does_not_list_people_in_the_job(
    app_client: AsyncClient, app_auth_headers: dict
):
    # Sekcja imienników jest tylko dla frazy wyglądającej na osobę — kubełki
    # boolowskie i fraza „po znaczeniu” to przeglądanie, nie szukanie kogoś.
    token = _token()
    world = await _seed(token)

    data = await _search(
        app_client,
        app_auth_headers,
        {"q_all": [token], "exclude_in_job_id": world["job_id"]},
    )

    assert world["free"] in {item["id"] for item in data["items"]}
    assert data["in_job_matches"] == []
