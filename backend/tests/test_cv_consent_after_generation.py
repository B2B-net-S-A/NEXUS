"""Generator v3: zrzut zgody RODO dołączany (i wymieniany) PO generacji CV.

Przepływ: ``POST /consent-screenshot`` z ``generated_id`` → pokwitowanie →
``POST /generated/{id}/consent``. Kontrakty:

- oba dokumenty pakietu (PL i EN) dostają obraz, nowy DOCX z obrazem, klucz
  w ``render_payload`` (przypisanie „generated" z klientem, etapem i numerem
  projektu z polityki) i ślad w ``artifact_provenance``;
- wymiana zrzutu działa i zostawia ``cv_consent_replaced``;
- 409, gdy którakolwiek wersja się jeszcze generuje; 422 dla pokwitowania
  innego CV; 409 dla CV, którego polityka zgody nie wymaga;
- zatwierdzona wersja z niezmienioną treścią jest zatwierdzana ponownie
  z nowym obrazem BEZ wywołania AI; zmieniona treść czeka na człowieka;
- po dołączeniu pobranie przestaje być blokowane.
"""

# ruff: noqa: F811  (fixture `pv_client` importowana z sąsiedniego pliku)
from __future__ import annotations

import hashlib
import uuid
from datetime import datetime, timezone
from io import BytesIO
from unittest.mock import AsyncMock
from zipfile import ZipFile

import pytest
from httpx import AsyncClient
from PIL import Image
from sqlalchemy import select

import app.models  # noqa: F401
from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.models.activity import Activity
from app.models.candidate_stage_cv import CandidateStageCV
from app.models.cv_document_version import CvDocumentVersion
from app.models.cv_generated_document import CvGeneratedDocument
from app.models.cv_generated_draft import CvGeneratedDraft
from app.models.cv_generation_job import CvGenerationJob
from app.services import object_storage, storage_service
from app.services.cv_document_assets import default_template
from app.services.cv_generator_b2b.standalone_service import (
    rerender_docx_from_payload,
)
from tests.test_cv_auto_generate import _headers, _world
from tests.test_pending_gate_removed import pv_client  # noqa: F401

PAYLOAD = {
    "name": "Synthetic Person",
    "position": "Tester",
    "why_points": [],
    "experience": [],
    "skills": [],
    "languages": [],
}
HTML = "<h1>Synthetic Person</h1><p>Tester</p>"


def _png(color: str) -> bytes:
    buffer = BytesIO()
    Image.new("RGB", (3, 3), color).save(buffer, format="PNG")
    return buffer.getvalue()


def _sha(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


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


async def _package(
    *,
    second_status: str = "ready",
    policy: dict | None = None,
    base: dict | None = None,
):
    world = dict(base) if base is not None else await _world()
    docx = rerender_docx_from_payload(PAYLOAD)
    policy = policy or {
        "requires_rodo_consent_block": True,
        "required_languages": ["pl", "en"],
        "project_ref": "ZOB 4521",
        "stage_id": world["stage_id"],
    }
    async with AsyncSessionLocal() as db:
        rows = []
        for language, status in (("pl", "ready"), ("en", second_status)):
            row = CvGeneratedDocument(
                candidate_id=world["candidate_id"],
                job_id=world["job_id"],
                client_id=world["client_id"],
                candidate_name="Synthetic Person",
                language=language,
                mode="new",
                content_mode="polished",
                filename=f"pko-{language}.docx",
                status=status,
                render_payload=dict(PAYLOAD) if status == "ready" else None,
                docx_content=docx if status == "ready" else None,
                docx_sha256=_sha(docx) if status == "ready" else None,
                central_policy=policy,
                created_by=world["user_id"],
                stage_id=world["stage_id"],
            )
            db.add(row)
            await db.flush()
            rows.append(row)
        db.add(
            CvGenerationJob(
                generated_id=rows[0].id,
                second_generated_id=rows[1].id,
                created_by=world["user_id"],
                kind="new",
                status="complete",
                input_storage_key=f"cv/test/input-{uuid.uuid4().hex}",
                input_sha256="0" * 64,
            )
        )
        await db.commit()
        world.update(primary_id=rows[0].id, second_id=rows[1].id, docx=docx)
    return world


async def _upload_consent(client: AsyncClient, world: dict, image: bytes, **form):
    response = await client.post(
        "/api/cv-generator/consent-screenshot",
        headers=_headers(world["user_id"]),
        data={"generated_id": str(world["primary_id"]), **form},
        files={"file": ("zgoda.png", image, "image/png")},
    )
    return response


async def _attach(client: AsyncClient, world: dict, token: str, generated_id=None):
    return await client.post(
        f"/api/cv-generator/generated/{generated_id or world['second_id']}/consent",
        headers=_headers(world["user_id"]),
        json={"consent_screenshot_token": token},
    )


def _media(docx: bytes) -> list[bytes]:
    with ZipFile(BytesIO(docx)) as archive:
        return [
            archive.read(name)
            for name in archive.namelist()
            if name.startswith("word/media/")
        ]


async def _rows(world: dict) -> list[CvGeneratedDocument]:
    async with AsyncSessionLocal() as db:
        return [
            await db.get(CvGeneratedDocument, world["primary_id"]),
            await db.get(CvGeneratedDocument, world["second_id"]),
        ]


async def _actions(world: dict) -> list[str]:
    async with AsyncSessionLocal() as db:
        return list(
            (
                await db.scalars(
                    select(Activity.action)
                    .where(
                        Activity.entity_type == "cv_generated_document",
                        Activity.entity_id.in_(
                            [world["primary_id"], world["second_id"]]
                        ),
                    )
                    .order_by(Activity.id)
                )
            ).all()
        )


@pytest.mark.asyncio
async def test_consent_is_attached_to_the_whole_package_and_unblocks_download(
    pv_client: AsyncClient, storage
):
    world = await _package()
    headers = _headers(world["user_id"])
    blocked = await pv_client.get(
        f"/api/cv-generator/generated/{world['primary_id']}/docx", headers=headers
    )
    assert blocked.status_code == 409
    assert blocked.json()["detail"]["code"] == "consent_required"

    image = _png("white")
    upload = await _upload_consent(pv_client, world, image)
    assert upload.status_code == 200, upload.text
    # Pokwitowanie z wiersza głównego działa także wywołane dla drugiej wersji.
    attached = await _attach(pv_client, world, upload.json()["consent_token"])
    assert attached.status_code == 200, attached.text
    body = attached.json()
    assert body["package_id"] == world["primary_id"]
    assert body["replaced"] is False
    assert sorted(body["document_ids"]) == sorted(
        [world["primary_id"], world["second_id"]]
    )

    for row in await _rows(world):
        assert row.consent_content == image
        assert image in _media(row.docx_content)
        assert row.docx_sha256 == _sha(row.docx_content) != _sha(world["docx"])
        consent = row.render_payload["consent_screenshot"]
        assert "_bytes" not in consent
        subject = consent["binding"]["subject"]
        assert subject["mode"] == "generated"
        assert subject["client_id"] == world["client_id"]
        assert subject["recruitment_stage_id"] == world["stage_id"]
        assert subject["project_ref"] == "4521"
        provenance = row.render_payload["artifact_provenance"]
        assert provenance["consent_sha256"] == _sha(image)
        assert provenance["consent_attached_after_generation"]["replaced"] is False
    assert await _actions(world) == ["cv_consent_attached", "cv_consent_attached"]

    download = await pv_client.get(
        f"/api/cv-generator/generated/{world['primary_id']}/docx", headers=headers
    )
    assert download.status_code == 200, download.text
    assert image in _media(download.content)


@pytest.mark.asyncio
async def test_consent_can_be_replaced(pv_client: AsyncClient, storage):
    world = await _package()
    first = await _upload_consent(pv_client, world, _png("white"))
    assert (
        await _attach(pv_client, world, first.json()["consent_token"])
    ).status_code == 200
    new_image = _png("black")
    second = await _upload_consent(pv_client, world, new_image)
    replaced = await _attach(pv_client, world, second.json()["consent_token"])
    assert replaced.status_code == 200, replaced.text
    assert replaced.json()["replaced"] is True
    for row in await _rows(world):
        assert row.consent_content == new_image
        assert new_image in _media(row.docx_content)
    assert (await _actions(world))[-2:] == [
        "cv_consent_replaced",
        "cv_consent_replaced",
    ]


@pytest.mark.asyncio
async def test_package_still_generating_is_refused(pv_client: AsyncClient, storage):
    world = await _package(second_status="processing")
    upload = await _upload_consent(pv_client, world, _png("white"))
    assert upload.status_code == 200, upload.text
    response = await _attach(pv_client, world, upload.json()["consent_token"])
    assert response.status_code == 409, response.text
    assert "trwa" in response.json()["detail"]
    [primary, _second] = await _rows(world)
    assert primary.consent_content is None


@pytest.mark.asyncio
async def test_receipt_of_another_cv_is_refused(pv_client: AsyncClient, storage):
    world = await _package()
    # Ten sam autor, inne CV: pokwitowanie jest przypięte do CV (pakietu).
    other = await _package(base=world)
    upload = await _upload_consent(pv_client, other, _png("white"))
    assert upload.status_code == 200, upload.text
    response = await _attach(
        pv_client, world, upload.json()["consent_token"], world["primary_id"]
    )
    assert response.status_code == 422, response.text
    [primary, _second] = await _rows(world)
    assert primary.consent_content is None


@pytest.mark.asyncio
async def test_cv_without_the_requirement_does_not_take_a_consent(
    pv_client: AsyncClient, storage
):
    world = await _package(policy={"required_languages": ["pl"]})
    upload = await _upload_consent(pv_client, world, _png("white"))
    assert upload.status_code == 409, upload.text


@pytest.mark.asyncio
async def test_generated_binding_excludes_other_source_fields(
    pv_client: AsyncClient, storage
):
    world = await _package()
    response = await _upload_consent(
        pv_client, world, _png("white"), candidate_id=str(world["candidate_id"])
    )
    assert response.status_code == 422, response.text


# ── ponowne zatwierdzenie bez AI ────────────────────────────────────────────


async def _approve(world: dict, *, draft_html: str = HTML) -> dict:
    """Zatwierdzona wersja (i szkic edytora) + zatwierdzone CV etapu."""
    template = default_template()
    async with AsyncSessionLocal() as db:
        primary = await db.get(CvGeneratedDocument, world["primary_id"])
        metadata = {
            "template_sha256": _sha(template),
            "consent_sha256": None,
            "content_review": {"status": "verified", "method": "unchanged_generation"},
        }
        version = CvDocumentVersion(
            generated_owner_id=primary.id,
            generated_document_id=primary.id,
            version=1,
            content_html=HTML,
            content_sha256=_sha(HTML.encode()),
            template_content=template,
            docx_content=primary.docx_content,
            docx_sha256=primary.docx_sha256,
            docx_filename=primary.filename,
            render_metadata=metadata,
            language="pl",
            template="standard",
            approved_at=datetime.now(timezone.utc),
            approved_by=world["user_id"],
        )
        db.add(version)
        db.add(
            CvGeneratedDraft(
                generated_document_id=primary.id,
                edit_revision=1,
                branded_version=1,
                branded_status="finalized",
                branded_draft_html=draft_html,
                branded_template_content=template,
                branded_render_metadata=metadata,
                branded_language="pl",
                branded_template="standard",
                branded_docx_filename=primary.filename,
            )
        )
        csv = CandidateStageCV(
            candidate_stage_id=world["stage_id"],
            candidate_id=world["candidate_id"],
            job_id=world["job_id"],
            branded_status="finalized",
            branded_draft_html=HTML,
            branded_template_content=template,
            branded_render_metadata=metadata,
            branded_language="pl",
            branded_template="standard",
            branded_from_generator=True,
            generated_document_id=primary.id,
            edit_revision=3,
            branded_version=1,
            branded_finalized_at=datetime.now(timezone.utc),
            branded_finalized_by=world["user_id"],
        )
        db.add(csv)
        await db.flush()
        db.add(
            CvDocumentVersion(
                candidate_stage_cv_id=csv.id,
                generated_document_id=primary.id,
                version=1,
                content_html=HTML,
                content_sha256=_sha(HTML.encode()),
                template_content=template,
                docx_content=b"stage-docx",
                docx_sha256=_sha(b"stage-docx"),
                docx_filename="stage.docx",
                render_metadata=metadata,
                language="pl",
                template="standard",
                approved_at=datetime.now(timezone.utc),
                approved_by=world["user_id"],
            )
        )
        await db.commit()
        return {"csv_id": csv.id, "version_id": version.id}


@pytest.mark.asyncio
async def test_unchanged_approved_versions_are_reapproved_without_ai(
    pv_client: AsyncClient, storage, monkeypatch
):
    from app.services import cv_approval_review

    review = AsyncMock(side_effect=AssertionError("no AI review on consent"))
    monkeypatch.setattr(cv_approval_review, "review_for_approval", review)
    world = await _package()
    approved = await _approve(world)
    image = _png("white")
    upload = await _upload_consent(pv_client, world, image)
    response = await _attach(
        pv_client, world, upload.json()["consent_token"], world["primary_id"]
    )
    assert response.status_code == 200, response.text
    reapproved = response.json()["reapproved_version_ids"]
    assert len(reapproved) == 2
    review.assert_not_awaited()

    async with AsyncSessionLocal() as db:
        owned = (
            await db.scalars(
                select(CvDocumentVersion)
                .where(CvDocumentVersion.generated_owner_id == world["primary_id"])
                .order_by(CvDocumentVersion.version)
            )
        ).all()
        assert [v.version for v in owned] == [1, 2]
        new = owned[-1]
        assert new.consent_content == image
        assert new.content_sha256 == owned[0].content_sha256
        assert new.render_metadata["consent_sha256"] == _sha(image)
        assert new.render_metadata["content_review"]["consent_reapproval"] is True
        # Wersja bez edycji niosła DOCX generatora — następca też (z obrazem).
        primary = await db.get(CvGeneratedDocument, world["primary_id"])
        assert new.docx_sha256 == primary.docx_sha256
        draft = await db.scalar(
            select(CvGeneratedDraft).where(
                CvGeneratedDraft.generated_document_id == world["primary_id"]
            )
        )
        assert (draft.branded_status, draft.branded_version) == ("finalized", 2)
        assert draft.branded_consent_content == image

        csv = await db.get(CandidateStageCV, approved["csv_id"])
        assert (csv.branded_status, csv.branded_version) == ("finalized", 2)
        assert csv.branded_consent_content == image
        stage_version = await db.scalar(
            select(CvDocumentVersion).where(
                CvDocumentVersion.candidate_stage_cv_id == csv.id,
                CvDocumentVersion.version == 2,
            )
        )
        assert stage_version.consent_content == image
        assert image in _media(stage_version.docx_content)
        assert stage_version.render_metadata["content_review"]["consent_reapproval"]


@pytest.mark.asyncio
async def test_changed_draft_is_not_reapproved(
    pv_client: AsyncClient, storage, monkeypatch
):
    world = await _package()
    await _approve(world, draft_html="<h1>Zmieniona treść</h1>")
    upload = await _upload_consent(pv_client, world, _png("white"))
    response = await _attach(
        pv_client, world, upload.json()["consent_token"], world["primary_id"]
    )
    assert response.status_code == 200, response.text
    async with AsyncSessionLocal() as db:
        versions = (
            await db.scalars(
                select(CvDocumentVersion.version).where(
                    CvDocumentVersion.generated_owner_id == world["primary_id"]
                )
            )
        ).all()
        assert versions == [1]
        draft = await db.scalar(
            select(CvGeneratedDraft).where(
                CvGeneratedDraft.generated_document_id == world["primary_id"]
            )
        )
        # Szkic dostał obraz — zatwierdzenie zmienionej treści należy do człowieka.
        assert draft.branded_consent_content is not None


# ── kto może dołączyć zgodę ─────────────────────────────────────────────────


async def _user(role) -> int:
    from app.models.user import User

    async with AsyncSessionLocal() as db:
        user = User(
            email=f"cv-consent-{uuid.uuid4().hex[:8]}@example.com",
            name=f"Spoza zespołu {role.value}",
            role=role,
            roles=[role.value],
            is_active=True,
        )
        db.add(user)
        await db.commit()
        return user.id


def _role_headers(user_id: int, role) -> dict[str, str]:
    from app.core.security import create_access_token

    return {"Authorization": f"Bearer {create_access_token(user_id, role.value)}"}


async def _version_count(world: dict) -> int:
    from sqlalchemy import func

    async with AsyncSessionLocal() as db:
        return await db.scalar(
            select(func.count(CvDocumentVersion.id)).where(
                CvDocumentVersion.generated_document_id.in_(
                    [world["primary_id"], world["second_id"]]
                )
            )
        )


@pytest.mark.asyncio
@pytest.mark.parametrize("role_name", ["finance", "recruiter"])
async def test_outsider_cannot_attach_consent(
    pv_client: AsyncClient, storage, monkeypatch, role_name
):
    """Dołączenie zgody ponownie ZATWIERDZA wersje — bramka jak przy
    zatwierdzaniu (autor, admin, zespół rekrutacji). Sam odczyt nie wystarcza."""
    from app.models.user import UserRole

    world = await _package()
    await _approve(world)
    before = await _version_count(world)
    upload = await _upload_consent(pv_client, world, _png("white"))
    assert upload.status_code == 200, upload.text
    role = UserRole(role_name)
    outsider = await _user(role)
    response = await pv_client.post(
        f"/api/cv-generator/generated/{world['primary_id']}/consent",
        headers=_role_headers(outsider, role),
        json={"consent_screenshot_token": upload.json()["consent_token"]},
    )
    assert response.status_code == 403, response.text
    assert await _version_count(world) == before
    [primary, _second] = await _rows(world)
    assert primary.consent_content is None

    # Autor tym samym pokwitowaniem — przechodzi.
    author = await _attach(
        pv_client, world, upload.json()["consent_token"], world["primary_id"]
    )
    assert author.status_code == 200, author.text
    assert await _version_count(world) > before


@pytest.mark.asyncio
async def test_cv_without_recruitment_takes_consent_only_from_its_author(
    pv_client: AsyncClient, storage
):
    from app.models.user import UserRole

    world = await _package()
    async with AsyncSessionLocal() as db:
        for key in ("primary_id", "second_id"):
            (await db.get(CvGeneratedDocument, world[key])).job_id = None
        await db.commit()
    upload = await _upload_consent(pv_client, world, _png("white"))
    assert upload.status_code == 200, upload.text
    outsider = await _user(UserRole.recruiter)
    response = await pv_client.post(
        f"/api/cv-generator/generated/{world['primary_id']}/consent",
        headers=_role_headers(outsider, UserRole.recruiter),
        json={"consent_screenshot_token": upload.json()["consent_token"]},
    )
    assert response.status_code == 403, response.text
    assert "autor" in response.json()["detail"]
