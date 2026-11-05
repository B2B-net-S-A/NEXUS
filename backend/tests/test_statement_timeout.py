"""Bezpiecznik `statement_timeout`: tylko proces WWW, czytelny błąd po przekroczeniu.

Pomiar 04.11.2026 (`docs/claude/podstawy/statement-timeout.md`): od 20.07 nic poza
awarią dysku nie przekroczyło 78,7 s, a limit w `connect_args` dostałyby też skrypty,
CLI i start w entrypoincie, gdyby ustawić go dla całego kontenera.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.exc import DBAPIError
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.routing import Route

from app.core import database
from app.core.statement_timeout import STATEMENT_TIMEOUT_DETAIL, is_statement_timeout
from app.main import UnhandledErrorMiddleware

ASYNCPG_URL = "postgresql+asyncpg://u:p@h/d"
ENTRYPOINT = Path(__file__).resolve().parents[1] / "entrypoint.sh"


class _DriverError(Exception):
    def __init__(self, sqlstate: str) -> None:
        super().__init__("canceling statement")
        self.sqlstate = sqlstate


def _db_error(sqlstate: str) -> DBAPIError:
    return DBAPIError("SELECT 1", None, _DriverError(sqlstate))


def test_no_limit_without_the_setting(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(database.settings, "DB_STATEMENT_TIMEOUT_MS", 0)
    assert (
        "statement_timeout"
        not in (database._connect_args(ASYNCPG_URL)["server_settings"])
    )


def test_limit_reaches_the_connection_as_text(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(database.settings, "DB_STATEMENT_TIMEOUT_MS", 120_000)
    settings_ = database._connect_args(ASYNCPG_URL)["server_settings"]
    # asyncpg przyjmuje w `server_settings` wyłącznie tekst.
    assert settings_["statement_timeout"] == "120000"
    assert settings_["application_name"] == "nexus-backend"


def test_other_drivers_get_no_server_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(database.settings, "DB_STATEMENT_TIMEOUT_MS", 120_000)
    assert database._connect_args("sqlite+aiosqlite:///:memory:") == {}


def test_only_uvicorn_gets_the_limit() -> None:
    """Skrypty, CLI i start w entrypoincie zostają bez limitu: DDL trwa, ile musi."""
    lines = [line.strip() for line in ENTRYPOINT.read_text().splitlines()]
    uvicorn = lines.index("exec uvicorn app.main:app --host 0.0.0.0 --port 8000")
    export = lines.index("export DB_STATEMENT_TIMEOUT_MS=120000")
    assert export == uvicorn - 1
    assert sum("DB_STATEMENT_TIMEOUT_MS" in line for line in lines) == 1


def test_compose_does_not_set_the_limit_for_the_whole_container() -> None:
    """Zmienna w `environment:` dostałaby też `docker exec` ze skryptami."""
    root = ENTRYPOINT.parents[1]
    for name in ("docker-compose.yml", "docker-compose.staging.yml"):
        assert "DB_STATEMENT_TIMEOUT_MS" not in (root / name).read_text()


@pytest.mark.parametrize(
    ("error", "expected"),
    [
        (_db_error("57014"), True),
        (_db_error("55P03"), False),  # lock_timeout ma własne obsługi
        (_db_error("23505"), False),
        (ValueError("canceling statement due to statement timeout"), False),
    ],
)
def test_recognises_only_the_cancelled_statement(
    error: Exception, expected: bool
) -> None:
    assert is_statement_timeout(error) is expected


def test_recognises_the_driver_error_down_the_cause_chain() -> None:
    wrapper = RuntimeError("opakowanie")
    wrapper.__cause__ = _db_error("57014")
    assert is_statement_timeout(wrapper)


async def _request_with(error: Exception) -> tuple[int, dict]:
    async def boom(_request: Request) -> None:
        raise error

    app = Starlette(routes=[Route("/x", boom)])
    app.add_middleware(UnhandledErrorMiddleware)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://t") as client:
        response = await client.get("/x")
    return response.status_code, response.json()


@pytest.mark.asyncio
async def test_cancelled_statement_gets_its_own_message() -> None:
    """500, nie 504 ani 503: front ponowiłby odczyt, który właśnie trwał 2 minuty."""
    status, body = await _request_with(_db_error("57014"))
    assert status == 500
    assert body == {"detail": STATEMENT_TIMEOUT_DETAIL}


@pytest.mark.asyncio
async def test_other_database_errors_keep_the_general_message() -> None:
    status, body = await _request_with(_db_error("23505"))
    assert status == 500
    assert body["detail"] != STATEMENT_TIMEOUT_DETAIL
