"""Generator v3: bez zrzutu zgody RODO (PKO BP) CV nie da się pobrać ani udostępnić.

Każda trasa wydająca plik CV klienta z wymogiem zgody zwraca 409
``{"code": "consent_required"}``, dopóki zgoda nie jest dołączona. Wersję
zatwierdzoną sprawdzamy po jej WŁASNYM obrazie. Wyłącznik awaryjny
``CV_CONSENT_DOWNLOAD_GATE_ENABLED=false`` zdejmuje blokadę.
"""

# ruff: noqa: F811  (fixture `pv_client` importowana z sąsiedniego pliku)
from __future__ import annotations

import hashlib
from datetime import datetime, timezone

import pytest
from httpx import AsyncClient

import app.models  # noqa: F401
from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.models.candidate_stage_cv import CandidateStageCV
from app.models.cv_document_version import CvDocumentVersion
from app.models.cv_generated_document import CvGeneratedDocument
from app.services import cv_consent_gate as gate
from app.services.cv_document_assets import default_template
from tests.test_cv_auto_generate import _headers, _world
from tests.test_cv_auto_generate_central_policies import _docx
from tests.test_pending_gate_removed import pv_client  # noqa: F401

PKO_POLICY = {"requires_rodo_consent_block": True, "required_languages": ["pl"]}
HTML = "<h1>CV</h1><p>Python</p>"


def _sha(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


async def _pko_world(*, with_consent: bool = False) -> dict:
    world = await _world()
    template = default_template()
    docx = _docx()
    consent = b"\x89PNG\r\n\x1a\nfake" if with_consent else None
    payload = {"name": "PKO Kandydat", "language": "pl"}
    if with_consent:
        payload["consent_screenshot"] = {"storage_key": "cv/test/zgoda.png"}
    async with AsyncSessionLocal() as db:
        row = CvGeneratedDocument(
            candidate_id=world["candidate_id"],
            job_id=world["job_id"],
            client_id=world["client_id"],
            candidate_name="PKO Kandydat",
            language="pl",
            mode="new",
            content_mode="polished",
            filename="pko.docx",
            status="ready",
            render_payload=payload,
            docx_content=docx,
            docx_sha256=_sha(docx),
            consent_content=consent,
            central_policy=PKO_POLICY,
            created_by=world["user_id"],
        )
        db.add(row)
        await db.flush()
        metadata = {
            "template_sha256": _sha(template),
            "consent_sha256": _sha(consent) if consent else None,
        }
        version = CvDocumentVersion(
            generated_owner_id=row.id,
            generated_document_id=row.id,
            version=1,
            content_html=HTML,
            content_sha256=_sha(HTML.encode()),
            template_content=template,
            consent_content=consent,
            docx_content=docx,
            docx_sha256=_sha(docx),
            docx_filename="pko.docx",
            render_metadata=metadata,
            language="pl",
            template="standard",
            approved_at=datetime.now(timezone.utc),
            approved_by=world["user_id"],
        )
        csv = CandidateStageCV(
            candidate_stage_id=world["stage_id"],
            candidate_id=world["candidate_id"],
            job_id=world["job_id"],
            branded_status="draft",
            branded_draft_html=HTML,
            branded_template_content=template,
            branded_consent_content=consent,
            branded_language="pl",
            branded_template="standard",
            branded_from_generator=True,
            generated_document_id=row.id,
            edit_revision=0,
            branded_version=2,
        )
        db.add_all([version, csv])
        await db.flush()
        db.add(
            CvDocumentVersion(
                candidate_stage_cv_id=csv.id,
                generated_document_id=row.id,
                version=1,
                content_html=HTML,
                content_sha256=_sha(HTML.encode()),
                template_content=template,
                consent_content=consent,
                docx_content=docx,
                docx_sha256=_sha(docx),
                docx_filename="pko.docx",
                render_metadata=metadata,
                language="pl",
                template="standard",
                approved_at=datetime.now(timezone.utc),
                approved_by=world["user_id"],
            )
        )
        await db.commit()
        world.update(generated_id=row.id, version_id=version.id)
    return world


def _routes(world: dict) -> list[tuple[str, str, dict]]:
    g, v, s = world["generated_id"], world["version_id"], world["stage_id"]
    editor = {"expected_revision": 0, "content_html": HTML}
    return [
        ("GET", f"/api/cv-generator/generated/{g}/docx", {}),
        ("GET", f"/api/cv-generator/generated/{g}/html", {}),
        ("GET", f"/api/cv-generator/generated/{g}/approved/{v}/docx", {}),
        ("GET", f"/api/cv-generator/generated/{g}/editor/versions/1/docx", {}),
        ("POST", f"/api/cv-generator/generated/{g}/editor/preview-docx", editor),
        ("GET", f"/api/cv-generator/generated/{g}/editor/render-pdf", {}),
        (
            "POST",
            f"/api/cv-generator/generated/{g}/share-token?document_version_id={v}",
            {},
        ),
        ("GET", f"/api/candidates/stages/{s}/cv/branded/versions/1/docx", {}),
        ("POST", f"/api/candidates/stages/{s}/cv/branded/preview-docx", editor),
        ("GET", f"/api/candidates/stages/{s}/cv/branded/render-pdf", {}),
    ]


ROUTE_NAMES = [
    "generated-docx",
    "generated-html",
    "package-approved",
    "editor-version-docx",
    "editor-preview-docx",
    "editor-print",
    "share-link",
    "stage-version-docx",
    "stage-preview-docx",
    "stage-print",
]


async def _call(client: AsyncClient, world: dict, index: int):
    method, url, body = _routes(world)[index]
    headers = _headers(world["user_id"])
    if method == "GET":
        return await client.get(url, headers=headers)
    return await client.post(url, headers=headers, json=body)


def _is_consent_refusal(response) -> bool:
    if response.status_code != 409:
        return False
    detail = response.json().get("detail")
    return isinstance(detail, dict) and detail.get("code") == "consent_required"


@pytest.mark.asyncio
@pytest.mark.parametrize("index", range(len(ROUTE_NAMES)), ids=ROUTE_NAMES)
async def test_download_without_consent_is_refused(
    pv_client: AsyncClient, monkeypatch, index
):
    monkeypatch.setattr(settings, "CV_CONSENT_DOWNLOAD_GATE_ENABLED", True)
    world = await _pko_world()
    response = await _call(pv_client, world, index)
    assert _is_consent_refusal(response), (response.status_code, response.text)
    assert "zgod" in response.json()["detail"]["message"]


@pytest.mark.asyncio
@pytest.mark.parametrize("index", range(len(ROUTE_NAMES)), ids=ROUTE_NAMES)
async def test_kill_switch_lifts_the_gate(pv_client: AsyncClient, monkeypatch, index):
    monkeypatch.setattr(settings, "CV_CONSENT_DOWNLOAD_GATE_ENABLED", False)
    world = await _pko_world()
    response = await _call(pv_client, world, index)
    assert not _is_consent_refusal(response), response.text


@pytest.mark.asyncio
@pytest.mark.parametrize("index", range(len(ROUTE_NAMES)), ids=ROUTE_NAMES)
async def test_attached_consent_opens_every_route(
    pv_client: AsyncClient, monkeypatch, index
):
    monkeypatch.setattr(settings, "CV_CONSENT_DOWNLOAD_GATE_ENABLED", True)
    world = await _pko_world(with_consent=True)
    response = await _call(pv_client, world, index)
    assert not _is_consent_refusal(response), response.text


# ── reguła w izolacji ───────────────────────────────────────────────────────


class _Row:
    def __init__(self, policy=None, payload=None):
        self.central_policy = policy
        self.render_payload = payload or {}


class _Version:
    def __init__(self, consent):
        self.consent_content = consent


def test_rows_without_the_requirement_are_never_blocked(monkeypatch):
    monkeypatch.setattr(settings, "CV_CONSENT_DOWNLOAD_GATE_ENABLED", True)
    gate.ensure_downloadable(None)
    gate.ensure_downloadable(_Row())
    gate.ensure_downloadable(_Row({"requires_rodo_consent_block": False}))
    gate.ensure_downloadable(_Row(), _Version(None))


def test_version_is_judged_by_its_own_image(monkeypatch):
    from fastapi import HTTPException

    monkeypatch.setattr(settings, "CV_CONSENT_DOWNLOAD_GATE_ENABLED", True)
    row = _Row(PKO_POLICY, {"consent_screenshot": {"storage_key": "cv/x.png"}})
    gate.ensure_downloadable(row)
    gate.ensure_downloadable(row, _Version(b"img"))
    # Wersja zatwierdzona PRZED dołączeniem zgody nie niesie obrazu.
    with pytest.raises(HTTPException) as caught:
        gate.ensure_downloadable(row, _Version(None))
    assert caught.value.status_code == 409
    assert caught.value.detail["code"] == "consent_required"
