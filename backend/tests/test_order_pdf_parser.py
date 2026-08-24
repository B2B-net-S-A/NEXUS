"""Testy jednostkowe parsera PDF zamówienia (``order_pdf_parser``).

Czysta logika (bez DB / bez sieci): normalizacja dat/kwot, regexowy fallback
(w tym okres BNP ``mc MM-RRRR_MM-RRRR``), normalizacja odpowiedzi Claude i reguły
niepewności. Bez klucza ANTHROPIC ``parse_order_document`` degraduje do regexu.
"""

from decimal import Decimal

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
        assert any("Nietypowa stawka godzinowa" in r for r in enforced.uncertain_reasons)

    def test_hourly_rate_above_band_warns(self):
        result = m.OrderExtraction(
            rate_client=Decimal("2401"),  # 300.13 zł/h
            start_date="2026-01-01",
            end_date="2026-06-30",
            source="claude",
        )
        enforced = m.apply_bank_pocztowy_order_policy(result, "Numer pisma: BP/4/26")
        assert enforced.uncertain is True
        assert any("Nietypowa stawka godzinowa" in r for r in enforced.uncertain_reasons)

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
            uncertain_reasons=[
                "Odczyt awaryjny (bez AI) — zweryfikuj wszystkie pola"
            ],
            source="regex",
        )
        enforced = m.apply_bank_pocztowy_order_policy(result, "Numer pisma: BP/7/26")
        assert enforced.uncertain is True
        assert any("Odczyt awaryjny" in r for r in enforced.uncertain_reasons)

    def test_no_rate_in_document_leaves_rate_fields_untouched(self):
        result = m.OrderExtraction(
            start_date="2026-01-01", end_date="2026-06-30", source="claude"
        )
        enforced = m.apply_bank_pocztowy_order_policy(result, "Numer pisma: BP/8/26")
        assert enforced.rate_client is None
        assert enforced.rate_client_md is None
        # Brak stawki nie jest na białej liście komunikatów — pole po prostu
        # zostaje puste do ręcznego uzupełnienia.
        assert enforced.uncertain_reasons == []

    def test_net_formula_with_thousands_and_spaces(self):
        assert m.bank_pocztowy_net_md_rate(
            "Wynagrodzenie: 1 600,00 * 1,23 * 20 MD"
        ) == Decimal("1600.00")
        assert m.bank_pocztowy_net_md_rate("1600 x 1.23 x 20") == Decimal("1600")
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
