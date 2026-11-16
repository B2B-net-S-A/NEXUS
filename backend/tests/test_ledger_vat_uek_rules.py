"""VAT-UEK(5) (K5b-3c) — reguły bez bazy: „było” i „jest” per kontrahent z korekt
miesiąca K do okresu faktury pierwotnej, pozycje dopisane i usunięte, problemy
i walidacja schematem MF. Firma, kontrahenci i numery fikcyjne."""

from __future__ import annotations

from lxml import etree

from app.services.hr.payroll_lists.parameters import Company
from app.services.ledger import vat_ue, vat_uek

NS = {"k": vat_uek.NS, "etd": vat_uek.ETD}
COMPANY = Company(
    nip="1234567890",
    name="Spółka Testowa sp. z o.o.",
    short_name="Testowa",
    regon=None,
    tax_office_code="0202",
    zus_account=None,
    tax_account=None,
)
PERIOD = "2026-02"


def _row(
    number: str,
    key: str,
    net: int,
    *,
    tax_id: str | None,
    name: str = "Klient UE",
    corrected_month: str | None = None,
) -> dict:
    return {
        "correction": corrected_month is not None,
        "corrected_month": corrected_month,
        "document_id": abs(hash(number)) % 10_000,
        "number": number,
        "counterparty": name,
        "tax_id": tax_id,
        "country": None,
        "net": net,
        "vat": 0,
        "groups": [{"key": key, "net": net, "vat": 0}],
    }


def _base(*rows: dict) -> dict:
    lines, problems = vat_ue.gather(
        {"year": 2026, "month": 2, "sales": list(rows), "purchases": []}
    )
    assert problems == []
    return lines


def _amounts(positions: list[vat_uek.Position]) -> dict[str, tuple[int, int]]:
    return {
        f"{item.country}{item.number}": (item.before_amount, item.after_amount)
        for item in positions
    }


def test_before_is_the_period_with_earlier_corrections_and_after_adds_month_k():
    """Decyzja Artura 16.11.2026: „było” = VAT-UE za luty z rejestru lutego +
    korekty z marca (VAT-UEK z marca złożona), „jest” = + korekty z kwietnia."""

    base = _base(
        _row(
            "1/02/UE", "np_ue", 1_000_000, tax_id="FI28583949", name="Nordic Testbank"
        ),
        _row("2/02/UE", "np_ue", 300_000, tax_id="DE123456789", name="Test GmbH"),
        _row("3/02/WDT", "0_wdt", 50_000, tax_id="DE123456789", name="Test GmbH"),
    )
    march = [
        _row("K1/03", "np_ue", -100_000, tax_id="FI28583949", corrected_month=PERIOD),
        # Korekta faktury z marca — nie dotyczy lutego.
        _row("K2/03", "np_ue", -5_000, tax_id="FI28583949", corrected_month="2026-03"),
    ]
    april = [
        _row("K1/04", "np_ue", -50_049, tax_id="FI28583949", corrected_month=PERIOD),
        _row("K2/04", "0_wdt", 12_300, tax_id="DE123456789", corrected_month=PERIOD),
        _row("FS 3/04", "np_ue", 99_000, tax_id="FI28583949"),
    ]
    positions, problems = vat_uek.combine(base, march, april, period=PERIOD)
    assert problems == []
    # FI: 10 000 − 1 000 (marzec) = 9 000 było; − 500,49 = 8 499,51 → 8 500 jest.
    assert _amounts(positions) == {
        "DE123456789": (500, 623),
        "FI28583949": (9_000, 8_500),
    }
    assert [item.section for item in positions] == ["goods", "services"]
    assert positions[1].documents == ["K1/04"]
    assert positions[1].name == "Nordic Testbank"


def test_new_and_removed_counterparty_and_unchanged_rounding():
    base = _base(
        _row("1/02/UE", "np_ue", 200_000, tax_id="FI28583949"),
        _row("2/02/UE", "np_ue", 100_020, tax_id="EL123456789", name="Hellenic Test"),
    )
    april = [
        # Faktura z lutego w całości anulowana — kontrahent znika z informacji.
        _row("K1/04", "np_ue", -200_000, tax_id="FI28583949", corrected_month=PERIOD),
        # Korekta faktury z lutego dla nabywcy, którego w VAT-UE nie było.
        _row("K2/04", "np_ue", 70_000, tax_id="ATU12345678", name="Test AT"),
        # 20 gr mniej — w pełnych złotych bez zmiany, VAT-UEK nie potrzebna.
        _row("K3/04", "np_ue", -20, tax_id="EL123456789", corrected_month=PERIOD),
    ]
    april[1]["correction"], april[1]["corrected_month"] = True, PERIOD
    positions, problems = vat_uek.combine(base, [], april, period=PERIOD)
    assert problems == []
    assert _amounts(positions) == {"ATU12345678": (0, 700), "FI28583949": (2_000, 0)}

    content = vat_uek.build(positions, company=COMPANY, year=2026, month=2)
    assert vat_uek.validate(content) == []
    tree = etree.fromstring(content)
    groups = tree.findall(".//k:Grupa3", NS)
    assert [[child.tag.split("}")[1] for child in group] for group in groups] == [
        ["P_UJa", "P_UJb", "P_UJc"],
        ["P_UBa", "P_UBb", "P_UBc"],
    ]
    code = tree.find(".//k:KodFormularza", NS)
    assert code.text == "VAT-UEK"
    assert code.get("kodSystemowy") == "VATUEK (5)"
    assert code.get("wersjaSchemy") == "2-1E"
    assert tree.findtext(".//k:Rok", namespaces=NS) == "2026"
    assert tree.findtext(".//k:Miesiac", namespaces=NS) == "2"


def test_goods_carry_the_triangular_flag_on_both_sides():
    base = _base(_row("1/02/WDT", "0_wdt", 500_000, tax_id="DE123456789"))
    april = [
        _row("K1/04", "0_wdt", -100_000, tax_id="DE123456789", corrected_month=PERIOD)
    ]
    positions, _ = vat_uek.combine(base, [], april, period=PERIOD)
    content = vat_uek.build(positions, company=COMPANY, year=2026, month=2)
    assert vat_uek.validate(content) == []
    group = etree.fromstring(content).find(".//k:Grupa1", NS)
    assert [(child.tag.split("}")[1], child.text) for child in group] == [
        ("P_DBa", "DE"),
        ("P_DBb", "123456789"),
        ("P_DBc", "5000"),
        ("P_DBd", "1"),
        ("P_DJa", "DE"),
        ("P_DJb", "123456789"),
        ("P_DJc", "4000"),
        ("P_DJd", "1"),
    ]


def test_buyer_without_eu_number_and_negative_period_are_problems():
    base = _base(_row("1/02/UE", "np_ue", 100_000, tax_id="FI28583949"))
    april = [
        _row("K1/04", "np_ue", -150_000, tax_id="FI28583949", corrected_month=PERIOD),
        _row("K2/04", "np_ue", -1_000, tax_id=None, corrected_month=PERIOD),
        _row("K3/04", "np_ue", -1_000, tax_id="GB123456789", corrected_month=PERIOD),
    ]
    positions, problems = vat_uek.combine(base, [], april, period=PERIOD)
    assert positions == []
    kinds = {item["number"]: item["kind"] for item in problems}
    assert kinds == {
        "K2/04": "counterparty",
        "K3/04": "counterparty",
        "K1/04": "negative",
    }


def test_schema_catches_a_broken_file_and_years_past_the_schema():
    base = _base(_row("1/02/UE", "np_ue", 100_000, tax_id="FI28583949"))
    april = [
        _row("K1/04", "np_ue", -10_000, tax_id="FI28583949", corrected_month=PERIOD)
    ]
    positions, _ = vat_uek.combine(base, [], april, period=PERIOD)
    content = vat_uek.build(positions, company=COMPANY, year=2026, month=2)
    broken = content.replace(b"<P_UBa>FI</P_UBa>", b"<P_UBa>PL</P_UBa>")
    assert any("P_UBa" in error for error in vat_uek.validate(broken))
    # etd:TRok w strukturach v6 kończy się na 2030 (testy na bazie losują lata
    # 2050–2090 i sprawdzają pozycje, nie schemat).
    late = vat_uek.build(positions, company=COMPANY, year=2031, month=2)
    assert vat_uek.validate(late)
