"""0330: DDL Jarvisa ma lustro w entrypoincie.

Prod alembic bywa osierocony — `entrypoint.sh` JEST wdrożeniem. Model `User`
deklaruje `jarvis_prefs`, więc brak lustra = KAŻDY odczyt użytkownika (w tym
logowanie) na produkcji pada na `UndefinedColumnError`, a w CI (gdzie działa
migracja) wszystko jest zielone. Test czyta DDL z modułu migracji.
"""

from __future__ import annotations

import importlib.util
import re
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
MIGRATION = BACKEND / "alembic" / "versions" / "0330_jarvis.py"


def _collapse(sql: str) -> str:
    return re.sub(r"\s+", " ", sql).strip()


def _migration_module():
    spec = importlib.util.spec_from_file_location("m0330", MIGRATION)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_migration_chains_after_candidate_search_notification():
    module = _migration_module()
    assert module.revision == "0330_jarvis"
    assert module.down_revision == "0329_candidate_search_completed_notif"


def _entrypoint_text() -> str:
    # Sąsiednie literały Pythona („…a " "b…”) skleja interpreter — tu też,
    # inaczej indeks rozbity na dwie linie wyglądałby na brak lustra.
    raw = (BACKEND / "entrypoint.sh").read_text()
    return _collapse(re.sub(r'"\s*\n\s*"', "", raw))


def test_every_ddl_statement_is_mirrored_in_entrypoint():
    entrypoint = _entrypoint_text()
    for statement in _migration_module().DDL_STATEMENTS:
        assert _collapse(statement) in entrypoint, statement


def test_ddl_is_idempotent():
    for statement in _migration_module().DDL_STATEMENTS:
        collapsed = _collapse(statement)
        assert "IF NOT EXISTS" in collapsed, collapsed


def test_every_jarvis_table_has_a_deep_health_probe():
    source = (BACKEND / "app" / "main.py").read_text()
    for table in (
        "jarvis_conversations",
        "jarvis_messages",
        "jarvis_actions",
        "jarvis_conversation_entities",
    ):
        assert f'("{table}", ' in source, table


def test_help_procedure_is_seeded_by_migration_and_entrypoint():
    import ast

    from app.data.procedures import JARVIS_PROCEDURE

    assert JARVIS_PROCEDURE.read().startswith("# Jarvis")
    assert "JARVIS_PROCEDURE" in MIGRATION.read_text()
    entrypoint = (BACKEND / "entrypoint.sh").read_text()
    block = re.search(
        r"^_REPO_PROCEDURES = (\[.*?\n\])$", entrypoint, flags=re.MULTILINE | re.DOTALL
    )
    assert block is not None
    rows = {row["slug"]: row for row in ast.literal_eval(block.group(1))}
    row = rows[JARVIS_PROCEDURE.slug]
    assert (row["title"], row["sort_order"], row["filename"]) == (
        JARVIS_PROCEDURE.title,
        JARVIS_PROCEDURE.sort_order,
        JARVIS_PROCEDURE.filename,
    )


MIGRATION_0355 = BACKEND / "alembic" / "versions" / "0355_jarvis_ui_events.py"


def _module_0355():
    spec = importlib.util.spec_from_file_location("m0355", MIGRATION_0355)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_ui_events_migration_is_mirrored_and_matches_the_model():
    """0355: telemetria pomocy na ekranie — lustro w entrypoincie i ta sama
    lista zdarzeń w migracji, modelu i CHECK-u."""
    from app.models.jarvis import JARVIS_UI_EVENTS

    module = _module_0355()
    assert module.down_revision == "0354_order_change_checks"
    entrypoint = _entrypoint_text()
    for statement in module.DDL_STATEMENTS:
        collapsed = _collapse(statement)
        assert "IF NOT EXISTS" in collapsed, collapsed
        assert collapsed in entrypoint, statement
    assert tuple(module.UI_EVENT_NAMES) == JARVIS_UI_EVENTS
    for event in JARVIS_UI_EVENTS:
        assert f"'{event}'" in module.CREATE_UI_EVENTS
    source = (BACKEND / "app" / "main.py").read_text()
    assert '("jarvis_ui_events", ' in source
