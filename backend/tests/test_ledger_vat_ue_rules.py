"""VAT-UE(5) (K5b-3a) — reguły bez bazy: pozycje z rejestru sprzedaży (usługi
np II i WDT), suma per kontrahent w pełnych złotych, problemy i walidacja
schematem MF z crd.gov.pl. Firma, kontrahenci i numery fikcyjne."""

from __future__ import annotations

from lxml import etree

from app.services.hr.payroll_lists.parameters import Company
from app.services.ledger import vat_ue

NS = {"u": vat_ue.NS, "etd": vat_ue.ETD}
COMPANY = Company(
    nip="1234567890",
    name="Spółka Testowa sp. z o.o.",
    short_name="Testowa",
    regon=None,
    tax_office_code="0202",
    zus_account=None,
    tax_account=None,
)


def _row(number: str, key: str, net: int, *, tax_id: str | None, country: str | None, name: str = "Klient UE") -> dict:
    return {
        "document_id": abs(hash(number)) % 10_000,
        "number": number,
        "counterparty": name,
        "tax_id": tax_id,
        "country": country,
        "net": net,
        "vat": 0,
        "groups": [{"key": key, "net": net, "vat": 0}],
    }


def _data(*rows: dict) -> dict:
    return {"year": 2026, "month": 3, "sales": list(rows), "purchases": []}


def test_services_and_goods_per_counterparty_in_whole_zloty():
    data = _data(
        _row("1/03/UE", "np_ue", 215_000, tax_id="FI28583949", country="FI", name="Nordic Testbank"),
        _row("2/03/UE", "np_ue", 100_049, tax_id="FI28583949", country="FI", name="Nordic Testbank"),
        _row("3/03/UE", "np_ue", 50_000, tax_id="EL123456789", country="GR", name="Hellenic Test"),
        _row("4/03/WDT", "0_wdt", 12_350, tax_id="DE123456789", country="DE", name="Test GmbH"),
        _row("FS 5/03", "23", 100_000, tax_id="1111111111", country="PL"),
    )
    lines, problems = vat_ue.collect(data)
    assert problems == []
    assert [(line.section, line.country, line.number, line.amount, line.documents) for line in lines] == [
        ("goods", "DE", "123456789", 124, ["4/03/WDT"]),
        ("services", "EL", "123456789", 500, ["3/03/UE"]),
        # 2150,00 + 1000,49 = 3150,49 zł → 3150 zł.
        ("services", "FI", "28583949", 3150, ["1/03/UE", "2/03/UE"]),
    ]
    content = vat_ue.build(lines, company=COMPANY, year=2026, month=3)
    assert vat_ue.validate(content) == []
    root = etree.fromstring(content)
    services = root.findall(".//u:Grupa3", NS)
    assert [(g.findtext("u:P_Ua", namespaces=NS), g.findtext("u:P_Ub", namespaces=NS), g.findtext("u:P_Uc", namespaces=NS)) for g in services] == [
        ("EL", "123456789", "500"),
        ("FI", "28583949", "3150"),
    ]
    goods = root.find(".//u:Grupa1", NS)
    assert (goods.findtext("u:P_Da", namespaces=NS), goods.findtext("u:P_Dc", namespaces=NS), goods.findtext("u:P_Dd", namespaces=NS)) == ("DE", "124", "2")
    assert root.findtext("u:Naglowek/u:CelZlozenia", namespaces=NS) == "1"
    assert root.findtext(".//etd:NIP", namespaces=NS) == "1234567890"


def test_buyer_without_eu_vat_number_and_negative_month_are_problems():
    data = _data(
        _row("1/03/UE", "np_ue", 215_000, tax_id="1111111111", country="PL", name="Polski nabywca"),
        _row("KOR 2/03", "np_ue", -50_000, tax_id="SE556677889901", country="SE"),
        _row("2/03/UE", "np_ue", 10_000, tax_id="SE556677889901", country="SE"),
        # Irlandia Północna: VAT UE tylko dla towarów — usługa nie wchodzi.
        _row("3/03/UE", "np_ue", 10_000, tax_id="XI123456789", country="GB"),
    )
    lines, problems = vat_ue.collect(data)
    assert lines == []
    details = {item["number"]: item["detail"] for item in problems}
    assert "bez numeru VAT UE" in details["1/03/UE"]
    assert "poniżej zera" in details["KOR 2/03, 2/03/UE"]
    assert "nie pasuje do VAT-UE" in details["3/03/UE"]


def test_schema_catches_a_broken_file():
    lines, _ = vat_ue.collect(_data(_row("1/03/UE", "np_ue", 215_000, tax_id="FI28583949", country="FI")))
    content = vat_ue.build(lines, company=COMPANY, year=2026, month=3)
    broken = content.replace(b"<P_Ua>FI</P_Ua>", b"<P_Ua>PL</P_Ua>")
    assert broken != content
    assert any("P_Ua" in error for error in vat_ue.validate(broken))
