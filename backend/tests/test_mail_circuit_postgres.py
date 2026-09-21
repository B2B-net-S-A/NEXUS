"""Hosted CI: prove persistence and exclusive recovery across DB connections."""

from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4
from sqlalchemy import text
from app.services.m365 import mail_circuit


def test_restart_and_concurrent_recovery(monkeypatch):
    key = uuid4().hex
    monkeypatch.setattr(mail_circuit, "circuit_key", lambda: key)
    try:
        mail_circuit.finish(mail_circuit.acquire(), code="http_403")
        mail_circuit._engine().dispose()
        mail_circuit._engine.cache_clear()
        assert mail_circuit.snapshot()["last_failure_code"] == "http_403"
        assert mail_circuit.acquire() is None
        mail_circuit.transition(lambda s, now: s.update(next_attempt_at=now - 1))
        with ThreadPoolExecutor(max_workers=2) as pool:
            tickets = list(pool.map(lambda _: mail_circuit.acquire(), range(2)))
        assert sum(t is not None for t in tickets) == 1
        mail_circuit.finish(next(t for t in tickets if t is not None), code=None)
        assert mail_circuit.snapshot()["consecutive_failures"] == 0
    finally:
        with mail_circuit._engine().begin() as conn:
            conn.execute(
                text("DELETE FROM mail_delivery_state WHERE scope=:scope"),
                {"scope": key},
            )
