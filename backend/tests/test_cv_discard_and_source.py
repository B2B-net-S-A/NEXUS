"""„Odrzuć to CV” i „Powstało z: <plik>” (21.10.2026) — prawdziwy Postgres.

Zgłoszenie zespołu: CV do klienta powstało z błędnego pliku i nie dało się
go usunąć. Kontrakty:

- „Odrzuć to CV” wraca do stanu „brak”, ale nic nie kasuje: treść idzie do
  migawki szkicu (`replaced`), zostaje ślad w historii;
- nieaktualna wersja (inna rewizja) i etap bez CV → 409; od „CV wysłane” →
  409 `client_cv_locked_after_send`;
- generacja zapisuje plik źródłowy, a `…/cv/ai-sources` mówi, czy to kopia
  „Oryginał CV” rekrutacji.

Dane fikcyjne.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.core.database import AsyncSessionLocal
from app.models.activity import Activity
from app.models.candidate_stage_cv import CandidateStageCV
from app.models.cv_stage_draft_snapshot import CvStageDraftSnapshot
from tests.test_stage_cv_upload import _client_world


async def _with_draft(stage_id: int) -> int:
    async with AsyncSessionLocal() as db:
        row = await db.scalar(
            select(CandidateStageCV).where(
                CandidateStageCV.candidate_stage_id == stage_id
            )
        )
        row.branded_status = "draft"
        row.branded_draft_html = "<p>CV z błędnego pliku (fikcyjne).</p>"
        row.edit_revision = 3
        await db.commit()
        return row.id


@pytest.mark.asyncio
async def test_discard_returns_card_to_none_and_keeps_a_snapshot(
    app_client: AsyncClient, app_auth_headers: dict[str, str]
) -> None:
    world = await _client_world(stage="verified")
    csv_id = await _with_draft(world["stage_id"])
    url = f"/api/candidates/stages/{world['stage_id']}/cv/branded/discard"

    stale = await app_client.post(
        url, headers=app_auth_headers, json={"expected_revision": 2}
    )
    assert stale.status_code == 409, stale.text

    res = await app_client.post(
        url, headers=app_auth_headers, json={"expected_revision": 3}
    )
    assert res.status_code == 200, res.text
    assert res.json()["status"] == "none"
    async with AsyncSessionLocal() as db:
        row = await db.get(CandidateStageCV, csv_id)
        assert row.branded_status == "none"
        assert row.branded_draft_html is None
        [snapshot] = (
            await db.scalars(
                select(CvStageDraftSnapshot).where(
                    CvStageDraftSnapshot.candidate_stage_cv_id == csv_id
                )
            )
        ).all()
        assert snapshot.reason == "replaced"
        assert "błędnego pliku" in snapshot.content_html
        actions = (
            await db.scalars(
                select(Activity.action).where(
                    Activity.entity_type == "candidate_stage_cv",
                    Activity.entity_id == csv_id,
                )
            )
        ).all()
        assert "branded_cv_discarded" in actions

    again = await app_client.post(
        url,
        headers=app_auth_headers,
        json={"expected_revision": res.json()["edit_revision"]},
    )
    assert again.status_code == 409, again.text


@pytest.mark.asyncio
async def test_discard_refuses_after_cv_sent(
    app_client: AsyncClient, app_auth_headers: dict[str, str]
) -> None:
    world = await _client_world(stage="cv_sent")
    await _with_draft(world["stage_id"])
    res = await app_client.post(
        f"/api/candidates/stages/{world['stage_id']}/cv/branded/discard",
        headers=app_auth_headers,
        json={"expected_revision": 3},
    )
    assert res.status_code == 409, res.text
    assert res.json()["detail"]["code"] == "client_cv_locked_after_send"


def test_generation_records_its_source_file():
    from app.api.cv_generator_b2b import _record_ai_sources

    source = SimpleNamespace(ai_sources=(), cv_document_id=17, cv_filename="Ewa_CV.pdf")
    result = SimpleNamespace(render_payload={"name": "Ewa Fikcyjna"})
    _record_ai_sources(source, result)
    assert result.render_payload["source_cv"] == {
        "document_id": 17,
        "filename": "Ewa_CV.pdf",
    }
    assert "ai_sources" not in result.render_payload


@pytest.mark.asyncio
async def test_ai_sources_says_which_file_the_current_cv_came_from(
    app_client: AsyncClient, app_auth_headers: dict[str, str]
) -> None:
    from app.models.candidate_document import CandidateDocument
    from app.models.cv_generated_document import CvGeneratedDocument

    world = await _client_world(stage="verified")
    async with AsyncSessionLocal() as db:
        original = await db.scalar(
            select(CandidateDocument).where(
                CandidateDocument.candidate_id == world["candidate_id"]
            )
        )
        row = await db.scalar(
            select(CandidateStageCV).where(
                CandidateStageCV.candidate_stage_id == world["stage_id"]
            )
        )
        # Kopia etapu i plik profilu to ten sam plik — ten sam SHA. Bez odczytu
        # `file_content` (kolumna `deferred` — doczytanie w async = MissingGreenlet).
        sha = "e" * 64
        original.content_sha256 = sha
        row.original_cv_sha256 = sha
        original_id = original.id
        original_filename = original.filename
        generated = CvGeneratedDocument(
            candidate_id=world["candidate_id"],
            job_id=world["job_id"],
            candidate_name="Ewa Fikcyjna",
            language="pl",
            mode="new",
            content_mode="polished",
            filename="cv.docx",
            status="ready",
            render_payload={
                "name": "Ewa Fikcyjna",
                "source_cv": {
                    "document_id": original_id,
                    "filename": original_filename,
                },
            },
        )
        db.add(generated)
        await db.flush()
        row.generated_document_id = generated.id
        row.branded_status = "draft"
        row.branded_draft_html = "<p>CV</p>"
        await db.commit()

    res = await app_client.get(
        f"/api/candidates/stages/{world['stage_id']}/cv/ai-sources",
        headers=app_auth_headers,
    )
    assert res.status_code == 200, res.text
    used = res.json()["last_source_cv"]
    assert used["document_id"] == original_id
    assert used["stage_original"] is True
    assert used["removed"] is False


@pytest.mark.asyncio
async def test_discarded_cv_is_not_the_pair_cv_anywhere(
    app_client: AsyncClient, app_auth_headers: dict[str, str]
) -> None:
    """Audyt 22.10 (F64): po „Odrzuć to CV” dokument generatora zostaje
    w plikach, ale nie jest już CV pary — ani dla karty („Użyj tej wersji”),
    ani dla wymagań ruchu i kolejek DL/Cpro, ani dla QC CV."""
    from app.models.cv_generated_document import CvGeneratedDocument
    from app.services.dz_review import _generated_cv
    from app.services.move_requirements import company_cv_refs

    world = await _client_world(stage="verified")
    pair = (world["candidate_id"], world["job_id"])

    def _doc(name: str) -> CvGeneratedDocument:
        return CvGeneratedDocument(
            candidate_id=world["candidate_id"],
            job_id=world["job_id"],
            candidate_name="Ewa Fikcyjna",
            language="pl",
            mode="new",
            content_mode="polished",
            filename=name,
            status="ready",
            render_payload={"name": "Ewa Fikcyjna"},
        )

    async with AsyncSessionLocal() as db:
        older, attached = _doc("starsze.docx"), _doc("z-blednego-pliku.docx")
        db.add_all([older, attached])
        await db.flush()
        row = await db.scalar(
            select(CandidateStageCV).where(
                CandidateStageCV.candidate_stage_id == world["stage_id"]
            )
        )
        row.generated_document_id = attached.id
        row.branded_status = "draft"
        row.branded_draft_html = "<p>CV z błędnego pliku (fikcyjne).</p>"
        row.edit_revision = 3
        attached_id = attached.id
        await db.commit()

    res = await app_client.post(
        f"/api/candidates/stages/{world['stage_id']}/cv/branded/discard",
        headers=app_auth_headers,
        json={"expected_revision": 3},
    )
    assert res.status_code == 200, res.text

    listed = await app_client.get(
        "/api/cv-generator/generated",
        headers=app_auth_headers,
        params={"candidate_id": pair[0], "job_id": pair[1]},
    )
    assert listed.status_code == 200, listed.text
    rows = {r["id"]: r for r in listed.json()}
    assert attached_id in rows, "dokument zostaje w plikach kandydata"
    assert all(r["discarded"] for r in rows.values())

    async with AsyncSessionLocal() as db:
        assert pair not in await company_cv_refs(db, [pair])
        assert await _generated_cv(db, *pair) is None

        fresh = _doc("nowe.docx")
        db.add(fresh)
        await db.commit()
        fresh_id = fresh.id

    async with AsyncSessionLocal() as db:
        refs = await company_cv_refs(db, [pair])
        assert refs[pair]["generated_document_id"] == fresh_id
        assert (await _generated_cv(db, *pair))["generated_document_id"] == fresh_id


def test_discarded_auto_cv_does_not_wait_for_review():
    """Audyt 22.10 (F64, dopięcie): odrzucone auto-CV nie świeci na tablicy
    jako „gotowe do przejrzenia” ani nie czeka w „CV do sprawdzenia” —
    `needs_review_clause` (jedna definicja dla tablicy, listy generatora
    i tematu CV) pomija generację ze znacznikiem `discarded_at`."""
    from sqlalchemy.dialects import postgresql

    from app.services.cv_auto_review import needs_review_clause

    compiled = needs_review_clause().compile(dialect=postgresql.dialect())
    assert "render_payload" in str(compiled), str(compiled)
    assert "discarded_at" in compiled.params.values(), compiled.params


def test_return_to_verified_does_not_reattach_a_discarded_cv():
    """Audyt 22.10 (F64, dopięcie): powrót karty na „Zweryfikowany” podpinał
    wcześniejszą gotową generację automatu — także tę, którą ktoś odrzucił
    w karcie „CV do klienta”. Zapytanie o wcześniejszą generację pomija
    odrzucone (zachowanie na bazie: `test_cv_auto_generate.py`)."""
    import inspect

    from app.services import cv_auto_generate

    source = inspect.getsource(cv_auto_generate._enqueue)
    earlier = source[
        source.index("earlier = (") : source.index("if earlier is not None")
    ]
    assert "not_discarded_clause()" in earlier, earlier
