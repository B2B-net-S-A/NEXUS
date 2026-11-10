"""E2: odczyt RCP z szablonu BNP i kontrole dowodu pracy.

Dane zmyślone w układzie prawdziwego szablonu (tekst strony PDF z ``pdfplumber``
i wiersze arkusza); prawdziwe pliki z nazwiskami sprawdzamy tylko lokalnie.
"""

from __future__ import annotations

import io
from datetime import datetime, timezone
from decimal import Decimal as D

import openpyxl
import pytest

from app.services.client_settlements import rules_catalog
from app.services.client_settlements.rcp_bnp import (
    ParsedRcp,
    SignatureInfo,
    SummaryRow,
    parse_pdf_text,
    parse_xlsx,
    parse_xlsx_rows,
)
from app.services.client_settlements.rcp_checks import PDF, XLSX, evaluate
from app.services.consultant_portal import documents
from app.services.hr import documents_store

WEEK = "0,0 0,0 0,0 0,0 8,0 10,0 0,0 8,0 10,0 0,0 0,0 10,0 9,0 8,0 12,0 10,0 0,0 0,0 10,0 8,0 9,0 0,0 0,0 0,0 0,0 9,0 11,0 10,0 8,0 8,0 0,0"
TOTAL = "0,0 0,0 0,0 0,0 8,0 10,0 0,0 8,0 10,0 4,0 4,0 10,0 9,0 8,0 12,0 10,0 0,0 0,0 10,0 8,0 9,0 0,0 0,0 4,0 4,0 9,0 11,0 10,0 8,0 8,0 0,0"

PDF_TEXT = f"""Rozliczenie czasu pracy
Rozliczenie 2026-10-01 Ilość dni przepracowanych 21,8
Check OK
Nazwa firmy B2B Network
Nazwisko Testowa
Imię Anna
Rola Devops Engineer
Numer zamówienia
DANE WPISANE W DOKUMENCIE TRAKTUJEMY JAKO PODSTAWĘ DO ROZLICZENIA FAKTURY
1 2 3 4 5 6 7 8 9 10 11 12 13 14 15 16 17 18 19 20 21 22 23 24 25 26 27 28 29 30 31 Total MD's
Godziny w tygodniu {WEEK} 158,0 19,75
Godziny w sobotę 4,0 4,0 8,0 1,0
Godziny w niedzielę 4,0 4,0 8,0 1,0
SUMA {TOTAL} 174,0 21,75
Koszty Delegacji 1 2 3 4 5 6 7 8 9 10 11 12 13 14 15 16 17 18 19 20 21 22 23 24 25 26 27 28 29 30 31 Total
SUMA 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0,00
OPIS PRAC MDs No ID PRODUCT Kod aplikacji CMDB Koszty wyjazdu służbowego
Prace DevOps 17,0000 ORD SX01929
Przykładowy opis prac np.: testy, zarządzanie,
Wyjazd służbowy 0,0000
Godziny dodatkowe w tygodniu 2,7500 ORD SX01929
Godziny dodatkowe w sobotę 1,0000 ORD SX01929
Godziny dodatkowe w niedzielę 1,0000 ORD SX01929
SUMA: 21,7500
Cyfrowy podpis Przełożonego
"""


def test_pdf_odczyt_szablonu_bnp():
    p = parse_pdf_text(PDF_TEXT)
    assert p is not None
    assert p.month == "2026-10"
    assert (p.first_name, p.last_name) == ("Anna", "Testowa")
    assert p.check_ok is True
    assert p.total_hours == D("174.0") and p.declared_md == D("21.75")
    assert p.md_regular == D("17") and p.md_extra == D("4.75")
    assert p.weekend_days == (10, 11, 24, 25)
    assert max(p.day_totals) == D("12.0")
    assert p.travel_total == D("0.00")
    assert all(r.product == "ORD" and r.cmdb == "SX01929" for r in p.summary)


def test_pdf_spoza_szablonu_to_brak_odczytu():
    assert parse_pdf_text("Faktura VAT nr 1/10/2026\nNabywca: B2B") is None


def _sheet(summary_rows: list[list]) -> list[list]:
    days = list(range(1, 32))
    week = [8 if d in (1, 2, 5, 6, 7, 8, 9) else 0 for d in days]
    return [
        [None, None, "Rozliczenie czasu pracy"],
        [None, "Rozliczenie", datetime(2026, 10, 31), "Check", "OK"],
        [None, "Nazwisko", "Testowa"],
        [None, "Imię", "Anna"],
        [None, "Numer zamówienia", "ZAM_1_2026"],
        [None, None, *days],
        [None, "Godziny w tygodniu", *week, None, 56, 7],
        [None, "SUMA", *week, 0, 56, 7],
        [None, "Koszty Delegacji", *days],
        [None, "SUMA", *([0] * 31), 0],
        [
            None,
            "OPIS PRAC",
            "MDs No",
            None,
            None,
            "ID PRODUCT ",
            None,
            "Kod aplikacji CMDB",
        ],
        *summary_rows,
        [None, "SUMA:", 7],
    ]


def test_xlsx_wiersz_z_przykladowym_opisem_i_danymi_to_praca():
    rows = _sheet(
        [
            [
                None,
                "Przykładowy opis prac np.: development",
                0,
                None,
                None,
                'np.: "ORD"',
                None,
                'np.: "SX03889"',
            ],
            [
                None,
                "Przykładowy opis prac np.: testy",
                7,
                None,
                None,
                "DPF",
                None,
                "OFS Suite: SX04571 ",
            ],
            [
                None,
                "Godziny dodatkowe w tygodniu",
                0,
                None,
                None,
                'np.: "ORD"',
                None,
                'np.: "SX03889"',
            ],
        ]
    )
    p = parse_xlsx_rows(rows)
    assert p is not None and p.source == "xlsx"
    assert p.month == "2026-10" and p.order_number == "ZAM_1_2026"
    assert p.total_hours == D("56") and p.declared_md == D("7")
    assert p.md_regular == D("7") and p.md_extra == D("0")
    assert [(r.product, r.cmdb) for r in p.summary] == [("DPF", "OFS Suite: SX04571")]


def test_xlsx_z_pliku():
    workbook = openpyxl.Workbook()
    for row in _sheet([[None, "development", 7, None, None, "EBI", None, "SX03098"]]):
        workbook.active.append(row)
    buffer = io.BytesIO()
    workbook.save(buffer)
    p = parse_xlsx(buffer.getvalue())
    assert p is not None and p.md_regular == D("7") and p.summary_total == D("7")


# ── Kontrole ────────────────────────────────────────────────────────────────


def _rules(**levels: str) -> dict:
    stored = {
        "proof.month": {"level": "block"},
        "proof.signed_pdf": {
            "level": "block",
            "params": {"issuer": "Fortis Bank Polska"},
        },
        "proof.excel_with_mail": {"level": "warn"},
        "proof.name_match": {"level": "warn"},
        "fields.product_id": {"level": "block"},
        "fields.cmdb": {"level": "warn"},
        "fields.md_hours": {"level": "block", "params": {"hours": "8"}},
        "fields.day_limit": {"level": "block", "params": {"hours": "24"}},
        "extra.mail_accept": {"level": "block"},
    }
    for key, level in levels.items():
        stored[key.replace("__", ".")] = {
            **stored.get(key.replace("__", "."), {}),
            "level": level,
        }
    return rules_catalog.effective(stored)


SIGNED = [
    SignatureInfo(
        True,
        True,
        "Fortis Bank Polska S.A. Subordinate CA",
        "PRZELOZONY Jan",
        "bank.pl",
        datetime(2026, 11, 2, 16, 52, tzinfo=timezone.utc),
    )
]


def _eval(parsed: ParsedRcp, **kw):
    args = {
        "mime": PDF,
        "month": "2026-10",
        "person_name": "Anna Testowa",
        "has_mail": True,
        "rules": _rules(),
    }
    args.update(kw)
    signatures = args.pop("signatures", SIGNED)
    return evaluate(parsed, signatures, **args)


def _states(result) -> dict[str, str]:
    return {c["title"]: c["state"] for g in result.groups for c in g["checks"]}


def test_poprawne_rcp_bez_uwag():
    r = _eval(parse_pdf_text(PDF_TEXT))
    assert not r.blocking and not r.warn
    assert r.md_regular == D("17") and r.md_extra == D("4.75")
    assert "fail" not in _states(r).values()


def test_nazwisko_bez_polskich_znakow_i_w_innej_kolejnosci_przechodzi():
    r = _eval(parse_pdf_text(PDF_TEXT), person_name="Testowa Anna")
    assert not r.warn


def test_inne_nazwisko_ostrzega_a_wylaczona_regula_milczy():
    assert _eval(parse_pdf_text(PDF_TEXT), person_name="Jan Inny").warn
    quiet = _eval(
        parse_pdf_text(PDF_TEXT),
        person_name="Jan Inny",
        rules=_rules(proof__name_match="off"),
    )
    assert not quiet.warn


def test_zly_miesiac_i_brak_podpisu_blokuja():
    assert _eval(parse_pdf_text(PDF_TEXT), month="2026-11").blocking
    assert _eval(parse_pdf_text(PDF_TEXT), signatures=[]).blocking
    other_issuer = [SignatureInfo(True, True, "Inny Urząd CA", None, None, None)]
    assert _eval(parse_pdf_text(PDF_TEXT), signatures=other_issuer).blocking
    broken = [
        SignatureInfo(
            False, True, "Fortis Bank Polska S.A. Subordinate CA", None, None, None
        )
    ]
    assert _eval(parse_pdf_text(PDF_TEXT), signatures=broken).blocking


def test_nadgodziny_bez_maila_blokuja():
    assert _eval(parse_pdf_text(PDF_TEXT), has_mail=False).blocking


def test_sumy_niezgodne_z_godzinami_blokuja():
    p = parse_pdf_text(PDF_TEXT.replace("SUMA: 21,7500", "SUMA: 22,0000"))
    r = _eval(p)
    assert r.blocking
    assert _states(r)["Sumy MD nie zgadzają się z godzinami"] == "fail"


def test_limit_godzin_w_dniu():
    r = _eval(parse_pdf_text(PDF_TEXT), rules=_rules())
    assert not r.blocking
    tight = rules_catalog.effective(
        {"fields.day_limit": {"level": "block", "params": {"hours": "10"}}}
    )
    assert _eval(parse_pdf_text(PDF_TEXT), rules=tight, has_mail=True).blocking


def test_brak_id_product_blokuje():
    p = parse_pdf_text(PDF_TEXT)
    stripped = ParsedRcp(
        **{
            **p.__dict__,
            "summary": tuple(
                SummaryRow(r.label, r.md, None, r.cmdb) for r in p.summary
            ),
        }
    )
    assert _eval(stripped).blocking


def test_excel_wymaga_maila_gdy_regula_wlaczona():
    p = parse_xlsx_rows(
        _sheet([[None, "development", 7, None, None, "EBI", None, "SX03098"]])
    )
    assert not _eval(p, mime=XLSX, signatures=[], has_mail=True).warn
    assert _eval(p, mime=XLSX, signatures=[], has_mail=False).warn
    no_excel = _rules(proof__excel_with_mail="off")
    assert _eval(p, mime=XLSX, signatures=[], rules=no_excel).blocking


def test_plik_spoza_szablonu_to_uwaga_bez_md():
    r = _eval(None)
    assert r.md_regular is None and r.warn and not r.blocking


# ── Typy plików (E2.0) ───────────────────────────────────────────────────────


def _xlsx_bytes(with_macro: bool = False) -> bytes:
    workbook = openpyxl.Workbook()
    workbook.active.append(["Rozliczenie czasu pracy"])
    buffer = io.BytesIO()
    workbook.save(buffer)
    if not with_macro:
        return buffer.getvalue()
    import zipfile

    out = io.BytesIO()
    with (
        zipfile.ZipFile(io.BytesIO(buffer.getvalue())) as src,
        zipfile.ZipFile(out, "w") as dst,
    ):
        for item in src.infolist():
            dst.writestr(item, src.read(item))
        dst.writestr("xl/vbaProject.bin", b"x")
    return out.getvalue()


def test_typy_plikow_rozliczen():
    assert documents.check_settlement_file(_xlsx_bytes())[0] == documents.XLSX_MIME
    eml = b"From: a@b.pl\r\nTo: c@d.pl\r\nSubject: Akceptacja\r\nDate: Mon, 2 Nov 2026 10:00:00 +0100\r\nMIME-Version: 1.0\r\n\r\nOK"
    assert documents.check_settlement_file(eml)[0] == documents.EML_MIME
    msg = (
        b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"
        + b"\x00" * 100
        + "__substg1.0_0037001F".encode("utf-16-le")
    )
    assert documents.check_settlement_file(msg)[0] == documents.MSG_MIME
    assert documents.check_settlement_file(b"%PDF-1.7 test")[0] == "application/pdf"


def test_arkusz_z_makrami_i_zly_typ_odrzucone():
    with pytest.raises(documents_store.FileRejected):
        documents.check_settlement_file(_xlsx_bytes(with_macro=True))
    with pytest.raises(documents_store.FileRejected, match="XLSX"):
        documents.check_settlement_file(b"zwykly tekst bez naglowkow")
    ole_doc = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"\x00" * 200
    with pytest.raises(documents_store.FileRejected):
        documents.check_settlement_file(ole_doc)


@pytest.mark.asyncio
async def test_odczyt_rcp_dziala_w_petli_async(monkeypatch):
    """Na kopii 09.11 podpis czytał się poprawnie w skrypcie, a w ścieżce
    `documents.store` (działająca pętla zdarzeń) wychodził „PDF bez podpisu”:
    synchroniczny walidator pyHanko odpala własną pętlę. Odczyt idzie w wątku."""

    import asyncio

    from app.services.client_settlements import service

    calls: list[bool] = []

    def fake_read(content: bytes, mime: str):
        try:
            asyncio.get_running_loop()
            calls.append(False)
        except RuntimeError:
            calls.append(True)
        return parse_pdf_text(PDF_TEXT), SIGNED

    monkeypatch.setattr(service, "_read_rcp", fake_read)
    parsed, signatures = await service.read_rcp(b"%PDF-", "application/pdf")
    assert calls == [True]
    assert parsed is not None and signatures == SIGNED
