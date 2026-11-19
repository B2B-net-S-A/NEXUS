"""Fikcyjna tabela punktowa w kształcie zał. 5 SWZ Centrum e-Zdrowia (Excel).

Prawdziwych plików klienta nie trzymamy w publicznym repo — ten buduje ten sam
układ: dane osoby, tabelę wymagań „Tak/Nie” i tabelę kryteriów punktowanych
z „Liczbą punktów”, wierszami „Razem” i formułami sum.
"""

from __future__ import annotations

import io

from openpyxl import Workbook


def score_xlsx() -> bytes:
    book = Workbook()
    sheet = book.active
    sheet.title = "Tester automatyczny"
    sheet["A1"] = "Tester automatyczny"
    sheet.merge_cells("A1:D1")
    sheet["A2"] = "Imię i nazwisko:"
    sheet["A3"] = "Firma:"
    sheet["A5"] = "Wymagania obligatoryjne"
    for col, text in enumerate(["Lp", "Oceniany element", "Tak/Nie", "Wynik"], 1):
        sheet.cell(row=6, column=col, value=text)
    yes_no = [
        "Minimum 3 lata doświadczenia w testowaniu oprogramowania;",
        "Znajomość języka SQL;",
    ]
    for offset, text in enumerate(yes_no):
        row = 7 + offset
        sheet.cell(row=row, column=1, value=f"{offset + 1}.")
        sheet.cell(row=row, column=2, value=text)
        sheet.cell(row=row, column=3, value="Tak/Nie")
    sheet["A10"] = "Kryteria punktowane"
    for col, text in enumerate(
        ["Lp", "Oceniany element", "Liczba punktów", "Wynik"], 1
    ):
        sheet.cell(row=11, column=col, value=text)
    scored = [
        (
            "Długość doświadczenia w automatyzacji testów ponad 2 lata przewidziane w OPZ.",
            5,
        ),
        ("Długość doświadczenia z frameworkiem Selenium", 5),
        ("Posiadanie certyfikatu ISTQB na poziomie podstawowym", 3),
    ]
    for offset, (text, points) in enumerate(scored):
        row = 12 + offset
        sheet.cell(row=row, column=1, value=f"{offset + 1}.")
        sheet.cell(row=row, column=2, value=text)
        sheet.cell(row=row, column=3, value=points)
    sheet["B15"] = "Razem:"
    sheet["C15"] = "=SUM(C12:C14)"
    sheet["D15"] = "=SUM(D12:D14)"
    buffer = io.BytesIO()
    book.save(buffer)
    return buffer.getvalue()


def score_xlsx_unheaded_maximum() -> bytes:
    """Układ zał. 5 Testera (19.11.2026): maksimum stoi w kolumnie bez nagłówka,
    a pusta kolumna na wynik nazywa się „Liczba punktów”. Etykiety osoby w
    środku wiersza, legenda obok, pod „Razem” wiersz testu klienta."""
    book = Workbook()
    sheet = book.active
    sheet.title = "Tester"
    sheet["B1"] = "Tester"
    sheet["E2"] = "Firma:"
    sheet["E3"] = "Imię i nazwisko:"
    sheet.merge_cells("F2:H2")
    sheet.merge_cells("F3:H3")
    sheet["A4"] = "Wymagania obligatoryjne"
    sheet.merge_cells("A4:E4")
    for col, text in enumerate(
        ["Lp", "Oceniany element", "Tak/Nie", "Wynik", "Legenda"], 1
    ):
        sheet.cell(row=5, column=col, value=text)
    for offset, text in enumerate(
        ["Minimum 3 lata doświadczenia w testowaniu.", "Znajomość języka SQL;"]
    ):
        row = 6 + offset
        sheet.cell(row=row, column=1, value=f"{offset + 1}.")
        sheet.cell(row=row, column=2, value=text)
        sheet.cell(row=row, column=3, value="Tak/Nie")
        sheet.cell(row=row, column=5, value="Konsultant musi spełniać wymaganie.")
    sheet["A8"] = "Kryteria punktowane"
    sheet.merge_cells("A8:E8")
    # Kolumna C bez nagłówka — to w niej stoją maksima.
    for col, text in {
        1: "Lp",
        2: "Oceniany element",
        4: "Liczba punktów",
        5: "Legenda (punktacja)",
    }.items():
        sheet.cell(row=9, column=col, value=text)
    scored = [
        ("Staż pracy w testowaniu ponad minimum z OPZ", 5),
        ("Doświadczenie w wytwarzaniu dokumentacji testowej", 3),
        ("Doświadczenie w pracy z wtyczką do Jira Xray", 3),
    ]
    for offset, (text, points) in enumerate(scored):
        row = 10 + offset
        sheet.cell(row=row, column=1, value=f"{offset + 1}.")
        sheet.cell(row=row, column=2, value=text)
        sheet.cell(row=row, column=3, value=points)
        sheet.cell(row=row, column=5, value="0 pkt - brak, 1 pkt za każdy rok.")
    sheet["B13"] = "Razem:"
    sheet["C13"] = "=SUM(C10:C12)"
    sheet["D13"] = "=SUM(D10:D12)"
    # Wynik testu wpisuje klient po teście — to nie jest pole dla NEXUSA.
    sheet["B14"] = "Test sprawdzający wiedzę z zakresu wymagań"
    sheet["C14"] = 60
    sheet["E14"] = "Wynik z testu."
    sheet["B15"] = "Razem:"
    sheet["C15"] = "=SUM(C13,C14)"
    buffer = io.BytesIO()
    book.save(buffer)
    return buffer.getvalue()
