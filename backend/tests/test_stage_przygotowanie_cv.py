"""Kolumna `verified` nazywa się „Przygotowanie CV” (27.11.2026, migracja 0798).

Kod etapu się nie zmienia; nazwa w ludzkich napisach backendu idzie za
kolumną Tablicy, a szablon z Traffita z etapem „Zweryfikowany” dalej trafia
na etap `verified` szablonu rekrutacji.
"""

import re
from pathlib import Path
from types import SimpleNamespace

from app.models.recruitment_pipeline import PipelineStage
from app.schemas.pipeline import STAGE_LABELS
from app.services import board_stage_badges as badges
from app.services.move_requirements import COLUMN_LABEL

ROOT = Path(__file__).resolve().parents[1]
NEW_NAME = "Przygotowanie CV"


def _squash(text: str) -> str:
    return re.sub(r"\s+", " ", text)


def test_column_and_stage_labels_say_przygotowanie_cv() -> None:
    assert COLUMN_LABEL["verified"] == NEW_NAME
    assert STAGE_LABELS[PipelineStage.verified] == NEW_NAME
    # QC CV zostaje przy swojej nazwie.
    assert COLUMN_LABEL["cv_qc"] == "QC CV"


def test_migration_renames_only_nexus_templates_once_and_is_reversible() -> None:
    migration = (ROOT / "alembic/versions/0798_stage_przygotowanie_cv.py").read_text()
    squashed = _squash(migration)
    assert 'revision = "0798_stage_przygotowanie_cv"' in migration
    assert 'down_revision = "0797_verification_counts_from_qc_cv"' in migration
    assert "UPDATE pipeline_stage_defs SET name = 'Przygotowanie CV'" in squashed
    assert "WHERE name = 'Zweryfikowany'" in squashed
    assert "<> 'traffit'" in squashed
    assert "x.name = 'Przygotowanie CV'" in squashed
    assert "def downgrade" in migration
    assert "UPDATE pipeline_stage_defs SET name = 'Zweryfikowany'" in squashed


def test_migration_is_mirrored_in_entrypoint() -> None:
    entry = _squash((ROOT / "entrypoint.sh").read_text())
    migration = _squash(
        (ROOT / "alembic/versions/0798_stage_przygotowanie_cv.py").read_text()
    )
    for fragment in (
        "0798_stage_renamed_przygotowanie_cv",
        "UPDATE pipeline_stage_defs SET name = 'Przygotowanie CV', updated_at = now() ",
        "WHERE name = 'Zweryfikowany' ",
        "WHERE coalesce(external_source, 'manual') <> 'traffit') ",
        "AND x.name = 'Przygotowanie CV') ",
        "AND EXISTS (SELECT 1 FROM marker)",
    ):
        assert fragment in migration, fragment
        assert fragment in entry, fragment
    # Rename stoi za blokiem 0361 (ta sama lista instrukcji, ta sama kolejność).
    assert entry.index("0361_dz_stage_renamed_qc_cv") < entry.index(
        "0798_stage_renamed_przygotowanie_cv"
    )


def test_new_name_is_an_ordinary_stage_not_a_badge() -> None:
    # „Przygotowanie” nie może złapać się na „prep”/„przygotowany do spotkania”
    # (odznaka rozmowy u klienta) ani na QC.
    assert badges.stage_badge_kind(NEW_NAME) is None
    assert badges.board_column_for(NEW_NAME, "verified") == "verified"


def test_traffit_zweryfikowany_still_lands_on_the_renamed_stage() -> None:
    def sd(id_: int, name: str, enum: str | None) -> SimpleNamespace:
        return SimpleNamespace(
            id=id_, name=name, legacy_enum_value=enum, is_terminal=False
        )

    default_b2b = [
        sd(3, "Screening", "screening"),
        sd(13, NEW_NAME, "verified"),
        sd(823, "QC CV", "interview"),
    ]
    for traffit_name in ("Zweryfikowany", "Kandydat Zweryfikowany"):
        target = badges.foreign_stage_target(traffit_name, "verified", default_b2b)
        assert target is not None and target.id == 13, traffit_name
