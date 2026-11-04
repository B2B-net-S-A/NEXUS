"""Odczyt faktury FA(3)/FA(2) z KSeF (R1, R7): sprzedawca, kwoty, okres, pozycje, korekta.

Faktury fikcyjne z ``tests/data/ksef`` i warianty składane w teście.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from app.services.hr.ksef import fa
from tests._ksef_fake import (
    ANNA_CORRECTION,
    ANNA_INVOICE,
    ANNA_NIP,
    COMPANY_NIP,
    DATA_DIR,
    OLA_INVOICE,
    OLA_NIP,
)

FA3 = "http://crd.gov.pl/wzor/2025/06/25/13775/"
FA2 = "http://crd.gov.pl/wzor/2023/06/29/12648/"


def _fixture(number: str) -> bytes:
    return (DATA_DIR / f"{number}.xml").read_bytes()


def _invoice(
    fa_body: str,
    *,
    namespace: str = FA3,
    variant: str = "3",
    seller: str = OLA_NIP,
    head: str = "",
) -> bytes:
    return f"""<?xml version="1.0" encoding="UTF-8"?>{head}
<Faktura xmlns="{namespace}">
  <Naglowek>
    <KodFormularza kodSystemowy="FA ({variant})" wersjaSchemy="1-0E">FA</KodFormularza>
    <WariantFormularza>{variant}</WariantFormularza>
  </Naglowek>
  <Podmiot1><DaneIdentyfikacyjne><NIP>{seller}</NIP><Nazwa>Firma Przykładowa</Nazwa></DaneIdentyfikacyjne></Podmiot1>
  <Podmiot2><DaneIdentyfikacyjne><NIP>{COMPANY_NIP}</NIP><Nazwa>Spółka Testowa</Nazwa></DaneIdentyfikacyjne></Podmiot2>
  <Fa>{fa_body}</Fa>
</Faktura>""".encode()


BASIC = """
    <KodWaluty>PLN</KodWaluty><P_1>2026-11-04</P_1><P_2>FV 10/2026</P_2>
    <P_13_1>1000.00</P_13_1><P_14_1>230.00</P_14_1><P_15>1230.00</P_15>
    <RodzajFaktury>VAT</RodzajFaktury>
    <FaWiersz><NrWierszaFa>1</NrWierszaFa><P_7>Usługi</P_7><P_8A>h</P_8A>
      <P_8B>10</P_8B><P_9A>100.00</P_9A><P_11>1000.00</P_11><P_12>23</P_12></FaWiersz>
"""


def test_faktura_ola_z_data_sprzedazy():
    parsed = fa.parse_invoice(_fixture(OLA_INVOICE))
    assert parsed.form == "FA(3)"
    assert parsed.seller_nip == OLA_NIP
    assert parsed.seller_name == "Nowak Recruitment Ola Nowak"
    assert parsed.buyer_nip == COMPANY_NIP
    assert parsed.invoice_number == "FV 9/2026"
    assert parsed.kind == "original"
    assert parsed.issue_date == date(2026, 10, 3)
    assert parsed.sale_date == date(2026, 9, 30)
    assert parsed.period == (2026, 9)
    assert parsed.currency == "PLN"
    assert (parsed.net_amount, parsed.vat_amount, parsed.gross_amount) == (
        Decimal("16400.00"),
        Decimal("3772.00"),
        Decimal("20172.00"),
    )
    # Kształt czytany przez widok rozbieżności (R-A): napisy dziesiętne z kropką.
    assert parsed.items == [
        {
            "name": "Usługi rekrutacyjne, wrzesień 2026",
            "quantity": "160",
            "unit": "h",
            "unit_price": "95.00",
            "net": "15200.00",
            "vat_rate": "23",
        },
        {
            "name": "Premia za placement",
            "quantity": "1",
            "unit": "szt.",
            "unit_price": "1200.00",
            "net": "1200.00",
            "vat_rate": "23",
        },
    ]


def test_okres_z_okresfa():
    parsed = fa.parse_invoice(_fixture(ANNA_INVOICE))
    assert parsed.seller_nip == ANNA_NIP
    assert parsed.period == (2026, 9)
    assert parsed.sale_date == date(2026, 9, 30)
    assert parsed.items[0]["quantity"] == "153.3"


def test_korekta_roznice_i_faktura_pierwotna():
    parsed = fa.parse_invoice(_fixture(ANNA_CORRECTION))
    assert parsed.kind == "correction"
    assert parsed.invoice_type == "KOR"
    assert parsed.corrected_ksef_number == ANNA_INVOICE
    assert parsed.corrected_invoice_number == "FV/26/09/26"
    assert parsed.net_amount == Decimal("-120.00")
    assert parsed.vat_amount == Decimal("-27.60")
    assert parsed.gross_amount == Decimal("-147.60")
    # Bez daty sprzedaży — okres dziedziczy po pierwotnej przy zapisie.
    assert parsed.period is None
    assert parsed.items[0]["before_correction"] is True
    assert "before_correction" not in parsed.items[1]


def test_bez_dat_sprzedazy_okres_pusty_a_nie_z_daty_wystawienia():
    parsed = fa.parse_invoice(_invoice(BASIC))
    assert parsed.period is None
    assert parsed.sale_date is None


def test_okres_ze_wspolnego_miesiaca_pozycji():
    body = BASIC.replace(
        "<P_7>Usługi</P_7>", "<P_6A>2026-10-31</P_6A><P_7>Usługi</P_7>"
    )
    assert fa.parse_invoice(_invoice(body)).period == (2026, 10)


def test_rozne_miesiace_pozycji_to_brak_okresu():
    body = BASIC.replace(
        "<P_7>Usługi</P_7>", "<P_6A>2026-10-31</P_6A><P_7>Usługi</P_7>"
    ) + BASIC[BASIC.index("<FaWiersz>") :].replace(
        "<P_7>Usługi</P_7>", "<P_6A>2026-09-30</P_6A><P_7>Usługi</P_7>"
    )
    assert fa.parse_invoice(_invoice(body)).period is None


def test_zwolniony_z_vat_netto_rowne_brutto():
    body = """
        <KodWaluty>PLN</KodWaluty><P_1>2026-10-31</P_1><P_2>1/10/2026</P_2>
        <P_13_7>3200.00</P_13_7><P_15>3200.00</P_15><RodzajFaktury>VAT</RodzajFaktury>
    """
    parsed = fa.parse_invoice(_invoice(body))
    assert parsed.net_amount == Decimal("3200.00")
    assert parsed.vat_amount == Decimal("0.00")


def test_bez_sum_netto_kwota_z_brutto():
    body = """
        <KodWaluty>PLN</KodWaluty><P_1>2026-10-31</P_1><P_2>U/1</P_2>
        <P_15>123.00</P_15><RodzajFaktury>UPR</RodzajFaktury>
    """
    parsed = fa.parse_invoice(_invoice(body))
    assert parsed.net_amount is None
    assert parsed.gross_amount == Decimal("123.00")


def test_wariant_fa2():
    parsed = fa.parse_invoice(_invoice(BASIC, namespace=FA2, variant="2"))
    assert parsed.form == "FA(2)"
    assert parsed.net_amount == Decimal("1000.00")


def test_waluta_euro():
    parsed = fa.parse_invoice(_invoice(BASIC.replace(">PLN<", ">EUR<")))
    assert parsed.currency == "EUR"


@pytest.mark.parametrize(
    ("xml", "code"),
    [
        (b"<Faktura", "malformed"),
        (b"<?xml version='1.0'?><Zamowienie/>", "not_invoice"),
        (_invoice(BASIC, variant="1"), "unsupported_form"),
        (_invoice(BASIC, seller="12345"), "missing_seller"),
        (_invoice(BASIC.replace("<P_2>FV 10/2026</P_2>", "")), "missing_number"),
        (_invoice(BASIC.replace("<P_1>2026-11-04</P_1>", "")), "missing_issue_date"),
        (_invoice(BASIC.replace("<P_15>1230.00</P_15>", "")), "missing_amounts"),
        (_invoice(BASIC.replace(">PLN<", ">GBP<")), "unsupported_currency"),
        (_invoice(BASIC.replace("1000.00</P_13_1>", "dużo</P_13_1>")), "bad_amount"),
        (_invoice(BASIC.replace("1000.00</P_13_1>", "1e12</P_13_1>")), "bad_amount"),
    ],
)
def test_odrzucone_pliki(xml, code):
    with pytest.raises(fa.InvoiceParseError) as caught:
        fa.parse_invoice(xml)
    assert caught.value.code == code


def test_deklaracja_dtd_i_encje_odrzucone():
    bomb = _invoice(
        BASIC.replace("<P_2>FV 10/2026</P_2>", "<P_2>&lol;</P_2>"),
        head='<!DOCTYPE Faktura [<!ENTITY lol "lol">]>',
    )
    with pytest.raises(fa.InvoiceParseError) as caught:
        fa.parse_invoice(bomb)
    assert caught.value.code == "doctype"


def test_za_duzy_plik_i_za_duzo_pozycji(monkeypatch):
    monkeypatch.setattr(fa, "MAX_XML_BYTES", 100)
    with pytest.raises(fa.InvoiceParseError) as caught:
        fa.parse_invoice(_invoice(BASIC))
    assert caught.value.code == "too_large"
    monkeypatch.setattr(fa, "MAX_XML_BYTES", 5 * 1024 * 1024)
    monkeypatch.setattr(fa, "MAX_ITEMS", 0)
    with pytest.raises(fa.InvoiceParseError) as caught:
        fa.parse_invoice(_invoice(BASIC))
    assert caught.value.code == "too_many_items"


def test_okres_spoza_lat_plac_to_brak_okresu():
    old = BASIC.replace(
        "<P_1>2026-11-04</P_1>", "<P_1>2026-11-04</P_1><P_6>2019-12-31</P_6>"
    )
    parsed = fa.parse_invoice(_invoice(old))
    assert parsed.sale_date == date(2019, 12, 31)
    assert parsed.period is None
