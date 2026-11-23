#!/usr/bin/env python3
"""Bieg na sucho: ile rekordów kampanii kolejka pomija jako powtórki i firmy w CRM.

Zgłoszenie dzwoniących z 17.11.2026 (``docs/claude/sprzedaz/dzwonienie-powtorki-i-firmy-w-crm.md``).
Kolejka od tej zmiany sama pomija dwie grupy rekordów (``calling_repeats.queue_conditions``):

- „Nowy” rekord pod numerem, adresem albo osobą, które mają już wynik w innym rekordzie
  (lista z 13.11.2026: 380 takich rekordów u jednej osoby);
- rekord z listy, którego firma ma otwartą szansę założoną po rekordzie (oferta zapisana
  jako szansa; na stagingu 17.11 takich rekordów było 31).

Skrypt niczego nie zapisuje. Wypisuje same liczby (osoba po id, stan poprzedniego
rekordu), więc wynik może trafić do raportu; ``--ids`` dokłada id rekordów do
sprawdzenia w Tabeli. Skasowanie tych rekordów to osobna decyzja Artura: kolejka
i bez tego ich nie pokazuje.

Użycie (kontener backendu)::

    python -m scripts.calling_repeats_report
    python -m scripts.calling_repeats_report --ids
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from collections import Counter
from pathlib import Path

from sqlalchemy import and_, not_, select

BACKEND_ROOT = Path(__file__).resolve().parent.parent
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.core.database import AsyncSessionLocal  # noqa: E402
from app.models.sales import SalesActivity, SalesCallRecord  # noqa: E402
from app.services.sales import calling, calling_repeats  # noqa: E402


async def report(with_ids: bool) -> None:
    not_in_crm, not_repeat = calling_repeats.queue_conditions()
    waiting = and_(
        SalesCallRecord.campaign_id.is_not(None),
        SalesCallRecord.state.in_(calling.OPEN_STATES),
    )
    async with AsyncSessionLocal() as db:
        crm_rows = (
            await db.execute(
                select(SalesCallRecord.id, SalesCallRecord.assigned_user_id).where(
                    waiting, not_(not_in_crm)
                )
            )
        ).all()
        repeat_rows = (
            await db.execute(
                select(SalesCallRecord.id, SalesCallRecord.assigned_user_id).where(
                    waiting, not_in_crm, not_(not_repeat)
                )
            )
        ).all()
        reported = (
            (
                await db.execute(
                    select(SalesActivity.external_id).where(
                        SalesActivity.external_source
                        == calling_repeats.DUPLICATE_SOURCE
                    )
                )
            )
            .scalars()
            .all()
        )
    print(f"Firma już w CRM (otwarta szansa po rekordzie): {len(crm_rows)}")
    for user_id, count in Counter(row[1] for row in crm_rows).most_common():
        print(f"  osoba {user_id}: {count}")
    print(f"Powtórka numeru, adresu albo osoby z wynikiem: {len(repeat_rows)}")
    for user_id, count in Counter(row[1] for row in repeat_rows).most_common():
        print(f"  osoba {user_id}: {count}")
    # „To duplikat” z karty (23.11.2026): przykłady, których bramki nie złapały.
    print(f"Zgłoszone „To duplikat”: {len(reported)}")
    if with_ids:
        print(
            "Id zgłoszonych rekordów:",
            " ".join(sorted({key.split(":")[0] for key in reported})) or "—",
        )
        print("Id w CRM:", " ".join(str(row[0]) for row in crm_rows) or "—")
        print("Id powtórek:", " ".join(str(row[0]) for row in repeat_rows) or "—")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--ids", action="store_true", help="wypisz też id rekordów")
    args = parser.parse_args()
    asyncio.run(report(args.ids))


if __name__ == "__main__":
    main()
