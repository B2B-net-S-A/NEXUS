"""PATCH /api/clients/{id} — kontrakt edycji nazwy przez `display_name`.

Ticket #1 bug 4: formularz edycji pisał do `Client.name`, które (a) przegrywa
w wyświetlaniu z `display_name` (coalesce) i (b) jest nadpisywane przez daily
sync Traffita. Edycja nazwy idzie teraz w sync-odporny `display_name`:

- PATCH display_name → GET/PATCH-response zwracają nową nazwę EFEKTYWNĄ,
- PATCH display_name="" → normalizacja do NULL → powrót nazwy źródłowej,
- PATCH innego pola nie dotyka display_name (dirty-check jest po stronie FE,
  ale backendowy exclude_unset gwarantuje to samo dla API).

Pattern: in-process app_client / app_auth_headers (admin).
"""

from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.core.database import AsyncSessionLocal
from app.models.client import Client

pytestmark = pytest.mark.asyncio


async def _new_client(*, display_name: str | None = None) -> int:
    suffix = uuid.uuid4().hex[:8]
    async with AsyncSessionLocal() as db:
        c = Client(name=f"Zrodlowa Nazwa {suffix}", display_name=display_name)
        db.add(c)
        await db.flush()
        await db.commit()
        return c.id


async def _cleanup(client_id: int) -> None:
    async with AsyncSessionLocal() as db:
        await db.execute(Client.__table__.delete().where(Client.id == client_id))
        await db.commit()


async def test_patch_display_name_changes_effective_name(
    app_client: AsyncClient, app_auth_headers: dict[str, str]
):
    client_id = await _new_client()
    try:
        resp = await app_client.patch(
            f"/api/clients/{client_id}",
            json={"display_name": "Nordea Bank Abp"},
            headers=app_auth_headers,
        )
        assert resp.status_code == 200, resp.text
        # Odpowiedź PATCH musi już pokazywać nazwę efektywną — surowy ORM
        # zwracał tu client.name i wyglądało to jak brak zapisu.
        assert resp.json()["name"] == "Nordea Bank Abp"

        get_resp = await app_client.get(
            f"/api/clients/{client_id}", headers=app_auth_headers
        )
        assert get_resp.status_code == 200
        assert get_resp.json()["name"] == "Nordea Bank Abp"

        # Kolumna źródłowa `name` została nietknięta (Traffit-owned).
        async with AsyncSessionLocal() as db:
            row = await db.scalar(select(Client).where(Client.id == client_id))
            assert row is not None
            assert row.name.startswith("Zrodlowa Nazwa")
            assert row.display_name == "Nordea Bank Abp"
    finally:
        await _cleanup(client_id)


async def test_patch_blank_display_name_reverts_to_source_name(
    app_client: AsyncClient, app_auth_headers: dict[str, str]
):
    client_id = await _new_client(display_name="Stara Wyswietlana")
    try:
        # Wyczyszczenie pola: whitespace → walidator normalizuje do NULL.
        resp = await app_client.patch(
            f"/api/clients/{client_id}",
            json={"display_name": "   "},
            headers=app_auth_headers,
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["name"].startswith("Zrodlowa Nazwa")

        async with AsyncSessionLocal() as db:
            row = await db.scalar(select(Client).where(Client.id == client_id))
            assert row is not None
            assert row.display_name is None
    finally:
        await _cleanup(client_id)


async def test_patch_name_is_ignored_source_column_untouched(
    app_client: AsyncClient, app_auth_headers: dict[str, str]
):
    """`name` usunięte z ClientUpdate — surowy PATCH {"name": ...} nie może
    pisać do Traffit-owned kolumny (odtwarzałby bug „nazwa się cofa")."""
    client_id = await _new_client()
    try:
        resp = await app_client.patch(
            f"/api/clients/{client_id}",
            json={"name": "Proba Nadpisania", "industry": "IT"},
            headers=app_auth_headers,
        )
        assert resp.status_code == 200, resp.text

        async with AsyncSessionLocal() as db:
            row = await db.scalar(select(Client).where(Client.id == client_id))
            assert row is not None
            # Kolumna źródłowa nietknięta; legalne pole z tego samego payloadu
            # przeszło normalnie.
            assert row.name.startswith("Zrodlowa Nazwa")
            assert row.industry == "IT"
    finally:
        await _cleanup(client_id)


async def test_patch_other_field_leaves_display_name_alone(
    app_client: AsyncClient, app_auth_headers: dict[str, str]
):
    client_id = await _new_client(display_name="Przypieta Nazwa")
    try:
        resp = await app_client.patch(
            f"/api/clients/{client_id}",
            json={"industry": "Fintech"},
            headers=app_auth_headers,
        )
        assert resp.status_code == 200, resp.text
        # exclude_unset: nie wysłane pole = nietknięte; nazwa efektywna zostaje.
        assert resp.json()["name"] == "Przypieta Nazwa"

        async with AsyncSessionLocal() as db:
            row = await db.scalar(select(Client).where(Client.id == client_id))
            assert row is not None
            assert row.display_name == "Przypieta Nazwa"
            assert row.industry == "Fintech"
    finally:
        await _cleanup(client_id)
