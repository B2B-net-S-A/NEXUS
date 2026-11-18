"""`http_outcome` mówi, ile zapytań zrobiło żądanie i ile na nie czekało.

Pomiar 04.11.2026: czas trasy to liczba zapytań razy kolejka w pętli zdarzeń,
więc sam `duration_ms` nie odróżnia wolnej bazy od zajętego wątku.
"""

from __future__ import annotations

import asyncio
import logging

import httpx
from fastapi import BackgroundTasks, FastAPI
from sqlalchemy import create_engine, text
from starlette.middleware.base import BaseHTTPMiddleware

from app.core.database import attach_request_db_usage
from app.core.request_correlation import (
    RequestCorrelationMiddleware,
    RequestDbUsage,
    request_db_usage,
)


async def _run(app, path: str = "/x") -> None:
    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(_message):
        return None

    await RequestCorrelationMiddleware(app)(
        {"type": "http", "method": "GET", "path": path, "headers": []}, receive, send
    )


def _outcome(caplog) -> logging.LogRecord:
    return next(r for r in caplog.records if r.getMessage() == "http_outcome")


async def test_outcome_counts_statements_of_this_request(caplog) -> None:
    engine = create_engine("sqlite://")
    attach_request_db_usage(engine)

    async def app(_scope, _receive, send):
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
            conn.execute(text("SELECT 2"))
        await send({"type": "http.response.start", "status": 200, "headers": []})

    with caplog.at_level(logging.INFO):
        await _run(app)
    engine.dispose()

    record = _outcome(caplog)
    assert record.db_statements == 2
    assert record.db_ms >= 0


async def test_outcome_without_database_reports_zero(caplog) -> None:
    async def app(_scope, _receive, send):
        await send({"type": "http.response.start", "status": 200, "headers": []})

    with caplog.at_level(logging.INFO):
        await _run(app)

    record = _outcome(caplog)
    assert (record.db_statements, record.db_ms) == (0, 0.0)


def test_statements_outside_a_request_are_not_counted() -> None:
    # Pętle w tle nie mają licznika żądania i nie mogą paść na jego braku.
    assert request_db_usage.get() is None
    engine = create_engine("sqlite://")
    attach_request_db_usage(engine)
    with engine.connect() as conn:
        assert conn.execute(text("SELECT 1")).scalar() == 1
    engine.dispose()


def test_usage_rounds_only_on_read() -> None:
    usage = RequestDbUsage()
    usage.finished(0.00125)
    usage.finished(0.00125)
    assert usage.statements == 2
    assert usage.rounded_ms() == 2.5


async def _run_with_body(app, path: str = "/x") -> None:
    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(_message):
        return None

    await RequestCorrelationMiddleware(app)(
        {"type": "http", "method": "POST", "path": path, "headers": []}, receive, send
    )


async def test_background_work_after_response_is_logged_apart(caplog) -> None:
    """18.11.2026: odczyt CV w `BackgroundTasks` biegnie w middleware po wysłaniu
    odpowiedzi; `duration_ms` liczył go jak czas trasy (p50 18 s dla wgrania CV)."""
    engine = create_engine("sqlite://")
    attach_request_db_usage(engine)

    async def app(_scope, _receive, send):
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"{}", "more_body": False})
        # Jak Starlette `BackgroundTasks`: praca po ostatnim kawałku odpowiedzi.
        await asyncio.sleep(0.15)
        with engine.connect() as conn:
            conn.execute(text("SELECT 2"))
            conn.execute(text("SELECT 3"))

    with caplog.at_level(logging.INFO):
        await _run_with_body(app)
    engine.dispose()

    record = _outcome(caplog)
    assert record.duration_ms < 150
    assert record.background_ms >= 150
    assert record.db_statements == 1
    assert record.background_db_statements == 2
    assert record.background_db_ms >= 0


async def test_streamed_response_ends_at_last_chunk(caplog) -> None:
    async def app(_scope, _receive, send):
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"a", "more_body": True})
        await asyncio.sleep(0.12)
        await send({"type": "http.response.body", "body": b"b", "more_body": False})

    with caplog.at_level(logging.INFO):
        await _run_with_body(app)

    record = _outcome(caplog)
    assert record.duration_ms >= 120
    assert not hasattr(record, "background_ms")


async def test_no_background_fields_for_a_plain_response(caplog) -> None:
    async def app(_scope, _receive, send):
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"{}", "more_body": False})

    with caplog.at_level(logging.INFO):
        await _run_with_body(app)

    record = _outcome(caplog)
    assert not hasattr(record, "background_ms")
    assert not hasattr(record, "background_db_statements")


async def test_fastapi_background_task_behind_base_http_middleware(caplog) -> None:
    """Ten sam układ co `main.py`: middleware'y z `BaseHTTPMiddleware` wewnątrz."""
    app = FastAPI()

    async def passthrough(request, call_next):
        return await call_next(request)

    async def slow_job() -> None:
        await asyncio.sleep(0.2)

    @app.post("/cv")
    async def upload(background_tasks: BackgroundTasks) -> dict:
        background_tasks.add_task(slow_job)
        return {"ok": True}

    app.add_middleware(BaseHTTPMiddleware, dispatch=passthrough)
    app.add_middleware(RequestCorrelationMiddleware)

    with caplog.at_level(logging.INFO):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://t"
        ) as client:
            response = await client.post("/cv")
    assert response.status_code == 200

    record = _outcome(caplog)
    assert record.route == "/cv"
    assert record.duration_ms < 200
    assert record.background_ms >= 200
