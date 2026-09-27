"""Runda 9 (R9-V3-5): downgrade 0381 nie gubi publikacji JJIT ani konta portalu.

Downgrade usuwa ``pending_action``/``remote_state`` i tabelę
``job_board_connections``. Publikacja w toku straciłaby jedyną drogę do
zamknięcia ogłoszenia na portalu, a połączone konto — tokeny. Strażnik odmawia
(RAISE EXCEPTION) PRZED jakimkolwiek DROP-em.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

_FILE = (
    Path(__file__).resolve().parents[1]
    / "alembic"
    / "versions"
    / "0381_job_boards_jjit_rocketjobs.py"
)


def _module():
    spec = importlib.util.spec_from_file_location("m0381", _FILE)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_guard_covers_jjit_state_and_connections(monkeypatch) -> None:
    module = _module()
    executed: list[str] = []
    monkeypatch.setattr(module.op, "execute", executed.append, raising=False)
    module.downgrade()

    guard = executed[0]
    assert guard == module.REFUSE_WITH_ROCKETJOBS_POSTINGS
    assert "pending_action IS NOT NULL" in guard
    assert "remote_state IS NOT NULL" in guard
    assert "FROM job_board_connections" in guard
    # Tabela i kolumny sprawdzane przed zapytaniem (brak = pominięcie, nie błąd).
    assert guard.index("to_regclass('job_board_connections')") < guard.index(
        "FROM job_board_connections)"
    )
    assert guard.index("information_schema.columns") < guard.index(
        "pending_action IS NOT NULL"
    )
    assert "DROP" not in guard and "DELETE" not in guard
    assert any("DROP TABLE IF EXISTS job_board_connections" in s for s in executed[1:])


@pytest.mark.asyncio
async def test_guard_refuses_with_a_connected_account_on_postgres() -> None:
    """Wiersz konta tylko w transakcji wycofywanej na końcu (wspólna baza CI)."""
    from app.core.database import AsyncSessionLocal

    guard = _module().REFUSE_WITH_ROCKETJOBS_POSTINGS
    async with AsyncSessionLocal() as db:
        try:
            await db.execute(
                text(
                    "INSERT INTO job_board_connections (provider, refresh_token_ct) "
                    "VALUES ('r9-test-provider', 'x')"
                )
            )
            with pytest.raises(DBAPIError) as exc:
                await db.execute(text(guard))
            assert "Downgrade 0381 odmawia" in str(exc.value)
        finally:
            await db.rollback()
