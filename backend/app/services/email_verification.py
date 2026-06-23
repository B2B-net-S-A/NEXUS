"""Service layer dla email-verification flow (self-service rejestracja).

Zarządza cyklem życia tokenów potwierdzających adres w tabeli
``email_verification_tokens``. Bliźniaczy do
:mod:`app.services.password_reset`, z dwiema różnicami:

- TTL 24 h (nie 60 min) — link weryfikacyjny w mailu rejestracyjnym powinien
  przeżyć "kliknę wieczorem".
- ``verify_and_consume_token`` nie wymaga ``user.is_active`` — świeżo
  zarejestrowany viewer JEST aktywny (``is_active=True``), brakuje mu tylko
  ``email_verified``; to właśnie ten flow ma odblokować.

Bezpieczeństwo (identyczne jak reset):
- ``secrets.token_hex(32)`` — 64 znaki, 256 bitów entropii.
- W DB tylko SHA-256 hash; plaintext token istnieje wyłącznie w mailu.
- Lookup po UNIQUE INDEX na ``token_hash`` — brak timing leak.
- Atomic ``UPDATE … WHERE used_at IS NULL RETURNING *`` — race-safe consumption.
"""

from __future__ import annotations

import hashlib
import logging
import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.email_verification_token import EmailVerificationToken
from app.models.user import User

logger = logging.getLogger(__name__)


# TTL — link weryfikacyjny ważny 24 h. Dłużej niż reset hasła, bo nie jest to
# operacja wrażliwa (potwierdzenie posiadania skrzynki, nie zmiana hasła).
VERIFY_TOKEN_TTL_MINUTES = 60 * 24

# Cleanup window — usuwamy rekordy starsze niż 7 dni (audit retention).
CLEANUP_WINDOW_DAYS = 7


def _hash_token(plain: str) -> str:
    """SHA-256 hex digest. Stała 64 znaki — pasuje do VARCHAR(64) w DB."""
    return hashlib.sha256(plain.encode("utf-8")).hexdigest()


async def create_verification_token(
    db: AsyncSession,
    user_id: int,
    *,
    requested_ip: Optional[str] = None,
) -> str:
    """Generuje nowy token weryfikacyjny i zapisuje hash do DB.

    Invaliduje wszystkie wcześniejsze nieużyte tokeny tego usera (single
    active per user) — ponowne "wyślij link ponownie" unieważnia poprzedni.
    Plaintext token zwracany jest tylko z tej funkcji — dalej powinien trafić
    wyłącznie do maila.

    Returns:
        plain (unhashed) token — 64 znaki hex.
    """
    now = datetime.now(timezone.utc)
    await db.execute(
        update(EmailVerificationToken)
        .where(
            EmailVerificationToken.user_id == user_id,
            EmailVerificationToken.used_at.is_(None),
        )
        .values(used_at=now)
    )

    plain = secrets.token_hex(32)  # 64 chars hex, 256 bits entropy
    token_hash = _hash_token(plain)
    expires_at = now + timedelta(minutes=VERIFY_TOKEN_TTL_MINUTES)

    db.add(
        EmailVerificationToken(
            user_id=user_id,
            token_hash=token_hash,
            expires_at=expires_at,
            requested_ip=requested_ip,
        )
    )
    await db.flush()

    logger.info(
        "email_verification: token created user_id=%s ip=%s", user_id, requested_ip
    )
    return plain


async def verify_and_consume_token(
    db: AsyncSession, plain_token: str
) -> Optional[User]:
    """Weryfikuje token i atomicznie oznacza go jako użyty.

    Race-safe: ``UPDATE … WHERE used_at IS NULL RETURNING user_id`` — przy
    dwóch równoczesnych requestach tylko jeden zużyje token.

    Nie ustawia ``user.email_verified`` — to robi endpoint (mirror flow
    resetu, gdzie hasło ustawia handler). Returns User gdy token valid +
    nieużyty + nie wygasł, inaczej None.
    """
    if not plain_token or len(plain_token) != 64:
        return None

    token_hash = _hash_token(plain_token)
    now = datetime.now(timezone.utc)

    result = await db.execute(
        update(EmailVerificationToken)
        .where(
            EmailVerificationToken.token_hash == token_hash,
            EmailVerificationToken.used_at.is_(None),
            EmailVerificationToken.expires_at > now,
        )
        .values(used_at=now)
        .returning(EmailVerificationToken.user_id)
    )
    row = result.first()
    if row is None:
        logger.info(
            "email_verification: token verification failed (invalid/expired/used)"
        )
        return None

    user_id = row[0]
    user = await db.scalar(select(User).where(User.id == user_id))
    if user is None:
        logger.warning(
            "email_verification: token valid but user_id=%s missing", user_id
        )
        return None

    logger.info("email_verification: token consumed user_id=%s", user_id)
    return user


async def cleanup_expired_tokens(db: AsyncSession) -> int:
    """Usuwa rekordy starsze niż ``CLEANUP_WINDOW_DAYS`` dni (best-effort).

    Returns: liczba usuniętych rekordów.
    """
    cutoff = datetime.now(timezone.utc) - timedelta(days=CLEANUP_WINDOW_DAYS)
    result = await db.execute(
        EmailVerificationToken.__table__.delete().where(
            EmailVerificationToken.created_at < cutoff
        )
    )
    deleted = result.rowcount or 0
    if deleted:
        logger.debug("email_verification: cleaned up %d expired tokens", deleted)
    return deleted
