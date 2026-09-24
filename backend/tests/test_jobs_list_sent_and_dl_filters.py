"""Filtry listy rekrutacji: „Wysłanych do klienta" i „Delivery Lead".

``min_sent``/``max_sent`` liczą OSOBY (distinct kandydat), które w danej
rekrutacji doszły do „CV wysłane" albo dalej (rozmowa u klienta, akceptacja,
zatrudnienie) — z widoku ``analytics_first_milestones`` (reguła D2), więc
powrót na etap nie dubluje osoby, a rozmowa WEWNĘTRZNA (``interview``) się nie
liczy.

Baza testowa jest wspólna i nieczyszczona — każde zapytanie zawęża się do
klientów zasianych w tym teście (``client_id``).
"""

import uuid
from datetime import datetime, timedelta, timezone

import app.models  # noqa: F401  (zarejestruj wszystkie mappery)
import pytest
from httpx import AsyncClient


async def _seed_job_with_stages(
    stages_per_candidate: list[list[str]],
    *,
    delivery_lead_id: int | None = None,
) -> dict:
    """Rekrutacja u własnego klienta; każda lista = kolejne etapy jednej osoby."""
    from app.core.database import AsyncSessionLocal
    from app.models.candidate import Candidate, CandidateStatus
    from app.models.client import Client
    from app.models.job import Job, JobStatus
    from app.models.recruitment_pipeline import CandidateStage, PipelineStage

    tag = uuid.uuid4().hex[:8]
    now = datetime.now(timezone.utc)
    async with AsyncSessionLocal() as db:
        client = Client(name=f"SentFilterClient-{tag}")
        db.add(client)
        await db.flush()
        job = Job(
            title=f"SentFilterJob-{tag}",
            status=JobStatus.published,
            client_id=client.id,
            delivery_lead_id=delivery_lead_id,
        )
        db.add(job)
        await db.flush()
        for index, stages in enumerate(stages_per_candidate):
            candidate = Candidate(
                name="Wysłany",
                lastname=f"SentFilter-{index}-{tag}",
                email=f"sentfilter-{index}-{tag}@example.com",
                status=CandidateStatus.active,
            )
            db.add(candidate)
            await db.flush()
            for step, stage in enumerate(stages):
                db.add(
                    CandidateStage(
                        candidate_id=candidate.id,
                        job_id=job.id,
                        stage=PipelineStage(stage),
                        moved_at=now - timedelta(days=10 - step),
                    )
                )
        await db.commit()
        return {"job_id": job.id, "client_id": client.id}


async def _ids(app_client: AsyncClient, headers: dict, client_ids: list[int], **params):
    response = await app_client.get(
        "/api/jobs",
        params={"client_id": client_ids, "page_size": 100, **params},
        headers=headers,
    )
    assert response.status_code == 200, response.text
    return {row["id"] for row in response.json()["items"]}


@pytest.mark.asyncio
async def test_sent_filter_counts_distinct_people_at_or_past_cv_sent(
    app_client: AsyncClient, app_auth_headers: dict
):
    # Dwie osoby wysłane: A był na „CV wysłane" DWA razy (powrót na etap),
    # B przeskoczył od razu na rozmowę u klienta (import Traffita). C doszedł
    # tylko do rozmowy WEWNĘTRZNEJ — nie był u klienta.
    two_sent = await _seed_job_with_stages(
        [
            ["new", "verified", "cv_sent", "verified", "cv_sent"],
            ["new", "client_interview"],
            ["new", "verified", "interview"],
        ]
    )
    nobody_sent = await _seed_job_with_stages([["new", "screening", "verified"]])
    empty = await _seed_job_with_stages([])
    client_ids = [two_sent["client_id"], nobody_sent["client_id"], empty["client_id"]]

    assert await _ids(app_client, app_auth_headers, client_ids, min_sent=1) == {
        two_sent["job_id"]
    }
    assert await _ids(app_client, app_auth_headers, client_ids, min_sent=2) == {
        two_sent["job_id"]
    }
    # A liczy się RAZ, mimo dwóch wierszy „CV wysłane".
    assert await _ids(app_client, app_auth_headers, client_ids, min_sent=3) == set()
    assert await _ids(app_client, app_auth_headers, client_ids, max_sent=0) == {
        nobody_sent["job_id"],
        empty["job_id"],
    }
    assert await _ids(
        app_client, app_auth_headers, client_ids, min_sent=1, max_sent=2
    ) == {two_sent["job_id"]}


@pytest.mark.asyncio
async def test_sent_filter_total_matches_rows_and_rejects_inverted_range(
    app_client: AsyncClient, app_auth_headers: dict
):
    seeded = await _seed_job_with_stages([["new", "cv_sent"]])
    response = await app_client.get(
        "/api/jobs",
        params={"client_id": seeded["client_id"], "min_sent": 1},
        headers=app_auth_headers,
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["total"] == len(body["items"]) == 1

    inverted = await app_client.get(
        "/api/jobs",
        params={"client_id": seeded["client_id"], "min_sent": 3, "max_sent": 1},
        headers=app_auth_headers,
    )
    assert inverted.status_code == 422


@pytest.mark.asyncio
async def test_delivery_lead_filter_accepts_one_or_many_ids(
    app_client: AsyncClient, app_auth_headers: dict
):
    me = (await app_client.get("/api/auth/me", headers=app_auth_headers)).json()["id"]
    mine = await _seed_job_with_stages([], delivery_lead_id=me)
    unassigned = await _seed_job_with_stages([])
    client_ids = [mine["client_id"], unassigned["client_id"]]

    # Pojedyncze id — kontrakt zakładki „Aktywne rekrutacje" w portalu DL.
    assert await _ids(
        app_client, app_auth_headers, client_ids, delivery_lead_id=me
    ) == {mine["job_id"]}
    # Kilka id = LUB.
    assert await _ids(
        app_client,
        app_auth_headers,
        client_ids,
        delivery_lead_id=[me, 999_999_999],
    ) == {mine["job_id"]}
