"""Runda 7 (R7-X5-4): ``assert_client_assignable`` bez bazy."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone

import pytest
from fastapi import HTTPException

from app.models.client import Client
from app.services.client_access import assert_client_assignable


class _FakeDb:
    def __init__(self, *rows):
        self._rows = list(rows)

    async def scalar(self, _statement):
        return self._rows.pop(0) if self._rows else None


def _run(db, client_id):
    return asyncio.run(assert_client_assignable(db, client_id))


def test_none_and_missing_client_are_left_to_the_caller():
    assert _run(_FakeDb(), None) is None
    assert _run(_FakeDb(None), 7) is None


def test_live_client_passes():
    live = Client(id=7, name="Firma Zmyślona")
    assert _run(_FakeDb(live), 7) is live


def test_deleted_client_is_422_with_its_name():
    deleted = Client(id=7, name="Firma Zmyślona", deleted_at=datetime.now(timezone.utc))
    with pytest.raises(HTTPException) as exc:
        _run(_FakeDb(deleted), 7)
    assert exc.value.status_code == 422
    assert exc.value.detail["code"] == "client_deleted"
    assert "Firma Zmyślona" in exc.value.detail["message"]


def test_merged_client_is_422_and_names_the_canonical_record():
    duplicate = Client(id=7, name="Duplikat Sp. z o.o.", merged_into_client_id=9)
    canonical = Client(id=9, name="Firma Główna S.A.")
    with pytest.raises(HTTPException) as exc:
        _run(_FakeDb(duplicate, canonical), 7)
    assert exc.value.status_code == 422
    assert exc.value.detail["code"] == "client_merged"
    assert exc.value.detail["merged_into_client_id"] == 9
    assert "Firma Główna S.A." in exc.value.detail["message"]
