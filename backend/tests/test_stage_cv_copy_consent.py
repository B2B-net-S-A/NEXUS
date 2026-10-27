"""Zrzut zgody RODO dla CV etapu bez dokumentu generatora (12.10.2026).

CV wybrane zamiast generacji (plik Word, kopia z innej rekrutacji) u klienta
z wymogiem zgody dało się dotąd tylko odrzucić. Teraz kopia powstaje, pobranie
czeka na zrzut, a zgodę dołącza ``POST …/cv/branded/consent`` pokwitowaniem
tej samej trasy co przy generacji (kandydat + etap). Kontrakty:

- po dołączeniu pobranie przestaje być blokowane; zrzut można wymienić;
- pokwitowanie z innego etapu albo innej osoby — 422;
- kopia bez wymogu zgody i CV z dokumentem generatora — 409;
- zatwierdzona wersja z niezmienioną treścią jest zatwierdzana ponownie
  z obrazem BEZ wywołania AI; zmieniona treść czeka na człowieka.
"""

from __future__ import annotations

import uuid
from io import BytesIO
from unittest.mock import AsyncMock

import pytest
from httpx import AsyncClient
from PIL import Image
from sqlalchemy import select

import app.models  # noqa: F401
from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.models.activity import Activity
from app.models.cv_document_version import CvDocumentVersion
from app.models.recruitment_pipeline import CandidateStage, PipelineStage
from app.models.user import User, UserRole
from app.services import (
    cv_approval_review,
    cv_consent_check,
    object_storage,
    storage_service,
)
from tests.test_stage_cv_pick_from_profile import (
    _base,
    _csv,
    _generated,
    _revision,
    _seed,
    consent_client,
)


@pytest.fixture(autouse=True)
def _consent_reuse_not_checked(monkeypatch):
    """Te testy wgrywają ten sam obrazek dla wielu kandydatów w jednej bazie;
    kontrolę „ten sam plik u innego kandydata” sprawdza `test_cv_consent_check`."""
    monkeypatch.setattr(
        cv_consent_check, "used_for_other_candidate", AsyncMock(return_value=False)
    )


def _png(color: str = "white") -> bytes:
    out = BytesIO()
    Image.new("RGB", (3, 3), color).save(out, format="PNG")
    return out.getvalue()


@pytest.fixture
def storage(monkeypatch):
    blobs: dict[str, bytes] = {}

    def _upload(content, filename, content_type=None, **_):
        key = f"cv/test/{uuid.uuid4().hex}-{filename}"
        blobs[key] = content
        return key

    monkeypatch.setattr(object_storage, "is_available", lambda: True)
    monkeypatch.setattr(object_storage, "upload_cv", _upload)
    monkeypatch.setattr(object_storage, "download_cv", lambda key: blobs[key])
    monkeypatch.setattr(
        storage_service,
        "save_branded_cv",
        lambda **kwargs: (f"branded/{uuid.uuid4().hex}.html", 10),
    )
    monkeypatch.setattr(settings, "CV_CONSENT_DOWNLOAD_GATE_ENABLED", True)
    return blobs


async def _copy_from_profile(client: AsyncClient, headers: dict, world: dict) -> dict:
    chosen = await client.post(
        _base(world["stage_id"]) + "/select-document",
        headers=headers,
        json={
            "expected_revision": await _revision(client, headers, world["stage_id"]),
            "document_id": world["document_id"],
        },
    )
    assert chosen.status_code == 200, chosen.text
    return chosen.json()


async def _receipt(
    client: AsyncClient,
    headers: dict,
    world: dict,
    image: bytes,
    *,
    stage_id: int | None = None,
) -> str:
    response = await client.post(
        "/api/cv-generator/consent-screenshot",
        headers=headers,
        data={
            "candidate_id": str(world["candidate_id"]),
            "stage_id": str(stage_id or world["stage_id"]),
        },
        files={"file": ("zgoda.png", image, "image/png")},
    )
    assert response.status_code == 200, response.text
    return response.json()["consent_token"]


async def _attach(client: AsyncClient, headers: dict, world: dict, token: str):
    return await client.post(
        _base(world["stage_id"]) + "/consent",
        headers=headers,
        json={"consent_screenshot_token": token},
    )


async def _preview(client: AsyncClient, headers: dict, world: dict):
    current = (await client.get(_base(world["stage_id"]), headers=headers)).json()
    return await client.post(
        _base(world["stage_id"]) + "/preview-docx",
        headers=headers,
        json={
            "content_html": current["content_html"],
            "expected_revision": current["edit_revision"],
        },
    )


@pytest.mark.asyncio
async def test_consent_attached_to_a_copy_unblocks_download_and_can_be_replaced(
    app_client: AsyncClient, app_auth_headers: dict, monkeypatch, storage
):
    consent_client(monkeypatch)
    world = await _seed()
    await _copy_from_profile(app_client, app_auth_headers, world)
    assert (await _preview(app_client, app_auth_headers, world)).status_code == 409

    first = _png("white")
    attached = await _attach(
        app_client,
        app_auth_headers,
        world,
        await _receipt(app_client, app_auth_headers, world, first),
    )

    assert attached.status_code == 200, attached.text
    body = attached.json()
    assert (body["status"], body["consent_attached"], body["consent_missing"]) == (
        "draft",
        True,
        False,
    )
    assert (await _preview(app_client, app_auth_headers, world)).status_code == 200
    csv = await _csv(world["stage_id"])
    assert bytes(csv.branded_consent_content) == first
    assert (
        csv.branded_render_metadata["consent_binding"]["subject"]["stage_id"]
        == (world["stage_id"])
    )

    second = _png("black")
    replaced = await _attach(
        app_client,
        app_auth_headers,
        world,
        await _receipt(app_client, app_auth_headers, world, second),
    )
    assert replaced.status_code == 200, replaced.text
    assert bytes((await _csv(world["stage_id"])).branded_consent_content) == second
    async with AsyncSessionLocal() as db:
        actions = (
            await db.scalars(
                select(Activity.action)
                .where(
                    Activity.entity_type == "candidate_stage_cv",
                    Activity.entity_id == csv.id,
                    Activity.action.in_(("cv_consent_attached", "cv_consent_replaced")),
                )
                .order_by(Activity.id)
            )
        ).all()
    assert actions == ["cv_consent_attached", "cv_consent_replaced"]


@pytest.mark.asyncio
async def test_receipt_for_another_stage_or_another_user_is_refused(
    app_client: AsyncClient, app_auth_headers: dict, monkeypatch, storage
):
    from app.core.security import create_access_token

    consent_client(monkeypatch)
    world = await _seed()
    await _copy_from_profile(app_client, app_auth_headers, world)
    async with AsyncSessionLocal() as db:
        elsewhere = CandidateStage(
            candidate_id=world["candidate_id"],
            job_id=world["other_job_id"],
            stage=PipelineStage.screening,
        )
        recruiter = User(
            email=f"cv-copy-consent-{uuid.uuid4().hex[:8]}@example.com",
            name="Inny rekruter",
            role=UserRole.recruiter,
            roles=[UserRole.recruiter.value],
            is_active=True,
        )
        db.add_all([elsewhere, recruiter])
        await db.commit()
        other_stage_id = elsewhere.id
        other_headers = {
            "Authorization": "Bearer "
            + create_access_token(recruiter.id, UserRole.recruiter.value)
        }

    from_other_stage = await _attach(
        app_client,
        app_auth_headers,
        world,
        await _receipt(
            app_client, app_auth_headers, world, _png(), stage_id=other_stage_id
        ),
    )
    from_other_user = await _attach(
        app_client,
        app_auth_headers,
        world,
        await _receipt(app_client, other_headers, world, _png()),
    )
    forged = await _attach(app_client, app_auth_headers, world, "nie-pokwitowanie")

    for response in (from_other_stage, from_other_user, forged):
        assert response.status_code == 422, response.text
        assert "Zrzut zgody" in response.json()["detail"]
    assert (await _csv(world["stage_id"])).branded_consent_content is None


@pytest.mark.asyncio
async def test_copy_without_the_requirement_or_with_a_generator_document_refuses(
    app_client: AsyncClient, app_auth_headers: dict, storage
):
    world = await _seed()
    await _copy_from_profile(app_client, app_auth_headers, world)
    token = await _receipt(app_client, app_auth_headers, world, _png())

    not_required = await _attach(app_client, app_auth_headers, world, token)

    assert not_required.status_code == 409, not_required.text
    assert "nie wymaga" in not_required.json()["detail"]

    generated_id = await _generated(world["candidate_id"], world["job_id"])
    linked = await app_client.post(
        _base(world["stage_id"]) + "/select-generated",
        headers=app_auth_headers,
        json={
            "expected_revision": await _revision(
                app_client, app_auth_headers, world["stage_id"]
            ),
            "generated_document_id": generated_id,
        },
    )
    assert linked.status_code == 200, linked.text

    from_generator = await _attach(app_client, app_auth_headers, world, token)

    assert from_generator.status_code == 409, from_generator.text
    assert "generatora" in from_generator.json()["detail"]
    assert (await _csv(world["stage_id"])).branded_consent_content is None


async def _approve(client: AsyncClient, headers: dict, world: dict) -> dict:
    current = (await client.get(_base(world["stage_id"]), headers=headers)).json()
    approved = await client.post(
        _base(world["stage_id"]) + "/finalize",
        headers=headers,
        json={
            "expected_revision": current["edit_revision"],
            "content_html": current["content_html"],
        },
    )
    assert approved.status_code == 200, approved.text
    return approved.json()


async def _versions(stage_cv_id: int) -> list[CvDocumentVersion]:
    async with AsyncSessionLocal() as db:
        return list(
            (
                await db.scalars(
                    select(CvDocumentVersion)
                    .where(CvDocumentVersion.candidate_stage_cv_id == stage_cv_id)
                    .order_by(CvDocumentVersion.version)
                )
            ).all()
        )


@pytest.mark.asyncio
async def test_unchanged_finalized_copy_is_reapproved_with_the_image_without_ai(
    app_client: AsyncClient, app_auth_headers: dict, monkeypatch, storage
):
    consent_client(monkeypatch)
    review = AsyncMock(return_value={"status": "unverified", "method": "test"})
    monkeypatch.setattr(cv_approval_review, "review_for_approval", review)
    world = await _seed()
    await _copy_from_profile(app_client, app_auth_headers, world)
    await _approve(app_client, app_auth_headers, world)
    image = _png()

    attached = await _attach(
        app_client,
        app_auth_headers,
        world,
        await _receipt(app_client, app_auth_headers, world, image),
    )

    assert attached.status_code == 200, attached.text
    assert (attached.json()["status"], attached.json()["version"]) == ("finalized", 2)
    csv = await _csv(world["stage_id"])
    first, second = await _versions(csv.id)
    assert first.consent_content is None
    assert bytes(second.consent_content) == image
    assert second.content_sha256 == first.content_sha256
    assert second.render_metadata["content_review"]["consent_reapproval"] is True
    # Kontrola treści biegła raz — przy zatwierdzeniu przez człowieka.
    assert review.await_count == 1
    docx = await app_client.get(
        _base(world["stage_id"]) + "/versions/2/docx", headers=app_auth_headers
    )
    assert docx.status_code == 200, docx.text
    blocked = await app_client.get(
        _base(world["stage_id"]) + "/versions/1/docx", headers=app_auth_headers
    )
    assert blocked.status_code == 409, blocked.text


@pytest.mark.asyncio
async def test_changed_draft_of_a_copy_is_not_reapproved(
    app_client: AsyncClient, app_auth_headers: dict, monkeypatch, storage
):
    consent_client(monkeypatch)
    monkeypatch.setattr(
        cv_approval_review,
        "review_for_approval",
        AsyncMock(return_value={"status": "unverified", "method": "test"}),
    )
    world = await _seed()
    await _copy_from_profile(app_client, app_auth_headers, world)
    approved = await _approve(app_client, app_auth_headers, world)
    base = _base(world["stage_id"])
    reopened = await app_client.post(
        base + "/new-draft",
        headers=app_auth_headers,
        json={"expected_revision": approved["edit_revision"]},
    )
    assert reopened.status_code == 200, reopened.text
    edited = await app_client.patch(
        base,
        headers=app_auth_headers,
        json={
            "expected_revision": reopened.json()["edit_revision"],
            "content_html": reopened.json()["content_html"]
            + "<p>Dopisek po zatwierdzeniu.</p>",
        },
    )
    assert edited.status_code == 200, edited.text

    attached = await _attach(
        app_client,
        app_auth_headers,
        world,
        await _receipt(app_client, app_auth_headers, world, _png()),
    )

    assert attached.status_code == 200, attached.text
    assert (attached.json()["status"], attached.json()["consent_attached"]) == (
        "draft",
        True,
    )
    csv = await _csv(world["stage_id"])
    assert len(await _versions(csv.id)) == 1
