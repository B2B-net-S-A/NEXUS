"""Kontrahenci „czekają na Symfonię” (E0b) — reguły bez bazy.

Plik roboczy CSV (kolejność kolumn, BOM, średniki, formuły z KSeF), kontrola
numeru, prefiksy kont wg kraju, scalanie źródeł i ta sama kartka odesłana
z ID Symfonii przez import E0. Firmy i numery fikcyjne.
"""

from __future__ import annotations

import csv
import io

from app.models.finance_ledger import FinanceCounterparty
from app.services.finance_ledger import counterparty_import as importer
from app.services.finance_ledger import symfonia_partners as sp
from app.services.finance_ledger.counterparties import _derive_accounts


def _nip(seed: int) -> str:
    weights = (6, 5, 7, 2, 3, 4, 5, 6, 7)
    for offset in range(1000):
        base = f"{(seed + offset) % 10**9:09d}"
        check = sum(int(d) * w for d, w in zip(base, weights)) % 11
        if check != 10:
            return base + str(check)
    raise AssertionError("brak NIP-u")


def _rows(content: bytes) -> list[list[str]]:
    text = content.decode("utf-8-sig")
    return list(csv.reader(io.StringIO(text), delimiter=";"))


def test_konta_z_id_i_kraju_jak_w_ebi24() -> None:
    assert sp.derived_accounts("1441", "PL") == ("201-2-1441", "200-2-1441")
    assert sp.derived_accounts("77", "de") == ("203-2-77", "202-2-77")
    # ID nie będące liczbą albo brak kraju: nie zgadujemy konta.
    assert sp.derived_accounts("A12", "PL") is None
    assert sp.derived_accounts("", "PL") is None
    assert sp.derived_accounts("15", None) is None
    assert sp.account_prefixes(None) == ("200-2", "201-2")
    assert sp.account_prefixes("US") == ("202-2", "203-2")


def test_numer_z_suma_kontrolna_i_kraj_z_numeru() -> None:
    good = sp._candidate("koszty", f"PL {_nip(500)}", "Dostawca Testowy", id_type="nip")
    assert good.ready and (good.id_type, good.country) == ("nip", "PL")
    bad = sp._candidate("koszty", "1234567890", "Dostawca Testowy", id_type="nip")
    assert not bad.ready and "sumę kontrolną" in bad.problems[0]
    eu = sp._candidate("sprzedaz", "DE123456789", "Kunde GmbH")
    assert (eu.id_type, eu.country, eu.ready) == ("vat_eu", "DE", True)
    nameless = sp._candidate("koszty", _nip(501), "  ", id_type="nip")
    assert nameless.problems == ["brak nazwy"]
    other = sp._candidate(
        "kartoteka", "ABC-1", "Firma Spoza UE", id_type="other", validate=False
    )
    assert other.problems == ["brak kraju"]


def test_scalanie_zrodel_adres_z_kartoteki_albo_sprzedazy() -> None:
    nip = _nip(777)
    costs_row = sp._candidate("koszty", nip, "Nazwa z kosztów", id_type="nip")
    sales_row = sp._candidate(
        "sprzedaz", nip, "Nazwa ze sprzedaży", id_type="nip", street="ul. Testowa 1"
    )
    merged = sp._merge([costs_row, sales_row])
    assert len(merged) == 1
    assert merged[0].name == "Nazwa ze sprzedaży"
    assert merged[0].street == "ul. Testowa 1"
    assert merged[0].sources == ["sprzedaz", "koszty"]


def test_lista_gotowi_przed_problemami_i_brak_adresu_to_ostrzezenie() -> None:
    bad = sp._candidate("koszty", "1234567890", "Aaa Zły numer", id_type="nip")
    ok = sp._candidate("koszty", _nip(900), "Zzz Dobry", id_type="nip")
    ordered = sp._merge([bad, ok])
    assert [item.name for item in ordered] == ["Zzz Dobry", "Aaa Zły numer"]
    assert ordered[0].warnings == ["brak adresu"]
    payload = sp.payload(ordered[0])
    assert (payload["receivable_prefix"], payload["payable_prefix"]) == (
        "200-2",
        "201-2",
    )
    assert payload["sources"] == ["faktura kosztowa"]


def test_csv_bom_srednik_tylko_gotowi_i_formula_nie_wykonuje_sie() -> None:
    domestic = sp._candidate(
        "sprzedaz",
        _nip(100),
        "Firma Krajowa Sp. z o.o.",
        id_type="nip",
        street="ul. Testowa 1",
        postal_code="00-001",
        city="Warszawa",
    )
    foreign = sp._candidate("koszty", "DE123456789", '=HYPERLINK("x")')
    broken = sp._candidate("koszty", "1234567890", "Zły", id_type="nip")
    content, count = sp.render_csv([domestic, foreign, broken])
    assert content.startswith(b"\xef\xbb\xbf") and count == 2
    rows = _rows(content)
    assert tuple(rows[0]) == sp.CSV_COLUMNS
    by_name = {row[0].strip(): row for row in rows[1:]}
    assert set(by_name) == {"Firma Krajowa Sp. z o.o.", '=HYPERLINK("x")'}
    # Spacja z przodu zatrzymuje formułę w Excelu; import ją zdejmuje.
    formula = next(row for row in rows[1:] if "HYPERLINK" in row[0])
    assert formula[0].startswith(" =")
    assert formula[2] == "VAT UE" and formula[3] == "DE"
    assert formula[8:10] == ["202-2", "203-2"]
    domestic_row = by_name["Firma Krajowa Sp. z o.o."]
    assert domestic_row[1:8] == [
        domestic.id_value,
        "NIP",
        "PL",
        "ul. Testowa 1",
        "00-001",
        "Warszawa",
        "",
    ]
    assert domestic_row[8:11] == ["200-2", "201-2", "faktura sprzedaży"]


def test_ta_sama_kartka_z_id_wraca_przez_import_e0() -> None:
    domestic = sp._candidate(
        "sprzedaz", _nip(300), "Firma Krajowa", id_type="nip", street="ul. Testowa 1"
    )
    pending = sp._candidate("koszty", _nip(400), "Firma Czekająca", id_type="nip")
    content, _ = sp.render_csv([domestic, pending])
    rows = _rows(content)
    rows[1][7] = "1441"  # księgowa wpisała ID tylko pierwszemu
    out = io.StringIO()
    csv.writer(out, delimiter=";").writerows(rows)
    parsed = importer.parse(out.getvalue().encode("utf-8-sig"))
    assert parsed.errors == []
    assert {c for c in parsed.columns.values()} >= {
        "name",
        "identifier",
        "id_type",
        "country",
        "street",
        "postal_code",
        "city",
        "symfonia_partner_id",
    }
    first, second = parsed.rows
    assert first.id_type == "nip" and first.values["symfonia_partner_id"] == "1441"
    assert first.values["country"] == "PL"
    assert second.values["symfonia_partner_id"] is None


def test_import_wylicza_konta_z_id_i_nie_nadpisuje_wpisanych() -> None:
    nip = _nip(600)
    content = (
        "Nazwa;NIP;Kraj;ID Symfonii;Konto kosztowe\r\n"
        f"Nowy Dostawca;{nip};PL;2001;\r\n"
        f"Ręczny Dostawca;{_nip(601)};PL;2002;402-999\r\n"
        f"Zagraniczny;DE123456789;DE;2003;\r\n"
    )
    rows = importer.parse(content.encode("utf-8")).rows
    for item in rows:
        _derive_accounts(item, None)
    assert (rows[0].values["cost_account"], rows[0].values["revenue_account"]) == (
        "201-2-2001",
        "200-2-2001",
    )
    # Konto wpisane w pliku zostaje, brakujące przychodowe dochodzi z ID.
    assert (rows[1].values["cost_account"], rows[1].values["revenue_account"]) == (
        "402-999",
        "200-2-2002",
    )
    assert (rows[2].values["cost_account"], rows[2].values["revenue_account"]) == (
        "203-2-2003",
        "202-2-2003",
    )


def test_istniejace_konto_w_kartotece_nie_jest_wyprowadzane_ponownie() -> None:
    nip = _nip(700)
    item = importer.parse(
        f"Nazwa;NIP;ID Symfonii\r\nDostawca;{nip};3001\r\n".encode()
    ).rows[0]
    row = FinanceCounterparty(
        id_type="nip",
        id_value=nip,
        name="Dostawca",
        country="PL",
        cost_account="402-1",
        symfonia_partner_id=None,
    )
    _derive_accounts(item, row)
    assert "cost_account" not in item.values or item.values["cost_account"] is None
    assert item.values["revenue_account"] == "200-2-3001"
    # To samo ID, które kartoteka już ma: nic nie dopisujemy.
    row.symfonia_partner_id = "3001"
    again = importer.parse(
        f"Nazwa;NIP;ID Symfonii\r\nDostawca;{nip};3001\r\n".encode()
    ).rows[0]
    _derive_accounts(again, row)
    assert again.values.get("revenue_account") is None


def test_sprzedawca_z_kosztow_bez_typu_zagraniczny_numer_to_vat_ue() -> None:
    foreign = sp._candidate("koszty", "DE123456789", "Lieferant GmbH")
    assert (foreign.id_type, foreign.country, foreign.ready) == ("vat_eu", "DE", True)
    # Zły NIP krajowy nadal jest błędem, nie „innym numerem”.
    assert not sp._candidate("koszty", "1234567890", "Dostawca").ready


def test_adres_klienta_w_jednym_polu_to_nie_brak_adresu() -> None:
    one_field = sp._candidate(
        "sprzedaz",
        _nip(810),
        "Klient",
        id_type="nip",
        street="ul. Testowa 1, 00-001 Warszawa",
    )
    assert one_field.warnings == []
    assert sp._candidate("sprzedaz", _nip(811), "Klient", id_type="nip").warnings == [
        "brak adresu"
    ]


def test_import_bierze_kraj_z_prefiksu_vat_ue_gdy_brak_kolumny_kraju() -> None:
    item = importer.parse(b"Nazwa;NIP;ID Symfonii\r\nKunde;DE123456789;4001\r\n").rows[
        0
    ]
    _derive_accounts(item, None)
    assert (item.values["cost_account"], item.values["revenue_account"]) == (
        "203-2-4001",
        "202-2-4001",
    )
