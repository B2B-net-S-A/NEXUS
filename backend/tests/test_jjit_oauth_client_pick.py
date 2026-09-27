"""Runda 9 (R9-N9-11): import JJIT wybiera klienta OAuth jednoznacznie."""

import asyncio
from types import SimpleNamespace

import pytest

from app.services.integrations.jjit import nexus_client


class _Result:
    def __init__(self, rows):
        self._rows = rows

    def scalars(self):
        return self

    def all(self):
        return list(self._rows)


class _Db:
    def __init__(self, rows):
        self.rows = rows
        self.statements = []

    async def execute(self, stmt):
        self.statements.append(str(stmt))
        return _Result(self.rows)


def test_two_enabled_clients_with_the_same_name_are_refused():
    db = _Db([SimpleNamespace(id=1), SimpleNamespace(id=2)])
    with pytest.raises(nexus_client.NexusClientError, match="niejednoznaczny"):
        asyncio.run(nexus_client._pick_oauth_client(db))


def test_missing_client_is_refused():
    with pytest.raises(nexus_client.NexusClientError, match="nie istnieje"):
        asyncio.run(nexus_client._pick_oauth_client(_Db([])))


def test_query_filters_enabled_and_acting_user():
    only = SimpleNamespace(id=7)
    db = _Db([only])
    assert asyncio.run(nexus_client._pick_oauth_client(db)) is only
    sql = db.statements[0]
    assert "oauth_clients.enabled IS true" in sql
    assert "oauth_clients.acting_user_id IS NOT NULL" in sql
