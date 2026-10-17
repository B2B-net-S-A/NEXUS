"""Nadawca komunikatów z administracja@ (O12): awaria połączenia ≠ awaria osoby.

Brak tokenu, wyjątek przy pobieraniu tokenu, 401 po odświeżeniu, 403 i brak
połączenia z Graph to awaria CAŁEGO połączenia (``unavailable``) — mail na
pewno nie wyszedł, kolejka kończy przebieg i nikt nie traci próby. 408 i 429
to odłożenie jednej osoby, 502/504 i zerwanie po wysłaniu — „niepewny”.
Graph jest podmieniony ``httpx.MockTransport``; nic nie wychodzi.
"""

from __future__ import annotations

from collections.abc import Callable

import httpx
import pytest

from app.services.care import announcement_mail
from app.services.hr.m365 import auth as m365_auth

pytestmark = pytest.mark.asyncio

MAILBOX = "administracja@example.com"
_REAL_CLIENT = httpx.AsyncClient


def _graph(monkeypatch, handler: Callable[[httpx.Request], httpx.Response]) -> list:
    calls: list[httpx.Request] = []

    def factory(*args, **kwargs):
        def route(request: httpx.Request) -> httpx.Response:
            calls.append(request)
            return handler(request)

        return _REAL_CLIENT(*args, transport=httpx.MockTransport(route), **kwargs)

    monkeypatch.setattr(announcement_mail.httpx, "AsyncClient", factory)
    return calls


def _token(monkeypatch, value) -> list[bool]:
    asked: list[bool] = []

    def acquire(*, force_refresh: bool = False):
        asked.append(force_refresh)
        if isinstance(value, Exception):
            raise value
        return value

    monkeypatch.setattr(m365_auth, "acquire_hr_token", acquire)
    return asked


async def _send() -> announcement_mail.MailOutcome:
    return await announcement_mail.GraphMailer(MAILBOX).send(
        to="anna.przykladowa@example.com", subject="Temat", text="Treść"
    )


async def test_missing_token_is_a_connection_failure(monkeypatch) -> None:
    _token(monkeypatch, None)
    calls = _graph(monkeypatch, lambda request: httpx.Response(202))
    outcome = await _send()
    assert outcome.status == "unavailable" and outcome.code == "token"
    assert calls == []


async def test_token_exception_is_a_connection_failure_not_a_crash(
    monkeypatch,
) -> None:
    _token(monkeypatch, RuntimeError("msal"))
    calls = _graph(monkeypatch, lambda request: httpx.Response(202))
    outcome = await _send()
    assert outcome.status == "unavailable" and outcome.code == "token"
    assert calls == []


async def test_refresh_after_401_failing_is_a_connection_failure(monkeypatch) -> None:
    asked: list[bool] = []

    def acquire(*, force_refresh: bool = False):
        asked.append(force_refresh)
        if force_refresh:
            raise RuntimeError("msal")
        return "token-1"

    monkeypatch.setattr(m365_auth, "acquire_hr_token", acquire)
    _graph(monkeypatch, lambda request: httpx.Response(401))
    outcome = await _send()
    assert outcome.status == "unavailable" and outcome.code == "token"
    assert asked == [False, True]


@pytest.mark.parametrize("status_code", [401, 403])
async def test_401_and_403_are_connection_failures(monkeypatch, status_code) -> None:
    _token(monkeypatch, "token-1")
    calls = _graph(monkeypatch, lambda request: httpx.Response(status_code))
    outcome = await _send()
    assert outcome.status == "unavailable"
    assert outcome.code == f"http_{status_code}"
    # 401 dostaje jedno ponowienie ze świeżym tokenem, 403 — żadnego.
    assert len(calls) == (2 if status_code == 401 else 1)


@pytest.mark.parametrize("status_code", [408, 429])
async def test_408_and_429_defer_one_person(monkeypatch, status_code) -> None:
    _token(monkeypatch, "token-1")
    _graph(monkeypatch, lambda request: httpx.Response(status_code))
    outcome = await _send()
    assert outcome.status == "deferred" and outcome.code == f"http_{status_code}"


async def test_no_connection_to_graph_is_a_connection_failure(monkeypatch) -> None:
    _token(monkeypatch, "token-1")

    def refuse(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("brak połączenia", request=request)

    _graph(monkeypatch, refuse)
    outcome = await _send()
    assert outcome.status == "unavailable" and outcome.code == "transport_connect"


async def test_timeout_after_posting_is_uncertain(monkeypatch) -> None:
    _token(monkeypatch, "token-1")

    def hang(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("bez odpowiedzi", request=request)

    _graph(monkeypatch, hang)
    outcome = await _send()
    assert outcome.status == "uncertain"


async def test_accepted_and_rejected(monkeypatch) -> None:
    _token(monkeypatch, "token-1")
    _graph(monkeypatch, lambda request: httpx.Response(202))
    assert (await _send()).status == "accepted"
    _graph(monkeypatch, lambda request: httpx.Response(400))
    rejected = await _send()
    assert rejected.status == "failed" and rejected.code == "http_400"
