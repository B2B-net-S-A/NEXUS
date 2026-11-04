"""Jedna reguła adresu e-mail konta: małe litery, bez białych znaków na brzegach.

Runda 9 (R9-N1-1): panel admina zapisywał adres tak, jak go wpisano
(``Jan.Kowalski@…``), rejestracja i SSO — małymi literami, a logowanie hasłem
i „nie pamiętam hasła” porównywały dosłownie. Skutek: SSO nie znajdowało konta
założonego przez admina i zakładało DRUGIE, a hasło do takiego konta działało
tylko przy wpisaniu adresu z tymi samymi wielkimi literami.

Zapis zawsze przez :func:`normalize_email`, wyszukiwanie zawsze przez
:func:`find_user_by_email` (``lower(email)``). Dopóki w bazie mogą leżeć stare
adresy z wielkimi literami (korekta w ``entrypoint.sh`` pomija kolizje),
wygrywa wiersz zapisany dokładnie tak jak zapytanie, potem najstarszy.
"""

from __future__ import annotations

from typing import Optional

from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User


# Jednorazowa (samoograniczająca) korekta starych adresów — biegnie w
# ``entrypoint.sh`` przy każdym starcie, drugi raz nic nie znajduje. Adres,
# którego forma małymi literami jest już zajęta przez INNE konto, zostaje
# (dwa konta jednej osoby rozstrzyga człowiek); ich liczbę zwraca
# ``LOWERCASE_EMAIL_COLLISIONS_SQL``.
LOWERCASE_EMAILS_SQL = """
UPDATE users AS u
   SET email = lower(u.email)
 WHERE u.email <> lower(u.email)
   AND NOT EXISTS (
       SELECT 1 FROM users AS o
        WHERE o.id <> u.id AND lower(o.email) = lower(u.email)
   )
"""

LOWERCASE_EMAIL_COLLISIONS_SQL = """
SELECT count(*) FROM users WHERE email <> lower(email)
"""


def normalize_email(value: Optional[str]) -> str:
    return (value or "").strip().lower()


def user_by_email_statement(email: Optional[str], *, for_update: bool = False):
    normalized = normalize_email(email)
    stmt = (
        select(User)
        .where(func.lower(User.email) == normalized)
        .order_by(case((User.email == normalized, 0), else_=1), User.id)
        .limit(1)
    )
    if for_update:
        stmt = stmt.with_for_update()
    return stmt


async def find_user_by_email(
    db: AsyncSession, email: Optional[str], *, for_update: bool = False
) -> Optional[User]:
    if not normalize_email(email):
        return None
    return await db.scalar(user_by_email_statement(email, for_update=for_update))
