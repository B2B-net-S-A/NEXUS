"""Rozpoznanie klienta z PDF-a: numer rejestrowy ∩ rejestr → markery → domena.

Fixture'y są SYNTETYCZNE — zachowują układ realnych dokumentów (etykieta nad
numerem, numer przełamany myślnikiem, NIP-y osób trzecich), ale nazwy i numery
są zmyślone z poprawną sumą kontrolną. Realny korpus zostaje poza repo.
"""

from app.services.order_client_identity import (
    ClientMarkers,
    ClientRegistry,
    fi_business_id_valid,
    identify_client,
    nip_checksum_valid,
    normalize_registry_id,
    registry_ids_in_text,
)
from app.services.order_policies.known_clients import (
    build_registry_from_known_clients,
)

# Syntetyczne NIP-y z poprawną sumą kontrolną (policzone, nie przepisane).
BANK_A = "1234563218"
BANK_B = "5260001246"
SIGNATURE_VENDOR = "7010001453"  # „Autenti-like" — obecny na karcie podpisu
OWN = "5711707392"


def _registry(**extra):
    return ClientRegistry(
        by_registry_id={BANK_A: "bank_a", BANK_B: "bank_b"},
        markers={
            "nordic": ClientMarkers(
                all_of=(r"call off agreement", r"nordic bank"),
                foreign_registry_ids=frozenset({"FI12345678"}),
            ),
            "cardiff": ClientMarkers(
                all_of=(r"zamowienie z dnia", r"umowy ramowej z dnia 3 lipca 2017"),
            ),
        },
        sender_domains={"bank-a.example": "bank_a"},
        **extra,
    )


class TestNormalizationAndChecksum:
    def test_nip_checksum(self):
        assert nip_checksum_valid(BANK_A)
        assert nip_checksum_valid(BANK_B)
        assert not nip_checksum_valid("1234567890")
        assert not nip_checksum_valid("123")

    def test_normalize_strips_pl_and_separators(self):
        assert normalize_registry_id("PL 123-456-32-18") == BANK_A
        assert normalize_registry_id("NIP: 123 456 32 18") == BANK_A

    def test_foreign_prefix_is_part_of_identity(self):
        assert normalize_registry_id("FI12345678") == "FI12345678"


class TestRegistryIdsInText:
    def test_finds_labelled_and_unlabelled_numbers_and_drops_own(self):
        text = f"Zamawiający: Bank A S.A., NIP: {BANK_A}\nWykonawca: B2B.NET NIP {OWN}"
        assert registry_ids_in_text(text) == [BANK_A]

    def test_joins_number_broken_across_lines(self):
        # Credit Agricole: „NIP: 657-008-\n22-74"
        text = "Zleceniodawca … NIP: 123-456-\n32-18, Regon: 290512345"
        assert registry_ids_in_text(text) == [BANK_A]

    def test_label_on_previous_line(self):
        # EY/Fieldglass: „VAT\nPL5252314195"
        text = f"Bill To Firma\nVAT\nPL{BANK_B}\nNew"
        assert registry_ids_in_text(text) == [BANK_B]

    def test_order_number_with_valid_checksum_is_harmless_noise(self):
        # Suma kontrolna to filtr szumu, nie dowód — przecięcie decyduje.
        text = "ZLECENIE nr 4500724536\nNIP 5271037727"
        found = registry_ids_in_text(text)
        assert "5271037727" in found  # prawdziwy NIP (Polkomtel) przechodzi
        # 4500724536 też przechodzi checksum — i to jest OK, bo nie ma go w rejestrze.

    def test_rejects_invalid_checksum(self):
        assert registry_ids_in_text("NIP 1234567890") == []


class TestIdentifyClient:
    def test_single_registry_hit_wins(self):
        text = f"Bank A S.A. NIP {BANK_A}\nB2B.NET NIP {OWN}"
        r = identify_client(text, _registry())
        assert (r.client_key, r.method) == ("bank_a", "registry_id")

    def test_third_party_ids_do_not_confuse_intersection(self):
        # Karta podpisu z NIP-em dostawcy + cztery firmy konsultantów w załączniku:
        # żaden nie jest w rejestrze, więc przecięcie ma dokładnie jeden element.
        text = (
            f"Zamawiający Bank A NIP {BANK_A}\n"
            f"Podpisano przez Vendor sp. z o.o. NIP {SIGNATURE_VENDOR}\n"
            "Podwykonawca 1 NIP 1112223332\nPodwykonawca 2 NIP 9998887778\n"
        )
        r = identify_client(text, _registry())
        assert r.client_key == "bank_a"

    def test_two_known_clients_in_one_document_is_ambiguous_not_a_guess(self):
        text = f"NIP {BANK_A} … NIP {BANK_B}"
        r = identify_client(text, _registry())
        assert r.client_key is None
        assert r.candidates == ("bank_a", "bank_b")
        assert "więcej niż jednego" in r.reason

    def test_foreign_registry_id_counts_as_registry_method(self):
        # Nordea: „VAT number: FI…" bez polskiego NIP-u.
        text = "Call Off Agreement\nNordic Bank Abp\n(VAT number: FI12345678)"
        r = identify_client(text, _registry())
        assert (r.client_key, r.method) == ("nordic", "registry_id")

    def test_markers_when_no_registry_id(self):
        text = "Zamówienie z dnia 27.04.2026 do umowy ramowej z dnia 3 lipca 2017"
        r = identify_client(text, _registry())
        assert (r.client_key, r.method) == ("cardiff", "marker")

    def test_markers_are_diacritic_insensitive(self):
        text = "ZAMOWIENIE Z DNIA 1.1.2026 do umowy ramowej z dnia 3 lipca 2017"
        assert identify_client(text, _registry()).client_key == "cardiff"

    def test_sender_domain_is_last_resort_and_labelled_as_such(self):
        r = identify_client(
            "brak czegokolwiek", _registry(), sender_email="x@bank-a.example"
        )
        assert (r.client_key, r.method) == ("bank_a", "sender_domain")
        assert "najsłabszy" in r.reason

    def test_unrecognized_is_a_normal_outcome(self):
        r = identify_client(
            "Zamówienie nr 1", _registry(), sender_email="x@unknown.example"
        )
        assert r.client_key is None and r.method is None and r.candidates == ()

    def test_registry_id_beats_markers_even_when_markers_also_match(self):
        text = f"Zamówienie z dnia 1.1.2026 do umowy ramowej z dnia 3 lipca 2017 NIP {BANK_B}"
        r = identify_client(text, _registry())
        assert (r.client_key, r.method) == ("bank_b", "registry_id")


class TestFinnishBusinessId:
    """Zgłoszenie 05.10.2026 (zam. Nordei 287341): nagłówek Call Off Agreement
    niesie „Company number 2858394-9" — fiński Business ID w zapisie krajowym.
    Bez prefiksu „FI" odpadał jak zły polski NIP, Nordea była rozpoznawana tylko
    markerem i żadne jej zamówienie bez linii VAT nie mogło przejść automatem.
    Numer Nordea Bank Abp jest publiczny (rejestr handlowy Finlandii)."""

    NORDEA_HEADER = (
        "Call Off Agreement\n"
        'Company name (hereinafter referred to as "Nordea") Company number\n'
        "Nordea Bank Abp 2858394-9\n"
        "Frame Agreement number: CW2117535\n"
    )

    def test_checksum(self):
        assert fi_business_id_valid("28583949")
        assert not fi_business_id_valid("28583948")
        assert not fi_business_id_valid("1234567")

    def test_national_form_becomes_vat_form(self):
        assert registry_ids_in_text("Nordea Bank Abp 2858394-9") == ["FI28583949"]

    def test_wrong_check_digit_is_not_an_id(self):
        assert registry_ids_in_text("Nordea Bank Abp 2858394-8") == []

    def test_hyphen_after_country_prefix(self):
        assert registry_ids_in_text("VAT: FI-28583949") == ["FI28583949"]

    def test_postal_code_with_country_prefix_is_not_an_id(self):
        assert registry_ids_in_text("Satamaradankatu 5, FI-00020 NORDEA") == []

    def test_header_alone_confirms_nordea_by_registry_id(self):
        r = identify_client(self.NORDEA_HEADER, build_registry_from_known_clients())
        assert (r.client_key, r.method) == ("nordea", "registry_id")

    def test_header_and_vat_line_are_one_id_not_ambiguity(self):
        text = self.NORDEA_HEADER + "(VAT number: FI28583949)\n"
        r = identify_client(text, build_registry_from_known_clients())
        assert (r.client_key, r.method) == ("nordea", "registry_id")
        assert r.registry_ids_found == ("FI28583949",)

    def test_other_finnish_company_is_not_nordea(self):
        # Poprawny Business ID innej firmy: przecięcie z rejestrem odfiltrowuje
        # go, więc dokument zostaje przy markerach (bez awansu do numeru).
        assert fi_business_id_valid("12345671")
        text = "Call Off Agreement\nNordea Bank Abp\nPartner Oy 1234567-1\n"
        r = identify_client(text, build_registry_from_known_clients())
        assert r.registry_ids_found == ("FI12345671",)
        assert (r.client_key, r.method) == ("nordea", "marker")
