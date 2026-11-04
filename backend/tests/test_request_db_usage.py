"""`http_outcome` mówi, ile zapytań zrobiło żądanie i ile na nie czekało.

Pomiar 04.11.2026: czas trasy to liczba zapytań razy kolejka w pętli zdarzeń,
więc sam `duration_ms` nie odróżnia wolnej bazy od zajętego wątku.
"""

from __future__ import annotations

import logging

from sqlalchemy import create_engine, text

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
