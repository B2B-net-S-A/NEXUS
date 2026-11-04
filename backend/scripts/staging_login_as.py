#!/usr/bin/env python3
"""„Zaloguj jako” — token dostępu dla wskazanej osoby, WYŁĄCZNIE na stagingu.

Po co: test całej ścieżki na stagingu (``docs/claude/podstawy/test-calej-sciezki-na-stagingu.md``)
przechodzi kolejne kroki jako prawdziwe osoby w różnych rolach — rekruter
przesuwa kartę, Delivery Lead akceptuje, Head of Recruitment widzi wynik.
Hasła na stagingu są skopiowane z produkcji (a konta SSO nie mają ich wcale),
a admiński „Podgląd jako” (``api/deps.py``) jest tylko do odczytu, więc
żadną z tych dróg nie da się przejść ścieżki z zapisami.

Bezpieczeństwo:

- skrypt kończy się kodem 2, gdy ``NEXUS_ENV`` nie jest ``staging``;
- token jest podpisany ``SECRET_KEY`` stagingu, który jest własny
  (``staging-na-laptopie.md``), więc na produkcji jest bezwartościowy;
- konto nieaktywne dostaje odmowę, tak jak przy zwykłym logowaniu.

Użycie (w kontenerze backendu stagingu)::

    docker exec nexus-staging-backend-1 python -m scripts.staging_login_as --role delivery_lead
    docker exec nexus-staging-backend-1 python -m scripts.staging_login_as --user-id 123

Pierwsza komenda wypisuje aktywne osoby w roli (id, role, imię i nazwisko),
druga — sam token na stdout. Token wkładasz do karty przeglądarki
(``localStorage.access_token``) i otwierasz ``/login``: strona sama sprawdza go
przez ``GET /api/auth/me`` i kończy logowanie (cookie ``nexus_access``,
``nexus_user``). Wyjście zawiera dane osobowe z kopii produkcji — tylko
terminal na laptopie, nigdy repo ani logi Actions.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

from sqlalchemy import select

BACKEND_ROOT = Path(__file__).resolve().parent.parent
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.core.config import settings  # noqa: E402
from app.core.security import create_access_token  # noqa: E402
from app.models.user import User, UserRole  # noqa: E402

EXIT_NOT_STAGING = 2
EXIT_NO_USER = 3


def staging_only() -> bool:
    return settings.NEXUS_ENV == "staging"


def access_token_for(user: User) -> str:
    """Ten sam zestaw claimów co ``POST /api/auth/login``.

    ``user.effective_section_access`` musi być już policzone
    (``resolve_effective_section_access``).
    """
    return create_access_token(
        user.id,
        user.role.value,
        force_password_change=user.force_password_change,
        roles=[r.value for r in user.get_all_roles()],
        authorization_version=user.authorization_version,
        section_access=user.effective_section_access,
    )


async def _list_role(role: UserRole) -> int:
    from app.core.database import AsyncSessionLocal

    async with AsyncSessionLocal() as db:
        users = (
            (
                await db.execute(
                    select(User).where(User.is_active.is_(True)).order_by(User.id)
                )
            )
            .scalars()
            .all()
        )
    for user in users:
        if role in user.get_all_roles():
            roles = ",".join(sorted(r.value for r in user.get_all_roles()))
            print(f"{user.id}\t{roles}\t{user.name}")
    return 0


async def _token(user_id: int) -> int:
    from app.core.database import AsyncSessionLocal
    from app.services.section_permissions import resolve_effective_section_access

    async with AsyncSessionLocal() as db:
        user = await db.get(User, user_id)
        if user is None or not user.is_active:
            print(f"Brak aktywnej osoby o id {user_id}", file=sys.stderr)
            return EXIT_NO_USER
        await resolve_effective_section_access(db, user)
        print(access_token_for(user))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--user-id", type=int)
    group.add_argument("--role", choices=[r.value for r in UserRole])
    args = parser.parse_args(argv)

    if not staging_only():
        print(
            f"Odmowa: NEXUS_ENV={settings.NEXUS_ENV!r}. "
            "„Zaloguj jako” działa wyłącznie na stagingu.",
            file=sys.stderr,
        )
        return EXIT_NOT_STAGING

    if args.role:
        return asyncio.run(_list_role(UserRole(args.role)))
    return asyncio.run(_token(args.user_id))


if __name__ == "__main__":
    raise SystemExit(main())
