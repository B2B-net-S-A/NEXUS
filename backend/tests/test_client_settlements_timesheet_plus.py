"""Raporty godzin grupy Polkomtel / Cyfrowy Polsat w plikach „.xls” (próba IX–X 2026).

Bez bazy. Żaden z tych plików nie jest starym Excelem: Polkomtel przysyła
„Project timesheet Report” z Jiry jako tabelę HTML, a Cyfrowy Polsat arkusz
XML Spreadsheet 2003 („B2B_RRRR_MM.xls”) z numerem zamówienia w każdym wierszu.
Do 23.11.2026 HTML był odrzucany przy zapisie, a arkusza Polsatu nie czytał
żaden czytnik MD. Dane fikcyjne: „Jan Testowy”, „Anna Inna”, zamówienia Z99….
"""

from __future__ import annotations

from decimal import Decimal

from app.models.consultant_portal import CpDocument
from app.services.client_settlements import kesu, rules_catalog, service
from app.services.client_settlements import timesheet, timesheet_plus
from app.services.consultant_portal import documents

PERSON = "Jan Testowy"


def _rules() -> dict:
    return rules_catalog.effective(
        {
            "proof.month": {"level": "block"},
            "proof.name_match": {"level": "warn"},
            "proof.excel_with_mail": {"level": "off"},
            "proof.accept_has_hours": {"level": "off"},
            "fields.md_hours": {"level": "block", "params": {"hours": "8"}},
            "fields.md_month_limit": {"level": "off"},
        }
    )


# ── Polkomtel: „Project timesheet Report” (HTML) ──────────────────────────────


def polkomtel_html(
    *,
    person: str = PERSON,
    month: str = "Wrzesień 2026",
    order: str = "",
    total: str = "176 godz.",
    days: int = 22,
    year_month: str = "09/2026",
) -> bytes:
    rows = "".join(
        f"<tr><td>{day:02d}/{year_month}</td><td>8 godz.</td><td>WD-1</td>"
        f"<td>Testy ALFA</td><td></td></tr>"
        for day in range(1, days + 1)
    )
    return (
        '<html><head><title>Project timesheet Report</title><meta http-equiv="Content-Type" '
        'Content="application/vnd.ms-excel; charset=UTF-8" /></head><body>'
        "<style>td { padding-top: 2px; }</style><table>"
        f"<tr><td>Nazwisko konsultanta:</td><td>{person}</td></tr>"
        f"<tr><td>Miesiąc:</td><td>{month}</td></tr>"
        f"<tr><td>Nr zlecenia:</td><td>{order}</td></tr>"
        "<tr><td>Nazwa firmy:</td><td>Firma Testowa</td></tr>"
        f"<tr><td>Suma godzin:</td><td>{total}</td></tr>"
        "<tr><td>50% kosztów:</td><td>0 godz.</td></tr>"
        "<tr><td>Zestawienie szczegółowe:</td></tr>"
        "<tr><th>Data</th><th>Liczba godzin pracy</th><th>Numer zadania</th>"
        "<th>Opis wykonanej pracy</th><th>PB</th></tr>"
        f"{rows}"
        "<tr><td>Podpis Konsultanta</td><td></td></tr></table></body></html>"
    ).encode()


def test_polkomtel_report_md_z_sumy_godzin() -> None:
    sheet = timesheet_plus.parse(polkomtel_html())

    assert sheet is not None and sheet.source == timesheet_plus.POLKOMTEL
    assert sheet.month == "2026-09"
    assert [(r.person, r.order, r.hours) for r in sheet.rows] == [
        (PERSON, None, Decimal("176"))
    ]
    found = timesheet_plus.declared_for(sheet, PERSON)
    assert found is not None and found.hours == Decimal("176")


def test_polkomtel_report_z_numerem_zlecenia() -> None:
    sheet = timesheet_plus.parse(polkomtel_html(order="PZ/0000099001"))

    assert sheet is not None and sheet.rows[0].order == "PZ/0000099001"


def test_polkomtel_report_suma_inna_niz_dni_to_bez_godzin() -> None:
    """176 h w nagłówku, a 21 dni po 8 h: nie zgadujemy, który zapis jest dobry."""

    sheet = timesheet_plus.parse(polkomtel_html(days=21))

    assert sheet is not None and sheet.rows[0].hours is None


def test_inny_html_to_nie_raport_polkomtelu() -> None:
    other = b"<html><head><title>Time Sheet Report</title></head><body></body></html>"

    assert timesheet_plus.parse(other) is None
    assert timesheet_plus.is_polkomtel_report(other) is False


def test_raport_polkomtelu_przechodzi_kontrole_pliku() -> None:
    """Na main ``check_settlement_file`` odrzucał HTML („Wgraj PDF, arkusz…”)."""

    mime, _ = documents.check_settlement_file(polkomtel_html())

    assert mime == documents.KESU_MIME


# ── Cyfrowy Polsat: „B2B_RRRR_MM.xls” (XML Spreadsheet 2003) ─────────────────


def _cell(value: str, *, index: int | None = None, merge: int = 0) -> str:
    attrs = f' ss:Index="{index}"' if index else ""
    attrs += f' ss:MergeAcross="{merge}"' if merge else ""
    kind = "Number" if value.isdigit() else "String"
    data = f'<Data ss:Type="{kind}">{value}</Data>' if value else ""
    return f"<Cell{attrs}>{data}</Cell>"


def polsat_xml(rows: list[tuple[str, str, str, dict[int, str]]]) -> bytes:
    """Wiersze: (konsultant, zamówienie, godziny w miesiącu, {dzień: godziny})."""

    header = "".join(
        _cell(v)
        for v in ("Opis", "Dostawca", "Konsultant", "Zamówienie", "R(h)", "P(h)")
    )
    header += _cell("2026") + _cell("2026", merge=30)
    months = _cell("październik", index=7) + _cell("październik", merge=30)
    days = _cell("1", index=8) + "".join(_cell(str(d)) for d in range(2, 32))
    body = ""
    for person, order, month_hours, per_day in rows:
        cells = [_cell("PROJEKT ALFA"), _cell("B2B"), _cell(person), _cell(order)]
        cells += [_cell("240"), _cell(""), _cell(month_hours)]
        cells += [_cell(per_day.get(d, "")) for d in range(1, 32)]
        body += "<Row>" + "".join(cells) + "</Row>"
    return (
        '﻿<?xml version="1.0" encoding="utf-8"?>'
        '<Workbook xmlns="urn:schemas-microsoft-com:office:spreadsheet" '
        'xmlns:ss="urn:schemas-microsoft-com:office:spreadsheet">'
        '<Worksheet ss:Name="B2B"><Table>'
        f"<Row>{header}</Row><Row>{months}</Row><Row>{days}</Row>{body}"
        "</Table></Worksheet></Workbook>"
    ).encode()


def _ten(days: range) -> dict[int, str]:
    return {d: "10" for d in days}


POLSAT = polsat_xml(
    [
        ("Testowy Jan", "Z990101001", "120", _ten(range(1, 13))),
        ("Testowy Jan", "Z990101001", "100", _ten(range(22, 32))),
        ("Inna Anna", "Z990202002", "80", {d: "8" for d in range(1, 11)}),
    ]
)


def test_polsat_wiersze_osoby_i_zamowienia() -> None:
    """Dni 22–31 leżą za 30. kolumną: czytnik KEŚU ucinał je (``_MAX_COLS``)."""

    sheet = timesheet_plus.parse(POLSAT)

    assert sheet is not None and sheet.source == timesheet_plus.POLSAT
    assert sheet.month == "2026-10"
    assert [(r.person, r.order, r.hours) for r in sheet.rows] == [
        ("Testowy Jan", "Z990101001", Decimal("120")),
        ("Testowy Jan", "Z990101001", Decimal("100")),
        ("Inna Anna", "Z990202002", Decimal("80")),
    ]


def test_polsat_godziny_tylko_tej_osoby() -> None:
    found = timesheet_plus.declared_for(timesheet_plus.parse(POLSAT), PERSON)

    assert found is not None and found.hours == Decimal("220")
    assert found.month == "2026-10"


def test_polsat_kolumna_miesiaca_inna_niz_dni_to_bez_godzin() -> None:
    sheet = timesheet_plus.parse(
        polsat_xml([("Testowy Jan", "Z990101001", "130", _ten(range(1, 13)))])
    )

    assert sheet is not None and sheet.rows[0].hours is None


def test_polsat_to_nie_keszu() -> None:
    assert kesu.is_kesu_file(POLSAT)
    assert kesu.parse(POLSAT) is None


def test_arkusz_polsatu_z_bom_przechodzi_kontrole_pliku() -> None:
    """CP 634 X: plik zaczyna się od BOM UTF-8, więc na main ``is_kesu_file`` go nie
    poznawał i mail z rozliczeniem nie zostawiał w NEXUS-ie żadnego dokumentu."""

    assert POLSAT.startswith(b"\xef\xbb\xbf")
    mime, _ = documents.check_settlement_file(POLSAT)

    assert mime == documents.KESU_MIME


def test_numer_zamowienia_bez_przedrostka() -> None:
    same = timesheet_plus.order_key
    assert same("CP Z990101001") == same("Z990101001") == "Z990101001"
    assert same("SAP 4500000001") == same("4500000001")
    assert same("") is None and same(None) is None


# ── Odczyt MD w rozliczeniu (``service._proof``) ──────────────────────────────


def _document(tmp_path, doc_id: int, name: str, content: bytes) -> CpDocument:
    folder = tmp_path / "consultant_portal" / "1"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / name).write_bytes(content)
    return CpDocument(
        id=doc_id,
        kind="report",
        mime=documents.KESU_MIME,
        file_path=f"consultant_portal/1/{name}",
    )


async def test_md_z_raportu_polkomtelu(tmp_path, monkeypatch) -> None:
    from app.services import storage_service

    monkeypatch.setattr(storage_service, "STORAGE_ROOT", tmp_path)
    doc = _document(tmp_path, 1, "ts.xls", polkomtel_html())

    result = await service._proof(
        doc, [doc], month="2026-09", person_name=PERSON, rules=_rules()
    )

    assert result is not None and result.md_regular == Decimal("22.000")


async def test_md_z_arkusza_polsatu(tmp_path, monkeypatch) -> None:
    """CP 634 X: 120 h + 100 h po 10 h dziennie = 27,5 MD, jak na fakturze."""

    from app.services import storage_service

    monkeypatch.setattr(storage_service, "STORAGE_ROOT", tmp_path)
    doc = _document(tmp_path, 1, "B2B_2026_10.xls", POLSAT)

    result = await service._proof(
        doc, [doc], month="2026-10", person_name=PERSON, rules=_rules()
    )

    assert result is not None and result.md_regular == Decimal("27.500")


# ── Ten sam układ w „.xlsx” (próba VI–VIII 2026) ─────────────────────────────


def polsat_xlsx(
    rows: list[tuple[str, str, str, dict[int, str]]],
    *,
    month: str = "lipiec",
    hours_columns: bool = False,
) -> bytes:
    """Wiersze jak w ``polsat_xml``; ``hours_columns`` = kolumny R(h)/P(h) i wiersz SUMA."""

    import io

    import openpyxl

    lead = ["Opis", "Dostawca", "Konsultant", "Zamówienie"]
    lead += ["R(h)", "P(h)"] if hours_columns else []
    width = len(lead)
    book = openpyxl.Workbook()
    sheet = book.active
    sheet.title = "Harmonogram"
    sheet.append([*lead, 2026, 2026])
    sheet.append([None] * width + [month, month])
    sheet.append([None] * (width + 1) + list(range(1, 32)))
    for person, order, month_hours, per_day in rows:
        extra = [240, 0] if hours_columns else []
        days = [int(per_day[d]) if d in per_day else None for d in range(1, 32)]
        sheet.append(
            ["PROJEKT ALFA", "B2B", person, order, *extra, int(month_hours), *days]
        )
    if hours_columns:
        sheet.append(["SUMA", None, None, None, 480, 0, 999])
    out = io.BytesIO()
    book.save(out)
    return out.getvalue()


def test_polsat_xlsx_jedna_osoba_na_dwoch_zamowieniach() -> None:
    content = polsat_xlsx(
        [
            ("Testowy Jan", "Z990101001", "88", {d: "8" for d in range(1, 12)}),
            ("Testowy Jan", "4500000001", "8", {14: "8"}),
        ]
    )
    sheet = timesheet_plus.parse(content)

    assert sheet is not None and sheet.source == timesheet_plus.POLSAT
    assert sheet.month == "2026-07"
    assert [(r.order, r.hours) for r in sheet.rows] == [
        ("Z990101001", Decimal("88")),
        ("4500000001", Decimal("8")),
    ]
    polsat = timesheet_plus.declared_for(
        sheet, PERSON, orders=frozenset({timesheet_plus.order_key("CP Z990101001")})
    )
    polkomtel = timesheet_plus.declared_for(
        sheet, PERSON, orders=frozenset({timesheet_plus.order_key("SAP 4500000001")})
    )
    assert polsat.hours == Decimal("88") and polkomtel.hours == Decimal("8")
    # Bez numerów kontraktu: cała osoba, jak dotąd.
    assert timesheet_plus.declared_for(sheet, PERSON).hours == Decimal("96")


def test_polsat_xlsx_z_kolumnami_godzin_i_wierszem_suma() -> None:
    content = polsat_xlsx(
        [
            ("Testowy Jan", "Z990101001", "40", {d: "8" for d in range(1, 6)}),
            ("Inna Anna", "Z990202002", "16", {1: "8", 2: "8"}),
        ],
        month="czerwiec",
        hours_columns=True,
    )
    sheet = timesheet_plus.parse(content)

    assert sheet is not None and sheet.month == "2026-06"
    assert [(r.person, r.hours) for r in sheet.rows] == [
        ("Testowy Jan", Decimal("40")),
        ("Inna Anna", Decimal("16")),
    ]
    assert len(timesheet_plus.people(sheet)) == 2


def test_wiersze_innego_kontraktu_nie_licza_sie_drugi_raz() -> None:
    """Kontrakt bez żadnego numeru z pliku (zamówienie jeszcze nie w NEXUS-ie) bierze
    wiersze osoby bez numerów jej pozostałych kontraktów, inaczej te same godziny
    weszłyby do dwóch rozliczeń. Gdy nie zostaje żaden wiersz, godzin nie ma."""

    sheet = timesheet_plus.parse(
        polsat_xlsx(
            [
                ("Testowy Jan", "Z990101001", "88", {d: "8" for d in range(1, 12)}),
                ("Testowy Jan", "4500000001", "8", {14: "8"}),
            ]
        )
    )
    polsat = timesheet_plus.order_key("CP Z990101001")

    rest = timesheet_plus.declared_for(sheet, PERSON, other_orders=frozenset({polsat}))
    none = timesheet_plus.declared_for(
        sheet, PERSON, other_orders=frozenset({polsat, "4500000001"})
    )

    assert rest is not None and rest.hours == Decimal("8")
    assert none is not None and none.hours is None
    assert (none.consultant, none.month) == ("Testowy Jan", "2026-07")


def test_inny_arkusz_xlsx_to_nie_polsat() -> None:
    import io

    import openpyxl

    book = openpyxl.Workbook()
    book.active.append(["Data", "Godziny"])
    out = io.BytesIO()
    book.save(out)
    assert timesheet_plus.parse(out.getvalue()) is None


async def test_md_tylko_z_wierszy_zamowien_kontraktu(tmp_path, monkeypatch) -> None:
    """Lipiec 2026: Polsat 111 h (13,875 MD), Polkomtel 8 h (1 MD) w jednym pliku."""

    from app.services import storage_service

    monkeypatch.setattr(storage_service, "STORAGE_ROOT", tmp_path)
    content = polsat_xlsx(
        [
            ("Testowy Jan", "Z990101001", "88", {d: "8" for d in range(1, 12)}),
            ("Testowy Jan", "4500000001", "8", {14: "8"}),
        ]
    )
    folder = tmp_path / "consultant_portal" / "1"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "B2B_2026_07.xlsx").write_bytes(content)
    doc = CpDocument(
        id=1,
        kind="report",
        mime=timesheet.XLSX,
        file_path="consultant_portal/1/B2B_2026_07.xlsx",
    )

    polkomtel = await service._proof(
        doc,
        [doc],
        month="2026-07",
        person_name=PERSON,
        rules=_rules(),
        order_keys=frozenset({timesheet_plus.order_key("SAP 4500000001")}),
    )

    assert polkomtel is not None and polkomtel.md_regular == Decimal("1.000")
