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


# ── Rotacja klucza (M365_TOKEN_ENCRYPTION_KEY_PREVIOUS, 25.11.2026) ─────────


def _key() -> str:
    return Fernet.generate_key().decode("utf-8")


def test_data_encrypted_with_the_old_key_reads_after_rotation() -> None:
    old, new = _key(), _key()
    stored = TokenCipher(old).encrypt("refresh-token")

    rotated = TokenCipher(new, [old])

    assert rotated.decrypt(stored) == "refresh-token"
    # Nowe zapisy idą bieżącym kluczem: bez poprzedniego też się czytają.
    fresh = rotated.encrypt("refresh-token-2")
    assert TokenCipher(new).decrypt(fresh) == "refresh-token-2"
    with pytest.raises(TokenCipherNotConfigured):
        TokenCipher(old).decrypt(fresh)


def test_key_index_tells_which_key_reads_a_value() -> None:
    old, new, unknown = _key(), _key(), _key()
    cipher = TokenCipher(new, [old])

    assert cipher.key_index(cipher.encrypt("a")) == 0
    assert cipher.key_index(TokenCipher(old).encrypt("a")) == 1
    assert cipher.key_index(TokenCipher(unknown).encrypt("a")) is None
    assert cipher.key_index("") is None
    assert cipher.key_index("not-a-token") is None
    assert cipher.previous_count == 1


def test_rotate_moves_a_value_to_the_current_key() -> None:
    old, new = _key(), _key()
    cipher = TokenCipher(new, [old])
    stored = TokenCipher(old).encrypt("secret")

    moved = cipher.rotate(stored)

    assert TokenCipher(new).decrypt(moved) == "secret"
    assert cipher.key_index(moved) == 0
    with pytest.raises(TokenCipherNotConfigured):
        cipher.rotate(TokenCipher(_key()).encrypt("secret"))


def test_invalid_previous_key_names_the_position_not_the_value() -> None:
    bad = "definitely-not-a-fernet-key"
    with pytest.raises(TokenCipherNotConfigured) as exc:
        TokenCipher(_key(), [_key(), bad])

    message = str(exc.value)
    assert "M365_TOKEN_ENCRYPTION_KEY_PREVIOUS (entry 2)" in message
    assert bad not in message


def test_previous_setting_is_a_comma_separated_list() -> None:
    from app.core.encryption import parse_key_list

    assert parse_key_list("") == ()
    assert parse_key_list(None) == ()
    assert parse_key_list(" a ,, b ,") == ("a", "b")


def test_fingerprint_with_the_current_key_matches_the_formula_before_rotation() -> None:
    """Skróty rachunku i PESEL-u zapisane przed tą zmianą muszą dalej pasować."""
    import hashlib
    import hmac

    old, new = _key(), _key()
    purpose = b"nexus-hr-payee-account:"

    def legacy(secret: str) -> str:
        key = hashlib.sha256(purpose + secret.encode()).digest()
        return hmac.new(key, b"12345", hashlib.sha256).hexdigest()

    assert TokenCipher(old).fingerprints(purpose, "12345") == (legacy(old),)
    assert TokenCipher(new, [old]).fingerprints(purpose, "12345") == (
        legacy(new),
        legacy(old),
    )


def test_get_token_cipher_reads_the_previous_keys_setting(monkeypatch) -> None:
    from app.core import encryption

    old, new = _key(), _key()
    stored = TokenCipher(old).encrypt("x")
    monkeypatch.setattr(encryption.settings, "M365_TOKEN_ENCRYPTION_KEY", new)
    monkeypatch.setattr(
        encryption.settings, "M365_TOKEN_ENCRYPTION_KEY_PREVIOUS", f" {old} "
    )
    encryption.get_token_cipher.cache_clear()
    try:
        cipher = encryption.get_token_cipher()
        assert cipher.decrypt(stored) == "x"
        assert cipher.key_index(cipher.encrypt("y")) == 0
    finally:
        monkeypatch.undo()
        encryption.get_token_cipher.cache_clear()
