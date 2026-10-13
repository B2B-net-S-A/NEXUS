"""CV w procesie (PR 4, 13.10.2026): źródła w migawce, QC po podpięciu.

Dane fikcyjne. Trasa `…/cv/ai-sources` — test z bazą niżej (CI).
"""

# ruff: noqa: F811  (fixture `pv_client` importowana z sąsiedniego pliku)
import uuid
from dataclasses import replace
from types import SimpleNamespace

import pytest
from httpx import AsyncClient

from app.core.database import AsyncSessionLocal
from app.services.cv_generator_b2b import job_snapshot
from app.services.cv_generator_b2b.standalone_service import CandidateGenerationSource
from tests.test_cv_auto_generate import _headers, _world
from tests.test_pending_gate_removed import pv_client  # noqa: F401


def _source(**extra) -> CandidateGenerationSource:
    base = dict(
        cv_bytes=b"cv",
        cv_filename="cv.pdf",
        champion_json="{}",
        has_champion=False,
        screening_notes_text="",
        source_warnings=(),
        fallback_name=None,
        job_id=1,
        job_title="Data Engineer",
        client_content_mode_cap=None,
        candidate_id=2,
        stage_id=3,
        cv_document_id=4,
    )
    base.update(extra)
    return CandidateGenerationSource(**base)


def test_old_job_snapshot_without_sources_still_decodes():
    encoded = job_snapshot._encode(_source())
    encoded["value"].pop("ai_sources")
    decoded = job_snapshot._decode(encoded)
    assert decoded.ai_sources == ()
    chosen = replace(_source(), ai_sources=(("answers", True), ("transcripts", False)))
    assert job_snapshot._decode(job_snapshot._encode(chosen)).ai_sources == (
        ("answers", True),
        ("transcripts", False),
    )


def test_generated_cv_remembers_its_sources_for_the_card():
    from app.api.cv_generator_b2b import _record_ai_sources

    result = SimpleNamespace(render_payload={"name": "Anna Testowa"})
    _record_ai_sources(_source(ai_sources=(("notes", False),)), result)
    assert result.render_payload["ai_sources"] == {"notes": False}
    untouched = SimpleNamespace(render_payload={"name": "Anna Testowa"})
    _record_ai_sources(_source(), untouched)
    assert "ai_sources" not in untouched.render_payload


@pytest.mark.asyncio
async def test_qc_runs_right_after_the_cv_is_attached(monkeypatch: pytest.MonkeyPatch):
    from app.core.config import settings
    from app.services import cv_auto_generate, cv_qc

    calls: list[tuple] = []

    async def run_after_move(stage_id, user_id):
        calls.append((stage_id, user_id))

    monkeypatch.setattr(cv_qc, "run_after_move", run_after_move)
    monkeypatch.setattr(settings, "CV_QC_GATE_ENABLED", True)
    await cv_auto_generate.qc_after_attach(7, 8)
    monkeypatch.setattr(settings, "CV_QC_GATE_ENABLED", False)
    await cv_auto_generate.qc_after_attach(9, 10)
    assert calls == [(7, 8)]


@pytest.mark.asyncio
async def test_ai_sources_counts_material_without_content(pv_client: AsyncClient):
    from app.models.note import Note
    from app.models.recruitment_pipeline import CandidateStage
    from app.services import note_kinds

    world = await _world()
    tag = uuid.uuid4().hex[:6]
    async with AsyncSessionLocal() as db:
        stage = await db.get(CandidateStage, world["stage_id"])
        stage.screening_answers = {
            "answers": [
                {"question_id": "q1", "response": "Kafka w Acme Bank."},
                {"question_id": "q2", "response": "Nie znam Icebergu."},
            ]
        }
        db.add_all(
            [
                Note(
                    candidate_id=world["candidate_id"],
                    job_id=world["job_id"],
                    content=f"Zna Grafanę {tag}.",
                ),
                Note(
                    candidate_id=world["candidate_id"],
                    job_id=world["job_id"],
                    content="Stawka 150 PLN/h netto.",
                ),
                Note(
                    candidate_id=world["candidate_id"],
                    job_id=world["job_id"],
                    content="Prep: tematy na następny prep.",
                    kind=note_kinds.PREP_SUMMARY,
                ),
            ]
        )
        await db.commit()
    response = await pv_client.get(
        f"/api/candidates/stages/{world['stage_id']}/cv/ai-sources",
        headers=_headers(world["user_id"]),
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["answers"] == {"count": 2, "excluded": 1}
    assert body["notes"]["count"] == 2
    assert body["rate_notes"]["count"] == 1
    assert body["prep"]["count"] == 1
    assert body["original_cv"]["filename"] == "cv.pdf"
    assert body["defaults"] == {
        "answers": True,
        "notes": True,
        "transcripts": False,
        "prep": False,
    }
    assert "Grafan" not in response.text
