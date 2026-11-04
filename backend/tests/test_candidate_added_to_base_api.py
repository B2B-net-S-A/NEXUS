"""„W bazie od” dojeżdża do API: karta Tablicy, detal kandydata, kolejność listy.

Testy frontu mockują warstwę API, więc nie zauważą, że pola nie ma — stąd ten
plik (ta sama klasa defektu co `cost_orders_enabled`, PR #1196).
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import text

import app.models  # noqa: F401  (zarejestruj wszystkie mappery)

UTC = timezone.utc
IN_TRAFFIT = datetime(2019, 5, 11, 22, 0, tzinfo=UTC)


async def _seed() -> dict:
    from app.core.database import AsyncSessionLocal
    from app.models.client import Client
    from app.models.job import Job, JobStatus
    from app.models.recruitment_pipeline import CandidateStage, PipelineStage

    tag = uuid.uuid4().hex[:8]
    # Jedno słowo z samych liter i cyfr — filtr słów kluczowych listy po CV.
    token = f"wbazie{tag}"
    now = datetime.now(UTC)
    async with AsyncSessionLocal() as db:
        client = Client(name=f"InBaseClient-{tag}")
        db.add(client)
        await db.commit()
        await db.refresh(client)
        job = Job(title=f"InBaseJob-{tag}", status=JobStatus.published, client_id=client.id)
        db.add(job)
        await db.commit()
        await db.refresh(job)

        async def candidate(external_source: str, src, created) -> int:
            return int(
                await db.scalar(
                    text(
                        """
                        INSERT INTO candidates (
                            external_id, external_source, name, lastname, email,
                            source, tags, raw_cv_text, source_created_at,
                            created_at, updated_at
                        ) VALUES (
                            :ext, :es, 'Inez', :ln, :email, :source, CAST(:tags AS JSONB),
                            :cv, :src, :created, :created
                        ) RETURNING id
                        """
                    ),
                    {
                        "ext": f"ib-{uuid.uuid4().hex[:10]}",
                        "es": external_source,
                        "ln": f"Wbazie-{tag}",
                        "email": f"ib-{uuid.uuid4().hex[:10]}@example.com",
                        "source": "traffit" if external_source == "traffit" else "cv_upload",
                        "tags": json.dumps(
                            [{"type": "traffit_source", "value": None, "domain": "Aktywny Search"}]
                            if external_source == "traffit"
                            else []
                        ),
                        "cv": f"devops engineer {token}",
                        "src": src,
                        "created": created,
                    },
                )
            )

        # Z Traffita, z datą u źródła: w bazie od 2019, choć wiersz jest z dziś.
        old_traffit = await candidate("traffit", IN_TRAFFIT, now)
        # Dodana w NEXUSIE dzień temu — nowsza w bazie niż osoba wyżej.
        fresh_nexus = await candidate("manual", None, now - timedelta(days=1))
        # Z Traffita bez daty u źródła — data niedokładna.
        unknown_traffit = await candidate("traffit", None, now - timedelta(days=2))
        for cid in (old_traffit, fresh_nexus, unknown_traffit):
            db.add(
                CandidateStage(
                    candidate_id=cid, job_id=job.id, stage=PipelineStage.new, moved_at=now
                )
            )
        await db.commit()
        return {
            "token": token,
            "job_id": job.id,
            "old_traffit": old_traffit,
            "fresh_nexus": fresh_nexus,
            "unknown_traffit": unknown_traffit,
        }


def _items(payload: dict) -> dict[int, dict]:
    return {
        item["candidate_id"]: item
        for column in payload.get("columns", [])
        for item in column.get("items", [])
    }


def _at(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


async def test_kanban_card_carries_the_added_to_base_date(app_client, app_auth_headers) -> None:
    world = await _seed()

    resp = await app_client.get(f"/api/pipeline/kanban/{world['job_id']}", headers=app_auth_headers)
    assert resp.status_code == 200, resp.text
    items = _items(resp.json())

    old = items[world["old_traffit"]]
    assert _at(old["candidate_added_at"]) == IN_TRAFFIT
    assert old["candidate_added_exact"] is True
    assert items[world["fresh_nexus"]]["candidate_added_exact"] is True
    unknown = items[world["unknown_traffit"]]
    assert unknown["candidate_added_at"] is not None
    assert unknown["candidate_added_exact"] is False


async def test_candidate_detail_carries_date_exactness_and_source(
    app_client, app_auth_headers
) -> None:
    world = await _seed()

    resp = await app_client.get(f"/api/candidates/{world['old_traffit']}", headers=app_auth_headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert _at(body["source_created_at"]) == IN_TRAFFIT
    assert _at(body["added_to_base_at"]) == IN_TRAFFIT
    assert body["added_to_base_exact"] is True
    assert body["added_via"] == "Traffit · Aktywny Search"

    unknown = (
        await app_client.get(f"/api/candidates/{world['unknown_traffit']}", headers=app_auth_headers)
    ).json()
    assert unknown["added_to_base_exact"] is False


async def test_newest_sort_follows_the_added_to_base_date(app_client, app_auth_headers) -> None:
    """Po starej regule (`created_at`) osoba z Traffita z dziś byłaby pierwsza."""
    world = await _seed()

    resp = await app_client.get(
        "/api/candidates",
        params={"q_all": world["token"], "sort": "newest", "page_size": 10},
        headers=app_auth_headers,
    )
    assert resp.status_code == 200, resp.text
    ids = [item["id"] for item in resp.json()["items"]]
    assert ids.index(world["fresh_nexus"]) < ids.index(world["old_traffit"])

    oldest = await app_client.get(
        "/api/candidates",
        params={"q_all": world["token"], "sort": "oldest", "page_size": 10},
        headers=app_auth_headers,
    )
    assert oldest.status_code == 200, oldest.text
    assert oldest.json()["items"][0]["id"] == world["old_traffit"]
