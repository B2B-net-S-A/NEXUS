"""CV do klienta po nowym CV kandydata (29.10.2026, decyzje Artura D1 = A).

Rekruter wgrywa w rekrutacji nowe CV (np. z LinkedIna). Odpowiedź wgrania
mówi, co dzieje się z CV do klienta pary: nietknięty szkic z generatora
generuje się od nowa z nowego pliku i sam się podmienia, poprawiony albo
zatwierdzony — pytamy, brak CV — potwierdzenia jak od 21.10, po „CV wysłane”
— nic. Generację podmieniamy za CV tylko wtedy, gdy nikt go w międzyczasie
nie ruszył.
"""

from __future__ import annotations

import pytest
from fastapi import HTTPException
from httpx import AsyncClient
from sqlalchemy import select

from app.core.database import AsyncSessionLocal
from app.models.activity import Activity
from app.models.cv_generated_document import CvGeneratedDocument
from app.services.new_cv_company_cv import INTENT_ACTION, REPLACE_ACTION
from tests.test_stage_cv_upload import (
    CLIENT_CV_NAME,
    NEW_PDF,
    _auto_cv,
    _client_docx,
    _client_world,
    _documents,
    _stage_cv,
    _upload,
    _upload_docx,
)

pytestmark = pytest.mark.asyncio


@pytest.fixture(autouse=True)
def _no_cv_reading(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "app.services.cv_text_extractor.extract_text",
        lambda *_args, **_kwargs: "",
    )


@pytest.fixture
def generation(monkeypatch: pytest.MonkeyPatch) -> list[dict]:
    """Zlecenia generacji: wiersz „processing” jak prawdziwe, bez modelu i kolejki."""
    calls: list[dict] = []

    async def _enqueue(db, **kwargs):
        calls.append(kwargs)
        row = CvGeneratedDocument(
            candidate_id=kwargs["candidate"].id,
            job_id=kwargs["stage"].job_id,
            stage_id=kwargs["stage"].id,
            candidate_name="Ewa Fikcyjna",
            filename="nowe.docx",
            status="processing",
            origin="manual",
        )
        db.add(row)
        await db.flush()
        return row.id, 0, "Ewa Fikcyjna"

    async def _no_job(_durable_id: int) -> None:
        return None

    monkeypatch.setattr(
        "app.api.cv_generator_b2b.enqueue_candidate_generation", _enqueue
    )
    monkeypatch.setattr(
        "app.services.cv_generator_b2b.durable_jobs.execute_job", _no_job
    )
    return calls


async def _finish(generated_id: int) -> None:
    async with AsyncSessionLocal() as db:
        row = await db.get(CvGeneratedDocument, generated_id)
        row.status = "ready"
        row.render_payload = {
            "name": "Ewa Fikcyjna",
            "position": "Analityk",
            "why_points": ["Nowe doświadczenie z nowego CV"],
        }
        await db.commit()


async def _edit(stage_id: int) -> None:
    async with AsyncSessionLocal() as db:
        from app.models.candidate_stage_cv import CandidateStageCV

        csv = await db.scalar(
            select(CandidateStageCV).where(
                CandidateStageCV.candidate_stage_id == stage_id
            )
        )
        csv.branded_draft_html = "<p>Poprawione przez rekrutera</p>"
        csv.edit_revision = (csv.edit_revision or 0) + 1
        await db.commit()


async def _attach(stage_id: int, generated_id: int) -> bool:
    from app.services.cv_auto_generate import attach_as_stage_draft

    return await attach_as_stage_draft(
        stage_id=stage_id,
        user_id=1,
        generated_id=generated_id,
        activity_action="branded_cv_attached_after_generation",
    )


async def test_untouched_draft_regenerates_from_the_new_cv_and_replaces_itself(
    app_client: AsyncClient,
    app_auth_headers: dict[str, str],
    generation: list[dict],
) -> None:
    world = await _client_world(stage="verified")
    auto_id = await _auto_cv(world)

    res = await _upload(app_client, app_auth_headers, world["stage_id"])

    assert res.status_code == 200, res.text
    body = res.json()
    assert body["company_cv"] == "regenerating"
    assert body["company_cv_stage_id"] == world["stage_id"]
    new_doc = next(d for d in await _documents(world["candidate_id"]) if d.is_primary)
    assert body["uploaded_document_id"] == new_doc.id
    assert len(generation) == 1
    assert generation[0]["cv_document_id"] == new_doc.id
    assert generation[0]["attach_stage_draft"] is True

    await _finish(body["regenerating_document_id"])
    assert await _attach(world["stage_id"], body["regenerating_document_id"])

    csv = await _stage_cv(world["stage_id"])
    assert csv.generated_document_id == body["regenerating_document_id"]
    assert "Nowe doświadczenie" in csv.branded_draft_html
    async with AsyncSessionLocal() as db:
        actions = (
            await db.scalars(
                select(Activity.action).where(
                    Activity.entity_type == "candidate_stage_cv",
                    Activity.entity_id == csv.id,
                )
            )
        ).all()
    assert INTENT_ACTION in actions and REPLACE_ACTION in actions

    # „Cofnij” = „Wróć do poprzedniej”: auto-CV wraca z migawki.
    restored = await app_client.post(
        f"/api/candidates/stages/{world['stage_id']}/cv/branded/restore-previous",
        headers=app_auth_headers,
        json={"expected_revision": csv.edit_revision},
    )
    assert restored.status_code == 200, restored.text
    assert (await _stage_cv(world["stage_id"])).generated_document_id == auto_id


async def test_edit_during_generation_wins_over_the_new_version(
    app_client: AsyncClient,
    app_auth_headers: dict[str, str],
    generation: list[dict],
) -> None:
    world = await _client_world(stage="verified")
    await _auto_cv(world)
    body = (await _upload(app_client, app_auth_headers, world["stage_id"])).json()
    await _edit(world["stage_id"])

    await _finish(body["regenerating_document_id"])

    assert not await _attach(world["stage_id"], body["regenerating_document_id"])
    assert (
        "Poprawione przez rekrutera"
        in (await _stage_cv(world["stage_id"])).branded_draft_html
    )


async def test_edited_cv_is_not_regenerated_without_asking(
    app_client: AsyncClient,
    app_auth_headers: dict[str, str],
    generation: list[dict],
) -> None:
    world = await _client_world(stage="verified")
    await _auto_cv(world)
    await _edit(world["stage_id"])

    res = await _upload(app_client, app_auth_headers, world["stage_id"])

    assert res.status_code == 200, res.text
    body = res.json()
    assert (body["company_cv"], body["company_cv_status"]) == ("ask", "draft")
    assert body["regenerating_document_id"] is None
    assert generation == []

    # „Generuj z nowego CV”: ta sama generacja, a gotowa wersja zastępuje CV.
    csv = await _stage_cv(world["stage_id"])
    asked = await app_client.post(
        f"/api/candidates/stages/{world['stage_id']}/cv/branded/regenerate-from-original",
        headers=app_auth_headers,
        json={"expected_revision": csv.edit_revision},
    )
    assert asked.status_code == 200, asked.text
    generated_id = asked.json()["generated_document_id"]
    assert generation[0]["cv_document_id"] == body["uploaded_document_id"]
    await _finish(generated_id)
    assert await _attach(world["stage_id"], generated_id)
    assert (await _stage_cv(world["stage_id"])).generated_document_id == generated_id


async def test_regenerate_refuses_a_stale_revision(
    app_client: AsyncClient,
    app_auth_headers: dict[str, str],
    generation: list[dict],
) -> None:
    world = await _client_world(stage="verified")
    await _auto_cv(world)
    await _edit(world["stage_id"])

    res = await app_client.post(
        f"/api/candidates/stages/{world['stage_id']}/cv/branded/regenerate-from-original",
        headers=app_auth_headers,
        json={"expected_revision": 0},
    )

    assert res.status_code == 409, res.text
    assert generation == []


async def test_no_client_cv_yet_waits_for_confirmations(
    app_client: AsyncClient,
    app_auth_headers: dict[str, str],
    generation: list[dict],
) -> None:
    world = await _client_world(stage="screening")

    res = await _upload(app_client, app_auth_headers, world["stage_id"])

    assert res.status_code == 200, res.text
    assert res.json()["company_cv"] == "confirm"
    assert generation == []

    nothing = await app_client.post(
        f"/api/candidates/stages/{world['stage_id']}/cv/branded/regenerate-from-original",
        headers=app_auth_headers,
        json={"expected_revision": 0},
    )
    assert nothing.status_code == 409, nothing.text


async def test_after_cv_sent_the_client_cv_stays(
    app_client: AsyncClient,
    app_auth_headers: dict[str, str],
    generation: list[dict],
) -> None:
    world = await _client_world(stage="cv_sent")
    await _auto_cv(world)

    res = await _upload(app_client, app_auth_headers, world["stage_id"])

    assert res.status_code == 200, res.text
    assert res.json()["company_cv"] == "locked"
    assert generation == []


async def test_refused_generation_still_uploads_and_asks(
    app_client: AsyncClient,
    app_auth_headers: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _refuse(db, **kwargs):
        raise HTTPException(422, "Reguła klienta wymaga numeru projektu.")

    monkeypatch.setattr(
        "app.api.cv_generator_b2b.enqueue_candidate_generation", _refuse
    )
    world = await _client_world(stage="verified")
    await _auto_cv(world)

    res = await _upload(app_client, app_auth_headers, world["stage_id"])

    assert res.status_code == 200, res.text
    assert res.json()["company_cv"] == "ask"
    csv = await _stage_cv(world["stage_id"])
    assert csv.original_snapshot_source == "manual_upload"


async def _set_stage(stage_id: int, **values) -> None:
    from app.models.candidate_stage_cv import CandidateStageCV

    async with AsyncSessionLocal() as db:
        csv = await db.scalar(
            select(CandidateStageCV).where(
                CandidateStageCV.candidate_stage_id == stage_id
            )
        )
        for name, value in values.items():
            setattr(csv, name, value)
        await db.commit()


async def test_older_upload_finishing_late_does_not_win(
    app_client: AsyncClient,
    app_auth_headers: dict[str, str],
    generation: list[dict],
) -> None:
    """Przegląd 29.10: dwa szybkie wgrania — wygrywa ostatni plik, nie szybszy job."""
    world = await _client_world(stage="verified")
    await _auto_cv(world)
    first = (await _upload(app_client, app_auth_headers, world["stage_id"])).json()
    second = (
        await _upload(
            app_client,
            app_auth_headers,
            world["stage_id"],
            filename="poprawne-cv.pdf",
            content=NEW_PDF + b"% poprawne\n",
        )
    ).json()
    assert (first["company_cv"], second["company_cv"]) == (
        "regenerating",
        "regenerating",
    )

    await _finish(first["regenerating_document_id"])
    assert not await _attach(world["stage_id"], first["regenerating_document_id"])
    await _finish(second["regenerating_document_id"])
    assert await _attach(world["stage_id"], second["regenerating_document_id"])


async def test_file_sent_to_identity_quarantine_never_becomes_the_client_cv(
    app_client: AsyncClient,
    app_auth_headers: dict[str, str],
    generation: list[dict],
) -> None:
    """Bramka tożsamości oddała kopię etapu poprzedniemu CV — podmiany nie ma."""
    world = await _client_world(stage="verified")
    await _auto_cv(world)
    body = (await _upload(app_client, app_auth_headers, world["stage_id"])).json()
    await _set_stage(world["stage_id"], original_cv_sha256="0" * 64)

    await _finish(body["regenerating_document_id"])

    assert not await _attach(world["stage_id"], body["regenerating_document_id"])


async def test_consent_attached_during_generation_is_kept(
    app_client: AsyncClient,
    app_auth_headers: dict[str, str],
    generation: list[dict],
) -> None:
    world = await _client_world(stage="verified")
    await _auto_cv(world)
    body = (await _upload(app_client, app_auth_headers, world["stage_id"])).json()
    await _set_stage(world["stage_id"], branded_consent_content=b"zgoda")

    await _finish(body["regenerating_document_id"])

    assert not await _attach(world["stage_id"], body["regenerating_document_id"])
    assert (await _stage_cv(world["stage_id"])).branded_consent_content == b"zgoda"


async def test_candidate_mode_keeps_a_b2b_named_file_as_the_candidate_cv(
    app_client: AsyncClient,
    app_auth_headers: dict[str, str],
    generation: list[dict],
) -> None:
    """„Dodaj CV” w profilu: plik to CV kandydata, także z „B2B” w nazwie."""
    world = await _client_world(stage="verified")
    auto_id = await _auto_cv(world)

    res = await _upload_docx(
        app_client,
        app_auth_headers,
        world["stage_id"],
        _client_docx(),
        data={"mode": "candidate"},
    )

    assert res.status_code == 200, res.text
    body = res.json()
    assert (body["outcome"], body["company_cv"]) == ("original", "regenerating")
    docs = await _documents(world["candidate_id"])
    assert [d.filename for d in docs if d.is_primary] == [CLIENT_CV_NAME]
    assert (await _stage_cv(world["stage_id"])).generated_document_id == auto_id


async def test_candidate_pipelines_say_whether_the_recruitment_is_closed(
    app_client: AsyncClient, app_auth_headers: dict[str, str]
) -> None:
    """„Dodaj CV” w profilu pomija zamknięte rekrutacje — karta zostaje w „Nowych”."""
    from app.models.job import Job, JobStatus

    world = await _client_world(stage="new")
    async with AsyncSessionLocal() as db:
        job = await db.get(Job, world["job_id"])
        job.status = JobStatus.closed
        await db.commit()

    res = await app_client.get(
        f"/api/candidates/{world['candidate_id']}/pipelines", headers=app_auth_headers
    )

    assert res.status_code == 200, res.text
    [row] = res.json()["pipelines"]
    assert (row["board_column"], row["job_status"]) == ("new", "closed")
