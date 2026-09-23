"""``GET /api/pipeline/job/{job_id}/moves`` — dziennik ruchów całej rekrutacji.

Prawdziwy Postgres i prawdziwa autoryzacja; baza jest wspólna i nieczyszczona,
więc każdy test zakłada własną rekrutację i asertuje wyłącznie jej wiersze.
"""

import uuid
from datetime import datetime, timedelta, timezone

from httpx import AsyncClient

import app.models  # noqa: F401  (zarejestruj wszystkie mappery)
from app.core.database import AsyncSessionLocal
from app.core.security import create_access_token, hash_password
from app.models.candidate import Candidate
from app.models.client import Client
from app.models.job import Job, JobStatus
from app.models.pipeline_template import (
    PipelineStageDef,
    PipelineTemplate,
    StageCategoryEnum,
)
from app.models.recruitment_pipeline import CandidateStage, PipelineStage
from app.models.section_permission import UserSectionOverride
from app.models.user import User, UserRole


async def _user(role: UserRole, *, pipeline: str | None = None):
    tag = uuid.uuid4().hex[:8]
    async with AsyncSessionLocal() as db:
        user = User(
            email=f"moves-{role.value}-{tag}@example.com",
            password_hash=hash_password(f"T3st_{tag}!Moves"),
            name=f"Moves {role.value} {tag}",
            role=role,
            is_active=True,
        )
        db.add(user)
        await db.flush()
        if pipeline is not None:
            db.add(
                UserSectionOverride(
                    user_id=user.id, section="pipeline", access=pipeline
                )
            )
        await db.commit()
        return (
            user.id,
            user.name,
            {"Authorization": f"Bearer {create_access_token(user.id, role.value)}"},
        )


async def _world(recruiter_id: int) -> dict:
    """Dwie osoby; ruchy przeplatają się w czasie, żeby LAG musiał partycjonować."""
    tag = uuid.uuid4().hex[:8]
    t0 = datetime.now(timezone.utc) - timedelta(days=3)
    async with AsyncSessionLocal() as db:
        client = Client(name=f"Moves client {tag}")
        template = PipelineTemplate(name=f"Moves tpl {tag}")
        db.add_all([client, template])
        await db.flush()
        custom = PipelineStageDef(
            template_id=template.id,
            name="Rozmowa techniczna v3",
            order=0,
            category=StageCategoryEnum.internal,
            legacy_enum_value="interview",
            is_terminal=False,
        )
        job = Job(
            title=f"Moves job {tag}",
            client_id=client.id,
            status=JobStatus.published,
            recruiter_id=recruiter_id,
            pipeline_template_id=template.id,
        )
        anna = Candidate(name="Anna", lastname=f"Ruch-{tag}", email=f"a-{tag}@ex.com")
        bo = Candidate(name="Bo", lastname=f"Ruch-{tag}", email=f"b-{tag}@ex.com")
        db.add_all([custom, job, anna, bo])
        await db.flush()

        def stage(candidate, pipeline_stage, minutes, **extra) -> CandidateStage:
            return CandidateStage(
                candidate_id=candidate.id,
                job_id=job.id,
                stage=pipeline_stage,
                moved_at=t0 + timedelta(minutes=minutes),
                **extra,
            )

        rows = [
            stage(
                anna,
                PipelineStage.new,
                0,
                external_source="traffit",
                external_id=f"mv-{tag}-1",
            ),
            stage(bo, PipelineStage.new, 1, moved_by=recruiter_id),
            stage(anna, PipelineStage.screening, 2, moved_by=recruiter_id),
            stage(
                bo,
                PipelineStage.interview,
                3,
                moved_by=recruiter_id,
                stage_def_id=custom.id,
            ),
            stage(anna, PipelineStage.verified, 4, moved_by=recruiter_id),
        ]
        db.add_all(rows)
        await db.commit()
        return {
            "job_id": job.id,
            "tag": tag,
            "anna": anna.id,
            "bo": bo.id,
            "custom_name": custom.name,
            "ids": [r.id for r in rows],
        }


def _url(job_id: int) -> str:
    return f"/api/pipeline/job/{job_id}/moves"


async def test_moves_are_newest_first_with_the_previous_stage_per_person(
    app_client: AsyncClient,
):
    recruiter_id, recruiter_name, recruiter = await _user(UserRole.recruiter)
    world = await _world(recruiter_id)

    response = await app_client.get(_url(world["job_id"]), headers=recruiter)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["total"] == 5 and body["next_offset"] is None
    assert body["candidate_names_redacted"] is False
    items = body["items"]
    assert [i["id"] for i in items] == list(reversed(world["ids"]))
    assert [
        (i["candidate_id"], i["from_stage_name"], i["to_stage_name"]) for i in items
    ] == [
        (world["anna"], "Screening", "Zweryfikowany"),
        # Poprzedni etap Bo to JEGO „new", nie sąsiedni w czasie wiersz Anny;
        # nazwa kolumny szablonu wygrywa z etykietą enuma.
        (world["bo"], "Nowi / Analiza CV", world["custom_name"]),
        (world["anna"], "Nowi / Analiza CV", "Screening"),
        (world["bo"], None, "Nowi / Analiza CV"),
        (world["anna"], None, "Nowi / Analiza CV"),
    ]
    assert items[0]["candidate_name"] == f"Anna Ruch-{world['tag']}"
    assert items[0]["moved_by_id"] == recruiter_id
    assert items[0]["moved_by_name"] == recruiter_name
    assert items[0]["moved_at"] > items[1]["moved_at"]
    assert [i["source"] for i in items] == ["nexus"] * 4 + ["traffit"]
    assert items[-1]["moved_by_id"] is None and items[-1]["moved_by_name"] is None


async def test_moves_pagination_keeps_lag_and_total(app_client: AsyncClient):
    recruiter_id, _, recruiter = await _user(UserRole.recruiter)
    world = await _world(recruiter_id)

    page = await app_client.get(
        _url(world["job_id"]), params={"limit": 2, "offset": 1}, headers=recruiter
    )
    body = page.json()
    assert body["total"] == 5 and body["next_offset"] == 3
    assert [i["id"] for i in body["items"]] == [world["ids"][3], world["ids"][2]]
    # Poprzedni etap leży POZA stroną — LAG liczy się przed LIMIT-em.
    assert body["items"][1]["from_stage_name"] == "Nowi / Analiza CV"

    beyond = await app_client.get(
        _url(world["job_id"]), params={"offset": 50}, headers=recruiter
    )
    assert beyond.json()["items"] == [] and beyond.json()["total"] == 5
    assert (
        await app_client.get(
            _url(world["job_id"]), params={"limit": 0}, headers=recruiter
        )
    ).status_code == 422


async def test_moves_follow_the_kanban_read_gate(app_client: AsyncClient):
    recruiter_id, _, recruiter = await _user(UserRole.recruiter)
    _, _, outsider = await _user(UserRole.recruiter)
    _, _, no_pipeline = await _user(UserRole.recruiter, pipeline="none")
    _, _, finance = await _user(UserRole.finance)
    _, _, viewer = await _user(UserRole.user)
    world = await _world(recruiter_id)
    url = _url(world["job_id"])

    assert (await app_client.get(url)).status_code == 401
    # Od 23.09.2026 dziennik czyta każda rola wewnętrzna — także rekruter spoza
    # zespołu rekrutacji. Odebrana sekcja i stara rola podglądu nadal 403.
    outsider_body = await app_client.get(url, headers=outsider)
    assert outsider_body.status_code == 200, outsider_body.text
    assert {i["candidate_id"] for i in outsider_body.json()["items"]} == {
        world["anna"],
        world["bo"],
    }
    assert (await app_client.get(url, headers=no_pipeline)).status_code == 403
    assert (await app_client.get(url, headers=viewer)).status_code == 403
    # Finanse czytają organizacyjnie — jak tablicę.
    assert (await app_client.get(url, headers=finance)).status_code == 200
    assert (
        await app_client.get(_url(2000000000), headers=recruiter)
    ).status_code == 404

    # Tablica i dziennik odpowiadają tak samo tej samej osobie.
    for headers in (recruiter, outsider, viewer):
        board = await app_client.get(
            f"/api/pipeline/kanban/{world['job_id']}", headers=headers
        )
        moves = await app_client.get(url, headers=headers)
        assert board.status_code == moves.status_code


async def test_moves_redact_names_without_candidate_read(
    app_client: AsyncClient, monkeypatch
):
    import app.api.pipeline as pipeline_api

    recruiter_id, _, recruiter = await _user(UserRole.recruiter)
    world = await _world(recruiter_id)
    # Dziś każda rola operacyjna z odczytem sekcji ma odczyt kandydatów, więc
    # redakcja jest zabezpieczeniem na przyszłość — sprawdzamy ją na samej trasie.
    monkeypatch.setattr(pipeline_api, "user_has_candidate_read", lambda user: False)

    body = (await app_client.get(_url(world["job_id"]), headers=recruiter)).json()
    assert body["candidate_names_redacted"] is True
    assert {i["candidate_name"] for i in body["items"]} == {None}
    assert {i["candidate_id"] for i in body["items"]} == {world["anna"], world["bo"]}
    assert world["tag"] not in str(body)
