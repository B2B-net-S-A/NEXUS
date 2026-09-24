"""Wystawia krótkie tokeny dostępu do testu obciążeniowego produkcji.

Uruchamiany WEWNĄTRZ kontenera backendu (sekret podpisu nie opuszcza serwera):

    ssh root@<prod> "docker exec -i <backend> python - id=82 recruiter=6 delivery_lead=3 head_of_recruitment=1" \
        < qa/load/mint_prod_tokens.py > .qa/prod-tokens.json

Argumenty: ``id=<n>`` (konkretne konto) albo ``<rola>=<liczba>`` (tylu aktywnych
użytkowników o tej roli głównej, najniższe id). Na wyjściu JSON z tokenami (ważne
``LOADTEST_TOKEN_MINUTES`` minut, domyślnie 180) — zapisz go do
``.qa/prod-tokens.json`` z prawami 0600 i nigdy nie commituj. Transakcja jest
tylko do odczytu: skrypt niczego nie zapisuje w bazie.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from datetime import timedelta

from sqlalchemy import select, text

from app.core.database import AsyncSessionLocal
from app.core.security import create_access_token
from app.models.user import User, UserRole
from app.services.section_permissions import resolve_effective_section_access


async def main(specs: list[str]) -> None:
    minutes = int(os.environ.get("LOADTEST_TOKEN_MINUTES", "180"))
    sessions = []
    async with AsyncSessionLocal() as db:
        await db.execute(text("SET TRANSACTION READ ONLY"))
        user_ids: list[int] = []
        for spec in specs:
            key, _, value = spec.partition("=")
            if key == "id":
                user_ids.append(int(value))
                continue
            rows = await db.execute(
                select(User.id)
                .where(User.is_active.is_(True), User.role == UserRole(key))
                .order_by(User.id)
                .limit(int(value))
            )
            user_ids.extend(rows.scalars())
        for user_id in dict.fromkeys(user_ids):
            user = (
                await db.execute(select(User).where(User.id == user_id))
            ).scalar_one_or_none()
            if user is None or not user.is_active:
                raise SystemExit(f"user {user_id}: brak albo nieaktywny")
            await resolve_effective_section_access(db, user)
            sessions.append(
                {
                    "user_id": user.id,
                    "role": user.role.value,
                    "token": create_access_token(
                        user.id,
                        user.role.value,
                        expires_delta=timedelta(minutes=minutes),
                        roles=[r.value for r in user.get_all_roles()],
                        authorization_version=user.authorization_version,
                        section_access=user.effective_section_access,
                    ),
                }
            )
        await db.rollback()
    json.dump({"sessions": sessions}, sys.stdout)


if __name__ == "__main__":
    if not sys.argv[1:]:
        raise SystemExit("podaj id=<n> albo <rola>=<liczba>")
    asyncio.run(main(sys.argv[1:]))
