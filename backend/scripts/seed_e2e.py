"""Konta ról dla efemerycznego stacku E2E (QA-02, plan poprawy po audycie 14.09).

Tworzy WYŁĄCZNIE użytkowników — każdy scenariusz Playwrighta zakłada własne
dane przez API. Świadomie nie reużywa ``backend/seed.py``: tamten skrypt
zasiewa dane demo i konto w roli ``user``, którą migracja 0210 wycofała, a
scenariusze, które zakładają „jakąś rekrutację o id 1", były dokładnie tym
defektem, który audyt wytknął (``SAMPLE_JOB_ID = 1``).

Konta mają ukończony onboarding i zweryfikowany e-mail — inaczej rekruter
i Delivery Lead zostaliby przekierowani na ``/onboarding`` i każdy scenariusz
testowałby bramkę onboardingu zamiast przepływu.

Dwie bramki bezpieczeństwa, bo skrypt pisze hasła do tabeli ``users``:
* ``E2E_SEED_CONFIRM=nexus-e2e`` — bez tego skrypt kończy się błędem;
* baza z więcej niż ``MAX_EXISTING_USERS`` kontami jest odrzucana — produkcja
  ma ich setki, świeży stack E2E zero.

Użycie::

    E2E_SEED_CONFIRM=nexus-e2e E2E_SEED_PASSWORD=... python scripts/seed_e2e.py
"""

from __future__ import annotations

import asyncio
import logging
import os
import sys
from dataclasses import dataclass
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parent.parent
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from sqlalchemy import func, select  # noqa: E402
from sqlalchemy.ext.asyncio import AsyncSession  # noqa: E402

from app.core.database import AsyncSessionLocal  # noqa: E402
from app.core.security import hash_password  # noqa: E402
from app.models.user import User, UserRole  # noqa: E402

logger = logging.getLogger("seed_e2e")

CONFIRM_TOKEN = "nexus-e2e"
MAX_EXISTING_USERS = 10


@dataclass(frozen=True)
class E2EAccount:
    email: str
    name: str
    role: UserRole


ACCOUNTS: tuple[E2EAccount, ...] = (
    E2EAccount("e2e-admin@example.com", "E2E Admin", UserRole.admin),
    E2EAccount("e2e-recruiter@example.com", "E2E Rekruter", UserRole.recruiter),
    E2EAccount("e2e-dl@example.com", "E2E Delivery Lead", UserRole.delivery_lead),
)


class SeedRefused(RuntimeError):
    """Skrypt odmówił zasiewu — bramka bezpieczeństwa nie przeszła."""


async def seed_accounts(db: AsyncSession, password: str) -> list[str]:
    """Zakłada brakujące konta (idempotentnie) i zwraca e-maile nowych."""
    if len(password) < 12:
        raise SeedRefused("E2E_SEED_PASSWORD musi mieć co najmniej 12 znaków.")

    emails = [account.email for account in ACCOUNTS]
    existing_total = await db.scalar(select(func.count()).select_from(User))
    existing_e2e = set(
        (await db.scalars(select(User.email).where(User.email.in_(emails)))).all()
    )
    foreign_users = int(existing_total or 0) - len(existing_e2e)
    if foreign_users > MAX_EXISTING_USERS:
        raise SeedRefused(
            f"Baza ma {foreign_users} kont spoza E2E — to nie jest świeży stack testowy."
        )

    created: list[str] = []
    for account in ACCOUNTS:
        if account.email in existing_e2e:
            continue
        user = User(
            email=account.email,
            password_hash=hash_password(password),
            name=account.name,
            role=account.role,
            is_active=True,
            email_verified=True,
            profile_completed=True,
        )
        user.ensure_roles_invariant()
        db.add(user)
        created.append(account.email)
    await db.commit()
    return created


async def _main() -> int:
    if os.environ.get("E2E_SEED_CONFIRM") != CONFIRM_TOKEN:
        logger.error("Brak E2E_SEED_CONFIRM=%s — zasiew odrzucony.", CONFIRM_TOKEN)
        return 2
    password = os.environ.get("E2E_SEED_PASSWORD", "")
    async with AsyncSessionLocal() as db:
        try:
            created = await seed_accounts(db, password)
        except SeedRefused as exc:
            logger.error("%s", exc)
            return 2
    logger.info("Konta E2E: nowe=%d, wszystkie=%d", len(created), len(ACCOUNTS))
    return 0


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    sys.exit(asyncio.run(_main()))
