"""Podział rozliczenia na zamówienia z maila klienta (``order_split``). Bez bazy.

Dane fikcyjne: osoby „Jan Testowy”, „Anna Inna”, domeny ``klient.example``
i ``firma.example``, numery zamówień i kwoty wymyślone. Układ jak w poczcie
rozliczeń z próby IX–X 2026:

* odpowiedź klienta na naszą prośbę o akceptację godzin z liniami
  „<numer>: 48h  4800,00 PLN” (wzór BIK za X),
* forward z adresu firmy maila koordynatorki klienta z tabelą przestawną
  osoba × numer SAP, komórki w MD albo puste (wzór Polkomtelu za IX).
"""

from __future__ import annotations

from decimal import Decimal
from email.message import EmailMessage

from app.services.client_settlements import order_split
from app.services.client_settlements.order_split import Part, Row

EML = "message/rfc822"
MSG = "application/vnd.ms-outlook"
CLIENT = "Kierownik Projektu <kierownik@klient.example>"
COORDINATOR = "Koordynatorka <koordynatorka@firma.example>"

LINES_SUBJECT = "RE: Akceptacja czasu Październik 2026 - Jan Testowy"
LINES_BODY = """Dzień dobry.

Akceptuję.

Prośba o rozliczenie października według zamówień:
4500011111:      48h          4800,00 PLN
4500022222:  120h         12000,00 PLN


Pozdrawiam
Kierownik Projektu

From: rozliczenia@firma.example <rozliczenia@firma.example>
Sent: Monday, November 16, 2026 11:19 AM
To: Kierownik Projektu <kierownik@klient.example>
Subject: Akceptacja czasu Październik 2026 - Jan Testowy

Dzień dobry,
Proszę o akceptację czasu świadczenia usług przez Jana Testowego za październik 2026 r. - 168 godzin.

Pozdrawiam,
Koordynator ds. Rozliczeń
"""

TABLE_SUBJECT = "FW: [EXT] RE: Raport Timesheet za 09/2026"
#: Tekst Outlooka z tej samej tabeli: każda komórka w osobnej linii, puste giną.
TABLE_TEXT = """Dw

Pozdrawiam
Koordynatorka

From: Specjalistka Klienta <specjalistka@klient.example>
Sent: Tuesday, October 13, 2026 9:13 AM
To: Koordynatorka <koordynatorka@firma.example>
Subject: ODP: [EXT] RE: Raport Timesheet za 09/2026

Dzień dobry,

Zestawienie poniżej:

Etykiety wierszy
4500011111
4500022222
4500033333
4500044444
Testowy Jan
6
2,5

13,5
Inna Anna


20


Pozdrawiam,
Specjalistka Klienta

From: Kierowniczka <kierowniczka@klient.example>
Sent: Tuesday, October 13, 2026 8:10 AM
Subject: RE: Raport Timesheet za 09/2026

Akceptuję
"""


def _cell(text: str, *, bold: bool = False, right: bool = True) -> str:
    inner = f"<span>{text}<o:p></o:p></span>"
    if bold:
        inner = f"<b>{inner}</b>"
    align = ' align="right"' if right else ""
    return f"<td><p class=MsoNormal{align}>{inner}</p></td>"


def _table(header: list[str], rows: list[list[str]]) -> str:
    head = "".join(
        _cell(text, bold=True, right=index > 0) for index, text in enumerate(header)
    )
    body = "".join(
        "<tr>"
        + "".join(
            _cell(text or "&nbsp;", bold=index == 0, right=index > 0)
            for index, text in enumerate(row)
        )
        + "</tr>"
        for row in rows
    )
    return (
        '<table border="0" cellspacing="0" cellpadding="0"><tbody>'
        f"<tr>{head}</tr>{body}</tbody></table>"
    )


PIVOT = _table(
    ["Etykiety wierszy", "4500011111", "4500022222", "4500033333", "4500044444"],
    [["Testowy Jan", "6", "2,5", "", "13,5"], ["Inna Anna", "", "", "20", ""]],
)


def _forward_html(table: str) -> str:
    return (
        "<html><head><style>p.MsoNormal{margin:0}</style></head><body>"
        "<p class=MsoNormal>Dw<o:p></o:p></p>"
        "<p class=MsoNormal>Pozdrawiam<br>Koordynatorka<o:p></o:p></p>"
        "<div><p class=MsoNormal><b>From:</b> Specjalistka Klienta "
        "&lt;specjalistka@klient.example&gt;<br><b>Sent:</b> Tuesday, October 13, "
        "2026 9:13 AM<br><b>To:</b> Koordynatorka &lt;koordynatorka@firma.example&gt;"
        "<br><b>Subject:</b> ODP: [EXT] RE: Raport Timesheet za 09/2026</p></div>"
        "<p class=MsoNormal>Dzień dobry,<o:p></o:p></p>"
        "<p class=MsoNormal>Zestawienie poniżej:<o:p></o:p></p>"
        f"{table}"
        "<p class=MsoNormal>Pozdrawiam,<br>Specjalistka Klienta</p>"
        "<div><p class=MsoNormal><b>From:</b> Kierowniczka "
        "&lt;kierowniczka@klient.example&gt;<br><b>Sent:</b> Tuesday, October 13, "
        "2026 8:10 AM<br><b>Subject:</b> RE: Raport Timesheet za 09/2026</p></div>"
        "<p class=MsoNormal>Akceptuję<o:p></o:p></p>"
        "</body></html>"
    )


def _eml(subject: str, sender: str, text: str, html: str | None = None) -> EmailMessage:
    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = sender
    message["To"] = "rozliczenia@firma.example"
    message.set_content(text)
    if html is not None:
        message.add_alternative(html, subtype="html")
    return message


def _parse(message: EmailMessage) -> order_split.Split | None:
    return order_split.parse(message.as_bytes(), EML)


# ── Linie w treści (wzór BIK) ────────────────────────────────────────────────


def test_linie_z_odpowiedzi_klienta_z_jednostka_i_akceptacja():
    split = _parse(_eml(LINES_SUBJECT, CLIENT, LINES_BODY))

    assert split is not None
    assert split.kind == order_split.LINES
    assert split.rows == (
        Row(
            None,
            (
                Part("4500011111", Decimal("48"), "h"),
                Part("4500022222", Decimal("120"), "h"),
            ),
        ),
    )
    assert "kierownik@klient.example" in split.author
    assert split.approved is True
    assert split.month == "2026-10"
    assert split.subject == LINES_SUBJECT
    assert order_split.total(split.rows[0]) == Decimal("168")


def test_starsza_wersja_podzialu_w_cytacie_nie_liczy_sie():
    body = (
        "Poprawka, proszę tak:\n"
        "SAP 4500011111 - 8 MD\n"
        "nr 4500022222: 13,5 MD\n\n"
        "From: Kierownik Projektu <kierownik@klient.example>\n"
        "Sent: Monday, November 16, 2026 12:00 PM\n"
        "Subject: RE: Akceptacja czasu Październik 2026 - Jan Testowy\n\n"
        "4500011111: 100h\n"
        "4500033333: 68h\n"
    )
    split = _parse(_eml(LINES_SUBJECT, CLIENT, body))

    assert split is not None
    assert split.rows[0].parts == (
        Part("4500011111", Decimal("8"), "md"),
        Part("4500022222", Decimal("13.5"), "md"),
    )
    assert split.approved is False


def test_linie_tylko_w_naszej_prosbie_maja_naszego_autora():
    body = (
        "Akceptuję.\n\n"
        "From: rozliczenia@firma.example <rozliczenia@firma.example>\n"
        "Sent: Monday, November 16, 2026 11:19 AM\n"
        "Subject: Akceptacja czasu Październik 2026 - Jan Testowy\n\n"
        "Proszę o akceptację godzin według zamówień:\n"
        "4500011111: 48 godz.\n"
        "4500022222: 120 godzin\n"
    )
    split = _parse(_eml(LINES_SUBJECT, CLIENT, body))

    assert split is not None
    assert "rozliczenia@firma.example" in split.author
    assert [p.value for p in split.rows[0].parts] == [Decimal("48"), Decimal("120")]
    assert split.approved is False


def test_ten_sam_numer_dwa_razy_to_brak_podzialu():
    body = "Akceptuję.\n4500011111: 48h\n4500011111: 120h\n"

    assert _parse(_eml(LINES_SUBJECT, CLIENT, body)) is None
    assert order_split.parse_lines(body) == ()


def test_mail_bez_podzialu_to_none():
    body = (
        "Akceptuję 168 h za październik 2026.\n\n"
        "Biuro: ul. Testowa 1, 00-001 Warszawa\nKRS: 0000123456, NIP: 123-456-78-90\n"
        "tel. +48 600 000 000\n"
    )

    assert _parse(_eml(LINES_SUBJECT, CLIENT, body)) is None


def test_linie_cytatu_z_nawiasem_nie_licza_sie():
    assert order_split.parse_lines("> 4500011111: 48h\n> 4500022222: 120h\n") == ()


def test_mail_zalaczony_do_maila_daje_autora_z_zalacznika():
    inner = _eml(LINES_SUBJECT, CLIENT, LINES_BODY)
    outer = _eml(
        "FW: Akceptacja czasu Październik 2026 - Jan Testowy", COORDINATOR, "Dw"
    )
    outer.add_attachment(inner)

    split = _parse(outer)

    assert split is not None
    assert "kierownik@klient.example" in split.author
    assert len(split.rows[0].parts) == 2
    assert split.month == "2026-10"


# ── Tabela przestawna w HTML (wzór Polkomtelu) ───────────────────────────────


def test_tabela_z_pustymi_komorkami_tylko_z_html():
    split = _parse(_eml(TABLE_SUBJECT, COORDINATOR, TABLE_TEXT, _forward_html(PIVOT)))

    assert split is not None
    assert split.kind == order_split.TABLE
    assert split.rows == (
        Row(
            "Testowy Jan",
            (
                Part("4500011111", Decimal("6"), None),
                Part("4500022222", Decimal("2.5"), None),
                Part("4500044444", Decimal("13.5"), None),
            ),
        ),
        Row("Inna Anna", (Part("4500033333", Decimal("20"), None),)),
    )
    assert split.month == "2026-09"
    # Forward z adresu firmy: autor tabeli z cytatu nad nią, akceptacja jest
    # w innej (starszej) wiadomości wątku.
    assert "specjalistka@klient.example" in split.author
    assert split.approved is False
    # Domena klienta sprawdza się po samym adresie, bez imienia i nawiasów.
    assert order_split.author_address(split) == "specjalistka@klient.example"


def test_sam_tekst_maila_nie_daje_tabeli():
    assert _parse(_eml(TABLE_SUBJECT, COORDINATOR, TABLE_TEXT)) is None


def test_wiersz_i_kolumna_sum_pominiete():
    table = _table(
        ["Etykiety wierszy", "SAP 4500011111", "4500022222", "Suma końcowa"],
        [
            ["Testowy Jan", "10", "12", "22"],
            ["Inna Anna", "", "20", "20"],
            ["Suma końcowa", "10", "32", "42"],
        ],
    )
    corner = (
        "<table><tr><td>Suma z MD</td><td>Etykiety kolumn</td></tr>"
        + table.removeprefix('<table border="0" cellspacing="0" cellpadding="0">')
    )
    rows = order_split.parse_table(corner)

    assert rows == (
        Row(
            "Testowy Jan",
            (
                Part("SAP4500011111", Decimal("10"), None),
                Part("4500022222", Decimal("12"), None),
            ),
        ),
        Row("Inna Anna", (Part("4500022222", Decimal("20"), None),)),
    )


def test_tabela_z_kwotami_nie_jest_podzialem():
    table = _table(
        ["Etykiety wierszy", "4500011111", "4500022222"],
        [["Testowy Jan", "4800,00", "12000,00"]],
    )

    assert order_split.parse_table(table) == ()


def test_tabela_bez_numerow_zamowien_w_naglowku_nie_jest_podzialem():
    table = _table(
        ["Numer zamówienia", "Ilość MD", "Kwota netto"],
        [["4500011111", "22", "22000,00"]],
    )

    assert order_split.parse_table(table) == ()


def test_tabela_wygrywa_z_liniami():
    text = "Akceptuję.\n4500011111: 48h\n4500022222: 120h\n"
    split = _parse(
        _eml(TABLE_SUBJECT, CLIENT, text, f"<html><body>{PIVOT}</body></html>")
    )

    assert split is not None
    assert split.kind == order_split.TABLE
    # Tabela bez cytatu nad nią: autor to nadawca maila.
    assert "kierownik@klient.example" in split.author


# ── Dopasowanie osoby i numeru ───────────────────────────────────────────────


def test_row_for_kolejnosc_slow_i_ogonki():
    table = _table(
        ["Etykiety wierszy", "4500011111"],
        [["Testowa-Łęcka Anna", "7"], ["Inna Anna", "3"]],
    )
    split = _parse(_eml(TABLE_SUBJECT, CLIENT, "Zestawienie", f"<html>{table}</html>"))

    assert split is not None
    row = order_split.row_for(split, "Anna Testowa-Łęcka")
    assert row is not None and row.person == "Testowa-Łęcka Anna"
    assert order_split.row_for(split, "anna testowa lecka") is row
    assert order_split.row_for(split, "Anna Testowa") is None
    assert order_split.row_for(split, "") is None


def test_row_for_linie_to_jedyny_wiersz_bez_osoby():
    split = _parse(_eml(LINES_SUBJECT, CLIENT, LINES_BODY))

    assert split is not None
    assert order_split.row_for(split, "Ktokolwiek Inny") is split.rows[0]


def test_dwa_wiersze_tej_samej_osoby_to_brak_dopasowania():
    table = _table(
        ["Etykiety wierszy", "4500011111", "4500022222"],
        [["Testowy Jan", "7", ""], ["Jan Testowy", "", "5"]],
    )
    split = _parse(_eml(TABLE_SUBJECT, CLIENT, "x", f"<html>{table}</html>"))

    assert split is not None
    assert order_split.row_for(split, "Jan Testowy") is None


def test_order_key_z_przedrostkiem_sap():
    assert order_split.order_key("SAP 4500011111") == "4500011111"
    assert order_split.order_key("4500011111") == "4500011111"
    assert order_split.order_key(None) is None


def test_order_key_z_przedrostkiem_po():
    # Komórka nagłówka „PO 4500011111” to ten sam numer co w NEXUS-ie.
    assert order_split.order_key("PO 4500011111") == "4500011111"
    assert order_split.order_key("PO4500011111") == "4500011111"


def test_uszkodzony_plik_to_none():
    assert order_split.parse(b"\x00\xff nie mail", EML) is None
    assert order_split.parse(b"\x00\xff nie mail", MSG) is None
    assert order_split.parse(b"cokolwiek", "application/pdf") is None
