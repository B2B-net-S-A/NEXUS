"""Numer zapytania w nagłówku CV z reguły klienta (0661, 07.11.2026).

Nagłówek to nazwa roli bez numeru zapytania (D2/D4). Reguła klienta może
włączyć numer: „AML Analyst (43114) – Imię Nazwisko”. Nazwa pliku zostaje
z samej roli. Kolumna ma lustro w entrypoincie (alembic na produkcji bywa
osierocony), a Nordea włącza ją przez katalog polityk centralnych.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

from app.services.cv_generator_b2b import central_policies
from app.services.cv_generator_b2b.client_rules import (
    CvRuleSnapshot,
    apply_header_reference,
    build_filename,
)
from app.services.job_working_title import cv_header_title

BACKEND = Path(__file__).resolve().parents[1]
MIGRATION = BACKEND / "alembic" / "versions" / "0661_cv_title_with_reference.py"
COLUMN_DDL = (
    "ALTER TABLE client_cv_rules ADD COLUMN IF NOT EXISTS cv_title_with_reference "
    "BOOLEAN NOT NULL DEFAULT FALSE"
)


def test_header_without_rule_stays_role_only() -> None:
    assert cv_header_title("AML Analyst", "43114", False) == "AML Analyst"


def test_header_with_rule_appends_reference() -> None:
    assert cv_header_title("AML Analyst", "43114", True) == "AML Analyst (43114)"


def test_reference_already_in_role_is_not_repeated() -> None:
    assert cv_header_title("AML Analyst (43114)", "43114", True) == "AML Analyst (43114)"
    # Granica bez liter i cyfr: „143114” to nie numer „43114”.
    assert cv_header_title("Analyst 143114", "43114", True) == "Analyst 143114 (43114)"


def test_several_references_and_missing_ones() -> None:
    assert (
        cv_header_title("Data Engineer", "42928, 42927", True)
        == "Data Engineer (42928, 42927)"
    )
    assert cv_header_title("Data Engineer 42928", "42928, 42927", True) == (
        "Data Engineer 42928 (42927)"
    )


def test_only_request_numbers_go_to_the_header() -> None:
    """Kody stanowisk i zgłoszeń D4 zdejmuje — nie wracają przez regułę."""
    assert cv_header_title("Developer", "TP#43288", True) == "Developer"
    assert cv_header_title("Developer", "RITM0553762", True) == "Developer"
    assert cv_header_title("Developer", "ZOB-3103", True) == "Developer (ZOB-3103)"
    assert cv_header_title("Developer", "43114, TP#43288", True) == "Developer (43114)"


def test_no_reference_or_no_role_changes_nothing() -> None:
    assert cv_header_title("AML Analyst", None, True) == "AML Analyst"
    assert cv_header_title("AML Analyst", "  ", True) == "AML Analyst"
    assert cv_header_title("", "43114", True) == ""


def _rule(on: bool) -> CvRuleSnapshot:
    return CvRuleSnapshot(
        filename_pattern="B2B_{STANOWISKO}_{IMIE_NAZWISKO}",
        spaces_to_underscores=False,
        cv_language=None,
        requires_en_copy=False,
        requires_rodo_consent_block=False,
        managed_policy={"key": "x"},
        title_with_reference=on,
    )


def test_generator_header_gets_reference_and_filename_does_not() -> None:
    data = {"presentation_position": "AML Analyst"}
    apply_header_reference(data, _rule(True), "43114")
    assert data["presentation_position"] == "AML Analyst (43114)"
    # Nazwa pliku liczy się z nazwy roli (pipeline podaje role_title).
    result = build_filename(_rule(True), position="AML Analyst", candidate_name="Anna Nowak")
    assert result is not None
    assert "43114" not in result.filename


def test_generator_header_untouched_when_rule_off_or_missing() -> None:
    for rule in (_rule(False), None):
        data = {"presentation_position": "AML Analyst"}
        apply_header_reference(data, rule, "43114")
        assert data["presentation_position"] == "AML Analyst"
    data: dict = {}
    apply_header_reference(data, _rule(True), "43114")
    assert "presentation_position" not in data


def test_central_recipe_carries_flag_only_for_nordea() -> None:
    nordea = next(p for p in central_policies.catalog() if p["client_id"] == 11)
    assert central_policies.recipe_for(nordea)["cv_title_with_reference"] is True
    standard = central_policies.policy_for(-1)
    assert central_policies.recipe_for(standard)["cv_title_with_reference"] is False


def test_catalog_flag_is_a_bool_where_present() -> None:
    raw = json.loads((BACKEND / "app" / "data" / "cv_policies.json").read_text())
    for entry in raw:
        if "cv_title_with_reference" in entry:
            assert isinstance(entry["cv_title_with_reference"], bool)


def _migration():
    spec = importlib.util.spec_from_file_location("m0661", MIGRATION)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_migration_chain_and_ddl() -> None:
    module = _migration()
    assert module.revision == MIGRATION.stem
    assert module.down_revision == "0660_skill_relations"
    assert module.ADD_COLUMN == COLUMN_DDL


def test_entrypoint_mirrors_migration() -> None:
    entrypoint = (BACKEND / "entrypoint.sh").read_text()
    assert COLUMN_DDL in entrypoint


def test_model_column_default_false() -> None:
    from app.models.client_cv_rule import ClientCvRule

    column = ClientCvRule.__table__.c.cv_title_with_reference
    assert column.nullable is False
    assert str(column.server_default.arg) == "false"


def test_editor_html_has_one_paragraph_per_language() -> None:
    """G4 (07.11.2026): kartka edytora jak Word — każdy język w osobnej linii."""
    from app.services.cv_generator_b2b.html_export import render_interactive_html

    html = render_interactive_html(
        {
            "language": "en",
            "candidate_name": "Anna Nowak",
            "position": "AML Analyst",
            "languages": ["English - advanced", "Russian - basic"],
        },
        [],
        document_only=True,
    )
    assert (
        '<h2 data-cv-section="languages">LANGUAGES</h2>'
        "<p>English - advanced</p><p>Russian - basic</p>"
    ) in html
    assert "English - advanced · Russian" not in html
