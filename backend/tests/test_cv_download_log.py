"""Pobranie pliku CV zostawia wpis ``cv_file_downloaded`` (D5, 12.10.2026).

Mierzymy, jak często CV wychodzi z NEXUSA do Worda. Podgląd i pobranie idą tą
samą trasą, więc wpis powstaje tylko przy ``intent=download``; zapis wpisu
nigdy nie może zatrzymać pobrania, a w szczegółach nie ma nazw plików.
"""

# ruff: noqa: F811  (fixture `pv_client` importowana z sąsiedniego pliku)
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.models.activity import Activity
from app.models.candidate_stage_cv import CandidateStageCV
from app.services.cv_download_log import ACTION, log_cv_download
from tests.test_cv_auto_generate import _headers
from tests.test_cv_consent_download_gate import ROUTE_NAMES, _pko_world, _routes
from tests.test_pending_gate_removed import pv_client  # noqa: F401


def _session(*, fail: bool = False):
    @asynccontextmanager
    async def begin_nested():
        yield
        if fail:
            raise RuntimeError("insert failed")

    return SimpleNamespace(add=Mock(), begin_nested=begin_nested)


async def _log(db, **overrides):
    values = {
        "intent": "download",
        "surface": "editor",
        "entity_type": "candidate_stage_cv",
        "entity_id": 12,
        "user": SimpleNamespace(id=7),
        "file_format": "docx",
        "state": "draft",
        "version": 3,
    }
    await log_cv_download(db, **{**values, **overrides})


async def test_download_writes_one_entry_without_file_names():
    db = _session()
    await _log(db)
    (entry,) = (call.args[0] for call in db.add.call_args_list)
    assert (entry.entity_type, entry.entity_id) == ("candidate_stage_cv", 12)
    assert (entry.action, entry.user_id) == (ACTION, 7)
    assert entry.details == {
        "format": "docx",
        "state": "draft",
        "surface": "editor",
        "version": 3,
    }


@pytest.mark.parametrize("intent", [None, "", "preview", "DOWNLOAD"])
async def test_anything_but_a_download_writes_nothing(intent):
    db = _session()
    await _log(db, intent=intent)
    db.add.assert_not_called()


@pytest.mark.parametrize("surface", [None, "", "<script>", "x" * 500])
async def test_unknown_surface_is_stored_as_other(surface):
    db = _session()
    await _log(db, surface=surface)
    assert db.add.call_args.args[0].details["surface"] == "other"


async def test_preview_does_not_even_look_at_the_user():
    # Testy tras wołają handlery wprost z atrapą użytkownika bez `id`.
    db = _session()
    await _log(db, intent=None, user=object())
    db.add.assert_not_called()


async def test_failed_write_does_not_stop_the_download(caplog):
    await _log(_session(fail=True))
    assert "cv_file_downloaded" in caplog.text


# ── trasy (baza) ────────────────────────────────────────────────────────────

FILE_ROUTES = [name for name in ROUTE_NAMES if name != "share-link"]
EXPECTED = {
    "generated-docx": ("cv_generated_document", "docx", "generated", None),
    "generated-html": ("cv_generated_document", "html", "generated", None),
    "package-approved": ("cv_generated_document", "docx", "approved", 1),
    "editor-version-docx": ("cv_generated_document", "docx", "approved", 1),
    # Świat testu ma zatwierdzoną wersję 1 i żadnego szkicu: druk oddaje ją,
    # a DOCX z treści przysłanej przez edytor jest zawsze szkicem.
    "editor-preview-docx": ("cv_generated_document", "docx", "draft", 1),
    "editor-print": ("cv_generated_document", "print", "approved", 1),
    "stage-version-docx": ("candidate_stage_cv", "docx", "approved", 1),
    "stage-preview-docx": ("candidate_stage_cv", "docx", "draft", 2),
    "stage-print": ("candidate_stage_cv", "print", "draft", 2),
}


async def _entries(user_id: int) -> list[Activity]:
    async with AsyncSessionLocal() as db:
        rows = await db.scalars(
            select(Activity).where(
                Activity.action == ACTION, Activity.user_id == user_id
            )
        )
        return list(rows)


async def _request(client: AsyncClient, world: dict, name: str, query: str = ""):
    method, url, body = _routes(world)[ROUTE_NAMES.index(name)]
    headers = _headers(world["user_id"])
    if method == "GET":
        return await client.get(url + query, headers=headers)
    return await client.post(url + query, headers=headers, json=body)


@pytest.mark.asyncio
@pytest.mark.parametrize("name", FILE_ROUTES)
async def test_route_logs_a_download_and_only_a_download(
    pv_client: AsyncClient, monkeypatch, name
):
    monkeypatch.setattr(settings, "CV_CONSENT_DOWNLOAD_GATE_ENABLED", False)
    world = await _pko_world()

    preview = await _request(pv_client, world, name)
    assert preview.status_code == 200, preview.text
    assert await _entries(world["user_id"]) == []

    download = await _request(pv_client, world, name, "?intent=download&surface=card")
    assert download.status_code == 200, download.text
    assert download.content == preview.content or name.endswith("preview-docx")
    (entry,) = await _entries(world["user_id"])
    entity_type, file_format, state, version = EXPECTED[name]
    assert entry.entity_type == entity_type
    assert entry.details == {
        "format": file_format,
        "state": state,
        "surface": "card",
        "version": version,
    }
    if entity_type == "cv_generated_document":
        assert entry.entity_id == world["generated_id"]
    else:
        async with AsyncSessionLocal() as db:
            assert entry.entity_id == await db.scalar(
                select(CandidateStageCV.id).where(
                    CandidateStageCV.candidate_stage_id == world["stage_id"]
                )
            )


@pytest.mark.asyncio
async def test_refused_download_is_not_logged(pv_client: AsyncClient, monkeypatch):
    monkeypatch.setattr(settings, "CV_CONSENT_DOWNLOAD_GATE_ENABLED", True)
    world = await _pko_world()
    response = await _request(
        pv_client, world, "stage-version-docx", "?intent=download&surface=card"
    )
    assert response.status_code == 409, response.text
    assert await _entries(world["user_id"]) == []
