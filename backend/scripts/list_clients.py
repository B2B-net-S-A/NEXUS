#!/usr/bin/env python3
"""Read-only podgląd klientów — ``id`` + nazwa, po fragmencie nazwy.

Po co osobne narzędzie: kilka polityk domenowych jest bramkowanych LISTĄ
``client_id`` w zmiennych środowiskowych (``MULTI_CONSULTANT_ORDER_CLIENT_IDS``,
``COST_ORDER_CLIENT_IDS``, ``BANK_POCZTOWY_ORDER_EXTRACTION_CLIENT_IDS``,
``CREDIT_AGRICOLE_ORDER_EXTRACTION_CLIENT_IDS``, ``ERSTE_GROSS_RATE_CLIENT_IDS``).
Bramka po ID, nie po nazwie, jest świadoma — Traffit nadpisuje ``Client.name``,
a rodzina rekordów tego samego banku bywa większa niż jeden wiersz. Cena tej
decyzji: żeby WŁĄCZYĆ politykę, trzeba znać numer, a numeru nie widać ani
w interfejsie, ani w repo. Bez tego skryptu jedyną drogą był panel Coolify
albo SSH — a SSH na tym serwerze nie działa.

**Wyłącznie SELECT.** Skrypt nie ma ścieżki zapisu i nie przyjmuje SQL-a
z zewnątrz: filtr jedzie parametrem wiązanym, a wildcardy ``%``/``_`` są
escapowane, więc ``%`` szuka znaku procenta, a nie zwraca całej bazy.

Wyjście jest CELOWO ubogie — ``id``, nazwa, nazwa wyświetlana, NIP. Żadnych
kwot, żadnych osób: to narzędzie odpowiada na pytanie „który numer wpisać
w zmienną", a jego wyjście ląduje w logu GitHub Actions.

Użycie::

    python -m scripts.list_clients --like cardif
    python -m scripts.list_clients --like erste --limit 20
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

from sqlalchemy import func, or_, select

BACKEND_ROOT = Path(__file__).resolve().parent.parent
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.core.database import AsyncSessionLocal  # noqa: E402
from app.models.client import Client  # noqa: E402

# Znak ucieczki dla LIKE. Bez tego fragment „100%" albo „a_b" zachowuje się
# jak wzorzec, a nie jak tekst — ta sama reguła co w wyszukiwarce umów B2B.
_ESCAPE = "\\"


def escape_like(value: str) -> str:
    """Wildcardy LIKE stają się zwykłymi znakami."""
    return (
        value.replace(_ESCAPE, _ESCAPE * 2)
        .replace("%", f"{_ESCAPE}%")
        .replace("_", f"{_ESCAPE}_")
    )


async def find_clients(needle: str, limit: int) -> list[tuple[int, str, str, str]]:
    pattern = f"%{escape_like(needle.strip().lower())}%"
    async with AsyncSessionLocal() as db:
        rows = await db.execute(
            select(Client.id, Client.name, Client.display_name, Client.nip)
            .where(
                or_(
                    func.lower(Client.name).like(pattern, escape=_ESCAPE),
                    func.lower(func.coalesce(Client.display_name, "")).like(
                        pattern, escape=_ESCAPE
                    ),
                    func.lower(func.coalesce(Client.legal_name, "")).like(
                        pattern, escape=_ESCAPE
                    ),
                )
            )
            .order_by(Client.id)
            .limit(limit)
        )
        return [(r[0], r[1] or "", r[2] or "", r[3] or "") for r in rows.all()]


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--like", required=True, help="fragment nazwy klienta")
    parser.add_argument("--limit", type=int, default=50)
    args = parser.parse_args()

    rows = await find_clients(args.like, max(1, min(args.limit, 200)))
    # Nagłówek drukujemy ZAWSZE, także przy zerze trafień: pusty wydruk
    # w logu Actions nie odróżnia „nic nie pasuje" od „skrypt się nie wykonał".
    print(f"=== clients matching {args.like!r}: {len(rows)} ===")
    for cid, name, display, nip in rows:
        print(f"{cid}\t{name}\tdisplay={display}\tnip={nip}")


if __name__ == "__main__":
    asyncio.run(main())
