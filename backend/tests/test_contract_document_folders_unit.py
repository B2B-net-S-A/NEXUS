"""0494: foldery w Dokumentach kontraktu — logika bez bazy (numer umowy
z nazwy pliku, podpowiedź „Poprzednia umowa”, nazwa folderu)."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.models.contract_document import ContractDocumentType as T
from app.services.contract_document_folders import (
    build_suggestions,
    clean_folder_name,
    parse_contract_number,
)


def _doc(doc_id: int, filename: str, doc_type: T, folder_id: int | None = None):
    return SimpleNamespace(
        id=doc_id, filename=filename, doc_type=doc_type, folder_id=folder_id
    )


def _folder(folder_id: int, name: str):
    return SimpleNamespace(id=folder_id, name=name)


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Umowa B2B nr 518-2026_Błachewicz Agnieszka.pdf", (518, 2026)),
        ("Aneks nr 1 do umowy 361-2019.pdf", (361, 2019)),
        ("1401-2026 B2B 04.05.2026 aneks 1.pdf", (1401, 2026)),
        ("1434/2026", (1434, 2026)),
        ("umowa_77_2021.pdf", (77, 2021)),
        # Daty nie są numerem umowy.
        ("wypowiedzenie 01-10-2026.pdf", None),
        ("skan 04.05.2026.pdf", None),
        ("wypowiedzenie b2b Agnieszka Błachewicz.pdf", None),
        ("", None),
        (None, None),
    ],
)
def test_parse_contract_number(text, expected) -> None:
    assert parse_contract_number(text) == expected


def test_suggests_previous_contract_with_unnumbered_termination() -> None:
    docs = [
        _doc(1, "Umowa B2B nr 518-2026_X.pdf", T.contract),
        _doc(2, "Aneks nr 1 do umowy 518-2026.pdf", T.annex),
        _doc(3, "Umowa nr 361-2019_X.pdf", T.contract),
        _doc(4, "Aneks nr 1 do umowy 361-2019.pdf", T.annex),
        _doc(5, "wypowiedzenie b2b X.pdf", T.termination_notice),
        _doc(
            6,
            "Porozumienie o rozwiązaniu umowy nr 361-2019.pdf",
            T.termination_agreement,
        ),
        # Zamówienie i NDA nie wchodzą do podpowiedzi, nawet z numerem.
        _doc(7, "Zamówienie 12-2019.pdf", T.order),
        _doc(8, "NDA 3-2019.pdf", T.nda),
    ]
    current, out = build_suggestions(docs, [], current=(518, 2026), contract_live=True)
    assert current == (518, 2026)
    assert len(out) == 1
    assert out[0].number == "361-2019"
    assert out[0].folder_name == "Poprzednia umowa – nr 361-2019"
    assert out[0].folder_id is None
    assert out[0].document_ids == [3, 4, 5, 6]


def test_without_known_number_the_newest_counts_as_current() -> None:
    docs = [
        _doc(1, "Umowa nr 361-2019.pdf", T.contract),
        _doc(2, "Umowa nr 518-2026.pdf", T.contract),
    ]
    current, out = build_suggestions(docs, [], current=None, contract_live=True)
    assert current == (518, 2026)
    assert [s.document_ids for s in out] == [[1]]


def test_unnumbered_termination_is_not_guessed_between_two_old_contracts() -> None:
    docs = [
        _doc(1, "Umowa nr 518-2026.pdf", T.contract),
        _doc(2, "Umowa nr 361-2019.pdf", T.contract),
        _doc(3, "Umowa nr 12-2017.pdf", T.contract),
        _doc(4, "wypowiedzenie.pdf", T.termination_notice),
    ]
    _, out = build_suggestions(docs, [], current=(518, 2026), contract_live=True)
    assert [s.number for s in out] == ["361-2019", "12-2017"]
    assert all(4 not in s.document_ids for s in out)


def test_termination_on_ended_contract_stays_put() -> None:
    docs = [
        _doc(1, "Umowa nr 518-2026.pdf", T.contract),
        _doc(2, "Umowa nr 361-2019.pdf", T.contract),
        _doc(3, "wypowiedzenie.pdf", T.termination_notice),
    ]
    _, out = build_suggestions(docs, [], current=(518, 2026), contract_live=False)
    assert out[0].document_ids == [2]


def test_files_already_in_a_folder_are_not_suggested_again() -> None:
    docs = [
        _doc(1, "Umowa nr 518-2026.pdf", T.contract),
        _doc(2, "Umowa nr 361-2019.pdf", T.contract, folder_id=9),
    ]
    _, out = build_suggestions(docs, [], current=(518, 2026), contract_live=True)
    assert out == []


def test_existing_folder_with_the_suggested_name_is_reused() -> None:
    docs = [
        _doc(1, "Umowa nr 518-2026.pdf", T.contract),
        _doc(2, "Aneks do umowy 361-2019.pdf", T.annex),
    ]
    folders = [_folder(9, "poprzednia umowa – NR 361-2019")]
    _, out = build_suggestions(docs, folders, current=(518, 2026), contract_live=True)
    assert out[0].folder_id == 9


def test_single_contract_has_no_suggestion() -> None:
    docs = [_doc(1, "Umowa nr 518-2026.pdf", T.contract)]
    assert build_suggestions(docs, [], current=None, contract_live=True)[1] == []
    assert build_suggestions([], [], current=None, contract_live=True) == (None, [])


def test_folder_name_is_trimmed_and_bounded() -> None:
    assert clean_folder_name("  Poprzednia   umowa ") == "Poprzednia umowa"
    with pytest.raises(HTTPException) as empty:
        clean_folder_name("   ")
    assert empty.value.status_code == 422
    with pytest.raises(HTTPException) as long:
        clean_folder_name("x" * 121)
    assert long.value.status_code == 422
