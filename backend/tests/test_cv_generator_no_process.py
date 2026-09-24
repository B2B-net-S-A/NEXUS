"""Generator v3: CV dla kandydata BEZ procesu („inny klient") — prawdziwy Postgres.

Kontrakty:

- ``POST /generate`` bez ``stage_id`` wymaga klienta (422 „Wybierz klienta"),
  nieistniejący klient = 404;
- wiersz nie ma rekrutacji ani etapu, a zadanie nie próbuje podpinać szkicu;
- źródło bez etapu: Champion wyłącznie z ``champion_profile``, tytuł roli =
  stanowisko z formularza, notatki WYŁĄCZNIE bez rekrutacji (notatka z procesu
  innego klienta niesie jego stawki i czerwone flagi);
- ``champion_profile`` z podglądu ma pierwszeństwo przed Championem rekrutacji;
- ręczna generacja z etapem zapisuje etap na wierszu i każe podpiąć szkic.
"""

# ruff: noqa: F811  (fixture `pv_client` importowana z sąsiedniego pliku)
from __future__ import annotations

import json

import pytest
from httpx import AsyncClient

import app.models  # noqa: F401
from app.api import cv_generator_b2b as api
from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.models.candidate_document import CandidateDocument
from app.models.cv_generated_document import CvGeneratedDocument
from app.models.job import Job
from app.models.note import Note
from app.services import object_storage
from app.services.cv_generator_b2b.standalone_service import (
    load_candidate_generation_source,
)
from tests.test_cv_auto_generate import _headers, _world
from tests.test_cv_auto_generate_central_policies import (
    _cv_document_id,
    _docx,
    _documents,
    _stub_generation,
)
from tests.test_pending_gate_removed import pv_client  # noqa: F401


def _spy_loader(monkeypatch, world: dict) -> list[dict]:
    """Zapisz argumenty loadera źródła (i tak podstawionego przez stub)."""
    calls: list[dict] = []
    stubbed = api.load_candidate_generation_source

    async def _load(db, **kwargs):
        calls.append(kwargs)
        source = await stubbed(db, **kwargs)
        from dataclasses import replace

        return replace(
            source,
            job_id=None if kwargs["stage_id"] is None else source.job_id,
            stage_id=kwargs["stage_id"],
            client_id=kwargs.get("client_id") or source.client_id,
            # Jak prawdziwy loader: podgląd Championa czyni źródło „z Championem".
            has_champion=bool(kwargs.get("champion_profile")) or source.has_champion,
        )

    monkeypatch.setattr(api, "load_candidate_generation_source", _load)
    return calls


async def _post(client: AsyncClient, world: dict, **payload):
    return await client.post(
        "/api/cv-generator/generate",
        headers=_headers(world["user_id"]),
        json={
            "candidate_id": world["candidate_id"],
            "cv_document_id": await _cv_document_id(world),
            **payload,
        },
    )


@pytest.mark.asyncio
async def test_generation_without_process_requires_a_client(
    pv_client: AsyncClient, monkeypatch
):
    monkeypatch.setattr(api.limiter, "enabled", False)
    world = await _world()
    seen = _stub_generation(monkeypatch, world)

    missing = await _post(pv_client, world)
    assert missing.status_code == 422, missing.text
    assert "Wybierz klienta" in missing.json()["detail"]

    unknown = await _post(pv_client, world, client_id=987_654_321)
    assert unknown.status_code == 404, unknown.text
    assert seen["charges"] == [] and seen["persisted"] == []
    assert await _documents(world) == []


@pytest.mark.asyncio
async def test_generation_without_process_has_no_recruitment_and_no_attach(
    pv_client: AsyncClient, monkeypatch
):
    monkeypatch.setattr(api.limiter, "enabled", False)
    world = await _world()
    seen = _stub_generation(monkeypatch, world)
    calls = _spy_loader(monkeypatch, world)

    response = await _post(
        pv_client, world, client_id=world["client_id"], position="Analityk danych"
    )
    assert response.status_code == 202, response.text

    [row] = await _documents(world)
    assert (row.job_id, row.stage_id, row.client_id) == (
        None,
        None,
        world["client_id"],
    )
    [call] = calls
    assert call["stage_id"] is None
    assert call["client_id"] == world["client_id"]
    assert call["position"] == "Analityk danych"
    [job] = seen["persisted"]
    assert job["inputs"]["stage_id"] is None
    assert "attach_stage_draft" not in job["inputs"]
    # Stanowisko z formularza idzie też jako zapas nagłówka/nazwy pliku.
    assert job["inputs"]["position_fallback"] == "Analityk danych"
    assert seen["charges"] == [world["user_id"]]


@pytest.mark.asyncio
async def test_manual_generation_with_stage_records_it_and_asks_for_attach(
    pv_client: AsyncClient, monkeypatch
):
    monkeypatch.setattr(api.limiter, "enabled", False)
    world = await _world()
    seen = _stub_generation(monkeypatch, world)

    response = await _post(pv_client, world, stage_id=world["stage_id"])
    assert response.status_code == 202, response.text
    [row] = await _documents(world)
    assert (row.origin, row.stage_id, row.source_cv_revision) == (
        "manual",
        world["stage_id"],
        None,
    )
    [job] = seen["persisted"]
    assert job["inputs"]["attach_stage_draft"] is True
    assert job["inputs"]["stage_id"] == world["stage_id"]


@pytest.mark.asyncio
async def test_preview_champion_wins_over_the_recruitment_champion(
    pv_client: AsyncClient, monkeypatch
):
    """Podgląd wgranego pliku Championa (zapis w rekrutacji się nie udał) idzie
    do generacji — tryb „Pod rekrutację" przechodzi mimo pustej rekrutacji."""
    monkeypatch.setattr(api.limiter, "enabled", False)
    monkeypatch.setattr(settings, "CV_CENTRAL_POLICIES_ENABLED", False)
    world = await _world()
    _stub_generation(monkeypatch, world)
    calls = _spy_loader(monkeypatch, world)
    profile = {"stack": {"must": ["Python", "FastAPI"], "nice": []}}

    response = await _post(
        pv_client,
        world,
        stage_id=world["stage_id"],
        content_mode="tailored",
        champion_profile=profile,
    )
    assert response.status_code == 202, response.text
    [call] = calls
    assert call["champion_profile"] is not None
    assert "Python" in json.dumps(call["champion_profile"])
    [row] = await _documents(world)
    assert row.content_mode == "tailored"

    # Bez podglądu ta sama prośba o „Pod rekrutację" kończy się 422 — rekrutacja
    # nie ma Championa (poza centralnymi regułami tryb nie schodzi sam).
    refused = await _post(
        pv_client, world, stage_id=world["stage_id"], content_mode="tailored"
    )
    assert refused.status_code == 422, refused.text


async def test_source_without_stage_reads_only_notes_outside_recruitments(
    monkeypatch,
):
    world = await _world()
    async with AsyncSessionLocal() as db:
        document = CandidateDocument(
            candidate_id=world["candidate_id"],
            filename="no-process.docx",
            storage_key=f"cv/test/no-process-{world['candidate_id']}.docx",
            is_primary=True,
        )
        db.add(document)
        db.add(
            Note(
                candidate_id=world["candidate_id"],
                content="Kandydat zna Kotlin i Spring.",
            )
        )
        db.add(
            Note(
                candidate_id=world["candidate_id"],
                job_id=world["job_id"],
                content="Stawka u klienta: TAJNE 190 zł/h",
            )
        )
        (await db.get(Job, world["job_id"])).champion_profile = {
            "stack": {"must": ["COBOL"]}
        }
        await db.commit()
        document_id = document.id

    monkeypatch.setattr(object_storage, "download_cv", lambda key: _docx())
    async with AsyncSessionLocal() as db:
        source = await load_candidate_generation_source(
            db,
            candidate_id=world["candidate_id"],
            stage_id=None,
            cv_document_id=document_id,
            position="Architekt",
            client_id=world["client_id"],
        )
    assert (source.job_id, source.stage_id, source.client_id) == (
        None,
        None,
        world["client_id"],
    )
    assert source.job_title == "Architekt"
    assert "Kotlin" in source.screening_notes_text
    assert "TAJNE" not in source.screening_notes_text
    # Champion rekrutacji NIE wchodzi do generacji bez procesu.
    assert source.has_champion is False
    assert "COBOL" not in source.champion_json
    assert source.requirements == ()

    async with AsyncSessionLocal() as db:
        with_preview = await load_candidate_generation_source(
            db,
            candidate_id=world["candidate_id"],
            stage_id=None,
            cv_document_id=document_id,
            client_id=world["client_id"],
            champion_profile={"stack": {"must": ["Rust"]}},
        )
    assert with_preview.has_champion is True
    assert "Rust" in with_preview.champion_json


async def test_preview_champion_has_priority_on_a_stage_too(monkeypatch):
    world = await _world()
    async with AsyncSessionLocal() as db:
        document = CandidateDocument(
            candidate_id=world["candidate_id"],
            filename="stage.docx",
            storage_key=f"cv/test/stage-{world['candidate_id']}.docx",
            is_primary=True,
        )
        db.add(document)
        (await db.get(Job, world["job_id"])).champion_profile = {
            "stack": {"must": ["COBOL"]}
        }
        await db.commit()
        document_id = document.id
    monkeypatch.setattr(object_storage, "download_cv", lambda key: _docx())
    async with AsyncSessionLocal() as db:
        source = await load_candidate_generation_source(
            db,
            candidate_id=world["candidate_id"],
            stage_id=world["stage_id"],
            cv_document_id=document_id,
            champion_profile={"stack": {"must": ["Rust"]}},
        )
    assert source.job_id == world["job_id"]
    assert "Rust" in source.champion_json and "COBOL" not in source.champion_json


async def test_stage_row_attach_and_stage_less_rows_share_the_list(
    pv_client: AsyncClient,
):
    """Wiersz bez procesu jest widoczny na liście autora (filtr zakresu)."""
    world = await _world()
    async with AsyncSessionLocal() as db:
        row = CvGeneratedDocument(
            candidate_id=world["candidate_id"],
            job_id=None,
            client_id=world["client_id"],
            candidate_name="Bez Procesu",
            language="pl",
            mode="new",
            content_mode="polished",
            filename="bez-procesu.docx",
            status="ready",
            render_payload={"name": "Bez Procesu"},
            created_by=world["user_id"],
        )
        db.add(row)
        await db.commit()
        row_id = row.id
    listed = await pv_client.get(
        "/api/cv-generator/generated",
        params={"mine": "true"},
        headers=_headers(world["user_id"]),
    )
    assert listed.status_code == 200, listed.text
    assert row_id in [item["id"] for item in listed.json()]


@pytest.mark.asyncio
async def test_form_notes_reach_the_source_only_without_process_and_are_not_saved(
    pv_client: AsyncClient, monkeypatch
):
    """Notatka z formularza generacji bez procesu idzie wyłącznie do TEGO CV:
    dopisana do źródła, bez nowego wiersza w `notes`. Z etapem pole nie działa
    (notatki procesu żyją w rekrutacji)."""
    from sqlalchemy import func, select

    monkeypatch.setattr(api.limiter, "enabled", False)
    world = await _world()
    _stub_generation(monkeypatch, world)
    calls = _spy_loader(monkeypatch, world)

    async def _notes() -> int:
        async with AsyncSessionLocal() as db:
            return await db.scalar(
                select(func.count(Note.id)).where(
                    Note.candidate_id == world["candidate_id"]
                )
            )

    before = await _notes()
    response = await _post(
        pv_client,
        world,
        client_id=world["client_id"],
        screening_notes="Kandydat dostępny od listopada.",
    )
    assert response.status_code == 202, response.text
    with_stage = await _post(
        pv_client,
        world,
        stage_id=world["stage_id"],
        screening_notes="To nie może trafić do źródła.",
    )
    assert with_stage.status_code == 202, with_stage.text
    no_process, stage_call = calls
    assert no_process["extra_notes"] == "Kandydat dostępny od listopada."
    assert stage_call["extra_notes"] == ""
    assert await _notes() == before


async def test_loader_prepends_the_form_note_without_a_stage(monkeypatch):
    world = await _world()
    async with AsyncSessionLocal() as db:
        document = CandidateDocument(
            candidate_id=world["candidate_id"],
            filename="notes.docx",
            storage_key=f"cv/test/notes-{world['candidate_id']}.docx",
            is_primary=True,
        )
        db.add(document)
        await db.commit()
        document_id = document.id
    monkeypatch.setattr(object_storage, "download_cv", lambda key: _docx())
    async with AsyncSessionLocal() as db:
        source = await load_candidate_generation_source(
            db,
            candidate_id=world["candidate_id"],
            stage_id=None,
            cv_document_id=document_id,
            client_id=world["client_id"],
            extra_notes="Zna Terraform.",
        )
        with_stage = await load_candidate_generation_source(
            db,
            candidate_id=world["candidate_id"],
            stage_id=world["stage_id"],
            cv_document_id=document_id,
            extra_notes="Zna Terraform.",
        )
    assert "[Notatka rekrutera do tego CV]\nZna Terraform." in (
        source.screening_notes_text
    )
    assert "Terraform" not in with_stage.screening_notes_text
