"""Reakcja kandydata na ofertę dojeżdża do karty kanbana.

`candidate_stages.candidate_offer_response` jest zapisywana od migracji 0066
(modal wycofania po akceptacji), ale do 09.2026 NIE była w żadnej odpowiedzi
API — „Przyjął / Odrzucił / Oczekuje" dawało się zobaczyć wyłącznie w bazie.
Krok 07 „Rozmowy i decyzja" pokazuje ją przy ofercie.

Ten test istnieje, bo dokładnie tę klasę defektu repo już zaliczyło: pole
`cost_orders_enabled` było zaplanowane, opisane w dokumentacji i konsumowane
przez front, a mimo to nigdy nie powstało po stronie API (PR #1196). Wyszło
z odpytania produkcji, nie z zielonych testów — bo testy front-endu mockują
warstwę API i nie mają jak zauważyć, że pola nie ma.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import app.models  # noqa: F401  (zarejestruj wszystkie mappery)
from app.models.skill import Skill  # noqa: F401

NOW = datetime(2036, 5, 12, 9, 0, tzinfo=timezone.utc)


async def _seed(offer_response) -> dict:
    from app.core.database import AsyncSessionLocal
    from app.models.candidate import Candidate, CandidateStatus
    from app.models.client import Client
    from app.models.job import Job, JobStatus
    from app.models.recruitment_pipeline import CandidateStage, PipelineStage

    tag = uuid.uuid4().hex[:8]
    async with AsyncSessionLocal() as db:
        client = Client(name=f"OfferRespClient-{tag}")
        db.add(client)
        await db.commit()
        await db.refresh(client)

        job = Job(
            title=f"OfferRespJob-{tag}",
            status=JobStatus.published,
            client_id=client.id,
        )
        candidate = Candidate(
            name="Inez",
            lastname=f"Oferta-{tag}",
            email=f"offer-{tag}@example.com",
            status=CandidateStatus.active,
        )
        db.add_all([job, candidate])
        await db.commit()
        await db.refresh(job)
        await db.refresh(candidate)

        db.add(
            CandidateStage(
                candidate_id=candidate.id,
                job_id=job.id,
                stage=PipelineStage.acceptance,
                moved_at=NOW,
                candidate_offer_response=offer_response,
            )
        )
        await db.commit()
        return {"job_id": job.id, "candidate_id": candidate.id}


def _find_item(payload: dict, candidate_id: int) -> dict | None:
    for column in payload.get("columns", []):
        for item in column.get("items", []):
            if item.get("candidate_id") == candidate_id:
                return item
    return None


async def test_kanban_card_carries_the_recorded_offer_response(
    app_client, app_auth_headers
) -> None:
    from app.models.candidate_risk import CandidateOfferResponse

    world = await _seed(CandidateOfferResponse.accepted)

    resp = await app_client.get(
        f"/api/pipeline/kanban/{world['job_id']}", headers=app_auth_headers
    )
    assert resp.status_code == 200, resp.text
    item = _find_item(resp.json(), world["candidate_id"])
    assert item is not None, "kandydat zniknął z tablicy"
    assert item["candidate_offer_response"] == "accepted"


async def test_no_recorded_response_is_null_not_pending(
    app_client, app_auth_headers
) -> None:
    """`pending` to JAWNE „czekamy na odpowiedź", a nie brak zapisu.

    Zlanie tych dwóch stanów w jedno kazałoby ekranowi twierdzić, że czekamy na
    odpowiedź kandydata, którego nikt o nic nie zapytał.
    """
    world = await _seed(None)

    resp = await app_client.get(
        f"/api/pipeline/kanban/{world['job_id']}", headers=app_auth_headers
    )
    assert resp.status_code == 200, resp.text
    item = _find_item(resp.json(), world["candidate_id"])
    assert item is not None
    assert item["candidate_offer_response"] is None
