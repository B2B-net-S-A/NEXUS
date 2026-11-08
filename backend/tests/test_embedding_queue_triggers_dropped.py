"""0668: triggery martwej kolejki ``embedding_index_queue`` znikają z bazy.

Migracja 0165 z #701 założyła kolejkę bez konsumenta, a rewert #713 usunął
migrację, nie obiekty. Decyzja Artura z 08.11.2026: zdjąć triggery, tabelę
i funkcję zostawić, bo DROP tabeli cofa tylko backup, a triggery odtwarza
downgrade. Lustro w entrypoincie działa przy każdym starcie, więc na czystej
bazie nie może prosić o ACCESS EXCLUSIVE na ``candidates``.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
MIGRATION = BACKEND / "alembic" / "versions" / "0668_drop_embedding_queue_triggers.py"
TRIGGERS = ("trg_candidates_embedding_index", "trg_jobs_embedding_index")


def _migration_module():
    spec = importlib.util.spec_from_file_location("m0668", MIGRATION)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _entrypoint() -> str:
    return (BACKEND / "entrypoint.sh").read_text(encoding="utf-8")


def _executed(monkeypatch, name: str) -> list[str]:
    module = _migration_module()
    executed: list[str] = []
    monkeypatch.setattr(module.op, "execute", executed.append, raising=False)
    getattr(module, name)()
    return executed


def test_revision_fits_the_alembic_version_column() -> None:
    module = _migration_module()
    assert len(module.revision) <= 32
    assert module.down_revision and module.down_revision != module.revision


def test_upgrade_drops_both_triggers_and_nothing_else(monkeypatch) -> None:
    executed = _executed(monkeypatch, "upgrade")
    assert executed == [
        "DROP TRIGGER IF EXISTS trg_candidates_embedding_index ON candidates",
        "DROP TRIGGER IF EXISTS trg_jobs_embedding_index ON jobs",
    ]


def test_table_and_function_stay() -> None:
    for source in (MIGRATION.read_text(encoding="utf-8"), _entrypoint()):
        assert "DROP TABLE IF EXISTS embedding_index_queue" not in source
        assert "DROP TABLE embedding_index_queue" not in source
        assert "DROP FUNCTION IF EXISTS nexus_enqueue_embedding_index" not in source
        assert "DROP FUNCTION nexus_enqueue_embedding_index" not in source


def test_entrypoint_mirrors_the_drops_without_recreating_the_triggers() -> None:
    module = _migration_module()
    entrypoint = _entrypoint()
    for statement in module.DROP_TRIGGERS:
        assert statement in entrypoint
    for trigger in TRIGGERS:
        assert f"CREATE TRIGGER {trigger}" not in entrypoint


def test_entrypoint_takes_the_table_lock_only_when_a_trigger_is_still_there() -> None:
    entrypoint = _entrypoint()
    start = entrypoint.index('startup_phase "embedding-queue-triggers"')
    step = entrypoint[start : entrypoint.index("\nPY\n", start)]
    assert step.index("pg_trigger") < step.index("await conn.execute(text(statement))")
    assert "lock_timeout" in step
    assert "except Exception" in step


def test_downgrade_restores_the_definitions_from_production(monkeypatch) -> None:
    executed = "\n".join(_executed(monkeypatch, "downgrade"))
    assert (
        "CREATE TRIGGER trg_candidates_embedding_index "
        "AFTER INSERT OR DELETE OR UPDATE OF name, lastname, competence_category, "
        "competence_category_id, years_it_experience, skills, verified_tech, "
        "experience, tags, preferences, ai_summary, raw_cv_text, languages "
        "ON public.candidates FOR EACH ROW "
        "EXECUTE FUNCTION nexus_enqueue_embedding_index('candidate')"
    ) in executed
    assert (
        "CREATE TRIGGER trg_jobs_embedding_index "
        "AFTER INSERT OR DELETE OR UPDATE OF title, description, requirements, "
        "seniority, subcategory, industry, train_name, champion_profile, "
        "must_skills, nice_skills, competence_category_id, work_mode "
        "ON public.jobs FOR EACH ROW "
        "EXECUTE FUNCTION nexus_enqueue_embedding_index('job')"
    ) in executed


def test_downgrade_is_a_no_op_on_a_database_without_the_function(monkeypatch) -> None:
    """Czysta baza (CI, nowy staging) nigdy nie miała funkcji z usuniętej 0165."""
    for statement in _executed(monkeypatch, "downgrade"):
        assert "to_regprocedure('public.nexus_enqueue_embedding_index()')" in statement
        assert "to_regclass('public.embedding_index_queue')" in statement
