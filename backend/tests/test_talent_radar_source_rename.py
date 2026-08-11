"""Źródło importu nazywa się `tr_legacy`; nazwa „Talent Radar" należy do modułu.

Kolizja była realna, nie estetyczna: `/api/talent-radar/search` (moduł
wyszukiwania) sąsiaduje w routingu z `/api/admin/import-talent-radar` (import ze
starego systemu), a `external_source='talent_radar'` na kandydacie nie mówił,
o które z nich chodzi.
"""

from __future__ import annotations

from pathlib import Path

from app.services.talent_radar_importer import SOURCE_VALUE

BACKEND = Path(__file__).resolve().parents[1]


def test_importer_writes_the_new_source_value():
    assert SOURCE_VALUE == "tr_legacy"


def test_importer_has_no_hardcoded_old_value_left():
    """One constant, not six string literals scattered through the file."""
    src = (BACKEND / "app/services/talent_radar_importer.py").read_text("utf-8")
    code = "\n".join(
        line for line in src.splitlines() if not line.strip().startswith("#")
    )
    # The module docstring still explains the history; only executable
    # assignments matter here.
    assert '"external_source": "talent_radar"' not in code
    assert 'provenance="talent_radar"' not in code


def test_both_spellings_stay_accepted_for_rollback_safety():
    """Rollback here means redeploying the previous image, which still writes
    `talent_radar`. A CHECK that rejected it would turn a rollback into an
    outage, so the migration widens rather than swaps."""
    migration = (
        BACKEND / "alembic/versions/0222_rename_talent_radar_source.py"
    ).read_text("utf-8")
    for spelling in ("'talent_radar'", "'tr_legacy'"):
        assert spelling in migration

    model = (BACKEND / "app/models/candidate_language.py").read_text("utf-8")
    assert "'talent_radar'" in model and "'tr_legacy'" in model


def test_entrypoint_mirrors_the_constraint_change():
    """Prod alembic can be orphaned, so every schema change needs a mirror here
    or it silently never reaches production."""
    entry = (BACKEND / "entrypoint.sh").read_text("utf-8")
    assert "ck_candidate_languages_provenance" in entry
    assert "tr_legacy" in entry
    assert "tr_legacy_cv" in entry


def test_quarantine_reads_both_spellings():
    """Existing review rows keep the old kind until the migration rewrites them;
    a reader that knew only one spelling would drop them from the queue."""
    src = (BACKEND / "app/api/candidate_identity_quarantine.py").read_text("utf-8")
    assert "tr_legacy_cv" in src and "talent_radar_cv" in src
