"""Etap „Ogłoszenia" (`posting`, migracja 0317) — kontrakty.

1. `posting` jest PIERWSZY w kolejności kanbana, wewnętrzny, z polską etykietą
   i mapowaniem semantycznym (test_workflow_registry pilnuje kompletności).
2. Bulk-add bez wskazania etapu NADAL trafia do „Nowi", nie do „Ogłoszeń" —
   inaczej każde ręczne dodanie lądowałoby w poczekalni auto-matchu.
3. `initial_stage_legacy="posting"` (integracje) rozwiązuje się do kolumny
   „Ogłoszenia" szablonu; nieznany legacy → domyślne zachowanie.
4. `posting` NIE liczy się do alertów „kandydat utknął".
5. Lustro w `entrypoint.sh` zawiera dokładnie tę samą wstawkę co migracja.
6. Rekrutacja BEZ szablonu (legacy kanban z `STAGE_ORDER`): integracja z
   `initial_stage_legacy="posting"` dostaje enum `posting`; ręczne dodanie
   i każdy inny legacy nadal dają `new`.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from sqlalchemy import select

from app.core.database import AsyncSessionLocal
from app.models.pipeline_template import PipelineStageDef, PipelineTemplate
from app.models.recruitment_pipeline import (
    STAGE_CATEGORY,
    STAGE_ORDER,
    PipelineStage,
    StageCategory,
)
from app.schemas.pipeline import STAGE_LABELS
from app.services.notification_triggers import _NON_TERMINAL_STAGES
from app.services.semantic_states import LEGACY_TO_SEMANTIC

_BACKEND = Path(__file__).resolve().parents[1]


def test_posting_is_first_internal_stage_with_label_and_semantics():
    assert STAGE_ORDER[0] is PipelineStage.posting
    assert STAGE_ORDER[1] is PipelineStage.new
    assert STAGE_CATEGORY[PipelineStage.posting] is StageCategory.internal
    assert STAGE_LABELS[PipelineStage.posting] == "Ogłoszenia"
    assert LEGACY_TO_SEMANTIC["posting"] == "identified"


def test_legacy_job_without_template_gets_posting_only_when_asked():
    from types import SimpleNamespace

    from app.api.proposals_bulk import _legacy_enum_for

    posting, new = PipelineStage.posting, PipelineStage.new
    assert _legacy_enum_for(None, "posting", has_template=False) is posting
    assert _legacy_enum_for(None, None, has_template=False) is new
    assert _legacy_enum_for(None, "screening", has_template=False) is new
    # Z szablonem o etapie decyduje kolumna, nie legacy z ciała żądania.
    assert _legacy_enum_for(None, "posting", has_template=True) is new
    new_def = SimpleNamespace(legacy_enum_value="new")
    assert _legacy_enum_for(new_def, "posting", has_template=True) is new
    posting_def = SimpleNamespace(legacy_enum_value="posting")
    assert _legacy_enum_for(posting_def, None, has_template=True) is posting
    bogus_def = SimpleNamespace(legacy_enum_value="bogus")
    assert _legacy_enum_for(bogus_def, None, has_template=True) is new


def test_posting_is_excluded_from_stuck_candidate_alerts():
    assert PipelineStage.posting not in _NON_TERMINAL_STAGES
    assert PipelineStage.new in _NON_TERMINAL_STAGES


def test_entrypoint_mirror_matches_migration():
    migration = (
        _BACKEND / "alembic" / "versions" / "0317_pipeline_stage_posting.py"
    ).read_text(encoding="utf-8")
    entrypoint = (_BACKEND / "entrypoint.sh").read_text(encoding="utf-8")
    assert "ALTER TYPE pipelinestage ADD VALUE IF NOT EXISTS 'posting'" in entrypoint
    body = re.search(r"INSERT_SQL = f\"\"\"(.*?)\"\"\"", migration, re.S).group(1)
    body = body.replace("{STAGE_NAME}", "Ogłoszenia")
    normalized = re.sub(r"\s+", " ", body).strip()
    entry_norm = re.sub(r"\s+", " ", entrypoint)
    assert normalized in entry_norm, (
        "Lustro w entrypoint.sh rozjechało się z migracją 0317"
    )


async def _template_with_posting(name: str) -> tuple[int, int, int]:
    """Szablon: Ogłoszenia(0) → Nowi(1) → Odrzucony(terminal). Zwraca (tpl, posting, new)."""
    async with AsyncSessionLocal() as db:
        tpl = PipelineTemplate(name=name, description="test posting", is_default=False)
        db.add(tpl)
        await db.flush()
        posting = PipelineStageDef(
            template_id=tpl.id,
            name="Ogłoszenia",
            order=0,
            category="internal",
            is_terminal=False,
            legacy_enum_value="posting",
        )
        new = PipelineStageDef(
            template_id=tpl.id,
            name="Nowi / Analiza CV",
            order=1,
            category="internal",
            is_terminal=False,
            legacy_enum_value="new",
        )
        rejected = PipelineStageDef(
            template_id=tpl.id,
            name="Odrzucony",
            order=2,
            category="terminal",
            is_terminal=True,
            terminal_type="rejected",
            legacy_enum_value="rejected",
        )
        db.add_all([posting, new, rejected])
        await db.commit()
        return tpl.id, posting.id, new.id


@pytest.mark.asyncio
async def test_default_initial_stage_skips_posting():
    from types import SimpleNamespace

    from app.api.proposals_bulk import _resolve_initial_stage

    import uuid

    tpl_id, posting_id, new_id = await _template_with_posting(
        f"posting-{uuid.uuid4().hex[:8]}"
    )
    job = SimpleNamespace(pipeline_template_id=tpl_id)
    async with AsyncSessionLocal() as db:
        default = await _resolve_initial_stage(db, job, None)
        assert default is not None and default.id == new_id, "ręczne dodanie → Nowi"
        via_legacy = await _resolve_initial_stage(db, job, None, "posting")
        assert via_legacy is not None and via_legacy.id == posting_id
        unknown = await _resolve_initial_stage(db, job, None, "no_such_stage")
        assert unknown is not None and unknown.id == new_id
        explicit = await _resolve_initial_stage(db, job, posting_id)
        assert explicit is not None and explicit.id == posting_id
        # sprzątanie
        for sd in (
            await db.execute(
                select(PipelineStageDef).where(PipelineStageDef.template_id == tpl_id)
            )
        ).scalars():
            await db.delete(sd)
        tpl = await db.get(PipelineTemplate, tpl_id)
        if tpl is not None:
            await db.delete(tpl)
        await db.commit()
