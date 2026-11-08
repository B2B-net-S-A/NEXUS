"""Przypisania kont wyłączonych przed regułą z audytu 08.11.2026 (B8).

Od tej daty ``deactivate_account`` zwalnia przypisania sam. Ten skrypt domyka
konta wyłączone wcześniej (7 otwartych rekrutacji na 4 kontach na kopii
z 08.11.2026). Domyślnie podgląd (bez zapisu), ``--apply`` zwalnia i commituje.
Wynik: JSON z samymi identyfikatorami, bez nazwisk.

Uruchomienie w kontenerze backendu::

    python -m scripts.release_deactivated_accounts
    python -m scripts.release_deactivated_accounts --apply
"""

import argparse
import asyncio
import json

from sqlalchemy import select

from app.core.database import AsyncSessionLocal, engine
from app.models.user import User
from app.services.account_assignment_release import (
    planned_release,
    release_user_assignments,
)


async def _run(*, apply: bool) -> dict:
    report: dict = {"apply": apply, "accounts": {}, "released_jobs": []}
    async with AsyncSessionLocal() as db:
        users = (
            await db.scalars(
                select(User).where(User.is_active.is_(False)).order_by(User.id)
            )
        ).all()
        for user in users:
            planned = await planned_release(db, user.id)
            if not planned:
                continue
            report["accounts"][user.id] = planned
            if apply:
                report["released_jobs"] += await release_user_assignments(
                    db, user, actor_id=None
                )
        if apply:
            await db.commit()
    await engine.dispose()
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="zapisz zmiany")
    args = parser.parse_args()
    print(json.dumps(asyncio.run(_run(apply=args.apply)), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
