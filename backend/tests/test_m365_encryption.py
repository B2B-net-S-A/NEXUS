"""Unit tests for `app.core.encryption.TokenCipher`.

These stay pure-function; no DB, no network.
"""

from __future__ import annotations

import pytest
from cryptography.fernet import Fernet

from app.core.encryption import TokenCipher, TokenCipherNotConfigured


@pytest.fixture
def valid_key() -> str:
    return Fernet.generate_key().decode("utf-8")


def test_roundtrip_plaintext(valid_key: str) -> None:
    cipher = TokenCipher(valid_key)
    plaintext = "super-secret-refresh-token"
    ct = cipher.encrypt(plaintext)

    assert ct != plaintext
    assert cipher.decrypt(ct) == plaintext


def test_two_encryptions_produce_different_ciphertext(valid_key: str) -> None:
    """Fernet uses a random IV per call, so encrypt(x) != encrypt(x)."""
    cipher = TokenCipher(valid_key)
    ct1 = cipher.encrypt("abc")
    ct2 = cipher.encrypt("abc")
    assert ct1 != ct2
    assert cipher.decrypt(ct1) == "abc"
    assert cipher.decrypt(ct2) == "abc"


def test_empty_key_raises() -> None:
    with pytest.raises(TokenCipherNotConfigured):
        TokenCipher("")


def test_invalid_key_raises() -> None:
    with pytest.raises(TokenCipherNotConfigured):
        TokenCipher("not-a-valid-fernet-key")


def test_key_rotation_invalidates_old_ciphertext(valid_key: str) -> None:
    cipher = TokenCipher(valid_key)
    ct = cipher.encrypt("x")

    new_cipher = TokenCipher(Fernet.generate_key().decode("utf-8"))
    with pytest.raises(TokenCipherNotConfigured):
        new_cipher.decrypt(ct)


def test_decrypt_empty_raises(valid_key: str) -> None:
    cipher = TokenCipher(valid_key)
    with pytest.raises(ValueError):
        cipher.decrypt("")


def test_encrypt_none_raises(valid_key: str) -> None:
    cipher = TokenCipher(valid_key)
    with pytest.raises(ValueError):
        cipher.encrypt(None)  # type: ignore[arg-type]
