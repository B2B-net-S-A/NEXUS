"""Status klienta jest NEXUS-owned — Traffit seeduje, ale NIE nadpisuje.

Decyzja Fazy B (2026-08-06): ``_UPSERT_CLIENT`` przy konflikcie aktualizuje
``name``/``notes``, ale zostawia ``status`` w spokoju. Wcześniej każdy daily
sync cofał ręczne zmiany statusu w <24h i wpychał default 'active'
(``normalize_client_status`` fallback) 130 nieaktywnym klientom.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select, update

from app.core.database import AsyncSessionLocal
from app.models.client import Client, ClientStatus
from app.services.traffit.importer import _UPSERT_CLIENT

pytestmark = pytest.mark.asyncio


async def test_second_sync_keeps_manual_status_but_updates_name():
    ext_id = f"status-own-{uuid.uuid4().hex[:8]}"
    payload = {
        "external_id": ext_id,
        "external_source": "traffit",
        "name": "Traffit Nazwa v1",
        "status": "active",
        "notes": None,
    }
    client_id: int | None = None
    try:
        async with AsyncSessionLocal() as db:
            row = (await db.execute(_UPSERT_CLIENT, payload)).fetchone()
            assert row is not None and row[1] is True  # was_insert
            client_id = row[0]
            await db.commit()

        # Ręczna zmiana statusu z UI (PATCH /api/clients/{id}).
        async with AsyncSessionLocal() as db:
            result = await db.execute(
                update(Client)
                .where(Client.id == client_id)
                .values(status=ClientStatus.inactive)
            )
            assert result.rowcount == 1
            await db.commit()

        # Drugi sync: Traffit przysyła 'active' + nową nazwę.
        async with AsyncSessionLocal() as db:
            row = (
                await db.execute(
                    _UPSERT_CLIENT,
                    {**payload, "name": "Traffit Nazwa v2", "status": "active"},
                )
            ).fetchone()
            assert row is not None and row[1] is False  # update, nie insert
            await db.commit()

        async with AsyncSessionLocal() as db:
            client = await db.scalar(select(Client).where(Client.id == client_id))
            assert client is not None
            # Nazwa źródłowa dalej Traffit-owned…
            assert client.name == "Traffit Nazwa v2"
            # …ale status przetrwał ręczną edycję.
            assert client.status == ClientStatus.inactive
    finally:
        if client_id is not None:
            async with AsyncSessionLocal() as db:
                await db.execute(
                    Client.__table__.delete().where(Client.id == client_id)
                )
                await db.commit()
