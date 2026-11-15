"""Porównanie JPK z Symfonią (K5b-3b) — reguły bez bazy. „Plik z Symfonii”
to JPK zbudowany przez NEXUS z tych samych rejestrów, potem psuty. Firma,
kontrahenci i numery fikcyjne."""

from __future__ import annotations

import pytest

from app.services.finance_ledger.costs import LedgerError
from app.services.ledger import jpk, jpk_compare
from tests.test_ledger_jpk_rules import COMPANY, NOW, _data


def _file(data: dict, surplus: int = 0) -> bytes:
    content, _ = jpk.build(
        data,
        company=COMPANY,
        email="ksiegowosc@example.com",
        phone="",
        purpose="submission",
        reason=None,
        surplus=surplus,
        now=NOW,
    )
    return content


def test_same_registers_give_no_differences():
    data = _data()
    data["sales"][0]["markers"] = ["GTU_12"]
    result = jpk_compare.compare(data, jpk_compare.parse(_file(data, surplus=7)))
    assert result["differences"] == 0
    sales, purchases = result["rows"]
    assert (sales["matched"], sales["symfonia_rows"], purchases["matched"]) == (3, 3, 2)
    assert {item["field"]: item["nexus"] for item in result["declaration"]}["P_39"] == 7


def test_amount_missing_row_marker_and_declaration_differences():
    data = _data()
    content = _file(data)
    # Symfonia: inna kwota VAT jednej faktury, brak faktury zakupu, GTU_12 na FS 1/03.
    content = content.replace(b"<K_20>230.00</K_20>", b"<K_20>231.00</K_20>", 1)
    symfonia = jpk_compare.parse(content)
    symfonia["purchases"].pop(next(iter(symfonia["purchases"])))
    first_sale = next(iter(symfonia["sales"].values()))
    first_sale["markers"].add("GTU_12")
    result = jpk_compare.compare(data, symfonia)
    sales, purchases = result["rows"]
    assert [(item["number"], item["fields"]) for item in sales["different"]] == [
        ("FS 1/03", {"K_20": {"nexus": 23_000, "symfonia": 23_100}})
    ]
    assert sales["different"][0]["markers"] == {"nexus": [], "symfonia": ["GTU_12"]}
    assert purchases["only_nexus_count"] == 1 and purchases["only_symfonia_count"] == 0
    # Deklaracja w pliku nie ruszona — różnica tylko w wierszach (2).
    assert result["differences"] == 2
    symfonia["declaration"]["P_38"] = 208
    p_38 = next(item for item in jpk_compare.compare(data, symfonia)["declaration"] if item["field"] == "P_38")
    assert (p_38["nexus"], p_38["symfonia"]) == (207, 208)


def test_numbers_match_without_spaces_case_and_country_code():
    assert jpk_compare.doc_key("fs 1/03 ", "PL 111-111-11-11") == jpk_compare.doc_key("FS1/03", "PL1111111111")


def test_wrong_files_are_refused():
    for content, message in (
        (b"not xml", "nie jest plik XML"),
        (b"<?xml version='1.0'?><Faktura/>", "brak elementu JPK"),
        (b'<?xml version="1.0"?><!DOCTYPE JPK [<!ENTITY x SYSTEM "file:///etc/passwd">]><JPK>&x;</JPK>', ""),
    ):
        with pytest.raises(LedgerError) as caught:
            jpk_compare.parse(content)
        assert caught.value.status == 422 and message in caught.value.message


def test_symfonia_numbers_with_country_prefix_and_brak_match_nexus_rows():
    """Przegląd K5b-3b: Symfonia pisze numer VAT UE z prefiksem (DE…, PL…) —
    klucz po obu stronach bez kodu kraju; „BRAK” zostaje „BRAK”."""

    data = _data()
    data["sales"].append(dict(data["sales"][0], document_id=901, number="FS 9/03", tax_id=None, country=None, ksef_number=None))
    content = _file(data)
    content = content.replace(b"<NrKontrahenta>28583949</NrKontrahenta>", b"<NrKontrahenta>FI28583949</NrKontrahenta>")
    content = content.replace(b"<NrKontrahenta>1111111111</NrKontrahenta>", b"<NrKontrahenta>PL1111111111</NrKontrahenta>")
    result = jpk_compare.compare(data, jpk_compare.parse(content))
    sales = result["rows"][0]
    assert (sales["only_nexus_count"], sales["only_symfonia_count"], sales["matched"]) == (0, 0, 4)
    assert result["differences"] == 0
