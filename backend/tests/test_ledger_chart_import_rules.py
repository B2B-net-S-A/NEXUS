"""Plan kont z Symfonii (K1) — odczyt XML „Model księgowy” bez bazy.

Numer konta z ``syntet`` i ``wartN``, słownik kontrahentów z węzła ``wart=0``,
typ konta, znaczniki MF (pojedynczy i para), bezpieczeństwo pliku. XML
sfabrykowany: numery, nazwy i znaczniki są wymyślone, nie z pliku firmy.
"""

from __future__ import annotations

import pytest

from app.services.finance_ledger.counterparty_import import ImportFileError
from app.services.ledger import chart_import


def _plankont(syntet: int, *segments: tuple[int, int], name: str, typ: int) -> str:
    attrs = [f'syntet="{syntet}"']
    padded = list(segments) + [(0, 0)] * (5 - len(segments))
    for index, (kind, value) in enumerate(padded, start=1):
        attrs.append(f'typ{index}="{kind}" wart{index}="{value}"')
    return f'<plankont {" ".join(attrs)} nazwa="{name}" typ="{typ}" podtyp="0"/>'


def _znacznik(account: str, first: str, second: str = "") -> str:
    return (
        f'<znacznik konto="{account}" znacznikJpk1="{first}" '
        f'znacznikJpk2="{second}" znacznikJpkPd=""/>'
    )


def _file(*items: str) -> bytes:
    body = "\n".join(items)
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        f"<DokumentXML><naglowek><wersja>3.00</wersja></naglowek>{body}</DokumentXML>"
    ).encode()


def test_number_is_padded_syntet_plus_segments_until_zero_pair():
    parsed = chart_import.parse(
        _file(
            _plankont(10, name="Środki trwałe", typ=1),
            _plankont(10, (-1, 3), name="Środki trwałe - inne", typ=1),
            _plankont(402, (-1, 203), name="Usługi obce", typ=2),
            _plankont(131, (-1, 1), (-1, 7), name="Rachunek", typ=1),
        )
    )
    assert list(parsed.accounts) == ["010", "010-3", "402-203", "131-1-7"]
    assert parsed.accounts["010-3"].name == "Środki trwałe - inne"


def test_type_comes_from_symfonia_type_and_account_class():
    parsed = chart_import.parse(
        _file(
            _plankont(10, name="ŚT", typ=1),
            _plankont(131, name="Bank", typ=1),
            _plankont(201, name="Dostawcy", typ=1),
            _plankont(801, name="Kapitał", typ=1),
            _plankont(402, name="Usługi", typ=2),
            _plankont(900, name="Pozabilansowe", typ=0),
        )
    )
    types = {number: item.account_type for number, item in parsed.accounts.items()}
    assert types == {
        "010": "active",
        "131": "active",
        "201": "mixed",
        "801": "passive",
        "402": "result",
        "900": "off_balance",
    }


def test_dictionary_node_marks_parent_and_is_not_an_account():
    parsed = chart_import.parse(
        _file(
            _plankont(201, (-1, 2), name="Dostawcy krajowi", typ=1),
            _plankont(201, (-1, 2), (2, 0), name="Kontrahenci", typ=1),
            _plankont(208, name="Rozrachunki", typ=1),
            _plankont(208, (2, 0), name="Kontrahenci", typ=1),
            _plankont(234, name="Pracownicy konto", typ=1),
            _plankont(234, (1, 0), name="Pracownicy", typ=1),
        )
    )
    assert sorted(parsed.accounts) == ["201-2", "208", "234"]
    assert {n: a.dictionary for n, a in parsed.accounts.items()} == {
        "201-2": "counterparty",
        "208": "counterparty",
        "234": "counterparty",
    }
    assert parsed.dictionaries == 3
    assert any("Pracownicy" in note for note in parsed.notes)


def test_unknown_dictionary_is_reported_not_guessed():
    parsed = chart_import.parse(
        _file(
            _plankont(300, name="Towary", typ=1),
            _plankont(300, (2, 0), name="Magazyny", typ=1),
        )
    )
    assert parsed.accounts["300"].dictionary is None
    assert any("Magazyny" in problem for problem in parsed.problems)


def test_markers_single_pair_and_foreign_account():
    parsed = chart_import.parse(
        _file(
            _plankont(402, name="Usługi", typ=2),
            _plankont(200, (-1, 2), name="Odbiorcy", typ=1),
            _plankont(131, name="Bank", typ=1),
            _znacznik("402", "RPBIII"),
            _znacznik("200-2", "BABII3a_D12", "BPBIII3d_D12"),
            _znacznik("131", "BABIII1c1_SPKR", "BABIII1c1_SPKR"),
            _znacznik("200-2-x", "BABII3a_D12", "BPBIII3d_D12"),
        )
    )
    assert parsed.accounts["402"].report_line == "RPBIII"
    assert parsed.accounts["200-2"].report_line == "BABII3a_D12/BPBIII3d_D12"
    assert parsed.accounts["131"].report_line == "BABIII1c1_SPKR"
    assert (parsed.markers_applied, parsed.markers_ignored) == (3, 1)


def test_marker_pair_on_result_account_is_refused_with_one_summary_problem():
    parsed = chart_import.parse(
        _file(
            _plankont(753, name="Pozostałe", typ=2),
            _plankont(756, name="Inne", typ=2),
            _znacznik("753", "RPHII_RKKII_POZ", "RPGIII_RKJIII_POZ"),
            _znacznik("756", "RPHIV_RKKIV_RK", "RPGV_RKJV_RK"),
            _znacznik("999", "RPBIII"),
        )
    )
    assert parsed.accounts["753"].report_line is None
    assert len([p for p in parsed.problems if "Pozycji sprawozdania" in p]) == 1
    assert "753" in parsed.problems[0] and "756" in parsed.problems[0]


def test_duplicates_nameless_and_broken_accounts_are_reported():
    parsed = chart_import.parse(
        _file(
            _plankont(131, name="Bank", typ=1),
            _plankont(131, name="Bank drugi", typ=1),
            _plankont(132, name="", typ=1),
            '<plankont syntet="abc" nazwa="Zły" typ="1"/>',
        )
    )
    assert list(parsed.accounts) == ["131"]
    assert parsed.accounts["131"].name == "Bank"
    assert len(parsed.problems) == 3


def test_not_a_symfonia_file_is_refused():
    with pytest.raises(ImportFileError):
        chart_import.parse(b"to nie jest xml")
    with pytest.raises(ImportFileError):
        chart_import.parse(b"<Inny><plankont syntet='1'/></Inny>")
    with pytest.raises(ImportFileError):
        chart_import.parse(_file())  # brak kont


def test_doctype_entities_and_size_are_refused():
    bomb = (
        b'<?xml version="1.0"?><!DOCTYPE DokumentXML [<!ENTITY a "aaaa">]>'
        b"<DokumentXML>&a;</DokumentXML>"
    )
    with pytest.raises(ImportFileError) as exc:
        chart_import.parse(bomb)
    assert "DOCTYPE" in str(exc.value)
    with pytest.raises(ImportFileError):
        chart_import.parse(b"x" * (chart_import.MAX_BYTES + 1))
