"""Jednorazowe domknięcie zaległych punktów planu kontaktów przed startem kolejki.

Decyzja Artura 02.11.2026: rytm kontaktów zostaje tylko dla ważnych punktów, więc
zaległości sprzed startu (kopia z 02.11: 909 pozycji) zamykamy raz, jako pominięte
z powodem, a nie kasujemy. Punkt z rozmową dalej można przywrócić („Przywróć”).

Domyślnie próba na sucho: wypisuje liczby i niczego nie zmienia. Zapis wyłącznie
z ``--apply`` i po zgodzie Artura. Paragon bez nazwisk: same liczby, kto i kiedy.

    python -m scripts.close_overdue_contact_plan
    python -m scripts.close_overdue_contact_plan --apply
"""

from __future__ import annotations

import argparse
import asyncio
import json
from datetime import date
from typing import Any

from sqlalchemy import text

from app.core.database import AsyncSessionLocal
from app.core.scheduling import business_today
from app.services.hr import audit

SKIP_REASON = "other"
SKIP_NOTE = "Porządek przed startem kolejki back office: zaległy punkt rytmu."

_COUNT = text(
    """
    SELECT kind, count(*) AS n FROM contract_care_plan_items
    WHERE status = 'open' AND due_on < :today
    GROUP BY kind ORDER BY kind
    """
)
_CLOSE = text(
    """
    UPDATE contract_care_plan_items
    SET status = 'skipped', skip_reason = :reason, skip_note = :note
    WHERE status = 'open' AND due_on < :today
    RETURNING id
    """
)


async def run(*, apply: bool, today: date) -> dict[str, Any]:
    async with AsyncSessionLocal() as db:
        counts = {
            row.kind: row.n
            for row in (await db.execute(_COUNT, {"today": today})).all()
        }
        result: dict[str, Any] = {
            "today": today.isoformat(),
            "overdue": counts,
            "total": sum(counts.values()),
            "applied": False,
        }
        if not apply:
            return result
        closed = (
            await db.execute(
                _CLOSE, {"today": today, "reason": SKIP_REASON, "note": SKIP_NOTE}
            )
        ).all()
        audit.record(
            db,
            actor_user_id=None,
            subject_user_id=None,
            entity_type="care_plan",
            entity_id=0,
            action="care.plan_overdue_closed",
            details={
                "closed": len(closed),
                "by_kind": counts,
                "today": today.isoformat(),
            },
        )
        await db.commit()
        return {**result, "applied": True, "closed": len(closed)}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="zapisz zmiany")
    args = parser.parse_args()
    print(json.dumps(asyncio.run(run(apply=args.apply, today=business_today()))))


if __name__ == "__main__":
    main()
