"""Testy brandowanego CV per rekrutacja + public share token (PR2 — Faza 3+4).

Pokrycie:

  GET /cv/branded:
    * lazy render przy pierwszym GET — content_html niepusty, status='draft',
      template='standard', language='pl', rendered_from_default=True
    * drugi GET → status='draft', rendered_from_default=False (no re-render)

  PATCH /cv/branded:
    * save content_html → zachowuje treść
    * swap template → re-render, nadpisuje content_html
    * podać oba → 422 (model_validator)
    * podać żaden → 422
    * po finalize → 409 immutable

  GET /cv/branded/render-pdf:
    * zwraca printable HTML (z window.print() script)
    * 404 gdy draft pusty

  POST /cv/branded/finalize:
    * draft → finalized, snapshot do storage
    * 409 gdy status≠'draft'
    * 422 gdy treść pusta
    * po finalize ponowny finalize → 409

  Isolation (the-feature):
    * 2 stages dla 1 kandydata: edycja A nie wpływa na B (każdy ma swój)

  Public share (Faza 4):
    * POST /share-token wymaga finalized (409 dla draft)
    * GET /api/public/cv/{token} 200 z PII-safe response
    * test_public_cv_no_pii_leakage — assertion że w body NIE ma email/phone/lastname
    * GET 404 gdy revoked
    * GET 410 gdy expired
    * DELETE /share-token/{token} → revoked=true, drugi DELETE → already_revoked
"""

from __future__ import annotations

import hashlib
import asyncio
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from httpx import AsyncClient
from sqlalchemy import select, update

from app.core.database import AsyncSessionLocal
from app.models.candidate import Candidate
from app.models.candidate_stage_cv import CandidateStageCV
from app.models.client import Client
from app.models.cv_share_token import CVShareToken
from app.models.cv_document_version import CvDocumentVersion
from app.models.job import Job
from app.models.recruitment_pipeline import CandidateStage, PipelineStage
from app.services.candidate_stage_cv_service import (
    create_original_cv_snapshot,
)


async def _draft_request_body(url, body=None):
    sid = int(url.split("/stages/")[1].split("/")[0])
    async with AsyncSessionLocal() as db:
        csv = await db.scalar(
            select(CandidateStageCV).where(CandidateStageCV.candidate_stage_id == sid)
        )
        values = {"expected_revision": csv.edit_revision}
        if url.endswith("/finalize"):
            values["content_html"] = csv.branded_draft_html or " "
        return {**values, **(body or {})}


async def _patch(client, url, **kwargs):
    kwargs["json"] = await _draft_request_body(url, kwargs.get("json"))
    return await client.patch(url, **kwargs)


async def _post(client, url, **kwargs):
    if url.endswith("/cv/branded/finalize"):
        kwargs["json"] = await _draft_request_body(url, kwargs.get("json"))
    return await client.post(url, **kwargs)


async def _expire_share_token(token: str) -> None:
    """Backdate the row behind a raw share token so it reads as expired.

    Matched the way production reads it (`get_public_cv`): since migration 0176
    the secret is no longer stored — `token_sha256` holds its SHA-256 and the
    `token` PK holds a non-secret ``v2$…`` revoke key. Matching the raw secret
    against `token` updates zero rows, and an UPDATE that touches nothing fails
    silently: the link stays valid and the 410 assertion below quietly becomes
    an assertion about a live link. The rowcount guard makes that failure mode
    loud instead.
    """
    digest = hashlib.sha256(token.encode()).hexdigest()
    async with AsyncSessionLocal() as db:
        res = await db.execute(
            update(CVShareToken)
            .where(
                (CVShareToken.token_sha256 == digest)
                | (
                    (CVShareToken.token == token)
                    & (CVShareToken.token_sha256.is_(None))
                )
            )
            .values(expires_at=datetime.now(timezone.utc) - timedelta(days=1))
        )
        await db.commit()
    assert res.rowcount == 1, (
        f"expiry precondition matched {res.rowcount} rows — the test would have "
        "asserted against a link that was never expired"
    )


async def _seed_full_stage(
    *, with_cv: bool = True, candidate_email: str | None = None
) -> tuple[int, int, int]:
    """Seed candidate (z CV) + client + job + stage + snapshot.

    Zwraca (stage_id, candidate_id, job_id).
    """
    unique = uuid.uuid4().hex[:6]
    async with AsyncSessionLocal() as db:
        cli = Client(name=f"Klient PR2 {unique}")
        db.add(cli)
        await db.flush()

        cand = Candidate(
            name="Brand",
            lastname=f"PR2{unique}",
            email=candidate_email or f"brand-{unique}@example.com",
            phone="+48 500 000 001",
            cv_filename="my_cv.pdf" if with_cv else None,
            cv_file_content=b"%PDF-1.4 fake" if with_cv else None,
            cv_language="pl" if with_cv else None,
            ai_summary="Senior Python developer.",
            skills=[
                {"name": "Python", "level": "Senior", "years": 8},
                {"name": "FastAPI", "level": "Senior", "years": 4},
            ],
            experience=[
                {
                    "company": "Acme Corp",
                    "role": "Tech Lead",
                    "start": "2020-01",
                    "end": "2024-12",
                    "desc": "Led 5-person team building distributed services.",
                }
            ],
        )
        db.add(cand)
        await db.flush()

        job = Job(
            title=f"Senior Python Engineer {unique}",
            client_id=cli.id,
            description="x",
        )
        db.add(job)
        await db.flush()

        stage = CandidateStage(
            candidate_id=cand.id, job_id=job.id, stage=PipelineStage.new
        )
        db.add(stage)
        await db.flush()
        await create_original_cv_snapshot(db, stage)
        await db.commit()
        return stage.id, cand.id, job.id


# ── Lazy render ─────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_get_branded_lazy_renders_on_first_call(
    app_client: AsyncClient, app_auth_headers: dict
):
    sid, cid, jid = await _seed_full_stage()
    res = await app_client.get(
        f"/api/candidates/stages/{sid}/cv/branded", headers=app_auth_headers
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["status"] == "draft"
    assert body["template"] == "standard"
    assert body["language"] == "pl"
    assert body["rendered_from_default"] is True
    assert body["content_html"] is not None
    # Treść powinna zawierać imię kandydata (z _generate_cv_html)
    assert "Brand" in body["content_html"]


@pytest.mark.asyncio
async def test_get_branded_returns_existing_after_first(
    app_client: AsyncClient, app_auth_headers: dict
):
    sid, _, _ = await _seed_full_stage()
    first = await app_client.get(
        f"/api/candidates/stages/{sid}/cv/branded", headers=app_auth_headers
    )
    second = await app_client.get(
        f"/api/candidates/stages/{sid}/cv/branded", headers=app_auth_headers
    )
    assert second.status_code == 200
    assert second.json()["rendered_from_default"] is False
    # Treść powinna być identyczna z pierwszym wywołaniem.
    assert second.json()["content_html"] == first.json()["content_html"]


# ── PATCH save / swap ──────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_patch_branded_saves_content(
    app_client: AsyncClient, app_auth_headers: dict
):
    sid, _, _ = await _seed_full_stage()
    await app_client.get(
        f"/api/candidates/stages/{sid}/cv/branded", headers=app_auth_headers
    )
    custom = "<h1>Custom edit</h1><p>Modified by recruiter</p>"
    res = await _patch(
        app_client,
        f"/api/candidates/stages/{sid}/cv/branded",
        headers=app_auth_headers,
        json={"content_html": custom},
    )
    assert res.status_code == 200, res.text
    assert res.json()["content_html"] == custom


@pytest.mark.asyncio
async def test_patch_branded_swaps_template_rerenders(
    app_client: AsyncClient, app_auth_headers: dict
):
    sid, _, _ = await _seed_full_stage()
    first = await app_client.get(
        f"/api/candidates/stages/{sid}/cv/branded", headers=app_auth_headers
    )
    res = await _patch(
        app_client,
        f"/api/candidates/stages/{sid}/cv/branded",
        headers=app_auth_headers,
        json={"template": "blind", "language": "en"},
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["template"] == "blind"
    assert body["language"] == "en"
    assert body["content_html"] != first.json()["content_html"]


@pytest.mark.asyncio
async def test_patch_branded_rejects_both_branches(
    app_client: AsyncClient, app_auth_headers: dict
):
    sid, _, _ = await _seed_full_stage()
    res = await _patch(
        app_client,
        f"/api/candidates/stages/{sid}/cv/branded",
        headers=app_auth_headers,
        json={"content_html": "<p>x</p>", "template": "blind"},
    )
    assert res.status_code == 422


@pytest.mark.asyncio
async def test_patch_branded_rejects_empty_payload(
    app_client: AsyncClient, app_auth_headers: dict
):
    sid, _, _ = await _seed_full_stage()
    res = await _patch(
        app_client,
        f"/api/candidates/stages/{sid}/cv/branded",
        headers=app_auth_headers,
        json={},
    )
    assert res.status_code == 422


# ── render-pdf ──────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_render_pdf_returns_printable_html(
    app_client: AsyncClient, app_auth_headers: dict
):
    sid, _, _ = await _seed_full_stage()
    await app_client.get(
        f"/api/candidates/stages/{sid}/cv/branded", headers=app_auth_headers
    )
    res = await app_client.get(
        f"/api/candidates/stages/{sid}/cv/branded/render-pdf",
        headers=app_auth_headers,
    )
    assert res.status_code == 200
    assert "window.print()" in res.text
    assert res.headers["content-type"].startswith("text/html")


# ── Finalize ────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_finalize_creates_snapshot_and_flips_status(
    app_client: AsyncClient, app_auth_headers: dict
):
    sid, _, _ = await _seed_full_stage()
    await app_client.get(
        f"/api/candidates/stages/{sid}/cv/branded", headers=app_auth_headers
    )
    res = await _post(
        app_client,
        f"/api/candidates/stages/{sid}/cv/branded/finalize",
        headers=app_auth_headers,
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["status"] == "finalized"
    assert body["snapshot_filename"].endswith(".html")
    assert body["snapshot_size_bytes"] > 0


@pytest.mark.asyncio
async def test_finalize_409_when_not_draft(
    app_client: AsyncClient, app_auth_headers: dict
):
    sid, _, _ = await _seed_full_stage()
    # Bez GET najpierw — status='none' → 409
    res = await _post(
        app_client,
        f"/api/candidates/stages/{sid}/cv/branded/finalize",
        headers=app_auth_headers,
    )
    assert res.status_code == 409


@pytest.mark.asyncio
async def test_finalize_immutable_after_finalize(
    app_client: AsyncClient, app_auth_headers: dict
):
    sid, _, _ = await _seed_full_stage()
    await app_client.get(
        f"/api/candidates/stages/{sid}/cv/branded", headers=app_auth_headers
    )
    first = await _post(
        app_client,
        f"/api/candidates/stages/{sid}/cv/branded/finalize",
        headers=app_auth_headers,
    )
    assert first.status_code == 200
    second = await _post(
        app_client,
        f"/api/candidates/stages/{sid}/cv/branded/finalize",
        headers=app_auth_headers,
    )
    assert second.status_code == 409


@pytest.mark.asyncio
async def test_patch_branded_409_when_finalized(
    app_client: AsyncClient, app_auth_headers: dict
):
    sid, _, _ = await _seed_full_stage()
    await app_client.get(
        f"/api/candidates/stages/{sid}/cv/branded", headers=app_auth_headers
    )
    await _post(
        app_client,
        f"/api/candidates/stages/{sid}/cv/branded/finalize",
        headers=app_auth_headers,
    )
    res = await _patch(
        app_client,
        f"/api/candidates/stages/{sid}/cv/branded",
        headers=app_auth_headers,
        json={"content_html": "<p>after-finalize edit</p>"},
    )
    assert res.status_code == 409


# ── Isolation: 2 stages dla 1 kandydata ────────────────────────────────────


@pytest.mark.asyncio
async def test_branded_cv_isolated_between_stages(
    app_client: AsyncClient, app_auth_headers: dict
):
    """Edycja brandowanego dla stage A nie wpływa na stage B (problem Traffit)."""
    sid_a, cid, _ = await _seed_full_stage()
    # Drugi stage dla tego samego kandydata na innej ofercie
    async with AsyncSessionLocal() as db:
        unique = uuid.uuid4().hex[:6]
        cli = await db.scalar(select(Client).limit(1))
        if cli is None:
            cli = Client(name=f"Klient ISO {unique}")
            db.add(cli)
            await db.flush()
        job_b = Job(title=f"Other role {unique}", client_id=cli.id, description="x")
        db.add(job_b)
        await db.flush()
        stage_b = CandidateStage(
            candidate_id=cid, job_id=job_b.id, stage=PipelineStage.new
        )
        db.add(stage_b)
        await db.flush()
        await create_original_cv_snapshot(db, stage_b)
        await db.commit()
        sid_b = stage_b.id

    # Edytuj brandowane stage A
    await app_client.get(
        f"/api/candidates/stages/{sid_a}/cv/branded", headers=app_auth_headers
    )
    await _patch(
        app_client,
        f"/api/candidates/stages/{sid_a}/cv/branded",
        headers=app_auth_headers,
        json={"content_html": "<p>STAGE-A custom</p>"},
    )
    # Stage B nadal status='none', content_html=None
    res_b = await app_client.get(
        f"/api/candidates/stages/{sid_b}/cv/branded",
        headers=app_auth_headers,
    )
    body_b = res_b.json()
    assert body_b["status"] == "draft"  # świeżo lazy-rendered po GET
    assert "STAGE-A custom" not in (body_b["content_html"] or "")


# ── Public share token ─────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_share_token_409_when_not_finalized(
    app_client: AsyncClient, app_auth_headers: dict
):
    sid, _, _ = await _seed_full_stage()
    await app_client.get(
        f"/api/candidates/stages/{sid}/cv/branded", headers=app_auth_headers
    )  # status='draft', NOT finalized
    res = await _post(
        app_client,
        f"/api/candidates/stages/{sid}/cv/share-token",
        headers=app_auth_headers,
    )
    assert res.status_code == 409


@pytest.mark.asyncio
async def test_share_token_returns_url_suffix(
    app_client: AsyncClient, app_auth_headers: dict
):
    sid, _, _ = await _seed_full_stage()
    await app_client.get(
        f"/api/candidates/stages/{sid}/cv/branded", headers=app_auth_headers
    )
    await _post(
        app_client,
        f"/api/candidates/stages/{sid}/cv/branded/finalize",
        headers=app_auth_headers,
    )
    res = await _post(
        app_client,
        f"/api/candidates/stages/{sid}/cv/share-token",
        headers=app_auth_headers,
    )
    assert res.status_code == 201, res.text
    body = res.json()
    assert body["token"]
    assert body["share_url_suffix"].startswith("/cv/")
    assert body["share_url_suffix"].endswith(body["token"])


@pytest.mark.asyncio
async def test_public_cv_returns_html_no_pii_keys(
    app_client: AsyncClient, app_auth_headers: dict
):
    """Response klucze są PII-safe: tylko candidate_first_name + job_title + cv_html + expires_at.

    Uwaga: `cv_html` MOŻE zawierać email/phone, jeśli rekruter wybrał template
    `standard`. To jest świadome — recruiter ustawia template przy edycji.
    `blind` template anonimizuje (testowane w cv_generator.py). Tutaj sprawdzamy
    tylko że nie ma _osobnych pól_ z PII na top-level response.
    """
    sid, _, _ = await _seed_full_stage()
    # Switch na 'blind' żeby anonimizować przed finalize
    await app_client.get(
        f"/api/candidates/stages/{sid}/cv/branded", headers=app_auth_headers
    )
    await _patch(
        app_client,
        f"/api/candidates/stages/{sid}/cv/branded",
        headers=app_auth_headers,
        json={"template": "blind", "language": "pl"},
    )
    await _post(
        app_client,
        f"/api/candidates/stages/{sid}/cv/branded/finalize",
        headers=app_auth_headers,
    )
    tok = (
        await _post(
            app_client,
            f"/api/candidates/stages/{sid}/cv/share-token",
            headers=app_auth_headers,
        )
    ).json()["token"]

    pub = await app_client.get(f"/api/public/cv/{tok}")
    assert pub.status_code == 200, pub.text
    body = pub.json()

    # Top-level keys: PII-safe set
    assert set(body.keys()) == {
        "candidate_first_name",
        "job_title",
        "cv_html",
        "expires_at",
    }
    assert body["candidate_first_name"] == "Brand"
    assert body["job_title"]
    assert body["cv_html"]
    # Skoro wybraliśmy 'blind' template, CV body NIE powinno zawierać emaila
    # ani imienia/nazwiska kandydata.
    cv = body["cv_html"]
    assert "@example.com" not in cv  # _anonymize_text blind → [EMAIL]
    assert "PR2" not in cv  # lastname zanonimizowane do "Kandydat / Candidate"


@pytest.mark.asyncio
async def test_public_cv_404_when_revoked(
    app_client: AsyncClient, app_auth_headers: dict
):
    sid, _, _ = await _seed_full_stage()
    await app_client.get(
        f"/api/candidates/stages/{sid}/cv/branded", headers=app_auth_headers
    )
    await _post(
        app_client,
        f"/api/candidates/stages/{sid}/cv/branded/finalize",
        headers=app_auth_headers,
    )
    tok = (
        await _post(
            app_client,
            f"/api/candidates/stages/{sid}/cv/share-token",
            headers=app_auth_headers,
        )
    ).json()["token"]

    rev = await app_client.delete(
        f"/api/candidates/stages/cv/share-token/{tok}", headers=app_auth_headers
    )
    assert rev.status_code == 200
    pub = await app_client.get(f"/api/public/cv/{tok}")
    assert pub.status_code == 404


@pytest.mark.asyncio
async def test_public_cv_410_when_expired(
    app_client: AsyncClient, app_auth_headers: dict
):
    sid, _, _ = await _seed_full_stage()
    await app_client.get(
        f"/api/candidates/stages/{sid}/cv/branded", headers=app_auth_headers
    )
    await _post(
        app_client,
        f"/api/candidates/stages/{sid}/cv/branded/finalize",
        headers=app_auth_headers,
    )
    tok = (
        await _post(
            app_client,
            f"/api/candidates/stages/{sid}/cv/share-token",
            headers=app_auth_headers,
        )
    ).json()["token"]

    # Positive control: the same token, before backdating, must serve. Without it
    # a 410 could equally mean "expiry works" or "the link was broken all along",
    # and only expiry is under test here.
    live = await app_client.get(f"/api/public/cv/{tok}")
    assert live.status_code == 200, live.text

    await _expire_share_token(tok)

    pub = await app_client.get(f"/api/public/cv/{tok}")
    assert pub.status_code == 410


@pytest.mark.asyncio
async def test_revoke_share_token_idempotent(
    app_client: AsyncClient, app_auth_headers: dict
):
    sid, _, _ = await _seed_full_stage()
    await app_client.get(
        f"/api/candidates/stages/{sid}/cv/branded", headers=app_auth_headers
    )
    await _post(
        app_client,
        f"/api/candidates/stages/{sid}/cv/branded/finalize",
        headers=app_auth_headers,
    )
    tok = (
        await _post(
            app_client,
            f"/api/candidates/stages/{sid}/cv/share-token",
            headers=app_auth_headers,
        )
    ).json()["token"]

    first = await app_client.delete(
        f"/api/candidates/stages/cv/share-token/{tok}", headers=app_auth_headers
    )
    second = await app_client.delete(
        f"/api/candidates/stages/cv/share-token/{tok}", headers=app_auth_headers
    )
    assert first.json()["status"] == "revoked"
    assert second.json()["status"] == "already_revoked"


@pytest.mark.asyncio
async def test_legacy_public_cv_404_when_csv_no_longer_finalized(
    app_client: AsyncClient, app_auth_headers: dict
):
    """Legacy unbound links still fail closed when their live draft is reset."""
    sid, _, _ = await _seed_full_stage()
    await app_client.get(
        f"/api/candidates/stages/{sid}/cv/branded", headers=app_auth_headers
    )
    await _post(
        app_client,
        f"/api/candidates/stages/{sid}/cv/branded/finalize",
        headers=app_auth_headers,
    )
    tok = (
        await _post(
            app_client,
            f"/api/candidates/stages/{sid}/cv/share-token",
            headers=app_auth_headers,
        )
    ).json()["token"]

    # Model a pre-versioning token. Newly issued links are deliberately pinned
    # and remain on the approved version, covered by the version lifecycle test.
    async with AsyncSessionLocal() as db:
        unbound = await db.execute(
            update(CVShareToken)
            .where(
                CVShareToken.token_sha256 == hashlib.sha256(tok.encode()).hexdigest()
            )
            .values(document_version_id=None)
        )
        assert unbound.rowcount == 1
        await db.execute(
            update(CandidateStageCV)
            .where(CandidateStageCV.candidate_stage_id == sid)
            .values(branded_status="draft", branded_finalized_at=None)
        )
        await db.commit()

    pub = await app_client.get(f"/api/public/cv/{tok}")
    assert pub.status_code == 404


@pytest.mark.asyncio
@pytest.mark.parametrize("legacy", [False, True])
async def test_atomic_current_content_and_old_links_survive_new_version(
    app_client, app_auth_headers, legacy
):
    sid, _, _ = await _seed_full_stage()
    url = f"/api/candidates/stages/{sid}/cv/branded"
    initial = (await app_client.get(url, headers=app_auth_headers)).json()
    # No autosave request precedes approval: the body is newer than the DB.
    approved = await app_client.post(
        url + "/finalize",
        headers=app_auth_headers,
        json={
            "expected_revision": initial["edit_revision"],
            "content_html": "<p>Approved first version</p>",
        },
    )
    assert approved.status_code == 200, approved.text
    first = approved.json()
    shared = await app_client.post(
        f"/api/candidates/stages/{sid}/cv/share-token", headers=app_auth_headers
    )
    assert shared.status_code == 201, shared.text
    token = shared.json()["token"]
    if legacy:
        async with AsyncSessionLocal() as db:
            version = await db.get(CvDocumentVersion, first["document_version_id"])
            await db.execute(
                update(CVShareToken)
                .where(CVShareToken.document_version_id == version.id)
                .values(document_version_id=None)
            )
            await db.delete(version)
            await db.commit()
    draft = await app_client.post(
        url + "/new-draft",
        headers=app_auth_headers,
        json={"expected_revision": first["edit_revision"]},
    )
    assert draft.status_code == 200, draft.text
    assert draft.json()["version"] == 2
    old_view = await app_client.get(f"/api/public/cv/{token}")
    assert old_view.status_code == 200, old_view.text
    assert "Approved first version" in old_view.json()["cv_html"]
    second = await app_client.post(
        url + "/finalize",
        headers=app_auth_headers,
        json={
            "expected_revision": draft.json()["edit_revision"],
            "content_html": "<p>Approved second version</p>",
        },
    )
    assert second.status_code == 200, second.text
    assert (
        second.json()["document_version_id"] != first["document_version_id"] or legacy
    )
    after = await app_client.get(f"/api/public/cv/{token}")
    assert "Approved first version" in after.json()["cv_html"]
    assert "second version" not in after.json()["cv_html"]
    newer_share = await app_client.post(
        f"/api/candidates/stages/{sid}/cv/share-token", headers=app_auth_headers
    )
    newer = await app_client.get(f"/api/public/cv/{newer_share.json()['token']}")
    assert "Approved second version" in newer.json()["cv_html"]


@pytest.mark.asyncio
async def test_competing_cv_saves_have_exactly_one_winner(app_client, app_auth_headers):
    sid, _, _ = await _seed_full_stage()
    url = f"/api/candidates/stages/{sid}/cv/branded"
    original = (await app_client.get(url, headers=app_auth_headers)).json()
    responses = await asyncio.gather(
        *[
            app_client.patch(
                url,
                headers=app_auth_headers,
                json={
                    "expected_revision": original["edit_revision"],
                    "content_html": f"<p>{text}</p>",
                },
            )
            for text in ["first writer", "second writer"]
        ]
    )
    assert sorted(r.status_code for r in responses) == [200, 409]
    winner = next(r.json() for r in responses if r.status_code == 200)
    stored = (await app_client.get(url, headers=app_auth_headers)).json()
    assert stored["content_html"] == winner["content_html"]
    assert stored["edit_revision"] == original["edit_revision"] + 1


async def test_selected_generated_document_is_edited_approved_and_pinned_to_link(
    app_client, app_auth_headers
):
    from app.models.cv_generated_document import CvGeneratedDocument

    sid, cid, jid = await _seed_full_stage()
    base = f"/api/candidates/stages/{sid}/cv/branded"
    initial = (await app_client.get(base, headers=app_auth_headers)).json()
    async with AsyncSessionLocal() as db:
        source = CvGeneratedDocument(
            candidate_id=cid,
            job_id=jid,
            candidate_name="Synthetic",
            filename="selected.docx",
            status="ready",
            render_payload={
                "name": "Synthetic",
                "why_points": ["Chosen Python result"],
                "highlight_keywords": ["Python"],
            },
        )
        db.add(source)
        await db.commit()
        generated_id = source.id
    choice = await app_client.post(
        base + "/select-generated",
        headers=app_auth_headers,
        json={
            "expected_revision": initial["edit_revision"],
            "generated_document_id": generated_id,
        },
    )
    assert choice.status_code == 200, choice.text
    selected = choice.json()
    assert "Chosen <b>Python</b> result" in selected["content_html"]
    assert "Acme Corp" not in selected["content_html"]  # no profile regeneration
    edited = selected["content_html"].replace("Chosen", "Reviewed")
    approved = await app_client.post(
        base + "/finalize",
        headers=app_auth_headers,
        json={"expected_revision": selected["edit_revision"], "content_html": edited},
    )
    assert approved.status_code == 200, approved.text
    link = await app_client.post(
        f"/api/candidates/stages/{sid}/cv/share-token", headers=app_auth_headers
    )
    assert link.status_code == 200, link.text
    token = link.json()["token"]
    async with AsyncSessionLocal() as db:
        version = await db.get(
            CvDocumentVersion, approved.json()["document_version_id"]
        )
        assert version.generated_document_id == generated_id
        assert version.content_html == edited
    replacement = await app_client.post(
        base + "/select-generated",
        headers=app_auth_headers,
        json={
            "expected_revision": approved.json()["edit_revision"],
            "generated_document_id": generated_id,
        },
    )
    assert replacement.status_code == 200, replacement.text
    assert (
        replacement.json()["version"] == 2 and replacement.json()["status"] == "draft"
    )
    public = await app_client.get(f"/api/public/cv/{token}")
    assert public.status_code == 200, public.text
    assert "Reviewed <b>Python</b> result" in public.json()["cv_html"]
    assert "Chosen" not in public.json()["cv_html"]
    first_docx = await app_client.get(
        base + "/versions/1/docx", headers=app_auth_headers
    )
    assert first_docx.status_code == 200, first_docx.text
    async with AsyncSessionLocal() as db:
        source = await db.get(CvGeneratedDocument, generated_id)
        await db.delete(source)
        await db.commit()
    second_docx = await app_client.get(
        base + "/versions/1/docx", headers=app_auth_headers
    )
    assert second_docx.status_code == 200, second_docx.text
    assert second_docx.content == first_docx.content
    from io import BytesIO
    from docx import Document

    document = Document(BytesIO(second_docx.content))
    visible = "\n".join(p.text for p in document.paragraphs)
    assert "Reviewed Python result" in visible and "Chosen" not in visible
