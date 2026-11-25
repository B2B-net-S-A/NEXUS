"""Znaczniki zamiast danych osób w tekście do modelu (dane fikcyjne)."""

from __future__ import annotations

import pytest

from app.services.legal.pseudonymize import Entity, mask, unknown_tokens, unmask

# Numery z poprawną cyfrą kontrolną, niczyje.
NIP = "5260250274"
PESEL = "44051401359"


def test_given_values_become_tokens_and_come_back() -> None:
    text = "Jan Testowy (NIP 526-025-02-74) prowadzi Testowa Firma sp. z o.o."
    masked, mapping = mask(
        text,
        [
            Entity("PARTNER", "Jan Testowy", inflect=True),
            Entity("NIP", NIP),
            Entity("FIRMA", "Testowa Firma sp. z o.o."),
        ],
    )
    assert masked == "[PARTNER] (NIP [NIP]) prowadzi [FIRMA]"
    assert mapping == {
        "[PARTNER]": "Jan Testowy",
        "[NIP]": NIP,
        "[FIRMA]": "Testowa Firma sp. z o.o.",
    }
    assert (
        unmask(masked, mapping)
        == "Jan Testowy (NIP 5260250274) prowadzi Testowa Firma sp. z o.o."
    )


def test_inflected_name_and_bare_surname_are_masked() -> None:
    masked, mapping = mask(
        "Pismo do Jana Testowego. Pan Testowy potwierdził odbiór.",
        [Entity("PARTNER", "Jan Testowy", inflect=True)],
    )
    assert "Testow" not in masked and "Jana" not in masked
    assert masked.count("[PARTNER]") == 2


def test_second_distinct_value_of_a_label_gets_a_number() -> None:
    masked, mapping = mask(
        "Anna Próbna i Ewa Wzorcowa",
        [Entity("OSOBA", "Anna Próbna"), Entity("OSOBA", "Ewa Wzorcowa")],
    )
    assert masked == "[OSOBA] i [OSOBA_2]"
    assert mapping["[OSOBA_2]"] == "Ewa Wzorcowa"


def test_detects_identifiers_that_were_not_given() -> None:
    text = (
        f"PESEL {PESEL}, NIP {NIP}, e-mail jan.testowy@example.com, tel. +48 600 100 200, "
        "konto PL61 1090 1014 0000 0712 1981 2874."
    )
    masked, mapping = mask(text)
    for token in ("[PESEL]", "[NIP]", "[EMAIL]", "[TELEFON]", "[RACHUNEK]"):
        assert token in masked, (token, masked)
    assert PESEL not in masked and NIP not in masked and "example.com" not in masked
    assert unmask(masked, mapping) == text


def test_numbers_with_wrong_check_digit_stay() -> None:
    masked, mapping = mask("Numer sprawy 1234567890 i 12345678901.")
    assert masked == "Numer sprawy 1234567890 i 12345678901."
    assert mapping == {}


def test_detection_can_be_turned_off() -> None:
    masked, _mapping = mask(f"NIP {NIP}", detect=False)
    assert masked == f"NIP {NIP}"


def test_unknown_tokens_from_the_model_are_reported_and_left() -> None:
    mapping = {"[PARTNER]": "Jan Testowy"}
    text = "Szanowny [PARTNER], zgodnie z [ADRES] i [ADRES] …"
    assert unknown_tokens(text, mapping) == ["[ADRES]"]
    assert (
        unmask(text, mapping) == "Szanowny Jan Testowy, zgodnie z [ADRES] i [ADRES] …"
    )


def test_label_must_be_letters() -> None:
    with pytest.raises(ValueError):
        mask("x", [Entity("partner name", "Jan")])


def test_value_ending_with_a_dot_does_not_double_the_full_stop() -> None:
    mapping = {"[DATA_ROZWIAZANIA]": "31 stycznia 2027 r.", "[PARTNER]": "Jan Testowy"}
    text = "Umowa rozwiązuje się z dniem [DATA_ROZWIAZANIA]. Adresat: [PARTNER]."
    assert unmask(text, mapping) == (
        "Umowa rozwiązuje się z dniem 31 stycznia 2027 r. Adresat: Jan Testowy."
    )


def test_email_with_the_surname_is_masked_whole():
    # Przegląd 25.11: maska nazwiska rozcinała adres („jan.[PARTNER]@example.com”).
    masked, mapping = mask(
        "Kontakt: jan.testowy@example.com.", [Entity("PARTNER", "Jan Testowy", inflect=True)]
    )
    assert "example.com" not in masked and "testowy" not in masked.lower()
    assert unmask(masked, mapping) == "Kontakt: jan.testowy@example.com."
