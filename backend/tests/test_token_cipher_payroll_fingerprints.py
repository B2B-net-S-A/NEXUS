"""Skróty rachunku i PESEL-u przy rotacji klucza szyfrowania (25.11.2026).

Skrót zapisany przed rotacją ma klucz wyprowadzony z poprzedniego klucza:
porównania biorą wszystkie skonfigurowane klucze, zapis tylko bieżący.
Bez bazy. Dane fikcyjne (repo jest publiczne).
"""

from __future__ import annotations

import hashlib
import hmac

import pytest
from cryptography.fernet import Fernet

from app.core.encryption import TokenCipher
from app.models.hr_settlement import PayrollPayment
from app.services.hr import billing_details
from app.services.hr.bank import batches
from app.services.hr.bank.accounts import iban_check_digits
from app.services.hr.payroll_lists import pesel


def _account(sort_code: str, number: str) -> str:
    """Fikcyjny rachunek NRB (bank 9999xxxx nie istnieje), jak w testach płatności."""

    bban = f"{sort_code}{number.zfill(16)}"
    return iban_check_digits(bban) + bban


ACCOUNT = _account("99990001", "1234")
OTHER = _account("99990002", "5678")


def _key() -> str:
    return Fernet.generate_key().decode("utf-8")


@pytest.fixture
def use_cipher(monkeypatch):
    def use(cipher: TokenCipher) -> None:
        for module in (billing_details, pesel):
            monkeypatch.setattr(module, "get_token_cipher", lambda: cipher)

    return use


def test_account_fingerprint_keeps_the_formula_of_stored_batches(use_cipher) -> None:
    key = _key()
    use_cipher(TokenCipher(key))
    derived = hashlib.sha256(b"nexus-hr-payee-account:" + key.encode()).digest()

    assert billing_details.account_fingerprint(ACCOUNT) == (
        hmac.new(derived, ACCOUNT.encode(), hashlib.sha256).hexdigest()
    )


def test_pesel_fingerprint_keeps_the_formula_of_stored_records(use_cipher) -> None:
    key = _key()
    use_cipher(TokenCipher(key))
    derived = hashlib.sha256(b"nexus-payroll-pesel:" + key.encode()).digest()

    assert pesel.fingerprint("90030312403") == (
        hmac.new(derived, b"90030312403", hashlib.sha256).hexdigest()
    )


def test_after_rotation_the_old_fingerprint_is_second_and_writes_use_the_new(
    use_cipher,
) -> None:
    old, new = _key(), _key()
    use_cipher(TokenCipher(old))
    old_account = billing_details.account_fingerprint(ACCOUNT)
    old_pesel = pesel.fingerprint("90030312403")

    use_cipher(TokenCipher(new, [old]))

    assert billing_details.account_fingerprints(ACCOUNT)[1] == old_account
    assert billing_details.account_fingerprint(ACCOUNT) != old_account
    assert pesel.fingerprints("90030312403")[1] == old_pesel
    assert pesel.fingerprint("90030312403") != old_pesel


def test_batch_from_before_the_rotation_still_matches_the_same_account(
    use_cipher,
) -> None:
    old, new = _key(), _key()
    use_cipher(TokenCipher(old))
    payment = PayrollPayment(
        kind="transfer_batch",
        counterparty_hmac=billing_details.account_fingerprint(ACCOUNT),
    )

    use_cipher(TokenCipher(new, [old]))
    assert batches._same_account(ACCOUNT, payment)
    # Podmieniony rachunek dalej blokuje pobranie.
    assert not batches._same_account(OTHER, payment)

    # Bez poprzedniego klucza skrót sprzed rotacji już nie pasuje — dlatego
    # skrypt rotacji przelicza go, zanim poprzedni klucz zniknie.
    use_cipher(TokenCipher(new))
    assert not batches._same_account(ACCOUNT, payment)
