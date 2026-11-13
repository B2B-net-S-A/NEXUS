"""Księgowość w Finansach (0696, E0 i E1) — reguły bez bazy.

Etapy kolejki kosztów i odmowy, flagi (MPP wyklucza NIE MPP), identyfikator
kontrahenta (NIP z sumą kontrolną, PESEL, VAT UE), import pliku z eBI24
(aliasy nagłówków, duplikaty, zły NIP) i rola kontrahenta. Dane fikcyjne.
"""

from __future__ import annotations

import io
import zipfile

import pytest
from openpyxl import Workbook

from app.services.finance_ledger import costs, identifiers
from app.services.finance_ledger import counterparty_import as importer
from app.services.finance_ledger.counterparties import RoleIndex
from app.services.finance_ledger_schema import (
    DATA_DDL,
    ENTRY_INSERTS,
    STAGES,
    entry_inserts,
)


def _nip(seed: int) -> str:
    """Fikcyjny NIP z poprawną sumą kontrolną."""

    weights = (6, 5, 7, 2, 3, 4, 5, 6, 7)
    for offset in range(1000):
        base = f"{(seed + offset) % 10**9:09d}"
        check = sum(int(d) * w for d, w in zip(base, weights)) % 11
        if check != 10:
            return base + str(check)
    raise AssertionError("brak NIP-u")


def _bad_nip(seed: int) -> str:
    good = _nip(seed)
    return good[:9] + str((int(good[9]) + 1) % 10)


NIP_A = _nip(111_222_333)
NIP_B = _nip(444_555_666)
NIP_C = _nip(777_888_999)
PESEL = "44051401458"  # przykład z dokumentacji MSWiA, suma kontrolna poprawna


# ── Etapy ────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("action", "stage", "target"),
    [
        ("accept", "received", "new"),
        ("reject", "received", "rejected"),
        ("reject", "new", "rejected"),
        ("verify", "new", "verified"),
        ("ready", "verified", "ready"),
        ("back", "new", "received"),
        ("back", "verified", "new"),
        ("back", "ready", "verified"),
        ("back", "rejected", "received"),
    ],
)
def test_przejscia_z_ksef(action: str, stage: str, target: str) -> None:
    assert costs.next_stage(action, stage, from_ksef=True) == target


@pytest.mark.parametrize(
    ("action", "stage"),
    [
        ("accept", "new"),
        ("verify", "received"),
        ("verify", "verified"),
        ("ready", "new"),
        ("ready", "ready"),
        ("reject", "verified"),
        ("back", "received"),
    ],
)
def test_zly_etap_to_odmowa_z_powodem(action: str, stage: str) -> None:
    with pytest.raises(costs.LedgerError) as exc:
        costs.next_stage(action, stage, from_ksef=True)
    assert exc.value.status == 409
    assert "etap" in exc.value.message or "wstecz" in exc.value.message


@pytest.mark.parametrize("action", ["accept", "reject", "verify", "ready", "back"])
def test_zaksiegowanej_nie_ruszamy(action: str) -> None:
    with pytest.raises(costs.LedgerError) as exc:
        costs.next_stage(action, "booked", from_ksef=True)
    assert exc.value.message == costs.BOOKED_DETAIL


def test_pdf_nie_ma_poczekalni() -> None:
    with pytest.raises(costs.LedgerError):
        costs.next_stage("back", "new", from_ksef=False)
    assert costs.next_stage("back", "rejected", from_ksef=False) == "new"


def test_nieznana_akcja_to_422() -> None:
    with pytest.raises(costs.LedgerError) as exc:
        costs.next_stage("book", "ready", from_ksef=True)
    assert exc.value.status == 422


def test_powod_odrzucenia_wymagany() -> None:
    with pytest.raises(costs.LedgerError) as exc:
        costs.clean_reason("  a ")
    assert exc.value.status == 422
    assert costs.clean_reason("  nie   dotyczy firmy ") == "nie dotyczy firmy"


def test_etykiety_dla_kazdego_etapu() -> None:
    assert set(costs.STAGE_LABELS) == set(STAGES)


# ── Flagi ────────────────────────────────────────────────────────────────────


def test_mpp_wyklucza_nie_mpp() -> None:
    assert costs.with_flag(["no_mpp", "duplicate"], "mpp", on=True) == [
        "mpp",
        "duplicate",
    ]
    assert costs.with_flag(["mpp"], "no_mpp", on=True) == ["no_mpp"]
    assert costs.with_flag(["mpp", "hold_payment"], "mpp", on=False) == ["hold_payment"]
    with pytest.raises(costs.LedgerError):
        costs.clean_flags(["mpp", "no_mpp"])
    with pytest.raises(costs.LedgerError):
        costs.with_flag([], "pilne", on=True)


# ── Zakładanie wpisów ────────────────────────────────────────────────────────


def test_backfill_obejmuje_trzy_zrodla_i_nie_nadpisuje() -> None:
    joined = " ".join(ENTRY_INSERTS)
    for table in (
        "payroll_invoices",
        "client_contractor_invoices",
        "approval_documents",
    ):
        assert f"FROM {table}" in joined
    assert all("DO NOTHING" in statement for statement in ENTRY_INSERTS)
    # Bez NOT EXISTS co godzinę każdy wiersz źródła zjadałby wartość SERIAL.
    assert all("NOT EXISTS" in statement for statement in ENTRY_INSERTS)
    assert all(":ksef_number" not in statement for statement in DATA_DDL)
    assert all(":ksef_number" in s for s in entry_inserts(by_ksef_number=True))


# ── Identyfikator ────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("raw", "kind", "expected"),
    [
        (f"PL {NIP_A[:3]}-{NIP_A[3:6]}-{NIP_A[6:8]}-{NIP_A[8:]}", None, NIP_A),
        (NIP_A, "NIP", NIP_A),
        (f"PL{NIP_A}", "VAT UE", NIP_A),
    ],
)
def test_nip_w_kazdym_zapisie_to_ten_sam_klucz(raw, kind, expected) -> None:
    identifier = identifiers.normalize(raw, kind)
    assert identifier == identifiers.Identifier("nip", expected)


def test_zly_nip_to_blad() -> None:
    with pytest.raises(identifiers.IdentifierError, match="sumę kontrolną"):
        identifiers.normalize(_bad_nip(1))
    with pytest.raises(identifiers.IdentifierError):
        identifiers.normalize("12345", "NIP")


def test_pesel_vat_ue_i_inny() -> None:
    assert identifiers.normalize(PESEL) == identifiers.Identifier("pesel", PESEL)
    assert identifiers.normalize("de 123 456 789") == identifiers.Identifier(
        "vat_eu", "DE123456789"
    )
    assert identifiers.normalize("US-98-7654321", "inny") == identifiers.Identifier(
        "other", "US987654321"
    )
    with pytest.raises(identifiers.IdentifierError):
        identifiers.normalize("44051401459", "PESEL")
    with pytest.raises(identifiers.IdentifierError, match="typ"):
        identifiers.normalize(NIP_A, "REGON")
    assert identifiers.normalize("   ") is None


# ── Import pliku ─────────────────────────────────────────────────────────────


def _csv(rows: list[list[str]], delimiter: str = ";") -> bytes:
    return "\n".join(delimiter.join(row) for row in rows).encode("utf-8")


@pytest.mark.parametrize(
    ("header", "field"),
    [
        ("Nazwa", "name"),
        ("Nazwa kontrahenta", "name"),
        ("NIP", "identifier"),
        ("NIP kontrahenta", "identifier"),
        ("Identyfikator", "identifier"),
        ("Typ identyfikatora", "id_type"),
        ("Kod pocztowy", "postal_code"),
        ("Kod kraju", "country"),
        ("Kraj", "country"),
        ("Miejscowość", "city"),
        ("E-mail", "email"),
        ("Adres e-mail", "email"),
        ("Symfonia ID", "symfonia_partner_id"),
        ("Id partnera", "symfonia_partner_id"),
        ("ID kontrahenta Symfonia", "symfonia_partner_id"),
        ("Konto kosztowe", "cost_account"),
        ("Symfonia: konto kosztowe", "cost_account"),
        ("Konto przychodowe (Symfonia)", "revenue_account"),
        ("Uwagi", None),
    ],
)
def test_aliasy_naglowkow(header: str, field) -> None:
    assert importer.match_header(header) == field


def test_csv_z_tytulem_duplikatem_i_zlym_nipem() -> None:
    content = _csv(
        [
            ["Partnerzy — eksport"],
            ["Nazwa", "NIP", "Kraj", "Email", "Symfonia ID", "Konto kosztowe"],
            [
                "Biuro Testowe Sp. z o.o.",
                NIP_A,
                "PL",
                "biuro@example.com",
                "17",
                "201-2-317",
            ],
            ["Kurier Przykładowy", NIP_B, "Polska", "zły-adres", "18", "201-2-273"],
            ["Duplikat Biura", f"PL{NIP_A}", "PL", "", "19", ""],
            ["Literówka NIP", _bad_nip(5), "PL", "", "20", ""],
            ["", "", "", "", "", ""],
            ["Bez numeru", "", "DE", "", "", ""],
            ["Tylko Symfonia", "", "DE", "", "21", "201-2-9"],
            ["Ten sam ID Symfonii", NIP_C, "PL", "", "17", ""],
        ]
    )
    parsed = importer.parse(content)
    assert [row.line for row in parsed.rows] == [3, 4, 9]
    assert parsed.rows[0].values["cost_account"] == "201-2-317"
    assert parsed.rows[1].values["country"] == "PL"
    assert parsed.rows[1].values["email"] is None
    assert parsed.rows[2].id_value is None
    assert parsed.skipped_empty == 1
    messages = {error["line"]: error["message"] for error in parsed.errors}
    assert "wierszu 3" in messages[5]
    assert "sumę kontrolną" in messages[6]
    assert "Brak identyfikatora" in messages[8]
    assert "ID Symfonii" in messages[10]


def test_xlsx_liczby_i_typ_identyfikatora() -> None:
    book = Workbook()
    sheet = book.active
    sheet.append(
        ["Nazwa partnera", "Typ identyfikatora", "Identyfikator", "Id partnera"]
    )
    sheet.append(["Konsultant Przykładowy", "PESEL", PESEL, 501])
    sheet.append(["Firma Niemiecka", "VAT UE", "DE 123456789", 502.0])
    sheet.append(["Firma Polska", "NIP", int(NIP_A), 503])
    buffer = io.BytesIO()
    book.save(buffer)
    parsed = importer.parse(buffer.getvalue())
    assert parsed.errors == []
    assert [(row.id_type, row.id_value) for row in parsed.rows] == [
        ("pesel", PESEL),
        ("vat_eu", "DE123456789"),
        ("nip", NIP_A),
    ]
    assert [row.values["symfonia_partner_id"] for row in parsed.rows] == [
        "501",
        "502",
        "503",
    ]


def test_xlsx_z_bomba_zip_odrzucony_przed_openpyxl() -> None:
    """Część XML ponad limit wspólnego strażnika (10 MB) — po kompresji kilka
    KB, więc limit uploadu jej nie zatrzyma (wzór: ``test_r10_impex_imports``)."""

    book = Workbook()
    book.active.append(["Nazwa", "NIP"])
    original_buffer = io.BytesIO()
    book.save(original_buffer)
    rebuilt_buffer = io.BytesIO()
    with (
        zipfile.ZipFile(io.BytesIO(original_buffer.getvalue())) as original,
        zipfile.ZipFile(rebuilt_buffer, "w", zipfile.ZIP_DEFLATED) as rebuilt,
    ):
        for info in original.infolist():
            rebuilt.writestr(info, original.read(info))
        rebuilt.writestr("customXml/item1.xml", "<a>" + "x" * (11 * 1024 * 1024))
    assert len(rebuilt_buffer.getvalue()) < 1024 * 1024
    with pytest.raises(importer.ImportFileError, match="za duży po rozpakowaniu"):
        importer.parse(rebuilt_buffer.getvalue())


def test_plik_bez_naglowka_albo_pusty() -> None:
    with pytest.raises(importer.ImportFileError, match="nagłówka"):
        importer.parse(_csv([["a", "b"], ["c", "d"]]))
    with pytest.raises(importer.ImportFileError):
        importer.parse(b"")
    with pytest.raises(importer.ImportFileError, match="XLSX"):
        importer.parse(b"PK\x03\x04zepsuty")


def test_zle_konto_to_blad_wiersza() -> None:
    parsed = importer.parse(
        _csv([["Nazwa", "NIP", "Konto kosztowe"], ["Firma", NIP_A, "201 2 ##"]])
    )
    assert parsed.rows == []
    assert "Konto kosztowe" in parsed.errors[0]["message"]


def test_csv_z_przecinkiem_i_cp1250() -> None:
    content = "Nazwa,NIP\nŁódzka Spółka,{}\n".format(NIP_B).encode("cp1250")
    parsed = importer.parse(content)
    assert parsed.rows[0].values["name"] == "Łódzka Spółka"


# ── Rola kontrahenta ─────────────────────────────────────────────────────────


def test_rola_klient_osoba_kontraktor_dostawca() -> None:
    index = RoleIndex(
        clients=frozenset({NIP_A, "DE123456789"}),
        team=frozenset({NIP_B}),
        contractors=frozenset({NIP_C, NIP_B}),
    )
    assert index.role("nip", NIP_A) == "client"
    assert index.role("vat_eu", "DE123456789") == "client"
    assert index.role("nip", NIP_B) == "team"
    assert index.role("nip", NIP_C) == "contractor"
    assert index.role("nip", _nip(9)) == "supplier"
    assert index.role("pesel", PESEL) == "supplier"
    assert index.role(None, None) == "supplier"
