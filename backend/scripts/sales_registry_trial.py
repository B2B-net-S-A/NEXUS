"""Próba danych firm z rejestrów (biała lista VAT, KRS) na stagingu z laptopa.

Staging ma zaporę wyjścia (rejestry nie przechodzą) i stojącą pętlę, więc próbę
robi się z hosta: skrypt łączy się z bazą stagingu (``DATABASE_URL`` na
``127.0.0.1:5433``), bierze karty do sprawdzenia w tej samej kolejności co noc
(``registry_cards.due_company_ids``) i pyta prawdziwe rejestry.

Domyślnie na sucho: ten sam przebieg co pętla, na końcu wycofanie, bez zapisu
historii i licznika MF. ``--apply`` zapisuje wynik w tej bazie (karty,
``custom_fields``, licznik w ``app_settings``). Skrypt odmawia bazy spoza
``localhost``: produkcji nie dotyka.

Na standardowym wyjściu same liczby. Nazwy kart i wartości z rejestrów idą do
pliku ``--list-out`` poza repozytorium. Reguły:
``docs/claude/sprzedaz/dane-firm-z-rejestrow.md``.

    python -m scripts.sales_registry_trial --limit 3 --list-out ~/registry-trial.json
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.engine import make_url

from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.models.sales import SalesCompany
from app.services.sales import registry_cards

LOCAL_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})


class Refused(Exception):
    pass


def _local_database() -> None:
    host = make_url(settings.DATABASE_URL).host or ""
    if host not in LOCAL_HOSTS:
        raise Refused("baza spoza localhost: próba tylko na stagingu z laptopa")


def _list_path(value: Optional[str]) -> Optional[Path]:
    """Plik z nazwami firm; w repozytorium trafiłby do publicznej historii."""

    if value is None:
        return None
    path = Path(value).expanduser().resolve()
    if any((parent / ".git").exists() for parent in path.parents):
        raise Refused("--list-out: wskaż plik poza repozytorium")
    if not path.parent.is_dir():
        raise Refused("--list-out: katalog nie istnieje")
    return path


async def _names(ids: list[int]) -> dict[int, dict[str, Any]]:
    async with AsyncSessionLocal() as db:
        rows = await db.execute(
            select(
                SalesCompany.id,
                SalesCompany.name,
                SalesCompany.nip,
                SalesCompany.krs,
                SalesCompany.legal_name,
                SalesCompany.regon,
                SalesCompany.hq_city,
            ).where(SalesCompany.id.in_(ids))
        )
        return {row.id: dict(row._mapping) for row in rows}


async def run(limit: int, apply: bool, list_out: Optional[Path]) -> dict[str, Any]:
    now = datetime.now(timezone.utc)
    async with AsyncSessionLocal() as db:
        ids = await registry_cards.due_company_ids(db, now=now, limit=limit)
    before = await _names(ids)
    async with AsyncSessionLocal() as db:
        summary = await registry_cards.check_companies(
            db, ids, now=now, dry_run=not apply
        )
    if list_out is not None:
        cards = [
            {"card": before.get(cid), "registry": payload}
            for cid, payload in summary.cards.items()
        ]
        list_out.write_text(
            json.dumps(cards, ensure_ascii=False, indent=2, default=str),
            encoding="utf-8",
        )
    return {"mode": "apply" if apply else "dry-run", **summary.report()}


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--limit", type=int, default=3)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--list-out")
    args = parser.parse_args(argv)
    try:
        _local_database()
        list_out = _list_path(args.list_out)
        if not 1 <= args.limit <= registry_cards.NIGHT_BATCH:
            raise Refused(f"--limit: od 1 do {registry_cards.NIGHT_BATCH}")
    except Refused as exc:
        print(f"Odmowa: {exc}", file=sys.stderr)
        return 2
    report = asyncio.run(run(args.limit, args.apply, list_out))
    print(json.dumps(report, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
