#!/usr/bin/env python3
"""Import CRM Atlasa do Sprzedaży NEXUSA — najpierw na stagingu z laptopa.

Czyta bazę Atlasa (Supabase) połączeniem tylko do odczytu z ``ATLAS_DATABASE_URL``
i zapisuje do bazy NEXUSA z ``DATABASE_URL`` (logika: ``app/services/sales/
atlas_import.py``). Domyślnie NA SUCHO: cały import w transakcji, raport,
wycofanie. ``--apply`` zatwierdza. Drugi bieg aktualizuje, nie dubluje.

Uruchomienie na stagingu (backend gałęzi, baza ``nexus_sales``)::

    docker exec -e ATLAS_DATABASE_URL="$(grep ^ATLAS_DATABASE_URL= ~/ATLAS/.env | cut -d= -f2-)" \\
        nexus-staging-backend-sales python -m scripts.import_atlas_sales [--apply]

Raport to same liczby (bez nazw i adresów) — można go wkleić do paragonu
migracji. Pliki z Supabase Storage przenosi osobny krok.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from typing import Any

import asyncpg

TABLES = {
    "people_roles": "user_roles",
    "people_team": "team_members",
    "pipelines": "pipelines",
    "stages": "pipeline_stages",
    "companies": "companies",
    "contacts": "contacts",
    "company_contacts": "company_contacts",
    "deals": "deals",
    "deal_contacts": "deal_contacts",
    "deal_activities": "deal_activities",
    "company_activities": "company_activities",
    "deal_notes": "deal_notes",
    "company_notes": "company_notes",
}


def _postgres_dsn(url: str) -> str:
    """asyncpg nie zna schematu SQLAlchemy ``postgresql+asyncpg://``."""

    return url.replace("postgresql+asyncpg://", "postgresql://", 1)


class AsyncpgSource:
    """Atlas przez asyncpg, każda tabela czytana raz (``SELECT *``)."""

    def __init__(self, connection: asyncpg.Connection) -> None:
        self._connection = connection
        self._cache: dict[str, list[dict[str, Any]]] = {}

    async def _rows(self, key: str) -> list[dict[str, Any]]:
        if key not in self._cache:
            table = TABLES[key]
            records = await self._connection.fetch(f"SELECT * FROM {table}")  # noqa: S608 — stała lista tabel
            self._cache[key] = [dict(record) for record in records]
        return self._cache[key]

    async def people(self) -> list[dict[str, Any]]:
        return [*await self._rows("people_roles"), *await self._rows("people_team")]

    async def pipelines(self):
        return await self._rows("pipelines")

    async def stages(self):
        return await self._rows("stages")

    async def companies(self):
        return await self._rows("companies")

    async def contacts(self):
        return await self._rows("contacts")

    async def company_contacts(self):
        return await self._rows("company_contacts")

    async def deals(self):
        return await self._rows("deals")

    async def deal_contacts(self):
        return await self._rows("deal_contacts")

    async def deal_activities(self):
        return await self._rows("deal_activities")

    async def company_activities(self):
        return await self._rows("company_activities")

    async def deal_notes(self):
        return await self._rows("deal_notes")

    async def company_notes(self):
        return await self._rows("company_notes")

    async def attachments_count(self) -> int:
        total = 0
        for table in ("deal_attachments", "company_attachments"):
            try:
                total += int(
                    await self._connection.fetchval(f"SELECT count(*) FROM {table}")
                )  # noqa: S608
            except asyncpg.UndefinedTableError:
                continue
        return total


async def _main(apply: bool) -> int:
    url = os.environ.get("ATLAS_DATABASE_URL", "").strip()
    if not url:
        print("Brak ATLAS_DATABASE_URL — wpisz go do ~/ATLAS/.env i przekaż przez -e.")
        return 2

    from app.core.database import AsyncSessionLocal
    from app.services.sales.atlas_import import run_import

    connection = await asyncpg.connect(_postgres_dsn(url), timeout=30)
    try:
        await connection.execute("SET default_transaction_read_only = on")
        for codec in ("json", "jsonb"):
            await connection.set_type_codec(
                codec, encoder=json.dumps, decoder=json.loads, schema="pg_catalog"
            )
        source = AsyncpgSource(connection)
        async with AsyncSessionLocal() as db:
            report = await run_import(db, source)
            if apply:
                await db.commit()
            else:
                await db.rollback()
    finally:
        await connection.close()
    print(
        json.dumps({"applied": apply, **report.as_dict()}, ensure_ascii=False, indent=2)
    )
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--apply", action="store_true", help="zatwierdź (domyślnie na sucho)"
    )
    args = parser.parse_args()
    return asyncio.run(_main(args.apply))


if __name__ == "__main__":
    sys.exit(main())
