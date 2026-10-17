"""Szyfrowanie tokenu KSeF kluczem publicznym Ministerstwa Finansów.

``POST /auth/ksef-token`` przyjmuje ciąg ``{token}|{timestampMs}`` (znacznik
czasu z ``POST /auth/challenge``) zaszyfrowany RSA-OAEP z SHA-256 (MGF1)
i zakodowany w Base64. Klucz wybieramy z ``GET /security/public-key-certificates``:
przeznaczenie ``KsefTokenEncryption``, ważny teraz, najnowszy. MF może
rotować klucze — przy odmowie „nieznany klucz” klient pobiera listę ponownie.
"""

from __future__ import annotations

import base64
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Iterable, Optional

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa

TOKEN_KEY_USAGE = "KsefTokenEncryption"


class PublicKeyError(ValueError):
    """Brak ważnego klucza do szyfrowania tokenu albo klucz nie jest RSA."""


@dataclass(frozen=True)
class TokenKey:
    public_key: rsa.RSAPublicKey
    public_key_id: Optional[str]
    valid_from: Optional[datetime]


def _instant(raw: Any) -> Optional[datetime]:
    if not isinstance(raw, str) or not raw:
        return None
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None


def _load_public_key(encoded: str) -> rsa.RSAPublicKey:
    der = base64.b64decode(encoded, validate=False)
    try:
        key = x509.load_der_x509_certificate(der).public_key()
    except ValueError:
        # Przykład w specyfikacji ma w polu „certificate” sam SubjectPublicKeyInfo.
        key = serialization.load_der_public_key(der)
    if not isinstance(key, rsa.RSAPublicKey):
        raise PublicKeyError("klucz do szyfrowania tokenu nie jest kluczem RSA")
    return key


def pick_token_key(certificates: Iterable[dict[str, Any]], now: datetime) -> TokenKey:
    """Najnowszy ważny klucz z przeznaczeniem ``KsefTokenEncryption``."""

    candidates: list[TokenKey] = []
    for item in certificates:
        if not isinstance(item, dict) or TOKEN_KEY_USAGE not in (
            item.get("usage") or []
        ):
            continue
        valid_from, valid_to = (
            _instant(item.get("validFrom")),
            _instant(item.get("validTo")),
        )
        if (valid_from and valid_from > now) or (valid_to and valid_to < now):
            continue
        try:
            key = _load_public_key(str(item.get("certificate") or ""))
        except (ValueError, TypeError):
            continue
        candidates.append(
            TokenKey(
                public_key=key,
                public_key_id=item.get("publicKeyId") or None,
                valid_from=valid_from,
            )
        )
    if not candidates:
        raise PublicKeyError("brak ważnego klucza KsefTokenEncryption")
    return max(
        candidates,
        key=lambda c: c.valid_from or datetime.min.replace(tzinfo=now.tzinfo),
    )


def encrypt_token(token: str, timestamp_ms: int, key: rsa.RSAPublicKey) -> str:
    plaintext = f"{token}|{timestamp_ms}".encode("utf-8")
    ciphertext = key.encrypt(
        plaintext,
        padding.OAEP(
            mgf=padding.MGF1(algorithm=hashes.SHA256()),
            algorithm=hashes.SHA256(),
            label=None,
        ),
    )
    return base64.b64encode(ciphertext).decode("ascii")
