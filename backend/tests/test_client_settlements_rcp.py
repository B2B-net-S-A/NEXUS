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


def test_arkusz_z_makrami_przyjety_jako_xlsm_a_zly_typ_odrzucony():
    """Time Sheet PKO to szablon .xlsm (E6.1): przyjmujemy go jako osobny typ,
    czytamy same wartości, makr nie uruchamiamy."""

    mime, _digest = documents.check_settlement_file(_xlsx_bytes(with_macro=True))
    assert mime == documents.XLSM_MIME
    assert documents.relative_path("7", "abc", mime).endswith(".xlsm")
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


# ── Puste „OPIS PRAC” i arkusz z samym tytułem (próba IX–XI 2026) ────────────

EMPTY_SUMMARY_PDF = """Rozliczenie czasu pracy
Rozliczenie 2026-09-30 Ilość dni przepracowanych 13,0
Check OK
Nazwisko Testowa
Imię Anna
Godziny w tygodniu 8,0 8,0 8,0 8,0 0,0 0,0 8,0 0,0 0,0 0,0 0,0 0,0 0,0 0,0 0,0 0,0 0,0 0,0 0,0 0,0 8,0 8,0 8,0 8,0 8,0 0,0 0,0 8,0 8,0 8,0 0,0 104,0 13,00
SUMA 8,0 8,0 8,0 8,0 0,0 0,0 8,0 0,0 0,0 0,0 0,0 0,0 0,0 0,0 0,0 0,0 0,0 0,0 0,0 0,0 8,0 8,0 8,0 8,0 8,0 0,0 0,0 8,0 8,0 8,0 0,0 104,0 13,00
Koszty Delegacji 1 2 3
SUMA 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0,00
OPIS PRAC MDs No ID PRODUCT Kod aplikacji CMDB Koszty wyjazdu
Godziny dodatkowe w tygodniu 0,00
SUMA: 13,0000
"""


def test_puste_opis_prac_bierze_md_z_sumy_zamiast_zera():
    """RCP BNP z wypełnionymi godzinami i sumą 13 MD, bez wierszy opisu: NEXUS
    liczył 0 MD i zdejmował 0 z zamówienia (faktura do klienta: 13 MD)."""

    p = parse_pdf_text(EMPTY_SUMMARY_PDF)
    assert p is not None and p.summary == ()
    r = _eval(p, month="2026-09")
    assert r.md_regular == D("13.0000")
    assert not r.md_extra
    # Brak ID PRODUCT nadal widać jako uwagę według reguł klienta.
    assert _states(r)["Brak ID PRODUCT w podsumowaniu"] == "fail"


def test_arkusz_z_samym_tytulem_rcp_to_brak_odczytu():
    """Szablon innego klienta z tytułem „Rozliczenie czasu pracy”, ale bez
    układu BNP: NEXUS dawał 0 MD ze statusem „ok”. Ma być „nie rozpoznano”,
    żeby spróbować innych odczytów i oddać MD Finansom."""

    rows = [
        [None, "Rozliczenie czasu pracy"],
        [None, "Imię i nazwisko", "Anna Testowa"],
        [None, "Data", "Godziny", "Opis"],
        *[[None, f"2026-10-{d:02d}", 8, "praca"] for d in range(1, 23)],
    ]
    assert parse_xlsx_rows(rows) is None


# ── Data „Rozliczenie” w formatach z poczty (próba IX–X 2026) ────────────────


@pytest.mark.parametrize(
    ("raw", "month"),
    [
        ("30/09/2026", "2026-09"),
        ("31.10.2026", "2026-10"),
        # Excel z ustawieniami amerykańskimi: M/D/RR.
        ("10/30/26", "2026-10"),
        ("2026-10-01", "2026-10"),
    ],
)
def test_pdf_miesiac_z_daty_w_formacie_z_poczty(raw, month):
    """RCP z poczty mają datę „Rozliczenie” DD/MM/RRRR, DD.MM.RRRR albo M/D/RR.
    NEXUS czytał tylko RRRR-MM-DD i blokował rozliczenie „RCP za inny miesiąc —
    brak pola Rozliczenie”, choć MD były zgodne z fakturą."""

    text = PDF_TEXT.replace("Rozliczenie 2026-10-01", f"Rozliczenie {raw}")
    p = parse_pdf_text(text)
    assert p is not None and p.month == month
    r = _eval(p, month=month)
    assert _states(r)[f"Miesiąc z RCP: {month}"] == "ok"
    assert not r.blocking


@pytest.mark.parametrize("raw", ["01/02/26", "05.06.2026", "31/31/2026"])
def test_pdf_dwuznaczna_albo_zla_data_to_brak_miesiaca(raw):
    """01/02/26 to 1 lutego albo 2 stycznia: nie zgadujemy, Finanse widzą
    „brak pola Rozliczenie” jak dotąd."""

    p = parse_pdf_text(PDF_TEXT.replace("Rozliczenie 2026-10-01", f"Rozliczenie {raw}"))
    assert p is not None and p.month is None


def test_xlsx_miesiac_z_daty_jako_tekst():
    rows = _sheet([[None, "Prace", 7, None, None, "ORD", None, "SX1"]])
    rows[1][2] = "30/09/2026"
    p = parse_xlsx_rows(rows)
    assert p is not None and p.month == "2026-09"


# ── Warianty szablonu i odstępstwa z poczty BNP (próba IX–X 2026) ────────────


def test_pdf_nowy_tytul_wykaz_godzin_ten_sam_uklad():
    """BNP od IX 2026 drukuje „Wykaz godzin w ramach zleconych usług” zamiast
    „Rozliczenie czasu pracy”, reszta układu bez zmian. NEXUS nie rozpoznawał
    szablonu i 16 RCP czekało bez MD."""

    text = PDF_TEXT.replace(
        "Rozliczenie czasu pracy", "Wykaz godzin w ramach zleconych usług", 1
    )
    p = parse_pdf_text(text)
    assert p is not None and p.month == "2026-10"
    assert p.md_regular == D("17") and p.md_extra == D("4.75")


EN_WEEK = "8,0 8,0 8,0 8,0 0,0 0,0 8,0 8,0 8,0 8,0 8,0 0,0 0,0 8,0 8,0 8,0 0,0 8,0 0,0 0,0 8,0 8,0 8,0 8,0 8,0 0,0 0,0 8,0 8,0 0,0 0,0"

EN_PDF = f"""Rozliczenie czasu pracy
Month 2026-09-30 Number of working days 20,0
Check OK
Client company B2B Network
Last name Testowa
First name Anna
Role Konsultant
Order number ZAM_1_2026
1 2 3 4 5 6 7 8 9 10 11 12 13 14 15 16 17 18 19 20 21 22 23 24 25 26 27 28 29 30 1 Total MD's
Working days hours {EN_WEEK} 160,0 20,00
Saturday hours 0,0 0,0
Sunday hours 0,0 0,0
RAZEM {EN_WEEK} 160,0 20,00
Koszty Delegacji 1 2 3 4 5 6 7 8 9 10 11 12 13 14 15 16 17 18 19 20 21 22 23 24 25 26 27 28 29 30 1 Total
RAZEM 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0
WORK SUMMARY
Work Description* MDs No PRODUCT ID Delegacja (koszty
Prace utrzymaniowe w produkcie 20,0000 NTO
Przykładowy opis prac np.: testy, zarządzanie,
administrowanie 0,0000 np. EBM
Delegacja 0,0000 ID produktu (np. OER) 0
Nadgodziny w tygodniu 0,0000 ID produktu (np. OER)
Total 20,0000
Przełożony
"""


def test_pdf_angielska_wersja_szablonu():
    """Wersja angielska: Month, Last/First name, Working days hours, RAZEM,
    WORK SUMMARY, Total. Tytuł pasował, etykiety nie: 2 RCP bez MD."""

    p = parse_pdf_text(EN_PDF)
    assert p is not None
    assert p.month == "2026-09"
    assert (p.first_name, p.last_name) == ("Anna", "Testowa")
    assert p.order_number == "ZAM_1_2026"
    assert p.total_hours == D("160.0") and p.declared_md == D("20.00")
    assert p.summary_total == D("20.0000")
    assert p.md_regular == D("20") and p.md_extra == D("0")
    assert [r.product for r in p.summary] == ["NTO"]
    r = _eval(p, month="2026-09")
    assert r.md_regular == D("20") and not r.blocking


@pytest.mark.parametrize(
    ("raw", "month"),
    [("wrzesień 2026", "2026-09"), ("Październik 2026", "2026-10")],
)
def test_pdf_miesiac_slownie(raw, month):
    """„Rozliczenie wrzesień 2026”: miesiąc wpisany słownie blokował rozliczenie
    („RCP za inny miesiąc — brak pola Rozliczenie”) przy MD zgodnych z fakturą."""

    p = parse_pdf_text(PDF_TEXT.replace("Rozliczenie 2026-10-01", f"Rozliczenie {raw}"))
    assert p is not None and p.month == month


DELEGATION_PDF = PDF_TEXT.replace(
    """Prace DevOps 17,0000 ORD SX01929
Przykładowy opis prac np.: testy, zarządzanie,
Wyjazd służbowy 0,0000
Godziny dodatkowe w tygodniu 2,7500 ORD SX01929
Godziny dodatkowe w sobotę 1,0000 ORD SX01929
Godziny dodatkowe w niedzielę 1,0000 ORD SX01929
SUMA: 21,7500""",
    """Przykładowy opis prac np.: development 21,7500 GCL SX05942 - Phoenix
Delegacja 718,00
SUMA: 21,7500""",
)


def test_pdf_wiersz_z_ogonem_i_kwota_delegacji():
    """Wiersz pracy z ogonem po kodzie CMDB wypadał z odczytu, a kwota delegacji
    „Delegacja 718,00” wchodziła jako MD: 718 MD zamiast 22 przy statusie „ok”."""

    p = parse_pdf_text(DELEGATION_PDF)
    assert p is not None
    assert p.md_regular == D("21.75")
    assert [(r.product, r.cmdb) for r in p.summary if not r.is_travel] == [
        ("GCL", "SX05942")
    ]
    assert any(r.is_travel and r.md == D("718.00") for r in p.summary)
    r = _eval(p)
    assert r.md_regular == D("21.75")


def test_pdf_liczba_w_opisie_to_nie_md():
    text = PDF_TEXT.replace("Prace DevOps 17,0000", "Release 2.5 wdrożenie 17,0000")
    p = parse_pdf_text(text)
    assert p is not None and p.md_regular == D("17")
    assert p.summary[0].label == "Release 2.5 wdrożenie"


def test_wiersze_niesumujace_sie_do_sumy_biora_sume_i_ostrzegaja():
    """Nachodzące napisy w PDF: z wierszy 15 MD, „SUMA: 22”, godziny 176. NEXUS
    brał 15 MD bez uwagi. Teraz MD z SUMA i uwaga do sprawdzenia podziału."""

    text = PDF_TEXT.replace(
        "Prace DevOps 17,0000 ORD SX01929", "Prace DevOps 10,0000 ORD SX01929"
    )
    p = parse_pdf_text(text)
    assert p is not None and p.md_regular + p.md_extra == D("14.75")
    r = _eval(p)
    assert r.md_regular == D("21.7500") and not r.md_extra
    assert _states(r)["Wiersze opisu prac nie sumują się do SUMA"] == "warn"
    assert r.warn


def test_xlsx_nowy_tytul_i_angielskie_etykiety():
    rows = _sheet([[None, "Prace", 7, None, None, "ORD", None, "SX1"]])
    rows[0][2] = "Wykaz godzin w ramach zleconych usług"
    p = parse_xlsx_rows(rows)
    assert p is not None and p.md_regular == D("7")

    en = _sheet([[None, "Prace", 7, None, None, "ORD", None, "SX1"]])
    en[1][1] = "Month"
    en[2][1] = "Last name"
    en[3][1] = "First name"
    en[4][1] = "Order number"
    en[6][1] = "Working days hours"
    en[7][1] = "RAZEM"
    en[10] = [None, "Work Description*", "MDs No", None, None, "PRODUCT ID", None, None]
    en[-1] = [None, "Total", 7]
    p = parse_xlsx_rows(en)
    assert p is not None
    assert p.month == "2026-10" and (p.first_name, p.last_name) == ("Anna", "Testowa")
    assert p.total_hours == D("56") and p.declared_md == D("7")
    assert p.md_regular == D("7") and p.summary_total == D("7")
    assert [r.product for r in p.summary] == ["ORD"]


def test_pdf_suma_z_brakujacymi_dniami_daje_sume_godzin():
    """Puste dni wypadają z tekstu PDF: wiersz SUMA ma 32 albo 34 liczby zamiast 33.
    Cały wiersz przepadał i reguła blokowała „Nie da się policzyć sum MD” przy
    zgodnych MD (próba IX–X 2026, 7 RCP BNP)."""

    short = TOTAL.rsplit(" ", 1)[0]  # 30 dni zamiast 31
    p = parse_pdf_text(
        PDF_TEXT.replace(f"SUMA {TOTAL} 174,0 21,75", f"SUMA {short} 174,0 21,75")
    )
    assert p is not None
    assert p.total_hours == D("174.0") and p.declared_md == D("21.75")
    assert p.day_totals == ()
    r = _eval(p)
    assert _states(r)["Sumy MD policzone od nowa"] == "ok"


def test_koszty_delegacji_to_uwaga_z_opisem():
    """RCP z kosztami delegacji ma uwagę z tytułem, nie samą informację.

    Do 24.11.2026 silnik ustawiał uwagę, a zapisywał sprawdzenie jako
    informację, więc ekran pokazywał „Z uwagami” bez żadnego powodu.
    """
    import dataclasses

    parsed = dataclasses.replace(parse_pdf_text(PDF_TEXT), travel_total=D("450.00"))
    r = _eval(parsed)
    assert r.warn and not r.blocking
    warns = [c for g in r.groups for c in g["checks"] if c["state"] == "warn"]
    assert [c["title"] for c in warns] == ["Delegacja do sprawdzenia"]
    # Stały klucz: w „Przebiegu miesiąca” jedna grupa zamiast jednej na kwotę.
    assert warns[0]["rule"] == "travel.rcp_costs"
    assert "450 zł brutto" in warns[0]["detail"]
    assert "Faktury kosztów" in warns[0]["detail"]


def test_koszty_delegacji_z_akceptacja_do_dodatku_na_fakture():
    """Kwota z RCP i akceptacja klienta idą do dodatku na fakturę klienta
    (``extras.sync_from_rcp``); RCP bez kosztów nie daje nic."""
    import dataclasses

    from app.services.client_settlements.travel_acceptance import Verdict

    parsed = dataclasses.replace(parse_pdf_text(PDF_TEXT), travel_total=D("450.00"))
    assert _eval(parsed).travel_cost == (D("450.00"), False)
    other = Verdict(False, "Akceptacja kosztów na inną kwotę", "400 zł")
    assert _eval(parsed, travel=other).travel_cost == (D("450.00"), False)
    ok = Verdict(True, "Koszty delegacji w RCP podpisanym przez klienta", "x")
    accepted = _eval(parsed, travel=ok)
    assert accepted.travel_cost == (D("450.00"), True)
    assert _states(accepted)[ok.title] == "ok"
    assert _eval(parse_pdf_text(PDF_TEXT)).travel_cost is None
