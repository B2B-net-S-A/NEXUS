"""Zdarzenia API v1 (0448): lustro migracji w entrypoint.sh i rejestracje.

Prod alembic bywa osierocony — entrypoint JEST wdrożeniem schematu. Bez
tabel listener gubi zdarzenia (zapis biznesowy zostaje), a kanał i webhooki
dają 500, więc lustro, sonda ``/api/health/deep``, model w ``app.models``,
pętla w ``main.py`` i import listenera muszą iść razem.
"""

from __future__ import annotations

import re
from pathlib import Path

from app.models.integration_event import (
    IntegrationEvent,
    IntegrationEventOutbox,
    IntegrationWebhook,
)

ROOT = Path(__file__).resolve().parents[1]
VERSIONS = ROOT / "alembic/versions"
TABLES = ("integration_event_outbox", "integration_events", "integration_webhooks")


def _squash(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def _migration() -> dict:
    ns: dict = {}
    source = (VERSIONS / "0448_integration_events.py").read_text(encoding="utf-8")
    exec(compile(source.replace("from alembic import op", ""), "m", "exec"), ns)
    return ns


def test_revision_chain_has_one_head() -> None:
    ns = _migration()
    assert ns["revision"] == "0448_integration_events"
    assert ns["down_revision"] == "0447_job_previous_recruiters"
    children = [
        path.name
        for path in VERSIONS.glob("*.py")
        if re.search(
            r'^down_revision\s*=\s*"0448_integration_events"',
            path.read_text(encoding="utf-8"),
            re.MULTILINE,
        )
    ]
    siblings = [
        path.name
        for path in VERSIONS.glob("*.py")
        if re.search(
            r'^down_revision\s*=\s*"0447_job_previous_recruiters"',
            path.read_text(encoding="utf-8"),
            re.MULTILINE,
        )
    ]
    assert siblings == ["0448_integration_events.py"]
    # Następca jest dozwolony; tu tylko pilnujemy, że nikt nie podpiął drugiej
    # gałęzi pod 0447.
    assert all(name > "0448" for name in children)


def test_tables_and_indexes_are_mirrored_in_entrypoint() -> None:
    ns = _migration()
    entry = _squash((ROOT / "entrypoint.sh").read_text(encoding="utf-8"))
    for ddl in (ns["CREATE_OUTBOX"], ns["CREATE_EVENTS"], ns["CREATE_WEBHOOKS"]):
        assert _squash(ddl) in entry, ddl.splitlines()[0]
    for statement in ns["INDEXES"]:
        assert _squash(statement) in entry, statement
    # W `_COLUMN_STATEMENTS` (przed seedami i ograniczeniami), za tabelą
    # kont serwisowych, do której wskazuje klucz obcy webhooków.
    columns = entry.index("_COLUMN_STATEMENTS = [")
    data = entry.index("_DATA_STATEMENTS = [")
    at = entry.index("CREATE TABLE IF NOT EXISTS integration_webhooks")
    assert columns < at < data


def test_models_match_migration_columns() -> None:
    ns = _migration()
    for model, ddl in (
        (IntegrationEventOutbox, ns["CREATE_OUTBOX"]),
        (IntegrationEvent, ns["CREATE_EVENTS"]),
        (IntegrationWebhook, ns["CREATE_WEBHOOKS"]),
    ):
        declared = {
            match.group(1)
            for match in re.finditer(r"^\s+([a-z_]+) [A-Z]", ddl, re.MULTILINE)
            if match.group(1) != "constraint"
        }
        assert set(model.__table__.columns.keys()) == declared, model.__tablename__
    webhook_fk = next(
        iter(IntegrationWebhook.__table__.c.service_account_id.foreign_keys)
    )
    assert webhook_fk.ondelete == "CASCADE"
    assert "ON DELETE CASCADE" in ns["CREATE_WEBHOOKS"]


def test_tables_are_probed_by_deep_health_and_registered() -> None:
    main = (ROOT / "app/main.py").read_text(encoding="utf-8")
    block = main[main.index("    core_checks = [") :]
    block = block[: block.index("\n    ]")]
    for table in TABLES:
        assert re.search(rf'\("{table}",\s*\w+\)', block), table
    models_init = (ROOT / "app/models/__init__.py").read_text(encoding="utf-8")
    assert "from app.models.integration_event import" in models_init


def test_listener_import_and_loop_are_wired_in_main() -> None:
    main = (ROOT / "app/main.py").read_text(encoding="utf-8")
    # Listener rejestruje się przy imporcie — bez tego zdarzenia nie powstają.
    assert "import app.services.integration_events  # noqa: F401" in main
    assert (
        '"integration_webhooks": asyncio.create_task(integration_webhooks_loop())'
        in main
    )
    task = (ROOT / "app/tasks/integration_webhooks.py").read_text(encoding="utf-8")
    assert 'loop_heartbeat.register(\n        "integration_webhooks"' in task
