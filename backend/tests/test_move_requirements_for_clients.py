"""Pola minimum z karty klienta dla wielu klientów naraz
(`client_required_fields_for_clients`). Firmy są zmyślone."""

from __future__ import annotations

import uuid
from contextlib import contextmanager

from sqlalchemy import event

import app.models  # noqa: F401  (rejestracja wszystkich mapperów)
from app.core.database import AsyncSessionLocal, engine
from app.models.client import Client
from app.models.client_playbook import ClientPlaybook
from app.services.move_requirements import (
    client_required_fields,
    client_required_fields_for_clients,
)


@contextmanager
def count_statements():
    seen: list[str] = []

    def _on(conn, cursor, statement, parameters, context, executemany):
        seen.append(statement)

    event.listen(engine.sync_engine, "before_cursor_execute", _on)
    try:
        yield seen
    finally:
        event.remove(engine.sync_engine, "before_cursor_execute", _on)


async def _seed() -> dict:
    """Karta z polami, karta ze starym kluczem, karta pusta, klient bez karty."""
    tag = uuid.uuid4().hex[:8]
    async with AsyncSessionLocal() as db:
        clients = {
            label: Client(name=f"Karta-{label}-{tag}", display_name=display)
            for label, display in (
                ("fields", f"  Pola {tag} "),
                ("legacy", None),
                ("empty", None),
                ("none", None),
            )
        }
        db.add_all(clients.values())
        await db.flush()
        db.add_all(
            [
                ClientPlaybook(
                    client_id=clients["fields"].id,
                    verified_required_fields=["english", "motivation", "nieznane"],
                ),
                ClientPlaybook(
                    client_id=clients["legacy"].id,
                    verified_required_fields=["stary_klucz"],
                ),
                ClientPlaybook(
                    client_id=clients["empty"].id, verified_required_fields=[]
                ),
            ]
        )
        await db.commit()
        return {label: c.id for label, c in clients.items()}


async def test_each_client_gets_exactly_what_the_single_call_gives():
    w = await _seed()
    keys = [*w.values(), None]
    async with AsyncSessionLocal() as db:
        bulk = await client_required_fields_for_clients(db, keys)
        assert set(bulk) == set(keys)
        for key in keys:
            assert bulk[key] == await client_required_fields(db, key), key
    # Kolejność pól z `CLIENT_EXTRA_FIELDS`, nazwa wyświetlana bez spacji.
    assert bulk[w["fields"]][0] == ("motivation", "english")
    assert bulk[w["fields"]][1] == bulk[w["fields"]][1].strip()
    for label in ("legacy", "empty", "none"):
        assert bulk[w[label]] == ((), None)
    assert bulk[None] == ((), None)


async def test_query_count_does_not_grow_with_clients():
    w = await _seed()
    async with AsyncSessionLocal() as db:
        with count_statements() as none_only:
            assert await client_required_fields_for_clients(db, [None]) == {
                None: ((), None)
            }
        with count_statements() as one:
            await client_required_fields_for_clients(db, [w["fields"]])
        with count_statements() as many:
            await client_required_fields_for_clients(db, [*w.values(), None])
    assert none_only == []
    assert len(one) == 1, one
    assert len(many) == len(one), (len(one), len(many))
