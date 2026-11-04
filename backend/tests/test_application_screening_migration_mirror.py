"""0404: tabela oceny zgłoszeń ma lustro w entrypoincie i sondę w
``/api/health/deep`` (prod alembic bywa osierocony), a CHECK-i zgadzają się
z wartościami, które zapisuje kod."""

from __future__ import annotations

import importlib.util
import re
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
MIGRATION = BACKEND / "alembic" / "versions" / "0404_application_screenings.py"


def _migration_module():
    spec = importlib.util.spec_from_file_location("m0404", MIGRATION)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_migration_chains_after_plain_knowledge() -> None:
    module = _migration_module()
    assert module.revision == "0404_application_screenings"
    assert module.down_revision == "0403_plain_knowledge"


def test_entrypoint_imports_the_single_ddl_source_and_enums() -> None:
    text = (BACKEND / "entrypoint.sh").read_text()
    assert "from app.services import application_screening_schema" in text
    assert "*_APPLICATION_SCREENING_DDL," in text
    assert (
        "ALTER TYPE notificationtype ADD VALUE IF NOT EXISTS "
        "'application_screening_digest'" in text
    )
    assert "SELECT 'application_screening', TRUE, 0, now(), now()" in text


def test_ddl_is_idempotent() -> None:
    from app.services.application_screening_schema import TABLE_DDL

    for statement in TABLE_DDL:
        assert "IF NOT EXISTS" in re.sub(r"\s+", " ", statement), statement


def test_checks_cover_every_value_the_code_writes() -> None:
    from app.services import application_screening as svc
    from app.services.application_screening_schema import (
        OUTCOMES,
        STATUSES,
        TABLE_DDL,
        VERDICTS,
    )

    ddl = " ".join(TABLE_DDL)
    for value in (*OUTCOMES, *STATUSES, *VERDICTS):
        assert f"'{value}'" in ddl
    assert set(svc.VERDICTS) == set(VERDICTS)
    source = Path(svc.__file__).read_text()
    for outcome in re.findall(r'outcome="([a-z_]+)"', source):
        assert outcome in OUTCOMES, outcome


def test_health_deep_probes_the_table() -> None:
    main = (BACKEND / "app" / "main.py").read_text()
    assert '("application_screenings", ApplicationScreening)' in main


def test_downgrade_refuses_before_anything_is_dropped(monkeypatch) -> None:
    module = _migration_module()
    executed: list[str] = []
    monkeypatch.setattr(module.op, "execute", executed.append, raising=False)
    module.downgrade()
    guard = executed[0]
    assert "RAISE EXCEPTION" in guard
    assert "feature::text = 'application_screening'" in guard
    assert "'application_screening_digest'" in guard
    assert "DROP" not in guard and "DELETE" not in guard


def test_loop_is_registered_with_heartbeat() -> None:
    task = (BACKEND / "app" / "tasks" / "application_screening.py").read_text()
    assert 'loop_heartbeat.register("application_screening"' in task
    main = (BACKEND / "app" / "main.py").read_text()
    assert '"application_screening": asyncio.create_task(' in main
