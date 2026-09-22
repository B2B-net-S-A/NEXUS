"""POST do Graph nie jest powtarzany po utracie odpowiedzi (INT-06).

``ReadTimeout``/``ReadError`` znaczy: żądanie mogło zostać przyjęte, zginęła
tylko odpowiedź. Dla ``POST /me/events`` albo ``/send`` powtórka zdublowałaby
zaproszenie lub mail. ``ConnectError`` (żądanie nie wyszło) jest ponawiany
jak dawniej, a jawnie bezpieczne POST-y (``getSchedule``) mogą się powtarzać.
Wydarzenie niesie stały ``transactionId`` — Graph po nim rozpoznaje powtórkę.
"""

from __future__ import annotations

from datetime import datetime, timezone

import httpx
import pytest

from app.services.m365 import graph_client as gc_mod
from app.services.m365.calendar import _build_event_payload, event_transaction_id


class _FakeHttp:
    def __init__(self, errors: list[BaseException]) -> None:
        self.errors = list(errors)
        self.calls = 0

    async def request(self, method, url, params=None, json=None, headers=None):  # noqa: ANN001
        self.calls += 1
        if self.errors:
            raise self.errors.pop(0)
        return httpx.Response(
            200, json={"ok": True}, request=httpx.Request(method, url)
        )


def _client(errors: list[BaseException]) -> gc_mod.GraphClient:
    client = object.__new__(gc_mod.GraphClient)
    client._client = _FakeHttp(errors)
    client._access_token = "t"

    async def _authorize() -> None:
        return None

    client._authorize = _authorize
    return client


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch):
    async def _instant(_seconds):  # noqa: ANN001
        return None

    monkeypatch.setattr(gc_mod.asyncio, "sleep", _instant)


@pytest.mark.asyncio
@pytest.mark.parametrize("error", [httpx.ReadTimeout("lost"), httpx.ReadError("reset")])
async def test_post_is_not_retried_after_lost_response(error):
    client = _client([error])
    with pytest.raises(type(error)):
        await client.post("/me/events", json={"subject": "x"})
    assert client._client.calls == 1


@pytest.mark.asyncio
async def test_post_is_retried_after_connect_error():
    client = _client([httpx.ConnectError("refused")])
    assert await client.post("/me/events", json={}) == {"ok": True}
    assert client._client.calls == 2


@pytest.mark.asyncio
async def test_read_only_post_may_retry_after_lost_response():
    client = _client([httpx.ReadTimeout("lost")])
    result = await client.post("/me/calendar/getSchedule", json={}, retry_unsafe=True)
    assert result == {"ok": True}
    assert client._client.calls == 2


@pytest.mark.asyncio
async def test_get_still_retries_after_read_timeout():
    client = _client([httpx.ReadTimeout("lost")])
    assert await client.get("/me/messages") == {"ok": True}
    assert client._client.calls == 2


def test_event_payload_carries_stable_transaction_id():
    start = datetime(2026, 9, 23, 9, 0, tzinfo=timezone.utc)
    end = datetime(2026, 9, 23, 10, 0, tzinfo=timezone.utc)
    kwargs = dict(
        owner_user_id=7,
        title="Rozmowa",
        start=start,
        end=end,
        attendee_emails=["B@example.com", "a@example.com"],
    )
    first = event_transaction_id(**kwargs)
    # Kolejność i wielkość liter adresów nie zmieniają intencji.
    again = event_transaction_id(
        **{**kwargs, "attendee_emails": ["a@example.com", "b@example.com"]}
    )
    assert first == again
    assert first != event_transaction_id(**{**kwargs, "title": "Inna rozmowa"})
    assert event_transaction_id(**kwargs, intent_id="slot-1") == event_transaction_id(
        **{**kwargs, "title": "Zmieniony tytuł"}, intent_id="slot-1"
    )

    payload = _build_event_payload(
        title="Rozmowa",
        description="",
        start=start,
        end=end,
        attendee_emails=[],
        want_teams=False,
        transaction_id=first,
    )
    assert payload["transactionId"] == first
    assert len(first) <= 64
