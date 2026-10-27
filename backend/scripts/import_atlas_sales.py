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
migracji. Pliki z Supabase Storage: drugi bieg z ``--files`` (wymaga
``ATLAS_SUPABASE_URL`` i ``ATLAS_SUPABASE_SERVICE_KEY``; na stagingu host
Supabase musi być w ``STAGING_EXTRA_ALLOWED_HOSTS``).
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
    "linkedin_leads": "linkedin_leads",
    "press_signals": "press_signals",
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

    async def linkedin_leads(self):
        return await self._rows("linkedin_leads")

    async def press_signals(self):
        return await self._rows("press_signals")

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


async def _copy_files(
    connection: asyncpg.Connection, db, apply: bool
) -> dict[str, int]:
    """``--files``: pliki z Supabase Storage Atlasa → magazyn NEXUSA (po imporcie)."""

    import httpx
    from sqlalchemy import func, select

    from app.models.user import User
    from app.services.sales.atlas_files import copy_attachments

    base = os.environ.get("ATLAS_SUPABASE_URL", "").strip().rstrip("/")
    key = os.environ.get("ATLAS_SUPABASE_SERVICE_KEY", "").strip()
    if not base or not key:
        raise SystemExit(
            "Brak ATLAS_SUPABASE_URL / ATLAS_SUPABASE_SERVICE_KEY — wpisz je do ~/ATLAS/.env."
        )

    async def rows(table: str) -> list[dict[str, Any]]:
        try:
            return [dict(r) for r in await connection.fetch(f"SELECT * FROM {table}")]  # noqa: S608
        except asyncpg.UndefinedTableError:
            return []

    users = dict(
        (
            await db.execute(
                select(func.lower(User.email), User.id).where(User.email.is_not(None))
            )
        ).all()
    )
    async with httpx.AsyncClient(
        timeout=60, headers={"Authorization": f"Bearer {key}", "apikey": key}
    ) as client:

        async def fetch(bucket: str, path: str):
            resp = await client.get(f"{base}/storage/v1/object/{bucket}/{path}")
            return resp.content if resp.status_code == 200 else None

        report = await copy_attachments(
            db,
            deal_attachments=await rows("deal_attachments"),
            company_attachments=await rows("company_attachments"),
            fetch=fetch,
            users_by_email=users,
            dry_run=not apply,
        )
    return report.as_dict()


async def _main(apply: bool, files: bool) -> int:
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
        async with AsyncSessionLocal() as db:
            if files:
                # Na sucho pliki nie są pobierane ani zapisywane — same liczby.
                result = await _copy_files(connection, db, apply)
            else:
                result = (await run_import(db, AsyncpgSource(connection))).as_dict()
            if apply:
                await db.commit()
            else:
                await db.rollback()
    finally:
        await connection.close()
    print(json.dumps({"applied": apply, **result}, ensure_ascii=False, indent=2))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--apply", action="store_true", help="zatwierdź (domyślnie na sucho)"
    )
    parser.add_argument(
        "--files",
        action="store_true",
        help="przenieś pliki z Supabase Storage (po imporcie danych)",
    )
    args = parser.parse_args()
    return asyncio.run(_main(args.apply, args.files))


if __name__ == "__main__":
    sys.exit(main())
