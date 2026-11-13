"""Rozliczenia PKO (E6.1) i Velo (E6.2) bez bazy. Dane fikcyjne.

Odczyt Time Sheet z szablonu klienta w ``.xlsm`` (godziny [GG]:MM, miesiąc
z widocznego nagłówka, ukryta kolumna miesiąca tylko ostrzega), kontrola maila
akceptacji, mail jako HTML, rozpoznanie podpisanego arkusza zbiorczego
i protokołu po treści, limit MD z innymi klientami i stawka godzinowa.
"""

from __future__ import annotations

import io
import zipfile
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from types import SimpleNamespace

import openpyxl
import pytest

from app.services.client_settlements import (
    client_documents,
    consultant,
    mail_text,
    rcp_checks,
    rules_catalog,
    service,
    signoffs,
    timesheet_pko,
)

MONTH = "2026-10"


def _rules(**levels: str) -> dict:
    rules = rules_catalog.effective({})
    for key, level in levels.items():
        rules[key.replace("__", ".")]["level"] = level
    return rules


# ── Time Sheet PKO ───────────────────────────────────────────────────────────


def _old_template(month_cell: object = "czerwiec") -> list[list[object]]:
    """Szablon z kolumną „Liczba godzin realizacji usług <miesiąc> <rok>”."""

    rows: list[list[object]] = [[None] * 14 for _ in range(14)]
    rows[2][10:13] = ["Nazwa Firmy", "B2B.NET S.A.", "FIRMA PRZYKŁAD"]
    rows[3][10:13] = ["Nazwisko i Imię Kontraktora", "Testowa Ola", "Kowalski Jan"]
    rows[4][10:13] = ["Nr PZ", "PZ000001", "PZ999999"]
    rows[5][10:13] = ["Koordynator odbierający usługę (z banku)", "Koordynator A", "X"]
    rows.append(
        [
            None,
            None,
            "Lp.",
            "Miesiąc realizacji usług",
            "Nazwa firmy",
            "Imię i nazwisko Kontraktora",
            "Nr PZ",
            None,
            "Rozliczający",
            None,
            "Numer projektu / formacji",
            "Numer zadania projektowego / Tematu formacji",
            "Rezultat/dostarczona funkcjonalność",
            "Liczba godzin realizacji usług październik 2026",
        ]
    )
    rows.append(
        [
            None,
            None,
            1,
            month_cell,
            None,
            None,
            None,
            None,
            0,
            0,
            "J0001",
            "T-1",
            "Testy",
            timedelta(days=2, hours=16),
        ]
    )
    rows.append(
        [
            None,
            None,
            2,
            month_cell,
            None,
            None,
            None,
            None,
            0,
            0,
            "J0001",
            "T-2",
            "Analiza",
            timedelta(days=4, hours=16),
        ]
    )
    rows.append([None, None, 3] + [None] * 11)
    rows.append([None] * 12 + ["Całkowity czas", timedelta(days=7, hours=8)])
    # Wiersze „Przykład” pod tabelą nie są pracą konsultanta.
    rows.append([None] * 10 + ["Przykład"] + [None] * 3)
    rows.append([None] * 10 + ["K0094", "T-356", None, timedelta(days=3, hours=8)])
    return rows


def test_stary_szablon_miesiac_z_naglowka_a_ukryta_kolumna_ostrzega():
    parsed = timesheet_pko.parse_rows(_old_template(), hidden_columns=["D", "E"])
    assert parsed is not None
    assert parsed.month == MONTH
    assert parsed.consultant == "Testowa Ola"
    assert parsed.coordinator == "Koordynator A"
    assert parsed.total_hours == Decimal("176.00")
    assert parsed.declared_total == Decimal("176.00")
    assert len(parsed.entries) == 2
    assert parsed.month_column_hidden

    result = timesheet_pko.evaluate(
        parsed,
        month=MONTH,
        person_name="Ola Testowa",
        rules=_rules(proof__month="block", proof__name_match="warn"),
        working_days=22,
    )
    checks = {c["title"]: c for g in result.groups for c in g["checks"]}
    assert result.md_regular == Decimal("22.000")
    assert checks["Miesiąc z nagłówka: październik 2026"]["state"] == "ok"
    hidden = checks["W ukrytej kolumnie „Miesiąc realizacji usług” jest: czerwiec"]
    assert hidden["state"] == "warn" and "rule" not in hidden
    assert not result.blocking  # rozbieżność nigdy nie blokuje
    assert checks["Imię i nazwisko jak w kontrakcie"]["state"] == "ok"


def test_ukryta_kolumna_zgodna_nie_ostrzega_a_inny_naglowek_blokuje():
    same = timesheet_pko.parse_rows(_old_template("październik"))
    result = timesheet_pko.evaluate(
        same, month=MONTH, person_name="Ola Testowa", rules=_rules(), working_days=22
    )
    assert not any("kolumnie" in c["title"] for g in result.groups for c in g["checks"])

    other = timesheet_pko.evaluate(
        same,
        month="2026-11",
        person_name="Ola Testowa",
        rules=_rules(proof__month="block"),
        working_days=20,
    )
    assert other.blocking


def test_nowy_szablon_z_dniami_miesiac_z_pierwszej_daty_i_limit_dnia():
    header = [
        None,
        None,
        "Lp.",
        "Miesiąc rozliczenia",
        "Nazwa firmy",
        None,
        None,
        None,
        None,
        None,
        "Numer projektu / formacji [FINANSUJĄCY]",
        "Numer zadania projektowego",
        "RAZEM 2026 październik",
    ]
    header += [datetime(2026, 10, d) for d in range(1, 4)]
    rows = [
        [None] * 10 + ["Nazwisko i Imię Kontraktora", "Testowa Ola"],
        header,
        [
            None,
            None,
            1,
            datetime(2026, 10, 31),
            None,
            None,
            None,
            None,
            None,
            None,
            "J1",
            "T1",
            timedelta(hours=26),
            time(8, 0),
            "4:0",
            None,
        ],
        [
            None,
            None,
            2,
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            "J1",
            "T2",
            None,
            None,
            timedelta(hours=14),
            "6:30",
        ],
        [None] * 11 + ["Całkowity czas", timedelta(days=1, hours=22, minutes=30)],
    ]
    parsed = timesheet_pko.parse_rows(rows)
    assert parsed.month == MONTH
    assert parsed.total_hours == Decimal("46.50")  # 26 + (14 + 6,5) z dni
    totals = parsed.day_totals()
    assert totals[date(2026, 10, 2)] == Decimal("18.00")
    result = timesheet_pko.evaluate(
        parsed,
        month=MONTH,
        person_name="Ola Testowa",
        rules=_rules(fields__day_limit="block"),
        working_days=22,
    )
    titles = {c["title"]: c["state"] for g in result.groups for c in g["checks"]}
    assert titles["Najwięcej w jednym dniu: 18 h"] == "ok"
    assert not any("kolumnie" in t for t in titles)  # data w kolumnie = ten miesiąc


def test_czas_gg_mm_z_komorek():
    assert timesheet_pko.duration_hours(timedelta(days=7, hours=8)) == Decimal("176.00")
    assert timesheet_pko.duration_hours("4:0") == Decimal("4.00")
    assert timesheet_pko.duration_hours("7:30") == Decimal("7.50")
    assert timesheet_pko.duration_hours(time(7, 45)) == Decimal("7.75")
    assert timesheet_pko.duration_hours("8,5") == Decimal("8.50")
    assert timesheet_pko.duration_hours(None) is None
    assert timesheet_pko.duration_hours("brak") is None


def _xlsm(rows: list[list[object]], hidden: tuple[str, ...]) -> bytes:
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Timesheet"
    for row in rows:
        ws.append(row)
    for row in ws.iter_rows():
        for cell in row:
            if isinstance(cell.value, timedelta):
                cell.number_format = "[hh]:mm"
    for letter in hidden:
        ws.column_dimensions[letter].hidden = True
    dictionary = wb.create_sheet("SŁOWNIK")
    dictionary.sheet_state = "hidden"
    dictionary.append(["Lp.", "Numer projektu"])  # ukryty arkusz nie jest Time Sheet
    buffer = io.BytesIO()
    wb.save(buffer)
    out = io.BytesIO()
    with (
        zipfile.ZipFile(io.BytesIO(buffer.getvalue())) as src,
        zipfile.ZipFile(out, "w") as dst,
    ):
        for item in src.infolist():
            dst.writestr(item, src.read(item))
        dst.writestr("xl/vbaProject.bin", b"makro, ktorego nikt nie uruchamia")
    return out.getvalue()


def test_plik_xlsm_czyta_wartosci_i_ukryte_kolumny():
    from app.services.consultant_portal import documents

    content = _xlsm(_old_template(), hidden=("D", "E", "F"))
    mime, _ = documents.check_settlement_file(content)
    assert mime == timesheet_pko.XLSM
    parsed = timesheet_pko.parse(content, mime)
    assert parsed is not None
    assert parsed.month == MONTH
    assert parsed.month_column == ("????-06",)
    assert parsed.month_column_hidden
    assert parsed.total_hours == Decimal("176.00")
    # Time Sheet Boscha (inny szablon) nie wchodzi w ten odczyt.
    assert timesheet_pko.parse(content, "application/pdf") is None


# ── Akceptacja mailem ────────────────────────────────────────────────────────


THREAD = """Od: Akceptujący <akceptujacy@klient.example>
Data: 02.11.2026 09:56
Temat: RE: Odbiór usług za 10.2026
Cześć,
Potwierdzam godziny za miesiąc październik
Pozdrawiam

From: Konsultant <konsultant@klient.example>
Sent: Monday, November 2, 2026 9:54 AM
Subject: Odbiór usług za 10.2026
Proszę o potwierdzenie odbioru usług zrealizowanych w 10.2026. Łączna liczba godzin realizacji usług: 176.
"""


def _mail(body: str, subject: str = "RE: Odbiór usług") -> mail_text.Mail:
    return mail_text.Mail(subject=subject, body=body)


def test_akceptacja_godziny_w_cytowanej_prosbie_wystarczaja():
    verdict = mail_text.judge(
        [_mail(THREAD)], month=MONTH, hours=Decimal("176"), md=None
    )
    assert verdict.ok, verdict
    assert verdict.title == "Akceptacja: 176 h za październik 2026"


@pytest.mark.parametrize(
    ("body", "title"),
    [
        ("Potwierdzam usługi za październik.", "Akceptacja bez liczby godzin lub MD"),
        (
            THREAD.replace("10.2026", "09.2026").replace("październik", "wrzesień"),
            "Akceptacja za inny miesiąc",
        ),
        (
            THREAD.replace("Potwierdzam", "Proszę o"),
            "Mail bez odpowiedzi akceptującego",
        ),
        (
            THREAD.replace("176.", "160."),
            "Inna liczba godzin w akceptacji niż w Time Sheet",
        ),
    ],
)
def test_akceptacja_do_poprawy(body: str, title: str):
    verdict = mail_text.judge([_mail(body)], month=MONTH, hours=Decimal("176"), md=None)
    assert not verdict.ok
    assert verdict.title == title


def test_data_wyslania_maila_nie_jest_miesiacem_rozliczenia():
    body = "Data: 02.11.2026 09:56\nPotwierdzam 176 h"
    found = mail_text.read_acceptance(body, MONTH)
    assert "2026-11" not in found.months
    assert not mail_text.judge([_mail(body)], month=MONTH, hours=None, md=None).ok


def test_md_zamiast_godzin_i_brak_maila():
    ok = mail_text.judge(
        [_mail("Akceptuję 22 MD za październik 2026")],
        month=MONTH,
        hours=None,
        md=Decimal("22"),
    )
    assert ok.ok
    missing = mail_text.judge([], month=MONTH, hours=Decimal("176"), md=None)
    assert missing.title == "Brak maila z akceptacją"


def test_eml_na_html_bez_tresci_html_nadawcy():
    eml = (
        "From: Akceptujacy <a@klient.example>\r\nTo: k@klient.example\r\n"
        "Subject: RE: Odbior uslug za 10.2026\r\nDate: Mon, 2 Nov 2026 09:56:00 +0100\r\n"
        "MIME-Version: 1.0\r\nContent-Type: text/html; charset=utf-8\r\n\r\n"
        "<p>Potwierdzam 176 h za 10.2026</p><script>alert(1)</script>"
    ).encode()
    mail = mail_text.read(eml, mail_text.EML)
    assert mail is not None and "Potwierdzam 176 h" in mail.body
    html = mail_text.to_html(mail)
    assert "<script" not in html and "alert(1)" not in html
    assert "RE: Odbior uslug za 10.2026" in html and "<th>Od:</th>" in html
    assert mail_text.html_name(mail, "x") == "RE_Odbior_uslug_za_10.2026.html"
    assert mail_text.read(b"to nie jest mail", mail_text.MSG) is None


def test_zadanie_popraw_akceptacje_w_panelu_konsultanta():
    checks = [
        {
            "title": "Akceptacja",
            "checks": [
                {
                    "state": "fail",
                    "title": "Akceptacja bez liczby godzin lub MD",
                    "todo": "Popraw akceptację",
                }
            ],
        },
        {"title": "Zamówienie", "checks": [{"state": "fail", "title": "ukryte"}]},
    ]
    visible = consultant._visible_checks(checks, with_todo=True)
    assert visible == [
        {
            "state": "fail",
            "title": "Akceptacja bez liczby godzin lub MD",
            "todo": "Popraw akceptację",
        }
    ]
    assert "todo" not in consultant._visible_checks(checks)[0]


# ── Limit MD i stawki ────────────────────────────────────────────────────────


def test_limit_md_liczy_tez_innych_klientow():
    result = rcp_checks.ProofResult(md_regular=None, md_extra=None)
    group = rcp_checks._Group(
        result, _rules(fields__md_month_limit="warn"), "Pola i sumy"
    )
    timesheet_pko.month_limit(group, Decimal("17"), 22, Decimal("17"))
    group.close()
    check = result.groups[0]["checks"][0]
    assert check["state"] == "warn"
    assert check["title"] == "34 MD przy 22 dniach roboczych"
    assert "u innych 17 MD" in check["detail"]


def test_stawka_godzinowa_bez_stawek_md():
    hourly = SimpleNamespace(
        rate_unit="hourly",
        rate_client=Decimal("100"),
        rate_candidate=Decimal("60"),
        rate_client_currency="PLN",
        md_rate_cost=None,
        md_rate_revenue=None,
    )
    assert service.md_rates(hourly) == (Decimal("480"), Decimal("800"))
    assert client_documents.hourly_rate(hourly) == Decimal("100")
    daily = SimpleNamespace(
        rate_unit="daily",
        rate_client=None,
        md_rate_revenue=Decimal("1200"),
        md_rate_cost=Decimal("900"),
    )
    assert service.md_rates(daily) == (Decimal("900"), Decimal("1200"))
    assert client_documents.hourly_rate(daily) == Decimal("150")


def test_numer_zamowienia_z_tytulu_linii_i_rola_z_rekrutacji():
    line = SimpleNamespace(title="Zamówienie nr 9001/2026")
    assert client_documents.order_number(line, "GRUPA") == "9001/2026"
    assert (
        client_documents.order_number(SimpleNamespace(title="9002/2026"), None)
        == "9002/2026"
    )
    assert (
        client_documents.order_number(SimpleNamespace(title="linia MD"), "GRUPA")
        == "GRUPA"
    )
    assert (
        client_documents._role("Tester Manualny Middle (ZOB-1234)")
        == "Tester Manualny Middle"
    )
    assert (
        client_documents._role("AI Engineer MID (ZOB-2) - 3.iteracja")
        == "AI Engineer MID"
    )
    assert client_documents._role("Inżynier DevSecOps (ZOB-2688) - Senior") == (
        "Inżynier DevSecOps Senior"
    )


# ── Dokumenty dla klienta ────────────────────────────────────────────────────


def _person(
    name: str, signer: str, md: str, hours: str | None = None
) -> client_documents.Person:
    return client_documents.Person(
        contract_id=hash(name) % 1000,
        name=name,
        status="accepted",
        settlement=None,
        order_number="1000/2026",
        role="Tester",
        hours=Decimal(hours) if hours else None,
        md=Decimal(md),
        rate_hour=Decimal("100"),
        rate_day=Decimal("900"),
        period=(date(2026, 10, 1), date(2026, 10, 31)),
        signer=signer,
    )


def test_protokol_ma_kolumny_wzoru_i_kwote_z_godzin():
    rows = [
        _person("Ola Testowa", "x", "22", hours="176"),
        _person("Jan Próbny", "x", "17", hours="136"),
    ]
    html = client_documents.protocol_html(
        header="Załącznik do umowy – wzór protokołu odbioru",
        client_name="Klient Testowy",
        month=MONTH,
        rows=rows,
    )
    for column in (
        "Numer",
        "Imię i Nazwisko",
        "Rola/profil",
        "Numer zamówienia",
        "Stawka za godzinę netto",
        "Liczba godzin przepracowanych",
        "Kwota netto",
    ):
        assert column in html
    assert "Od 01.10.2026 do 31.10.2026" in html
    assert "17 600,00 zł" in html and "13 600,00 zł" in html
    assert "Podpis pracownika Klient Testowy" in html


def test_arkusze_per_podpisujacy_a_bez_podpisujacego_na_koncu():
    people = [
        _person("Ola Testowa", "Podpisujący B", "22"),
        _person("Jan Próbny", "Podpisujący A", "20,5".replace(",", ".")),
        _person("Ewa Nowa", client_documents.NO_SIGNER, "19"),
        _person("Adam Drugi", "Podpisujący A", "17"),
    ]
    for p in people:
        p.settlement = SimpleNamespace(checks=[])
    groups = client_documents._groups(people)
    assert list(groups) == [
        "Podpisujący A",
        "Podpisujący B",
        client_documents.NO_SIGNER,
    ]
    assert [p.name for p in groups["Podpisujący A"]] == ["Jan Próbny", "Adam Drugi"]
    html = client_documents.sheet_html(
        signer="Podpisujący A", rows=groups["Podpisujący A"], with_amounts=False
    )
    assert "Liczba MD" in html and "Stawka" not in html and "20,5" in html
    final = client_documents.sheet_html(signer="", rows=people, with_amounts=True)
    assert "Wartość" in final and "18 450,00 zł" in final  # 20,5 × 900


# ── Podpisany arkusz i protokół od klienta ───────────────────────────────────


OUR_SHEET = """Zlecenie od Zlecenie do
Nazwisko i imię Rodzaj kompetencji (profil) Liczba MD
(dd-mm-rrrr) (dd-mm-rrrr)
Ola Testowa Starszy Programista 1.10.2026 31.10.2026 19
Jan Próbny Programista 1.10.2026 31.10.2026 20,5
"""
BANK_SHEET = """Dostawca B2B.NET
Nazwisko Imię Stanowisko Okres od: Okres do: MD.
PRÓBNY JAN STARSZY INŻYNIER TESTÓW 2026-10-01 2026-10-31 20,00
Suma końcowa 2026-10-01 2026-10-31 20,00
"""
PROTOCOL = """PROTOKÓŁ ODBIORU
FIRMA: B2B.net S.A
OKRES ROZLICZENIOWY: Od 01.10.2026 do 31.10.2026
1 Ola Testowa Tester Middle 9003/2026 100,00 zł 176 17 600,00 zł
"""


def test_arkusz_rozpoznany_po_tresci_nasz_wzor_i_wzor_banku():
    kind, month, rows = signoffs.read_text(OUR_SHEET)
    assert (kind, month) == (signoffs.SHEET, MONTH)
    assert rows[1].md == Decimal("20.5")
    assert rcp_checks.name_tokens("Jan Próbny") <= rows[1].tokens

    kind, month, rows = signoffs.read_text(BANK_SHEET)
    assert (kind, month, len(rows)) == (signoffs.SHEET, MONTH, 1)  # bez „Suma końcowa”
    assert rows[0].md == Decimal("20.00")
    assert rcp_checks.name_tokens("Jan Próbny") <= rows[0].tokens

    kind, month, _rows = signoffs.read_text(PROTOCOL)
    assert (kind, month) == (signoffs.PROTOCOL, MONTH)
    assert signoffs.read_text("Faktura VAT nr 1/10/2026") is None


def _plain_pdf(lines: list[str]) -> bytes:
    """Najprostszy PDF z tekstem (bez weasyprint i bibliotek systemowych)."""

    stream = (
        "BT /F1 9 Tf 40 800 Td 12 TL "
        + " ".join(
            "(" + line.replace("\\", "").replace("(", "").replace(")", "") + ") '"
            for line in lines
        )
        + " ET"
    )
    objects = [
        "<< /Type /Catalog /Pages 2 0 R >>",
        "<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] "
        "/Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>",
        "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        f"<< /Length {len(stream)} >>\nstream\n{stream}\nendstream",
    ]
    out = b"%PDF-1.7\n"
    offsets = []
    for index, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += f"{index} 0 obj\n{body}\nendobj\n".encode("latin-1")
    xref = len(out)
    out += f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode()
    for offset in offsets:
        out += f"{offset:010d} 00000 n \n".encode()
    out += (
        f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n"
    ).encode()
    return out


def _signed_pdf(lines: list[str], signers: int) -> bytes:
    from asn1crypto import keys as asn1_keys
    from asn1crypto import x509 as asn1_x509
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.x509.oid import NameOID
    from pyhanko.pdf_utils.incremental_writer import IncrementalPdfFileWriter
    from pyhanko.sign import signers as pyhanko_signers
    from pyhanko.sign.fields import SigFieldSpec, append_signature_field

    content = _plain_pdf(lines)
    for index in range(signers):
        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        name = x509.Name(
            [x509.NameAttribute(NameOID.COMMON_NAME, f"Podpisujacy {index}")]
        )
        cert = (
            x509.CertificateBuilder()
            .subject_name(name)
            .issuer_name(name)
            .public_key(key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(datetime(2026, 1, 1))
            .not_valid_after(datetime(2030, 1, 1))
            .sign(key, hashes.SHA256())
        )
        signer = pyhanko_signers.SimpleSigner(
            signing_cert=asn1_x509.Certificate.load(
                cert.public_bytes(serialization.Encoding.DER)
            ),
            signing_key=asn1_keys.PrivateKeyInfo.load(
                key.private_bytes(
                    serialization.Encoding.DER,
                    serialization.PrivateFormat.PKCS8,
                    serialization.NoEncryption(),
                )
            ),
            cert_registry=None,
        )
        writer = IncrementalPdfFileWriter(io.BytesIO(content), strict=False)
        append_signature_field(writer, SigFieldSpec(f"Podpis{index}"))
        out = io.BytesIO()
        pyhanko_signers.sign_pdf(
            writer,
            pyhanko_signers.PdfSignatureMetadata(field_name=f"Podpis{index}"),
            signer=signer,
            output=out,
        )
        content = out.getvalue()
    return content


def test_podpisany_pdf_arkusza_i_protokol_wymaga_dwoch_podpisow():
    """Prawdziwy podpis pyHanko na PDF-ie bez polskich znaków w czcionce."""

    sheet = [
        "Nazwisko i imie Rodzaj kompetencji (profil) Zlecenie od Zlecenie do Liczba MD",
        "Ola Testowa Tester 01-10-2026 31-10-2026 19",
        "Jan Probny Tester 01-10-2026 31-10-2026 20,5",
    ]
    unsigned = signoffs.recognize(_signed_pdf(sheet, 0), signoffs.PDF)
    assert unsigned is not None and unsigned.kind == signoffs.SHEET
    assert not unsigned.signers  # wydruk bez podpisu niczego nie zmienia

    signed = signoffs.recognize(_signed_pdf(sheet, 1), signoffs.PDF)
    assert signed.complete and signed.month == MONTH
    assert signed.signers == ("Podpisujacy 0",)
    assert [r.md for r in signed.rows] == [Decimal("19"), Decimal("20.5")]

    protocol = [
        "PROTOKOL ODBIORU",
        "OKRES ROZLICZENIOWY: Od 01.10.2026 do 31.10.2026",
        "1 Ola Testowa Tester 1000/2026 100,00 176 17 600,00",
    ]
    ours_only = signoffs.recognize(_signed_pdf(protocol, 1), signoffs.PDF)
    assert ours_only.kind == signoffs.PROTOCOL and not ours_only.complete
    both = signoffs.recognize(_signed_pdf(protocol, 2), signoffs.PDF)
    assert both.complete and both.month == MONTH


def test_rozpoznanie_podpisu_i_kompletu(monkeypatch):
    """Arkusz: wystarczy podpis klienta. Protokół: podpis spółki i klienta."""

    monkeypatch.setattr(signoffs, "_pdf_text", lambda content: content.decode())
    calls = {"n": 0}

    def fake_signatures(content: bytes) -> list:
        return [
            SimpleNamespace(intact=True, signer=f"P{i}", signed_at=None)
            for i in range(calls["n"])
        ]

    monkeypatch.setattr(signoffs, "signatures", fake_signatures)
    calls["n"] = 0
    assert not signoffs.recognize_pdf(OUR_SHEET.encode()).signers
    calls["n"] = 1
    sheet = signoffs.recognize_pdf(OUR_SHEET.encode())
    assert sheet.complete and sheet.signers == ("P0",)
    protocol = signoffs.recognize_pdf(PROTOCOL.encode())
    assert protocol.kind == signoffs.PROTOCOL and not protocol.complete
    calls["n"] = 2
    assert signoffs.recognize_pdf(PROTOCOL.encode()).complete


def test_znacznik_podpisu_zostaje_przy_przeliczeniu():
    checks = [{"title": "RCP", "checks": []}, {"remaining_after": "1.000"}]
    marked = signoffs.with_marker(checks, {"kind": "sheet", "complete": True})
    assert signoffs.is_complete(marked, signoffs.SHEET)
    assert not signoffs.is_complete(marked, signoffs.PROTOCOL)
    again = signoffs.with_marker(marked, signoffs.marker(marked))
    assert sum(1 for c in again if "signed" in c) == 1


def test_regula_dokumentu_wybiera_uklad():
    rules = _rules()
    rules["cl.client_document"] = {
        "level": "warn",
        "params": {"per": "podpisujący", "from": "2026-11"},
    }
    assert signoffs.document_rule(rules, MONTH) is None  # przed „od miesiąca”
    assert signoffs.document_rule(rules, "2026-11") == signoffs.SHEET
    rules["cl.client_document"]["params"]["per"] = "cały miesiąc"
    assert client_documents.layout(rules, "2026-11") == "month"
    rules["cl.client_document"]["params"]["per"] = "projekt"
    assert client_documents.layout(rules, "2026-11") is None
