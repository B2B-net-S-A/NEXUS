#!/usr/bin/env python3
"""
Reset user password (admin emergency tool).

Usage (z Coolify shell lub SSH do backend container):

    cd /app
    python scripts/reset_password.py <email> <new_password>

Przykład:

    python scripts/reset_password.py artur@b2bnet.pl NowEMocneHaslo2026!

Sprawdza czy user istnieje, haszuje hasło przez bcrypt (passlib, ten sam
mechanizm co /api/auth/login), zapisuje do DB. **Nie wymaga żadnego
endpointu API** — pisze bezpośrednio do bazy przez SQLAlchemy, omija guardy.

Uruchamiać TYLKO z backendu produkcyjnego (backend ma DATABASE_URL w env).
"""

from __future__ import annotations

import asyncio
import os
import sys

# Zapewnij że `app` jest na sys.path (backend container ma /app jako root —
# entrypoint.sh ustawia PYTHONPATH tylko dla uvicorn, nie dla dowolnego python).
_APP_ROOT = "/app"
if os.path.isdir(_APP_ROOT) and _APP_ROOT not in sys.path:
    sys.path.insert(0, _APP_ROOT)


async def reset_password(email: str, new_password: str) -> int:
    # Opóźniony import — wymaga DATABASE_URL + SECRET_KEY w env.
    from sqlalchemy import select

    from app.core.database import AsyncSessionLocal
    from app.core.security import hash_password
    from app.models.user import User

    if len(new_password) < 8:
        print("error: new_password must be ≥ 8 characters", file=sys.stderr)
        return 2

    async with AsyncSessionLocal() as db:
        user = await db.scalar(select(User).where(User.email == email))
        if user is None:
            print(f"error: user {email!r} not found", file=sys.stderr)
            return 3

        user.password_hash = hash_password(new_password)
        await db.commit()
        print(
            f"OK: password reset for id={user.id} email={user.email} "
            f"role={user.role.value} is_active={user.is_active}"
        )
        return 0


def main() -> int:
    if len(sys.argv) != 3:
        print(f"usage: {sys.argv[0]} <email> <new_password>", file=sys.stderr)
        return 1

    email = sys.argv[1].strip()
    new_password = sys.argv[2]

    if not os.environ.get("DATABASE_URL"):
        print(
            "error: DATABASE_URL not set — run from backend container",
            file=sys.stderr,
        )
        return 4

    return asyncio.run(reset_password(email, new_password))


if __name__ == "__main__":
    sys.exit(main())
