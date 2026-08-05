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
