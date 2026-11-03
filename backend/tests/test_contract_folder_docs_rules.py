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


# ── Podmieniona treść dokumentu wysłanego do SharePointa ─────────────────────
# Skan podpisanego aneksu podmienia się w miejscu (ten sam dokument kontraktu).
# Wiersz z ``sharepoint_item_id`` nie wracał do wysyłki, więc w SharePoincie
# zostawał stary skan (przegląd kodu 13.10.2026).


def _sent_document(**overrides):
    from app.models.contract_document import ContractDocument

    fields = {
        "contract_id": 1,
        "filename": "skan.pdf",
        "file_path": "contracts/1/skan.pdf",
        "content_type": "application/pdf",
        "content_sha256": "a" * 64,
        "source": "upload",
        "sharepoint_item_id": "up-1",
        "sharepoint_push_status": "done",
        "sharepoint_push_attempts": 3,
        "sharepoint_push_error": "stary błąd",
    }
    return ContractDocument(**{**fields, **overrides})


def test_replaced_content_goes_back_to_waiting_for_a_file_nexus_sent() -> None:
    from app.services.contract_folder_docs.store import requeue_replaced_content

    doc = _sent_document()
    requeue_replaced_content(doc, content_sha256="b" * 64, filename="skan.pdf")
    assert doc.sharepoint_item_id == "up-1"
    assert doc.sharepoint_push_status is None
    assert doc.sharepoint_push_attempts == 0
    assert doc.sharepoint_push_error is None

    # Ta sama treść pod tą samą nazwą — kopia w SharePoincie jest aktualna.
    same = _sent_document()
    requeue_replaced_content(same, content_sha256="a" * 64, filename="skan.pdf")
    assert same.sharepoint_push_status == "done"
    # Dokument, który nie trafił do SharePointa, zostaje przy swoim stanie.
    skipped = _sent_document(sharepoint_item_id=None, sharepoint_push_status="skipped")
    requeue_replaced_content(skipped, content_sha256="b" * 64, filename="skan.pdf")
    assert skipped.sharepoint_push_status == "skipped"
    # Plik, który przyszedł z SharePointa, nie wraca tam z NEXUSA.
    pulled = _sent_document(source="sharepoint")
    requeue_replaced_content(pulled, content_sha256="b" * 64, filename="skan.pdf")
    assert pulled.sharepoint_push_status == "done"


class _SpStateSession:
    """Sesja na potrzeby ``sync._replace_one``: zna stan jednego pliku."""

    def __init__(self, state) -> None:
        self.state = state

    async def get(self, _model, _item_id):
        return self.state


def _replace_setup(monkeypatch, tmp_path, *, rename_fails: bool = False):
    from app.models.contract_doc_sharepoint import ContractDocSpItem
    from app.services import storage_service
    from app.services.contract_folder_docs import sync
    from app.services.m365 import sharepoint_docs as sp
    from app.services.m365.graph_client import GraphRequestError

    stored = tmp_path / "skan"
    stored.write_bytes(b"nowa tresc skanu")
    monkeypatch.setattr(
        storage_service, "get_contract_document_path", lambda _path: stored
    )
    calls: list[tuple] = []
    remote = {"name": "skan.pdf"}

    async def rename_file(_client, drive_id, item_id, name):
        calls.append(("rename", item_id, name))
        if rename_fails:
            raise GraphRequestError(409, {})
        remote["name"] = name
        return sp.DriveItem(item_id, name, False, 4, "c1", drive_id)

    async def replace_content(_client, drive_id, item_id, content, _content_type):
        calls.append(("content", item_id, content))
        return sp.DriveItem(
            item_id, remote["name"], False, len(content), "c2", drive_id
        )

    async def upload_file(*_args):
        raise AssertionError("podmiana nie dokłada drugiego pliku")

    monkeypatch.setattr(sp, "rename_file", rename_file)
    monkeypatch.setattr(sp, "replace_content", replace_content)
    monkeypatch.setattr(sp, "upload_file", upload_file)
    state = ContractDocSpItem(
        item_id="up-1",
        drive_id="drive",
        file_name="skan.pdf",
        size_bytes=4,
        c_tag="c1",
        status="pushed",
    )
    listed = {"up-1": sp.DriveItem("up-1", "skan.pdf", False, 4, "c1", "drive")}
    return sync, state, listed, calls


async def test_replaced_scan_overwrites_the_same_sharepoint_file(
    monkeypatch, tmp_path
) -> None:
    sync, state, listed, calls = _replace_setup(monkeypatch, tmp_path)
    doc = _sent_document(filename="poprawiony.pdf", sharepoint_push_status=None)
    stats = sync.SyncStats()

    handled = await sync._replace_one(
        _SpStateSession(state), None, "drive", doc, listed, stats
    )

    assert handled is True
    assert calls == [
        ("rename", "up-1", "poprawiony.pdf"),
        ("content", "up-1", b"nowa tresc skanu"),
    ]
    assert doc.sharepoint_item_id == "up-1"
    assert doc.sharepoint_push_status == "done"
    assert doc.sharepoint_pushed_at is not None
    assert (state.file_name, state.size_bytes, state.c_tag) == (
        "poprawiony.pdf",
        len(b"nowa tresc skanu"),
        "c2",
    )
    assert stats.pushed == 1


async def test_rename_conflict_keeps_the_old_name_unless_the_file_type_changes(
    monkeypatch, tmp_path
) -> None:
    from app.services.m365.graph_client import GraphRequestError

    sync, state, listed, calls = _replace_setup(
        monkeypatch, tmp_path, rename_fails=True
    )
    # Ten sam typ pliku: nazwa w SharePoincie zostaje, treść i tak jest nowa.
    doc = _sent_document(filename="poprawiony.pdf", sharepoint_push_status=None)
    assert await sync._replace_one(
        _SpStateSession(state), None, "drive", doc, listed, sync.SyncStats()
    )
    assert [c[0] for c in calls] == ["rename", "content"]
    assert doc.sharepoint_push_status == "done"
    assert state.file_name == "skan.pdf"

    # Inny typ: zdjęcie pod nazwą „.pdf” byłoby zepsutym plikiem — błąd,
    # ponowienie w następnym biegu, treść nietknięta.
    calls.clear()
    picture = _sent_document(filename="poprawiony.jpg", sharepoint_push_status=None)
    with pytest.raises(GraphRequestError):
        await sync._replace_one(
            _SpStateSession(state), None, "drive", picture, listed, sync.SyncStats()
        )
    assert [c[0] for c in calls] == ["rename"]


@pytest.mark.parametrize("case", ["not_ours", "no_state", "gone"])
async def test_file_nexus_did_not_send_is_never_overwritten(
    monkeypatch, tmp_path, case
) -> None:
    """Plik, który leżał w folderze, zanim NEXUS go powiązał, należy do działu;
    plik usunięty z SharePointa nie ma czego podmieniać. Dokument idzie wtedy
    jako nowy plik (zwykła wysyłka)."""
    sync, state, listed, calls = _replace_setup(monkeypatch, tmp_path)
    if case == "not_ours":
        state.status = "imported"
    doc = _sent_document(sharepoint_push_status=None)

    handled = await sync._replace_one(
        _SpStateSession(None if case == "no_state" else state),
        None,
        "drive",
        doc,
        {} if case == "gone" else listed,
        sync.SyncStats(),
    )

    assert handled is False
    assert doc.sharepoint_item_id is None
    assert calls == []
