"""Fernet-based token-at-rest encryption.

Used for storing third-party OAuth access/refresh tokens (Microsoft 365 for now,
future: Gmail) in the database without leaving them in plaintext. The key lives
in settings (env-driven, backed by Coolify secrets in prod).

Key rotation is NOT automatic: changing `M365_TOKEN_ENCRYPTION_KEY` invalidates
every existing encrypted row. Users must reconnect. Document this in ops runbook.
"""

from __future__ import annotations

import logging
from functools import lru_cache

from cryptography.fernet import Fernet, InvalidToken

from app.core.config import settings

logger = logging.getLogger(__name__)


class TokenCipherNotConfigured(RuntimeError):
    """Raised at first use when M365_TOKEN_ENCRYPTION_KEY is empty/invalid."""


class TokenCipher:
    """Thin Fernet wrapper with lazy validation.

    We don't fail at import time — dev and tests that never touch M365 should
    still be able to boot without the secret. Any actual encrypt/decrypt call
    without a configured key raises a clear error.
    """

    def __init__(self, key: str) -> None:
        if not key:
            raise TokenCipherNotConfigured(
                "M365_TOKEN_ENCRYPTION_KEY is empty. Generate via "
                '`python -c "from cryptography.fernet import Fernet; '
                'print(Fernet.generate_key().decode())"` and set in Coolify secrets.'
            )
        try:
            self._fernet = Fernet(key.encode("utf-8"))
        except (ValueError, TypeError) as exc:
            raise TokenCipherNotConfigured(
                "M365_TOKEN_ENCRYPTION_KEY is not a valid Fernet key "
                "(must be 32 url-safe base64-encoded bytes)."
            ) from exc

    def encrypt(self, plaintext: str) -> str:
        if plaintext is None:
            raise ValueError("encrypt() received None")
        return self._fernet.encrypt(plaintext.encode("utf-8")).decode("utf-8")

    def decrypt(self, ciphertext: str) -> str:
        if not ciphertext:
            raise ValueError("decrypt() received empty ciphertext")
        try:
            return self._fernet.decrypt(ciphertext.encode("utf-8")).decode("utf-8")
        except InvalidToken as exc:
            raise TokenCipherNotConfigured(
                "Failed to decrypt token — key likely rotated. User must reconnect."
            ) from exc


@lru_cache(maxsize=1)
def get_token_cipher() -> TokenCipher:
    """Lazy singleton. Cached so the Fernet object is constructed once per process."""
    return TokenCipher(settings.M365_TOKEN_ENCRYPTION_KEY)
