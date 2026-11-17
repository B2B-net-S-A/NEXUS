"""Adres nabywcy z ``Podmiot2/Adres`` faktury sprzedażowej (0730) — bez bazy.

XML-e są sfabrykowane z fikstury KSeF (``tests/data/ksef/sales``): fikcyjny
nabywca i adres, bez danych prawdziwych firm (repo jest publiczne).
"""

from __future__ import annotations

from datetime import datetime, timezone

from app.services.client_invoicing import buyer_address, fa_sales
from tests.client_invoicing import helpers as fx

_FIXTURE = (fx.DATA_DIR / f"{fx.KSEF_118}.xml").read_bytes().decode("utf-8")
_ADDRESS = "<Adres><KodKraju>PL</KodKraju><AdresL1>ul. Przykładowa 5</AdresL1></Adres>"


def _xml(address: str) -> bytes:
    assert _FIXTURE.count(_ADDRESS) == 1
    return _FIXTURE.replace(_ADDRESS, address).encode("utf-8")


def test_reads_country_and_both_address_lines():
    sales = fa_sales.parse_sales_invoice(
        _xml(
            "<Adres><KodKraju>pl</KodKraju>"
            "<AdresL1>ul. Testowa  12/3\n</AdresL1><AdresL2>00-001 Warszawa</AdresL2>"
            "</Adres>"
        )
    )
    assert sales.buyer_address == fa_sales.BuyerAddress(
        country="PL", line1="ul. Testowa 12/3", line2="00-001 Warszawa"
    )


def test_seller_address_is_not_taken_for_the_buyer():
    sales = fa_sales.parse_sales_invoice(_xml(""))
    assert sales.buyer_address is None


def test_empty_address_lines_mean_no_address():
    sales = fa_sales.parse_sales_invoice(
        _xml("<Adres><KodKraju>PL</KodKraju><AdresL1>  </AdresL1></Adres>")
    )
    assert sales.buyer_address is None


def test_long_line_is_cut_to_the_column_length():
    sales = fa_sales.parse_sales_invoice(
        _xml(f"<Adres><KodKraju>PL</KodKraju><AdresL1>{'a' * 600}</AdresL1></Adres>")
    )
    assert len(sales.buyer_address.line1) == fa_sales.ADDRESS_LINE_MAX_LENGTH


def test_columns_mark_the_invoice_as_read_also_without_address():
    now = datetime(2026, 11, 17, 12, 0, tzinfo=timezone.utc)
    assert buyer_address.columns(None, now) == {
        "buyer_country": None,
        "buyer_address_line1": None,
        "buyer_address_line2": None,
        "buyer_address_read_at": now,
    }
    sales = fa_sales.parse_sales_invoice(_xml(_ADDRESS))
    assert buyer_address.columns(sales, now)["buyer_address_line1"] == (
        "ul. Przykładowa 5"
    )
