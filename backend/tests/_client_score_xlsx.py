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
