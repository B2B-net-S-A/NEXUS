"""Ticket 9: typ dokumentu z nazwy pliku, folder „Nazwisko Imię” ↔ kontrakt,
plan przypisań. Czyste funkcje — bez bazy i bez sieci."""

from __future__ import annotations

import pytest

from app.services.m365.sharepoint_docs import (
    SharePointFolderNotFound,
    parse_site_url,
)

from app.services.contract_folder_docs.classify import classify_filename, is_importable
from app.services.contract_folder_docs.matching import (
    AMBIGUOUS,
    EXCLUDED,
    NONE,
    SURE,
    UNCERTAIN,
    ContractPerson,
    Folder,
    folder_display_name,
    match_contracts,
    match_person,
)
from app.services.contract_folder_docs.plan import (
    MAX_FILE_BYTES,
    ListedFile,
    build_plan,
)


@pytest.mark.parametrize(
    ("path", "folder"),
    [
        (
            "/sites/Share_B2B/Shared%20Documents/Umowy%20pracownik%C3%B3w",
            "Umowy pracowników",
        ),
        (
            "/sites/Share_B2B/Shared%20Documents/Forms/AllItems.aspx?id=%2Fsites%2FShare_B2B%2FShared%20Documents%2FUmowy%20pracownik%C3%B3w&p=true",
            "Umowy pracowników",
        ),
        ("/sites/Share_B2B/Shared%20Documents/Forms/AllItems.aspx", None),
        ("/:f:/s/Share_B2B/sharing-token", None),
    ],
)
def test_folder_link_accepts_sharepoint_browser_urls(path, folder):
    assert parse_site_url("https://b2bnetsa.sharepoint.com" + path) == (
        "b2bnetsa.sharepoint.com",
        "/sites/Share_B2B",
        folder,
    )


def test_browser_folder_link_cannot_switch_sites():
    with pytest.raises(SharePointFolderNotFound):
        parse_site_url(
            "https://b2bnetsa.sharepoint.com/sites/Share_B2B/Shared%20Documents/Forms/AllItems.aspx"
            "?id=%2Fsites%2FOther%2FShared%20Documents%2FUmowy"
        )


@pytest.mark.parametrize(
    ("filename", "expected"),
    [
        ("1401-2026 B2B 04.05.2026.pdf", "contract"),
        ("1401_2026_B2B_4.5.2026.pdf", "contract"),
        ("1401-2026 b2b 04-05-2026.jpg", "contract"),
        ("Aneks nr 1 do umowy.pdf", "annex"),
        # Numer umowy na początku, a to aneks — słowo wygrywa z formatem.
        ("1401-2026 B2B 04.05.2026 aneks 2.pdf", "annex"),
        ("Wypowiedzenie umowy.pdf", "termination_notice"),
        ("Porozumienie rozwiązujące.pdf", "termination_agreement"),
        ("Rozwiązanie umowy za porozumieniem.pdf", "termination_agreement"),
        ("ROZWIAZANIE.pdf", "termination_agreement"),
        ("NDA.pdf", "nda"),
        ("Umowa NDA podpisana.pdf", "nda"),
        ("Polisa 2026.jpg", "oc_policy"),
        ("OC 2026.pdf", "oc_policy"),
        ("Zaświadczenie ZUS.pdf", "zus_certificate"),
        ("Oświadczenie zleceniobiorcy.pdf", "other"),
        ("skan.jpg", "other"),
        # „OC” tylko jako osobne słowo — „ocena” nie jest polisą.
        ("ocena okresowa.pdf", "other"),
        ("Kodeks etyki.pdf", "other"),
        # Zamówienie klienta (ticket 10).
        ("Zamówienie 4500123456.pdf", "order"),
        ("ZAMOWIENIE_OIT_0189_2026.pdf", "order"),
        ("ZAM 12-2026.pdf", "order"),
        ("PO 4500123456.pdf", "order"),
        ("Purchase Order.pdf", "order"),
        ("Zlecenie wykonawcze nr 5.pdf", "order"),
        ("1401-2026 B2B 04.05.2026 zamówienie.pdf", "order"),
        # Aneks do zamówienia to aneks; „po” bez numeru to przyimek.
        ("Aneks do zamówienia.pdf", "annex"),
        ("Oświadczenie po zmianie.pdf", "other"),
        ("Umowa zlecenie.pdf", "other"),
        ("Polisa OC.pdf", "oc_policy"),
    ],
)
def test_document_type_comes_from_the_filename(filename: str, expected: str) -> None:
    assert classify_filename(filename).doc_type.value == expected


def test_contract_like_name_without_the_number_format_is_other_with_a_note() -> None:
    result = classify_filename("umowa B2B podpisana.pdf")
    assert result.doc_type.value == "other"
    assert result.note and "Inne" in result.note


@pytest.mark.parametrize(
    ("filename", "importable"),
    [
        ("umowa.pdf", True),
        ("skan.JPG", True),
        ("skan.jpeg", True),
        ("umowa.docx", False),
        ("umowa.doc", False),
        ("zdjecie.png", False),
        ("bez_rozszerzenia", False),
    ],
)
def test_only_pdf_and_jpg_are_imported(filename: str, importable: bool) -> None:
    assert is_importable(filename) is importable


FOLDERS = [
    Folder.of(name)
    for name in (
        "Kowalski Jan",
        "Nowak Łukasz",
        "Nowak-Kowalska Anna",
        "Zieliński Tomasz Marek",
        "Wiśniewski Piotr",
        "Wisniewski Piotr",
        "Jabłoński Filip",
        "Mazur Karolina",
    )
]


@pytest.mark.parametrize(
    ("first", "last", "kind", "folder", "reasons"),
    [
        ("Jan", "Kowalski", SURE, "Kowalski Jan", ()),
        ("JAN", "kowalski", SURE, "Kowalski Jan", ()),
        ("Lukasz", "Nowak", UNCERTAIN, "Nowak Łukasz", ("diacritics",)),
        ("Anna", "Nowak-Kowalska", SURE, "Nowak-Kowalska Anna", ()),
        ("Anna", "Nowak Kowalska", SURE, "Nowak-Kowalska Anna", ()),
        ("Anna", "Nowak", UNCERTAIN, "Nowak-Kowalska Anna", ("partial_name",)),
        ("Tomasz", "Zieliński", UNCERTAIN, "Zieliński Tomasz Marek", ("partial_name",)),
        ("Karolna", "Mazur", UNCERTAIN, "Mazur Karolina", ("typo",)),
        ("Piotr", "Wiśniewski", AMBIGUOUS, None, ("multiple_folders",)),
        ("Filip", "Jabłoński", EXCLUDED, None, ()),
        ("Filip", "Jablonski", EXCLUDED, None, ()),
        ("Adam", "Nieobecny", NONE, None, ()),
    ],
)
def test_person_is_matched_to_their_folder(first, last, kind, folder, reasons) -> None:
    result = match_person(first, last, FOLDERS)
    assert result.kind == kind
    assert (result.folder.name if result.folder else None) == folder
    assert result.reasons == reasons


def test_same_folder_for_two_candidate_records_is_flagged() -> None:
    contracts = [
        ContractPerson(1, 10, "Jan", "Kowalski"),
        ContractPerson(2, 11, "Jan", "Kowalski"),
    ]
    results = match_contracts(contracts, FOLDERS)
    assert [r.match.kind for r in results] == [UNCERTAIN, UNCERTAIN]
    assert all("same_name_people" in r.match.reasons for r in results)


def test_new_folder_name_is_last_name_first() -> None:
    assert folder_display_name("Jan", "Kowalski") == "Kowalski Jan"


def _plan():
    contracts = [
        ContractPerson(1, 10, "Jan", "Kowalski"),
        # Ta sama osoba, drugi projekt jako osobny kontrakt (ticket, pkt 3).
        ContractPerson(2, 10, "Jan", "Kowalski"),
        ContractPerson(3, 11, "Filip", "Jabłoński"),
        ContractPerson(4, 12, "Adam", "Nieobecny"),
        ContractPerson(5, 13, "Ewa", "Pusta"),
    ]
    folders = ["Kowalski Jan", "Obcy Ktoś", "Pusta Ewa", "Jabłoński Filip"]
    files = [
        ListedFile("Kowalski Jan", "a", "1401-2026 B2B 04.05.2026.pdf", 100),
        ListedFile("Kowalski Jan", "b", "2025/Aneks 1.pdf", 100),
        ListedFile("Kowalski Jan", "c", "umowa.docx", 100),
        ListedFile("Kowalski Jan", "d", "wielki.pdf", MAX_FILE_BYTES + 1),
        ListedFile("Obcy Ktoś", "e", "NDA.pdf", 10),
        ListedFile("Pusta Ewa", "f", "umowa.doc", 10),
        ListedFile("Jabłoński Filip", "g", "NDA.pdf", 10),
        ListedFile(None, "h", "lista.xlsx", 10),
    ]
    return build_plan(contracts, folders, files)


def test_plan_assigns_every_file_to_every_contract_of_the_person() -> None:
    plan = _plan()
    assignments = sorted(
        (r.contract_id, r.item_id, r.doc_type)
        for r in plan.rows
        if r.kind == "assignment"
    )
    assert assignments == [
        (1, "a", "contract"),
        (1, "b", "annex"),
        (2, "a", "contract"),
        (2, "b", "annex"),
    ]


def test_plan_reports_what_the_ticket_asks_for() -> None:
    plan = _plan()
    counters = plan.counters
    assert counters["contracts_with_documents"] == 2
    # Adam bez folderu, Ewa z folderem bez PDF/JPG.
    assert counters["contracts_without_documents"] == 2
    assert counters["contracts_excluded"] == 1
    # „Obcy Ktoś” — bez kontraktu; folder Filipa to wykluczenie, nie brak.
    assert counters["folders_without_contract"] == 1
    assert counters["files_skipped_extension"] == 2
    assert counters["files_skipped_size"] == 1
    assert counters["files_loose"] == 1
    notes = {r.contract_id: r.note for r in plan.rows if r.kind == "contract"}
    assert "Nie znaleziono podfolderu" in notes[4]
    assert "PDF ani JPG" in notes[5]
    assert "Filip Jabłoński" in notes[3]


def test_filip_jablonski_files_are_never_assigned() -> None:
    plan = _plan()
    assert not [r for r in plan.rows if r.kind == "assignment" and r.item_id == "g"]
