"""Synchronizacja kalendarza M365 nie przypina spotkań do kandydata po adresie
z domeny firmy (20.10.2026).

Kandydat z adresem pracownika (rekord testowy) zbierał każde spotkanie, na
którym ten pracownik był uczestnikiem — także spotkania z prawdziwym
kandydatem, który „przegrywał” niższym ``id``. Ta sama reguła co w matcherze
maili: pomijamy domeny z ``SSO_ALLOWED_DOMAINS`` i domenę właściciela skrzynki.
Testy bez bazy.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.core.config import settings

FIRMA = "firma.example"


def _graph_event(*addresses: str) -> dict:
    return {
        "id": "graph-ev-internal",
        "changeKey": "ck1",
        "subject": "Spotkanie",
        "body": {"content": "Treść"},
        "start": {"dateTime": "2026-10-01T10:00:00Z"},
        "end": {"dateTime": "2026-10-01T11:00:00Z"},
        "attendees": [{"emailAddress": {"address": a}} for a in addresses],
        "sensitivity": "normal",
    }


def _conn(mailbox: str = f"wlasciciel@{FIRMA}") -> SimpleNamespace:
    return SimpleNamespace(user_id=5, mailbox_upn=mailbox)


def _candidate_query_addresses(db: AsyncMock) -> list[str]:
    """Adresy z zapytania o kandydata (drugie ``db.scalar``)."""
    stmt = db.scalar.await_args_list[1].args[0]
    params = stmt.compile().params
    return sorted(v for vals in params.values() if isinstance(vals, list) for v in vals)


@pytest.mark.asyncio
async def test_colleague_from_company_domain_does_not_link_candidate(
    monkeypatch,
) -> None:
    from app.services.m365.sync import _upsert_event

    monkeypatch.setattr(settings, "SSO_ALLOWED_DOMAINS", FIRMA)
    db = AsyncMock()
    db.add = MagicMock()
    # Gdyby zapytanie o kandydata poszło, zwróciłoby kandydata z adresem kolegi.
    db.scalar.side_effect = [None, SimpleNamespace(id=99)]

    assert await _upsert_event(db, _conn(), _graph_event(f"Kolega@{FIRMA}"))

    row = db.add.call_args.args[0]
    assert row.candidate_id is None
    # Jedyne zapytanie to odczyt istniejącego wiersza — bez szukania kandydata.
    assert db.scalar.await_count == 1


@pytest.mark.asyncio
async def test_owner_mailbox_domain_counts_as_internal_without_sso_setting(
    monkeypatch,
) -> None:
    from app.services.m365.sync import _upsert_event

    monkeypatch.setattr(settings, "SSO_ALLOWED_DOMAINS", "")
    db = AsyncMock()
    db.add = MagicMock()
    db.scalar.side_effect = [None, SimpleNamespace(id=99)]

    assert await _upsert_event(
        db, _conn(f"wlasciciel@{FIRMA}"), _graph_event(f"kolega@{FIRMA}")
    )

    assert db.add.call_args.args[0].candidate_id is None
    assert db.scalar.await_count == 1


@pytest.mark.asyncio
async def test_external_attendee_still_links_candidate(monkeypatch) -> None:
    from app.services.m365.sync import _upsert_event

    monkeypatch.setattr(settings, "SSO_ALLOWED_DOMAINS", FIRMA)
    db = AsyncMock()
    db.add = MagicMock()
    db.scalar.side_effect = [None, SimpleNamespace(id=42)]

    assert await _upsert_event(
        db,
        _conn(),
        _graph_event(
            f"kolega@{FIRMA}", " Kandydat@Example.com ", f"wlasciciel@{FIRMA}"
        ),
    )

    row = db.add.call_args.args[0]
    assert row.candidate_id == 42
    # Szukamy tylko po adresie zewnętrznym; uczestnicy zostają w całości.
    assert _candidate_query_addresses(db) == ["kandydat@example.com"]
    assert len(row.attendees) == 3


@pytest.mark.asyncio
async def test_existing_row_is_not_linked_by_company_address(monkeypatch) -> None:
    from app.models.calendar_event import EventType
    from app.services.m365.sync import _upsert_event

    monkeypatch.setattr(settings, "SSO_ALLOWED_DOMAINS", FIRMA)
    existing = SimpleNamespace(
        title="Spotkanie",
        description=None,
        location=None,
        attendees=[],
        teams_link=None,
        online_meeting_url=None,
        m365_change_key="ck0",
        m365_series_master_id=None,
        event_type=EventType.meeting,
        candidate_id=None,
        external_source="m365",
    )
    db = AsyncMock()
    db.scalar.side_effect = [existing, SimpleNamespace(id=99)]

    assert await _upsert_event(db, _conn(), _graph_event(f"kolega@{FIRMA}"))

    assert existing.candidate_id is None
    assert db.scalar.await_count == 1


def test_external_addresses_shared_rule(monkeypatch) -> None:
    from app.services.m365.matcher import external_addresses

    monkeypatch.setattr(settings, "SSO_ALLOWED_DOMAINS", f"{FIRMA}, druga.example")
    assert external_addresses(
        [
            f"KOLEGA@{FIRMA}",
            "ktos@druga.example",
            "wlasciciel@inna.example",
            " Kandydat@Example.com ",
            "kandydat@example.com",
            "",
            "bez-malpy",
        ],
        "wlasciciel@inna.example",
    ) == ["bez-malpy", "kandydat@example.com"]
