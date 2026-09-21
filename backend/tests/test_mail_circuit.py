"""State machine tests use the same transitions as the locked Postgres store."""

import pytest
from app.services.m365 import mail_circuit


@pytest.fixture
def memory_circuit(monkeypatch):
    state = {}
    clock = [1000.0]

    def transition(fn):
        return fn(state, clock[0])

    monkeypatch.setattr(mail_circuit, "transition", transition)
    monkeypatch.setattr(mail_circuit, "snapshot", lambda: dict(state))
    return state, clock


def test_persistent_denial_has_one_probe_and_only_one_incident(memory_circuit):
    s, clock = memory_circuit
    ticket = mail_circuit.acquire()
    assert mail_circuit.finish(ticket, code="http_403") is True
    assert all(mail_circuit.acquire() is None for _ in range(100))
    clock[0] += 901
    ticket = mail_circuit.acquire()
    assert ticket is not None
    assert mail_circuit.acquire() is None
    assert mail_circuit.finish(ticket, code="http_403") is False
    assert s["attempts"] == 2
    clock[0] += 901
    assert mail_circuit.finish(mail_circuit.acquire(), code=None) is True
    assert s["consecutive_failures"] == 0
    assert mail_circuit.acquire() is not None


def test_stale_success_does_not_close_new_incident(memory_circuit):
    s, _ = memory_circuit
    a = mail_circuit.acquire()
    b = mail_circuit.acquire()
    mail_circuit.finish(a, code="http_403")
    mail_circuit.finish(b, code=None)
    assert s["consecutive_failures"] == 1
    assert mail_circuit.acquire() is None


def test_retry_after_and_abandoned_probe(memory_circuit):
    s, clock = memory_circuit
    mail_circuit.finish(mail_circuit.acquire(), code="http_429", retry_after=3600)
    clock[0] += 3599
    assert mail_circuit.acquire() is None
    clock[0] += 2
    abandoned = mail_circuit.acquire()
    clock[0] += 91
    replacement = mail_circuit.acquire()
    assert replacement > abandoned
    mail_circuit.finish(abandoned, code=None)
    assert s["consecutive_failures"] == 1
    assert mail_circuit.finish(replacement, code=None) is True
