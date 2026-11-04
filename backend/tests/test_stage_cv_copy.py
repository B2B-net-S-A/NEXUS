"""„Użyj innego CV” w karcie „CV do klienta” (12.10.2026).

Pomiar na produkcji: 16 z 22 auto-CV z dwóch tygodni powstało dla osób, które
miały już gotowe CV. Testy pilnują trzech dróg do szkicu bez generacji — CV
etapu z innej rekrutacji (z poprawkami rekrutera), plik Word z dysku
i zrzut zgody jadący z kopią w obrębie jednego klienta — oraz ich odmów.
"""

from __future__ import annotations

import hashlib
import uuid
from io import BytesIO

import pytest
from httpx import AsyncClient
from PIL import Image
from sqlalchemy import func, select

import app.models  # noqa: F401
from app.core.database import AsyncSessionLocal
from app.models.activity import Activity
from app.models.candidate_document import CandidateDocument
from app.models.candidate_stage_cv import CandidateStageCV
from app.models.client import Client
from app.models.cv_document_version import CvDocumentVersion
from app.models.job import Job
from app.models.recruitment_pipeline import CandidateStage, PipelineStage
from app.models.user import User, UserRole
from app.services.cv_docx_import import docx_to_editor_html
from tests.test_stage_cv_pick_from_profile import (
    MARKER,
    _base,
    _csv,
    _docx,
    _revision,
    _seed,
    consent_client,
)

DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
FIX = "Poprawka rekrutera: prowadziła migrację do chmury"
# Treść po edycji w edytorze: nagłówek z tytułem rekrutacji ŹRÓDŁOWEJ.
EDITED = (
    "<h1>ZOB-1725 Inżynier DevOps – Ewa Fikcyjna</h1>"
    "<p><b>Rozważany na stanowisko:</b> ZOB-1725 Inżynier DevOps w banku</p>"
    '<h2 data-cv-section="why_points">DLACZEGO NASZ KANDYDAT?</h2>'
    f"<ul><li>{FIX}</li></ul>"
)
GENERATOR_METADATA = {
    # Klucze, których kopia NIE może odziedziczyć: skrót treści generatora
    # dałby jej fałszywe „zweryfikowane”, migawka reguł — limity cudzego klienta.
    "generated_editor_html_sha256": "a" * 64,
    "generation_review_available": True,
    "client_rule_snapshot": {"max_roles": 3},
    "client_rule_snapshot_status": "verified",
    "blind_identity_guard": False,
    "blind_identity_terms": [],
}


def _png() -> bytes:
    out = BytesIO()
    Image.new("RGB", (3, 3), "white").save(out, format="PNG")
    return out.getvalue()


async def _source_cv(
    world: dict,
    *,
    job_id: int | None = None,
    stage: PipelineStage = PipelineStage.cv_sent,
    **columns,
) -> dict:
    """CV etapu tej samej osoby w innej rekrutacji (domyślnie zatwierdzone)."""
    async with AsyncSessionLocal() as db:
        stage = CandidateStage(
            candidate_id=world["candidate_id"],
            job_id=job_id or world["other_job_id"],
            stage=stage,
        )
        db.add(stage)
        await db.flush()
        values = {
            "branded_status": "finalized",
            "branded_draft_html": EDITED,
            "branded_from_generator": True,
            "branded_language": "pl",
            "branded_template": "standard",
            "branded_version": 2,
            "branded_render_metadata": dict(GENERATOR_METADATA),
            **columns,
        }
        row = CandidateStageCV(
            candidate_stage_id=stage.id,
            candidate_id=world["candidate_id"],
            job_id=stage.job_id,
            **values,
        )
        db.add(row)
        await db.commit()
        return {"stage_id": stage.id, "csv_id": row.id, "job_id": stage.job_id}


async def _job(*, same_client_as: int | None = None, title: str = "Trzecia") -> int:
    """Kolejna rekrutacja: u tego samego klienta albo u nowego (fikcyjnego)."""
    tag = uuid.uuid4().hex[:8]
    async with AsyncSessionLocal() as db:
        if same_client_as is not None:
            client_id = await db.scalar(
                select(Job.client_id).where(Job.id == same_client_as)
            )
        else:
            client = Client(name=f"Trzeci klient kopii CV {tag}")
            db.add(client)
            await db.flush()
            client_id = client.id
        job = Job(title=f"{title} {tag}", client_id=client_id)
        db.add(job)
        await db.commit()
        return job.id


async def _copy(client: AsyncClient, headers: dict, world: dict, source_job_id: int):
    return await client.post(
        _base(world["stage_id"]) + "/select-stage-cv",
        headers=headers,
        json={
            "expected_revision": await _revision(client, headers, world["stage_id"]),
            "source_job_id": source_job_id,
        },
    )


@pytest.mark.asyncio
async def test_branded_get_answers_empty_state_for_a_stage_without_a_cv_row(
    app_client: AsyncClient, app_auth_headers: dict
):
    """Etapy z importu Traffita nie mają wiersza CV — karta pokazana przed
    „Zweryfikowany” dostawała 404 i rysowała błąd wczytania."""
    world = await _seed(with_cv_row=False)
    response = await app_client.get(_base(world["stage_id"]), headers=app_auth_headers)

    assert response.status_code == 200, response.text
    body = response.json()
    assert (body["status"], body["edit_revision"]) == ("none", 0)
    assert body["candidate_stage_id"] == world["stage_id"]
    assert await _csv(world["stage_id"]) is None
    missing = await app_client.get(_base(2_000_000_000), headers=app_auth_headers)
    assert missing.status_code == 404


@pytest.mark.asyncio
async def test_sources_list_one_cv_per_other_recruitment_and_write_nothing(
    app_client: AsyncClient, app_auth_headers: dict
):
    world = await _seed(with_cv_row=False)
    await _source_cv(world, branded_status="draft", branded_version=3)
    approved = await _source_cv(world)
    # Stary szablon „CV firmowe” (z danymi kontaktowymi) nie jest do kopiowania.
    await _source_cv(
        world,
        job_id=await _job(),
        branded_from_generator=False,
        branded_render_metadata={},
    )
    # CV TEJ rekrutacji nie jest „innym CV”.
    await _source_cv(world, job_id=world["job_id"])

    response = await app_client.get(
        _base(world["stage_id"]) + "/sources", headers=app_auth_headers
    )

    assert response.status_code == 200, response.text
    items = response.json()["items"]
    assert [item["job_id"] for item in items] == [world["other_job_id"]]
    # Zatwierdzone wygrywa ze szkicem tej samej pary.
    assert (items[0]["status"], items[0]["version"]) == ("finalized", 2)
    assert items[0]["stage_id"] == approved["stage_id"]
    assert items[0]["client_name"].startswith("Inny klient")
    assert items[0]["consent_carried"] is False
    assert await _csv(world["stage_id"]) is None


@pytest.mark.asyncio
async def test_edited_cv_from_another_recruitment_becomes_a_detached_draft(
    app_client: AsyncClient, app_auth_headers: dict
):
    world = await _seed(with_cv_row=False)
    source = await _source_cv(world)

    chosen = await _copy(app_client, app_auth_headers, world, world["other_job_id"])

    assert chosen.status_code == 200, chosen.text
    body = chosen.json()
    assert (body["status"], body["source"]) == ("draft", "generator")
    assert body["generated_document_id"] is None
    assert body["origin"]["kind"] == "stage_copy"
    assert body["origin"]["job_id"] == world["other_job_id"]
    assert body["origin"]["selected_at"]
    # Treść po poprawkach rekrutera, nagłówek o TEJ rekrutacji.
    assert FIX in body["content_html"]
    assert "ZOB-1725" not in body["content_html"]
    assert (
        f"<h1>Platform Engineer {world['tag']} – Ewa Fikcyjna</h1>"
        in body["content_html"]
    )

    csv = await _csv(world["stage_id"])
    metadata = csv.branded_render_metadata
    assert metadata["source"] == "generated_other_job"
    assert metadata["source_stage_cv_id"] == source["csv_id"]
    assert csv.generated_document_id is None and csv.branded_from_generator is True
    assert csv.branded_consent_content is None
    assert world["tag"] in csv.branded_docx_filename
    async with AsyncSessionLocal() as db:
        original = await db.get(CandidateStageCV, source["csv_id"])
        assert (original.branded_status, original.branded_draft_html) == (
            "finalized",
            EDITED,
        )
        activity = await db.scalar(
            select(Activity).where(
                Activity.entity_type == "candidate_stage_cv",
                Activity.entity_id == csv.id,
                Activity.action == "branded_cv_copied_from_other_job",
            )
        )
        assert activity.details["source_job_id"] == world["other_job_id"]


@pytest.mark.asyncio
async def test_copy_does_not_inherit_generation_review_or_client_rules(
    app_client: AsyncClient, app_auth_headers: dict
):
    world = await _seed()
    await _source_cv(world)

    chosen = await _copy(app_client, app_auth_headers, world, world["other_job_id"])

    assert chosen.status_code == 200, chosen.text
    metadata = (await _csv(world["stage_id"])).branded_render_metadata
    for inherited in (
        "generated_editor_html_sha256",
        "generation_review_available",
        "client_rule_snapshot",
        "client_rule_snapshot_status",
    ):
        assert inherited not in metadata
    assert "consent_required" not in metadata


@pytest.mark.asyncio
async def test_word_origin_copy_stays_an_editable_document_draft(
    app_client: AsyncClient, app_auth_headers: dict
):
    """Nagłówek pliku Word pochodzi z pliku (bywa samym nazwiskiem) — kopia
    go nie przepisuje, a szkic nie może wyjść jako „stary szablon”."""
    world = await _seed()
    word_html = "<h1>Ewa Fikcyjna</h1><p>Inżynier platformy od dziesięciu lat.</p>"
    await _source_cv(
        world,
        branded_status="draft",
        branded_draft_html=word_html,
        branded_from_generator=False,
        branded_render_metadata={"source": "document", "source_document_id": 1},
    )

    chosen = await _copy(app_client, app_auth_headers, world, world["other_job_id"])

    assert chosen.status_code == 200, chosen.text
    body = chosen.json()
    assert (body["source"], body["from_generator"]) == ("document", False)
    assert body["content_html"] == word_html
    assert (await _csv(world["stage_id"])).branded_render_metadata[
        "source"
    ] == "document"


@pytest.mark.asyncio
async def test_blind_copy_keeps_identity_guard_and_masked_file_name(
    app_client: AsyncClient, app_auth_headers: dict
):
    world = await _seed()
    terms = [f"Ewa Fikcyjna{world['tag']}", "Ewa"]
    await _source_cv(
        world,
        branded_template="blind",
        branded_draft_html="<h1>ZOB-1725 Inżynier DevOps</h1><p>Dziesięć lat w chmurze.</p>",
        branded_render_metadata={
            **GENERATOR_METADATA,
            "blind_identity_guard": True,
            "blind_identity_terms": terms,
        },
    )

    chosen = await _copy(app_client, app_auth_headers, world, world["other_job_id"])

    assert chosen.status_code == 200, chosen.text
    assert f"<h1>Platform Engineer {world['tag']}</h1>" in chosen.json()["content_html"]
    assert "Fikcyjna" not in chosen.json()["content_html"]
    csv = await _csv(world["stage_id"])
    assert csv.branded_template == "blind"
    assert "Fikcyjna" not in csv.branded_docx_filename
    assert "Kandydat" in csv.branded_docx_filename
    assert csv.branded_render_metadata["blind_identity_guard"] is True
    assert csv.branded_render_metadata["blind_identity_terms"] == terms


@pytest.mark.asyncio
async def test_copy_is_refused_for_foreign_same_or_legacy_sources(
    app_client: AsyncClient, app_auth_headers: dict
):
    world = await _seed()
    stranger = await _seed()
    await _source_cv(stranger)
    legacy_job = await _job()
    await _source_cv(
        world,
        job_id=legacy_job,
        branded_from_generator=False,
        branded_render_metadata={},
    )
    # CV tej samej rekrutacji przed wysyłką — po „CV wysłane” trasa odmawia
    # wcześniej (409, `test_stage_cv_upload.py`), a tu sprawdzamy odmowę 422.
    await _source_cv(world, job_id=world["job_id"], stage=PipelineStage.verified)

    # W tamtej rekrutacji CV ma tylko INNA osoba.
    foreign = await _copy(app_client, app_auth_headers, world, stranger["other_job_id"])
    same = await _copy(app_client, app_auth_headers, world, world["job_id"])
    legacy = await _copy(app_client, app_auth_headers, world, legacy_job)
    nothing = await _copy(app_client, app_auth_headers, world, world["other_job_id"])

    assert [r.status_code for r in (foreign, same, legacy, nothing)] == [
        404,
        422,
        404,
        404,
    ]
    assert (await _csv(world["stage_id"])).branded_status == "none"


@pytest.mark.asyncio
async def test_stale_revision_does_not_replace_a_draft_with_a_copy(
    app_client: AsyncClient, app_auth_headers: dict
):
    world = await _seed()
    await _source_cv(world)
    payload = {
        "expected_revision": await _revision(
            app_client, app_auth_headers, world["stage_id"]
        ),
        "source_job_id": world["other_job_id"],
    }
    url = _base(world["stage_id"]) + "/select-stage-cv"

    first = await app_client.post(url, headers=app_auth_headers, json=payload)
    second = await app_client.post(url, headers=app_auth_headers, json=payload)

    assert (first.status_code, second.status_code) == (200, 409)


@pytest.mark.asyncio
async def test_uploaded_docx_becomes_a_draft_and_is_not_stored_in_candidate_files(
    app_client: AsyncClient, app_auth_headers: dict
):
    world = await _seed(with_cv_row=False)
    content = _docx()

    uploaded = await app_client.post(
        _base(world["stage_id"]) + "/upload",
        headers=app_auth_headers,
        data={"expected_revision": "0"},
        files={"file": ("C:\\Pulpit\\CV_gotowe_dla_klienta.docx", content, DOCX_MIME)},
    )

    assert uploaded.status_code == 200, uploaded.text
    body = uploaded.json()
    assert (body["status"], body["source"]) == ("draft", "document")
    assert body["origin"]["kind"] == "upload"
    assert body["origin"]["label"] == "CV_gotowe_dla_klienta.docx"
    assert MARKER in body["content_html"]
    csv = await _csv(world["stage_id"])
    assert (
        csv.branded_render_metadata["upload_sha256"]
        == hashlib.sha256(content).hexdigest()
    )
    # Plik z dysku nie staje się plikiem kandydata (ani jego „aktualnym CV”).
    async with AsyncSessionLocal() as db:
        files = await db.scalar(
            select(func.count())
            .select_from(CandidateDocument)
            .where(CandidateDocument.candidate_id == world["candidate_id"])
        )
    assert files == 1


@pytest.mark.asyncio
async def test_upload_that_is_not_word_is_empty_or_too_big_is_refused_in_polish(
    app_client: AsyncClient, app_auth_headers: dict, monkeypatch
):
    from app.services import cv_docx_import

    world = await _seed()
    url = _base(world["stage_id"]) + "/upload"

    async def _upload(content: bytes, name: str = "cv.docx"):
        return await app_client.post(
            url,
            headers=app_auth_headers,
            data={
                "expected_revision": str(
                    await _revision(app_client, app_auth_headers, world["stage_id"])
                )
            },
            files={"file": (name, content, DOCX_MIME)},
        )

    pdf = await _upload(b"%PDF-1.7 to nie jest Word", "cv.pdf")
    empty = await _upload(b"")
    monkeypatch.setattr(cv_docx_import, "MAX_BYTES", 64)
    too_big = await _upload(_docx())

    assert (pdf.status_code, empty.status_code, too_big.status_code) == (422, 422, 422)
    assert "tylko plik Word" in pdf.json()["detail"]
    assert "pusty" in empty.json()["detail"]
    assert "za duży" in too_big.json()["detail"]
    assert (await _csv(world["stage_id"])).branded_status == "none"


@pytest.mark.asyncio
async def test_account_without_candidate_write_cannot_copy_upload_or_attach_consent(
    app_client: AsyncClient,
):
    from app.core.security import create_access_token

    world = await _seed()
    await _source_cv(world)
    async with AsyncSessionLocal() as db:
        viewer = User(
            email=f"cv-copy-viewer-{uuid.uuid4().hex[:8]}@example.com",
            name="Konto bez zapisu",
            role=UserRole.user,
            roles=[UserRole.user.value],
            is_active=True,
        )
        db.add(viewer)
        await db.commit()
        headers = {
            "Authorization": f"Bearer {create_access_token(viewer.id, UserRole.user.value)}"
        }
    base = _base(world["stage_id"])

    listed = await app_client.get(base + "/sources", headers=headers)
    copied = await app_client.post(
        base + "/select-stage-cv",
        headers=headers,
        json={"expected_revision": 0, "source_job_id": world["other_job_id"]},
    )
    uploaded = await app_client.post(
        base + "/upload",
        headers=headers,
        data={"expected_revision": "0"},
        files={"file": ("cv.docx", _docx(), DOCX_MIME)},
    )
    consent = await app_client.post(
        base + "/consent", headers=headers, json={"consent_screenshot_token": "x"}
    )

    assert [r.status_code for r in (listed, copied, uploaded, consent)] == [403] * 4
    assert (await _csv(world["stage_id"])).branded_status == "none"


@pytest.mark.asyncio
async def test_same_client_copy_carries_the_consent_image(
    app_client: AsyncClient, app_auth_headers: dict, monkeypatch
):
    """Decyzja Artura 12.10.2026: zrzut zgody jedzie z CV w obrębie klienta."""
    consent_client(monkeypatch)
    world = await _seed()
    image = _png()
    sibling_job = await _job(same_client_as=world["job_id"], title="Ten sam klient")
    source = await _source_cv(world, job_id=sibling_job, branded_consent_content=image)

    listed = await app_client.get(
        _base(world["stage_id"]) + "/sources", headers=app_auth_headers
    )
    chosen = await _copy(app_client, app_auth_headers, world, sibling_job)

    assert listed.json()["items"][0]["consent_carried"] is True
    assert chosen.status_code == 200, chosen.text
    body = chosen.json()
    assert (
        body["consent_required"],
        body["consent_attached"],
        body["consent_missing"],
    ) == (True, True, False)
    csv = await _csv(world["stage_id"])
    assert bytes(csv.branded_consent_content) == image
    assert (
        csv.branded_render_metadata["consent_sha256"]
        == hashlib.sha256(image).hexdigest()
    )
    assert (
        csv.branded_render_metadata["consent_carried_from_stage_id"]
        == source["stage_id"]
    )
    preview = await app_client.post(
        _base(world["stage_id"]) + "/preview-docx",
        headers=app_auth_headers,
        json={
            "content_html": body["content_html"],
            "expected_revision": body["edit_revision"],
        },
    )
    assert preview.status_code == 200, preview.text


@pytest.mark.asyncio
async def test_other_client_copy_does_not_carry_the_consent_image(
    app_client: AsyncClient, app_auth_headers: dict, monkeypatch
):
    """Zgoda dla jednego klienta nie trafia do CV dla innego."""
    consent_client(monkeypatch)
    world = await _seed()
    await _source_cv(world, branded_consent_content=_png())

    chosen = await _copy(app_client, app_auth_headers, world, world["other_job_id"])

    assert chosen.status_code == 200, chosen.text
    body = chosen.json()
    assert (body["consent_attached"], body["consent_missing"]) == (False, True)
    csv = await _csv(world["stage_id"])
    assert csv.branded_consent_content is None
    assert "consent_carried_from_stage_id" not in csv.branded_render_metadata
    blocked = await app_client.post(
        _base(world["stage_id"]) + "/preview-docx",
        headers=app_auth_headers,
        json={
            "content_html": body["content_html"],
            "expected_revision": body["edit_revision"],
        },
    )
    assert blocked.status_code == 409, blocked.text
    assert blocked.json()["detail"]["code"] == "consent_required"


# ── Podgląd importu Worda w edytorze CV: `…/import-preview` (PR 5) ───────────

AFTER_WORD = "Dopisane w Wordzie: wdrożyła monitoring usług płatniczych"


async def _untouchable(world: dict) -> tuple:
    """Wszystko, czego podgląd importu nie może zmienić: CV etapu i jego ślady."""
    async with AsyncSessionLocal() as db:
        csv = await db.scalar(
            select(CandidateStageCV).where(
                CandidateStageCV.candidate_stage_id == world["stage_id"]
            )
        )
        if csv is None:
            return (None,)
        counts = [
            await db.scalar(select(func.count()).select_from(model).where(*where))
            for model, where in (
                (
                    Activity,
                    (
                        Activity.entity_type == "candidate_stage_cv",
                        Activity.entity_id == csv.id,
                    ),
                ),
                (
                    CvDocumentVersion,
                    (CvDocumentVersion.candidate_stage_cv_id == csv.id,),
                ),
                (
                    CandidateDocument,
                    (CandidateDocument.candidate_id == world["candidate_id"],),
                ),
            )
        ]
        return (
            csv.branded_status,
            csv.branded_draft_html,
            csv.edit_revision,
            csv.branded_version,
            csv.branded_updated_at,
            csv.branded_render_metadata,
            *counts,
        )


@pytest.mark.asyncio
async def test_import_preview_converts_the_file_and_saves_nothing(
    app_client: AsyncClient, app_auth_headers: dict
):
    """Plik poprawiony w Wordzie wraca do edytora jako treść do przyjęcia:
    szkic, rewizja, wersje, historia zdarzeń i pliki kandydata zostają."""
    world = await _seed()
    url = _base(world["stage_id"])
    drafted = await app_client.post(
        url + "/upload",
        headers=app_auth_headers,
        data={
            "expected_revision": str(
                await _revision(app_client, app_auth_headers, world["stage_id"])
            )
        },
        files={"file": ("cv.docx", _docx(), DOCX_MIME)},
    )
    assert drafted.status_code == 200, drafted.text
    before = await _untouchable(world)
    corrected = _docx(AFTER_WORD)

    preview = await app_client.post(
        url + "/import-preview",
        headers=app_auth_headers,
        files={"file": ("C:\\Pulpit\\CV_po_poprawkach.docx", corrected, DOCX_MIME)},
    )

    assert preview.status_code == 200, preview.text
    # Ta sama konwersja (z sanitizerem) co przy `…/upload`.
    expected = docx_to_editor_html(corrected)
    assert preview.json() == {
        "content_html": expected.html,
        "filename": "CV_po_poprawkach.docx",
        "b2b_template": expected.b2b_template,
    }
    assert AFTER_WORD in preview.json()["content_html"]
    assert await _untouchable(world) == before
    current = (await app_client.get(url, headers=app_auth_headers)).json()
    assert current["edit_revision"] == drafted.json()["edit_revision"]
    assert MARKER in current["content_html"]
    assert AFTER_WORD not in current["content_html"]

    # Etap bez wiersza CV (import Traffita): podgląd działa i wiersza nie zakłada.
    bare = await _seed(with_cv_row=False)
    on_bare = await app_client.post(
        _base(bare["stage_id"]) + "/import-preview",
        headers=app_auth_headers,
        files={"file": ("cv.docx", corrected, DOCX_MIME)},
    )
    assert on_bare.status_code == 200, on_bare.text
    assert await _csv(bare["stage_id"]) is None


@pytest.mark.asyncio
async def test_import_preview_refuses_bad_files_in_polish_like_the_upload(
    app_client: AsyncClient, app_auth_headers: dict, monkeypatch
):
    from app.api import cv_editor_import
    from app.services import cv_docx_import

    world = await _seed()
    url = _base(world["stage_id"]) + "/import-preview"
    before = await _untouchable(world)

    async def _preview(content: bytes, name: str = "cv.docx"):
        return await app_client.post(
            url, headers=app_auth_headers, files={"file": (name, content, DOCX_MIME)}
        )

    pdf = await _preview(b"%PDF-1.7 to nie jest Word", "cv.pdf")
    empty = await _preview(b"")
    no_file = await app_client.post(url, headers=app_auth_headers)
    # Dłuższej treści edytor nie mógłby zapisać (limit `PATCH …/cv/branded`).
    monkeypatch.setattr(cv_editor_import, "CV_CONTENT_HTML_MAX", 20)
    too_long = await _preview(_docx())
    monkeypatch.setattr(cv_docx_import, "MAX_BYTES", 64)
    too_big = await _preview(_docx())

    refusals = (pdf, empty, no_file, too_long, too_big)
    assert [response.status_code for response in refusals] == [422] * 5
    assert "tylko plik Word" in pdf.json()["detail"]
    assert "pusty" in empty.json()["detail"]
    assert "za długa" in too_long.json()["detail"]
    assert "za duży" in too_big.json()["detail"]
    assert await _untouchable(world) == before


@pytest.mark.asyncio
async def test_import_preview_has_the_gates_of_the_upload(
    app_client: AsyncClient, app_auth_headers: dict
):
    from app.core.security import create_access_token
    from tests.test_board_tasks import _login, _seed_user

    world = await _seed()
    url = _base(world["stage_id"])
    async with AsyncSessionLocal() as db:
        viewer = User(
            email=f"cv-import-viewer-{uuid.uuid4().hex[:8]}@example.com",
            name="Konto bez zapisu",
            role=UserRole.user,
            roles=[UserRole.user.value],
            is_active=True,
        )
        db.add(viewer)
        await db.commit()
        viewer_headers = {
            "Authorization": f"Bearer {create_access_token(viewer.id, UserRole.user.value)}"
        }
    _, outsider_credentials = await _seed_user(UserRole.recruiter)
    outsider = await _login(app_client, outsider_credentials)

    def files() -> dict:
        return {"file": ("cv.docx", _docx(), DOCX_MIME)}

    anonymous = await app_client.post(url + "/import-preview", files=files())
    refused = await app_client.post(
        url + "/import-preview", headers=viewer_headers, files=files()
    )
    unknown = await app_client.post(
        _base(2_000_000_000) + "/import-preview",
        headers=app_auth_headers,
        files=files(),
    )
    # Rekruter spoza zespołu tej rekrutacji dostaje to samo co przy wgraniu
    # pliku — obie trasy pytają o zespół tę samą funkcję.
    outsider_preview = await app_client.post(
        url + "/import-preview", headers=outsider, files=files()
    )
    outsider_upload = await app_client.post(
        url + "/upload",
        headers=outsider,
        data={
            "expected_revision": str(
                await _revision(app_client, app_auth_headers, world["stage_id"])
            )
        },
        files=files(),
    )

    assert anonymous.status_code in (401, 403)
    assert refused.status_code == 403
    assert unknown.status_code == 404
    assert outsider_upload.status_code in (200, 403), outsider_upload.text
    assert outsider_preview.status_code == outsider_upload.status_code
