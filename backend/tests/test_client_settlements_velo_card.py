"""Karta ewidencji pracy VeloBanku jako wariant Time Sheet (``timesheet``). Bez bazy.

Próba IX–X 2026: konsultant przysyła „Karta ewidencji pracy_MM.RRRR_….xlsx”
(„NAZWISKO I IMIĘ”, „Tabela miesięczna”, „Dzień · Start · Koniec · Czas pracy”,
czas w formacie godzin, pod tabelą „Suma przepracowanych dni” w dniach). Nikt
tego pliku nie czytał, więc rozliczenie miało „Nie rozpoznano szablonu RCP”
i status „warnings”, a MD brało z podpisanego arkusza zbiorczego zaokrąglone
do setnych (21,63 zamiast 21,625). Osoba i liczby fikcyjne.
"""

from __future__ import annotations

import io
from datetime import date, datetime, time, timedelta
from decimal import Decimal

from app.services.client_settlements import rules_catalog, timesheet

PERSON = "Anna Testowa"


def _card(cells: dict[date, object], *, title: bool = True) -> list[list[object]]:
    rows: list[list[object]] = [
        ["NAZWISKO I IMIĘ", None, PERSON, None, None, None, "KLIENT", None, "BANK"],
        ["KONTRAHENT", None, "FIRMA S.A.", None, None, None, "ROLA", None, "TESTER"],
        ["Tabela miesięczna" if title else "Zestawienie"],
        ["WRZESIEŃ 2026"],
        ["Dzień", None, "Start", "Koniec", "Czas pracy ", "System", "Inicjatywa"],
    ]
    for day, worked in cells.items():
        rows.append(
            [datetime.combine(day, time()), "dzień", time(9), time(17), worked, "SYS"]
        )
    rows.append(["Suma przepracowanych dni", None, None, None, time(21, 37, 30)])
    return rows


def _september(first_short: object = time(5)) -> dict[date, object]:
    """22 dni robocze IX 2026, jeden krótszy: 21 × 8 h + 5 h = 173 h."""

    days = [date(2026, 9, d) for d in range(1, 31) if date(2026, 9, d).weekday() < 5]
    cells: dict[date, object] = {day: time(8) for day in days}
    cells[days[1]] = first_short
    cells[date(2026, 9, 5)] = None  # sobota: pusty czas pracy
    return cells


def test_karta_daje_godziny_osobe_i_miesiac():
    parsed = timesheet.parse_rows([_card(_september())])
    assert parsed is not None
    assert parsed.consultant == PERSON
    assert parsed.month == "2026-09"
    assert len(parsed.entries) == 22
    assert parsed.total_hours == Decimal("173")
    # Suma pod tabelą jest w dniach: nie jest ani wpisem, ani sumą godzin pliku.
    assert parsed.declared_total is None
    assert timesheet.md_from_hours(parsed.total_hours, Decimal("8")) == Decimal(
        "21.625"
    )


def test_wiersz_z_data_spoza_miesiaca_bez_czasu_pracy_pominiety():
    cells = _september()
    cells[date(2026, 8, 31)] = None  # przeniesiony wiersz z szablonu, bez czasu
    parsed = timesheet.parse_rows([_card(cells)])
    assert parsed is not None
    assert all(e.day.month == 9 for e in parsed.entries)


def test_czas_jako_tekst_i_timedelta():
    cells = _september(first_short="5:00")
    cells[date(2026, 9, 3)] = timedelta(hours=7, minutes=30)
    parsed = timesheet.parse_rows([_card(cells)])
    assert parsed is not None
    assert parsed.total_hours == Decimal("172.5")


def test_liczba_zamiast_czasu_to_nie_karta():
    # 0,3333 to ułamek doby albo godziny: nie zgadujemy, MD wpisują Finanse.
    assert timesheet.parse_rows([_card(_september(first_short=0.3333))]) is None


def test_bez_tytulu_tabela_miesieczna_to_nie_karta():
    assert timesheet.parse_rows([_card(_september(), title=False)]) is None


def test_kontrole_z_podpisem_klienta_na_arkuszu():
    parsed = timesheet.parse_rows([_card(_september())])
    assert parsed is not None
    rules = rules_catalog.effective({})
    for key in ("proof.excel_with_mail", "fields.md_hours", "fields.day_limit"):
        rules[key]["level"] = "block"
    result = timesheet.evaluate(
        parsed,
        month="2026-09",
        person_name=PERSON,
        has_mail=False,
        rules=rules,
        working_days=22,
        signed_sheet=True,
    )
    assert result.md_regular == Decimal("21.625")
    assert not result.blocking and not result.warn
    titles = {c["title"] for g in result.groups for c in g["checks"]}
    assert "Godziny zaakceptowane podpisem klienta na arkuszu zbiorczym" in titles
    assert "Imię i nazwisko jak w kontrakcie" in titles


def test_plik_xlsx_z_czasem_excela():
    import openpyxl

    workbook = openpyxl.Workbook()
    sheet = workbook.active
    sheet.title = "09.2026"
    for row in _card(_september()):
        sheet.append(row)
    workbook.create_sheet("SŁOWNIK").append(["KONTRAHENT", "PRACOWNIK BL"])
    buffer = io.BytesIO()
    workbook.save(buffer)
    parsed = timesheet.parse(buffer.getvalue(), timesheet.XLSX)
    assert parsed is not None
    assert parsed.total_hours == Decimal("173")
    assert parsed.consultant == PERSON
