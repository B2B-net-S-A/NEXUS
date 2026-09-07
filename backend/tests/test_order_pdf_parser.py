"""Testy jednostkowe parsera PDF zamówienia (``order_pdf_parser``).

Czysta logika (bez DB / bez sieci): normalizacja dat/kwot, regexowy fallback
(w tym okres BNP ``mc MM-RRRR_MM-RRRR``), normalizacja odpowiedzi Claude i reguły
niepewności. Bez klucza ANTHROPIC ``parse_order_document`` degraduje do regexu.
"""

from decimal import Decimal

import pytest

from app.services import order_pdf_parser as m
from app.services.order_pdf_parser import parse_order_document


class TestNormalizeDate:
    def test_iso_full(self):
        assert m._normalize_date("2026-06-01", end=False) == "2026-06-01"

    def test_iso_single_digit_padded(self):
        assert m._normalize_date("2026-6-1", end=False) == "2026-06-01"

    def test_eu_formats(self):
        assert m._normalize_date("01.06.2026", end=False) == "2026-06-01"
        assert m._normalize_date("1/6/2026", end=False) == "2026-06-01"
        assert m._normalize_date("15-07-2026", end=False) == "2026-07-15"

    def test_month_precision_start_is_first_day(self):
        assert m._normalize_date("2026-06", end=False) == "2026-06-01"

    def test_month_precision_end_is_last_day(self):
        assert m._normalize_date("2026-06", end=True) == "2026-06-30"
        assert m._normalize_date("2026-02", end=True) == "2026-02-28"  # non-leap
        assert m._normalize_date("2028-02", end=True) == "2028-02-29"  # leap

    def test_invalid_returns_none(self):
        assert m._normalize_date("garbage", end=False) is None
        assert m._normalize_date("2026-13", end=False) is None
        assert m._normalize_date("2026-02-30", end=False) is None
        assert m._normalize_date(None, end=False) is None
        assert m._normalize_date(12345, end=False) is None


class TestNormalizeAmount:
    def test_int_and_float(self):
        assert m._normalize_amount(17000) == Decimal("17000")
        assert m._normalize_amount(164.375) == Decimal("164.375")

    def test_bool_rejected(self):
        # True/False nie są stawkami (bool jest podklasą int).
        assert m._normalize_amount(True) is None

    def test_plain_string(self):
        assert m._normalize_amount("17000") == Decimal("17000")

    def test_pl_decimal_comma(self):
        assert m._normalize_amount("17000,50") == Decimal("17000.50")

    def test_pl_thousands_dot_decimal_comma(self):
        assert m._normalize_amount("17.000,50") == Decimal("17000.50")

    def test_us_thousands_comma_decimal_dot(self):
        assert m._normalize_amount("17,000.50") == Decimal("17000.50")

    def test_strips_currency_and_spaces(self):
        assert m._normalize_amount("17 000 PLN") == Decimal("17000")

    def test_garbage_returns_none(self):
        assert m._normalize_amount("abc") is None
        assert m._normalize_amount(None) is None
        assert m._normalize_amount("") is None


class TestCleanHelpers:
    def test_currency_uppercased_three_letters(self):
        assert m._clean_currency("pln") == "PLN"
        assert m._clean_currency("EUR") == "EUR"
        assert m._clean_currency("złoty") is None  # != 3 litery

    def test_unit_mapping(self):
        assert m._clean_unit("PLN/MD") is None  # nie sam token jednostki
        assert m._clean_unit("md") == "day"
        assert m._clean_unit("godz") == "hour"
        assert m._clean_unit("miesiąc") == "month"

    def test_title_capped(self):
        assert m._clean_str("  PO-123  ") == "PO-123"
        assert m._clean_str("x" * 400) == "x" * 255


class TestRegexFallback:
    def test_bnp_month_range(self):
        r = m._extract_with_regex("Zamówienie mc 06-2026_12-2026 dla klienta BNP")
        assert r.start_date == "2026-06-01"
        assert r.end_date == "2026-12-31"
        assert r.uncertain is True
        assert r.source == "regex"

    def test_generic_two_dates(self):
        r = m._extract_with_regex("Start date: 2026-01-15  End date: 2026-07-15")
        assert r.start_date == "2026-01-15"
        assert r.end_date == "2026-07-15"

    def test_amount_with_currency(self):
        r = m._extract_with_regex("Stawka 17000 PLN netto / mies")
        assert r.rate_client == Decimal("17000")


class TestNordeaCallOffNumber:
    def test_exact_field_wins_over_other_numbers(self):
        text = """
        Offer number: OFF-998877
        Project number: 123456
        Call Off Agreement number: COA-4500030222/26
        """
        result = m.OrderExtraction(
            title="OFF-998877",
            confidence={"title": 0.42},
            uncertain=True,
            uncertain_reasons=["Niska pewność numeru/tytułu zamówienia"],
        )

        enforced = m.enforce_nordea_order_number(result, text)

        assert enforced.title == "COA-4500030222/26"
        assert enforced.confidence["title"] == 1.0
        assert not any(
            "numeru/tytułu zamówienia" in reason
            for reason in enforced.uncertain_reasons
        )

    def test_missing_call_off_field_never_keeps_another_number(self):
        result = m.OrderExtraction(
            title="PROJECT-123",
            confidence={"title": 0.99},
            uncertain=False,
        )

        enforced = m.enforce_nordea_order_number(result, "Project number: PROJECT-123")

        assert enforced.title is None
        assert "title" not in enforced.confidence
        assert enforced.uncertain is True
        assert any("Call Off Agreement number" in r for r in enforced.uncertain_reasons)

    @pytest.mark.parametrize(
        "label",
        [
            "Call Off Agreement number:",
            "Call-Off Agreement number:",
            "Call-off agreement no.",
            "Calloff Agreement nr",
            "Call Off Agreement #",
            "Call Off Agreement:",
            "Call Off Agreement number",
        ],
    )
    def test_label_spelling_variants_are_all_recognised(self, label):
        """Zapis etykiety nie jest stały, a jej niedopasowanie ma cichy koszt.

        Polityka jest fail-closed: nierozpoznana etykieta CZYŚCI numer. Przy
        niewłączonej bramce klienta zostaje wtedy numer wybrany przez model —
        czyli zwykle „Frame Agreement number", bo stoi w dokumencie wyżej
        i wygląda równie oficjalnie. Dokładnie to zgłosił użytkownik.
        """
        assert (
            m.nordea_call_off_agreement_number(f"{label} COA-4500030222")
            == "COA-4500030222"
        )

    def test_frame_agreement_number_never_becomes_the_order_number(self):
        """Numer UMOWY RAMOWEJ nie jest numerem zamówienia — nigdy."""
        text = """
        Frame Agreement number: FA-4400011111
        Call Off Agreement number: COA-4500030222
        """
        assert m.nordea_call_off_agreement_number(text) == "COA-4500030222"
        # Kontrola negatywna: sam Frame Agreement nie daje numeru w ogóle,
        # więc polityka czyści pole i prosi o ręczne uzupełnienie.
        assert (
            m.nordea_call_off_agreement_number("Frame Agreement number: FA-1") is None
        )
        assert m.nordea_frame_agreement_number("Frame Agreement number: FA-1") == "FA-1"

    @pytest.mark.parametrize(
        ("text", "expected"),
        [
            # Wartość w tym samym wierszu, w następnym, z dodatkowymi spacjami.
            ("Call Off Agreement number: 123456", "123456"),
            ("Call-Off Agreement no.\n654321", "654321"),
            ("Call off agreement number :\t 100200 \nInne pole", "100200"),
            # Za etykietą stoi SŁOWO (drugi nagłówek kolumny, „nr"), a numer
            # dopiero dalej. To jest zgłoszony objaw: „pobiera losowe słowa".
            ("Call Off Agreement number  nr   345678", "345678"),
            ("Call Off Agreement number\nNumer\n778899", "778899"),
            # Data przechodzi test „zawiera cyfrę", a numerem nie jest.
            ("Call Off Agreement number\nData 2026-04-01\n456789", "456789"),
        ],
    )
    def test_value_must_contain_a_digit_and_may_sit_below_the_label(
        self, text, expected
    ):
        """Numer to wartość pola, nie „pierwszy token za etykietą".

        Poprzednia reguła brała dowolny token pasujący do klasy znaków
        dopuszczalnych w numerze — a ta klasa z ``IGNORECASE`` pasuje też na
        litery, więc do pola „numer zamówienia" trafiało zwykłe słowo
        z dokumentu.
        """

        assert m.nordea_call_off_agreement_number(text) == expected

    def test_two_column_header_layout_fails_closed(self):
        """Nagłówki obok siebie, wartości pod nimi — nie da się przypisać.

        W takim układzie pierwsza liczba za etykietą Call-Off należy do
        SĄSIEDNIEJ kolumny. Reguła zostawia pole puste (operator dostaje
        „sprawdź numer") zamiast wpisać numer umowy ramowej jako numer
        zamówienia — czyli jako fakt, którego nikt nie potwierdził.
        """

        text = "Call Off Agreement number   Frame Agreement number\n111111   222222"
        assert m.nordea_call_off_agreement_number(text) is None


class TestBankPocztowyOrderNumber:
    def test_numer_pisma_wins_over_zamowienie_nr(self):
        text = """
        Numer pisma: BP/DIT/2026/0451
        Zamówienie nr 445/2026
        """
        assert m.bank_pocztowy_order_number(text) == "BP/DIT/2026/0451"

    def test_fallback_to_zamowienie_nr(self):
        assert (
            m.bank_pocztowy_order_number("Zamówienie nr 445/2026 z dnia 01.02.2026")
            == "445/2026"
        )

    def test_zamowienie_without_diacritics_and_uppercase(self):
        # Ekstrakcja tekstu z PDF potrafi zgubić diakrytyki; nagłówki bywają
        # wersalikami.
        assert m.bank_pocztowy_order_number("ZAMOWIENIE NR: 71/2026") == "71/2026"

    def test_nr_pisma_abbreviation(self):
        assert m.bank_pocztowy_order_number("Nr pisma: DIT.271.45.2026") == (
            "DIT.271.45.2026"
        )

    def test_empty_label_does_not_swallow_next_label(self):
        # Puste pole „Numer pisma” + następna linia zaczynająca się literami:
        # guard na cyfrę odrzuca „wartość” bez cyfr zamiast łapać początek
        # kolejnej etykiety. Hierarchia schodzi wtedy do „Zamówienie nr”.
        text = "Numer pisma:\nZamówienie nr 512/2026"
        assert m.bank_pocztowy_order_number(text) == "512/2026"

    def test_neither_field_returns_none(self):
        assert m.bank_pocztowy_order_number("Umowa ramowa nr 9/2024") is None


class TestBankPocztowyPolicy:
    def _doc(self) -> str:
        return (
            "Bank Pocztowy S.A.\n"
            "Numer pisma: BP/DIT/2026/0451\n"
            "Zamówienie nr 445/2026\n"
            "Okres realizacji: od 2026-09-01 do 2026-12-31\n"
            "Wynagrodzenie: 1600*1,23*20\n"
        )

    def test_clean_document_converts_rate_and_stays_quiet(self):
        # Model wybrał brutto (1600 × 1,23) — wzór z dokumentu wymusza netto.
        result = m.OrderExtraction(
            title="445/2026",
            start_date="2026-09-01",
            end_date="2026-12-31",
            rate_client=Decimal("1968"),
            rate_unit="day",
            md_total=Decimal("20"),
            uncertain=True,
            uncertain_reasons=[
                "Jednostka stawki (dzień) wywnioskowana z kontekstu",
                "Cena 1600 jest kwotą netto przed VAT (mnożnik 1,23)",
            ],
            source="claude",
        )

        enforced = m.apply_bank_pocztowy_order_policy(result, self._doc())

        # Numer z hierarchii pól, nie z wyboru modelu.
        assert enforced.title == "BP/DIT/2026/0451"
        # Netto z wzoru ÷ 8: 1600 / 8 = 200 zł/h; oryginał MD zachowany.
        assert enforced.rate_client == Decimal("200.00")
        assert enforced.rate_client_md == Decimal("1600")
        assert enforced.rate_unit == "hour"
        # Liczba MD ze wzoru jest pomijana.
        assert enforced.md_total is None
        # Czysty odczyt w widełkach → ZERO komunikatów (wymóg ticketu).
        assert enforced.uncertain is False
        assert enforced.uncertain_reasons == []
        assert enforced.title_needs_review is False

    def test_rounding_is_always_up_to_two_decimals(self):
        result = m.OrderExtraction(rate_client=Decimal("1015"), source="claude")
        enforced = m.apply_bank_pocztowy_order_policy(
            result, "Numer pisma: BP/1/2026 od 2026-01-01 do 2026-06-30"
        )
        # 1015 / 8 = 126.875 → w górę → 126.88.
        assert enforced.rate_client == Decimal("126.88")
        assert enforced.rate_client_md == Decimal("1015")

    def test_hourly_rate_inside_band_has_no_warning(self):
        for md_rate in (Decimal("640"), Decimal("2400")):  # 80.00 i 300.00 zł/h
            result = m.OrderExtraction(
                rate_client=md_rate,
                start_date="2026-01-01",
                end_date="2026-06-30",
                source="claude",
            )
            enforced = m.apply_bank_pocztowy_order_policy(
                result, "Numer pisma: BP/2/2026"
            )
            assert enforced.uncertain_reasons == []
            assert enforced.uncertain is False

    def test_hourly_rate_below_band_warns(self):
        result = m.OrderExtraction(
            rate_client=Decimal("639"),  # 79.88 zł/h
            start_date="2026-01-01",
            end_date="2026-06-30",
            source="claude",
        )
        enforced = m.apply_bank_pocztowy_order_policy(result, "Numer pisma: BP/3/26")
        assert enforced.uncertain is True
        assert any(
            "Nietypowa stawka godzinowa" in r for r in enforced.uncertain_reasons
        )

    def test_hourly_rate_above_band_warns(self):
        result = m.OrderExtraction(
            rate_client=Decimal("2401"),  # 300.13 zł/h
            start_date="2026-01-01",
            end_date="2026-06-30",
            source="claude",
        )
        enforced = m.apply_bank_pocztowy_order_policy(result, "Numer pisma: BP/4/26")
        assert enforced.uncertain is True
        assert any(
            "Nietypowa stawka godzinowa" in r for r in enforced.uncertain_reasons
        )

    def test_missing_dates_produce_exact_message_and_keep_fields_empty(self):
        result = m.OrderExtraction(rate_client=Decimal("1600"), source="claude")
        enforced = m.apply_bank_pocztowy_order_policy(result, "Numer pisma: BP/5/26")
        assert enforced.start_date is None
        assert enforced.end_date is None
        assert "Nie znaleziono dat okresu zamówienia (od–do)" in (
            enforced.uncertain_reasons
        )
        assert enforced.uncertain is True

    def test_missing_number_clears_title_and_sets_review_flag(self):
        result = m.OrderExtraction(
            title="OFF-999",  # model wybrał numer oferty — polityka go odrzuca
            start_date="2026-01-01",
            end_date="2026-06-30",
            rate_client=Decimal("1600"),
            confidence={"title": 0.99},
            source="claude",
        )
        enforced = m.apply_bank_pocztowy_order_policy(
            result, "Umowa ramowa nr 9/2024, wynagrodzenie 1600 zł/MD"
        )
        assert enforced.title is None
        assert "title" not in enforced.confidence
        assert enforced.title_needs_review is True
        assert any("sprawdź numer zamówienia" in r for r in enforced.uncertain_reasons)
        assert enforced.uncertain is True

    def test_generic_noise_reasons_are_dropped(self):
        # Komunikaty o VAT / jednostce / liczbie MD / niskiej ufności znikają;
        # przy kompletnym odczycie zostaje cisza.
        result = m.OrderExtraction(
            title="ignored",
            start_date="2026-01-01",
            end_date="2026-06-30",
            rate_client=Decimal("1600"),
            rate_unit="day",
            md_total=Decimal("20"),
            uncertain=True,
            uncertain_reasons=[
                "Stawka może być w innej jednostce niż miesięczna — sprawdź przeliczenie",
                "Liczba 20 w wzorze może oznaczać liczbę dni roboczych/MD",
                "Cena 1600 jest kwotą netto przed VAT (mnożnik 1,23)",
            ],
            source="claude",
        )
        enforced = m.apply_bank_pocztowy_order_policy(
            result, "Numer pisma: BP/6/26\nod 2026-01-01 do 2026-06-30"
        )
        assert enforced.uncertain_reasons == []
        assert enforced.uncertain is False

    def test_regex_fallback_marker_survives_the_allowlist(self):
        # Jedyny generyczny komunikat, który polityka przepuszcza: odczyt bez
        # AI jest zgadywany i przemilczenie tego byłoby gorsze niż szum.
        result = m.OrderExtraction(
            rate_client=Decimal("1600"),
            start_date="2026-01-01",
            end_date="2026-06-30",
            uncertain=True,
            uncertain_reasons=["Odczyt awaryjny (bez AI) — zweryfikuj wszystkie pola"],
            source="regex",
        )
        enforced = m.apply_bank_pocztowy_order_policy(result, "Numer pisma: BP/7/26")
        assert enforced.uncertain is True
        assert any("Odczyt awaryjny" in r for r in enforced.uncertain_reasons)

    def test_no_rate_in_document_leaves_rate_fields_untouched(self):
        result = m.OrderExtraction(
            start_date="2026-01-01",
            end_date="2026-06-30",
            # LLM wywnioskował jednostkę mimo braku kwoty — polityka musi ją
            # wyczyścić: u BP jednostka jest godzinowa PO przeliczeniu, więc
            # „day" przy pustej stawce byłby sprzeczny z inwariantą.
            rate_unit="day",
            confidence={"rate_unit": 0.7},
            source="claude",
        )
        enforced = m.apply_bank_pocztowy_order_policy(result, "Numer pisma: BP/8/26")
        assert enforced.rate_client is None
        assert enforced.rate_client_md is None
        assert enforced.rate_unit is None
        assert "rate_unit" not in enforced.confidence
        # Brak stawki nie jest na białej liście komunikatów — pole po prostu
        # zostaje puste do ręcznego uzupełnienia.
        assert enforced.uncertain_reasons == []

    def test_net_formula_with_thousands_and_spaces(self):
        assert m.bank_pocztowy_net_md_rate(
            "Wynagrodzenie: 1 600,00 * 1,23 * 20 MD"
        ) == Decimal("1600.00")
        assert m.bank_pocztowy_net_md_rate("1600 x 1.23 x 20") == Decimal("1600")
        # Ekstraktory PDF potrafią oddać separator tysięcy jako NBSP (U+00A0)
        # albo wąski NBSP (U+202F) — klasa znaków musi je łapać.
        assert m.bank_pocztowy_net_md_rate("1\u00a0600,00 * 1,23 * 20") == Decimal(
            "1600.00"
        )
        assert m.bank_pocztowy_net_md_rate("1\u202f600 * 1,23") == Decimal("1600")
        assert m.bank_pocztowy_net_md_rate("stawka 1600 zł/MD netto") is None


class TestNormalizeClaudeShape:
    def test_full_confident(self):
        data = {
            "title": "PO-1",
            "start_date": "2026-06-01",
            "end_date": "2026-12-31",
            "rate_client": 17000,
            "rate_unit": "month",
            "total_value": 102000,
            "currency": "pln",
            "_confidence": {
                "title": 0.95,
                "start_date": 0.95,
                "end_date": 0.9,
                "rate_client": 0.92,
            },
            "uncertain": False,
            "uncertain_reasons": [],
        }
        r = m._normalize(data, source="claude")
        assert r.title == "PO-1"
        assert r.start_date == "2026-06-01"
        assert r.end_date == "2026-12-31"
        assert r.rate_client == Decimal("17000")
        assert r.total_value == Decimal("102000")
        assert r.currency == "PLN"
        assert r.uncertain is False
        assert r.source == "claude"

    def test_low_confidence_triggers_uncertain(self):
        data = {
            "title": "PO-2",
            "start_date": "2026-06-01",
            "rate_client": 5,
            "_confidence": {"title": 0.95, "start_date": 0.95, "rate_client": 0.3},
            "uncertain": False,
        }
        r = m._normalize(data, source="claude")
        assert r.uncertain is True
        assert any("stawka" in x.lower() for x in r.uncertain_reasons)

    def test_missing_title_and_start_uncertain(self):
        r = m._normalize({"end_date": "2026-12-31"}, source="claude")
        assert r.uncertain is True
        joined = " ".join(r.uncertain_reasons).lower()
        assert "tytu" in joined or "numer" in joined
        assert "rozpocz" in joined

    def test_hourly_rate_flags_unit_uncertainty(self):
        data = {
            "title": "PO",
            "start_date": "2026-01-01",
            "rate_client": 150,
            "rate_unit": "hour",
            "_confidence": {"title": 0.95, "start_date": 0.95, "rate_client": 0.95},
            "uncertain": False,
        }
        r = m._normalize(data, source="claude")
        assert r.uncertain is True
        assert any("jednost" in x.lower() for x in r.uncertain_reasons)

    def test_llm_uncertain_flag_respected_even_if_fields_present(self):
        data = {
            "title": "PO",
            "start_date": "2026-01-01",
            "end_date": "2026-06-30",
            "rate_client": 15000,
            "rate_unit": "month",
            "_confidence": {
                "title": 0.99,
                "start_date": 0.99,
                "end_date": 0.99,
                "rate_client": 0.99,
            },
            "uncertain": True,
            "uncertain_reasons": ["Kilku kandydatów na stawkę"],
        }
        r = m._normalize(data, source="claude")
        assert r.uncertain is True
        assert "Kilku kandydatów na stawkę" in r.uncertain_reasons

    def test_consultant_rows_are_normalized_without_exposing_global_guess(self):
        r = m._normalize(
            {
                "title": "PO-ROWS",
                "start_date": "2026-09-01",
                "rate_client": 999,
                "consultant_rows": [
                    {
                        "consultant_name": "Prus-Rudzińska Natalia",
                        "rate_client": "1 640,50 PLN",
                        "rate_unit": "MD",
                        "md_total": "42,5",
                        "uncertain": False,
                        "uncertain_reason": None,
                    },
                    {"consultant_name": "", "rate_client": 777},
                    "niepoprawny wiersz",
                ],
            },
            source="claude",
        )

        assert len(r.consultant_rows) == 1
        row = r.consultant_rows[0]
        assert row.consultant_name == "Prus-Rudzińska Natalia"
        assert row.rate_client == Decimal("1640.50")
        assert row.rate_unit == "day"
        assert row.md_total == Decimal("42.5")
        assert row.uncertain is False

    def test_consultant_row_without_explicit_certainty_fails_safe(self):
        r = m._normalize(
            {
                "consultant_rows": [
                    {
                        "consultant_name": "Natalia Prus-Rudzińska",
                        "rate_client": 1640,
                        "rate_unit": "day",
                        "md_total": 20,
                    }
                ]
            },
            source="claude",
        )

        assert r.consultant_rows[0].uncertain is True

    def test_consultant_row_reason_overrides_false_certainty_flag(self):
        r = m._normalize(
            {
                "consultant_rows": [
                    {
                        "consultant_name": "Natalia Prus-Rudzińska",
                        "rate_client": 1640,
                        "rate_unit": "day",
                        "md_total": 20,
                        "uncertain": False,
                        "uncertain_reason": "Stawka może dotyczyć sąsiedniej osoby",
                    }
                ]
            },
            source="claude",
        )

        assert r.consultant_rows[0].uncertain is True


class TestConsultantRowMatching:
    def test_six_token_name_matches_in_reverse_order(self):
        score = m._name_match_score(
            "Anna Maria Del Toro Garcia Kowalska",
            "Kowalska Garcia Toro Del Maria Anna",
            consultant_given_names="Anna Maria",
        )

        assert score == 0

    def test_six_token_name_allows_one_internal_transposition(self):
        score = m._name_match_score(
            "Anna Maria Del Toro Garcia Kowalska",
            "Kowaslka Garcia Toro Del Maria Anna",
            consultant_given_names="Anna Maria",
        )

        assert score == pytest.approx(1 / len("kowalska"))

    def test_six_token_name_rejects_two_transposed_pairs(self):
        score = m._name_match_score(
            "Anna Maria Del Toro Garcia Kowalska",
            "Kowaslka Gacria Toro Del Maria Anna",
            consultant_given_names="Anna Maria",
        )

        assert score is None

    @pytest.mark.parametrize(
        "written_name",
        [
            "PRUS-RUDZINSKA NATALIA",
            "Natalia Prus Rudzinska",
            "Natalia PrusRudzinska",
        ],
    )
    def test_order_case_diacritics_and_hyphen_formats_match(self, written_name):
        result = m.OrderExtraction(
            rate_client=Decimal("999"),
            md_total=Decimal("999"),
            consultant_rows=[
                m.ConsultantOrderRow(
                    consultant_name=written_name,
                    rate_client=Decimal("1640"),
                    rate_unit="day",
                    md_total=Decimal("42"),
                    uncertain=False,
                )
            ],
            uncertain=False,
            source="claude",
        )

        matched = m.apply_consultant_row_match(result, "Natalia Prus-Rudzińska")

        assert matched.rate_client == Decimal("1640")
        assert matched.rate_unit == "day"
        assert matched.md_total == Decimal("42")

    @pytest.mark.parametrize(
        "written_name",
        ["Natalia Prus-Rudzniska", "Natalia Purs-Rudzinska"],
    )
    def test_single_transposition_in_either_surname_component_is_tolerated(
        self, written_name
    ):
        result = m.OrderExtraction(
            consultant_rows=[
                m.ConsultantOrderRow(
                    consultant_name=written_name,
                    rate_client=Decimal("1700"),
                    rate_unit="day",
                    md_total=Decimal("15"),
                    uncertain=False,
                )
            ],
            uncertain=False,
            source="claude",
        )

        matched = m.apply_consultant_row_match(result, "Natalia Prus-Rudzińska")

        assert matched.rate_client == Decimal("1700")
        assert matched.md_total == Decimal("15")

    @pytest.mark.parametrize(
        ("target", "different_person"),
        [
            ("Anna Kowalska", "Hanna Kowalska"),
            ("Jan Kowalski", "Jan Kowalska"),
            ("Jan Nowak", "Jan Nowik"),
            ("Dariusz Wysocki", "Mariusz Wysocki"),
            ("Maria Nowak", "Maira Nowak"),
            ("Anna Maria Nowak", "Anna Maira Nowak"),
        ],
    )
    def test_close_but_real_other_person_is_not_a_typo(self, target, different_person):
        result = m.OrderExtraction(
            consultant_rows=[
                m.ConsultantOrderRow(
                    consultant_name=different_person,
                    rate_client=Decimal("1700"),
                    md_total=Decimal("15"),
                    uncertain=False,
                )
            ],
            uncertain=False,
            source="claude",
        )

        matched = m.apply_consultant_row_match(result, target)

        assert matched.rate_client is None
        assert matched.md_total is None
        assert matched.uncertain is True

    def test_rate_and_md_come_only_from_the_matched_person_row(self):
        result = m.OrderExtraction(
            # Symulacja starego, losowego wyboru modelu z pierwszego wiersza.
            rate_client=Decimal("910"),
            md_total=Decimal("8"),
            consultant_rows=[
                m.ConsultantOrderRow(
                    consultant_name="Dariusz Wysocki",
                    rate_client=Decimal("910"),
                    rate_unit="hour",
                    md_total=Decimal("8"),
                    uncertain=False,
                ),
                m.ConsultantOrderRow(
                    consultant_name="Prus-Rudzińska Natalia",
                    rate_client=Decimal("1640"),
                    rate_unit="day",
                    md_total=Decimal("37"),
                    uncertain=False,
                ),
            ],
            uncertain=False,
            source="claude",
        )

        matched = m.apply_consultant_row_match(result, "Natalia Prus-Rudzińska")

        assert matched.rate_client == Decimal("1640")
        assert matched.rate_unit == "day"
        assert matched.md_total == Decimal("37")

    def test_unrelated_person_never_matches_and_global_values_are_cleared(self):
        result = m.OrderExtraction(
            rate_client=Decimal("910"),
            rate_unit="hour",
            rate_client_md=Decimal("7280"),
            rate_client_gross=Decimal("1119.30"),
            md_total=Decimal("8"),
            confidence={"rate_client": 0.99, "md_total": 0.99},
            consultant_rows=[
                m.ConsultantOrderRow(
                    consultant_name="Dariusz Wysocki",
                    rate_client=Decimal("910"),
                    md_total=Decimal("8"),
                )
            ],
            uncertain=False,
            source="claude",
        )

        matched = m.apply_consultant_row_match(result, "Natalia Prus-Rudzińska")

        assert matched.rate_client is None
        assert matched.rate_unit is None
        assert matched.rate_client_md is None
        assert matched.rate_client_gross is None
        assert matched.md_total is None
        assert "rate_client" not in matched.confidence
        assert "md_total" not in matched.confidence
        assert matched.uncertain is True
        assert any(
            "Nie znaleziono jednoznacznej" in reason
            for reason in matched.uncertain_reasons
        )

    @pytest.mark.parametrize(
        ("policy", "document"),
        [
            (
                m.apply_bank_pocztowy_order_policy,
                "Numer pisma: BP/1/2026\nWynagrodzenie: 1600*1,23*20",
            ),
            (
                m.apply_credit_agricole_order_policy,
                "Szacowana ilość MD: 20\nWynagrodzenie za 1MD (8h) (PLN netto): 1040",
            ),
        ],
    )
    def test_target_policy_safety_stays_fail_closed_after_no_match(
        self, policy, document
    ):
        result = m.OrderExtraction(
            consultant_rows=[
                m.ConsultantOrderRow(
                    consultant_name="Dariusz Wysocki",
                    rate_client=Decimal("910"),
                    rate_unit="day",
                    md_total=Decimal("8"),
                    uncertain=False,
                )
            ],
            uncertain=False,
            source="claude",
        )
        no_match = m.apply_consultant_row_match(result, "Natalia Prus-Rudzińska")
        assert no_match.rate_client is None

        policy_result = policy(no_match, document)
        assert policy_result.rate_client is not None

        protected = m.enforce_consultant_policy_safety(policy_result)
        assert protected.rate_client is None
        assert protected.rate_unit is None
        assert protected.md_total is None
        assert protected.uncertain is True

    def test_target_policy_safety_keeps_erste_conversion_for_matched_row(self):
        matched = m.apply_consultant_row_match(
            m.OrderExtraction(
                consultant_rows=[
                    m.ConsultantOrderRow(
                        consultant_name="Natalia Prus-Rudzińska",
                        rate_client=Decimal("1230"),
                        rate_unit="day",
                        uncertain=False,
                    )
                ],
                uncertain=False,
            ),
            "Natalia Prus-Rudzińska",
        )

        converted = m.apply_erste_order_policy(matched, "Stawka 1230 PLN brutto")
        protected = m.enforce_consultant_policy_safety(converted)

        assert protected.rate_client == Decimal("1000.00")
        assert protected.rate_client_gross == Decimal("1230")

    def test_target_policy_safety_keeps_credit_agricole_correction_for_matched_row(
        self,
    ):
        matched = m.apply_consultant_row_match(
            m.OrderExtraction(
                consultant_rows=[
                    m.ConsultantOrderRow(
                        consultant_name="Natalia Prus-Rudzińska",
                        rate_client=Decimal("20"),
                        rate_unit="day",
                        md_total=Decimal("20"),
                        uncertain=False,
                    )
                ],
                uncertain=False,
            ),
            "Natalia Prus-Rudzińska",
        )
        document = "Szacowana ilość MD: 20\nWynagrodzenie za 1MD (8h) (PLN netto): 1040"

        corrected = m.apply_credit_agricole_order_policy(matched, document)
        protected = m.enforce_consultant_policy_safety(corrected)

        assert protected.rate_client == Decimal("1040")
        assert protected.md_total == Decimal("20")

    def test_two_possible_names_are_ambiguous_even_when_one_is_exact(self):
        result = m.OrderExtraction(
            consultant_rows=[
                m.ConsultantOrderRow(
                    consultant_name="Natalia Prus-Rudzińska",
                    rate_client=Decimal("1640"),
                    rate_unit="day",
                    md_total=Decimal("20"),
                    uncertain=False,
                ),
                m.ConsultantOrderRow(
                    consultant_name="Natalia Prus-Rudzniska",
                    rate_client=Decimal("1700"),
                    rate_unit="day",
                    md_total=Decimal("25"),
                    uncertain=False,
                ),
            ],
            uncertain=False,
            source="claude",
        )

        matched = m.apply_consultant_row_match(result, "Natalia Prus-Rudzińska")

        assert matched.rate_client is None
        assert matched.md_total is None
        assert matched.uncertain is True
        assert any("więcej niż jedną" in reason for reason in matched.uncertain_reasons)

    def test_identical_duplicate_rows_are_deduplicated(self):
        result = m.OrderExtraction(
            consultant_rows=[
                m.ConsultantOrderRow(
                    consultant_name="Natalia Prus-Rudzińska",
                    rate_client=Decimal("1640"),
                    rate_unit="day",
                    md_total=Decimal("20"),
                    uncertain=False,
                ),
                m.ConsultantOrderRow(
                    consultant_name="Prus Rudzinska Natalia",
                    rate_client=Decimal("1640"),
                    rate_unit="day",
                    md_total=Decimal("20"),
                    uncertain=False,
                ),
            ],
            uncertain=False,
            source="claude",
        )

        matched = m.apply_consultant_row_match(result, "Natalia Prus-Rudzińska")

        assert matched.rate_client == Decimal("1640")
        assert matched.md_total == Decimal("20")

    def test_conflicting_duplicate_rows_require_manual_review(self):
        result = m.OrderExtraction(
            consultant_rows=[
                m.ConsultantOrderRow(
                    consultant_name="Natalia Prus-Rudzińska",
                    rate_client=Decimal("1640"),
                    rate_unit="day",
                    md_total=Decimal("20"),
                    uncertain=False,
                ),
                m.ConsultantOrderRow(
                    consultant_name="Prus Rudzinska Natalia",
                    rate_client=Decimal("1700"),
                    rate_unit="day",
                    md_total=Decimal("20"),
                    uncertain=False,
                ),
            ],
            uncertain=False,
            source="claude",
        )

        matched = m.apply_consultant_row_match(result, "Natalia Prus-Rudzińska")

        assert matched.rate_client is None
        assert matched.md_total is None
        assert matched.uncertain is True

    def test_matched_row_marked_uncertain_never_applies_rate_or_md(self):
        result = m.OrderExtraction(
            consultant_rows=[
                m.ConsultantOrderRow(
                    consultant_name="Natalia Prus-Rudzińska",
                    rate_client=Decimal("1640"),
                    rate_unit="day",
                    md_total=Decimal("20"),
                    uncertain=True,
                    uncertain_reason="Nie można przypisać kwoty do wiersza osoby",
                )
            ],
            uncertain=True,
            source="claude",
        )

        matched = m.apply_consultant_row_match(result, "Natalia Prus-Rudzińska")

        assert matched.rate_client is None
        assert matched.rate_unit is None
        assert matched.md_total is None
        assert "Nie można przypisać kwoty" in " ".join(matched.uncertain_reasons)

    def test_rate_without_unit_is_left_for_manual_entry(self):
        result = m.OrderExtraction(
            consultant_rows=[
                m.ConsultantOrderRow(
                    consultant_name="Natalia Prus-Rudzińska",
                    rate_client=Decimal("1640"),
                    md_total=Decimal("20"),
                    uncertain=False,
                )
            ],
            uncertain=False,
            source="claude",
        )

        matched = m.apply_consultant_row_match(result, "Natalia Prus-Rudzińska")

        assert matched.rate_client is None
        assert matched.rate_unit is None
        assert matched.md_total == Decimal("20")
        assert matched.uncertain is True
        assert any("jednostki stawki" in reason for reason in matched.uncertain_reasons)


class TestOrlenOrderPolicy:
    """On-site/off-site dzielą pulę MD, ale mogą nieść jedną wspólną stawkę."""

    def _rows(
        self,
        *,
        onsite_rate: Decimal = Decimal("1320"),
        offsite_rate: Decimal = Decimal("1320"),
        onsite_unit: str = "day",
        offsite_unit: str = "day",
        offsite_uncertain: bool = False,
    ) -> list[m.ConsultantOrderRow]:
        return [
            m.ConsultantOrderRow(
                consultant_name="Aleksandra Lebiedziewicz",
                rate_client=onsite_rate,
                rate_unit=onsite_unit,
                md_total=Decimal("75"),
                uncertain=False,
            ),
            m.ConsultantOrderRow(
                consultant_name="Lebiedziewicz Aleksandra",
                rate_client=offsite_rate,
                rate_unit=offsite_unit,
                md_total=Decimal("50"),
                uncertain=offsite_uncertain,
            ),
        ]

    def test_equal_onsite_offsite_rate_is_accepted_without_md_total(self):
        result = m.OrderExtraction(
            start_date="2026-09-01",
            end_date="2026-12-31",
            consultant_rows=self._rows(),
            uncertain=False,
            source="claude",
        )
        # Generyczny matcher prawidłowo pozostaje zachowawczy dla innych
        # klientów i widzi dwie pozycje z różnymi pulami MD.
        ambiguous = m.apply_consultant_row_match(result, "Aleksandra Lebiedziewicz")
        assert ambiguous.rate_client is None
        assert any("więcej niż jedną" in r for r in ambiguous.uncertain_reasons)

        enforced = m.apply_orlen_order_policy(
            ambiguous,
            "on-site 75 MD; off-site 50 MD",
            consultant_name="Aleksandra Lebiedziewicz",
        )

        assert enforced.rate_client == Decimal("1320")
        assert enforced.rate_unit == "day"
        assert enforced.md_total is None
        assert enforced.consultant_rate_matched is True
        assert enforced.consultant_md_matched is False
        assert enforced.start_date == "2026-09-01"
        assert enforced.end_date == "2026-12-31"
        assert enforced.uncertain is False
        assert not any("więcej niż jedną" in r for r in enforced.uncertain_reasons)

    @pytest.mark.parametrize(
        ("offsite_rate", "offsite_unit"),
        [
            (Decimal("1330"), "day"),
            (Decimal("1320"), "hour"),
        ],
    )
    def test_different_rate_or_unit_stays_fail_closed(self, offsite_rate, offsite_unit):
        ambiguous = m.apply_consultant_row_match(
            m.OrderExtraction(
                consultant_rows=self._rows(
                    offsite_rate=offsite_rate,
                    offsite_unit=offsite_unit,
                ),
                uncertain=False,
                source="claude",
            ),
            "Aleksandra Lebiedziewicz",
        )

        enforced = m.apply_orlen_order_policy(
            ambiguous,
            "",
            consultant_name="Aleksandra Lebiedziewicz",
        )

        assert enforced.rate_client is None
        assert enforced.rate_unit is None
        assert enforced.md_total is None
        assert enforced.consultant_rate_matched is False
        assert enforced.uncertain is True
        assert any(
            "nie mają jednej pewnej stawki" in r for r in enforced.uncertain_reasons
        )

    def test_uncertain_row_stays_fail_closed_even_when_rates_are_equal(self):
        result = m.OrderExtraction(
            consultant_rows=self._rows(offsite_uncertain=True),
            md_total=Decimal("125"),
            confidence={"md_total": 0.95},
            uncertain=False,
            source="claude",
        )

        enforced = m.apply_orlen_order_policy(
            result,
            "",
            consultant_name="Aleksandra Lebiedziewicz",
        )

        assert enforced.rate_client is None
        assert enforced.md_total is None
        assert "md_total" not in enforced.confidence
        assert enforced.uncertain is True

    def test_unrelated_consultant_rows_do_not_change_target_common_rate(self):
        result = m.OrderExtraction(
            consultant_rows=self._rows()
            + [
                m.ConsultantOrderRow(
                    consultant_name="Jan Kowalski",
                    rate_client=Decimal("1800"),
                    rate_unit="day",
                    md_total=Decimal("20"),
                    uncertain=False,
                )
            ],
            uncertain=False,
            source="claude",
        )

        enforced = m.apply_orlen_order_policy(
            result,
            "",
            consultant_name="Aleksandra Lebiedziewicz",
        )

        assert enforced.rate_client == Decimal("1320")
        assert enforced.md_total is None


class TestTargetedDocumentExcerpt:
    def test_consultant_after_legacy_limit_is_included_with_header(self):
        header = "Zamówienie PO-4500724684\nOkres od 2026-09-01 do 2026-12-31\n"
        appendix = "".join(
            f"Załącznik techniczny, wiersz {index}\n" for index in range(900)
        )
        target_row = "Prus-Rudzińska Natalia | 1640 PLN/MD | 37 MD\n"
        document = header + appendix + target_row
        assert document.index(target_row) > m._MAX_DOC_CHARS

        excerpt, incomplete = m._document_text_for_prompt(
            document, "Natalia Prus-Rudzińska"
        )

        assert incomplete is False
        assert "PO-4500724684" in excerpt
        assert target_row.strip() in excerpt

    def test_no_plausible_target_keeps_safe_legacy_excerpt(self):
        document = "Początek dokumentu\n" + ("Dariusz Wysocki | 910 PLN\n" * 1000)

        excerpt, incomplete = m._document_text_for_prompt(
            document, "Natalia Prus-Rudzińska"
        )

        assert incomplete is False
        assert excerpt == document[: m._MAX_DOC_CHARS]

    def test_name_split_across_three_lines_after_limit_is_included(self):
        appendix = "".join(f"Załącznik {index}\n" for index in range(1500))
        split_row = "Natalia\nPrus\nRudzińska | 1640 PLN/MD | 37 MD\n"
        document = "PO-3-LINES\n" + appendix + split_row
        assert document.index(split_row) > m._MAX_DOC_CHARS

        excerpt, incomplete = m._document_text_for_prompt(
            document, "Natalia Prus-Rudzińska"
        )

        assert incomplete is False
        assert split_row.strip() in excerpt

    def test_raw_document_presence_requires_exact_first_name_anchor(self):
        assert m._document_mentions_consultant(
            "Prus-Rudzniska Natalia | 1640 PLN/MD", "Natalia Prus-Rudzińska"
        )
        assert not m._document_mentions_consultant(
            "Maira Nowak | 1700 PLN/MD", "Maria Nowak"
        )
        assert not m._document_mentions_consultant(
            "Anna Maira Nowak | 1700 PLN/MD", "Anna Maria Nowak"
        )

    def test_raw_document_presence_never_combines_adjacent_people(self):
        document = (
            "Natalia Wysocka | 1500 PLN/MD | 20 MD\n"
            "Anna Prus-Rudzińska | 1700 PLN/MD | 25 MD\n"
        )

        assert not m._document_mentions_consultant(
            document, "Natalia Prus-Rudzińska", "Natalia"
        )
        assert not m._document_mentions_consultant(
            "Prus Natalia\nRudzińska Natalia",
            "Natalia Prus-Rudzińska",
            "Natalia",
        )
        assert m._document_mentions_consultant(
            "Natalia\nPrus\nRudzińska | 1640 PLN/MD",
            "Natalia Prus-Rudzińska",
            "Natalia",
        )

    def test_cross_line_name_rejects_interleaved_duplicate_given_names(self):
        assert not m._document_mentions_consultant(
            "Prus\nNatalia\nRudzińska\nNatalia",
            "Natalia Prus-Rudzińska",
            "Natalia",
        )

    def test_cross_line_name_rejects_ambiguous_column_major_people(self):
        assert not m._document_mentions_consultant(
            "Prus\nRudzińska\nNatalia\nAnna",
            "Natalia Prus-Rudzińska",
            "Natalia",
        )

    def test_cross_line_name_rejects_other_person_even_with_rate_context(self):
        assert not m._document_mentions_consultant(
            "Prus\nRudzińska\nNatalia\nAnna | 1600 PLN/MD",
            "Natalia Prus-Rudzińska",
            "Natalia",
        )

    def test_cross_line_name_allows_compound_surname_without_retained_hyphen(self):
        assert m._document_mentions_consultant(
            "Natalia Prus\nRudzińska",
            "Natalia Prus-Rudzińska",
            "Natalia",
        )

    @pytest.mark.parametrize(
        "document",
        [
            "Natalia\nPrus\nRudzińska | 1640 zł/MD",
            "Natalia\nPrus\nRudzińska\nStawka: 1640 zł/MD",
            "Konsultant: Natalia\nPrus-Rudzińska",
        ],
    )
    def test_cross_line_name_accepts_structurally_anchored_wraps(self, document):
        assert m._document_mentions_consultant(
            document,
            "Natalia Prus-Rudzińska",
            "Natalia",
        )


class TestCreditAgricolePolicy:
    """Stawka WYŁĄCZNIE z „Wynagrodzenie za 1MD", liczba MD z „Szacowana ilość MD".

    Zgłoszony objaw: parser wpisywał do stawki wartość z pola liczby MD.
    Liczba jest arytmetycznie poprawna i przechodzi każdą walidację zakresu,
    więc błąd wychodził dopiero na fakturze — dlatego polityka nie „poprawia"
    wyboru modelu, tylko czyta obie wartości z ich własnych etykiet.
    """

    def _doc(self, rate: str = "1 040,00", md: str = "20") -> str:
        return (
            "Credit Agricole Bank Polska S.A.\n"
            "Zamówienie nr CA/2026/0142\n"
            f"Szacowana ilość MD: {md}\n"
            f"Wynagrodzenie za 1MD (8h) (PLN netto): {rate}\n"
        )

    def _swapped(self) -> m.OrderExtraction:
        """Wynik modelu z objawem z ticketu: w stawce siedzi liczba MD."""
        return m.OrderExtraction(
            title="CA/2026/0142",
            rate_client=Decimal("20"),
            rate_unit="day",
            md_total=Decimal("20"),
            uncertain=False,
            source="claude",
        )

    def test_rate_comes_from_the_rate_label_not_from_md_count(self):
        enforced = m.apply_credit_agricole_order_policy(self._swapped(), self._doc())
        assert enforced.rate_client == Decimal("1040.00")
        assert enforced.md_total == Decimal("20")
        assert enforced.rate_unit == "day"

    def test_label_digits_are_not_mistaken_for_the_value(self):
        """„1MD" i „8h" w samej etykiecie nie mogą wygrać z wartością za nią."""
        assert m.credit_agricole_md_rate(self._doc()) == Decimal("1040.00")

    def test_value_on_the_next_line_is_found(self):
        doc = "Szacowana ilość MD\n20\nWynagrodzenie za 1MD (8h) (PLN netto)\n1040,00\n"
        assert m.credit_agricole_md_rate(doc) == Decimal("1040.00")
        assert m.credit_agricole_md_count(doc) == Decimal("20")

    def test_missing_diacritics_still_match(self):
        doc = "Szacowana ilosc MD 20\nWynagrodzenie za 1 MD (8h) (PLN netto) 1040\n"
        assert m.credit_agricole_md_rate(doc) == Decimal("1040")
        assert m.credit_agricole_md_count(doc) == Decimal("20")

    def test_table_header_layout_refuses_instead_of_guessing(self):
        """Obie etykiety w jednym wierszu = nagłówek tabeli → nie zgadujemy.

        Wartości leżą wtedy w kolumnach wiersza niżej, a ekstrakcja z PDF gubi
        wyrównanie: „pierwsza liczba za etykietą" trafiłaby w liczbę porządkową.
        To jest dokładnie ta pomyłka, którą ticket zgłasza.
        """
        doc = (
            "Lp. Stanowisko Szacowana ilość MD Wynagrodzenie za 1MD (8h) (PLN netto)\n"
            "1. Java Developer 20 1 040,00\n"
        )
        enforced = m.apply_credit_agricole_order_policy(self._swapped(), doc)
        assert enforced.rate_client is None
        assert enforced.rate_unit is None
        assert enforced.uncertain is True
        assert any("wpisz stawkę ręcznie" in r for r in enforced.uncertain_reasons)

    def test_missing_rate_label_clears_the_model_guess(self):
        enforced = m.apply_credit_agricole_order_policy(
            self._swapped(), "Szacowana ilość MD: 20\nUwagi: brak\n"
        )
        assert enforced.rate_client is None
        assert enforced.md_total == Decimal("20")
        assert "rate_client" not in enforced.confidence

    def test_identical_values_under_both_labels_refuse_the_rate(self):
        """Ta sama liczba pod obiema etykietami = jedna z nich z cudzej kolumny."""
        enforced = m.apply_credit_agricole_order_policy(
            self._swapped(), self._doc(rate="20", md="20")
        )
        assert enforced.rate_client is None
        assert enforced.md_total == Decimal("20")

    def test_rate_outside_the_band_warns_but_keeps_the_value(self):
        enforced = m.apply_credit_agricole_order_policy(
            self._swapped(), self._doc(rate="12", md="20")
        )
        assert enforced.rate_client == Decimal("12")
        assert any("Nietypowa stawka za 1 MD" in r for r in enforced.uncertain_reasons)

    def test_clean_read_inside_the_band_stays_quiet(self):
        enforced = m.apply_credit_agricole_order_policy(self._swapped(), self._doc())
        assert enforced.uncertain is False
        assert enforced.uncertain_reasons == []


class TestPfronOrderPolicy:
    """PFRON używa konkretnego okresu, pomija MD i podaje stawkę brutto/h."""

    def test_period_end_ignores_extension_note_and_md_is_never_used(self):
        result = m.OrderExtraction(
            end_date="2027-12-31",
            rate_client=Decimal("1230"),
            rate_unit="hour",
            total_value=Decimal("246000"),
            md_total=Decimal("125"),
            confidence={"end_date": 0.4, "md_total": 0.9},
            uncertain=True,
            uncertain_reasons=[
                "Niepewny odczyt: data zakończenia",
                "Niepewna liczba MD",
                "Data zawiera dopisek o możliwości przedłużenia",
                "Stawka brutto wymaga przeliczenia VAT",
            ],
            source="claude",
        )
        document = (
            "Termin realizacji usług: od 01.09.2026 do 31.12.2026 "
            "z możliwością przedłużenia. Stawka 1230 PLN brutto."
        )

        enforced = m.apply_pfron_order_policy(result, document)

        assert enforced.end_date == "2026-12-31"
        assert enforced.confidence["end_date"] == 1.0
        assert enforced.md_total is None
        assert "md_total" not in enforced.confidence
        assert enforced.rate_client_gross == Decimal("1230")
        assert enforced.rate_client == Decimal("1000.00")
        assert enforced.rate_unit == "hour"
        assert enforced.total_value == Decimal("246000")
        assert enforced.uncertain is False
        assert enforced.uncertain_reasons == []

    @pytest.mark.parametrize(
        "document",
        [
            "Data zakończenia realizacji usług: 31.12.2026 "
            "(z możliwością przedłużenia)",
            "Okres realizacji usług: 01.09.2026 – 31.12.2026; możliwość przedłużenia",
            "Termin realizacji usług do dnia 31-12-2026, z możliwością przedłużenia",
        ],
    )
    def test_supported_explicit_end_date_forms(self, document):
        assert m.pfron_end_date(document) == "2026-12-31"

    def test_multiple_distinct_service_periods_are_fail_closed(self):
        result = m.OrderExtraction(
            end_date="2026-12-31",
            rate_client=Decimal("1230"),
            rate_unit="hour",
            md_total=Decimal("125"),
            uncertain=False,
            source="claude",
        )
        document = (
            "Okres podstawowy od 01.09.2026 do 31.12.2026. "
            "Okres opcjonalny od 01.01.2027 do 31.03.2027. Stawka 1230 PLN brutto."
        )

        enforced = m.apply_pfron_order_policy(result, document)

        assert enforced.end_date is None
        assert enforced.md_total is None
        assert enforced.rate_client == Decimal("1000.00")
        assert enforced.uncertain is True
        assert any("jednej konkretnej daty" in r for r in enforced.uncertain_reasons)

    def test_missing_explicit_end_date_does_not_keep_model_guess(self):
        result = m.OrderExtraction(
            end_date="2026-12-31",
            md_total=Decimal("125"),
            uncertain=False,
            source="claude",
        )

        enforced = m.apply_pfron_order_policy(
            result, "Usługi będą realizowane zgodnie z zamówieniem."
        )

        assert enforced.end_date is None
        assert enforced.md_total is None
        assert enforced.uncertain is True

    def test_policy_is_idempotent_on_the_same_result(self):
        result = m.OrderExtraction(
            rate_client=Decimal("1230"),
            rate_unit="hour",
            md_total=Decimal("125"),
            uncertain=False,
            source="claude",
        )
        document = (
            "Termin realizacji: od 01.09.2026 do 31.12.2026. Stawka 1230 PLN brutto"
        )

        once = m.apply_pfron_order_policy(result, document)
        twice = m.apply_pfron_order_policy(once, document)

        assert twice is once
        assert twice.rate_client_gross == Decimal("1230")
        assert twice.rate_client == Decimal("1000.00")
        assert twice.end_date == "2026-12-31"
        assert twice.md_total is None


class TestErsteGrossToNetPolicy:
    """Stawka w PDF Erste jest BRUTTO — zapisujemy netto (÷ 1,23)."""

    def test_gross_is_divided_by_vat_and_rounded_to_two_places(self):
        result = m.OrderExtraction(rate_client=Decimal("1230"), source="claude")
        enforced = m.apply_erste_order_policy(
            result, "Erste Bank Polska S.A. Stawka 1230 PLN brutto"
        )
        assert enforced.rate_client == Decimal("1000.00")
        # Oryginał brutto zostaje widoczny obok — operator konfrontuje z PDF-em.
        assert enforced.rate_client_gross == Decimal("1230")
        # Erste rozlicza DZIENNIE — korpus 09.2026: „23,00 dni roboczych x
        # 1 426,80 PLN BRUTTO". Do tej rewizji polityka wymuszała „hour" i na
        # tym dokumencie zapisywała stawkę dzienną jako godzinową z pewnością 1.0.
        assert enforced.rate_unit == "day"

    def test_client_rule_overrides_missing_or_wrong_model_unit_with_client_unit(self):
        missing = m.apply_erste_order_policy(
            m.OrderExtraction(rate_client=Decimal("1230"), source="claude"), ""
        )
        wrong = m.apply_pfron_order_policy(
            m.OrderExtraction(
                rate_client=Decimal("1230"), rate_unit="hour", source="claude"
            ),
            "Termin realizacji usług do dnia 31.12.2026",
        )
        # Każdy klient narzuca SWOJĄ jednostkę: Erste dzień, PFRON godzina
        # („Stawka za jedną Roboczogodzinę").
        assert missing.rate_unit == "day"
        assert wrong.rate_unit == "hour"

    def test_erste_reads_number_period_and_gross_day_rate_from_labels(self):
        """Etykiety Erste z korpusu: numer „Zlecenie K/…”, „Zlecenie od/do”, wzór brutto."""
        text = (
            "Zlecenie K/2031/194208/JP/525/31ERSTE10\n"
            "Dane kontraktora Anna Testowa Zlecenie od 2031-07-01 Zlecenie do 2031-07-31\n"
            "Wartość zlecenia 23,00 dni roboczych x 1 426,80 PLN BRUTTO = 32 816,40 PLN BRUTTO\n"
        )
        enforced = m.apply_erste_order_policy(m.OrderExtraction(source="claude"), text)
        assert enforced.title == "K/2031/194208/JP/525/31ERSTE10"
        assert (enforced.start_date, enforced.end_date) == ("2031-07-01", "2031-07-31")
        assert enforced.rate_client_gross == Decimal("1426.80")
        assert enforced.rate_client == Decimal("1160.00")
        assert enforced.rate_unit == "day"
        assert enforced.confidence["rate_client"] == 1.0

    def test_rounding_is_half_up_to_two_places(self):
        # 1000 / 1,23 = 813,00813… → 813,01
        result = m.OrderExtraction(rate_client=Decimal("1000"), source="claude")
        enforced = m.apply_erste_order_policy(result, "Stawka 1000 PLN brutto")
        assert enforced.rate_client == Decimal("813.01")

    def test_total_value_is_left_untouched(self):
        """Ticket mówi o STAWCE — dzielenie wartości całkowitej byłoby zgadywaniem."""
        result = m.OrderExtraction(
            rate_client=Decimal("1230"),
            total_value=Decimal("24600"),
            source="claude",
        )
        enforced = m.apply_erste_order_policy(result, "")
        assert enforced.total_value == Decimal("24600")

    def test_no_rate_means_nothing_to_convert(self):
        result = m.OrderExtraction(rate_client=None, source="claude")
        enforced = m.apply_erste_order_policy(result, "")
        assert enforced.rate_client is None
        assert enforced.rate_client_gross is None

    def test_conversion_is_idempotent_on_the_same_result(self):
        """Dwa przebiegi tej samej polityki nie mogą dzielić dwa razy.

        Router woła politykę raz, ale wartość musi być funkcją WEJŚCIA, a nie
        liczby wywołań — inaczej powtórka odczytu cicho zaniża stawkę o 23%.
        """
        result = m.OrderExtraction(rate_client=Decimal("1230"), source="claude")

        once = m.apply_erste_order_policy(result, "Stawka 1230 PLN brutto")
        twice = m.apply_erste_order_policy(once, "Stawka 1230 PLN brutto")

        assert twice is once
        assert twice.rate_client_gross == Decimal("1230")
        assert twice.rate_client == Decimal("1000.00")

    def test_compatible_erste_helper_uses_shared_conversion(self):
        assert m.erste_net_from_gross(Decimal("1000")) == m.net_rate_from_gross(
            Decimal("1000")
        )

    def test_explicit_netto_marking_overrides_client_gross_rule(self):
        """Dokument wygrywa z regułą klientową: jawne „netto" → brak ÷ 1,23."""
        result = m.OrderExtraction(rate_client=Decimal("1230"), source="claude")
        enforced = m.apply_erste_order_policy(
            result, "Stawka 1230,00 PLN netto za dzień roboczy"
        )
        assert enforced.rate_client == Decimal("1230")
        assert enforced.rate_client_gross is None
        # Jednostka klientowa (reguła deterministyczna) obowiązuje nadal.
        assert enforced.rate_unit == "day"

    def test_pfron_explicit_netto_marking_overrides_gross_rule(self):
        result = m.OrderExtraction(
            rate_client=Decimal("1230"), rate_unit="hour", source="claude"
        )
        enforced = m.apply_pfron_order_policy(
            result,
            "Stawka za 1 roboczogodzinę: 1230,00 PLN netto. "
            "Termin realizacji usług do dnia 31.12.2026",
        )
        assert enforced.rate_client == Decimal("1230")
        assert enforced.rate_client_gross is None
        assert enforced.rate_unit == "hour"


class TestDocumentRateGrossMarking:
    """Rodzaj stawki (brutto/netto) czytany z DOKUMENTU, per zamówienie."""

    def test_gross_marking_next_to_rate_amount(self):
        doc = "23,00 dni roboczych x 1 426,80 PLN BRUTTO = 32 816,40 PLN BRUTTO"
        assert (
            m.detect_rate_gross_marking(doc, [Decimal("1426.80")]) == m.RATE_MARK_GROSS
        )

    def test_net_rate_with_far_gross_total_is_not_gross(self):
        """Pułapka: dokument netto niesie osobną „wartość brutto" (total z VAT)."""
        doc = (
            "Stawka za 1 MD: 1 040,00 PLN netto.\n"
            "Łączna wartość zamówienia: 109 200,00 PLN netto "
            "i 134 316,00 PLN brutto."
        )
        assert m.detect_rate_gross_marking(doc, [Decimal("1040.00")]) == m.RATE_MARK_NET

    def test_no_marking_returns_none(self):
        doc = "Stawka 100,00 PLN za godzinę. Wartość zamówienia 16 800,00 PLN."
        assert m.detect_rate_gross_marking(doc, [Decimal("100.00")]) is None

    def test_conflicting_markings_on_the_rate_are_ambiguous(self):
        doc = "Stawka 1 000,00 PLN netto brutto"
        assert m.detect_rate_gross_marking(doc, [Decimal("1000.00")]) is None

    def test_verbose_gross_label_next_to_rate_is_caught(self):
        """Rozbudowana etykieta tuż przy kwocie — okno musi ją objąć (nie 24)."""
        doc = "1 040,00 PLN — stawka brutto za jeden dzień roboczy"
        assert (
            m.detect_rate_gross_marking(doc, [Decimal("1040.00")]) == m.RATE_MARK_GROSS
        )

    def test_grouped_and_ungrouped_amount_both_anchor(self):
        assert (
            m.detect_rate_gross_marking("1426,80 PLN brutto", [Decimal("1426.80")])
            == m.RATE_MARK_GROSS
        )
        assert (
            m.detect_rate_gross_marking("1 426,80 PLN brutto", [Decimal("1426.80")])
            == m.RATE_MARK_GROSS
        )

    def test_gross_conversion_applies_to_any_client_document(self):
        """Erste spoza env: brak polityki, a dokument mówi BRUTTO → ÷ 1,23."""
        ex = m.OrderExtraction(
            rate_client=Decimal("1426.80"),
            rate_unit="day",
            source="claude",
            consultant_rows=[
                m.ConsultantOrderRow(
                    consultant_name="Marcin Żółtaniecki",
                    rate_client=Decimal("1426.80"),
                    rate_unit="day",
                    uncertain=False,
                )
            ],
        )
        out = m.apply_document_rate_kind(
            ex, "23,00 dni roboczych x 1 426,80 PLN BRUTTO"
        )
        assert out.rate_client == Decimal("1160.00")
        assert out.rate_client_gross == Decimal("1426.80")
        row = out.consultant_rows[0]
        assert row.rate_client == Decimal("1160.00")
        assert row.rate_client_gross == Decimal("1426.80")

    def test_net_document_is_left_untouched(self):
        ex = m.OrderExtraction(
            rate_client=Decimal("1040.00"),
            source="claude",
            consultant_rows=[
                m.ConsultantOrderRow(
                    consultant_name="Jan Kowalski",
                    rate_client=Decimal("1040.00"),
                    uncertain=False,
                )
            ],
        )
        out = m.apply_document_rate_kind(ex, "Stawka za 1 MD 1 040,00 PLN netto")
        assert out.rate_client == Decimal("1040.00")
        assert out.rate_client_gross is None
        assert out.consultant_rows[0].rate_client == Decimal("1040.00")

    def test_unknown_marking_does_not_convert(self):
        ex = m.OrderExtraction(rate_client=Decimal("1000.00"), source="claude")
        out = m.apply_document_rate_kind(ex, "Stawka 1 000,00 PLN / godzina")
        assert out.rate_client == Decimal("1000.00")
        assert out.rate_client_gross is None

    def test_idempotent_after_client_policy_already_converted(self):
        """Znacznik rate_client_gross chroni przed drugim dzieleniem."""
        ex = m.OrderExtraction(rate_client=Decimal("1426.80"), source="claude")
        doc = "1 426,80 PLN BRUTTO"
        once = m.apply_erste_order_policy(ex, doc)  # policy converts top-level
        twice = m.apply_document_rate_kind(once, doc)
        assert twice.rate_client == m.net_rate_from_gross(Decimal("1426.80"))
        assert twice.rate_client_gross == Decimal("1426.80")


class TestNameTypoDistance:
    """Rozszerzona tolerancja literówek dla resolvera poczty (OSA ≤ 1)."""

    def test_osa_counts_single_edits_and_caps_beyond_budget(self):
        assert m._osa_distance("kowalski", "kowalska", max_distance=1) == 1  # sub
        assert m._osa_distance("kowalski", "kowalksi", max_distance=1) == 1  # transp
        assert m._osa_distance("zoltaniecki", "zoltanicki", max_distance=1) == 1  # del
        assert m._osa_distance("nowak", "nowakk", max_distance=1) == 1  # ins
        assert m._osa_distance("nowak", "kowal", max_distance=1) == 2  # capped

    def test_edit1_accepts_minor_typos_but_guards_short_tokens(self):
        assert m._edit1_token_distance("zoltaniecki", "zoltanicki") == 1
        assert m._edit1_token_distance("kowalski", "kowalska") == 1
        assert m._edit1_token_distance("kowalski", "kowalski") == 0
        assert m._edit1_token_distance("jan", "jon") is None  # < 5 znaków
        assert m._edit1_token_distance("nowak", "kowal") is None  # > 1 edycja

    def test_edit1_scores_a_substituted_surname_that_default_rejects(self):
        # Ścieżka ręczna (domyślna transpozycja) uznaje to za inną osobę…
        assert (
            m._name_match_score(
                "Marcin Zoltaniecki",
                "Marcin Zoltanicki",
                consultant_given_names="Marcin",
            )
            is None
        )
        # …resolver poczty (OSA ≤ 1) ratuje literówkę do kolejki.
        assert (
            m._name_match_score(
                "Marcin Zoltaniecki",
                "Marcin Zoltanicki",
                consultant_given_names="Marcin",
                distance_fn=m._edit1_token_distance,
            )
            is not None
        )

    def test_edit1_still_requires_exact_given_name_and_one_matching_token(self):
        # Inny człon imienia → nadal brak dopasowania (kotwica imienia).
        assert (
            m._name_match_score(
                "Marcin Zoltaniecki",
                "Marek Zoltaniecki",
                consultant_given_names="Marcin",
                distance_fn=m._edit1_token_distance,
            )
            is None
        )


class TestParseOrderDocument:
    async def test_empty_document(self):
        r = await parse_order_document("   ")
        assert r.uncertain is True
        assert r.source == "none"

    async def test_falls_back_to_regex_without_api_key(self, monkeypatch):
        # Bez klucza ANTHROPIC → _extract_with_claude zwraca None → regex.
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        monkeypatch.delenv("CLAUDE_API_KEY", raising=False)
        monkeypatch.setattr(m.settings, "ANTHROPIC_API_KEY", "", raising=False)
        r = await parse_order_document("Umowa call-off mc 03-2026_08-2026")
        assert r.source == "regex"
        assert r.start_date == "2026-03-01"
        assert r.end_date == "2026-08-31"
        assert r.uncertain is True

    async def test_targeted_regex_fallback_never_uses_first_rate_or_md(
        self, monkeypatch
    ):
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        monkeypatch.setattr(m.settings, "ANTHROPIC_API_KEY", "", raising=False)

        r = await parse_order_document(
            "Dariusz Wysocki | stawka 910 PLN | 8 MD",
            consultant_name="Natalia Prus-Rudzińska",
        )

        assert r.source == "regex"
        assert r.rate_client is None
        assert r.rate_unit is None
        assert r.md_total is None
        assert r.uncertain is True
        assert any(
            "Nie znaleziono jednoznacznej" in reason for reason in r.uncertain_reasons
        )

    async def test_target_absent_in_raw_text_rejects_hallucinated_claude_row(
        self, monkeypatch
    ):
        async def fake_extract(
            text: str,
            *,
            consultant_name: str | None = None,
            consultant_given_names: str | None = None,
        ):
            assert consultant_name == "Natalia Prus-Rudzińska"
            assert consultant_given_names is None
            return m.OrderExtraction(
                consultant_rows=[
                    m.ConsultantOrderRow(
                        consultant_name="Natalia Prus-Rudzińska",
                        rate_client=Decimal("1640"),
                        rate_unit="day",
                        md_total=Decimal("37"),
                        uncertain=False,
                    )
                ],
                uncertain=False,
                source="claude",
            )

        monkeypatch.setattr(m, "_extract_with_claude", fake_extract)

        r = await parse_order_document(
            "Dariusz Wysocki | 910 PLN/MD | 8 MD",
            consultant_name="Natalia Prus-Rudzińska",
        )

        assert r.rate_client is None
        assert r.md_total is None
        assert r.uncertain is True

    async def test_targeted_client_default_preserves_rate_when_model_omits_unit(
        self, monkeypatch
    ):
        """Twarda reguła PFRON/Erste działa przed fail-closed safety matchera."""

        async def fake_extract(
            text: str,
            *,
            consultant_name: str | None = None,
            consultant_given_names: str | None = None,
        ):
            return m.OrderExtraction(
                consultant_rows=[
                    m.ConsultantOrderRow(
                        consultant_name="Natalia Prus-Rudzińska",
                        rate_client=Decimal("1230"),
                        rate_unit=None,
                        uncertain=False,
                    )
                ],
                uncertain=False,
                source="claude",
            )

        monkeypatch.setattr(m, "_extract_with_claude", fake_extract)

        parsed = await parse_order_document(
            "Natalia Prus-Rudzińska — stawka brutto 1230 PLN za godzinę",
            consultant_name="Natalia Prus-Rudzińska",
            consultant_rate_unit_default="hour",
        )
        enforced = m.apply_pfron_order_policy(
            parsed,
            "Natalia Prus-Rudzińska — termin realizacji usług do 31.12.2026. Stawka brutto 1230 PLN za godzinę",
        )
        enforced = m.enforce_consultant_policy_safety(enforced)

        assert enforced.consultant_rate_matched is True
        assert enforced.rate_client_gross == Decimal("1230")
        assert enforced.rate_client == Decimal("1000.00")
        assert enforced.rate_unit == "hour"

    async def test_untargeted_regex_fallback_stays_backward_compatible(
        self, monkeypatch
    ):
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        monkeypatch.setattr(m.settings, "ANTHROPIC_API_KEY", "", raising=False)

        r = await parse_order_document("Stawka 910 PLN | 8 MD")

        assert r.rate_client == Decimal("910")
        assert r.md_total == Decimal("8")


class TestBnpOrderPolicy:
    """Zamówienie BNP: dokument JEDNOOSOBOWY, konsultant po numerze ID.

    Zgłoszony objaw: dla BNP odczyt nie dawał ani stawki, ani liczby MD.
    Przyczyną nie był model, tylko tożsamość — PDF-y tego klienta nie
    zawierają imienia ani nazwiska, a generyczny matcher jest fail-closed po
    nazwisku, więc kasował oba pola. Tu sprawdzamy samą politykę: co czyta,
    czego świadomie NIE zgaduje i czym o tym mówi.
    """

    def _doc(
        self,
        *,
        period: str = "Okres realizacji: 08-2026 do 12-2026",
        price: str = "Cena netto: 1 040,00 PLN",
        qty: str = "Szt.: 105",
        ref: str = "Konsultant ID: 4711",
    ) -> str:
        return f"Zamówienie nr 3728_2026\n{ref}\n{period}\n{price}\n{qty}\n"

    def _blank(self) -> m.OrderExtraction:
        return m.OrderExtraction(title="3728_2026", uncertain=False, source="claude")

    # ── Okres MM-RRRR do MM-RRRR ────────────────────────────────────────────

    @pytest.mark.parametrize(
        "period",
        [
            "Okres: 08-2026 do 12-2026",
            "od 08-2026 do 12-2026",
            "08-2026 - 12-2026",
            "08-2026 – 12-2026",
            "08-2026 — 12-2026",
            "mc 06-2026_12-2026",
            "08.2026 do 12.2026",
            "08/2026 do 12/2026",
            "8-2026 do 12-2026",
        ],
    )
    def test_month_range_variants_are_read(self, period):
        assert m.bnp_order_period(period) is not None

    def test_first_and_last_day_of_the_month(self):
        assert m.bnp_order_period("08-2026 do 12-2026") == ("2026-08-01", "2026-12-31")

    def test_february_uses_the_real_number_of_days(self):
        assert m.bnp_order_period("02-2026 do 02-2026") == ("2026-02-01", "2026-02-28")
        assert m.bnp_order_period("02-2024 do 02-2024") == ("2024-02-01", "2024-02-29")

    @pytest.mark.parametrize(
        "text",
        [
            # Środek pełnej daty NIE jest okresem miesięcznym — inaczej
            # „01.08.2026 do 31.12.2026" czytałoby się jako 08-2026 → 12-2026,
            # czyli tę samą liczbę w innym znaczeniu.
            "od 01.08.2026 do 31.12.2026",
            "Data: 31-12-2026 do 31-01-2027",
            "Kwota 1 040,00 do 2 000,00",
            "Faktura 12/2026 pozycja 3",
            "nr 445-2026 z dnia 01-2026",
        ],
    )
    def test_month_range_refuses_lookalikes(self, text):
        assert m.bnp_order_period(text) is None

    # ── „Cena netto" → stawka za 1 MD ───────────────────────────────────────

    def test_price_comes_from_its_own_label(self):
        assert m.bnp_net_md_rate("Cena netto: 1 040,00 PLN") == Decimal("1040.00")
        assert m.bnp_net_md_rate("Cena jednostkowa netto (PLN): 1 040,00") == Decimal(
            "1040.00"
        )

    def test_price_ignores_neighbouring_labels(self):
        assert m.bnp_net_md_rate("Wartość netto: 109 200,00") is None
        assert m.bnp_net_md_rate("Cena brutto: 1 279,20") is None

    def test_price_refuses_to_guess_a_table_column(self):
        """Nagłówek tabeli = wartości leżą w innym wierszu, w kolumnach.

        Ekstrakcja z PDF gubi wyrównanie, więc „pierwsza liczba za etykietą"
        trafia w sąsiednią kolumnę. Zła stawka zapisana jako pewna wychodzi
        dopiero na fakturze — dlatego odmowa, nie zgadywanie.
        """
        table = "Lp Ilość Jm Cena netto Wartość netto\n1 105 szt. 1 040,00 109 200,00"
        assert m.bnp_net_md_rate(table) is None

    # ── „Szt." → liczba MD ──────────────────────────────────────────────────

    def test_quantity_does_not_glue_the_amount_from_the_line_above(self):
        """REGRESJA: ``\\s*`` przechodziło przez znak nowej linii.

        Kwota z wiersza wyżej sklejała się z „Szt." z wiersza niżej i do
        liczby MD trafiała STAWKA (1040 zamiast 105) — cicha pomyłka
        operacyjno-finansowa dokładnie tej klasy, przed którą chronią
        pozostałe polityki klientowe.
        """
        assert m.bnp_md_quantity("Cena netto: 1 040,00\nSzt.: 105\n") == Decimal("105")

    def test_quantity_does_not_glue_the_row_number(self):
        """REGRESJA: spacja jako separator tysięcy sklejała Lp. z ilością."""
        row = "Lp Ilość Jm Cena netto Wartość netto\n1 105 szt. 1 040,00 109 200,00"
        assert m.bnp_md_quantity(row) == Decimal("105")

    def test_quantity_reads_both_layouts(self):
        assert m.bnp_md_quantity("Ilość: 105 szt.") == Decimal("105")
        assert m.bnp_md_quantity("Szt.: 105") == Decimal("105")

    def test_quantity_needs_the_unit_not_a_similar_word(self):
        assert m.bnp_md_quantity("Sztywny 5") is None

    # ── Numer ID konsultanta ────────────────────────────────────────────────

    def test_consultant_ref_needs_a_word_about_a_person(self):
        assert m.bnp_consultant_ref("Konsultant ID: 4711") == "4711"
        # Sam „nr" stoi w dokumencie wszędzie — numer zamówienia nie może
        # udawać identyfikatora osoby.
        assert m.bnp_consultant_ref("Zamówienie nr 3728_2026") is None

    # ── Polityka jako całość ────────────────────────────────────────────────

    def test_full_document_fills_every_field(self):
        result = m.apply_bnp_order_policy(self._blank(), self._doc())
        assert (result.start_date, result.end_date) == ("2026-08-01", "2026-12-31")
        assert result.rate_client == Decimal("1040.00")
        assert result.rate_unit == "day"
        assert result.md_total == Decimal("105")
        assert result.consultant_ref == "4711"
        assert result.uncertain is False

    def test_single_consultant_document_keeps_the_matcher_flags(self):
        """Cały PDF JEST pozycją jednej osoby — nie ma czego dopasowywać.

        Bez tych flag ``enforce_consultant_policy_safety`` wyczyściłaby
        stawkę i MD, czyli dokładnie to, na co skarży się zgłoszenie.
        """
        result = m.apply_bnp_order_policy(self._blank(), self._doc())
        assert result.consultant_rate_matched is True
        assert result.consultant_md_matched is True
        assert m.enforce_consultant_policy_safety(result).rate_client == Decimal(
            "1040.00"
        )

    def test_missing_consultant_ref_is_reported(self):
        result = m.apply_bnp_order_policy(self._blank(), self._doc(ref="—"))
        assert result.consultant_ref is None
        assert result.uncertain is True
        assert any("ID konsultanta" in reason for reason in result.uncertain_reasons)

    def test_missing_labels_keep_the_model_value_but_flag_it(self):
        """Brak etykiety NIE czyści pola (inaczej niż w Credit Agricole).

        Tam kasowanie było odpowiedzią na udokumentowaną pomyłkę dwóch
        sąsiednich etykiet. Tu takiego incydentu nie ma, a wyczyszczenie
        zostawiłoby operatora BNP z pustym formularzem — czyli z tym, na co
        się skarży. Wartość zostaje, ale zawsze z komunikatem „sprawdź".
        """
        model = m.OrderExtraction(
            rate_client=Decimal("1040"),
            md_total=Decimal("105"),
            uncertain=False,
            source="claude",
        )
        result = m.apply_bnp_order_policy(model, "Zamówienie nr 3728_2026\n")
        assert result.rate_client == Decimal("1040")
        assert result.md_total == Decimal("105")
        assert result.uncertain is True
        assert any("Cena netto" in reason for reason in result.uncertain_reasons)
        assert any("Szt." in reason for reason in result.uncertain_reasons)

    def test_rate_unit_is_always_md_for_this_client(self):
        """Jednostka jest u BNP regułą klientową, nie interpretacją modelu."""
        model = m.OrderExtraction(
            rate_client=Decimal("130"), rate_unit="hour", source="claude"
        )
        assert m.apply_bnp_order_policy(model, self._doc()).rate_unit == "day"

    def test_rate_outside_the_sanity_band_is_flagged(self):
        result = m.apply_bnp_order_policy(
            self._blank(), self._doc(price="Cena netto: 12,00 PLN")
        )
        assert result.rate_client == Decimal("12.00")
        assert result.uncertain is True
        assert any("Nietypowa stawka" in r for r in result.uncertain_reasons)
