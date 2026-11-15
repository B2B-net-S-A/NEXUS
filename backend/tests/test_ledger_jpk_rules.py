"""JPK_V7M(3) (K5b) — reguły bez bazy: zaokrąglenie deklaracji, kontrahent,
pola P_ z ewidencji, oznaczenia KSeF, daty i walidacja schematem MF (XSD
z crd.gov.pl). Kwoty w groszach, firma, kontrahenci i numery fikcyjne."""

from __future__ import annotations

from datetime import datetime, timezone

from lxml import etree

from app.services.hr.payroll_lists.parameters import Company
from app.services.ledger import jpk

NS = {"j": jpk.NS}
COMPANY = Company(
    nip="1234567890",
    name="Spółka Testowa sp. z o.o.",
    short_name="Testowa",
    regon=None,
    tax_office_code="0202",
    zus_account=None,
    tax_account=None,
)
NOW = datetime(2026, 11, 15, 10, 0, tzinfo=timezone.utc)


def _ksef(day: str, tail: str) -> str:
    return f"1234567890-{day}-{tail}-AB"


def _row(number: str, groups: list[tuple[str, int, int]], **extra) -> dict:
    values = {
        "document_id": abs(hash(number)) % 10_000,
        "number": number,
        "ksef_number": None,
        "issue_date": "2026-03-31",
        "date": "2026-03-31",
        "counterparty": "Klient Testowy",
        "tax_id": "1111111111",
        "country": "PL",
        "net": sum(net for _, net, _ in groups),
        "vat": sum(tax for _, _, tax in groups),
        "groups": [{"key": key, "net": net, "vat": tax} for key, net, tax in groups],
        "correction": False,
        "payroll": False,
        "problem": None,
    }
    values.update(extra)
    return values


def _data() -> dict:
    return {
        "year": 2026,
        "month": 3,
        "sales": [
            _row(
                "FS 1/03",
                [("23", 100_000, 23_000)],
                issue_date="2026-04-02",
                ksef_number=_ksef("20260402", "0A1B2C3D4E5F"),
            ),
            _row(
                "1/03/UE",
                [("np_ue", 215_000, 0)],
                tax_id="FI28583949",
                country="FI",
                counterparty="Nordic Testbank Oyj",
                ksef_number=_ksef("20260331", "0A1B2C3D4E60"),
            ),
            _row(
                "FK 1/03",
                [("23", -10_000, -2_300)],
                correction=True,
                ksef_number=_ksef("20260331", "0A1B2C3D4E61"),
            ),
        ],
        "purchases": [
            _row(
                "FV 7/03",
                [("other", 100_000, 23_000)],
                issue_date="2026-03-10",
                date="2026-03-15",
                ksef_number=_ksef("20260310", "0A1B2C3D4E62"),
                counterparty="Dostawca Testowy",
            ),
            _row("ST 1/03", [("assets", 500_000, 115_000)], counterparty="Sprzedawca Sprzętu"),
        ],
    }


def _build(**extra):
    values = {
        "company": COMPANY,
        "email": "ksiegowosc@example.com",
        "phone": "",
        "purpose": "submission",
        "reason": None,
        "surplus": 0,
        "now": NOW,
    }
    values.update(extra)
    return jpk.build(_data(), **values)


def test_rounding_to_whole_zloty_follows_the_tax_ordinance():
    assert [jpk.zl(value) for value in (1_249, 1_250, -1_249, -1_250, 0)] == [12, 13, -12, -13, 0]
    assert (jpk.money(12_345), jpk.money(-230), jpk.money(5)) == ("123.45", "-2.30", "0.05")


def test_counterparty_number_goes_without_the_country_code():
    assert jpk.counterparty("1111111111", "PL") == (None, "1111111111")
    assert jpk.counterparty("PL1111111111", "PL") == (None, "1111111111")
    assert jpk.counterparty("ATU99999999", "AT") == ("AT", "U99999999")
    assert jpk.counterparty("FI28583949", "FI") == ("FI", "28583949")
    assert jpk.counterparty(None, None) == (None, "BRAK")


def test_declaration_rounds_each_field_and_carries_the_surplus():
    fields = jpk.declaration(
        {"K_19": 90_049, "K_20": 20_711, "K_42": 100_000, "K_43": 23_000},
        surplus=5,
    )
    assert (fields["P_19"], fields["P_20"], fields["P_37"], fields["P_38"]) == (900, 207, 900, 207)
    assert (fields["P_39"], fields["P_48"], fields["P_51"]) == (5, 235, 0)
    assert (fields["P_53"], fields["P_62"]) == (28, 28)
    due = jpk.declaration({"K_19": 100_000, "K_20": 23_000}, surplus=0)
    assert (due["P_51"], "P_53" in due, "P_39" in due) == (230, False, False)


def test_file_passes_the_mf_schema_and_carries_the_registers():
    content, totals = _build()
    assert jpk.validate(content) == []
    root = etree.fromstring(content)
    rows = root.findall(".//j:SprzedazWiersz", NS)
    assert [row.findtext("j:DowodSprzedazy", namespaces=NS) for row in rows] == ["FS 1/03", "1/03/UE", "FK 1/03"]
    first, eu, correction = rows
    # Data sprzedaży tylko, gdy inna niż wystawienia; krajowy NIP bez kodu kraju.
    assert first.findtext("j:DataSprzedazy", namespaces=NS) == "2026-03-31"
    assert first.find("j:KodKrajuNadaniaTIN", NS) is None
    assert (first.findtext("j:K_19", namespaces=NS), first.findtext("j:K_20", namespaces=NS)) == ("1000.00", "230.00")
    assert (eu.findtext("j:KodKrajuNadaniaTIN", namespaces=NS), eu.findtext("j:NrKontrahenta", namespaces=NS)) == ("FI", "28583949")
    assert (eu.findtext("j:K_11", namespaces=NS), eu.findtext("j:K_12", namespaces=NS)) == ("2150.00", "2150.00")
    assert correction.find("j:DataSprzedazy", NS) is None
    assert correction.findtext("j:K_20", namespaces=NS) == "-23.00"
    purchases = root.findall(".//j:ZakupWiersz", NS)
    assert purchases[0].findtext("j:DataWplywu", namespaces=NS) == "2026-03-15"
    assert purchases[0].findtext("j:NrKSeF", namespaces=NS) == _ksef("20260310", "0A1B2C3D4E62")
    # Faktura bez numeru KSeF = BFK (wystawiona poza KSeF).
    assert purchases[1].findtext("j:BFK", namespaces=NS) == "1"
    assert root.findtext(".//j:PodatekNalezny", namespaces=NS) == "207.00"
    assert root.findtext(".//j:PodatekNaliczony", namespaces=NS) == "1380.00"
    positions = root.find(".//j:PozycjeSzczegolowe", NS)
    values = {child.tag.split("}")[1]: int(child.text) for child in positions}
    assert values == {
        "P_11": 2150,
        "P_12": 2150,
        "P_19": 900,
        "P_20": 207,
        "P_37": 3050,
        "P_38": 207,
        "P_40": 5000,
        "P_41": 1150,
        "P_42": 1000,
        "P_43": 230,
        "P_48": 1380,
        "P_51": 0,
        "P_53": 1173,
        "P_62": 1173,
    }
    assert (totals["P_38"], totals["P_48"], totals["P_62"], totals["sales_rows"]) == (207, 1380, 1173, 3)
    assert root.findtext("j:Naglowek/j:CelZlozenia", namespaces=NS) == "1"


def test_correction_has_purpose_two_and_the_reason():
    content, _ = _build(purpose="correction", reason="Korekta faktury FK 1/03 ujęta w marcu.", phone="+48 22 000 00 00")
    assert jpk.validate(content) == []
    root = etree.fromstring(content)
    assert root.findtext("j:Naglowek/j:CelZlozenia", namespaces=NS) == "2"
    assert root.findtext(".//j:P_ORDZU", namespaces=NS) == "Korekta faktury FK 1/03 ujęta w marcu."
    assert root.findtext(".//j:Telefon", namespaces=NS) == "+48 22 000 00 00"


def test_schema_catches_a_broken_file():
    content, _ = _build()
    broken = content.replace(b"<KodUrzedu>0202</KodUrzedu>", b"<KodUrzedu>9999</KodUrzedu>")
    assert broken != content
    assert any("KodUrzedu" in error for error in jpk.validate(broken))


def test_counterparty_country_comes_from_the_identifier():
    """Przegląd K5b: kraj nadania z prefiksu numeru VAT UE, Grecja = EL."""

    assert jpk.counterparty("DE123456789", None) == ("DE", "123456789")
    assert jpk.counterparty("EL123456789", "GR") == ("EL", "123456789")
    assert jpk.counterparty("123456789", "GR") == ("EL", "123456789")


def test_control_characters_do_not_break_the_file():
    data = _data()
    data["sales"][0]["counterparty"] = "Klient\x01 Testowy\x0b"
    content, _ = jpk.build(
        data,
        company=COMPANY,
        email="ksiegowosc@example.com",
        phone="",
        purpose="submission",
        reason=None,
        surplus=0,
        now=NOW,
    )
    assert jpk.validate(content) == []
    root = etree.fromstring(content)
    assert root.find(".//j:SprzedazWiersz", NS).findtext("j:NazwaKontrahenta", namespaces=NS) == "Klient Testowy"


def test_rows_whose_amounts_do_not_fit_jpk_fields_are_listed():
    """VAT na grupie bez pola VAT (np. np UE) po cichu by zniknął z P_38."""

    data = _data()
    data["sales"][1]["vat"] = 23_000
    assert jpk.row_problems(data) == ["1/03/UE"]
    assert jpk.row_problems(_data()) == []


def test_periods_before_february_2026_are_refused():
    assert jpk.period_problem(2026, 1) and jpk.period_problem(2025, 12)
    assert jpk.period_problem(2026, 2) is None
