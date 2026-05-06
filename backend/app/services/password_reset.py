"""Service layer dla password reset flow.

Zarządza cyklem życia tokenów resetowych w tabeli ``password_reset_tokens``:

- ``create_reset_token`` — generuje plaintext token (32-byte hex), hashuje
  SHA-256, zapisuje w DB. Invaliduje wcześniejsze nieużyte tokeny tego
  usera (single active per user). Zwraca PLAIN token do wysłania mailem.
- ``verify_and_consume_token`` — weryfikuje hash, expiry i used_at. Atomic
  UPDATE z ``RETURNING`` zapobiega replay attack przy concurrent requestach.
- ``cleanup_expired_tokens`` — czyści tokeny starsze niż 7 dni
  (best-effort housekeeping, wywoływane raz na request forgot-password).

Token TTL: 60 minut (configurable via ``RESET_TOKEN_TTL_MINUTES``).
Hash: SHA-256 hex (64 znaki). Plaintext token nigdzie nie persistowany.

Bezpieczeństwo:
- ``secrets.token_hex(32)`` — 64 znaki, 256 bitów entropii.
- Lookup po UNIQUE INDEX na ``token_hash`` — brak timing leak.
- Atomic ``UPDATE … WHERE used_at IS NULL RETURNING *`` — race-safe
  consumption (jeśli dwóch równoczesnych requestów próbuje użyć tego
  samego tokena, tylko jeden dostanie rekord).
"""

from __future__ import annotations

import hashlib
import logging
import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.password_reset_token import PasswordResetToken
from app.models.user import User

logger = logging.getLogger(__name__)


# TTL — link wysłany w mailu jest ważny 60 min. Standard branżowy.
RESET_TOKEN_TTL_MINUTES = 60

# Cleanup window — usuwamy stare wpisy starsze niż 7 dni (audit retention).
CLEANUP_WINDOW_DAYS = 7


def _hash_token(plain: str) -> str:
    """SHA-256 hex digest. Stała 64 znaki — pasuje do VARCHAR(64) w DB."""
    return hashlib.sha256(plain.encode("utf-8")).hexdigest()


async def create_reset_token(
    db: AsyncSession,
    user_id: int,
    *,
    requested_ip: Optional[str] = None,
    requested_by_admin_id: Optional[int] = None,
) -> str:
    """Generuje nowy token resetowy i zapisuje hash do DB.

    Invaliduje wszystkie wcześniejsze nieużyte tokeny tego usera (single
    active per user). Plaintext token zwracany jest tylko z tej funkcji
    — dalej powinien trafić tylko do maila i nigdzie poza.

    Args:
        db: aktywna sesja
        user_id: id usera, do którego token się odnosi
        requested_ip: IP z którego przyszło żądanie (audit)
        requested_by_admin_id: gdy admin wysyła link "w imieniu" usera

    Returns:
        plain (unhashed) token — 64 znaki hex.
    """
    # Invaliduj poprzednie aktywne tokeny — single active per user.
    # Jeśli user kliknął "wyślij link" dwa razy, drugi link unieważnia pierwszy.
    now = datetime.now(timezone.utc)
    await db.execute(
        update(PasswordResetToken)
        .where(
            PasswordResetToken.user_id == user_id,
            PasswordResetToken.used_at.is_(None),
        )
        .values(used_at=now)
    )

    plain = secrets.token_hex(32)  # 64 chars hex, 256 bits entropy
    token_hash = _hash_token(plain)

    expires_at = now + timedelta(minutes=RESET_TOKEN_TTL_MINUTES)

    db.add(
        PasswordResetToken(
            user_id=user_id,
            token_hash=token_hash,
            expires_at=expires_at,
            requested_ip=requested_ip,
            requested_by_admin_id=requested_by_admin_id,
        )
    )
    await db.flush()

    logger.info(
        "password_reset: token created user_id=%s admin_id=%s ip=%s",
        user_id,
        requested_by_admin_id,
        requested_ip,
    )
    return plain


async def verify_and_consume_token(
    db: AsyncSession, plain_token: str
) -> Optional[User]:
    """Weryfikuje token i atomicznie oznacza go jako użyty.

    Race-safe: ``UPDATE … WHERE used_at IS NULL RETURNING id`` — jeśli dwa
    requesty próbują zużyć ten sam token równolegle, tylko jeden dostanie
    zaktualizowany rekord, drugi dostanie pustą zwrotkę i fail.

    Returns:
        User instance jeśli token valid + nieużyty + nie wygasł.
        None w pozostałych przypadkach (invalid hash, expired, used).
    """
    if not plain_token or len(plain_token) != 64:
        return None

    token_hash = _hash_token(plain_token)
    now = datetime.now(timezone.utc)

    # Atomic consumption.
    result = await db.execute(
        update(PasswordResetToken)
        .where(
            PasswordResetToken.token_hash == token_hash,
            PasswordResetToken.used_at.is_(None),
            PasswordResetToken.expires_at > now,
        )
        .values(used_at=now)
        .returning(PasswordResetToken.user_id)
    )
    row = result.first()
    if row is None:
        logger.info("password_reset: token verification failed (invalid/expired/used)")
        return None

    user_id = row[0]
    user_result = await db.execute(select(User).where(User.id == user_id))
    user = user_result.scalar_one_or_none()
    if user is None or not user.is_active:
        logger.warning(
            "password_reset: token valid but user_id=%s inactive/missing", user_id
        )
        return None

    logger.info("password_reset: token consumed user_id=%s", user_id)
    return user


async def cleanup_expired_tokens(db: AsyncSession) -> int:
    """Usuwa rekordy starsze niż ``CLEANUP_WINDOW_DAYS`` dni.

    Best-effort housekeeping — wywoływane raz na request forgot-password.
    Audyt: trzymamy tokeny przez 7 dni (debug + dochodzenia bezpieczeństwa).
    Returns: liczba usuniętych rekordów.
    """
    cutoff = datetime.now(timezone.utc) - timedelta(days=CLEANUP_WINDOW_DAYS)
    result = await db.execute(
        # raw SQL via execute(text(...)) byłby krótszy, ale używamy ORM
        # delete dla type safety (pasuje też do testów z in-memory DB).
        PasswordResetToken.__table__.delete().where(
            PasswordResetToken.created_at < cutoff
        )
    )
    deleted = result.rowcount or 0
    if deleted:
        logger.debug("password_reset: cleaned up %d expired tokens", deleted)
    return deleted
