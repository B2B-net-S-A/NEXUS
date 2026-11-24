"""Przygotowanie jako prep 0 (F3, 0773): więz ``prep_no`` w migracji, modelu i entrypoincie.

Produkcyjny alembic bywa osierocony, a ``entrypoint.sh`` jest wtedy wdrożeniem
schematu. ``CREATE TABLE prep_meetings`` w entrypoincie to lustro 0370
z ``IN (1, 2)`` (pilnuje ``test_prep_meetings_schema.py``), więc poszerzenie
musi stać w ``_CONSTRAINT_STATEMENTS``, które biegną po tworzeniu tabel.
Węższa definicja wykonana PO szerszej zwężałaby więz przy każdym wdrożeniu
(lekcja z ``ck_dl_alerts_type``, 03.09.2026) — wtedy założenie Przygotowania
kończyłoby się 500, a kandydat miałby już zaproszenie z Outlooka.
"""

from __future__ import annotations

import re
from pathlib import Path

from app.models.prep_meeting import PrepMeeting

ROOT = Path(__file__).resolve().parents[1]
ENTRYPOINT = ROOT / "entrypoint.sh"
# Po nazwie, nie po numerze: pas migracji przenumerowuje plik przy przepięciu.
MIGRATION = next((ROOT / "alembic/versions").glob("*_prep_meeting_preparation.py"))


def _squash(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def _migration_sql() -> str:
    ns: dict = {}
    source = MIGRATION.read_text(encoding="utf-8")
    exec(compile(source.replace("from alembic import op", ""), "m", "exec"), ns)
    return ns["UPGRADE_SQL"]


def _model_values() -> set[int]:
    for constraint in PrepMeeting.__table__.constraints:
        if constraint.name == "ck_prep_meetings_prep_no":
            return {int(v) for v in re.findall(r"\d+", str(constraint.sqltext))}
    raise AssertionError("model nie ma ck_prep_meetings_prep_no")


def test_model_allows_preparation_as_prep_zero() -> None:
    assert _model_values() == {0, 1, 2}


def test_migration_is_mirrored_in_constraint_statements_after_create_table() -> None:
    source = ENTRYPOINT.read_text(encoding="utf-8")
    squashed = _squash(source)
    widening = _squash(_migration_sql())
    assert widening in squashed, "brak lustra migracji Przygotowania w entrypoint.sh"
    create_at = squashed.index("CREATE TABLE IF NOT EXISTS prep_meetings (")
    constraints_at = squashed.index("_CONSTRAINT_STATEMENTS = [")
    widening_at = squashed.index(widening)
    assert create_at < constraints_at < widening_at


def test_every_entrypoint_definition_is_the_0370_mirror_or_the_model() -> None:
    source = ENTRYPOINT.read_text(encoding="utf-8")
    definitions = re.findall(
        r"ck_prep_meetings_prep_no\s+CHECK \(prep_no IN \(([^)]*)\)\)", source
    )
    # CREATE TABLE (lustro 0370) + jawne poszerzenie w `_CONSTRAINT_STATEMENTS`.
    assert len(definitions) == 2, definitions
    values = [{int(v) for v in re.findall(r"\d+", raw)} for raw in definitions]
    assert values == [{1, 2}, _model_values()]
