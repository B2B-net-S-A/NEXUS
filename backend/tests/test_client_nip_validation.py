"""Pole NIP w formularzu klienta: suma kontrolna i postać w rejestrze. Dane fikcyjne."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.schemas.client import ClientCreate, ClientUpdate
from app.services.order_client_identity import client_registry_number


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("1111111111", "1111111111"),
        ("111-111-11-11", "1111111111"),
        ("PL 1111111111", "1111111111"),
        ("fi12345678", "FI12345678"),
        ("FR1A123456789", "FR1A123456789"),
        ("", None),
        ("   ", None),
        (None, None),
    ],
)
def test_valid_numbers_are_stored_in_registry_form(raw, expected) -> None:
    assert client_registry_number(raw) == expected


@pytest.mark.parametrize(
    "raw, phrase",
    [
        ("1111111112", "sumę kontrolną"),
        ("123456", "10 cyfr"),
        ("FR1", "VAT UE"),
        ("nie wiem", "VAT UE"),
    ],
)
def test_bad_number_is_refused_with_a_polish_reason(raw, phrase) -> None:
    with pytest.raises(ValueError, match=phrase):
        client_registry_number(raw)


def test_both_forms_refuse_bad_checksum_without_pydantic_prefix() -> None:
    with pytest.raises(ValidationError) as error:
        ClientUpdate(nip="1111111112")
    assert error.value.errors()[0]["msg"] == "Ten NIP ma niepoprawną sumę kontrolną."
    with pytest.raises(ValidationError):
        ClientCreate(name="Firma", nip="1111111112")


def test_blank_nip_clears_the_field() -> None:
    assert ClientUpdate(nip="").nip is None
