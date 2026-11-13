"""Faktura FA(3) z KSeF → e-faktura Peppol BIS Billing 3 (plan Nordei N2).

Próbki w ``tests/data/peppol`` są zanonimizowane: sprzedawca, osoby, numery
NIDS, osób i rachunków są fikcyjne; nabywca to Nordea Bank Abp z jawnym numerem
VAT UE. Kwoty i układ pozycji odwzorowują prawdziwe faktury do Nordei
(rabat z umowy ramowej w ``P_10``, „np II”, kilka NIDS, EUR, korekty).

Walidacja biegnie na oficjalnych regułach EN16931 i Peppol (Schematron
skompilowany do XSLT 2.0, ``scripts/build_peppol_rules.py``).
"""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pytest
from lxml import etree

from app.services.peppol import fa_reader, ubl, validation

DATA = Path(__file__).parent / "data" / "peppol"
SENDER = ubl.PeppolId.parse("9945:PL9876543210")
RECEIVER = ubl.Receiver(ubl.PeppolId.parse("0088:7332545042126"))
NS = {"cac": ubl.NS_CAC, "cbc": ubl.NS_CBC}


def _build(name: str, **kwargs) -> ubl.UblResult:
    doc = fa_reader.read((DATA / name).read_bytes())
    return ubl.build(doc, sender=SENDER, receiver=RECEIVER, **kwargs)


def _tree(result: ubl.UblResult) -> etree._Element:
    return etree.fromstring(result.xml)


def _texts(root: etree._Element, path: str) -> list[str]:
    return [node.text for node in root.findall(path, NS)]


def test_discount_and_reverse_charge_invoice_maps_like_the_prototype():
    result = _build("fa_nordea_rabat_ae.xml")
    root = _tree(result)

    assert result.document_type == "invoice"
    assert result.total == Decimal("36679.50")
    assert _texts(root, "cbc:InvoiceTypeCode") == ["380"]
    assert _texts(root, "cbc:DocumentCurrencyCode") == ["PLN"]
    # Osoba kontaktowa Nordei z opisu pozycji — Peppol wymaga BuyerReference.
    assert _texts(root, "cbc:BuyerReference") == ["Anna Testowa"]
    assert _texts(root, ".//cac:AccountingCustomerParty//cbc:EndpointID") == [
        "7332545042126"
    ]
    assert (
        root.find(".//cac:AccountingCustomerParty//cbc:EndpointID", NS).get("schemeID")
        == "0088"
    )
    assert _texts(
        root, ".//cac:AccountingCustomerParty//cac:PartyTaxScheme/cbc:CompanyID"
    ) == ["FI28583949"]
    assert _texts(
        root, ".//cac:AccountingSupplierParty//cac:PartyTaxScheme/cbc:CompanyID"
    ) == ["PL9876543210"]
    # NIDS w AccountingCost każdej pozycji.
    assert _texts(root, "cac:InvoiceLine/cbc:AccountingCost") == [
        "1000000001",
        "1500000002",
        "1600000003",
    ]
    # Rabat 2,5% z umowy ramowej: cena przed rabatem 180,00, po rabacie 175,50.
    assert _texts(root, "cac:InvoiceLine/cac:Price/cbc:PriceAmount") == ["175.50"] * 3
    assert (
        _texts(root, "cac:InvoiceLine/cac:Price/cac:AllowanceCharge/cbc:BaseAmount")
        == ["180.00"] * 3
    )
    assert (
        _texts(root, "cac:InvoiceLine/cac:Price/cac:AllowanceCharge/cbc:Amount")
        == ["4.50"] * 3
    )
    assert _texts(root, "cac:InvoiceLine/cbc:InvoicedQuantity") == [
        "86",
        "103.5",
        "19.5",
    ]
    # Odwrotne obciążenie: AE, 0%, kod zwolnienia VATEX-EU-AE.
    assert _texts(root, "cac:TaxTotal/cac:TaxSubtotal/cac:TaxCategory/cbc:ID") == ["AE"]
    assert _texts(root, ".//cbc:TaxExemptionReasonCode") == ["VATEX-EU-AE"]
    assert _texts(root, "cac:TaxTotal/cbc:TaxAmount") == ["0.00"]
    assert _texts(root, "cac:LegalMonetaryTotal/cbc:PayableAmount") == ["36679.50"]
    assert "Frame Agreement" in _texts(root, "cbc:Note")[0]
    assert _texts(root, "cbc:DueDate") == ["2026-12-05"]
    assert _texts(root, ".//cac:PayeeFinancialAccount/cbc:ID") == [
        "PL11111111110000000011111111"
    ]


def test_invoice_in_eur_keeps_currency_without_tax_currency_for_reverse_charge():
    root = _tree(_build("fa_nordea_eur.xml"))

    assert _texts(root, "cbc:DocumentCurrencyCode") == ["EUR"]
    assert root.find("cbc:TaxCurrencyCode", NS) is None
    currencies = {
        node.get("currencyID") for node in root.iter() if node.get("currencyID")
    }
    assert currencies == {"EUR"}
    assert _texts(root, "cac:InvoiceLine/cac:Price/cbc:PriceAmount") == ["58.50"]
    assert _texts(root, "cac:LegalMonetaryTotal/cbc:PayableAmount") == ["5674.50"]


def test_correction_down_becomes_credit_note_with_positive_difference():
    result = _build("fa_nordea_korekta_minus.xml")
    root = _tree(result)

    assert result.document_type == "credit_note"
    assert etree.QName(root).localname == "CreditNote"
    assert _texts(root, "cbc:CreditNoteTypeCode") == ["381"]
    assert root.find("cbc:DueDate", NS) is None
    assert _texts(root, "cac:BillingReference/cac:InvoiceDocumentReference/cbc:ID") == [
        "5/10/2026/UE"
    ]
    assert _texts(
        root, "cac:BillingReference/cac:InvoiceDocumentReference/cbc:IssueDate"
    ) == ["2026-10-02"]
    # 160 h → 152 h po 175,50: korekta o 8 h = 1 404,00.
    assert _texts(root, "cac:CreditNoteLine/cbc:CreditedQuantity") == ["8"]
    assert _texts(root, "cac:CreditNoteLine/cbc:LineExtensionAmount") == ["1404.00"]
    assert _texts(root, "cac:LegalMonetaryTotal/cbc:PayableAmount") == ["1404.00"]
    assert _texts(root, "cac:CreditNoteLine/cbc:AccountingCost") == ["2023-000001"]


def test_correction_up_becomes_invoice_referencing_the_original():
    result = _build("fa_nordea_korekta_plus.xml")
    root = _tree(result)

    assert result.document_type == "invoice"
    assert _texts(root, "cbc:InvoiceTypeCode") == ["380"]
    assert _texts(root, "cac:BillingReference/cac:InvoiceDocumentReference/cbc:ID") == [
        "7/11/2026/UE"
    ]
    assert _texts(root, "cac:InvoiceLine/cbc:InvoicedQuantity") == ["4"]
    assert _texts(root, "cac:InvoiceLine/cbc:LineExtensionAmount") == ["480.00"]
    assert _texts(root, "cac:InvoiceLine/cac:Price/cbc:PriceAmount") == ["120.00"]
    assert root.find("cac:InvoiceLine/cac:Price/cac:AllowanceCharge", NS) is None
    assert _texts(root, "cbc:Note")[0].startswith("Correction of invoice 7/11/2026/UE")


def test_correction_without_amount_change_is_not_sent():
    doc = fa_reader.read((DATA / "fa_nordea_korekta_data.xml").read_bytes())

    with pytest.raises(ubl.NothingToSend):
        ubl.build(doc, sender=SENDER, receiver=RECEIVER)


def test_polish_branch_with_standard_rate_has_vat_breakdown():
    root = _tree(_build("fa_nordea_oddzial_23.xml"))

    assert _texts(root, "cac:TaxTotal/cac:TaxSubtotal/cac:TaxCategory/cbc:ID") == ["S"]
    assert _texts(root, "cac:TaxTotal/cac:TaxSubtotal/cac:TaxCategory/cbc:Percent") == [
        "23"
    ]
    assert _texts(root, "cac:TaxTotal/cbc:TaxAmount") == ["5932.42"]
    assert _texts(root, "cac:LegalMonetaryTotal/cbc:PayableAmount") == ["31725.56"]
    assert _texts(
        root, ".//cac:AccountingCustomerParty//cac:PartyTaxScheme/cbc:CompanyID"
    ) == ["PL1111111111"]
    # Adres w jednej linii: kod i miasto wyciągnięte z AdresL1.
    assert _texts(root, ".//cac:AccountingCustomerParty//cbc:PostalZone") == ["00-002"]
    assert _texts(root, ".//cac:AccountingCustomerParty//cbc:CityName") == ["Warszawa"]
    # 157,00 − 2,5% = 153,075 — cena z trzema miejscami, R120 nadal spełnione.
    assert _texts(root, "cac:InvoiceLine/cac:Price/cbc:PriceAmount") == ["153.075"]


def test_pdf_goes_to_additional_document_reference():
    root = _tree(
        _build(
            "fa_nordea_rabat_ae.xml", attachment=ubl.Attachment("f.pdf", b"%PDF-1.4 x")
        )
    )

    node = root.find(
        "cac:AdditionalDocumentReference/cac:Attachment/cbc:EmbeddedDocumentBinaryObject",
        NS,
    )
    assert node.get("mimeCode") == "application/pdf"
    assert node.get("filename") == "f.pdf"
    assert node.text == "JVBERi0xLjQgeA=="


@pytest.mark.parametrize(
    "name",
    [
        "fa_nordea_rabat_ae.xml",
        "fa_nordea_eur.xml",
        "fa_nordea_korekta_minus.xml",
        "fa_nordea_korekta_plus.xml",
        "fa_nordea_oddzial_23.xml",
    ],
)
def test_samples_pass_en16931_and_peppol_rules(name):
    result = _build(name, attachment=ubl.Attachment("f.pdf", b"%PDF-1.4 x"))

    assert validation.validate(result.xml) == []


def test_validator_reports_broken_document():
    result = _build("fa_nordea_rabat_ae.xml")
    broken = result.xml.replace(
        b"<cbc:BuyerReference>Anna Testowa</cbc:BuyerReference>", b""
    )
    broken = broken.replace(
        b"<cbc:TaxExemptionReasonCode>VATEX-EU-AE</cbc:TaxExemptionReasonCode>", b""
    )
    broken = broken.replace(
        b"<cbc:TaxExemptionReason>Reverse charge</cbc:TaxExemptionReason>", b""
    )

    rules = {
        finding.rule for finding in validation.blocking(validation.validate(broken))
    }

    assert {"PEPPOL-EN16931-R003", "BR-AE-10"} <= rules


def test_unsupported_rate_is_refused_instead_of_guessed():
    xml = (
        (DATA / "fa_nordea_eur.xml")
        .read_bytes()
        .replace(b"<P_12>np II</P_12>", b"<P_12>zw</P_12>")
    )

    with pytest.raises(ubl.ConversionError) as exc:
        ubl.build(fa_reader.read(xml), sender=SENDER, receiver=RECEIVER)

    assert exc.value.code == "unsupported_rate"


def test_lines_must_add_up_to_invoice_net():
    xml = (
        (DATA / "fa_nordea_eur.xml")
        .read_bytes()
        .replace(b"<P_13_9>5674.50</P_13_9>", b"<P_13_9>5674.60</P_13_9>")
    )

    with pytest.raises(ubl.ConversionError) as exc:
        ubl.build(fa_reader.read(xml), sender=SENDER, receiver=RECEIVER)

    assert exc.value.code == "net_mismatch"


def test_price_that_does_not_divide_goes_as_line_allowance():
    # 333 h po 31,00 z rabatem do 10 000,01: żadna cena z 4 miejscami po
    # przecinku nie daje tej kwoty (krok 0,0001 × 333 h > 1 grosz).
    xml = (DATA / "fa_nordea_eur.xml").read_bytes()
    xml = xml.replace(b"<P_8B>97</P_8B>", b"<P_8B>333</P_8B>")
    xml = xml.replace(
        b"<P_9A>60.00</P_9A><P_10>145.50</P_10><P_11>5674.50</P_11>",
        b"<P_9A>31.00</P_9A><P_10>322.99</P_10><P_11>10000.01</P_11>",
    )
    xml = xml.replace(b"5674.50", b"10000.01")
    result = ubl.build(fa_reader.read(xml), sender=SENDER, receiver=RECEIVER)
    root = _tree(result)

    assert _texts(root, "cac:InvoiceLine/cac:Price/cbc:PriceAmount") == ["31.00"]
    assert _texts(root, "cac:InvoiceLine/cac:AllowanceCharge/cbc:Amount") == ["322.99"]
    assert _texts(root, "cac:InvoiceLine/cbc:LineExtensionAmount") == ["10000.01"]
    assert validation.blocking(validation.validate(result.xml)) == []


def test_bad_receiver_id_is_refused():
    with pytest.raises(ubl.ConversionError):
        ubl.PeppolId.parse("7332545042126")


def test_vat_comes_from_ksef_not_from_rounding_the_difference():
    # Korekta 100,02 → 100,04 przy 23%: KSeF ma VAT różnicy 0,01 (23,01 − 23,00),
    # a 23% od 0,02 to 0,00. E-faktura musi mieć kwoty z KSeF.
    xml = (DATA / "fa_nordea_oddzial_23.xml").read_bytes()
    xml = xml.replace(
        b"<RodzajFaktury>VAT</RodzajFaktury>",
        b"<RodzajFaktury>KOR</RodzajFaktury><PrzyczynaKorekty>Korekta</PrzyczynaKorekty><TypKorekty>2</TypKorekty>"
        b"<DaneFaKorygowanej><DataWystFaKorygowanej>2026-10-02</DataWystFaKorygowanej><NrFaKorygowanej>9/10/2026</NrFaKorygowanej>"
        b"<NrKSeF>1</NrKSeF><NrKSeFFaKorygowanej>9876543210-20261002-0A0B0C0D0E0F-11</NrKSeFFaKorygowanej></DaneFaKorygowanej>",
    )
    start = xml.index(b"    <FaWiersz>")
    end = xml.index(b"    <Platnosc>")
    xml = (
        xml[:start]
        + b"    <FaWiersz><NrWierszaFa>1</NrWierszaFa><P_7>Usluga</P_7><P_8A>szt.</P_8A><P_8B>1</P_8B><P_9A>100.04</P_9A><P_11>100.04</P_11><P_12>23</P_12></FaWiersz>\n"
        + b"    <FaWiersz><NrWierszaFa>1</NrWierszaFa><P_7>Usluga</P_7><P_8A>szt.</P_8A><P_8B>1</P_8B><P_9A>100.02</P_9A><P_11>100.02</P_11><P_12>23</P_12><StanPrzed>1</StanPrzed></FaWiersz>\n"
        + xml[end:]
    )
    xml = xml.replace(b"<P_13_1>25793.14</P_13_1>", b"<P_13_1>0.02</P_13_1>")
    xml = xml.replace(b"<P_14_1>5932.42</P_14_1>", b"<P_14_1>0.01</P_14_1>")
    xml = xml.replace(b"<P_15>31725.56</P_15>", b"<P_15>0.03</P_15>")

    result = ubl.build(fa_reader.read(xml), sender=SENDER, receiver=RECEIVER)
    root = _tree(result)

    assert _texts(root, "cac:TaxTotal/cbc:TaxAmount") == ["0.01"]
    assert _texts(root, "cac:LegalMonetaryTotal/cbc:PayableAmount") == ["0.03"]
    assert validation.blocking(validation.validate(result.xml)) == []


def test_vat_different_from_ksef_by_a_cent_is_refused():
    xml = (DATA / "fa_nordea_oddzial_23.xml").read_bytes()
    xml = xml.replace(b"<P_14_1>5932.42</P_14_1>", b"<P_14_1>5932.43</P_14_1>")

    with pytest.raises(ubl.ConversionError) as exc:
        ubl.build(fa_reader.read(xml), sender=SENDER, receiver=RECEIVER)

    assert exc.value.code == "gross_mismatch"
