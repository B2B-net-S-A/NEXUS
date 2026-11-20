"""KCP Banku Pocztowego, eksport Redmine i odpowiedź klienta na paczkę (E6.5). Bez bazy.

Dane fikcyjne w układzie prawdziwych plików: karta „KARTA EWIDENCJI ŚWIADCZENIA
USŁUG” ze wzoru banku (PDF z Excela i arkusz), eksport „Przepracowany czas”
z Redmine i odpowiedzi banku z wątku paczki („Akceptuję nadesłane KCP. Proszę
o dosłanie brakujących: …”, „Potwierdzam”).
"""

from __future__ import annotations

import io
from datetime import date, datetime, timezone
from decimal import Decimal

import openpyxl

from app.services.client_settlements import (
    client_acceptance,
    client_invoice,
    kcp,
    mail_text,
    redmine_timelog,
    rules_catalog,
)

PERSON = "Jan Testowy"


def _rules(**levels: str) -> dict:
    stored = {key: {"level": level, "params": {}} for key, level in levels.items()}
    return rules_catalog.effective(stored)


ON = _rules(
    **{
        "proof.month": "block",
        "proof.name_match": "block",
        "fields.md_hours": "block",
        "fields.day_limit": "block",
    }
)


def _card_rows(
    *,
    person: str = "Testowy Jan",
    month: str = "Październik",
    year: str = "2026",
    days: dict[int, tuple[str, str]] | None = None,
    worked: str = "3,0",
    hours: str = "24",
    overtime: str = "",
) -> list[list]:
    days = (
        days
        if days is not None
        else {
            1: ("Zadanie #1: Analiza", "8"),
            2: ("Zadanie #2: Testy", "8"),
            5: ("Zadanie #3: Wdrożenie", "8"),
        }
    )
    rows: list[list] = [
        [None, "KARTA EWIDENCJI ŚWIADCZENIA USŁUG", None],
        [None, f"Imię i Nazwisko: {person}", None],
        [None, f"Miesiąc: {month}", None],
        [None, f"Rok: {year}", None],
        ["Dzień\nmiesiąca", "Zagadnienia", "Liczba\ngodzin"],
    ]
    for day in range(1, 32):
        text, value = days.get(day, ("", ""))
        rows.append([day, text, value])
    rows += [
        [None, "Suma dni przepracowanych", worked],
        [None, "Liczba godzin czas podstawowy", hours],
        [None, "Liczba godzin - nadgodziny", overtime],
        [None, "Podpis dysponenta / dysponentów budżetu:", None],
    ]
    return rows


def _titles(result) -> dict[str, str]:
    return {c["title"]: c["state"] for g in result.groups for c in g["checks"]}


# ── KCP ──────────────────────────────────────────────────────────────────────


def test_karta_z_arkusza_daje_osobe_miesiac_dni_i_sumy() -> None:
    parsed = kcp.parse_rows(_card_rows())
    assert parsed is not None
    assert parsed.person == "Testowy Jan"
    assert parsed.month == "2026-10"
    assert parsed.total_hours == Decimal("24")
    assert parsed.worked_days == 3
    assert parsed.declared_days == Decimal("3.0")
    assert parsed.declared_hours == Decimal("24")
    assert parsed.overtime_hours is None


def test_tekst_strony_pdf_z_zawinietym_opisem_nie_myli_dni() -> None:
    """Tekst strony ma etykiety z wartością w jednej linii i samotne „8” po
    zawiniętym opisie; dni bierzemy z tabeli, sumy z pierwszego trafienia."""

    rows = [
        ["KARTA EWIDENCJI ŚWIADCZENIA USŁUG"],
        ["Imię i Nazwisko: Testowy Jan"],
        ["Miesiąc: Listopad"],
        ["Rok: 2026"],
        ["Zadanie #10: Bardzo długi opis zadania, który się zawija"],
        ["8"],
        ["3"],
        ["Suma dni przepracowanych 1,0"],
        ["Liczba godzin czas podstawowy 8"],
        ["Liczba godzin - nadgodziny"],
        ["Dzień\nmiesiąca", "Zagadnienia", "Liczba\ngodzin"],
        ["1", "Zadanie #10: Bardzo długi opis\nzadania, który się zawija", "8"],
        ["2", "", ""],
        ["Suma dni przepracowanych", "1,0"],
    ]
    parsed = kcp.parse_rows(rows)
    assert parsed.month == "2026-11"
    assert [(d.day, d.hours) for d in parsed.days if d.hours] == [(1, Decimal("8"))]
    assert parsed.declared_hours == Decimal("8")
    assert parsed.overtime_hours is None


def test_plik_bez_tytulu_karty_to_nie_kcp() -> None:
    rows = _card_rows()[1:]
    assert kcp.parse_rows(rows) is None


def test_kontrole_kcp_bez_uwag_i_md_z_godzin() -> None:
    parsed = kcp.parse_rows(_card_rows())
    result = kcp.evaluate(
        parsed, month="2026-10", person_name=PERSON, rules=ON, working_days=22
    )
    assert result.md_regular == Decimal("3.000")
    assert result.md_extra == Decimal("0")
    assert not result.blocking and not result.warn
    titles = _titles(result)
    assert titles["Miesiąc z KCP: 2026-10"] == "ok"
    assert titles["Imię i nazwisko jak w kontrakcie"] == "ok"
    assert titles["3 dni, 24 h"] == "ok"
    assert result.meta["kcp"] == {"source": "kcp", "hours": "24", "days": 3}


def test_inna_suma_na_karcie_blokuje() -> None:
    parsed = kcp.parse_rows(_card_rows(hours="32", worked="4,0"))
    result = kcp.evaluate(
        parsed, month="2026-10", person_name=PERSON, rules=ON, working_days=22
    )
    assert result.blocking
    titles = _titles(result)
    assert titles["Suma godzin na KCP inna niż suma dni"] == "fail"
    assert titles["Liczba dni na KCP inna niż dni z godzinami"] == "fail"


def test_inny_miesiac_inna_osoba_i_dzien_bez_zagadnienia() -> None:
    parsed = kcp.parse_rows(
        _card_rows(
            person="Inna Osoba",
            month="Wrzesień",
            days={1: ("", "8"), 2: ("Zadanie #2", "25")},
            worked="2,0",
            hours="33",
        )
    )
    result = kcp.evaluate(
        parsed, month="2026-10", person_name=PERSON, rules=ON, working_days=22
    )
    assert result.blocking
    titles = _titles(result)
    assert titles["KCP za inny miesiąc"] == "fail"
    assert titles["Inne imię lub nazwisko niż w kontrakcie"] == "fail"
    assert titles["25 h w dniu 2"] == "fail"
    assert titles["Dni z godzinami bez zagadnienia: 1"] == "warn"


def test_nadgodziny_ida_jako_praca_dodatkowa() -> None:
    parsed = kcp.parse_rows(_card_rows(overtime="4"))
    result = kcp.evaluate(
        parsed, month="2026-10", person_name=PERSON, rules=ON, working_days=22
    )
    assert result.md_regular == Decimal("3.000")
    assert result.md_extra == Decimal("0.500")


def test_wylaczone_reguly_nie_sprawdzaja_ale_md_liczy() -> None:
    parsed = kcp.parse_rows(_card_rows(person="Ktoś Inny", hours="99"))
    result = kcp.evaluate(
        parsed,
        month="2026-10",
        person_name=PERSON,
        rules=rules_catalog.effective(None),
        working_days=22,
    )
    assert not result.blocking
    assert result.md_regular == Decimal("3.000")


def _workbook(sheets: dict[str, list[list]]) -> bytes:
    book = openpyxl.Workbook()
    book.remove(book.active)
    for title, rows in sheets.items():
        ws = book.create_sheet(title)
        for row in rows:
            ws.append(row)
    out = io.BytesIO()
    book.save(out)
    return out.getvalue()


def test_kcp_w_arkuszu_karta() -> None:
    content = _workbook({"Wprowadzenie": [["Formatka"]], "KARTA": _card_rows()})
    parsed = kcp.parse(content, kcp.XLSX)
    assert parsed is not None and parsed.total_hours == Decimal("24")


# ── Redmine ──────────────────────────────────────────────────────────────────

HEADER = [
    "Projekt",
    "Data",
    "Użytkownik",
    "Aktywność",
    "Zagadnienie",
    "Komentarz",
    "Godzin",
]


def _timelog() -> list[list]:
    return [
        HEADER,
        [
            "Portal",
            datetime(2026, 10, 30),
            "Testowy Jan",
            "Programowanie",
            "Task #3: Logowanie",
            None,
            7,
        ],
        [
            "Portal",
            datetime(2026, 10, 30),
            "Testowy Jan",
            "Spotkania",
            "Task #9: Organizacja",
            None,
            1,
        ],
        [
            "Portal",
            datetime(2026, 10, 29),
            "Testowy Jan",
            "Programowanie",
            "Task #3: Logowanie",
            None,
            4,
        ],
        [
            "Portal",
            datetime(2026, 10, 29),
            "Testowy Jan",
            "Programowanie",
            "Task #3: Logowanie",
            None,
            4,
        ],
        [
            "Portal",
            datetime(2026, 9, 30),
            "Testowy Jan",
            "Programowanie",
            "Task #1: Stare",
            None,
            8,
        ],
        ["Portal", None, "Testowy Jan", "Programowanie", "Task #1: Bez daty", None, 8],
    ]


def test_eksport_redmine_skladany_w_kcp_dzien_po_dniu() -> None:
    log = redmine_timelog.parse_rows([_timelog()])
    assert log is not None and len(log.entries) == 5
    card, outside = redmine_timelog.to_kcp(log, "2026-10")
    assert outside == 1
    assert card.source == "redmine" and card.person == "Testowy Jan"
    assert [(d.day, d.hours) for d in card.days] == [
        (29, Decimal("8")),
        (30, Decimal("8")),
    ]
    assert card.days[1].description == "Task #3: Logowanie; Task #9: Organizacja"
    result = kcp.evaluate(
        card,
        month="2026-10",
        person_name=PERSON,
        rules=ON,
        working_days=22,
        outside_month=outside,
    )
    assert result.md_regular == Decimal("2.000")
    titles = _titles(result)
    assert titles["Wpisy spoza rozliczanego miesiąca: 1"] == "fail"
    assert titles["KCP złożona przez NEXUS ze wzoru banku"] == "ok"


def test_pusta_karta_we_wzorze_banku_czytana_z_arkusza_import() -> None:
    """Wzór banku zapisany bez przeliczenia formuł ma pustą „KARTA”: godziny
    bierzemy z wklejonego eksportu w arkuszu „import”."""

    empty = _card_rows(days={}, worked="", hours="")
    content = _workbook({"import": _timelog(), "KARTA": empty})
    found = redmine_timelog.read_card(content, kcp.XLSX, "2026-10")
    assert found is not None
    card, outside = found
    assert card.source == "redmine" and card.total_hours == Decimal("16")
    assert outside == 1


def test_wydruk_kcp_w_ukladzie_karty() -> None:
    log = redmine_timelog.parse_rows([_timelog()])
    card, _ = redmine_timelog.to_kcp(log, "2026-10")
    html = redmine_timelog.render_html(card)
    assert "KARTA EWIDENCJI ŚWIADCZENIA USŁUG" in html
    assert "Miesiąc: Październik" in html and "Rok: 2026" in html
    assert html.count("<tr><td class='n'>") == 31
    assert "Suma dni przepracowanych</td><td class='v'>2,0" in html
    assert "Podpis dysponenta" in html


def test_wydruk_kcp_czyta_sie_z_powrotem_jak_karta() -> None:
    log = redmine_timelog.parse_rows([_timelog()])
    card, _ = redmine_timelog.to_kcp(log, "2026-10")
    pdf = redmine_timelog.render_pdf(card)
    again = kcp.parse(pdf, kcp.PDF)
    assert again is not None
    assert again.month == "2026-10" and again.person == "Testowy Jan"
    assert again.total_hours == Decimal("16")


def _long_month_card() -> kcp.ParsedKcp:
    """22 dni robocze po 8 h, każdy z wieloma długimi zagadnieniami z Redmine:
    wydruk ma co najmniej 6 stron jak prawdziwa karta, ostatnie dni i sumy są
    za czwartą stroną."""

    issue = (
        "Task #{n}: Migracja modułu {n} do nowego frameworka — Implementacja zmian"
        " w kodzie, testy lokalne, weryfikacja poprawki oraz sprawdzenie regresji"
    )
    weekdays = [d for d in range(1, 31) if date(2026, 9, d).weekday() < 5]
    days = tuple(
        kcp.KcpDay(
            d, "; ".join(issue.format(n=d * 10 + i) for i in range(10)), Decimal("8")
        )
        for d in weekdays
    )
    return kcp.ParsedKcp(person="Testowy Jan", month="2026-09", days=days)


def test_kcp_z_pdf_dluzszego_niz_cztery_strony_czytana_do_konca() -> None:
    card = _long_month_card()
    assert card.worked_days == 22
    pdf = redmine_timelog.render_pdf(card)
    import pdfplumber

    with pdfplumber.open(io.BytesIO(pdf)) as doc:
        assert len(doc.pages) >= 6
    again = kcp.parse(pdf, kcp.PDF)
    assert again is not None
    assert again.worked_days == 22
    assert again.total_hours == Decimal("176")
    assert again.declared_days == Decimal("22.0")
    assert again.declared_hours == Decimal("176")
    result = kcp.evaluate(
        again, month="2026-09", person_name=PERSON, rules=ON, working_days=22
    )
    assert result.md_regular == Decimal("22")


def test_kcp_bez_sum_karty_nie_przechodzi_po_cichu() -> None:
    # Karta od konsultanta zawsze ma sumy; ich brak znaczy, że część pliku
    # się nie odczytała (np. ucięte strony), więc dni mogą być niepełne.
    rows = [r for r in _card_rows() if not (r[1] or "").startswith(("Suma", "Liczba"))]
    parsed = kcp.parse_rows(rows)
    assert parsed is not None and parsed.declared_days is None
    result = kcp.evaluate(
        parsed, month="2026-10", person_name=PERSON, rules=ON, working_days=22
    )
    assert _titles(result)["Nie odczytano sum z KCP"] == "warn"
    assert result.warn


# ── Odpowiedź klienta ────────────────────────────────────────────────────────


def _mail(
    body: str,
    *,
    sender: str = "Body <body@bank.example>",
    subject: str = "RE: KCP B2Bnetwork październik 2026",
) -> mail_text.Mail:
    return mail_text.Mail(
        subject=subject,
        sender=sender,
        sent_at=datetime(2026, 11, 10, 9, 30, tzinfo=timezone.utc),
        body=body,
    )


THREAD = (
    "\n\nFrom: Koordynatorka <koordynatorka@b2b.example>\n"
    "Sent: Friday, November 6, 2026 10:17 AM\n"
    "Subject: KCP B2Bnetwork październik 2026\n\n"
    "W załączeniu przekazuję KCP naszych konsultantów. Prośba o akceptację.\n"
)


def test_akceptacja_z_lista_brakujacych() -> None:
    reply = client_acceptance.judge(
        _mail(
            "Dzień dobry,\n\nAkceptuję nadesłane KCP.\n\nProszę o dosłanie brakujących:\n"
            "*\tAnna Brakująca\n*\tPiotr Drugi\n" + THREAD
        )
    )
    assert reply.accepted
    assert reply.sender_domain == "bank.example"
    assert reply.month == "2026-10"
    assert reply.quote == "Akceptuję nadesłane KCP."
    assert client_acceptance.named("Anna Brakująca", reply.missing_text)
    assert not client_acceptance.named("Jan Testowy", reply.missing_text)


def test_potwierdzam_bez_listy() -> None:
    reply = client_acceptance.judge(_mail("Dzień dobry,\n\nPotwierdzam.\n" + THREAD))
    assert reply.accepted and reply.missing_text == ""
    assert reply.quote == "Potwierdzam."


def test_akceptacja_tylko_w_cytacie_to_nie_akceptacja() -> None:
    """„Prośba o akceptację” stoi w naszym cytowanym mailu, nie w odpowiedzi."""

    reply = client_acceptance.judge(
        _mail("Dzień dobry,\n\nW KCP jest błąd w dniu 5.\n" + THREAD)
    )
    assert not reply.accepted


def test_odmowa_nie_akceptuje() -> None:
    reply = client_acceptance.judge(
        _mail("Nie akceptuję KCP, proszę o poprawę.\n" + THREAD)
    )
    assert not reply.accepted


def test_wiadomosc_z_eml_czytana_cala() -> None:
    raw = (
        "From: Body <body@bank.example>\r\n"
        "To: rozliczenia@b2b.example\r\n"
        "Subject: RE: KCP B2Bnetwork październik 2026\r\n"
        "Date: Mon, 16 Nov 2026 08:56:11 +0100\r\nMIME-Version: 1.0\r\n"
        "Content-Type: text/plain; charset=utf-8\r\n\r\n"
        "Potwierdzam.\r\n\r\nOd: Koordynatorka <k@b2b.example>\r\nProśba o akceptację.\r\n"
    ).encode()
    reply = client_acceptance.read_reply(raw, "message/rfc822")
    assert reply is not None and reply.accepted
    assert reply.sent_at is not None and reply.sent_at.date() == date(2026, 11, 16)


def test_temat_nazwa_pliku_i_tresc_maila() -> None:
    rules = rules_catalog.effective(
        {
            "cl.client_acceptance": {
                "level": "warn",
                "params": {"email": "Body@Bank.example", "subject": ""},
            }
        }
    )
    p = client_acceptance.params(rules)
    assert p.email == "body@bank.example" and p.domain == "bank.example"
    assert (
        client_acceptance.subject_for(p, "2026-10") == "KCP B2Bnetwork październik 2026"
    )
    assert client_acceptance.file_name("Jan Maria Testowy") == "J. Maria Testowy.pdf"
    body = client_acceptance.body_for("2026-11", ["Jan Testowy", "Anna Druga"])
    assert "za listopad 2026: Jan Testowy, Anna Druga." in body
    assert client_acceptance.params(rules_catalog.effective(None)) is None


def test_opis_pozycji_ze_wzoru_reguly() -> None:
    rules = rules_catalog.effective(
        {
            "cl.item_name": {
                "level": "warn",
                "params": {
                    "template": "Prace informatyczne zgodnie z zamówieniem {zamowienie}, {osoba}"
                },
            }
        }
    )
    assert (
        client_invoice.item_name(rules, "1/2026/ZAM/B2B", "Jan Testowy")
        == "Prace informatyczne zgodnie z zamówieniem 1/2026/ZAM/B2B, Jan Testowy"
    )
    assert client_invoice.item_name(rules, None, "Jan Testowy").endswith(
        "—, Jan Testowy"
    )
    assert client_invoice.item_name(rules_catalog.effective(None), "1", "J") is None


def test_reguly_e6_5_w_katalogu() -> None:
    for key in ("cl.client_acceptance", "cl.item_name"):
        assert rules_catalog.RULES[key].stage == "E6.5"
        assert rules_catalog.RULES[key].level == "off"
