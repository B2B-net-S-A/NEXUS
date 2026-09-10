from dataclasses import FrozenInstanceError, asdict
import json
from types import SimpleNamespace

import pytest

from app.services.cv_generator_b2b import standalone_service as svc
from app.services.cv_generator_b2b.champion_builder import ChampionProfileForPrompt


@pytest.mark.asyncio
async def test_variants_reuse_bytes_and_notes_but_cannot_mutate_champion(monkeypatch):
    dto = ChampionProfileForPrompt(must_have=["Python"])
    source = svc.CandidateGenerationSource(
        cv_bytes=b"original CV",
        cv_filename="cv.pdf",
        champion_json=json.dumps(asdict(dto)),
        has_champion=True,
        screening_notes_text="Original notes",
        source_warnings=("warning",),
        fallback_name="Synthetic",
        job_id=2,
        job_title="Developer",
        client_content_mode_cap=None,
        candidate_id=3,
        stage_id=4,
        cv_document_id=5,
    )
    dto.must_have.append("Not in snapshot")
    seen = []

    def pipeline(**kwargs):
        seen.append(
            (
                kwargs["cv_bytes"],
                kwargs["screening_notes_text"],
                list(kwargs["champion_dto"].must_have),
            )
        )
        kwargs["champion_dto"].must_have.clear()
        return SimpleNamespace(warnings=[])

    monkeypatch.setattr(svc, "_run_generation_pipeline", pipeline)
    first = await svc.generate_cv_from_candidate_source(source)
    second = await svc.generate_cv_from_candidate_source(source)
    assert seen == [(b"original CV", "Original notes", ["Python"])] * 2
    assert first.warnings == second.warnings == ["warning"]
    assert first.warnings is not second.warnings
    with pytest.raises(FrozenInstanceError):
        source.screening_notes_text = "changed"
