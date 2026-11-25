"""Fernet-based encryption at rest with key rotation (``MultiFernet``).

Used for third-party OAuth tokens (Microsoft 365, job portals), webhook
secrets, invite-link secrets and payroll data (bank accounts, PESEL and the
ZUS/PIT person record). The keys live in settings (env-driven, Coolify
secrets in prod):

* ``M365_TOKEN_ENCRYPTION_KEY`` — the current key: every encryption uses it;
* ``M365_TOKEN_ENCRYPTION_KEY_PREVIOUS`` — comma-separated keys that only
  decrypt. A rotation puts the old key here, re-encrypts every row with
  ``python -m app.cli.token_cipher_rotate --apply`` and removes it once the
  script reports nothing left under it.

HMAC fingerprints (bank account, PESEL) use a key derived from the same
secret: written with the current key, compared against every configured key
(``TokenCipher.fingerprints``), recomputed by the same script.

Procedure and pitfalls (M365 sync deactivates a mailbox whose token does not
decrypt): ``docs/claude/podstawy/rotacja-klucza-szyfrowania-tokenow.md``.
"""

from __future__ import annotations

import hashlib
import hmac
import logging
from collections.abc import Sequence
from functools import lru_cache
from typing import Optional

from cryptography.fernet import Fernet, InvalidToken, MultiFernet

from app.core.config import settings

logger = logging.getLogger(__name__)

PREVIOUS_KEYS_SETTING = "M365_TOKEN_ENCRYPTION_KEY_PREVIOUS"


class TokenCipherNotConfigured(RuntimeError):
    """Raised when a key is empty/invalid or a ciphertext matches no key."""


def parse_key_list(raw: Optional[str]) -> tuple[str, ...]:
    """``"a, b,,c"`` → ``("a", "b", "c")`` — the format of the PREVIOUS setting."""

    return tuple(part.strip() for part in (raw or "").split(",") if part.strip())


class TokenCipher:
    """``MultiFernet`` wrapper with lazy validation.

    We don't fail at import time — dev and tests that never touch encrypted
    data should still be able to boot without the secret. Any actual
    encrypt/decrypt call without a configured key raises a clear error.
    """

    def __init__(self, key: str, previous: Sequence[str] = ()) -> None:
        if not key:
            raise TokenCipherNotConfigured(
                "M365_TOKEN_ENCRYPTION_KEY is empty. Generate via "
                '`python -c "from cryptography.fernet import Fernet; '
                'print(Fernet.generate_key().decode())"` and set in Coolify secrets.'
            )
        secrets = (key, *previous)
        fernets: list[Fernet] = []
        for position, secret in enumerate(secrets):
            try:
                fernets.append(Fernet(secret.encode("utf-8")))
            except (ValueError, TypeError, AttributeError) as exc:
                # Never the value — only which setting and which position.
                where = (
                    "M365_TOKEN_ENCRYPTION_KEY"
                    if position == 0
                    else f"{PREVIOUS_KEYS_SETTING} (entry {position})"
                )
                raise TokenCipherNotConfigured(
                    f"{where} is not a valid Fernet key "
                    "(must be 32 url-safe base64-encoded bytes)."
                ) from exc
        self._secrets = secrets
        self._fernets = tuple(fernets)
        self._multi = MultiFernet(fernets)

    @property
    def previous_count(self) -> int:
        return len(self._fernets) - 1

    def encrypt(self, plaintext: str) -> str:
        if plaintext is None:
            raise ValueError("encrypt() received None")
        return self._multi.encrypt(plaintext.encode("utf-8")).decode("utf-8")

    def decrypt(self, ciphertext: str) -> str:
        if not ciphertext:
            raise ValueError("decrypt() received empty ciphertext")
        try:
            return self._multi.decrypt(ciphertext.encode("utf-8")).decode("utf-8")
        except InvalidToken as exc:
            raise TokenCipherNotConfigured(
                "Failed to decrypt token — no configured key matches. "
                "User must reconnect."
            ) from exc

    def key_index(self, ciphertext: str) -> Optional[int]:
        """0 = current key, n = n-th previous key, ``None`` = no key decrypts it."""

        if not ciphertext:
            return None
        token = ciphertext.encode("utf-8")
        for index, fernet in enumerate(self._fernets):
            try:
                fernet.decrypt(token)
            except InvalidToken:
                continue
            return index
        return None

    def rotate(self, ciphertext: str) -> str:
        """Same plaintext, encrypted with the current key (Fernet timestamp kept)."""

        try:
            return self._multi.rotate(ciphertext.encode("utf-8")).decode("utf-8")
        except InvalidToken as exc:
            raise TokenCipherNotConfigured(
                "Failed to re-encrypt token — no configured key matches."
            ) from exc

    def fingerprints(self, purpose: bytes, value: str) -> tuple[str, ...]:
        """HMAC-SHA256 of ``value`` under every key, the current key first.

        The HMAC key is ``sha256(purpose + key)`` — a separate purpose per
        fingerprint, so a fingerprint is never the encryption key. Write the
        first one; compare against all of them (a fingerprint written before
        a rotation matches a previous key until the rotation script rewrites it).
        """

        data = value.encode("utf-8")
        return tuple(
            hmac.new(
                hashlib.sha256(purpose + secret.encode("utf-8")).digest(),
                data,
                hashlib.sha256,
            ).hexdigest()
            for secret in self._secrets
        )


@lru_cache(maxsize=1)
def get_token_cipher() -> TokenCipher:
    """Lazy singleton. Cached so the keys are parsed once per process."""
    return TokenCipher(
        settings.M365_TOKEN_ENCRYPTION_KEY,
        parse_key_list(settings.M365_TOKEN_ENCRYPTION_KEY_PREVIOUS),
    )
