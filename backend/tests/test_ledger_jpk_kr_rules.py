"""JPK_KR_PD(1) i JPK_ST_KR(1) z księgi NEXUSA (K8c) — reguły bez bazy.

Fikcyjne dane (repo jest publiczne): spółka testowa, kontrahenci i kwoty
wymyślone. Plik sprawdzany schematem MF z ``jpk_kr_schema/``.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal

import pytest
from lxml import etree

from app.services.finance_ledger.costs import LedgerError
from app.services.hr.payroll_lists.parameters import Company
from app.services.ledger import jpk_kr, jpk_kr_compare, jpk_st_kr, markers
from app.services.ledger.depreciation import Opening, PlanInput
from app.services.ledger.settings import (
    JpkKrSettings,
    clean_jpk_kr,
    normalize,
    to_json,
)

NOW = datetime(2026, 11, 16, 12, 0, tzinfo=timezone.utc)
YEAR = 2026
COMPANY = Company(
    nip="5260250995",
    name="Spółka Testowa S.A.",
    short_name="TEST",
    regon="012345678",
    tax_office_code="1471",
    zus_account=None,
    tax_account=None,
)
ADDRESS = {
    "province": "mazowieckie",
    "county": "Testowo",
    "commune": "Testowo",
    "street": "Przykładowa",
    "building": "1",
    "city": "Testowo",
    "postal_code": "00-001",
}
SETTINGS = JpkKrSettings(address=ADDRESS, estonian=True, estonian_since=2025)
OWN = {
    "130-1": "BABIII1c1_SPKR",
    "200-1": "BABII3a_D12/BPBIII3d_D12",
    "202-1": "BABII3a_D12/BPBIII3d_D12",
    "221": "BABII3c_W",
    "222": "BPBIII3h",
    "231": "BPBIII3i",
    "404": "RPBV",
    "550": "RKE",
}
NAMES = {
    "130-1": "Rachunek bieżący",
    "200-1": "Odbiorcy krajowi",
    "202-1": "Dostawcy",
    "402": "Usługi obce",
    "404": "Wynagrodzenia",
}
KSEF_NUMBER = "5260250995-20260110-0123AB-45CD67-89"
NS = {"j": jpk_kr.NS, "etd": jpk_kr.ETD}
L = jpk_kr.Line


def _doc(no: int, doc_type: str, number: str, day: int, *lines, **extra):
    when = date(YEAR, 1, day)
    return jpk_kr.Doc(
        journal_no=no,
        doc_type=doc_type,
        number=number,
        op_date=when,
        doc_date=when,
        booked_on=when,
        author="Księgowa Testowa",
        description=f"{doc_type} testowy",
        lines=tuple(lines),
        **extra,
    )


def _docs() -> list[jpk_kr.Doc]:
    return [
        _doc(
            1,
            "BO",
            "BO 1/01",
            1,
            L("debit", "130-1", 100_000),
            L("credit", "801", 100_000),
        ),
        _doc(
            2,
            "FVS",
            "FV/1/2026",
            10,
            L("debit", "200-1-7", 12_300),
            L("credit", "700", 10_000),
            L("credit", "222", 2_300),
            counterparty_id=7,
            ksef_number=KSEF_NUMBER,
        ),
        _doc(
            3,
            "FVZ",
            "Z/9",
            12,
            L("debit", "402", 4_300, "Usługa obca"),
            L("debit", "221", 989),
            L("credit", "202-1-3", 5_289, currency="EUR", amount_cur=1_234),
            counterparty_id=3,
        ),
        # Storno czerwone części FVZ — kwoty z minusem.
        _doc(
            4,
            "ST",
            "ST 1/01",
            20,
            L("debit", "402", -100),
            L("credit", "202-1-3", -100),
        ),
        # Lista płac z osobą jako kontrahentem: pracownik nie trafia do pliku.
        _doc(
            5,
            "LP",
            "LP 1/01",
            31,
            L("debit", "404", 8_000),
            L("credit", "231", 8_000),
            counterparty_id=9,
        ),
        _doc(6, "PK", "PK 1/01", 31, L("debit", "550", 500), L("credit", "490", 500)),
    ]


PARTIES = {
    7: jpk_kr.Party(7, "nip", "PL5260250995", "PL"),
    3: jpk_kr.Party(3, "vat_eu", "EL123456789", "GR"),
    9: jpk_kr.Party(9, "nip", "1234563218", "PL"),
}


def _rows(docs=None, own=OWN):
    return jpk_kr.zois(jpk_kr.sums_from_docs(docs or _docs()), own, NAMES)


def _file(docs=None, *, settings=SETTINGS, correction=False):
    docs = docs or _docs()
    return jpk_kr.build(
        year_from=date(YEAR, 1, 1),
        year_to=date(YEAR, 12, 31),
        docs=docs,
        rows=_rows(docs),
        parties=PARTIES,
        company=COMPANY,
        settings=settings,
        correction=correction,
        now=NOW,
    )


def _xml(content: bytes):
    return etree.fromstring(content)


# ── Plik i schemat MF ────────────────────────────────────────────────────────


def test_year_file_passes_the_mf_schema() -> None:
    content, totals = _file()
    assert jpk_kr.validate(content) == []
    assert totals.documents == 6
    assert totals.lines == 14
    assert totals.debit == totals.credit


def test_header_subject_and_estonian_marker() -> None:
    root = _xml(_file()[0])
    code = root.find("j:Naglowek/j:KodFormularza", NS)
    assert code.get("kodSystemowy") == "JPK_KR_PD (1)"
    assert code.get("wersjaSchemy") == "1-1"
    assert root.findtext("j:Naglowek/j:CelZlozenia", namespaces=NS) == "1"
    assert root.findtext("j:Naglowek/j:DataOd", namespaces=NS) == "2026-01-01"
    assert root.findtext("j:Naglowek/j:RokPdDataDo", namespaces=NS) == "2026-12-31"
    assert root.findtext("j:Podmiot1/j:Znacznik_EST", namespaces=NS) == "1"
    assert (
        root.findtext("j:Podmiot1/j:Adres/j:AdresPol/etd:KodPocztowy", namespaces=NS)
        == "00-001"
    )
    # CIT estoński: RPD z zerami (MF, pytanie 114).
    assert [node.text for node in root.find("j:RPD", NS)] == ["0.00"] * 8


def test_correction_is_the_whole_file_with_purpose_two() -> None:
    content, _ = _file(correction=True)
    assert _xml(content).findtext("j:Naglowek/j:CelZlozenia", namespaces=NS) == "2"
    assert jpk_kr.validate(content) == []


def test_journal_lines_parties_and_control_sums() -> None:
    root = _xml(_file()[0])
    journal = root.findall("j:Dziennik", NS)
    assert [node.findtext("j:D_1", namespaces=NS) for node in journal] == [
        "1",
        "2",
        "3",
        "4",
        "5",
        "6",
    ]
    assert {node.findtext("j:D_2", namespaces=NS) for node in journal} == {
        "Dziennik Księga Główna"
    }
    sale, purchase, storno, payroll = journal[1], journal[2], journal[3], journal[4]
    assert sale.findtext("j:D_3", namespaces=NS) == "7"
    assert sale.findtext("j:D_12", namespaces=NS) == KSEF_NUMBER
    assert sale.findtext("j:D_11", namespaces=NS) == "123.00"
    # Pozycja walutowa: kwota w walucie i kod po stronie Ma.
    foreign = purchase.findall("j:KontoZapis", NS)[2]
    assert foreign.findtext("j:Z_7", namespaces=NS) == "52.89"
    assert foreign.findtext("j:Z_8", namespaces=NS) == "12.34"
    assert foreign.findtext("j:Z_9", namespaces=NS) == "EUR"
    assert storno.findtext("j:D_11", namespaces=NS) == "-1.00"
    # Lista płac: pracownik nie jest kontrahentem (MF, pytanie 123).
    assert payroll.find("j:D_3", NS) is None
    numbers = [
        node.findtext("j:Z_1", namespaces=NS)
        for node in root.iter(f"{{{jpk_kr.NS}}}KontoZapis")
    ]
    assert numbers == [str(index) for index in range(1, 15)]
    parties = {
        node.findtext("j:T_1", namespaces=NS): (
            node.findtext("j:T_2", namespaces=NS),
            node.findtext("j:T_3", namespaces=NS),
        )
        for node in root.findall("j:Kontrahent", NS)
    }
    # NIP z PL, VAT UE pełny z prefiksem, kraj ISO (EL → GR); bez pracownika.
    assert parties == {"3": ("GR", "EL123456789"), "7": ("PL", "5260250995")}
    ctrl = root.find("j:Ctrl", NS)
    assert ctrl.findtext("j:C_1", namespaces=NS) == "6"
    assert ctrl.findtext("j:C_3", namespaces=NS) == "14"
    assert ctrl.findtext("j:C_4", namespaces=NS) == ctrl.findtext(
        "j:C_5", namespaces=NS
    )


def test_empty_description_falls_back_to_type_and_number() -> None:
    docs = _docs()
    docs[5] = jpk_kr.Doc(**{**docs[5].__dict__, "description": "", "author": ""})
    content, _ = _file(docs)
    assert jpk_kr.validate(content) == []
    last = _xml(content).findall("j:Dziennik", NS)[5]
    assert last.findtext("j:D_10", namespaces=NS) == "Polecenie księgowania PK 1/01"
    assert last.findtext("j:D_9", namespaces=NS) == "NEXUS"


def test_schema_refuses_a_broken_file() -> None:
    root = _xml(_file()[0])
    first = root.find("j:ZOiS/j:ZOiS7", NS)
    first.find("j:S_12_1", NS).text = "NIE-MA-TAKIEGO"
    errors = jpk_kr.validate(etree.tostring(root))
    assert errors and "S_12_1" in errors[0]


# ── ZOiS i znaczniki ─────────────────────────────────────────────────────────


def test_zois_lists_accounts_and_every_parent_with_sums() -> None:
    rows = {row.account: row for row in _rows()}
    assert {"200", "200-1", "200-1-7", "202", "202-1", "202-1-3"} <= set(rows)
    assert rows["200-1-7"].parent == "200-1"
    assert rows["200-1"].parent == "200"
    assert rows["200"].parent == "200"
    assert rows["130"].bo_debit == rows["130-1"].bo_debit == 100_000
    assert rows["202-1-3"].credit == 5_189
    assert rows["202-1-3"].balance_credit == 5_189
    assert rows["202"].balance_credit == 5_189
    assert rows["200-1-7"].name == "Odbiorcy krajowi · 7"
    assert rows["402"].debit == 4_200


def test_parent_keeps_common_marker_or_gets_other() -> None:
    docs = _docs() + [
        _doc(
            7,
            "PK",
            "PK 2/01",
            31,
            L("debit", "202-2-1", 50),
            L("credit", "202-1-3", 50),
        )
    ]
    rows = {row.account: row for row in _rows(docs, {**OWN, "202-2": "BPBIII3i"})}
    assert rows["202-1"].pair.text == "BABII3a_D12/BPBIII3d_D12"
    # 202-1 i 202-2 mają różne znaczniki → konto syntetyczne „INNE” (pyt. 147).
    assert rows["202"].pair.text == "INNE"


def test_pair_goes_to_s12_1_and_s12_2() -> None:
    root = _xml(_file()[0])
    zois = {
        node.findtext("j:S_1", namespaces=NS): node
        for node in root.findall("j:ZOiS/j:ZOiS7", NS)
    }
    pair = zois["202-1-3"]
    assert pair.findtext("j:S_12_1", namespaces=NS) == "BABII3a_D12"
    assert pair.findtext("j:S_12_2", namespaces=NS) == "BPBIII3d_D12"
    single = zois["402"]
    assert single.findtext("j:S_12_1", namespaces=NS) == "RPBIII"
    assert single.find("j:S_12_2", NS) is None
    # Bez znaczników PD (CIT estoński).
    assert root.find(".//j:S_12_3", NS) is None


@pytest.mark.parametrize(
    ("account", "own", "expected", "source"),
    [
        ("490", {}, "INNE", markers.SOURCE_RULE),
        ("901-1", {}, "INNE", markers.SOURCE_RULE),
        ("550", {}, None, markers.SOURCE_NONE),
        ("550-1", {"550": "RKE"}, "RKE", markers.SOURCE_PARENT),
        ("402", {}, "RPBIII", markers.SOURCE_RULE),
        ("402", {"402": "RPBVII"}, "RPBVII", markers.SOURCE_OWN),
        ("401", {}, None, markers.SOURCE_NONE),
    ],
)
def test_account_marker_covers_both_rzis_variants(account, own, expected, source):
    pair, found = jpk_kr.account_marker(account, own)
    assert (pair.text if pair else None) == expected
    assert found == source


# ── Kontrahenci ──────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("party", "expected"),
    [
        (jpk_kr.Party(1, "nip", "526-025-09-95", None), ("PL", "5260250995")),
        (jpk_kr.Party(1, "vat_eu", "DE123456789", "DE"), ("DE", "DE123456789")),
        (jpk_kr.Party(1, "vat_eu", "XI123456789", None), ("GB", "XI123456789")),
        (jpk_kr.Party(1, "other", "12-3456789", "US"), ("US", "123456789")),
        (jpk_kr.Party(1, "other", "999", "ZZ"), (None, "999")),
        (jpk_kr.Party(1, "pesel", "44051401458", "PL"), None),
        (jpk_kr.Party(1, None, None, None), None),
    ],
)
def test_party_tax_id(party, expected) -> None:
    assert jpk_kr.party_tax_id(party) == expected


# ── Braki blokujące ──────────────────────────────────────────────────────────


def test_complete_year_has_no_problems() -> None:
    assert (
        jpk_kr.problems(
            year=YEAR,
            open_months=[],
            rows=_rows(),
            company=COMPANY,
            settings=SETTINGS,
            documents=6,
        )
        == []
    )


def test_problems_block_the_file() -> None:
    docs = _docs() + [
        _doc(7, "PK", "PK 3/01", 31, L("debit", "401", 10), L("credit", "405-5", 10))
    ]
    found = jpk_kr.problems(
        year=YEAR,
        open_months=[11, 12],
        rows=_rows(docs),
        company=Company(**{**COMPANY.__dict__, "tax_office_code": None}),
        settings=JpkKrSettings(address={"city": "Testowo"}, estonian=False),
        documents=7,
        payroll_accounts=frozenset({"405-5"}),
        viewer_payroll=False,
    )
    by_code = {item.code: item for item in found}
    assert by_code["periods"].items == ("11/2026", "12/2026")
    # Analityka z dokumentów płacowych schodzi bez Płac do konta syntetycznego.
    assert by_code["markers"].items == ("401", "405")
    assert "estonian" in by_code
    assert any("kod urzędu" in item for item in by_code["company"].items)
    assert any("województwo" in item for item in by_code["company"].items)


def test_estonian_without_first_year_and_late_years_are_problems() -> None:
    found = jpk_kr.problems(
        year=2051,
        open_months=[],
        rows=_rows(),
        company=COMPANY,
        settings=JpkKrSettings(address=ADDRESS, estonian=True),
        documents=0,
    )
    codes = {item.code for item in found}
    assert {"year", "empty", "company"} <= codes
    company = next(item for item in found if item.code == "company")
    assert "pierwszy rok CIT estońskiego" in company.items[0]


# ── Ustawienia ───────────────────────────────────────────────────────────────


def test_settings_round_trip_and_refusals() -> None:
    cleaned = clean_jpk_kr(
        {
            "address": {**ADDRESS, "street": "  Długa   ulica "},
            "estonian": True,
            "estonian_since": "2025",
        }
    )
    assert cleaned.address["street"] == "Długa ulica"
    assert cleaned.estonian_since == 2025
    stored = to_json(normalize({"jpk_kr": to_json_jpk(cleaned)}))["jpk_kr"]
    assert stored == {
        "address": cleaned.address,
        "estonian": True,
        "estonian_since": 2025,
    }
    for bad in (
        {"address": {"postal_code": "00001"}},
        {"address": {"building": "1" * 10}},
        {"estonian": True, "estonian_since": 2019},
        {"estonian": True, "estonian_since": "dwa tysiące"},
    ):
        with pytest.raises(LedgerError) as error:
            clean_jpk_kr(bad)
        assert error.value.status == 422
    # Bez ryczałtu rok ryczałtu się nie zapisuje.
    assert (
        clean_jpk_kr({"estonian": False, "estonian_since": 2025}).estonian_since is None
    )


def to_json_jpk(settings: JpkKrSettings) -> dict:
    return {
        "address": settings.address,
        "estonian": settings.estonian,
        "estonian_since": settings.estonian_since,
    }


def test_settings_ignore_garbage_from_the_database() -> None:
    loaded = normalize(
        {
            "jpk_kr": {
                "address": {"city": 5, "province": "  mazowieckie "},
                "estonian": "tak",
                "estonian_since": True,
            }
        }
    ).jpk_kr
    assert loaded.address == {"province": "mazowieckie"}
    assert loaded.estonian is False
    assert loaded.estonian_since is None


# ── Porównanie z Symfonią ────────────────────────────────────────────────────


def _prepared(docs=None):
    docs = docs or _docs()
    return jpk_kr.Prepared(
        year=None,
        docs=docs,
        rows=_rows(docs),
        parties=PARTIES,
        company=COMPANY,
        problems=[],
    )


def test_same_books_compare_without_differences() -> None:
    content, _ = _file()
    result = jpk_kr_compare.compare(
        jpk_kr_compare.ours(_prepared()), jpk_kr_compare.parse(content)
    )
    assert result["same"] is True
    assert result["differences"] == 0


def test_compare_shows_amounts_markers_and_one_sided_accounts() -> None:
    root = _xml(_file()[0])
    zois = root.find("j:ZOiS", NS)
    for node in zois.findall("j:ZOiS7", NS):
        account = node.findtext("j:S_1", namespaces=NS)
        if account == "402":
            node.find("j:S_6", NS).text = "50.00"
        if account == "222":
            node.find("j:S_12_1", NS).text = "BPBIII3i"
        if account == "700":
            zois.remove(node)
    root.find("j:Ctrl/j:C_1", NS).text = "5"
    result = jpk_kr_compare.compare(
        jpk_kr_compare.ours(_prepared()), jpk_kr_compare.parse(etree.tostring(root))
    )
    assert result["same"] is False
    assert result["amounts"] == [
        {"account": "402", "fields": {"S_6": {"nexus": 4_200, "symfonia": 5_000}}}
    ]
    assert result["markers"] == [
        {"account": "222", "nexus": ["BPBIII3h"], "symfonia": ["BPBIII3i"]}
    ]
    assert result["only_nexus"] == ["700"]
    assert result["ctrl"] == {"C_1": {"nexus": 6, "symfonia": 5}}


@pytest.mark.parametrize(
    "content",
    [
        b"to nie xml",
        b"<Inny/>",
        b'<?xml version="1.0"?><!DOCTYPE JPK [<!ENTITY x SYSTEM "file:///etc/passwd">]>'
        b"<JPK><Naglowek><DataOd>&x;</DataOd></Naglowek></JPK>",
    ],
)
def test_compare_refuses_bad_files(content) -> None:
    with pytest.raises(LedgerError) as error:
        jpk_kr_compare.parse(content)
    assert error.value.status == 422


# ── JPK_ST_KR ────────────────────────────────────────────────────────────────


def _asset(**extra) -> jpk_st_kr.Asset:
    accepted = extra.pop("accepted_on", date(2024, 3, 15))
    balance = extra.pop(
        "balance",
        PlanInput(
            method="linear", rate=Decimal("20"), initial=1_200_000, accepted=accepted
        ),
    )
    tax = extra.pop(
        "tax",
        PlanInput(
            method="linear", rate=Decimal("20"), initial=1_200_000, accepted=accepted
        ),
    )
    values = {
        "id": 1,
        "inventory": "ST/2024/001",
        "name": "Serwer testowy",
        "kind": "fixed",
        "kst": "491",
        "accepted_on": accepted,
        "balance": balance,
        "tax": tax,
        "balance_rate": Decimal("20"),
        "tax_rate": Decimal("30"),
        "status": "in_use",
        "disposed_on": None,
        "ot_number": "OT 1/2024",
        "from_invoice": True,
    }
    values.update(extra)
    return jpk_st_kr.Asset(**values)


def test_asset_before_estonian_cit_keeps_tax_values_at_its_start() -> None:
    item = jpk_st_kr.entry(_asset(), year=YEAR, estonian_since=2025)
    # Plan bilansowy: 1 200 000 gr × 20% / 12 = 20 000 gr miesięcznie od 04.2024.
    assert item.balance_start == 1_200_000
    assert item.balance_year == 240_000
    assert item.balance_accumulated == 9 * 20_000 + 240_000 + 240_000
    # Podatkowo: wartość i umorzenie na koniec 2024 (rok przed ryczałtem).
    assert item.tax_value == 1_200_000
    assert item.tax_accumulated == 9 * 20_000


def test_asset_accepted_under_estonian_cit_has_zero_tax_values() -> None:
    item = jpk_st_kr.entry(
        _asset(
            accepted_on=date(2026, 2, 3),
            balance=PlanInput("one_off", Decimal("100"), 500_000, date(2026, 2, 3)),
            tax=PlanInput("one_off", Decimal("100"), 500_000, date(2026, 2, 3)),
        ),
        year=YEAR,
        estonian_since=2025,
    )
    assert (item.tax_value, item.tax_accumulated) == (0, 0)
    assert item.balance_one_off == 500_000
    assert item.balance_accumulated == 500_000


def test_symfonia_opening_after_estonian_start_is_the_tax_state() -> None:
    accepted = date(2020, 6, 1)
    opening = Opening(month=date(2026, 9, 1), accumulated=700_000)
    item = jpk_st_kr.entry(
        _asset(
            accepted_on=accepted,
            ot_number=None,
            tax=PlanInput(
                "linear", Decimal("20"), 1_200_000, accepted, opening=opening
            ),
            balance=PlanInput(
                "linear", Decimal("20"), 1_200_000, accepted, opening=opening
            ),
        ),
        year=YEAR,
        estonian_since=2025,
    )
    assert item.tax_accumulated == 700_000
    assert item.balance_accumulated == 700_000 + 3 * 20_000


def test_st_kr_file_passes_the_mf_schema_with_disposal() -> None:
    sold = _asset(
        id=2,
        inventory="ST/2024/002",
        status="sold",
        disposed_on=date(2026, 5, 20),
        disposal_number="SP 1/2026",
        balance=PlanInput(
            "linear",
            Decimal("20"),
            1_200_000,
            date(2024, 3, 15),
            disposed=date(2026, 5, 20),
        ),
    )
    intangible = _asset(
        id=3, inventory="WNiP/2025/001", kind="intangible", kst=None, ot_number=None
    )
    entries = [
        jpk_st_kr.entry(asset, year=YEAR, estonian_since=2025)
        for asset in (_asset(), sold, intangible)
    ]
    content = jpk_st_kr.build(
        year=YEAR,
        entries=entries,
        company=COMPANY,
        settings=SETTINGS,
        correction=False,
        now=NOW,
    )
    assert jpk_kr.validate(content, jpk_st_kr.SCHEMA) == []
    root = etree.fromstring(content)
    ns = {"s": jpk_st_kr.NS}
    rows = root.findall("s:ST_KR", ns)
    assert rows[0].findtext("s:E_9_1", namespaces=ns) == "X"
    assert rows[0].findtext("s:E_11", namespaces=ns) == "0.00"
    assert rows[0].findtext("s:E_17", namespaces=ns) == "X"
    assert rows[1].findtext("s:E_29", namespaces=ns) == "S"
    assert rows[1].findtext("s:E_30", namespaces=ns) == "SP 1/2026"
    assert rows[1].findtext("s:E_27", namespaces=ns) == f"{(9 + 12 + 5) * 200}.00"
    assert rows[2].find("s:E_3", ns) is not None
    assert rows[2].find("s:E_8", ns) is None
    assert rows[2].findtext("s:E_5", namespaces=ns) == jpk_st_kr.FROM_SYMFONIA


def test_register_holds_assets_present_in_the_year() -> None:
    assert jpk_st_kr.in_register(_asset(), YEAR)
    assert not jpk_st_kr.in_register(_asset(accepted_on=date(2027, 1, 1)), YEAR)
    assert not jpk_st_kr.in_register(_asset(disposed_on=date(2025, 12, 31)), YEAR)
    assert jpk_st_kr.in_register(_asset(disposed_on=date(2026, 1, 1)), YEAR)


def test_st_kr_problems() -> None:
    entries = [jpk_st_kr.entry(_asset(kst=None), year=YEAR, estonian_since=2025)]
    found = jpk_st_kr.problems(
        year=YEAR,
        entries=entries,
        company=COMPANY,
        settings=JpkKrSettings(address=ADDRESS),
    )
    assert {item.code for item in found} == {"kst", "estonian"}
    empty = jpk_st_kr.problems(
        year=YEAR, entries=[], company=COMPANY, settings=SETTINGS
    )
    assert [item.code for item in empty] == ["empty"]


def test_year_before_estonian_cit_does_not_build_an_estonian_file() -> None:
    """Przegląd K8c: rok sprzed pierwszego roku ryczałtu szedł z ``Znacznik_EST``
    i RPD z zerami — deklaracja dla roku na zasadach ogólnych byłaby błędna."""

    found = jpk_kr.problems(
        year=2024,
        open_months=[],
        rows=_rows(),
        company=COMPANY,
        settings=SETTINGS,
        documents=6,
    )
    assert [item.code for item in found] == ["estonian"]
    entries = [jpk_st_kr.entry(_asset(), year=2024, estonian_since=2025)]
    st_found = jpk_st_kr.problems(
        year=2024, entries=entries, company=COMPANY, settings=SETTINGS
    )
    assert [item.code for item in st_found] == ["estonian"]
