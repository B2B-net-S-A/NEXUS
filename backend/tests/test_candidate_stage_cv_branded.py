"""Testy brandowanego CV per rekrutacja + public share token (PR2 — Faza 3+4).

Pokrycie:

  GET /cv/branded:
    * GET w stanie 'none' → pusty stan (stary szablon „CV firmowe" wycofany
      w generatorze v3): status='none', content_html=None, BEZ zapisu (CV-01)
    * drugi GET → nadal 'none', nic nie zapisane

  PATCH /cv/branded:
    * save content_html → zachowuje treść
    * swap template → 410 (stary szablon wycofany)
    * podać oba → 422 (model_validator)
    * podać żaden → 422
    * po finalize → 409 immutable

  GET /cv/branded/render-pdf:
    * zwraca printable HTML (z window.print() script)
    * 404 w stanie 'none' (nie ma czego drukować)

  POST /cv/branded/finalize:
    * draft → finalized, snapshot do storage
    * 'none' → 409 „Najpierw wygeneruj CV w generatorze”
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


@pytest.fixture(autouse=True)
def approved_content_review(monkeypatch):
    """This module tests persistence/sharing/RBAC with a successful review result.

    Factual review behavior has focused tests; rejection is also exercised below
    through the real HTTP approval endpoint and database state.
    """
    from unittest.mock import AsyncMock
    from app.services import cv_approval_review

    result = AsyncMock(return_value={"status": "verified", "method": "test-review"})
    monkeypatch.setattr(cv_approval_review, "review_for_approval", result)
    return result


async def _draft_request_body(url, body=None):
    sid = int(url.split("/stages/")[1].split("/")[0])
    async with AsyncSessionLocal() as db:
        csv = await db.scalar(
            select(CandidateStageCV).where(CandidateStageCV.candidate_stage_id == sid)
        )
        values = {"expected_revision": csv.edit_revision}
        if url.endswith("/finalize"):
            values["content_html"] = (
                csv.branded_draft_html or "<h1>Brand</h1><p>Treść CV</p>"
            )
        return {**values, **(body or {})}


async def _patch(client, url, **kwargs):
    kwargs["json"] = await _draft_request_body(url, kwargs.get("json"))
    return await client.patch(url, **kwargs)


async def _seed_draft(sid: int, html: str = "<h1>Brand</h1><p>Treść CV</p>") -> None:
    """Szkic CV etapu założony wprost w bazie.

    Generator v3: szkic powstaje WYŁĄCZNIE z generatora (podpięcie po generacji
    albo ``select-generated``) — PATCH na pustym etapie to 409. Te testy
    dotyczą zapisu, zatwierdzania i linków, nie pochodzenia szkicu, więc
    zakładamy go bezpośrednio (idempotentnie: istniejący szkic zostaje).
    """
    async with AsyncSessionLocal() as db:
        csv = await db.scalar(
            select(CandidateStageCV).where(CandidateStageCV.candidate_stage_id == sid)
        )
        if csv.branded_status != "none":
            return
        csv.branded_status = "draft"
        csv.branded_draft_html = html
        csv.branded_template = "standard"
        csv.branded_language = "pl"
        await db.commit()


async def _ensure_draft(client, finalize_url, headers):
    base = finalize_url.removesuffix("/finalize")
    await _seed_draft(int(base.split("/stages/")[1].split("/")[0]))


async def _post(client, url, **kwargs):
    if url.endswith("/cv/branded/finalize"):
        await _ensure_draft(client, url, kwargs.get("headers"))
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
async def test_get_branded_none_is_an_empty_state_without_render(
    app_client: AsyncClient, app_auth_headers: dict
):
    """Generator v3: stary szablon „CV firmowe" (HTML z e-mailem i telefonem
    kandydata) wycofany — etap bez CV zwraca pusty stan, bez renderu."""
    sid, cid, jid = await _seed_full_stage()
    res = await app_client.get(
        f"/api/candidates/stages/{sid}/cv/branded", headers=app_auth_headers
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["status"] == "none"
    assert body["content_html"] is None
    assert body["template"] is None and body["language"] is None
    assert body["rendered_from_default"] is False
    # Żadnych danych kontaktowych kandydata w odpowiedzi.
    assert "500 000 001" not in res.text and "@example.com" not in res.text
    # CV-01: odczyt niczego nie zapisuje — ani statusu, ani treści, ani rewizji.
    async with AsyncSessionLocal() as db:
        csv = await db.scalar(
            select(CandidateStageCV).where(CandidateStageCV.candidate_stage_id == sid)
        )
        assert csv.branded_status == "none"
        assert csv.branded_draft_html is None
        assert csv.branded_updated_by is None
        assert (csv.edit_revision or 0) == body["edit_revision"]


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
    assert second.json()["status"] == "none"
    assert second.json()["edit_revision"] == first.json()["edit_revision"]
    assert second.json()["content_html"] is None


# ── PATCH save / swap ──────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_patch_branded_saves_content(
    app_client: AsyncClient, app_auth_headers: dict
):
    sid, _, _ = await _seed_full_stage()
    await _seed_draft(sid)
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
@pytest.mark.parametrize("empty", ["", "   ", "<style>x</style>", "<script>a</script>"])
async def test_patch_with_nothing_left_after_cleaning_is_refused(
    app_client: AsyncClient, app_auth_headers: dict, empty: str
):
    """Audyt 13.10.2026, pkt 2: pusty zapis zdejmował ochronę klauzuli RODO —
    następny zapis z podmienioną klauzulą przechodził, a zatwierdzenie
    przypinało ją w Wordzie. Pusta treść = 422 jak przy zatwierdzeniu
    i w edytorze generatora; szkic zostaje bez zmian."""
    from app.services.cv_generator_b2b.docx_renderer import TRANSLATIONS

    clause = TRANSLATIONS["pl"]["rodo"]
    saved = f'<h1>Brand</h1><p>Treść CV</p><p class="rodo">{clause}</p>'
    sid, _, _ = await _seed_full_stage()
    await _seed_draft(sid, saved)

    res = await _patch(
        app_client,
        f"/api/candidates/stages/{sid}/cv/branded",
        headers=app_auth_headers,
        json={"content_html": empty},
    )

    assert res.status_code == 422, res.text
    assert res.json()["detail"] == "CV nie może być puste."
    async with AsyncSessionLocal() as db:
        csv = await db.scalar(
            select(CandidateStageCV).where(CandidateStageCV.candidate_stage_id == sid)
        )
        assert csv.branded_draft_html == saved


@pytest.mark.asyncio
async def test_saving_and_approving_keep_the_saved_consent_clause(
    app_client: AsyncClient, app_auth_headers: dict
):
    """Klauzula zgody RODO jest stała (D3, 12.10.2026): zapis bez niej albo
    ze zmienioną treścią zostawia w szkicu i w zatwierdzonej wersji tę, która
    była w CV."""
    from app.services.cv_generator_b2b.docx_renderer import TRANSLATIONS

    clause = TRANSLATIONS["pl"]["rodo"]
    sid, _, _ = await _seed_full_stage()
    await _seed_draft(sid, f'<h1>Brand</h1><p>Treść CV</p><p class="rodo">{clause}</p>')
    url = f"/api/candidates/stages/{sid}/cv/branded"

    res = await _patch(
        app_client,
        url,
        headers=app_auth_headers,
        json={"content_html": "<h1>Brand</h1><p>Po edycji</p>"},
    )
    assert res.status_code == 200, res.text
    saved = res.json()["content_html"]
    assert saved.startswith("<h1>Brand</h1><p>Po edycji</p>")
    assert saved.endswith(f'<p class="rodo">{clause}</p>')

    edited = clause.replace("B2B.net S.A.", "Inną Firmę")
    res = await _post(
        app_client,
        f"{url}/finalize",
        headers=app_auth_headers,
        json={
            "content_html": f'<h1>Brand</h1><p>Po edycji</p><p data-cv-section="rodo">{edited}</p>'
        },
    )
    assert res.status_code == 200, res.text
    async with AsyncSessionLocal() as db:
        version = await db.get(CvDocumentVersion, res.json()["document_version_id"])
        assert "Inną Firmę" not in version.content_html
        assert version.content_html.endswith(f'<p class="rodo">{clause}</p>')


@pytest.mark.asyncio
async def test_issues_route_serves_generator_warnings_and_review_findings(
    app_client: AsyncClient, app_auth_headers: dict
):
    """Panel „Do poprawy” w edytorze (PR 2): uwagi generatora z dokumentu
    podpiętego do etapu i uwagi kontroli AI ostatniej zatwierdzonej wersji —
    z tekstem linii, nie samym wskaźnikiem."""
    from app.models.cv_generated_document import CvGeneratedDocument
    from app.services.cv_editor_review import EDITOR_REVIEW_VERSION, editor_claims

    html = "<h1>Brand</h1><p>Zna Kafkę od 5 lat.</p><p>Prowadził zespół.</p>"
    sid, _, _ = await _seed_full_stage()
    url = f"/api/candidates/stages/{sid}/cv/branded/issues"

    empty = await app_client.get(url, headers=app_auth_headers)
    assert empty.status_code == 200, empty.text
    assert empty.json() == {
        "generated_document_id": None,
        "generator_warnings": [],
        "content_review": {"status": None, "version": None, "findings": []},
        "dismissed": [],
    }

    await _seed_draft(sid, html)
    async with AsyncSessionLocal() as db:
        csv = await db.scalar(
            select(CandidateStageCV).where(CandidateStageCV.candidate_stage_id == sid)
        )
        generated = CvGeneratedDocument(
            candidate_id=csv.candidate_id,
            job_id=csv.job_id,
            candidate_name="Fikcyjna Osoba",
            filename="cv.docx",
            mode="new",
            status="ready",
            warnings=["MUST-HAVE: Kubernetes — brak w CV", "  "],
        )
        db.add(generated)
        await db.flush()
        csv.generated_document_id = generated.id
        index = editor_claims(html).index("Zna Kafkę od 5 lat.")
        db.add(
            CvDocumentVersion(
                candidate_stage_cv_id=csv.id,
                generated_document_id=generated.id,
                version=1,
                content_html=html,
                content_sha256=hashlib.sha256(html.encode()).hexdigest(),
                render_metadata={
                    "content_review": {
                        "status": "reviewed",
                        "html_sha256": hashlib.sha256(html.encode()).hexdigest(),
                        "editor_review_version": EDITOR_REVIEW_VERSION,
                        "findings": {
                            "count": 1,
                            "paths": [f"/why_points/{index}"],
                            "statuses": {f"/why_points/{index}": "unsupported"},
                        },
                    }
                },
                language="pl",
                template="standard",
                approved_at=datetime.now(timezone.utc),
            )
        )
        generated_id = generated.id
        await db.commit()

    res = await app_client.get(url, headers=app_auth_headers)
    assert res.status_code == 200, res.text
    assert res.json() == {
        "generated_document_id": generated_id,
        "generator_warnings": ["MUST-HAVE: Kubernetes — brak w CV"],
        "content_review": {
            "status": "reviewed",
            "version": 1,
            "findings": [{"text": "Zna Kafkę od 5 lat.", "status": "unsupported"}],
        },
        "dismissed": [],
    }
    assert (await app_client.get(url)).status_code in (401, 403)
    missing = await app_client.get(
        "/api/candidates/stages/999999999/cv/branded/issues", headers=app_auth_headers
    )
    assert missing.status_code == 404


@pytest.mark.asyncio
async def test_patch_on_an_empty_stage_is_refused(
    app_client: AsyncClient, app_auth_headers: dict
):
    """Generator v3: ręczny HTML na pustym etapie omijałby reguły klienta
    i blokadę zgody RODO — szkic powstaje wyłącznie z generatora."""
    sid, _, _ = await _seed_full_stage()
    res = await _patch(
        app_client,
        f"/api/candidates/stages/{sid}/cv/branded",
        headers=app_auth_headers,
        json={"content_html": "<p>Ręczny HTML</p>"},
    )
    assert res.status_code == 409, res.text
    assert "Najpierw wygeneruj CV" in res.json()["detail"]
    async with AsyncSessionLocal() as db:
        csv = await db.scalar(
            select(CandidateStageCV).where(CandidateStageCV.candidate_stage_id == sid)
        )
        assert csv.branded_status == "none" and csv.branded_draft_html is None


@pytest.mark.asyncio
async def test_patch_branded_template_swap_is_gone(
    app_client: AsyncClient, app_auth_headers: dict
):
    """Zmiana szablonu renderowała stary szablon „CV firmowe" — 410."""
    sid, _, _ = await _seed_full_stage()
    res = await _patch(
        app_client,
        f"/api/candidates/stages/{sid}/cv/branded",
        headers=app_auth_headers,
        json={"template": "blind", "language": "en"},
    )
    assert res.status_code == 410, res.text
    assert "wycofany" in res.json()["detail"]
    async with AsyncSessionLocal() as db:
        csv = await db.scalar(
            select(CandidateStageCV).where(CandidateStageCV.candidate_stage_id == sid)
        )
        assert csv.branded_status == "none" and csv.branded_draft_html is None


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
    none = await app_client.get(
        f"/api/candidates/stages/{sid}/cv/branded/render-pdf",
        headers=app_auth_headers,
    )
    # Stan 'none' nie ma czego drukować (stary szablon wycofany).
    assert none.status_code == 404, none.text
    await _seed_draft(sid, "<h1>Brand</h1><p>Do druku</p>")
    res = await app_client.get(
        f"/api/candidates/stages/{sid}/cv/branded/render-pdf",
        headers=app_auth_headers,
    )
    assert res.status_code == 200
    assert "window.print()" in res.text
    assert "Do druku" in res.text
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
async def test_finalize_refuses_none(app_client: AsyncClient, app_auth_headers: dict):
    """Generator v3: zatwierdzić można wyłącznie CV podpięte do etapu — stan
    'none' odsyła do generatora zamiast materializować stary szablon."""
    sid, _, _ = await _seed_full_stage()
    preview = await app_client.get(
        f"/api/candidates/stages/{sid}/cv/branded", headers=app_auth_headers
    )
    res = await app_client.post(
        f"/api/candidates/stages/{sid}/cv/branded/finalize",
        headers=app_auth_headers,
        json={
            "expected_revision": preview.json()["edit_revision"],
            "content_html": "<p>Treść spoza generatora</p>",
        },
    )
    assert res.status_code == 409, res.text
    assert "Najpierw wygeneruj CV" in res.json()["detail"]
    async with AsyncSessionLocal() as db:
        csv = await db.scalar(
            select(CandidateStageCV).where(CandidateStageCV.candidate_stage_id == sid)
        )
        assert csv.branded_status == "none"


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
    await _seed_draft(sid_a)
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
    assert body_b["status"] == "none"  # podgląd bez zapisu (CV-01)
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
    await _ensure_draft(app_client, url + "/finalize", app_auth_headers)
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
    await _seed_draft(sid)
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


async def test_select_generated_runs_qc_after_the_swap(
    app_client, app_auth_headers, monkeypatch
):
    """CV w procesie (13.10.2026): po „Użyj nowej wersji” (i podmianie szkicu
    z karty) QC liczy się w tle, żeby plakietka na Tablicy nie czekała na
    otwarcie okna QC. Odmowa 409 (szkic zmienił się) niczego nie przelicza."""
    from app.core.config import settings
    from app.models.cv_generated_document import CvGeneratedDocument
    from app.services import cv_qc

    calls: list[int] = []

    async def run_after_move(stage_id, user_id):
        calls.append(stage_id)

    monkeypatch.setattr(cv_qc, "run_after_move", run_after_move)
    monkeypatch.setattr(settings, "CV_QC_GATE_ENABLED", True)
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
            render_payload={"name": "Synthetic", "why_points": ["Python w Acme"]},
        )
        db.add(source)
        await db.commit()
        generated_id = source.id
    stale = await app_client.post(
        base + "/select-generated",
        headers=app_auth_headers,
        json={
            "expected_revision": initial["edit_revision"] + 5,
            "generated_document_id": generated_id,
        },
    )
    assert stale.status_code == 409, stale.text
    assert calls == []
    choice = await app_client.post(
        base + "/select-generated",
        headers=app_auth_headers,
        json={
            "expected_revision": initial["edit_revision"],
            "generated_document_id": generated_id,
        },
    )
    assert choice.status_code == 200, choice.text
    assert calls == [sid]


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
    assert link.status_code == 201, link.text
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


async def test_review_rejection_keeps_database_draft(
    app_client, app_auth_headers, approved_content_review
):
    from fastapi import HTTPException

    sid, _, _ = await _seed_full_stage()
    # Szkic etapu (w aplikacji: podpięcie CV z generatora).
    await _seed_draft(sid, "<h1>Brand</h1><p>Szkic</p>")
    approved_content_review.side_effect = HTTPException(422, "Niepotwierdzone fakty")
    response = await _post(
        app_client,
        f"/api/candidates/stages/{sid}/cv/branded/finalize",
        headers=app_auth_headers,
    )
    assert response.status_code == 422
    current = await app_client.get(
        f"/api/candidates/stages/{sid}/cv/branded", headers=app_auth_headers
    )
    assert current.status_code == 200
    assert current.json()["status"] == "draft"


# ── Historia wersji w edytorze CV (Edytor CV 2, PR 5) ───────────────────────


async def _approve(client, headers, url: str, revision: int, html: str) -> dict:
    approved = await client.post(
        url + "/finalize",
        headers=headers,
        json={"expected_revision": revision, "content_html": html},
    )
    assert approved.status_code == 200, approved.text
    return approved.json()


@pytest.mark.asyncio
async def test_version_history_lists_approved_versions_and_serves_each_content(
    app_client: AsyncClient, app_auth_headers: dict
):
    """Dwie zatwierdzone wersje: lista od najnowszej z nazwą osoby (nie
    e-mailem), treść każdej taka jak przy zatwierdzeniu, nic nie zapisane."""
    sid, _, _ = await _seed_full_stage()
    url = f"/api/candidates/stages/{sid}/cv/branded"

    never_approved = await app_client.get(url + "/versions", headers=app_auth_headers)
    assert never_approved.status_code == 200, never_approved.text
    assert never_approved.json() == {"versions": []}

    await _seed_draft(sid)
    state = (await app_client.get(url, headers=app_auth_headers)).json()
    first = await _approve(
        app_client,
        app_auth_headers,
        url,
        state["edit_revision"],
        "<p>Pierwsza wersja</p>",
    )
    draft = await app_client.post(
        url + "/new-draft",
        headers=app_auth_headers,
        json={"expected_revision": first["edit_revision"]},
    )
    assert draft.status_code == 200, draft.text
    while_drafting = await app_client.get(url + "/versions", headers=app_auth_headers)
    second = await _approve(
        app_client,
        app_auth_headers,
        url,
        draft.json()["edit_revision"],
        "<p>Druga wersja</p>",
    )

    listed = await app_client.get(url + "/versions", headers=app_auth_headers)
    one = await app_client.get(url + "/versions/1", headers=app_auth_headers)
    two = await app_client.get(url + "/versions/2", headers=app_auth_headers)
    missing = await app_client.get(url + "/versions/7", headers=app_auth_headers)
    docx = await app_client.get(url + "/versions/1/docx", headers=app_auth_headers)
    after = (await app_client.get(url, headers=app_auth_headers)).json()

    # Otwarty szkic nosi numer 2 — wersja 1 nie jest wtedy „bieżącą”.
    assert [
        (item["version"], item["is_current"])
        for item in while_drafting.json()["versions"]
    ] == [(1, False)]
    assert listed.status_code == 200, listed.text
    versions = listed.json()["versions"]
    assert [
        (item["version"], item["is_current"], item["language"]) for item in versions
    ] == [(2, True, "pl"), (1, False, "pl")]
    assert set(versions[0]) == {
        "version",
        "approved_at",
        "approved_by_name",
        "language",
        "docx_available",
        "is_current",
    }
    assert all(item["docx_available"] and item["approved_at"] for item in versions)
    # Imię i nazwisko z konta (fixture `app_client`), nie adres e-mail.
    assert {item["approved_by_name"] for item in versions} == {"Pytest Admin"}

    assert (one.status_code, two.status_code) == (200, 200)
    assert one.json()["version"] == 1 and one.json()["language"] == "pl"
    assert one.json()["approved_at"] == versions[1]["approved_at"]
    assert "Pierwsza wersja" in one.json()["content_html"]
    assert "Druga wersja" not in one.json()["content_html"]
    assert "Druga wersja" in two.json()["content_html"]
    assert missing.status_code == 404
    assert missing.json()["detail"] == "Nie znaleziono zatwierdzonej wersji CV."
    # Plik Word tej samej wersji dalej stoi pod własnym adresem.
    assert docx.status_code == 200, docx.text
    assert docx.content[:2] == b"PK"
    # Odczyty historii niczego nie zmieniły w CV etapu.
    assert (after["status"], after["version"], after["edit_revision"]) == (
        "finalized",
        2,
        second["edit_revision"],
    )


@pytest.mark.asyncio
async def test_version_history_shows_an_approved_cv_that_was_never_frozen(
    app_client: AsyncClient, app_auth_headers: dict
):
    """CV zatwierdzone przed migracją 0287 nie ma wiersza wersji. Historia
    pokazuje je z wiersza etapu i nie zakłada wiersza przy odczycie."""
    sid, _, _ = await _seed_full_stage()
    url = f"/api/candidates/stages/{sid}/cv/branded"
    await _seed_draft(sid)
    state = (await app_client.get(url, headers=app_auth_headers)).json()
    approved = await _approve(
        app_client,
        app_auth_headers,
        url,
        state["edit_revision"],
        "<p>Zatwierdzone dawno temu</p>",
    )
    async with AsyncSessionLocal() as db:
        await db.delete(
            await db.get(CvDocumentVersion, approved["document_version_id"])
        )
        await db.commit()

    listed = await app_client.get(url + "/versions", headers=app_auth_headers)
    content = await app_client.get(url + "/versions/1", headers=app_auth_headers)

    assert listed.status_code == 200, listed.text
    (only,) = listed.json()["versions"]
    assert (only["version"], only["is_current"], only["docx_available"]) == (
        1,
        True,
        False,
    )
    assert only["approved_by_name"] == "Pytest Admin" and only["approved_at"]
    assert content.status_code == 200, content.text
    assert "Zatwierdzone dawno temu" in content.json()["content_html"]
    async with AsyncSessionLocal() as db:
        frozen = await db.scalar(
            select(CvDocumentVersion.id).where(
                CvDocumentVersion.id == approved["document_version_id"]
            )
        )
    assert frozen is None


@pytest.mark.asyncio
async def test_version_history_keeps_the_gates_of_the_stage_cv_read(
    app_client: AsyncClient, app_auth_headers: dict
):
    """Bez sesji i dla konta bez dostępu do dokumentów — odmowa; etap bez
    wiersza CV to pusta lista (stan), nieistniejący etap to 404."""
    from app.core.security import create_access_token
    from app.models.user import User, UserRole

    sid, candidate_id, job_id = await _seed_full_stage()
    await _seed_draft(sid)
    url = f"/api/candidates/stages/{sid}/cv/branded"
    state = (await app_client.get(url, headers=app_auth_headers)).json()
    await _approve(
        app_client, app_auth_headers, url, state["edit_revision"], "<p>Treść</p>"
    )
    async with AsyncSessionLocal() as db:
        viewer = User(
            email=f"cv-history-viewer-{uuid.uuid4().hex[:8]}@example.com",
            name="Konto bez dokumentów",
            role=UserRole.user,
            roles=[UserRole.user.value],
            is_active=True,
        )
        bare_stage = CandidateStage(
            candidate_id=candidate_id, job_id=job_id, stage=PipelineStage.screening
        )
        db.add_all([viewer, bare_stage])
        await db.commit()
        viewer_headers = {
            "Authorization": "Bearer "
            + create_access_token(viewer.id, UserRole.user.value)
        }
        bare_url = f"/api/candidates/stages/{bare_stage.id}/cv/branded"

    for path in ("/versions", "/versions/1"):
        anonymous = await app_client.get(url + path)
        refused = await app_client.get(url + path, headers=viewer_headers)
        unknown = await app_client.get(
            "/api/candidates/stages/999999999/cv/branded" + path,
            headers=app_auth_headers,
        )
        assert anonymous.status_code in (401, 403), path
        assert refused.status_code == 403, path
        assert unknown.status_code == 404, path
    no_row_list = await app_client.get(bare_url + "/versions", headers=app_auth_headers)
    no_row_one = await app_client.get(
        bare_url + "/versions/1", headers=app_auth_headers
    )
    assert no_row_list.status_code == 200, no_row_list.text
    assert no_row_list.json() == {"versions": []}
    assert no_row_one.status_code == 404
    async with AsyncSessionLocal() as db:
        created = await db.scalar(
            select(CandidateStageCV.id).where(
                CandidateStageCV.candidate_stage_id == bare_stage.id
            )
        )
    assert created is None


# ── „Napisz od nowa” (Edytor CV 3, PR 5) ─────────────────────────────────────

_REWRITE_A = {
    "name": "Synthetic",
    "language": "pl",
    "why_points": ["Python w Acme."],
    "languages": ["Polski – ojczysty"],
    "experience": [
        {
            "dates": "01.2020 – obecnie",
            "company": "Acme",
            "position": "Developer",
            "responsibilities": ["Usługi REST."],
            "technologies": ["Python"],
        },
        {
            "dates": "01.2015 – 12.2019",
            "company": "Beta",
            "position": "Junior Developer",
            "responsibilities": ["Testy ręczne."],
            "technologies": [],
        },
    ],
}


def _rewrite_b() -> dict:
    import copy

    payload = copy.deepcopy(_REWRITE_A)
    payload["why_points"] = ["Usługi REST w Pythonie."]
    payload["experience"][0]["responsibilities"] = ["Usługi REST w Pythonie."]
    payload["experience"][1]["responsibilities"] = ["Testy."]
    return payload


async def _ready_generation(cid: int, jid: int, payload: dict) -> int:
    from app.models.cv_generated_document import CvGeneratedDocument

    async with AsyncSessionLocal() as db:
        row = CvGeneratedDocument(
            candidate_id=cid,
            job_id=jid,
            candidate_name="Synthetic",
            filename="cv.docx",
            status="ready",
            render_payload=payload,
        )
        db.add(row)
        await db.commit()
        return row.id


async def test_rewrite_keeps_hand_edited_role_and_previous_draft_comes_back(
    app_client, app_auth_headers
):
    sid, cid, jid = await _seed_full_stage()
    base = f"/api/candidates/stages/{sid}/cv/branded"
    initial = (await app_client.get(base, headers=app_auth_headers)).json()
    first = await _ready_generation(cid, jid, _REWRITE_A)
    second = await _ready_generation(cid, jid, _rewrite_b())

    picked = await app_client.post(
        base + "/select-generated",
        headers=app_auth_headers,
        json={
            "expected_revision": initial["edit_revision"],
            "generated_document_id": first,
        },
    )
    assert picked.status_code == 200, picked.text
    # Zwykła podmiana nie niesie wyniku „Napisz od nowa”.
    assert picked.json()["rewrite"] is None
    edited = picked.json()["content_html"].replace(
        "Testy ręczne.", "Testy API w Pytest (fikcyjne)."
    )
    saved = await app_client.patch(
        base,
        headers=app_auth_headers,
        json={
            "expected_revision": picked.json()["edit_revision"],
            "content_html": edited,
        },
    )
    assert saved.status_code == 200, saved.text
    before = saved.json()["content_html"]

    rewrite = await app_client.post(
        base + "/select-generated",
        headers=app_auth_headers,
        json={
            "expected_revision": saved.json()["edit_revision"],
            "generated_document_id": second,
            "keep_edits": True,
        },
    )
    assert rewrite.status_code == 200, rewrite.text
    body = rewrite.json()
    assert body["rewrite"] == {
        "kept": ["Beta"],
        "recognized": True,
        "can_restore": True,
    }
    assert "Testy API w Pytest (fikcyjne)." in body["content_html"]
    assert "Usługi REST w Pythonie." in body["content_html"]
    assert body["generated_document_id"] == second

    restored = await app_client.post(
        base + "/restore-previous",
        headers=app_auth_headers,
        json={"expected_revision": body["edit_revision"]},
    )
    assert restored.status_code == 200, restored.text
    assert restored.json()["content_html"] == before
    assert restored.json()["generated_document_id"] == first
    # Wersja zdjęta przyciskiem też jest w migawce — nic nie ginie.
    from app.models.cv_stage_draft_snapshot import CvStageDraftSnapshot

    async with AsyncSessionLocal() as db:
        reasons = (
            await db.scalars(
                select(CvStageDraftSnapshot.reason).order_by(CvStageDraftSnapshot.id)
            )
        ).all()
    assert reasons[-1] == "restore"


async def test_restore_previous_brings_back_blind_flag_and_language_of_the_snapshot(
    app_client, app_auth_headers
):
    """Przegląd PR 5: treść wracała z migawki, a „anonimowe” i język zostawały
    z bieżącej wersji — CV z nazwiskiem oznaczone jako anonimowe."""
    import copy

    sid, cid, jid = await _seed_full_stage()
    base = f"/api/candidates/stages/{sid}/cv/branded"
    initial = (await app_client.get(base, headers=app_auth_headers)).json()
    plain = await _ready_generation(cid, jid, _REWRITE_A)
    blind_payload = copy.deepcopy(_REWRITE_A)
    blind_payload.update(blind_cv=True, language="en")
    blind = await _ready_generation(cid, jid, blind_payload)

    first = await app_client.post(
        base + "/select-generated",
        headers=app_auth_headers,
        json={
            "expected_revision": initial["edit_revision"],
            "generated_document_id": plain,
        },
    )
    assert first.status_code == 200, first.text
    assert (first.json()["template"], first.json()["language"]) == ("standard", "pl")
    second = await app_client.post(
        base + "/select-generated",
        headers=app_auth_headers,
        json={
            "expected_revision": first.json()["edit_revision"],
            "generated_document_id": blind,
        },
    )
    assert second.status_code == 200, second.text
    assert (second.json()["template"], second.json()["language"]) == ("blind", "en")
    restored = await app_client.post(
        base + "/restore-previous",
        headers=app_auth_headers,
        json={"expected_revision": second.json()["edit_revision"]},
    )
    assert restored.status_code == 200, restored.text
    assert (restored.json()["template"], restored.json()["language"]) == (
        "standard",
        "pl",
    )
    assert restored.json()["content_html"] == first.json()["content_html"]


async def test_restore_previous_refuses_stale_revision_and_missing_snapshot(
    app_client, app_auth_headers
):
    sid, cid, jid = await _seed_full_stage()
    base = f"/api/candidates/stages/{sid}/cv/branded"
    initial = (await app_client.get(base, headers=app_auth_headers)).json()
    stale = await app_client.post(
        base + "/restore-previous",
        headers=app_auth_headers,
        json={"expected_revision": initial["edit_revision"] + 3},
    )
    assert stale.status_code == 409, stale.text
    async with AsyncSessionLocal() as db:
        await db.execute(
            update(CandidateStageCV)
            .where(CandidateStageCV.candidate_stage_id == sid)
            .values(branded_draft_html=None)
        )
        await db.commit()
    first = await _ready_generation(cid, jid, _REWRITE_A)
    picked = await app_client.post(
        base + "/select-generated",
        headers=app_auth_headers,
        json={
            "expected_revision": initial["edit_revision"],
            "generated_document_id": first,
        },
    )
    assert picked.status_code == 200, picked.text
    # Przed tą podmianą szkic był pusty — nie ma do czego wracać.
    missing = await app_client.post(
        base + "/restore-previous",
        headers=app_auth_headers,
        json={"expected_revision": picked.json()["edit_revision"]},
    )
    assert missing.status_code == 404, missing.text


def test_snapshot_migration_is_mirrored_in_entrypoint_and_model() -> None:
    import re
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    entry = (root / "entrypoint.sh").read_text()
    migration = (root / "alembic/versions/0445_cv_stage_draft_snapshots.py").read_text()
    squash = lambda t: re.sub(r"\s+", " ", t)  # noqa: E731
    for fragment in (
        "CREATE TABLE IF NOT EXISTS cv_stage_draft_snapshots (",
        "candidate_stage_cv_id INTEGER NOT NULL REFERENCES candidate_stage_cvs(id) ON DELETE CASCADE",
        "generated_document_id INTEGER NULL REFERENCES cv_generated_documents(id) ON DELETE SET NULL",
        "CHECK (reason IN ('replaced', 'restore'))",
        "branded_template VARCHAR(20) NULL",
        "branded_language VARCHAR(10) NULL",
        "CREATE INDEX IF NOT EXISTS ix_cv_stage_draft_snapshots_cv",
    ):
        assert fragment in squash(migration), fragment
        assert fragment in squash(entry), fragment
    assert 'down_revision = "0444_also_fits_added_notification"' in migration
    from app.models.cv_stage_draft_snapshot import CvStageDraftSnapshot

    columns = set(CvStageDraftSnapshot.__table__.columns.keys())
    for name in re.findall(
        r"^    ([a-z_]+) [A-Z]", migration.split('"""CREATE TABLE')[1], re.M
    ):
        assert name in columns, name
