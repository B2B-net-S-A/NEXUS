"""Zatrudnienie podpowiada domknięcie rekrutacji — ale niczego nie zamyka.

Do 09.2026 ruch na `hired` nie dotykał stanu rekrutacji: `headcount` nie był
dekrementowany, a `close_reason = filled_by_us` nie był ustawiany NIGDZIE
w kodzie pipeline'u. Skutek widać w danych — 315 rekrutacji zamkniętych
w 90 dni, wszystkie bez powodu, więc raport wygranych i przegranych nie miał
z czego policzyć wygranej.

Automatu tu NIE MA świadomie (decyzja właściciela 2026-09-03): 99,6% ruchu
w pipelinie pochodzi z importu, więc automatyczne domykanie działałoby
retroaktywnie na tysiącach rekrutacji. Te testy pilnują OBU stron: że
podpowiedź powstaje, i że stan rekrutacji zostaje nietknięty.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import app.models  # noqa: F401  (zarejestruj wszystkie mappery)
from app.models.skill import Skill  # noqa: F401
from sqlalchemy import select

NOW = datetime(2035, 6, 4, 8, 0, tzinfo=timezone.utc)


async def _seed(headcount: int) -> dict:
    from app.core.database import AsyncSessionLocal
    from app.models.candidate import Candidate, CandidateStatus
    from app.models.client import Client
    from app.models.job import Job, JobStatus

    tag = uuid.uuid4().hex[:8]
    async with AsyncSessionLocal() as db:
        client = Client(name=f"FillClient-{tag}")
        db.add(client)
        await db.commit()
        await db.refresh(client)

        job = Job(
            title=f"FillJob-{tag}",
            status=JobStatus.published,
            client_id=client.id,
            headcount=headcount,
        )
        candidate = Candidate(
            name="Ewa",
            lastname=f"Fill-{tag}",
            email=f"fill-{tag}@example.com",
            status=CandidateStatus.active,
        )
        db.add_all([job, candidate])
        await db.commit()
        await db.refresh(job)
        await db.refresh(candidate)
        return {"job_id": job.id, "candidate_id": candidate.id, "client_id": client.id}


async def _hire(app_client, headers, world: dict) -> None:
    from app.core.database import AsyncSessionLocal
    from app.models.recruitment_pipeline import CandidateStage, PipelineStage

    async with AsyncSessionLocal() as db:
        db.add(
            CandidateStage(
                candidate_id=world["candidate_id"],
                job_id=world["job_id"],
                stage=PipelineStage.screening,
                moved_at=NOW,
            )
        )
        await db.commit()

    resp = await app_client.post(
        "/api/pipeline/move",
        headers=headers,
        json={
            "candidate_id": world["candidate_id"],
            "job_id": world["job_id"],
            "stage": "hired",
        },
    )
    assert resp.status_code == 200, resp.text


async def _hint_count(job_id: int) -> int:
    from app.core.database import AsyncSessionLocal
    from app.models.notification import Notification, NotificationType

    async with AsyncSessionLocal() as db:
        rows = (
            (
                await db.execute(
                    select(Notification).where(
                        Notification.related_entity_type == "job",
                        Notification.related_entity_id == job_id,
                        Notification.notification_type
                        == NotificationType.suggest_next_step,
                    )
                )
            )
            .scalars()
            .all()
        )
        return len(rows)


async def test_last_vacancy_filled_produces_a_hint(app_client, app_auth_headers):
    world = await _seed(headcount=1)

    await _hire(app_client, app_auth_headers, world)

    assert await _hint_count(world["job_id"]) > 0


async def test_the_hint_does_not_close_the_job_or_stamp_a_reason(
    app_client, app_auth_headers
):
    """Podpowiedź, nie automat — decyzja zostaje po stronie człowieka."""
    from app.core.database import AsyncSessionLocal
    from app.models.job import Job, JobStatus

    world = await _seed(headcount=1)

    await _hire(app_client, app_auth_headers, world)

    async with AsyncSessionLocal() as db:
        job = await db.scalar(select(Job).where(Job.id == world["job_id"]))
        assert job.status == JobStatus.published
        assert job.close_reason is None
        assert job.closed_at is None
        # `headcount` to deklaracja zapotrzebowania, nie licznik wolnych etatów —
        # dekrementowanie go zniszczyłoby informację, ilu ludzi zamawiał klient.
        assert job.headcount == 1


async def test_no_hint_while_vacancies_remain(app_client, app_auth_headers):
    world = await _seed(headcount=3)

    await _hire(app_client, app_auth_headers, world)

    assert await _hint_count(world["job_id"]) == 0


async def test_placements_are_counted_once_per_pair():
    """Powtórzony wiersz `hired` nie może liczyć się jako drugi placement."""
    from app.core.database import AsyncSessionLocal
    from app.models.recruitment_pipeline import CandidateStage, PipelineStage
    from app.services.job_fill import is_fully_staffed, placements_by_job

    world = await _seed(headcount=2)
    async with AsyncSessionLocal() as db:
        db.add_all(
            [
                CandidateStage(
                    candidate_id=world["candidate_id"],
                    job_id=world["job_id"],
                    stage=PipelineStage.hired,
                    moved_at=NOW,
                ),
                CandidateStage(
                    candidate_id=world["candidate_id"],
                    job_id=world["job_id"],
                    stage=PipelineStage.hired,
                    moved_at=NOW,
                ),
            ]
        )
        await db.commit()

        counted = (await placements_by_job(db, [world["job_id"]])).get(
            world["job_id"], 0
        )

    assert counted == 1, "Dwa wiersze `hired` tej samej pary to jeden placement."
    assert is_fully_staffed(2, counted) is False


async def test_the_hint_is_sent_once_not_on_every_later_hire(
    app_client, app_auth_headers
):
    """Druga osoba zatrudniona na tej samej rekrutacji nie powtarza komunikatu.

    Bez dedupu KAŻDE kolejne zatrudnienie rozsyłałoby ten sam tekst do
    wszystkich admin/DL/TAC — a powtórka niczego nie dodaje i uczy ignorować
    powiadomienia.
    """
    from app.core.database import AsyncSessionLocal
    from app.models.candidate import Candidate, CandidateStatus
    from app.models.recruitment_pipeline import CandidateStage, PipelineStage

    world = await _seed(headcount=1)
    await _hire(app_client, app_auth_headers, world)
    after_first = await _hint_count(world["job_id"])
    assert after_first > 0

    # Druga osoba na tej samej, jednoetatowej rekrutacji.
    async with AsyncSessionLocal() as db:
        second = Candidate(
            name="Piotr",
            lastname=f"Second-{world['job_id']}",
            email=f"second-{world['job_id']}@example.com",
            status=CandidateStatus.active,
        )
        db.add(second)
        await db.commit()
        await db.refresh(second)
        db.add(
            CandidateStage(
                candidate_id=second.id,
                job_id=world["job_id"],
                stage=PipelineStage.screening,
                moved_at=NOW,
            )
        )
        await db.commit()
        second_id = second.id

    resp = await app_client.post(
        "/api/pipeline/move",
        headers=app_auth_headers,
        json={
            "candidate_id": second_id,
            "job_id": world["job_id"],
            "stage": "hired",
        },
    )
    assert resp.status_code == 200, resp.text

    assert await _hint_count(world["job_id"]) == after_first
