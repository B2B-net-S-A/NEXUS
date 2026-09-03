"""Domyślny szablon musi mieć kolumnę dla legacy `interview`.

Bez niej karty z tego etapu nie miały gdzie się wyrenderować — 1 633 kandydatów
na 1 009 rekrutacjach (pomiar produkcyjny 2026-09-02). Migracja `0271`
wyrównuje szablon domyślny do szablonu importowanego z Traffita, który kolumnę
o TEJ SAMEJ nazwie mapuje na `interview`.

Testy sprawdzają REGUŁĘ (nazwa kolumny + `is_default`), nie identyfikatory,
i pilnują trzech zabezpieczeń: warunkowości, jedyności mapowania w obrębie
szablonu oraz tego, że lustro w `entrypoint.sh` nie rozjechało się z migracją.
"""

from __future__ import annotations

import re
import uuid
from pathlib import Path

from sqlalchemy import text


def _load_migration():
    """Wczytaj moduł migracji z pliku — `alembic/versions` nie jest pakietem."""
    import importlib.util

    path = (
        Path(__file__).resolve().parents[1]
        / "alembic"
        / "versions"
        / "0271_default_template_interview_column.py"
    )
    spec = importlib.util.spec_from_file_location("_mig_0271", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)  # type: ignore[union-attr]
    return module


UPGRADE_SQL: str = _load_migration().UPGRADE_SQL


async def _seed_template(*, is_default: bool, with_existing_interview: bool) -> dict:
    from app.core.database import AsyncSessionLocal
    from app.models.pipeline_template import (
        PipelineStageDef,
        PipelineTemplate,
        StageCategoryEnum,
    )

    tag = uuid.uuid4().hex[:8]
    async with AsyncSessionLocal() as db:
        template = PipelineTemplate(name=f"Tpl-{tag}", is_default=is_default)
        db.add(template)
        await db.commit()
        await db.refresh(template)

        target = PipelineStageDef(
            template_id=template.id,
            name="Przepuszczony przez DZ",
            order=0,
            category=StageCategoryEnum.internal,
            legacy_enum_value=None,
            is_terminal=False,
        )
        rows = [target]
        if with_existing_interview:
            rows.append(
                PipelineStageDef(
                    template_id=template.id,
                    name=f"Rozmowa techniczna {tag}",
                    order=1,
                    category=StageCategoryEnum.internal,
                    legacy_enum_value="interview",
                    is_terminal=False,
                )
            )
        db.add_all(rows)
        await db.commit()
        await db.refresh(target)
        return {"template_id": template.id, "target_id": target.id}


async def _legacy_value(stage_def_id: int) -> str | None:
    from app.core.database import AsyncSessionLocal

    async with AsyncSessionLocal() as db:
        return await db.scalar(
            text(
                "SELECT legacy_enum_value FROM pipeline_stage_defs WHERE id = :id"
            ).bindparams(id=stage_def_id)
        )


async def _run_upgrade() -> None:
    from app.core.database import AsyncSessionLocal

    async with AsyncSessionLocal() as db:
        await db.execute(text(UPGRADE_SQL))
        await db.commit()


async def test_default_template_gains_the_interview_mapping():
    world = await _seed_template(is_default=True, with_existing_interview=False)
    assert await _legacy_value(world["target_id"]) is None

    await _run_upgrade()

    assert await _legacy_value(world["target_id"]) == "interview"


async def test_non_default_template_is_left_alone():
    """Szablony importowane z Traffita mają własne mapowanie — nie dotykamy ich."""
    world = await _seed_template(is_default=False, with_existing_interview=False)

    await _run_upgrade()

    assert await _legacy_value(world["target_id"]) is None


async def test_template_that_already_maps_interview_is_left_alone():
    """Druga kolumna z tą samą wartością = karty raz tu, raz tam.

    `get_kanban` buduje `enum_to_def` jako słownik, więc przy dwóch kolumnach
    o `legacy_enum_value='interview'` wygrywa ta, którą akurat zwróci baza.
    """
    world = await _seed_template(is_default=True, with_existing_interview=True)

    await _run_upgrade()

    assert await _legacy_value(world["target_id"]) is None


async def test_rerunning_the_migration_changes_nothing():
    world = await _seed_template(is_default=True, with_existing_interview=False)

    await _run_upgrade()
    await _run_upgrade()

    assert await _legacy_value(world["target_id"]) == "interview"


def test_entrypoint_mirror_matches_the_migration():
    """Prod alembic bywa osierocony — lustro musi robić DOKŁADNIE to samo.

    Porównanie po znormalizowanych białych znakach: formatowanie może się
    różnić, semantyka nie.
    """
    entrypoint = (Path(__file__).resolve().parents[1] / "entrypoint.sh").read_text(
        encoding="utf-8"
    )

    def _norm(sql: str) -> str:
        return re.sub(r"\s+", " ", sql).strip().lower()

    mirrored = [
        _norm(block)
        for block in re.findall(
            r'"""(UPDATE pipeline_stage_defs.*?)"""', entrypoint, re.S
        )
    ]
    expected = _norm(UPGRADE_SQL)
    assert any(block == expected for block in mirrored), (
        f"Lustro w entrypoint.sh rozjechało się z migracją 0271.\nOczekiwano:\n{expected}\nZnaleziono:\n{mirrored}"
    )
